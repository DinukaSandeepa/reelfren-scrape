import os
import time
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Tuple

from wzgram import Client
from wzgram.errors import FloodWait

from core.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    FFMPEG_PATH,
    FFPROBE_PATH
)

logger = logging.getLogger(__name__)


def probe_video_dimensions_and_duration(video_path: Path) -> Tuple[int, int, int]:
    """
    Extracts (width, height, duration) of video using ffprobe.
    Returns integers suitable for Telegram send_video.
    """
    if not video_path.exists():
        return 0, 0, 0

    try:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration:format=duration",
            "-of", "json",
            str(video_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)

        width = 0
        height = 0
        duration = 0.0

        if "streams" in data and len(data["streams"]) > 0:
            st = data["streams"][0]
            width = int(st.get("width", 0))
            height = int(st.get("height", 0))
            if "duration" in st:
                duration = float(st["duration"])

        if duration <= 0 and "format" in data and "duration" in data["format"]:
            duration = float(data["format"]["duration"])

        return width, height, int(duration)
    except Exception as e:
        logger.warning(f"Failed to probe video metadata: {e}")
        return 0, 0, 0


def generate_telegram_thumbnail(poster_path: Path, output_thumb_path: Path) -> Optional[Path]:
    """
    Converts and scales the drama poster to a Telegram-compatible JPEG thumbnail (max 320x320).
    """
    if not poster_path.exists() or poster_path.stat().st_size == 0:
        return None

    try:
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-i", str(poster_path),
            "-vf", "scale='min(320,iw)':-1",
            "-q:v", "2",
            str(output_thumb_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and output_thumb_path.exists() and output_thumb_path.stat().st_size > 0:
            return output_thumb_path
    except Exception as e:
        logger.warning(f"Error generating thumbnail: {e}")

    return poster_path if poster_path.suffix.lower() in (".jpg", ".jpeg") else None


class TelegramUploader:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        logger_func: Optional[Callable[[str], None]] = None
    ):
        self.bot_token = (bot_token or TELEGRAM_BOT_TOKEN).strip()
        raw_channel = (channel_id or TELEGRAM_CHANNEL_ID).strip()
        self.channel_id = int(raw_channel) if raw_channel.lstrip("-").isdigit() else raw_channel
        self.api_id = api_id or TELEGRAM_API_ID
        self.api_hash = (api_hash or TELEGRAM_API_HASH).strip()
        self.logger = logger_func or (lambda msg: print(f"[Telegram] {msg}"))

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.channel_id)

    async def test_connection(self) -> Dict[str, Any]:
        """Verifies bot credentials and channel access using wzgram."""
        if not self.is_configured():
            raise ValueError("Telegram Bot Token or Channel ID is missing in configuration.")

        app = Client(
            "wzgram_test_session",
            api_id=self.api_id,
            api_hash=self.api_hash,
            bot_token=self.bot_token,
            in_memory=True
        )

        async with app:
            me = await app.get_me()
            chat = await app.get_chat(self.channel_id)
            return {
                "bot_username": me.username,
                "bot_name": me.first_name,
                "channel_title": chat.title,
                "channel_type": str(chat.type)
            }

    async def upload_playable_video(
        self,
        video_path: Path,
        caption: str,
        poster_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[float, str, int, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Uploads a video to the Telegram channel as a NATIVE PLAYABLE STREAMING VIDEO.
        Uses supports_streaming=True, sets width, height, duration, and thumbnail.
        """
        if not self.is_configured():
            raise ValueError("Telegram is not configured. Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID.")

        if not video_path.exists() or video_path.stat().st_size == 0:
            raise FileNotFoundError(f"Video file not found: {video_path}")

        total_bytes = video_path.stat().st_size
        self.logger(f"Preparing upload of {video_path.name} ({total_bytes / (1024*1024):.2f} MB) to channel {self.channel_id} via wzgram...")

        # 1. Probe video metadata for in-app playable rendering
        width, height, duration = probe_video_dimensions_and_duration(video_path)
        self.logger(f"Video specs probed: {width}x{height}, duration: {duration}s")

        # 2. Prepare thumbnail from poster
        thumb_file = None
        if poster_path and poster_path.exists():
            thumb_dest = video_path.parent / "thumb_telegram.jpg"
            thumb_file = generate_telegram_thumbnail(poster_path, thumb_dest)
            if thumb_file:
                self.logger(f"Attached custom video thumbnail from poster: {thumb_file.name}")

        start_time = time.time()
        last_progress_time = 0.0

        def wzgram_progress(current: int, total: int):
            nonlocal last_progress_time
            now = time.time()
            if now - last_progress_time >= 0.5 or current == total:
                last_progress_time = now
                pct = (current / total * 100) if total > 0 else 0.0
                elapsed = now - start_time
                speed_val = (current / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                speed_str = f"{speed_val:.2f} MB/s"

                if progress_callback:
                    progress_callback(pct, speed_str, current, total)

        app = Client(
            "wzgram_upload_session",
            api_id=self.api_id,
            api_hash=self.api_hash,
            bot_token=self.bot_token,
            in_memory=True
        )

        try:
            async with app:
                self.logger("Connected to Telegram MTProto via wzgram. Beginning video stream upload...")
                msg = await app.send_video(
                    chat_id=self.channel_id,
                    video=str(video_path),
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=str(thumb_file) if thumb_file and thumb_file.exists() else None,
                    supports_streaming=True,  # Crucial: Playable in Telegram, not document!
                    progress=wzgram_progress
                )

                self.logger(f"🎉 Successfully uploaded playable video to Telegram! (Message ID: {msg.id})")
                return {
                    "success": True,
                    "message_id": msg.id,
                    "chat_id": str(self.channel_id),
                    "file_id": msg.video.file_id if msg.video else None,
                }
        except FloodWait as fw:
            self.logger(f"Telegram FloodWait: Required to wait {fw.value} seconds.")
            await asyncio.sleep(fw.value)
            # Retry once after flood wait
            async with app:
                msg = await app.send_video(
                    chat_id=self.channel_id,
                    video=str(video_path),
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=str(thumb_file) if thumb_file and thumb_file.exists() else None,
                    supports_streaming=True,
                    progress=wzgram_progress
                )
                return {"success": True, "message_id": msg.id}
        except Exception as e:
            self.logger(f"❌ Telegram upload failed: {e}")
            raise
