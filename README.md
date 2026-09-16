# 🎬 ReelFren Drama Downloader, Merger & Telegram Uploader

A specialized automation tool and modern web dashboard to scrape, download, and losslessly merge dramas from [reelfren.com](https://reelfren.com/) into a single, seamless `.mp4` video with chapter markers and an episode guide, plus automatic upload to your Telegram channel via **wzgram**.

---

## 🌟 Key Features

1. **Python Web UI**: Sleek, modern dark-mode dashboard built with FastAPI, Tailwind CSS, and Server-Sent Events (SSE) for live real-time progress updates.
2. **Headed Cloudflare Turnstile Handling**:
   - Uses **Camoufox** stealth browser session with organic humanized movements.
   - Automatically detects and clicks the Turnstile verification checkbox.
3. **Episode Guide Generator & 1080p Highest Quality**:
   - Discovers all episodes from both the page grid and backend API.
   - Always selects **1080p Ultra HD** direct streams.
   - Natural numerical sorting (`EP 1`, `EP 2`, ..., `EP 10`, `EP 20`).
4. **Direct High-Speed MP4 Downloader**:
   - Sequential downloads with resume capability.
   - Multi-sweep targeted retry mechanism for failed episodes.
5. **Lossless FFmpeg Merging**:
   - Merges all episodes in seconds without re-encoding (`-c copy`).
   - Injects chapter metadata (`Episode 1`, `Episode 2`, ...) into the output file.
   - **Strict Merge Guard**: strictly prevents merging if any episode failed or is missing.
6. **Telegram Channel Auto-Uploader ([wzgram](https://wzgram.com/))**:
   - Uploads the merged drama directly to your Telegram channel via MTProto.
   - **Playable Video**: Uploads as native in-app streaming video (`supports_streaming=True`), **NOT as a document**.
   - **Poster as Thumbnail**: Automatically downloads the drama's official cover poster (`og:image`) and sets it as the video thumbnail.
   - Real-time upload progress bar and speed in the Web UI.

---

## 🚀 Quick Start

### 1. Requirements
- **Python 3.10+** (tested on Python 3.13)
- **FFmpeg & FFprobe** (`brew install ffmpeg`)

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Telegram Configuration (`.env`)
Create or edit `.env` in the project root:
```env
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHANNEL_ID="your_channel_id"
TELEGRAM_API_ID=6
TELEGRAM_API_HASH="eb06d4abfb49dc3eeb1aeb98ae0f581e"
AUTO_UPLOAD_TELEGRAM=true
STEALTH_HEADLESS=false
```

### 4. Run the Application
```bash
python3 run.py
```
Open `http://127.0.0.1:8000`.

---

## 📖 Usage Walkthrough

1. Paste any ReelFren drama URL into the input field:
   ```
   https://reelfren.com/drama/dramabox/42000023802-he-broke-the-heart-that-saved-him?lang=en
   ```
2. Toggle "Auto-upload to Telegram Channel" (enabled by default).
3. Click **Start Process**.
4. The system:
   - Auto-bypasses Cloudflare Turnstile with Camoufox.
   - Extracts all episodes in 1080p.
   - Downloads all episodes with retry sweeps.
   - Merges them losslessly with FFmpeg and chapter markers.
   - Uploads the complete drama directly to your Telegram channel as a playable video with the drama's poster as thumbnail!
