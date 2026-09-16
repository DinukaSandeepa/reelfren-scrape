#!/usr/bin/env python3
import sys
import time
import webbrowser
import threading
import uvicorn

from core.config import HOST, PORT, FFMPEG_PATH, CHROME_PATH, DOWNLOADS_DIR


def open_browser():
    """Wait for server to start, then open the Web UI in the default browser."""
    time.sleep(1.2)
    url = f"http://{HOST}:{PORT}"
    print(f"\n🌐 Opening Web UI at: {url}\n")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not automatically open browser: {e}")


def main():
    print("=" * 65)
    print("  🎬 ReelFren Drama Downloader & Lossless FFmpeg Merger")
    print("=" * 65)
    print(f"  • Downloads Directory : {DOWNLOADS_DIR}")
    print(f"  • FFmpeg Binary       : {FFMPEG_PATH}")
    print(f"  • Chrome Executable   : {CHROME_PATH}")
    print(f"  • Web UI Endpoint     : http://{HOST}:{PORT}")
    print("=" * 65)

    # Launch browser opener thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start FastAPI / Uvicorn server
    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
