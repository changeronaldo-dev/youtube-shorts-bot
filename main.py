#!/usr/bin/env python3
"""
Fully-automated YouTube Shorts generator & uploader — Khana Kaba / Makkah.

Pipeline (designed to run inside GitHub Actions — nothing to run on your PC):

  1. Fetch THREE distinct high-resolution images of the Holy Kaaba / Makkah
     (Pexels -> Unsplash -> Wikimedia Commons, in that order of preference).
  2. Download a freely-licensed naat / nasheed audio track
     (curated CC0 / Public-Domain / CC-BY catalogs on Internet Archive and
     Wikimedia Commons — direct, stable file links).
  3. Render a 1080x1920 @ 30fps MP4 slideshow: 3 images x 5 seconds (15 s)
     with a smooth slow-zoom "Ken Burns" animation on every image and a soft
     crossfade between them, using moviepy.
  4. Auto-generate an attractive title / description / hashtags
     (English + Urdu mix) incl. automatic attribution credits.
  5. Upload to YouTube via the YouTube Data API v3 (google-api-python-client)
     using OAuth credentials stored as GitHub repository secrets.

The GitHub workflow runs this THREE times a day (10:00, 14:00, 21:30 PKT).

Environment variables (all optional except YouTube ones when uploading):
  DRY_RUN=1                  generate the video + metadata but skip the upload
  PEXELS_API_KEY             https://www.pexels.com/api/  (optional)
  UNSPLASH_ACCESS_KEY        https://unsplash.com/developers  (optional)
  YOUTUBE_CLIENT_ID          Google OAuth client id      (required to upload)
  YOUTUBE_CLIENT_SECRET      Google OAuth client secret  (required to upload)
  YOUTUBE_REFRESH_TOKEN      OAuth refresh token         (required to upload)
  YT_PRIVACY                 public | unlisted | private  (default: public)
  YT_CATEGORY_ID             YouTube category id          (default: 22)
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

W, H, FPS = 1080, 1920, 30            # vertical 9:16 Short
SLIDE_COUNT = 3                       # images per Short
SLIDE_DURATION = 5.0                  # seconds each  -> 15 s video
CROSSFADE = 0.7                       # soft blend between slides (seconds)
DURATION = SLIDE_COUNT * SLIDE_DURATION
ZOOM_RANGE = 0.16                     # total Ken-Burns zoom amount (16%)
OUT_DIR = Path("output")
UA = "youtube-shorts-automation/1.0 (GitHub Actions; contact via repo)"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Image search queries (sampled for variety)
QUERIES = [
    "Khana Kaba",
    "Kaaba Makkah",
    "Kaaba",
    "Masjid al Haram Kaaba",
    "Kaaba night",
    "Kaaba door",
    "Kaaba kiswah",
    "Makkah grand mosque",
    "Haram Makkah",
]

# Curated pool of naat / nasheed albums on Internet Archive whose uploaders
# declared open licenses (CC0 / Public Domain Mark / CC BY).  ND-licensed and
# commercial-album items are deliberately excluded so the audio can legally be
# remixed into a video.  Each entry: (archive.org item id, human label, license url)
ARCHIVE_NAAT_ITEMS = [
    ("Khkuly-MADEENA-Album-6", "Khkuly MADEENA (Asmatullah Jarar) — Naat Album",
     "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("Shah_e_Medina_Vol_4", "Shah-e-Medina Vol. 4 — Muhammad Farhan Ali Qadri",
     "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("Huzoor_Ka_Sadqa_Vol_16", "Huzoor Ka Sadqa Vol. 16 — Muhammad Farhan Ali Qadri",
     "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("Vol-16-2013-BaagheJannat", "Baaghe Jannat (2013) — Naat Album",
     "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("Mere_Hussain_Salaam_Vol_1", "Mere Hussain Salaam Vol. 1",
     "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("Nasheed_400", "Nasheed Collection", "https://creativecommons.org/publicdomain/zero/1.0/"),
    ("AdfaitaBySheikhByMisharyRashidAlAfasy", "Nasheed by Sheikh Mishary Rashid Alafasy",
     "https://creativecommons.org/publicdomain/zero/1.0/"),
    ("Karimrachdi2016_gmail", "Arabic Nasheed — أنشودة لست أرضى المقام",
     "https://creativecommons.org/publicdomain/mark/1.0/"),
    ("nadera24", "أناشيد نادرة — Rare Nasheed Collection",
     "https://creativecommons.org/publicdomain/zero/1.0/"),
]

# Verified CC-BY fallback on Wikimedia Commons
COMMONS_NAAT_FALLBACK = {
    "url": ("https://upload.wikimedia.org/wikipedia/commons/9/90/"
            "Jawad_Syed_-_Alhamdulilah_%28Vocal_Only_Nasheed%29.flac"),
    "title": "Alhamdulilah (Vocal Only Nasheed)",
    "credit": "Jawad Syed, Wikimedia Commons",
    "license": "CC BY 3.0",
}

# --------------------------------------------------------------------------- #
# Title / description / hashtag pools (English + Urdu mix)
# --------------------------------------------------------------------------- #

TITLES = [
    "MashAllah! 🕋 Khana Kaba ka Roohani Manzar | Beautiful Kaaba in Makkah #Shorts",
    "SubhanAllah 🕋 Kaaba at Night — Masjid al-Haram, Makkah Mukarramah #Shorts",
    "🕌 Khan-e-Kaaba ki Khubsurti | Beautiful Moments of Makkah Mukarramah #Shorts",
    "Allahu Akbar! 🕋 Baitullah ka Noorani Nazara | Khana Kaba Makkah #Shorts",
    "خانہ کعبہ کی خوبصورت نظارہ 🕋 | Khana Kaba, Makkah Mukarramah #Shorts",
    "SubhanAllah! 🕋 Makkah Mukarramah ka Dilchasp Manzar | Kaaba Sharif #Shorts",
    "🕋 Baitullah Sharif | Masjid al-Haram, Makkah — Beautiful View #Shorts",
    "MashAllah 🕋 Kaaba ka Azeem Nazara | Makkah, Saudi Arabia #Shorts",
    "✨ Roohani Sakoon wali Nazara | Khana Kaba at Masjid al-Haram #Shorts",
    "الله أكبر 🕋 خانہ کعبہ — Beautiful Kaaba Moments | Makkah #Shorts",
]

URDU_LINES = [
    "خانہ کعبہ، مکہ مکرمہ کی خوبصورت نظارہ 🕋",
    "سبحان اللہ! بیت اللہ کا نورانی منظر ✨",
    "مسجد حرام، مکہ مکرمہ کا دلکش منظر 🕌",
    "اللہ اکبر! خانہ کعبہ کی رونق دیکھیے 🕋",
    "ماشاء اللہ! بیت اللہ شریف کا حسین نظارہ ✨",
]

ENGLISH_LINES = [
    "Beautiful views of the Holy Kaaba at Masjid al-Haram, Makkah Mukarramah.",
    "A peaceful slideshow of Baitullah in Makkah, Saudi Arabia. MashAllah!",
    "Enjoy this beautiful slideshow from the House of Allah. ❤️",
    "The Holy Kaaba — the qibla of Muslims around the world. 🕋",
]

HASHTAGS = (
    "#Shorts #KhanaKaba #Makkah #Kaaba #Kaba #Naat #NaatSharif #IslamicShorts "
    "#MasjidAlHaram #MakkahMukarramah #Baitullah #MuslimShorts #IslamicVideo #Islam"
)

TAGS = [
    "Khana Kaba", "Kaaba", "Kaba", "Makkah", "Makkah Mukarramah",
    "Masjid al Haram", "Baitullah", "Naat", "Naat Sharif", "Islamic Shorts",
    "Makkah Kaaba", "Saudi Arabia", "Islamic Video",
]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("shorts")

http = requests.Session()
http.headers.update({"User-Agent": UA})


def step(n: int, total: int, msg: str) -> None:
    log.info("\n[%d/%d] %s", n, total, msg)


def set_github_env(key: str, value: str) -> None:
    """Export a variable to subsequent GitHub Actions steps (if running in CI)."""
    gh_env = os.getenv("GITHUB_ENV")
    if gh_env:
        with open(gh_env, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def short_license(license_url: str) -> str:
    s = license_url or ""
    if "/publicdomain/zero" in s:
        return "CC0 1.0"
    if "/publicdomain" in s:
        return "Public Domain Mark 1.0"
    m = re.search(r"/licenses/([a-z-]+)(?:/(\d\.\d))?", s)
    if m:
        return f"CC {m.group(1).upper()} {m.group(2) or ''}".strip()
    return s or "Open License"


def download(url: str, dest: Path, timeout: int = 120, retries: int = 2) -> Path:
    """Download with polite retry/backoff on rate-limit or server errors."""
    for attempt in range(retries + 1):
        try:
            with http.get(url, stream=True, timeout=timeout, allow_redirects=True) as r:
                r.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
            return dest
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (429, 500, 502, 503) and attempt < retries:
                wait = 3.0 * (attempt + 1)
                if exc.response is not None:
                    try:
                        wait = float(exc.response.headers.get("Retry-After") or 0) or wait
                    except ValueError:
                        pass
                wait = min(wait, 20.0)
                log.warning("  HTTP %s — retry %d/%d in %.0fs …",
                            status, attempt + 1, retries, wait)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"download failed after {retries + 1} attempts: {url}")

# --------------------------------------------------------------------------- #
# Step 1 — background images  (Pexels -> Unsplash -> Wikimedia Commons)
# --------------------------------------------------------------------------- #

def fetch_from_pexels(query: str) -> list[dict]:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    try:
        r = http.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "portrait", "per_page": 40, "size": "large"},
            headers={"Authorization": key}, timeout=30,
        )
        r.raise_for_status()
        out = []
        for p in r.json().get("photos", []):
            out.append({
                "url": p["src"]["original"] + "?auto=compress&cs=tinysrgb&w=1600",
                "credit": f'{p.get("photographer", "Unknown")} / Pexels',
                "min_w": 900, "min_h": 1200,
            })
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("  Pexels failed (%s) — trying next source…", exc)
        return []


def fetch_from_unsplash(query: str) -> list[dict]:
    key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not key:
        return []
    try:
        r = http.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "orientation": "portrait", "per_page": 30},
            headers={"Authorization": f"Client-ID {key}"}, timeout=30,
        )
        r.raise_for_status()
        out = []
        for p in r.json().get("results", []):
            out.append({
                "url": p["urls"]["raw"] + "&w=1600&q=85&fm=jpg&fit=max",
                "credit": f'{p.get("user", {}).get("name", "Unknown")} / Unsplash',
                "min_w": 900, "min_h": 1200,
            })
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("  Unsplash failed (%s) — trying next source…", exc)
        return []


def clean_artist(raw: str) -> str:
    """Reduce Wikimedia's Artist metadata to a short, human-readable credit."""
    artist = strip_html(raw or "")
    for marker in ("The making of this document", "Submit your project",
                   "العربية", "∙", "+/−"):
        idx = artist.find(marker)
        if idx > 0:
            artist = artist[:idx]
    artist = re.sub(r"[\s(,]+$", "", artist.strip())
    return artist[:80] or "Unknown author"


