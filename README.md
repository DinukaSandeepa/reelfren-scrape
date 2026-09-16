# 🎬 ReelFren Drama Downloader & Merger

A specialized automation tool and modern web dashboard to scrape, download, and losslessly merge dramas from [reelfren.com](https://reelfren.com/) into a single, seamless `.mp4` video with chapter markers and an episode guide.

---

## 🌟 Key Features

1. **Python Web UI**: Sleek, modern dark-mode dashboard built with FastAPI, Tailwind CSS, and Server-Sent Events (SSE) for live real-time progress updates.
2. **Headed Cloudflare Turnstile Handling**:
   - Opens a headed Google Chrome window with stealth browser patches.
   - Allows the user to complete the Cloudflare Turnstile human verification check directly in the browser.
   - Automatically detects verification completion (or provides a manual 1-click confirmation) and starts the download pipeline.
3. **Episode Guide Generator**:
   - Discovers all episodes from the drama's `.episode-grid`.
   - Uses natural numerical sorting (`EP 1`, `EP 2`, ..., `EP 10`, `EP 20`).
   - Generates machine-readable `episode_guide.json` and human-readable `episode_guide.txt` with exact time ranges and file sizes.
4. **Direct High-Speed MP4 Downloader**:
   - Resolves direct CDN stream URLs (`*.dramaboxdb.com`).
   - Streaming downloads with resume capability (skips already downloaded files).
   - Real-time download speed and per-episode progress reporting.
5. **Lossless FFmpeg Merging**:
   - Uses FFmpeg concat demuxer (`-c copy`) to merge all episodes in seconds without re-encoding or quality degradation.
   - Injects chapter metadata (`Episode 1`, `Episode 2`, ...) into the output file for seamless scrubbing in media players.
   - Generates output video named `<Drama Title> - Complete.mp4`.
6. **One-Click Playback & Finder Integration**:
   - Buttons directly in the Web UI to launch the merged video or reveal the drama folder in macOS Finder.

---

## 🚀 Quick Start

### 1. Requirements
- **Python 3.10+** (tested on Python 3.13)
- **Google Chrome** (`/Applications/Google Chrome.app`)
- **FFmpeg & FFprobe** (`brew install ffmpeg`)

### 2. Installation
The necessary packages can be installed via pip:
```bash
pip install -r requirements.txt
```

### 3. Run the Application
Run the launcher script:
```bash
python3 run.py
```
This will automatically launch the web interface in your default browser at:
```
http://127.0.0.1:8000
```

---

## 📖 Usage Walkthrough

1. Paste any ReelFren drama URL into the input field:
   ```
   https://reelfren.com/drama/dramabox/42000023802-he-broke-the-heart-that-saved-him?lang=en
   ```
2. Click **Start Process**.
3. A Google Chrome browser window will open automatically.
4. **If a Cloudflare "Verify you are human" checkbox appears, click it in that browser window.**
5. Once verified:
   - The app automatically detects page access.
   - The Episode Guide table populates with all episodes.
   - Direct MP4 streams are extracted.
   - Episodes download sequentially into `downloads/<Drama Title>/episodes/`.
   - FFmpeg concatenates all episodes into `downloads/<Drama Title>/<Drama Title> - Complete.mp4`.
6. Click **Play Merged Video** or **Reveal in Finder** once complete!

---

## 📂 Output Folder Structure

```text
downloads/
└── He Broke The Heart That Saved Him/
    ├── episodes/
    │   ├── ep_001.mp4
    │   ├── ep_002.mp4
    │   └── ...
    ├── concat_list.txt
    ├── chapters.txt
    ├── episode_guide.json
    ├── episode_guide.txt
    └── He Broke The Heart That Saved Him - Complete.mp4
```
