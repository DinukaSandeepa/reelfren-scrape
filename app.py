import os
import sys
import json
import time
import uuid
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import PROJECT_ROOT, DOWNLOADS_DIR, HOST, PORT
from core.guide import EpisodeGuide
from core.scraper import ReelFrenScraper
from core.downloader import EpisodeDownloader
from core.merger import VideoMerger


app = FastAPI(title="ReelFren Downloader & Merger")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATES_DIR = PROJECT_ROOT / "templates"


class JobState:
    def __init__(self, job_id: str, drama_url: str):
        self.job_id = job_id
        self.drama_url = drama_url
        self.drama_title = ""
        self.status = "starting"  # starting, turnstile_wait, scraping, downloading, merging, completed, failed, cancelled
        self.status_message = "Initializing job..."
        self.logs: List[str] = []
        self.episodes: List[Dict[str, Any]] = []
        self.failed_episodes: List[int] = []
        self.current_episode = 0
        self.download_speed = "0.0 MB/s"
        self.episode_progress = 0.0
        self.overall_progress = 0.0
        self.merge_status = "Pending"
        self.output_video: Optional[str] = None
        self.output_dir: Optional[str] = None

        self.cancelled = False
        self.turnstile_verified = False
        self.active_scraper: Optional[ReelFrenScraper] = None
        self.guide: Optional[EpisodeGuide] = None

    def add_log(self, msg: str):
        self.logs.append(msg)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "drama_url": self.drama_url,
            "drama_title": self.drama_title,
            "status": self.status,
            "status_message": self.status_message,
            "logs": self.logs,
            "episodes": self.episodes,
            "failed_episodes": self.failed_episodes,
            "current_episode": self.current_episode,
            "download_speed": self.download_speed,
            "episode_progress": self.episode_progress,
            "overall_progress": self.overall_progress,
            "merge_status": self.merge_status,
            "output_video": self.output_video,
            "output_dir": self.output_dir,
        }


# Global store for jobs
jobs: Dict[str, JobState] = {}


class StartJobRequest(BaseModel):
    drama_url: str


class FolderRequest(BaseModel):
    folder_path: Optional[str] = None


class PlayRequest(BaseModel):
    video_path: Optional[str] = None


def run_pipeline(job: JobState):
    """Background worker executing the full scrape -> download -> strict merge flow."""
    job.add_log(f"Starting process for drama URL: {job.drama_url}")

    scraper = None
    try:
        # STEP 1: Browser Launch & Cloudflare Turnstile
        job.status = "turnstile_wait"
        job.status_message = "Resolving Cloudflare Turnstile in stealth browser..."
        job.overall_progress = 5.0

        def scraper_event(evt_type: str, data: Any):
            if evt_type == "status":
                job.status_message = str(data)
            elif evt_type == "turnstile_verified":
                job.turnstile_verified = True
                job.add_log("Cloudflare Turnstile verification passed.")
            elif evt_type == "episodes_loaded":
                job.episodes = data
                job.status = "scraping"
                job.status_message = f"Found {len(data)} episodes. Resolving highest quality streams..."
                job.overall_progress = 20.0

        scraper = ReelFrenScraper(
            drama_url=job.drama_url,
            logger=job.add_log,
            event_callback=scraper_event,
            is_cancelled=lambda: job.cancelled,
            is_verified=lambda: job.turnstile_verified
        )
        job.active_scraper = scraper

        guide = scraper.scrape_and_setup()
        job.guide = guide
        job.drama_title = guide.drama_title
        job.output_dir = str(guide.output_dir)
        job.episodes = guide.episodes

        if job.cancelled:
            job.status = "cancelled"
            job.status_message = "Process was cancelled."
            return

        total_eps = len(guide.episodes)
        if total_eps == 0:
            raise RuntimeError("No episodes were found to download.")

        job.add_log(f"Episode guide initialized: {total_eps} episodes identified in highest quality.")
        job.overall_progress = 30.0

        # STEP 2: Downloader with Multi-Round Retries
        job.status = "downloading"
        job.status_message = f"Downloading {total_eps} episodes in highest quality..."

        def on_dl_progress(ep_num: int, pct: float, speed: str, downloaded: int, total: int):
            job.current_episode = ep_num
            job.episode_progress = pct
            job.download_speed = speed

            completed_eps = sum(1 for e in guide.episodes if e.get("status") == "downloaded")
            fraction = (completed_eps + (pct / 100.0)) / total_eps
            job.overall_progress = 30.0 + (fraction * 55.0)
            job.status_message = f"Downloading Episode {ep_num} ({completed_eps}/{total_eps})..."
            job.episodes = guide.episodes

        downloader = EpisodeDownloader(
            guide=guide,
            logger=job.add_log,
            progress_callback=on_dl_progress,
            is_cancelled=lambda: job.cancelled
        )

        all_downloaded = downloader.download_all()
        job.episodes = guide.episodes

        if job.cancelled:
            job.status = "cancelled"
            job.status_message = "Download cancelled."
            return

        # STRICT VERIFICATION: CANNOT MERGE IF ANY EPISODE FAILED
        failed_eps = guide.get_failed_episodes()
        if not all_downloaded or failed_eps:
            job.failed_episodes = [e["episode"] for e in failed_eps]
            job.status = "failed"
            job.merge_status = "Blocked"
            err_msg = f"Cannot merge: {len(failed_eps)} episode(s) failed or missing: {job.failed_episodes}."
            job.status_message = err_msg
            job.add_log(f"❌ {err_msg} All episodes must be successfully downloaded before merging.")
            return

        job.overall_progress = 85.0

        # STEP 3: Merging with FFmpeg
        job.status = "merging"
        job.status_message = "All episodes verified! Merging with FFmpeg concat demuxer..."
        job.merge_status = "In Progress"
        job.add_log("Starting lossless FFmpeg concatenation with chapter markers...")

        merger = VideoMerger(guide=guide, logger=job.add_log)
        output_file = merger.merge_episodes()

        job.output_video = str(output_file)
        job.status = "completed"
        job.status_message = f"All {total_eps} episodes downloaded in highest quality and merged!"
        job.merge_status = "Completed"
        job.overall_progress = 100.0
        job.add_log(f"🎉 Process Complete! Output: {output_file.name}")

    except Exception as e:
        job.status = "failed"
        job.status_message = f"Error: {str(e)}"
        job.add_log(f"Pipeline error: {str(e)}")
    finally:
        if scraper:
            scraper.close()