def fetch_from_commons(query: str) -> list[dict]:
    try:
        r = http.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 40, "gsrnamespace": 6,
                "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 1600,
            }, timeout=30,
        )
        r.raise_for_status()
        out = []
        for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
            ii = (page.get("imageinfo") or [{}])[0]
            if ii.get("mime") not in ("image/jpeg", "image/png") or not ii.get("thumburl"):
                continue
            meta = ii.get("extmetadata", {})
            artist = clean_artist(meta.get("Artist", {}).get("value", ""))
            lic = meta.get("LicenseShortName", {}).get("value", "") or "see file page"
            out.append({
                "url": ii["thumburl"],
                "credit": f"{artist} / Wikimedia Commons ({lic})",
                "min_w": 700, "min_h": 900,
            })
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("  Wikimedia Commons failed: %s", exc)
        return []


def get_background_images(dest_dir: Path, count: int = SLIDE_COUNT) -> list[dict]:
    """Download `count` DISTINCT Kaaba/Makkah images (different URLs + file bytes)."""
    queries = QUERIES[:]
    random.shuffle(queries)
    pool: list[dict] = []
    for q in queries[:4]:                      # diverse queries -> visual variety
        for provider in (fetch_from_pexels, fetch_from_unsplash, fetch_from_commons):
            pool.extend(provider(q))
    random.shuffle(pool)
    log.info("  candidate pool: %d images", len(pool))

    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    results: list[dict] = []
    first = True

    # up to 2 passes over the pool; the 2nd pass retries after a cool-down
    for pass_no in (1, 2):
        fails = 0
        for cand in pool:
            if len(results) == count:
                break
            url_key = cand["url"].split("?")[0]
            if url_key in seen_urls:
                continue
            if first:
                first = False
            else:
                time.sleep(1.1)                # be polite to free image hosts
            path = dest_dir / f"background_{len(results)}.jpg"
            try:
                download(cand["url"], path, timeout=90)
                from PIL import Image  # local import: validates the file too
                with Image.open(path) as img:
                    if img.width < cand["min_w"] or img.height < cand["min_h"]:
                        path.unlink(missing_ok=True)
                        fails += 1
                        continue
                digest = hashlib.md5(path.read_bytes()).hexdigest()
                if digest in seen_hashes:      # same photo via different link
                    path.unlink(missing_ok=True)
                    continue
                seen_urls.add(url_key)
                seen_hashes.add(digest)
                results.append({"path": path, "credit": cand["credit"]})
                fails = 0
                log.info("  ✔ image %d/%d — %s",
                         len(results), count, cand["credit"][:60])
            except Exception as exc:  # noqa: BLE001
                fails += 1
                log.warning("  candidate failed (%s), next…", str(exc)[:90])
                path.unlink(missing_ok=True)
                if fails >= 10:                # host throttling hard — stop pass
                    log.warning("  10 consecutive failures — pausing this pass")
                    break
        if len(results) == count:
            break
        if pass_no == 1:
            log.info("  pass 1: %d/%d images — cooling down 30 s before retry…",
                     len(results), count)
            time.sleep(30)
    if len(results) < count:
        raise RuntimeError(
            f"Only {len(results)}/{count} distinct Kaaba/Makkah images could be "
            "downloaded. Check network access / API keys, then re-run."
        )
    return results

