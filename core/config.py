import os
import json
import shutil
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SETTINGS_FILE = PROJECT_ROOT / "settings.json"

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

# Initial Environment / Default Values
STEALTH_HEADLESS = os.getenv("STEALTH_HEADLESS", "false").lower() in ("true", "1", "yes")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "6"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "eb06d4abfb49dc3eeb1aeb98ae0f581e").strip()
AUTO_UPLOAD_TELEGRAM = os.getenv("AUTO_UPLOAD_TELEGRAM", "true").lower() in ("true", "1", "yes")
DOWNLOAD_CONCURRENCY = int(os.getenv("DOWNLOAD_CONCURRENCY", "4"))

# Server Settings
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))


def load_persistent_settings():
    """Loads settings from settings.json if present, overlaying environment defaults."""
    global STEALTH_HEADLESS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
    global TELEGRAM_API_ID, TELEGRAM_API_HASH, AUTO_UPLOAD_TELEGRAM
    global DOWNLOAD_CONCURRENCY, DOWNLOADS_DIR

    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "stealth_headless" in data:
                STEALTH_HEADLESS = bool(data["stealth_headless"])
            if "telegram_bot_token" in data:
                TELEGRAM_BOT_TOKEN = str(data["telegram_bot_token"]).strip()
            if "telegram_channel_id" in data:
                TELEGRAM_CHANNEL_ID = str(data["telegram_channel_id"]).strip()
            if "telegram_api_id" in data:
                try:
                    TELEGRAM_API_ID = int(data["telegram_api_id"])
                except Exception:
                    pass
            if "telegram_api_hash" in data:
                TELEGRAM_API_HASH = str(data["telegram_api_hash"]).strip()
            if "auto_upload_telegram" in data:
                AUTO_UPLOAD_TELEGRAM = bool(data["auto_upload_telegram"])
            if "download_concurrency" in data:
                try:
                    DOWNLOAD_CONCURRENCY = max(1, int(data["download_concurrency"]))
                except Exception:
                    pass
            if "downloads_dir" in data and data["downloads_dir"]:
                d_path = Path(data["downloads_dir"]).expanduser().resolve()
                d_path.mkdir(parents=True, exist_ok=True)
                DOWNLOADS_DIR = d_path
        except Exception as e:
            print(f"[Config] Error loading settings.json: {e}")


def get_active_config() -> Dict[str, Any]:
    """Returns the current active configuration dictionary."""
    return {
        "stealth_headless": STEALTH_HEADLESS,
        "telegram_bot_token": TELEGRAM_BOT_TOKEN,
        "telegram_channel_id": TELEGRAM_CHANNEL_ID,
        "telegram_api_id": TELEGRAM_API_ID,
        "telegram_api_hash": TELEGRAM_API_HASH,
        "auto_upload_telegram": AUTO_UPLOAD_TELEGRAM,
        "download_concurrency": DOWNLOAD_CONCURRENCY,
        "downloads_dir": str(DOWNLOADS_DIR),
        "ffmpeg_path": FFMPEG_PATH,
        "ffprobe_path": FFPROBE_PATH,
        "host": HOST,
        "port": PORT
    }


def save_persistent_settings(new_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Saves updated settings to settings.json and refreshes global runtime variables."""
    global STEALTH_HEADLESS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
    global TELEGRAM_API_ID, TELEGRAM_API_HASH, AUTO_UPLOAD_TELEGRAM
    global DOWNLOAD_CONCURRENCY, DOWNLOADS_DIR

    if "stealth_headless" in new_settings:
        STEALTH_HEADLESS = bool(new_settings["stealth_headless"])
    if "telegram_bot_token" in new_settings:
        TELEGRAM_BOT_TOKEN = str(new_settings["telegram_bot_token"]).strip()
    if "telegram_channel_id" in new_settings:
        TELEGRAM_CHANNEL_ID = str(new_settings["telegram_channel_id"]).strip()
    if "telegram_api_id" in new_settings:
        try:
            TELEGRAM_API_ID = int(new_settings["telegram_api_id"])
        except Exception:
            pass
    if "telegram_api_hash" in new_settings:
        TELEGRAM_API_HASH = str(new_settings["telegram_api_hash"]).strip()
    if "auto_upload_telegram" in new_settings:
        AUTO_UPLOAD_TELEGRAM = bool(new_settings["auto_upload_telegram"])
    if "download_concurrency" in new_settings:
        try:
            DOWNLOAD_CONCURRENCY = max(1, int(new_settings["download_concurrency"]))
        except Exception:
            pass
    if "downloads_dir" in new_settings and new_settings["downloads_dir"]:
        d_path = Path(new_settings["downloads_dir"]).expanduser().resolve()
        d_path.mkdir(parents=True, exist_ok=True)
        DOWNLOADS_DIR = d_path

    # Persist to settings.json
    data_to_save = {
        "stealth_headless": STEALTH_HEADLESS,
        "telegram_bot_token": TELEGRAM_BOT_TOKEN,
        "telegram_channel_id": TELEGRAM_CHANNEL_ID,
        "telegram_api_id": TELEGRAM_API_ID,
        "telegram_api_hash": TELEGRAM_API_HASH,
        "auto_upload_telegram": AUTO_UPLOAD_TELEGRAM,
        "download_concurrency": DOWNLOAD_CONCURRENCY,
        "downloads_dir": str(DOWNLOADS_DIR),
    }
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=2)

    return get_active_config()


# Load settings on initial import
load_persistent_settings()


