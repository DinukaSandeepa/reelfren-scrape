import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Callable

from core.config import FFMPEG_PATH
from core.guide import EpisodeGuide


FFPROBE_PATH = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


def get_video_duration(file_path: Path) -> float:
    """Use ffprobe to get precise video duration in seconds."""
    if not file_path.exists() or file_path.stat().st_size < 1000:
        return 0.0
    try:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


class VideoMerger:
    def __init__(self, guide: EpisodeGuide, logger: Optional[Callable[[str], None]] = None):
        self.guide = guide
        self.logger = logger or (lambda msg: print(f"[Merger] {msg}"))

    def merge_episodes(self, output_filename: Optional[str] = None) -> Path:
        """
        Merges all downloaded episodes into a single complete MP4 video.
        STRICT REQUIREMENT: ALL episodes must be present and valid.
        Will ABORT if any episode failed or is missing.
        """
        episodes = self.guide.episodes
        if not episodes:
            raise ValueError("No episodes registered in guide to merge.")

        total_expected = len(episodes)
        missing_eps = []
        valid_files: List[Path] = []

        self.logger(f"Verifying all {total_expected} episodes before merging...")

        for ep in episodes:
            ep_num = ep["episode"]
            path_str = ep.get("local_path")
            if not path_str:
                missing_eps.append(ep_num)
                continue

            file_path = Path(path_str)
            if not file_path.exists() or file_path.stat().st_size < 50000:
                missing_eps.append(ep_num)
                continue

            dur = get_video_duration(file_path)
            if dur <= 0:
                missing_eps.append(ep_num)
                continue

            size = file_path.stat().st_size
            self.guide.update_episode(ep_num, duration=dur, file_size=size, status="downloaded")
            valid_files.append(file_path)

        # STRICT MERGE CHECK
        if missing_eps:
            err_msg = (
                f"Cannot merge drama! {len(missing_eps)} of {total_expected} episodes failed or are missing: "
                f"Episodes {missing_eps}. All episodes must be successfully downloaded before merging."
            )
            self.logger(f"❌ {err_msg}")
            raise RuntimeError(err_msg)

        self.logger(f"✅ Pre-merge verification passed: All {len(valid_files)}/{total_expected} episodes valid.")
        self.logger("Generating episode guide and chapter markers...")
        self.guide.export_text_guide_and_chapters()

        # Output video path
        safe_title = self.guide.drama_title
        out_name = output_filename or f"{safe_title} - Complete.mp4"
        output_path = self.guide.output_dir / out_name

        # Create concat manifest
        concat_list_file = self.guide.output_dir / "concat_list.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for p in valid_files:
                escaped_path = str(p.resolve()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        self.logger(f"Executing lossless FFmpeg concatenation into {out_name}...")

        chapters_file = self.guide.chapters_file
        has_chapters = chapters_file.exists() and chapters_file.stat().st_size > 20

        cmd = [
            FFMPEG_PATH,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file)
        ]

        if has_chapters:
            cmd.extend([
                "-i", str(chapters_file),
                "-map_metadata", "1"
            ])

        cmd.extend([
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path)
        ])

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                self.logger(f"Lossless concat notice (code {res.returncode}): {res.stderr[:200]}")
                self.logger("Attempting fallback re-encoding concat...")
                self._fallback_reencode_merge(valid_files, output_path, chapters_file if has_chapters else None)
        except Exception as e:
            self.logger(f"Concat error: {e}, attempting fallback re-encoding...")
            self._fallback_reencode_merge(valid_files, output_path, chapters_file if has_chapters else None)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Merged video output file was not created successfully.")

        final_size_mb = output_path.stat().st_size / (1024 * 1024)
        self.logger(f"🎉 Successfully created complete merged video: {output_path.name} ({final_size_mb:.2f} MB)")
        return output_path

    def _fallback_reencode_merge(self, valid_files: List[Path], output_path: Path, chapters_file: Optional[Path]) -> None:
        """Fallback when codecs vary slightly."""
        inputs = []
        filter_complex = []
        for idx, file_path in enumerate(valid_files):
            inputs.extend(["-i", str(file_path)])
            filter_complex.append(f"[{idx}:v:0][{idx}:a:0]")

        filter_complex.append(f"concat=n={len(valid_files)}:v=1:a=1[outv][outa]")

        cmd = [FFMPEG_PATH, "-y"]
        cmd.extend(inputs)
        if chapters_file and chapters_file.exists():
            cmd.extend(["-i", str(chapters_file), "-map_metadata", str(len(valid_files))])

        cmd.extend([
            "-filter_complex", "".join(filter_complex),
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path)
        ])

        self.logger("Running fallback re-encode concat...")
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
