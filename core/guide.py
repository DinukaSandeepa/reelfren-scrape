import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Any


def natural_sort_key(s: str) -> List[Any]:
    """Helper for natural sorting strings containing numbers (e.g. 'EP 2' before 'EP 10')."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filesystem filenames."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return re.sub(r'\s+', ' ', cleaned) or "drama"


def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS format."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def format_size(bytes_val: int) -> str:
    """Format bytes into human-readable MB / GB string."""
    if bytes_val <= 0:
        return "0 MB"
    mb = bytes_val / (1024 * 1024)
    if mb >= 1000:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


class EpisodeGuide:
    def __init__(self, drama_title: str, drama_url: str, output_dir: Path):
        self.drama_title = sanitize_filename(drama_title)
        self.drama_url = drama_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_dir = self.output_dir / "episodes"
        self.episodes_dir.mkdir(parents=True, exist_ok=True)
        
        self.guide_file = self.output_dir / "episode_guide.json"
        self.text_guide_file = self.output_dir / "episode_guide.txt"
        self.chapters_file = self.output_dir / "chapters.txt"
        
        self.episodes: List[Dict[str, Any]] = []
        self.load()

    def set_episodes(self, raw_episodes: List[Dict[str, Any]]) -> None:
        """
        Takes raw episode list, sorts them naturally, and updates guide.
        Preserves existing downloaded files and video URLs.
        """
        sorted_eps = sorted(raw_episodes, key=lambda x: (x.get("episode", 0), natural_sort_key(x.get("title", ""))))
        
        existing_map = {e["episode"]: e for e in self.episodes}
        merged_list = []
        for ep_data in sorted_eps:
            ep_num = ep_data["episode"]
            existing = existing_map.get(ep_num, {})
            
            filename = f"ep_{ep_num:03d}.mp4"
            local_path = str(self.episodes_dir / filename)
            
            # Check if file exists on disk
            file_exists = Path(local_path).exists() and Path(local_path).stat().st_size > 50000
            file_size = Path(local_path).stat().st_size if file_exists else existing.get("file_size", 0)
            status = "downloaded" if file_exists else existing.get("status", "pending")

            merged_list.append({
                "episode": ep_num,
                "title": ep_data.get("title", f"EP {ep_num}"),
                "watch_url": ep_data.get("watch_url", ""),
                "video_url": ep_data.get("video_url") or existing.get("video_url"),
                "quality": ep_data.get("quality") or existing.get("quality", "1080p"),
                "local_path": local_path,
                "file_size": file_size,
                "duration": existing.get("duration", 0.0),
                "status": status,
                "error": None if file_exists else existing.get("error", None)
            })
            
        self.episodes = merged_list
        self.save()

    def update_episode(self, episode_num: int, **kwargs) -> None:
        for ep in self.episodes:
            if ep["episode"] == episode_num:
                ep.update(kwargs)
                break
        self.save()

    def get_failed_episodes(self) -> List[Dict[str, Any]]:
        """Returns list of episodes that are not yet downloaded successfully."""
        failed = []
        for ep in self.episodes:
            local = Path(ep.get("local_path", ""))
            if ep.get("status") != "downloaded" or not local.exists() or local.stat().st_size < 50000:
                failed.append(ep)
        return failed

    def save(self) -> None:
        data = {
            "drama_title": self.drama_title,
            "drama_url": self.drama_url,
            "total_episodes": len(self.episodes),
            "episodes": self.episodes
        }
        with open(self.guide_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self) -> None:
        if self.guide_file.exists():
            try:
                with open(self.guide_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.episodes = data.get("episodes", [])
            except Exception:
                self.episodes = []

    def export_text_guide_and_chapters(self) -> None:
        """
        Creates human-readable text guide and FFMPEG metadata chapters file.
        """
        current_time = 0.0
        txt_lines = [
            f"============================================================",
            f" DRAMA EPISODE GUIDE: {self.drama_title}",
            f" URL: {self.drama_url}",
            f" Total Episodes: {len(self.episodes)}",
            f"============================================================\n",
            f"{'Episode':<10} | {'Quality':<8} | {'Duration':<10} | {'Time Range':<22} | {'Size':<10} | {'Status'}",
            f"{'-'*10}-|-{'-'*8}-|-{'-'*10}-|-{'-'*22}-|-{'-'*10}-|-{'-'*10}"
        ]
        
        ffmpeg_chapters = [";FFMETADATA1\n"]
        
        for ep in self.episodes:
            ep_num = ep["episode"]
            quality = ep.get("quality", "1080p")
            dur = float(ep.get("duration", 0.0))
            size_str = format_size(ep.get("file_size", 0))
            status = ep.get("status", "unknown")
            
            start_fmt = format_timestamp(current_time)
            end_time = current_time + dur
            end_fmt = format_timestamp(end_time)
            dur_fmt = f"{int(dur // 60)}m {int(dur % 60):02d}s" if dur > 0 else "--"
            time_range = f"{start_fmt} - {end_fmt}" if dur > 0 else "--"
            
            txt_lines.append(f"EP {ep_num:<7} | {quality:<8} | {dur_fmt:<10} | {time_range:<22} | {size_str:<10} | {status}")
            
            if dur > 0:
                start_ms = int(current_time * 1000)
                end_ms = int(end_time * 1000)
                ffmpeg_chapters.append(
                    f"[CHAPTER]\n"
                    f"TIMEBASE=1/1000\n"
                    f"START={start_ms}\n"
                    f"END={end_ms}\n"
                    f"title=Episode {ep_num}\n"
                )
            
            current_time = end_time
            
        with open(self.text_guide_file, "w", encoding="utf-8") as f:
            f.write("\n".join(txt_lines) + "\n")
            
        with open(self.chapters_file, "w", encoding="utf-8") as f:
            f.write("\n".join(ffmpeg_chapters) + "\n")
