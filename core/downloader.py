import time
import requests
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from core.guide import EpisodeGuide, format_size


class EpisodeDownloader:
    def __init__(
        self,
        guide: EpisodeGuide,
        logger: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, float, str, int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ):
        self.guide = guide
        self.logger = logger or (lambda msg: print(f"[Downloader] {msg}"))
        self.progress_callback = progress_callback
        self.is_cancelled = is_cancelled or (lambda: False)

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

    def download_episode(self, ep_data: Dict[str, Any], max_attempts: int = 3) -> bool:
        """
        Downloads a single episode with multi-attempt retry and size validation.
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
            self.guide.update_episode(ep_num, status="downloaded", file_size=current_size)
            if self.progress_callback:
                self.progress_callback(ep_num, 100.0, "Cached", current_size, current_size)
            return True

        for attempt in range(1, max_attempts + 1):
            if self.is_cancelled():
                return False

            try:
                self.logger(f"Downloading Episode {ep_num} [{quality}] (Attempt {attempt}/{max_attempts})...")
                self.guide.update_episode(ep_num, status="downloading")

                with self.session.get(video_url, stream=True, timeout=20) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))

                    start_time = time.time()
                    downloaded = 0
                    chunk_size = 256 * 1024  # 256 KB chunks

                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if self.is_cancelled():
                                if temp_path.exists():
                                    temp_path.unlink()
                                return False

                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)

                                elapsed = time.time() - start_time
                                speed_val = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                                speed_str = f"{speed_val:.2f} MB/s"
                                pct = (downloaded / total_size * 100) if total_size > 0 else 0.0

                                if self.progress_callback:
                                    self.progress_callback(ep_num, pct, speed_str, downloaded, total_size)

                # Validation: file must exist and have reasonable size
                if temp_path.exists() and temp_path.stat().st_size > 50000:
                    temp_path.replace(local_path)
                    final_size = local_path.stat().st_size
                    self.guide.update_episode(ep_num, status="downloaded", file_size=final_size, error=None)
                    self.logger(f"Finished Episode {ep_num} [{quality}] ({format_size(final_size)})")
                    if self.progress_callback:
                        self.progress_callback(ep_num, 100.0, "Done", final_size, final_size)
                    return True
                else:
                    self.logger(f"Warning: Downloaded file for Episode {ep_num} was empty or too small.")
                    if temp_path.exists():
                        temp_path.unlink()

            except Exception as e:
                self.logger(f"Episode {ep_num} attempt {attempt} failed: {e}")
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                if attempt < max_attempts:
                    time.sleep(attempt * 2)

        self.guide.update_episode(ep_num, status="failed", error="Download failed after retries")
        return False

    def download_all(self, max_retry_sweeps: int = 3) -> bool:
        """
        Downloads all episodes sequentially.
        If any episodes fail, runs dedicated retry sweeps specifically for failed episodes.
        Returns True ONLY if 100% of episodes were successfully downloaded.
        """
        episodes = self.guide.episodes
        total = len(episodes)
        self.logger(f"Commencing download queue for {total} episodes...")

        # 1. First full pass
        for ep in episodes:
            if self.is_cancelled():
                self.logger("Download queue cancelled.")
                return False

            # If already downloaded, skip
            local = Path(ep["local_path"])
            if local.exists() and local.stat().st_size > 50000:
                self.guide.update_episode(ep["episode"], status="downloaded", file_size=local.stat().st_size)
                continue

            self.download_episode(ep)

        # 2. Check for failed episodes and perform targeted retry sweeps
        failed = self.guide.get_failed_episodes()
        if failed:
            for sweep in range(1, max_retry_sweeps + 1):
                if self.is_cancelled():
                    return False

                failed_nums = [e["episode"] for e in failed]
                self.logger(f"⚠️ Retry sweep {sweep}/{max_retry_sweeps} for {len(failed)} failed episode(s): {failed_nums}")

                for ep in failed:
                    if self.is_cancelled():
                        return False
                    self.download_episode(ep)

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
