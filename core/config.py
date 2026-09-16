import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# System Executables
FFMPEG_PATH = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"

# Browser & Cache directories
BROWSER_DATA_DIR = Path.home() / ".cache" / "reelfren_browser"
BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
STEALTH_HEADLESS = os.getenv("STEALTH_HEADLESS", "false").lower() in ("true", "1", "yes")

# Telegram & wzgram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "6"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "eb06d4abfb49dc3eeb1aeb98ae0f581e").strip()
AUTO_UPLOAD_TELEGRAM = os.getenv("AUTO_UPLOAD_TELEGRAM", "true").lower() in ("true", "1", "yes")

# Downloader Settings
DOWNLOAD_CONCURRENCY = int(os.getenv("DOWNLOAD_CONCURRENCY", "4"))

# Server Settings
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

