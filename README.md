# 🕋 Automated YouTube Shorts — Khana Kaba / Makkah

100% automated pipeline that **creates and uploads a YouTube Short every day**
without ever running anything on your own computer. Everything runs on
**GitHub Actions** (free for public repositories).

```
3 distinct Kaaba images (Pexels → Unsplash → Wikimedia Commons)
        +
freely-licensed Naat audio (Internet Archive / Wikimedia Commons — CC0, PD, CC-BY)
        ↓
1080×1920 MP4 slideshow — 3 images × 5 s (15 s total), slow zoom on every
image + soft crossfade transitions                            (moviepy)
        ↓
auto-generated title + Urdu/English description + hashtags + attribution
        ↓
upload to your channel  (YouTube Data API v3, OAuth refresh token)
        ↓
runs 3× DAILY — 10:00 AM, 2:00 PM & 9:30 PM Pakistan time
```

**Files**

| File | Purpose |
|---|---|
| `main.py` | The whole pipeline (image → audio → video → metadata → upload) |
| `requirements.txt` | Python dependencies installed by the workflow |
| `.github/workflows/youtube_auto_upload.yml` | ⭐ The automation — 3 cron runs daily + manual dispatch |
| `.github/workflows/youtube_auth.yml` | One-time helper to get your OAuth refresh token |
| `scripts/generate_refresh_token.py` | OAuth helper used by the workflow above |

> ℹ️ There is a **single** workflow file (`youtube_auto_upload.yml`) whose cron
> fires three times a day. Do not add another workflow with the same schedules —
> it would upload duplicates. Use the manual *Run workflow* button for extra runs.

---

## 🔧 One-time setup (≈10 minutes)

### 1. Google Cloud — create OAuth credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project (any name).
2. **APIs & Services → Library** → search **“YouTube Data API v3”** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External** → create.
   - Fill only App name + your email. Add the scope
     `https://www.googleapis.com/auth/youtube.upload` — or just skip scopes here.
   - Under **Test users**, add the Google account that owns your YouTube channel.
   - ⚠️ **Important:** click **“Publish app”** (set to *In production*). While the
     app stays in *Testing* mode, refresh tokens **die after 7 days** and your
     automation will stop with `invalid_grant` until you re-auth. Publishing
     avoids that (you may see an “unverified app” warning during your own login —
     that is normal and safe; click *Advanced → Continue*).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Desktop app** → Create.
   - Copy the **Client ID** and **Client secret**.

### 2. Add repository secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `YOUTUBE_CLIENT_ID` | OAuth client ID (step 1.4) |
| `YOUTUBE_CLIENT_SECRET` | OAuth client secret (step 1.4) |
| `YOUTUBE_REFRESH_TOKEN` | ← generated in step 3 below |
| `PEXELS_API_KEY` | *optional* — free key from [pexels.com/api](https://www.pexels.com/api/) (better image variety) |
| `UNSPLASH_ACCESS_KEY` | *optional* — free key from [unsplash.com/developers](https://unsplash.com/developers) |

Without Pexels/Unsplash keys the pipeline still works — it uses freely-licensed
Kaaba photos from Wikimedia Commons.

### 3. Get your refresh token (2 short workflow runs)

Repo → **Actions** tab → select **“Get YouTube Refresh Token”**:

1. **Run workflow** with the input **empty** → open the job log → copy the consent URL
   → open it in a browser → pick your channel account → **Allow**.
   The browser then tries to load `http://localhost:8080/?code=…` and shows an
   error page — **that is expected**. Copy the `code=` value from the address bar.
2. **Run workflow** again, this time pasting that code into the input.
   The log prints your **refresh token** → save it as the secret
   `YOUTUBE_REFRESH_TOKEN`.

### 4. First run — test it

Actions → **“YouTube Shorts Auto Upload”** → **Run workflow**:

- tick **`dry_run`** first if you want to see the generated video (downloadable
  artifact) without uploading;
- then run for real. Done — from now on it uploads automatically **three times a
  day: 10:00 AM, 2:00 PM and 9:30 PM Pakistan time** (05:00, 09:00 & 16:30 UTC).
  Change the cron lines in `.github/workflows/youtube_auto_upload.yml` if you
  prefer other times.

---

## ⏰ Scheduling & quota notes

- GitHub cron uses UTC (Pakistan = UTC+5). Current schedule:

  | Cron (UTC) | Pakistan time |
  |---|---|
  | `0 5 * * *` | 10:00 AM |
  | `0 9 * * *` | 2:00 PM |
  | `30 16 * * *` | 9:30 PM |

- Each run makes **1 video = 3 distinct Kaaba images × 5 s** with slow zoom and
  crossfades → 3 uploads/day. GitHub cron may fire a few minutes late.
- `schedule` triggers only run on the **default branch**, and GitHub pauses
  scheduled workflows after **60 days of repository inactivity** — this repo
  avoids that automatically because every upload appends a line to `UPLOADS.md`
  (a commit). Still, check the Actions tab occasionally.
- YouTube Data API default quota = 10,000 units/day; an upload costs 1,600 →
  3 uploads/day use 4,800 units (max possible: 6 uploads/day). A
  `quotaExceeded` error simply means: try tomorrow.

## 🎨 Customisation (all in `main.py`)

- **Slideshow**: `SLIDE_COUNT` (images per Short), `SLIDE_DURATION` (seconds per
  image), `CROSSFADE` (transition length) at the top of the file.
- **Variety**: image queries (`QUERIES`), zoom amount (`ZOOM_RANGE`),
  title/urdu-line/hashtag pools.
- **Privacy default**: `YT_PRIVACY` env / workflow input (`public` default).
- **Category**: `YT_CATEGORY_ID` (default `22` = People & Blogs; `27` = Education).

## 📜 Content licensing

- **Images**: Pexels/Unsplash licenses (free for commercial use, no attribution
  required — credit given anyway) or Wikimedia Commons photos with their license
  noted in the description.
- **Naat audio**: a curated pool of Internet Archive albums whose uploaders
  declared **CC0 / Public-Domain-Mark / CC-BY** licenses, plus one CC-BY
  vocal-only nasheed on Wikimedia Commons. No-Derivatives (ND) and non-licensed
  commercial albums are deliberately excluded. Attribution is appended to every
  video description automatically.
- You are the publisher of your channel — YouTube’s policies (reused-content
  rules for monetization, community guidelines) apply to you as the account
  owner. This tool automates creation/upload only.

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| `invalid_grant` on upload | Refresh token expired/revoked → publish the OAuth app (step 1.3) and re-do step 3 |
| `quotaExceeded` | Daily API quota used up → max 6 uploads/day |
| No video in artifact | Open the job log — media provider hiccup; just re-run |
| Schedule not firing | Must be default branch + repo active (see above) |
| Wrong size/length | Constants at the top of `main.py` (`W, H, FPS`, `SLIDE_COUNT`, `SLIDE_DURATION`, `CROSSFADE`) |
