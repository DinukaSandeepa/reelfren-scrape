import os
import shutil
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# System Executables
FFMPEG_PATH = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if not os.path.exists(CHROME_PATH):
    # Fallback to system-wide chrome
    CHROME_PATH = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"

# Browser & Cache directories
BROWSER_DATA_DIR = Path.home() / ".cache" / "reelfren_browser"
BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
STEALTH_HEADLESS = os.getenv("STEALTH_HEADLESS", "false").lower() in ("true", "1", "yes")

# Server Settings
HOST = "127.0.0.1"
PORT = 8000