# --------------------------------------------------------------------------- #
# Step 2 — naat / nasheed audio  (Internet Archive curated pool -> Commons)
# --------------------------------------------------------------------------- #

def archive_track_candidates(item_id: str) -> list[dict]:
    r = http.get(f"https://archive.org/metadata/{item_id}", timeout=45)
    r.raise_for_status()
    data = r.json()
    lic = short_license((data.get("metadata", {}) or {}).get("licenseurl", ""))
    tracks = []
    for f in data.get("files", []):
        name = f.get("name", "")
        size = int(f.get("size", 0) or 0)
        if name.lower().endswith(".mp3") and 2_000_000 < size < 20_000_000:
            if name.startswith("._") or "__MACOSX" in name:
                continue
            tracks.append({
                "url": f"https://archive.org/download/{item_id}/{urllib.parse.quote(name)}",
                "pretty": Path(name).stem.replace("_", " ").strip(" -–.,")[:70],
                "license": lic,
            })
    return tracks


def get_naat_audio(dest: Path) -> dict:
    items = ARCHIVE_NAAT_ITEMS[:]
    random.shuffle(items)
    for item_id, label, _lic in items:
        try:
            tracks = archive_track_candidates(item_id)
            if not tracks:
                continue
            track = random.choice(tracks)
            download(track["url"], dest, timeout=180)
            # make sure ffmpeg can actually decode it & it is long enough
            from moviepy import AudioFileClip
            probe = AudioFileClip(str(dest))
            dur = probe.duration or 0
            probe.close()
            if dur < 12:
                dest.unlink(missing_ok=True)
                continue
            log.info("  ✔ audio: %s — %s [%s]", track["pretty"], label, track["license"])
            return {
                "path": dest,
                "credit": f"{track['pretty']} — {label} (Internet Archive, {track['license']})",
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("  archive item %s failed (%s), trying next…", item_id, exc)
    # final fallback: verified CC-BY file on Wikimedia Commons
    try:
        download(COMMONS_NAAT_FALLBACK["url"], dest, timeout=180)
        return {"path": dest, "credit": f"{COMMONS_NAAT_FALLBACK['title']} — "
                                        f"{COMMONS_NAAT_FALLBACK['credit']} "
                                        f"({COMMONS_NAAT_FALLBACK['license']})"}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not download any naat audio: {exc}") from exc

# --------------------------------------------------------------------------- #
# Step 3 — render 1080x1920 slideshow (3 images x 5 s, slow zoom, crossfade)
# --------------------------------------------------------------------------- #

def _prepare_canvas(image_path: Path):
    """Cover-crop the image onto an oversized canvas so every frame downscales."""
    from PIL import Image
    big_w, big_h = int(W * (1 + ZOOM_RANGE)) + 2, int(H * (1 + ZOOM_RANGE)) + 2
    img = Image.open(image_path).convert("RGB")
    scale = max(big_w / img.width, big_h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - big_w) // 2, (img.height - big_h) // 2
    return img.crop((left, top, left + big_w, top + big_h))


def render_slideshow(image_paths: list[Path], audio_path: Path, out_path: Path) -> float:
    import numpy as np
    from PIL import Image
    from moviepy import AudioFileClip, VideoClip
    import moviepy.audio.fx as afx

    duration = len(image_paths) * SLIDE_DURATION

    # one animation style per slide, never the same twice in a row
    styles = ["zoom_in", "zoom_out", "zoom_in_pan"][: len(image_paths)]
    random.shuffle(styles)

    slides = []
    for i, p in enumerate(image_paths):
        style = styles[i % len(styles)]
        g0, g1 = (1.0, 1.0 + ZOOM_RANGE) if style != "zoom_out" else (1.0 + ZOOM_RANGE, 1.0)
        slides.append({
            "canvas": _prepare_canvas(p),
            "g0": g0, "g1": g1,
            "pan": random.choice((-1, 1)) if style == "zoom_in_pan" else 0,
            "big": (int(W * (1 + ZOOM_RANGE)) + 2, int(H * (1 + ZOOM_RANGE)) + 2),
        })
        log.info("  slide %d: %s (%s)", i + 1, p.name, style)

    def slide_frame(slide: dict, local_t: float) -> "np.ndarray":
        s = min(max(local_t / SLIDE_DURATION, 0.0), 1.0)
        eased = s * s * (3.0 - 2.0 * s)              # smoothstep easing
        g = slide["g0"] + (slide["g1"] - slide["g0"]) * eased
        big_w, big_h = slide["big"]
        cw, ch = big_w / g, big_h / g
        cx = big_w / 2 + slide["pan"] * (big_w - cw) * 0.5 * eased
        cy = big_h / 2
        crop = slide["canvas"].crop((cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))
        return np.asarray(crop.resize((W, H), Image.BILINEAR))

    boundaries = [k * SLIDE_DURATION for k in range(1, len(slides))]
    half = CROSSFADE / 2

    def frame(t: float) -> "np.ndarray":
        idx = min(int(t // SLIDE_DURATION), len(slides) - 1)
        cur = slide_frame(slides[idx], t - idx * SLIDE_DURATION)
        # soft crossfade around each internal boundary
        for b in boundaries:
            if abs(t - b) < half:
                alpha = min(max(0.5 + (t - b) / CROSSFADE, 0.0), 1.0)
                outgoing = slide_frame(slides[int(b // SLIDE_DURATION) - 1], t - (b - SLIDE_DURATION))
                incoming = slide_frame(slides[int(b // SLIDE_DURATION)], t - b)
                return (outgoing.astype(np.float32) * (1.0 - alpha)
                        + incoming.astype(np.float32) * alpha).astype(np.uint8)
        return cur

    video = VideoClip(frame_function=frame, duration=duration)

    # ---- audio: cut a random segment, or loop if the track is short ----------
    audio = AudioFileClip(str(audio_path))
    if (audio.duration or 0) >= duration + 1:
        hi = max(5.0, (audio.duration or 0) - duration - 1)
        start = random.uniform(5.0, hi) if hi > 5.0 else 0.0
        audio_seg = audio.subclipped(start, start + duration)
    else:
        audio_seg = audio.with_effects([afx.AudioLoop(duration=duration)])
    audio_seg = audio_seg.with_effects([afx.AudioFadeIn(0.8), afx.AudioFadeOut(1.2)])
    video = video.with_audio(audio_seg)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("  rendering %ds (%d slides x %.0fs) @ %dfps, %dx%d …",
             int(duration), len(slides), SLIDE_DURATION, FPS, W, H)
    t0 = time.time()
    video.write_videofile(
        str(out_path), fps=FPS, codec="libx264", audio_codec="aac",
        audio_bitrate="192k", preset="medium", threads=os.cpu_count() or 2,
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=None,
    )
    video.close()
    audio.close()
    log.info("  ✔ rendered in %.0fs → %s (%.1f MB)", time.time() - t0,
             out_path, out_path.stat().st_size / 1e6)
    return duration

# --------------------------------------------------------------------------- #
# Step 4 — title / description / hashtags (auto-generated)
# --------------------------------------------------------------------------- #

def build_metadata(image_credits: list[str], audio_credit: str) -> dict:
    title = random.choice(TITLES)[:98]

    urdu = random.choice(URDU_LINES)
    english = random.choice(ENGLISH_LINES)
    image_lines = "\n".join(f"   {i + 1}. {c[:140]}" for i, c in enumerate(image_credits))
    description = (
        f"{urdu}\n\n"
        f"{english}\n\n"
        f"🕋 Khana Kaba | Masjid al-Haram, Makkah Mukarramah\n\n"
        f"Like 👍, Share 🔄 & Subscribe 🔔 for daily Makkah & Madina Shorts!\n\n"
        f"──────────────────\n"
        f"🎵 Naat: {audio_credit}\n"
        f"🖼️ Images:\n{image_lines}\n"
        f"──────────────────\n\n"
        f"{HASHTAGS}"
    )
    return {"title": title, "description": description[:4900], "tags": TAGS}

# --------------------------------------------------------------------------- #
# Step 5 — upload to YouTube (Data API v3)
# --------------------------------------------------------------------------- #

def upload_to_youtube(video_path: Path, meta: dict) -> str:
    import google.auth.exceptions
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    missing = [n for n, v in (
        ("YOUTUBE_CLIENT_ID", client_id),
        ("YOUTUBE_CLIENT_SECRET", client_secret),
        ("YOUTUBE_REFRESH_TOKEN", refresh_token)) if not v]
    if missing:
        log.error("  Missing GitHub secrets: %s", ", ".join(missing))
        log.error("  Add them under Settings → Secrets and variables → Actions, "
                  "then re-run. See README.md for the one-time setup.")
        sys.exit(1)

    creds = Credentials(
        token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret, scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except google.auth.exceptions.RefreshError as exc:
        log.error("  OAuth refresh failed: %s", exc)
        log.error("  Most likely the refresh token expired (Google 'Testing' mode tokens "
                  "last 7 days) or was revoked. Publish your OAuth app to production "
                  "(or re-run the 'Get YouTube Refresh Token' workflow) and update "
                  "the YOUTUBE_REFRESH_TOKEN secret.")
        sys.exit(1)

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": os.getenv("YT_CATEGORY_ID", "22"),
        },
        "status": {
            "privacyStatus": os.getenv("YT_PRIVACY", "public").strip().lower() or "public",
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            resumable=True, chunksize=8 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    log.info("  uploading (%.1f MB) as '%s' [%s] …",
             video_path.stat().st_size / 1e6, meta["title"], body["status"]["privacyStatus"])
    retries, response = 0, None
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as exc:
            if exc.resp.status in (500, 502, 503, 429) and retries < 5:
                retries += 1
                wait = 2 ** retries * 5
                log.warning("  transient HTTP %d — retry %d/5 in %ds…", exc.resp.status, retries, wait)
                time.sleep(wait)
                continue
            if exc.resp.status == 403 and b"quotaExceeded" in exc.content:
                log.error("  YouTube API daily quota exceeded — upload again tomorrow "
                          "(default quota allows 6 uploads/day).")
            raise
    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    log.info("  ✔ uploaded: %s", url)
    return url

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    started = datetime.now(timezone.utc)
    log.info("════════════════════════════════════════════════════════")
    log.info("  Khana Kaba Shorts — automated run  %s", started.strftime("%Y-%m-%d %H:%M UTC"))
    log.info("════════════════════════════════════════════════════════")
    dry_run = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = OUT_DIR / "naat.mp3"
    video_path = OUT_DIR / "short.mp4"
    audio_path.unlink(missing_ok=True)
    video_path.unlink(missing_ok=True)
    for old in OUT_DIR.glob("background_*.jpg"):
        old.unlink(missing_ok=True)

    random.seed()

    step(1, 6, f"Fetching {SLIDE_COUNT} distinct Kaaba / Makkah images …")
    images = get_background_images(OUT_DIR, SLIDE_COUNT)

    step(2, 6, "Fetching freely-licensed naat audio …")
    audio = get_naat_audio(audio_path)

    step(3, 6, "Generating metadata (title / description / hashtags) …")
    meta = build_metadata([img["credit"] for img in images], audio["credit"])
    log.info("  title: %s", meta["title"])

    step(4, 6, f"Rendering {SLIDE_COUNT}-image slideshow ({SLIDE_DURATION:.0f}s each) …")
    render_slideshow([img["path"] for img in images], audio_path, video_path)
    for img in images:
        img["path"].unlink(missing_ok=True)     # keep the workspace light
    audio_path.unlink(missing_ok=True)

    step(5, 6, "Uploading to YouTube …")
    if dry_run:
        log.info("  DRY_RUN=1 → skipping upload. Metadata preview:")
        log.info("  ─────────────────────────────────────────────")
        log.info("  TITLE: %s", meta["title"])
        log.info("  DESCRIPTION:\n%s", meta["description"])
        log.info("  ─────────────────────────────────────────────")
        set_github_env("UPLOAD_RESULT", "dry_run")
        set_github_env("VIDEO_TITLE", meta["title"].replace("\n", " "))
        set_github_env("VIDEO_URL", "")
    else:
        url = upload_to_youtube(video_path, meta)
        set_github_env("UPLOAD_RESULT", "success")
        set_github_env("VIDEO_TITLE", meta["title"].replace("\n", " "))
        set_github_env("VIDEO_URL", url)
        step(6, 6, "Done! 🎉")
        log.info("  video:   %s", url)

    log.info("\nTotal time: %.0fs | output: %s",
             (datetime.now(timezone.utc) - started).total_seconds(), video_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error("\n✖ FAILED: %s", exc)
        sys.exit(1)
