# WNTR:\\\\Project StarFire UFO Sighting Tracker — free public web app

A free website anyone can open (no sign-in, no payment) that shows a worldwide, sourced archive of UFO/UAP sighting reports.
It updates itself automatically: hourly on GitHub (free for public repos), twice a day on GitLab. **It uses no AI and no Grok usage.** A small Python program
reads public news and report feeds, keeps sighting reports, finds the place on a map, and publishes the site.

- **Map**: a 3D globe (MapLibre GL, satellite imagery to street level; 2D Leaflet map if WebGL is missing) with glowing dots for reports first found in the last 24 hours (red = civilian/unknown, blue = alleged testing,
  yellow = article says officials/military/police confirmed or identified something, hollow cyan = OSINT/context).
- **Latest**: everything found in the last 24 hours, including items with no location (never given made-up coordinates).
- **Archive**: every report ever found, permanent, with search and filters.
- **Flap Watch**: flags a cluster only when 3+ separate reports from 3+ different source sites fall within 150 km and
  72 hours. Otherwise it says "No confirmed flap".
- **Sources & About**: which feeds worked in the last sweep, the rules, and the limits.
- **Page views**: a small count at the top of the main page. Each live site (GitHub Pages and GitLab Pages) has its own count; a combined total is shown when both are available. The number comes from a public counter API (no signup). If the API is down, the count is hidden.

Every entry links to its source. Old links are re-checked and marked "no longer available" if the page returns 404/410.

---

## Running on GitLab (current live version)

**Live site:** https://wntr-e6040b.gitlab.io  ·  **Project:** https://gitlab.com/ProjectStarFire/wntr

- **Schedules:** two pipeline schedules run a sweep at **4 AM and 4 PM America/Denver** every day
  (Build > Pipeline schedules). Each run restores the previous archive from the live site, sweeps, and republishes.
- **Manual sweep:** Build > Pipelines > **New pipeline** > **New pipeline** (branch `main`). It takes about 2 minutes.
- **Free-plan limit:** GitLab gives **400 compute minutes a month**. Each sweep is time-boxed (`WNTR_TIME_BUDGET=180`
  seconds for fetching) and pip is cached, so a whole run takes about 1.5–2.5 minutes. Twice a day is roughly
  100–150 minutes a month, which leaves room for manual sweeps. Hourly sweeps would not fit (~1,500+ minutes).
  Check usage under your avatar > Edit profile > Usage quotas.
- Pages visibility must stay **Everyone** (Settings > General > Visibility > Pages) so anyone can open the site.
- Every push to `main` also runs a sweep; put `[skip ci]` in the commit message to avoid using minutes.

The GitHub instructions below still work if you ever move the app to GitHub.

---

## What you need to do on GitHub (about 15 minutes, one time)

You only need a web browser. Everything is free.

### 1. Make a free GitHub account
1. Go to https://github.com/signup
2. Enter an email, a password and a username. (Your username becomes part of the website address.)
3. Verify your email when GitHub sends you a code.

### 2. Create a public repository (a folder for the app)
1. Sign in, then click the **+** at the top right and pick **New repository**.
2. **Repository name**: `wntr` (or anything you like, no spaces).
3. Choose **Public**. (Public is required for free automatic updates and the free website.)
4. Tick **Add a README file**, then click **Create repository**.

### 3. Upload the app files
1. On your computer, unzip `wntr-app.zip`. You get a folder called `wntr-app`.
2. In your new repository on GitHub, click **Add file → Upload files**.
3. Open the `wntr-app` folder, select **everything inside it** (not the folder itself) and drag it into the GitHub page.
   - Hidden folder warning: the `.github` folder holds the automatic schedule. On a Mac press **Cmd+Shift+.** in Finder
     to show hidden files; on Windows choose **View → Show → Hidden items**. Make sure `.github` is included.
   - If drag-and-drop skips `.github`, see "If the .github folder didn't upload" below.
4. Scroll down and click **Commit changes**. Wait until the upload finishes.

### 4. Turn on the website (GitHub Pages)
1. In the repository, click **Settings** (top menu) → **Pages** (left menu).
2. Under **Build and deployment → Source**, choose **GitHub Actions**.
   (That's all on this page; there's nothing to save.)

### 5. Turn on the automatic sweeps (GitHub Actions)
1. Click the **Actions** tab at the top of the repository.
2. If you see a green button like **"I understand my workflows, go ahead and enable them"**, click it.
3. On the left click **Sweep and publish**. If there's a banner saying scheduled workflows are disabled, click **Enable workflow**.

