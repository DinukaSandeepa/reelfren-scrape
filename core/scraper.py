import os
import re
import time
import json
import logging
from urllib.parse import urljoin, urlparse, parse_qs
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any, Tuple

from camoufox.sync_api import Camoufox

from core.config import BROWSER_DATA_DIR, STEALTH_HEADLESS, DOWNLOADS_DIR
from core.guide import EpisodeGuide, natural_sort_key, sanitize_filename

logger = logging.getLogger(__name__)


def parse_drama_url_params(url: str) -> Dict[str, str]:
    """
    Parses provider, drama_id, and lang from a ReelFren drama or watch URL.
    Example: https://reelfren.com/drama/dramabox/42000023802-he-broke-the-heart-that-saved-him?lang=en
    -> provider='dramabox', drama_id='42000023802', lang='en'
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    
    provider = "dramabox"
    drama_id = ""
    
    if len(path_parts) >= 3 and path_parts[0] in ("drama", "watch"):
        provider = path_parts[1]
        slug = path_parts[2]
        id_match = re.search(r"^(\d+)", slug)
        if id_match:
            drama_id = id_match.group(1)
        else:
            drama_id = slug
    elif len(path_parts) >= 2 and path_parts[0] in ("drama", "watch"):
        slug = path_parts[1]
        id_match = re.search(r"^(\d+)", slug)
        if id_match:
            drama_id = id_match.group(1)
            
    qs = parse_qs(parsed.query)
    lang = qs.get("lang", ["en"])[0]

    return {
        "provider": provider,
        "drama_id": drama_id,
        "lang": lang
    }


def select_highest_quality(quality_list: List[Dict[str, Any]], default_url: str = "") -> Tuple[str, str]:
    """
    Selects the highest resolution video URL from qualityList.
    Returns (highest_url, highest_label).
    """
    if not quality_list:
        # Fallback to default URL
        label = "720p"
        if "1080p" in default_url:
            label = "1080p"
        return default_url, label

    def get_score(item: Dict[str, Any]) -> int:
        label = str(item.get("label", ""))
        m = re.search(r"(\d+)", label)
        return int(m.group(1)) if m else 0

    sorted_qualities = sorted(quality_list, key=get_score, reverse=True)
    best = sorted_qualities[0]
    best_url = best.get("url") or default_url
    best_label = best.get("label") or "1080p"
    return best_url, best_label


class ReelFrenScraper:
    def __init__(
        self,
        drama_url: str,
        logger: Optional[Callable[[str], None]] = None,
        event_callback: Optional[Callable[[str, Any], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        is_verified: Optional[Callable[[], bool]] = None,
    ):
        self.drama_url = drama_url.strip()
        self.logger = logger or (lambda msg: print(f"[Scraper] {msg}"))
        self.event_callback = event_callback or (lambda evt, data: None)
        self.is_cancelled = is_cancelled or (lambda: False)
        self.is_verified = is_verified or (lambda: False)
        self.user_data_dir = BROWSER_DATA_DIR

        self._camoufox_instance = None
        self.context = None
        self.page = None
        self.guide: Optional[EpisodeGuide] = None
        self.captured_video_urls: Dict[int, str] = {}

    def _clean_stale_locks(self):
        """Cleans up any stale lock files left by crashed Firefox/Camoufox processes."""
        try:
            if self.user_data_dir.exists():
                for lock_name in ["parent.lock", ".parentlock", "lock"]:
                    lock_file = self.user_data_dir / lock_name
                    if lock_file.exists():
                        try:
                            lock_file.unlink()
                            self.logger(f"Removed stale browser lock file: {lock_file.name}")
                        except Exception:
                            pass
        except Exception as e:
            self.logger(f"Lock cleanup notice: {e}")

    def _setup_browser(self):
        """Initializes a persistent stealth Camoufox browser session."""
        self._clean_stale_locks()
        self.logger("Launching stealth Camoufox browser session with humanize=True...")

        try:
            self._camoufox_instance = Camoufox(
                persistent_context=True,
                user_data_dir=str(self.user_data_dir),
                headless=STEALTH_HEADLESS,
                humanize=True,
            )
            self.context = self._camoufox_instance.__enter__()
        except Exception as e:
            self.logger(f"Initial Camoufox launch notice: {e}. Retrying after lock cleanup...")
            self._clean_stale_locks()
            self._camoufox_instance = Camoufox(
                persistent_context=True,
                user_data_dir=str(self.user_data_dir),
                headless=STEALTH_HEADLESS,
                humanize=True,
            )
            self.context = self._camoufox_instance.__enter__()

        self.page = self.context.new_page()

    def _handle_turnstile(self, page):
        """Attempts to click Cloudflare Turnstile checkbox if present."""
        try:
            cf_frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            checkbox = cf_frame.locator('input[type="checkbox"], .ctp-checkbox-label, #challenge-stage, span.mark, div.spacer')
            if checkbox.count() > 0:
                checkbox.first.click(timeout=1500)
                self.logger("Clicked Cloudflare Turnstile checkbox inside iframe.")
        except Exception:
            pass

        try:
            stage = page.locator('#challenge-stage, #turnstile-wrapper, div[style*="height: 65px"]')
            if stage.count() > 0:
                box = stage.first.bounding_box()
                if box:
                    page.mouse.click(box['x'] + 28, box['y'] + 28)
                    self.logger("Clicked Cloudflare challenge stage bounding box.")
        except Exception:
            pass

    def wait_for_cloudflare_and_load(self, timeout_sec: int = 60) -> bool:
        """Loads drama URL and waits for Turnstile verification."""
        self.logger(f"Navigating to {self.drama_url}...")
        self.event_callback("status", "Navigating to drama page and resolving Cloudflare...")

        try:
            self.page.goto(self.drama_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            self.logger(f"Page initial load notice: {e}")

        start_time = time.time()

        while time.time() - start_time < timeout_sec:
            if self.is_cancelled():
                self.logger("Scraping cancelled by user.")
                return False

            if self.is_verified():
                self.logger("Verification confirmed manually via Web UI.")
                return True

            try:
                title = self.page.title()
                if "Just a moment" in title or "Cloudflare" in title or title.startswith("Loading "):
                    self._handle_turnstile(self.page)
                else:
                    grid_count = self.page.locator(".episode-grid, a.episode-link").count()
                    if grid_count > 0:
                        self.logger(f"Cloudflare Turnstile passed successfully! (Found {grid_count} episode links)")
                        self.event_callback("turnstile_verified", True)
                        return True
            except Exception:
                pass

            time.sleep(1.0)

        self.logger("Timed out waiting for Cloudflare Turnstile verification.")
        return False

    def extract_drama_metadata(self) -> Dict[str, str]:
        """Extracts drama title and poster details from the page."""
        title = "Unknown Drama"
        poster_url = None
        try:
            h1 = self.page.locator("h1").first
            if h1.count() > 0:
                text = h1.inner_text().strip()
                if text:
                    title = text
            if title == "Unknown Drama":
                title = self.page.evaluate("""() => {
                    const og = document.querySelector('meta[property="og:title"]');
                    if (og && og.content) return og.content;
                    return document.title;
                }""")
                
            # Extract poster image
            poster_url = self.page.evaluate("""() => {
                const ogImg = document.querySelector('meta[property="og:image"]');
                if (ogImg && ogImg.content) return ogImg.content;
                const twImg = document.querySelector('meta[property="twitter:image"]');
                if (twImg && twImg.content) return twImg.content;
                const cover = document.querySelector('img[class*="poster"], img[class*="cover"], .drama-cover img');
                if (cover && cover.src) return cover.src;
                return null;
            }""")
        except Exception as e:
            self.logger(f"Metadata extraction warning: {e}")

        title = re.sub(r"\s*[-|]\s*ReelFren.*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s*[-|]\s*Watch Online.*$", "", title, flags=re.IGNORECASE).strip()
        if not title:
            title = "Drama"

        self.logger(f"Drama Title: {title}")
        if poster_url:
            self.logger(f"Drama Poster URL: {poster_url[:90]}...")
        return {"title": title, "poster_url": poster_url}

    def extract_all_episodes(self) -> List[Dict[str, Any]]:
        """
        Discovers all episodes using both page grid and backend API.
        Always retrieves the HIGHEST quality available (e.g. 1080p).
        Includes retry logic for any failed episode requests.
        """
        params = parse_drama_url_params(self.drama_url)
        provider = params["provider"]
        drama_id = params["drama_id"]
        lang = params["lang"]

        self.logger(f"Detected drama parameters: provider={provider}, id={drama_id}, lang={lang}")

        # 1. Fetch EP 1 to discover total episodes and verify API access
        total_episodes = 0
        try:
            first_ep_info = self.page.evaluate(f"""async () => {{
                try {{
                    const url = "https://api.reelfren.com/api/video?provider={provider}&id={drama_id}&ep=1&lang={lang}&server=1&cv=v21";
                    const resp = await fetch(url);
                    return await resp.json();
                }} catch (e) {{
                    return {{ error: e.message }};
                }}
            }}""")
            if first_ep_info and not first_ep_info.get("error"):
                total_episodes = first_ep_info.get("totalEpisodes", 0)
                self.logger(f"API confirmed total episodes: {total_episodes}")
        except Exception as e:
            self.logger(f"API query notice: {e}")

        # Also inspect page grid count
        try:
            grid_count = self.page.locator(".episode-grid a, a.episode-link").count()
            if grid_count > total_episodes:
                total_episodes = grid_count
        except Exception:
            pass

        if total_episodes <= 0:
            total_episodes = 20  # Fallback default

        self.logger(f"Processing guide for {total_episodes} episodes in HIGHEST quality...")
        self.event_callback("status", f"Extracting {total_episodes} episodes in highest quality (1080p)...")

        # 2. Build episodes list and fetch stream metadata in batches with retry
        episodes_map: Dict[int, Dict[str, Any]] = {}
        for ep_num in range(1, total_episodes + 1):
            watch_url = f"https://reelfren.com/watch/{provider}/{drama_id}?ep={ep_num}&lang={lang}"
            episodes_map[ep_num] = {
                "episode": ep_num,
                "title": f"EP {ep_num}",
                "watch_url": watch_url,
                "video_url": None,
                "quality": "1080p",
                "status": "pending"
            }

        # Fetch video URLs in batches of 5
        batch_size = 5
        for start_idx in range(1, total_episodes + 1, batch_size):
            if self.is_cancelled():
                return list(episodes_map.values())

            end_idx = min(start_idx + batch_size, total_episodes + 1)
            ep_batch = list(range(start_idx, end_idx))

            batch_results = self._fetch_episodes_batch_with_retry(provider, drama_id, lang, ep_batch)
            for res in batch_results:
                ep_num = res.get("ep")
                if ep_num in episodes_map:
                    video_url = res.get("videoUrl")
                    quality = res.get("quality", "1080p")
                    if video_url:
                        episodes_map[ep_num]["video_url"] = video_url
                        episodes_map[ep_num]["quality"] = quality
                        episodes_map[ep_num]["status"] = "ready"
                        if self.guide:
                            self.guide.update_episode(ep_num, video_url=video_url, quality=quality, status="ready")

            # Update UI with currently loaded episodes
            self.event_callback("episodes_loaded", list(episodes_map.values()))

        # Check for any episodes that failed URL resolution
        failed_eps = [ep for ep in episodes_map.values() if not ep.get("video_url")]
        if failed_eps:
            self.logger(f"Warning: {len(failed_eps)} episode URLs failed resolution. Attempting secondary watch-page resolution...")
            for ep in failed_eps:
                if self.is_cancelled():
                    break
                self._resolve_single_watch_page(ep)

        ep_list = list(episodes_map.values())
        ep_list.sort(key=lambda x: x["episode"])
        return ep_list

    def _fetch_episodes_batch_with_retry(
        self, provider: str, drama_id: str, lang: str, ep_numbers: List[int], max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """Fetches a batch of episodes using page.evaluate with automatic retries."""
        results = []
        needed = list(ep_numbers)

        for attempt in range(1, max_retries + 1):
            if not needed or self.is_cancelled():
                break

            fetch_code = f"""async () => {{
                const eps = {json.dumps(needed)};
                const out = [];
                for (const ep of eps) {{
                    try {{
                        const url = "https://api.reelfren.com/api/video?provider={provider}&id={drama_id}&ep=" + ep + "&lang={lang}&server=1&cv=v21";
                        const resp = await fetch(url);
                        if (!resp.ok) throw new Error("HTTP " + resp.status);
                        const data = await resp.json();
                        out.push({{ ep: ep, data: data }});
                    }} catch (e) {{
                        out.push({{ ep: ep, error: e.message }});
                    }}
                }}
                return out;
            }}"""

            try:
                raw_out = self.page.evaluate(fetch_code)
                for item in raw_out:
                    ep_num = item.get("ep")
                    data = item.get("data")
                    if data and not item.get("error"):
                        # Select HIGHEST quality
                        best_url, best_label = select_highest_quality(
                            data.get("qualityList", []),
                            default_url=data.get("videoUrl", "")
                        )
                        results.append({
                            "ep": ep_num,
                            "videoUrl": best_url,
                            "quality": best_label,
                            "title": data.get("title", f"EP {ep_num}")
                        })
                        if ep_num in needed:
                            needed.remove(ep_num)
                    else:
                        self.logger(f"Episode {ep_num} API attempt {attempt} notice: {item.get('error')}")
            except Exception as e:
                self.logger(f"Batch evaluate attempt {attempt} error: {e}")

            if needed and attempt < max_retries:
                time.sleep(attempt * 1.5)

        return results

    def _resolve_single_watch_page(self, ep: Dict[str, Any]):
        """Fallback: Navigates to the watch page directly to resolve missing video stream."""
        ep_num = ep["episode"]
        watch_url = ep["watch_url"]
        self.logger(f"Visiting watch page for Episode {ep_num} fallback...")
        try:
            self.page.goto(watch_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            video_src = self.page.evaluate("""() => {
                const video = document.querySelector('video');
                if (video) {
                    if (video.src && video.src.startsWith('http')) return video.src;
                    const source = video.querySelector('source');
                    if (source && source.src) return source.src;
                }
                return null;
            }""")
            if video_src:
                ep["video_url"] = video_src
                ep["quality"] = "1080p" if "1080p" in video_src else "720p"
                ep["status"] = "ready"
                self.logger(f"Fallback resolved Episode {ep_num}: {video_src.split('/')[-1]}")
                if self.guide:
                    self.guide.update_episode(ep_num, video_url=video_src, quality=ep["quality"], status="ready")
        except Exception as e:
            self.logger(f"Watch page fallback failed for Episode {ep_num}: {e}")

    def scrape_and_setup(self) -> EpisodeGuide:
        """Full pipeline: Launch Camoufox -> Turnstile bypass -> Build Guide with Highest Quality."""
        try:
            self._setup_browser()

            verified = self.wait_for_cloudflare_and_load()
            if not verified:
                raise RuntimeError("Cloudflare verification was not completed or timed out.")

            metadata = self.extract_drama_metadata()
            title = metadata["title"]
            poster_url = metadata.get("poster_url")
            safe_title = sanitize_filename(title)

            drama_output_dir = DOWNLOADS_DIR / safe_title
            self.guide = EpisodeGuide(
                drama_title=title,
                drama_url=self.drama_url,
                output_dir=drama_output_dir,
                poster_url=poster_url
            )

            # Download official poster if available
            if poster_url:
                self.guide.download_poster()

            episodes = self.extract_all_episodes()
            if not episodes:
                raise RuntimeError("No episodes found for this drama.")

            self.guide.set_episodes(episodes)
            self.guide.save()
            return self.guide
        finally:
            self.close()

    def close(self):
        """Cleanly exit Camoufox session and cleanup locks."""
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        try:
            if self._camoufox_instance and self.context:
                self._camoufox_instance.__exit__(None, None, None)
        except Exception:
            pass
        finally:
            self.page = None
            self.context = None
            self._camoufox_instance = None
            self._clean_stale_locks()