def run_retry_pipeline(job: JobState):
    """Retries downloading only failed episodes, then proceeds to merge."""
    guide = job.guide
    if not guide:
        job.status = "failed"
        job.status_message = "No guide available to retry."
        return

    job.status = "downloading"
    job.status_message = "Retrying failed episodes..."
    job.add_log("Retrying failed episodes...")

    total_eps = len(guide.episodes)

    def on_dl_progress(ep_num: int, pct: float, speed: str, downloaded: int, total: int):
        job.current_episode = ep_num
        job.episode_progress = pct
        job.download_speed = speed
        completed_eps = sum(1 for e in guide.episodes if e.get("status") == "downloaded")
        fraction = (completed_eps + (pct / 100.0)) / total_eps
        job.overall_progress = 30.0 + (fraction * 55.0)
        job.status_message = f"Retrying Episode {ep_num} ({completed_eps}/{total_eps})..."
        job.episodes = guide.episodes

    downloader = EpisodeDownloader(
        guide=guide,
        logger=job.add_log,
        progress_callback=on_dl_progress,
        is_cancelled=lambda: job.cancelled
    )

    all_downloaded = downloader.download_all()
    job.episodes = guide.episodes

    failed_eps = guide.get_failed_episodes()
    if not all_downloaded or failed_eps:
        job.failed_episodes = [e["episode"] for e in failed_eps]
        job.status = "failed"
        job.merge_status = "Blocked"
        err_msg = f"Cannot merge: {len(failed_eps)} episode(s) still failed: {job.failed_episodes}."
        job.status_message = err_msg
        job.add_log(f"❌ {err_msg}")
        return

    job.failed_episodes = []
    job.status = "merging"
    job.status_message = "All episodes successfully recovered! Merging with FFmpeg..."
    job.merge_status = "In Progress"

    try:
        merger = VideoMerger(guide=guide, logger=job.add_log)
        output_file = merger.merge_episodes()

        job.output_video = str(output_file)
        job.status = "completed"
        job.status_message = f"All {total_eps} episodes downloaded and merged!"
        job.merge_status = "Completed"
        job.overall_progress = 100.0
        job.add_log(f"🎉 Retry succeeded! Complete output: {output_file.name}")
    except Exception as e:
        job.status = "failed"
        job.status_message = f"Merge error: {e}"
        job.add_log(f"Merge error: {e}")


@app.get("/", response_class=HTMLResponse)
def get_index():
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/start")
def start_job(req: StartJobRequest):
    if not req.drama_url or not req.drama_url.startswith("http"):
        raise HTTPException(status_code=400, detail="A valid drama URL is required.")

    job_id = str(uuid.uuid4())[:8]
    job = JobState(job_id=job_id, drama_url=req.drama_url)
    jobs[job_id] = job

    thread = threading.Thread(target=run_pipeline, args=(job,), daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "started"}


@app.post("/api/retry/{job_id}")
def retry_failed_episodes(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job.status not in ("failed", "incomplete"):
        raise HTTPException(status_code=400, detail="Job is not in a failed state.")

    job.cancelled = False
    thread = threading.Thread(target=run_retry_pipeline, args=(job,), daemon=True)
    thread.start()

    return {"status": "retrying", "job_id": job_id}


@app.get("/api/events/{job_id}")
def sse_events(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    def event_stream():
        while True:
            data_dict = job.to_dict()
            yield f"data: {json.dumps(data_dict)}\n\n"

            if job.status in ("completed", "cancelled"):
                time.sleep(0.5)
                yield f"data: {json.dumps(job.to_dict())}\n\n"
                break

            time.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/verify/{job_id}")
def verify_turnstile(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs[job_id].turnstile_verified = True
    jobs[job_id].add_log("Manual Turnstile verification trigger received.")
    return {"status": "ok"}


@app.post("/api/cancel/{job_id}")
def cancel_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    job.cancelled = True
    job.status = "cancelled"
    job.status_message = "Cancelled by user"
    job.add_log("Job cancellation requested by user.")
    if job.active_scraper:
        job.active_scraper.close()
    return {"status": "cancelled"}


@app.post("/api/open-folder")
def open_folder(req: FolderRequest):
    folder = req.folder_path or str(DOWNLOADS_DIR)
    if os.path.exists(folder):
        if sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        elif sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", folder])
        return {"status": "opened", "path": folder}
    raise HTTPException(status_code=404, detail="Folder does not exist")


@app.post("/api/play-video")
def play_video(req: PlayRequest):
    if req.video_path and os.path.exists(req.video_path):
        if sys.platform == "darwin":
            subprocess.Popen(["open", req.video_path])
        elif sys.platform == "win32":
            os.startfile(req.video_path)
        else:
            subprocess.Popen(["xdg-open", req.video_path])
        return {"status": "playing", "path": req.video_path}
    raise HTTPException(status_code=404, detail="Video file does not exist")