### 6. Run the first sweep by hand
1. Still in **Actions → Sweep and publish**, click **Run workflow** (right side) → **Run workflow**.
2. Wait 10–15 minutes. A yellow dot means running; a green tick means done.
3. You can run a manual sweep like this any time.

### 7. Find your public website address
- Go to **Settings → Pages**. At the top it says **"Your site is live at …"**.
- It looks like `https://YOUR-USERNAME.github.io/wntr/`.

### 8. Share it
- Send that address to anyone. They don't need a GitHub account, an app, or any payment.
- On a phone, open the address and use **Share → Add to Home Screen** to get an app-like icon.

From now on GitHub runs the sweep automatically **every hour, on the hour** (`cron: "0 * * * *"`, UTC). Public repositories
get free, unlimited Actions minutes. Each run commits the updated `docs/data` and `state` back to the repo and redeploys Pages.
GitHub can start scheduled runs a few minutes late when its servers are busy. All paths are relative, so the site works under
the project subpath `https://USER.github.io/wntr/`.

---

## If something goes wrong

- **If the .github folder didn't upload:** in the repository click **Add file → Create new file**, type
  `.github/workflows/sweep.yml` as the name (typing the `/` makes folders), open `sweep.yml` from the zip in a text
  editor, copy everything, paste it in, and click **Commit changes**.
- **The run has a red X:** click the run, then the failed step to see the message. A failure in the **deploy** step
  usually means Pages isn't set to **GitHub Actions** (step 4). Fix it and click **Re-run all jobs**.
- **The site shows "Could not load data/events.json":** wait a minute and refresh; the first publish can lag.
- **Automatic runs stopped:** GitHub pauses schedules in public repos after 60 days without activity. The sweep's own
  data commits normally count as activity, but if you ever see a "disabled" banner in Actions, click **Enable workflow**.
- **Want a different schedule?** Edit `.github/workflows/sweep.yml` and change the `cron:` line (UTC).

## Evidence grades and Sky Check

- **Evidence grade (1–5)**, computed from each record only: 5 official/military/police confirmation of this report or
  radar/sensor data cited · 4 photo or video linked (or the cited post/article is the footage) · 3 two or more witnesses
  or separate reports stated · 2 first-hand witness (own report or named witness) · 1 single anonymous/second-hand claim.
  Then one step down for each missing basic: second-hand account with the original not opened, no sighting date, no
  location (never below 1). It grades documentation, not what the object was. Filter by grade on the Map and Archive tabs.
- **Sky Check** (for reports with a recorded time and place): Starlink and bright satellites/ISS (CelesTrak orbit data (OMM CSV, so new 6-digit catalog numbers are included) + SATCAT launch dates + SGP4,
  only within 14 days of the orbit data and only for precise locations), rocket launches within 1,600 km from 3 h before
  to 1 h after (Launch Library 2), Sun/Moon/bright planets (JPL DE421 via skyfield) and major meteor showers. Not checked:
  aircraft, re-entries, weather, balloons, drones. Results are possible explanations, not verdicts. Computed once per
  report and cached in the record; data files are cached in `.cache/sky` (CI cache).

## Costs and limits

- GitHub Actions and Pages are free for public repositories. One sweep takes roughly 1.5–3 minutes (fetching is concurrent and capped at 180 seconds).
- No API keys or accounts are needed besides your GitHub account.
- **What gets logged (same rule as the Grok Page):** only concrete, newly reported sightings - a described observation
  (lights, shape, motion) from a first-hand witness, a witness-report database, or local media relaying a resident's
  report/footage, tied to a place. Not logged: general UFO news, politics/disclosure/hearings, declassified files,
  documentaries/TV/podcasts, explainers and questions, opinion/theories, listicles, talks/events, and items that mention
  only past years. Military exercises, launches, re-entries and airspace closures are cyan context only. Everything left
  out is listed with its reasons in `docs/data/excluded.json` (the live site serves it at `data/excluded.json`).
- Rules aren't perfect: some places will be wrong or only approximate (a town or a state/region centre). Nothing is
  verified. Read the linked source.
- Some sites block automated reading from cloud servers (NUFORC, Reddit JSON; Reddit RSS is often rate
  limited). The sweep keeps going when a source fails and shows it in **Sources & About**.
- Google News links open through a Google redirect to the publisher's page.

---

## For technical readers

