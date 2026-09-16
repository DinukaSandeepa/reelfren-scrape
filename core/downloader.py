import re
import time
import subprocess
import requests
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.config import FFMPEG_PATH, FFPROBE_PATH, DOWNLOAD_CONCURRENCY
from core.guide import EpisodeGuide, format_size
from core.merger import get_video_duration


def is_hls_url(url: str) -> bool:
    """Checks whether a video URL is an HLS playlist."""
    u = url.lower()
    return ".m3u8" in u or ".m3u" in u


class EpisodeDownloader:
    def __init__(
        self,
        guide: EpisodeGuide,
        logger: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, float, str, int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        concurrency: int = DOWNLOAD_CONCURRENCY,
    ):
        self.guide = guide
        self.logger = logger or (lambda msg: print(f"[Downloader] {msg}"))
        self.progress_callback = progress_callback
        self.is_cancelled = is_cancelled or (lambda: False)
        self.concurrency = max(1, concurrency)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) "
                "Gecko/20100101 Firefox/130.0"
            ),
            "Referer": "https://reelfren.com/",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive"
        })

    def _download_hls(
        self,
        video_url: str,
        temp_path: Path,
        ep_num: int,
        quality: str
    ) -> bool:
        """
        Downloads an HLS stream (.m3u8) using FFmpeg with multi-connection parallel segment
        streaming (-http_multiple 1 -http_persistent 1) without re-encoding (-c copy),
        preserving native 1080p stream quality and tracking real-time progress.
        """
        # 1. Parse M3U8 playlist to estimate total duration
        estimated_duration = 0.0
        try:
            r = self.session.get(video_url, timeout=10)
            if r.status_code == 200:
                extinfs = re.findall(r"#EXTINF:([0-9.]+)", r.text)
                if extinfs:
                    estimated_duration = sum(float(x) for x in extinfs)
        except Exception:
            pass

        # 2. Prepare FFmpeg command with headers and multi-connection acceleration
        headers = (
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0\r\n"
            "Referer: https://reelfren.com/\r\n"
        )
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-headers", headers,
            "-http_multiple", "1",
            "-http_persistent", "1",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", video_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            "-f", "mp4",
            "-loglevel", "error",
            "-progress", "pipe:1",
            str(temp_path)
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        try:
            current_speed = "0.0 MB/s"
            out_time_sec = 0.0

            for line in iter(proc.stdout.readline, ""):
                if self.is_cancelled():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    if temp_path.exists():
                        temp_path.unlink()
                    return False

                line = line.strip()
                if not line:
                    continue

                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()

                    if k == "out_time_us":
                        try:
                            out_time_sec = float(v) / 1_000_000.0
                        except ValueError:
                            pass
                    elif k == "speed":
                        current_speed = v
                    elif k == "progress":
                        if v == "end":
                            break
                        # Fire progress callback once per FFmpeg report block
                        if self.progress_callback:
                            curr_size = temp_path.stat().st_size if temp_path.exists() else 0
                            if estimated_duration > 0:
                                pct = min(99.0, (out_time_sec / estimated_duration) * 100.0)
                                est_total = int(curr_size / (pct / 100.0)) if pct > 5 else curr_size
                            else:
                                pct = 50.0
                                est_total = curr_size
                            self.progress_callback(ep_num, pct, current_speed, curr_size, est_total)

            proc.stdout.close()
            return_code = proc.wait(timeout=30)
            if return_code != 0:
                stderr_output = proc.stderr.read()
                proc.stderr.close()
                raise RuntimeError(f"FFmpeg exited with code {return_code}: {stderr_output.strip()[-300:]}")

            proc.stderr.close()
            return True

        except Exception as e:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            raise e

    def _download_http(
        self,
        video_url: str,
        temp_path: Path,
        ep_num: int,
        quality: str
    ) -> bool:
        """
        Downloads a direct video file (e.g. MP4) using HTTP streaming chunks.
        If the response is detected to be an HLS playlist, automatically hands off to _download_hls.
        """
        with self.session.get(video_url, stream=True, timeout=25) as response:
            response.raise_for_status()

            # Dynamic check: Did the server return an HLS manifest instead of an MP4?
            content_type = response.headers.get("content-type", "").lower()
            if "mpegurl" in content_type or "m3u8" in content_type:
                self.logger(f"Detected HLS playlist content-type ({content_type}). Routing to FFmpeg HLS stream engine...")
                return self._download_hls(video_url, temp_path, ep_num, quality)

            total_size = int(response.headers.get("content-length", 0))
            start_time = time.time()
            downloaded = 0
            chunk_size = 256 * 1024  # 256 KB chunks
            first_chunk = True
            hls_redirect = False

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if self.is_cancelled():
                        if temp_path.exists():
                            temp_path.unlink()
                        return False

                    if chunk:
                        # Check first chunk for #EXTM3U manifest header
                        if first_chunk:
                            first_chunk = False
                            if chunk.strip().startswith(b"#EXTM3U"):
                                self.logger("Detected #EXTM3U stream signature in body. Routing to FFmpeg HLS stream engine...")
                                hls_redirect = True
                                break

                        f.write(chunk)
                        downloaded += len(chunk)

                        elapsed = time.time() - start_time
                        speed_val = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        speed_str = f"{speed_val:.2f} MB/s"
                        pct = (downloaded / total_size * 100) if total_size > 0 else 0.0

                        if self.progress_callback:
                            self.progress_callback(ep_num, pct, speed_str, downloaded, total_size)

            if hls_redirect:
                if temp_path.exists():
                    temp_path.unlink()
                return self._download_hls(video_url, temp_path, ep_num, quality)

        return True

    def download_episode(self, ep_data: Dict[str, Any], max_attempts: int = 3) -> bool:
        """
        Downloads a single episode with automatic protocol selection (Direct MP4 vs. HLS m3u8),
        multi-attempt retry, and strict size validation.
        """
        ep_num = ep_data["episode"]
        video_url = ep_data.get("video_url")
        local_path = Path(ep_data["local_path"])
        quality = ep_data.get("quality", "1080p")

        if not video_url:
            self.logger(f"Error: Episode {ep_num} has no video URL to download.")
            self.guide.update_episode(ep_num, status="failed", error="No video URL")
            return False

        if self.is_cancelled():
            return False

        temp_path = local_path.with_suffix(".part")

        # Check existing complete file
        if local_path.exists() and local_path.stat().st_size > 50000:
            current_size = local_path.stat().st_size
            dur = ep_data.get("duration", 0.0)
            if dur <= 0:
                dur = get_video_duration(local_path)
            self.guide.update_episode(ep_num, status="downloaded", file_size=current_size, duration=dur)
            if self.progress_callback:
                self.progress_callback(ep_num, 100.0, "Cached", current_size, current_size)
            return True

        for attempt in range(1, max_attempts + 1):
            if self.is_cancelled():
                return False

            try:
                self.logger(f"Downloading Episode {ep_num} [{quality}] (Attempt {attempt}/{max_attempts})...")
                self.guide.update_episode(ep_num, status="downloading")

                # Route according to stream protocol
                if is_hls_url(video_url):
                    self._download_hls(video_url, temp_path, ep_num, quality)
                else:
                    self._download_http(video_url, temp_path, ep_num, quality)

                if self.is_cancelled():
                    if temp_path.exists():
                        temp_path.unlink()
                    return False

                # Strict validation: file must exist and have reasonable media size (> 50KB)
                if not temp_path.exists() or temp_path.stat().st_size <= 50000:
                    curr_size = temp_path.stat().st_size if temp_path.exists() else 0
                    if temp_path.exists():
                        temp_path.unlink()
                    raise RuntimeError(f"Downloaded file for Episode {ep_num} was empty or too small ({curr_size} bytes, expected > 50KB)")

                # Move verified part file to final path
                temp_path.replace(local_path)
                final_size = local_path.stat().st_size

                # Auto-detect exact media duration via ffprobe
                dur = get_video_duration(local_path)
                self.guide.update_episode(
                    ep_num,
                    status="downloaded",
                    file_size=final_size,
                    duration=dur if dur > 0 else ep_data.get("duration", 0.0),
                    error=None
                )
                self.logger(f"Finished Episode {ep_num} [{quality}] ({format_size(final_size)})")
                if self.progress_callback:
                    self.progress_callback(ep_num, 100.0, "Done", final_size, final_size)
                return True

            except Exception as e:
                self.logger(f"Episode {ep_num} attempt {attempt} failed: {e}")
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                if attempt < max_attempts and not self.is_cancelled():
                    time.sleep(attempt * 2)

        self.guide.update_episode(ep_num, status="failed", error="Download failed after retries")
        return False

    def download_all(self, max_retry_sweeps: int = 3, concurrency: Optional[int] = None) -> bool:
        """
        Downloads all episodes concurrently using a thread pool.
        If any episodes fail, runs dedicated retry sweeps specifically for failed episodes.
        Returns True ONLY if 100% of episodes were successfully downloaded.
        """
        workers = concurrency or self.concurrency
        episodes = self.guide.episodes
        total = len(episodes)
        self.logger(f"Commencing parallel download queue for {total} episodes (concurrency={workers})...")

        # 1. Filter episodes that need download
        to_download = []
        for ep in episodes:
            if self.is_cancelled():
                self.logger("Download queue cancelled.")
                return False

            local = Path(ep["local_path"])
            if local.exists() and local.stat().st_size > 50000:
                dur = ep.get("duration", 0.0)
                if dur <= 0:
                    dur = get_video_duration(local)
                self.guide.update_episode(ep["episode"], status="downloaded", file_size=local.stat().st_size, duration=dur)
            else:
                to_download.append(ep)

        # 2. Parallel First Pass
        if to_download:
            self.logger(f"Dispatching {len(to_download)} episodes across {workers} parallel download workers...")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self.download_episode, ep): ep["episode"]
                    for ep in to_download
                }
                for future in as_completed(futures):
                    if self.is_cancelled():
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.logger("Download queue cancelled.")
                        return False
                    try:
                        future.result()
                    except Exception as e:
                        ep_n = futures[future]
                        self.logger(f"Episode {ep_n} unhandled worker exception: {e}")

        # 3. Check for failed episodes and perform targeted retry sweeps
        failed = self.guide.get_failed_episodes()
        if failed:
            for sweep in range(1, max_retry_sweeps + 1):
                if self.is_cancelled():
                    return False

                failed_nums = [e["episode"] for e in failed]
                self.logger(f"⚠️ Retry sweep {sweep}/{max_retry_sweeps} for {len(failed)} failed episode(s): {failed_nums}")

                sweep_workers = min(workers, len(failed))
                with ThreadPoolExecutor(max_workers=sweep_workers) as executor:
                    futures = {
                        executor.submit(self.download_episode, ep): ep["episode"]
                        for ep in failed
                    }
                    for future in as_completed(futures):
                        if self.is_cancelled():
                            executor.shutdown(wait=False, cancel_futures=True)
                            return False
                        try:
                            future.result()
                        except Exception as e:
                            ep_n = futures[future]
                            self.logger(f"Episode {ep_n} retry unhandled exception: {e}")

                failed = self.guide.get_failed_episodes()
                if not failed:
                    self.logger("All previously failed episodes were successfully recovered!")
                    break

        # Final verification
        final_failed = self.guide.get_failed_episodes()
        if final_failed:
            failed_nums = [e["episode"] for e in final_failed]
            self.logger(f"❌ Download incomplete! {len(final_failed)} episode(s) failed: {failed_nums}")
            return False

        self.logger(f"✅ Download complete: All {total} episodes successfully verified on disk.")
        return True