```
.github/workflows/sweep.yml   cron 0 11 * * * and 0 23 * * * + workflow_dispatch; commits data; deploys docs/ to Pages
scraper/sweep.py              concurrent fetch (16 workers, 10 s timeouts, WNTR_TIME_BUDGET=180 s; skipped sources logged)
                              → filter → geocode → classify → dedupe → link check → Flap Watch → docs/data/events.json
scraper/sources.py            every feed: Google News (60 editions, ~120 queries), Bing News (16 markets), Reddit RSS,
                              Mastodon tags, Open Minds + Liberation Times RSS, UFO Meldpunt Nederland
scraper/witness_sources.py    witness-report databases used by the Grok Page: Probed.space, Aliens.co.il sightings feed,
                              UFO Hunters, MUFON last-20 (each parser yields nothing rather than guessing if a site changes)
scraper/grading.py            evidence grade 1-5 with reasons (deterministic, record data only)
scraper/skycheck.py           Sky Check: satellites (SGP4), launches (LL2), Sun/Moon/planets (skyfield), meteor showers
scraper/classify.py           assess(): Grok-Page-equivalent screening (concrete sighting + place + source tier; rejects
                              stories/politics/TV/explainers/listicles/historical; context-only OSINT) and marker colour
scraper/seed-grok.json        hand-reviewed Grok Page records, merged into the archive by every sweep (refresh by
                              re-exporting from the Grok Page state)
docs/data/excluded.json       what the sweep read but did not log, with reasons (capped at 2,500 newest)
scraper/geo.py                offline GeoNames gazetteer (cities5000 + admin1), native-script names, optional Nominatim
                              fallback (≤10 lookups/run, 1 req/s, cached in state/geocache.json; WNTR_NO_NOMINATIM=1 disables)
scraper/import_seed.py        one-time import of the hand-reviewed Nov 2026 archive
scraper/build_gazetteer.py    rebuilds gazetteer.tsv / admin1.tsv / countries.tsv from GeoNames
docs/                         static site styled after the original Grok Page: index.html, app.js, style.css,
                              views.js (page-view counter via Count API, countapi.mileshilliard.com; one key per
                              platform, hidden if the API is down), livemap.js (zoomable satellite/dark/street/terrain
                              map), vendor/ (Leaflet 1.9.4 + Leaflet.markercluster 1.5.3, bundled; BSD-2 / MIT),
                              land.js (offline SVG fallback map)
docs/data/events.json         the archive the site loads (relative path)
state/                        geocoder cache and sweep log
.gitlab-ci.yml                GitLab 'pages' job: pip cache, restore archive from live site, sweep, publish public/
                              (link checks capped at 25/run, WNTR_LINKCHECK_CAP)
```

Run locally: `pip install -r requirements.txt && python scraper/sweep.py` then
`python -m http.server -d docs 8000` and open http://localhost:8000.
Options: `--quick` (fewer Google queries) and `--no-linkcheck`. `WNTR_NOMINATIM_CAP=0` turns off online geocoding.

Alternative hosting: Settings → Pages → **Deploy from a branch** → `main` / `/docs` also works (the site is plain
static files); then you can delete the `deploy` job from the workflow.

Code: MIT. Place data: GeoNames, CC BY 4.0. Linked articles belong to their publishers.

## Map tiles

The Map tab uses free, keyless tile servers: Esri World Imagery with Esri's boundaries-and-places labels (default
"Satellite (Earth view)"), CARTO dark_all ("Dark map"), Esri World Street Map and Esri World Topo Map. Attribution is
shown on the map. If Leaflet cannot load, the page falls back to the built-in SVG outline map.

## Branding

`docs/img/` holds the Project StarFire logo, only cropped, scaled and padded on its own dark background (#000719). It includes `banner-wide.png` (1600×400, desktop header) and `banner-compact.png` (960×300, phones). It also has `icon-512/192/180/32/16.png` and `favicon.ico`, which are the radar emblem crop. `og-1200x630.png` is the social-share image. `docs/manifest.webmanifest` lists the app icons.

## 3D globe

- `docs/globe.js` + `docs/vendor/maplibre` (MapLibre GL JS 5, BSD-3, bundled; no CDN or key) draw the Map tab as a globe:
  drag to rotate, scroll/pinch from the whole Earth to street level, Satellite (Esri World Imagery + Esri labels/roads),
  Dark (Esri Dark Gray Canvas) and Streets (Esri World Street Map). Markers keep their colours and meanings, cluster into
  numbered bubbles, and open a popup with the evidence grade and a Sky Check link. 🌐 resets the view, ⤢ fits all markers,
  ⟳ toggles a slow spin (off for reduced motion; stops when you touch the globe); the globe button flattens to 2D.
- No WebGL, or `?map=2d`: the Leaflet 2D map (`docs/livemap.js`) loads instead. Cluster numbers use a bundled glyph file
  (`docs/vendor/glyphs`). GitLab CI pre-compresses text files (`*.gz`) so the library downloads at ~280 KB.
