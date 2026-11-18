#!/usr/bin/env python3
"""WNTR UFO Sighting Archive - automated sweep. No AI, no API keys.

Reads public feeds, keeps UFO/UAP sighting reports with a source link, geocodes place
names offline, classifies marker colour by keyword rules, merges duplicates, checks old
links, recomputes Flap Watch, and writes docs/data/events.json.

    python scraper/sweep.py               # full sweep
    python scraper/sweep.py --quick       # fewer Google queries (testing)
    python scraper/sweep.py --no-linkcheck
"""
import argparse, hashlib, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait as fwait
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qs, urlunparse, unquote

import feedparser
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources as S
from classify import clean, _any, assess, EXCLUDE, UFO, SCREEN_VERSION
import witness_sources as W
from grading import grade, GRADE_VERSION
import skycheck as SK
import gate as GATE
from geo import Gazetteer, haversine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data", "events.json")
STATE = os.path.join(ROOT, "state")
REPO = os.environ.get("GITHUB_REPOSITORY", "local")
UA = f"WNTR-UFO-Archive/1.0 (open-source public sighting archive; https://github.com/{REPO})"
MAX_AGE_DAYS = 7
NOW = datetime.now(timezone.utc).replace(microsecond=0)
NOW_ISO = NOW.isoformat().replace("+00:00", "Z")

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8,*;q=0.5"})
status = {}  # source family -> stats
_lock = threading.Lock()
T0 = time.time()
TIME_BUDGET = float(os.environ.get("WNTR_TIME_BUDGET", "180"))   # seconds for the whole fetch phase
WORKERS = int(os.environ.get("WNTR_WORKERS", "16"))
LINKCHECK_CAP = int(os.environ.get("WNTR_LINKCHECK_CAP", "25"))
# max simultaneous requests per site family (be polite; Reddit and Mastodon rate-limit hard)
FAMILY_LIMIT = {"Google News": 8, "Bing News": 6, "Reddit": 1, "Mastodon": 2, "UFO Meldpunt Nederland": 3, "Aliens.co.il": 2, "Probed": 1, "UFO Hunters": 1, "MUFON": 1, "UFO*BC": 1, "GEIPAN": 1, "YouTube": 1, "Specialist UFO news RSS": 4}
_sems = {}

def stat(family, **kw):
    with _lock:
        s = status.setdefault(family, {"name": family, "requests": 0, "ok": 0, "failed": 0, "items": 0, "kept": 0, "skipped": 0, "errors": []})
        for k, v in kw.items():
            if k == "error":
                if len(s["errors"]) < 3:
                    s["errors"].append(v[:160])
            else:
                s[k] = s.get(k, 0) + v

def time_left():
    return TIME_BUDGET - (time.time() - T0)

def get(url, family, delay=0.0, retries=1, **kw):
    if time_left() <= 0:
        stat(family, skipped=1, error="overall time budget reached; remaining requests skipped this sweep")
        return None
    with _lock:
        sem = _sems.setdefault(family, threading.Semaphore(FAMILY_LIMIT.get(family, 4)))
    with sem:
        if delay and time_left() > 0:
            time.sleep(min(delay, max(0.0, time_left())))
        if time_left() <= 0:  # budget may have run out while queued behind other requests
            stat(family, skipped=1, error="overall time budget reached; remaining requests skipped this sweep")
            return None
        stat(family, requests=1)
        for attempt in range(retries + 1):
            try:
                r = session.get(url, timeout=(5, 10), **kw)
                if r.status_code in (429, 503) and attempt < retries and time_left() > 20:
                    time.sleep(4 * (attempt + 1))
                    continue
                if r.ok:
                    stat(family, ok=1)
                    return r
                stat(family, failed=1, error=f"HTTP {r.status_code} {url[:90]}")
                return None
            except Exception as e:
                if attempt >= retries or time_left() <= 10:
                    stat(family, failed=1, error=f"{type(e).__name__} {url[:90]}")
                    return None
                time.sleep(1)

def to_dt(entry):
    for k in ("published_parsed", "updated_parsed"):
        v = entry.get(k)
        if v:
            return datetime(*v[:6], tzinfo=timezone.utc)
    for k in ("published", "updated"):
        if entry.get(k):
            try:
                return parsedate_to_datetime(entry[k]).astimezone(timezone.utc)
            except Exception:
                pass
    return None

def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if dt else None

def norm_url(u):
    try:
        p = urlparse(u.strip())
        q = "&".join(x for x in p.query.split("&") if x and not re.match(r"(utm_|fbclid|gclid|ocid|cmpid|ref=)", x))
        host = p.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("old.")
        frag = p.fragment if p.fragment.startswith("case-") else ""   # MUFON list rows share one page
        rc = re.search(r"/comments/([a-z0-9]+)", p.path) if host.endswith("reddit.com") else None
        if rc:   # one Reddit post = one key, whatever slug/subdomain a relay used
            return "reddit.com/comments/" + rc.group(1)
        return urlunparse(("", host, p.path.rstrip("/"), "", q, frag))[2:]
    except Exception:
        return u

def domain(u):
    try:
        return urlparse(u).netloc.lower().removeprefix("www.")
    except Exception:
        return ""

STOP = set("the a an of in on at to for and or is are was were with from by over near after video photos watch new ufo uap ovni sighting sightings sky lights light de la el en y los las del un una o que se em do da no na os as um uma le les des du et à il di della che der die das und im den ein eine het een van op".split())

def tokens(t):
    return {w for w in re.findall(r"[\w']+", (t or "").lower()) if len(w) > 2 and w not in STOP}

def jacc(a, b):
    return len(a & b) / max(1, len(a | b))

# ---------------------------------------------------------------- fetchers
def feed_items(fetch, family, raw_name=None):
    r = get(fetch["url"], family, delay=fetch.get("delay", 0.2))
    if not r:
        return []
    d = feedparser.parse(r.content)
    out = []
    for e in d.entries:
        title = clean(e.get("title", ""))
        link = e.get("link", "")
        publisher = raw_name
        if family == "Google News":
            src = e.get("source") or {}
            publisher = src.get("title") if isinstance(src, dict) else None
            if publisher and title.endswith(" - " + publisher):
                title = title[: -len(publisher) - 3]
        if family == "Bing News":
            qs = parse_qs(urlparse(link).query)
            if "url" in qs:
                link = unquote(qs["url"][0])
            publisher = e.get("news_source") or domain(link)
        summary = clean(e.get("summary", "") or e.get("description", ""))
        if family == "Reddit":
            summary = summary.replace("submitted by", " | submitted by")[:600]
        out.append({"title": title, "summary": summary[:700], "url": link, "published": to_dt(e),
                    "publisher": publisher or domain(link), "family": family, "edition": fetch.get("edition"),
                    "region": fetch.get("region"), "topic_feed": fetch.get("topic_feed", False)})
    stat(family, items=len(out))
    return out

def mastodon_tag(tag):
    items = []
    r = get(f"https://mastodon.social/api/v1/timelines/tag/{tag}?limit=40", "Mastodon", delay=0.5)
    if not r:
        return items
    try:
        posts = r.json()
    except Exception:
        return items
    stat("Mastodon", items=len(posts))
    for p in posts:
        txt = clean(p.get("content", ""))
        if not txt or p.get("reblog"):
            continue
        items.append({"title": txt[:140], "summary": txt[:700], "url": p.get("url") or p.get("uri"),
                      "published": datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")) if p.get("created_at") else None,
                      "publisher": "Mastodon @" + (p.get("account", {}).get("acct", "?")) + " (user post)", "family": "Mastodon",
                      "edition": "#" + tag, "region": None, "topic_feed": True})
    return items

def fetch_tasks(quick, known):
    """Every source request as an independent (family, callable) task, run concurrently."""
    tasks = []
    g = list(S.google_news_feeds())
    if quick:
        g = g[::6]
    tasks += [("Google News", lambda f=f: feed_items(f, "Google News")) for f in g]
    tasks += [("Bing News", lambda f=f: feed_items(f, "Bing News")) for f in S.bing_feeds()]
    for sub in S.REDDIT_SUBS:
        f = {"url": f"https://www.reddit.com/r/{sub}/new/.rss?limit=50", "delay": 6, "topic_feed": True, "edition": "r/" + sub}
        tasks.append(("Reddit", lambda f=f, sub=sub: feed_items(f, "Reddit", raw_name=f"Reddit r/{sub} (user post)")))
    tasks += [("Mastodon", lambda t=t: mastodon_tag(t)) for t in S.MASTODON_TAGS]
    tasks += [("Specialist UFO news RSS", lambda n=n, u=u: feed_items({"url": u, "edition": n}, "Specialist UFO news RSS", raw_name=n))
              for n, u in S.EXTRA_RSS]
    tasks.append(("UFO Meldpunt Nederland", lambda: fetch_meldpunt(known)))
    # witness-report databases the Grok Page relies on
    tasks.append(("Probed", lambda: W.fetch_probed(get, stat)))
    tasks.append(("Aliens.co.il", lambda: W.fetch_aliens(get, stat, known, norm_url)))
    tasks.append(("UFO Hunters", lambda: W.fetch_ufo_hunters(get, stat)))
    tasks.append(("MUFON", lambda: W.fetch_mufon(get, stat)))
    tasks.append(("UFO*BC", lambda: W.fetch_ufobc(get, stat)))
    tasks.append(("GEIPAN", lambda: W.fetch_geipan(get, stat)))
    tasks.append(("YouTube", lambda: W.fetch_youtube(stat)))
    # Witness-report databases first (often have media / first-hand accounts), then
    # interleave the rest so a time-budget cut never starves one whole source family.
    priority = ("UFO Meldpunt Nederland", "Probed", "Aliens.co.il", "UFO Hunters", "MUFON", "UFO*BC", "GEIPAN", "YouTube")
    first = [x for x in tasks if x[0] in priority]
    rest = [x for x in tasks if x[0] not in priority]
    fams = {}
    for item in rest:
        fams.setdefault(item[0], []).append(item)
    order = sorted(fams.values(), key=len)
    out = list(first)
    while any(order):
        for lst in order:
            if lst:
                out.append(lst.pop(0))
    return out

def run_fetch(tasks):
    raw, per = [], {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fn): fam for fam, fn in tasks}
        for fu in as_completed(futs):
            fam = futs[fu]
            try:
                got = fu.result() or []
            except Exception as e:  # one broken source never stops the sweep
                stat(fam, failed=1, error=f"crash {type(e).__name__}: {e}")
                got = []
            per[fam] = per.get(fam, 0) + len(got)
            raw += got
    for fam, n in per.items():
        print(f"{fam}: {n} raw items", flush=True)
    return raw

def fetch_meldpunt(known_urls):
    r = get(S.MELDPUNT_HOME, "UFO Meldpunt Nederland")
    if not r:
        return []
    links = []
    for m in re.finditer(r'href="(https://www\.ufomeldpunt\.nl/melding/\d+-[^"#]+)"', r.text):
        if m.group(1) not in links:
            links.append(m.group(1))
    stat("UFO Meldpunt Nederland", items=len(links))
    out = []
    todo = [l for l in links[:20] if norm_url(l) not in known_urls]
    with ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda l: (l, get(l, "UFO Meldpunt Nederland", delay=0.3)), todo))
    for link, p in pages:
        if not p:
            continue
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", p.text, flags=re.S)
        txt = clean(t)
        title = clean(re.search(r"<title>(.*?)</title>", p.text, re.S).group(1)).split(" - UFO Meldpunt")[0] if "<title>" in p.text else link
        when = re.search(r"Wanneer (\d{1,2} \w+ \d{4})(?: \((\d{1,2}:\d{2})\))?", txt)
        where = re.search(r"Waar (.+?)(?: , bewoog| Status|$)", txt)
        wat = re.search(r"Wat (.+?) Wanneer", txt)
        body = txt.split("Alle details weergeven", 1)[-1]
        body = body.split("Bekijk het vliegverkeer op moment van waarneming.", 1)[-1]
        body = re.split(r" Top 3 ufo-boeken| Reacties | Plaats een melding", body)[0].strip()[:700]
        months = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
        months.update({m: i for i, m in enumerate(["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"], 1)})
        dt = None
        if when:
            try:
                d, mo, y = when.group(1).split()
                hh, mm = (when.group(2) or "12:00").split(":")
                from zoneinfo import ZoneInfo
                dt = datetime(int(y), months[mo.lower()], int(d), int(hh), int(mm), tzinfo=ZoneInfo("Europe/Amsterdam")).astimezone(timezone.utc)
            except Exception:
                dt = None
        out.append({"title": title, "summary": ((wat.group(1) + ". ") if wat else "") + body, "url": link, "published": dt,
                    "publisher": "UFO Meldpunt Nederland (witness report)", "family": "UFO Meldpunt Nederland", "edition": "NL",
                    "region": "NL", "topic_feed": True, "place_hint": where.group(1).strip() + ", Netherlands" if where else None,
                    "event_local": (when.group(1) + (" " + when.group(2) if when.group(2) else "")) if when else None,
                    "event_tz": "Europe/Amsterdam", "forced_kind": "sighting", "reporterType": "civilian"})
    return out

# ---------------------------------------------------------------- link check
def _probe(url):
    try:
        h = session.head(url, timeout=(5, 8), allow_redirects=True)
        code = h.status_code
        if code in (403, 405, 400, 501):
            g = session.get(url, timeout=(5, 8), allow_redirects=True, stream=True)
            code = g.status_code
            g.close()
        return code
    except Exception:
        return None

def link_check(reports, limit=None):
    limit = LINKCHECK_CAP if limit is None else limit
    cands = []
    for r in reports:
        for s in r.get("sources", []):
            if not s.get("url", "").startswith("http"):
                continue
            av = s.setdefault("availability", {"status": "unchecked"})
            last = av.get("lastCheckedAt") or "1970-01-01T00:00:00Z"
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if NOW - last_dt < timedelta(days=3):
                    continue
            except Exception:
                pass
            cands.append((last, s))
    cands.sort(key=lambda x: x[0])
    picked = [s for _, s in cands[:limit]]
    checked = flagged = 0
    ex = ThreadPoolExecutor(max_workers=10)
    futs = {ex.submit(_probe, s["url"]): s for s in picked}
    done, _ = fwait(futs, timeout=40)
    ex.shutdown(wait=False, cancel_futures=True)
    for fu in done:
        s, code = futs[fu], fu.result()
        av = s["availability"]
        av["lastCheckedAt"] = NOW_ISO
        av["httpStatus"] = code
        checked += 1
        if code in (404, 410):
            if av.get("status") != "unavailable":
                av["firstUnavailableAt"] = NOW_ISO
                flagged += 1
            av["status"] = "unavailable"
            av["reason"] = f"HTTP {code}: source no longer available"
        elif code and 200 <= code < 400:
            av["status"] = "available"
            av["reason"] = "HTTP success (does not verify the claim)"
        else:
            av.setdefault("status", "unchecked")
            av["reason"] = f"inconclusive ({code or 'no response'}); not flagged"
    stat("Link check", requests=checked, items=checked, kept=flagged)
    return checked, flagged

# ---------------------------------------------------------------- flap watch
def parse_time(r):
    v = r.get("eventDate") or ""
    m = re.match(r"(\d{4}-\d\d-\d\d)", v)
    if r.get("origin") == "seed" and m:
        return datetime.fromisoformat(m.group(1) + "T12:00:00+00:00")
    for k in ("eventAt", "publishedAt", "sweptAt"):
        v = r.get(k)
        if v and re.match(r"\d{4}-\d\d-\d\dT", v):
            try:
                d = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    v = r.get("eventDate") or ""
    m = re.match(r"(\d{4}-\d\d-\d\d)", v)
    if m:
        return datetime.fromisoformat(m.group(1) + "T12:00:00+00:00")
    return None

def pub_key(s):
    d = domain(s.get("url", ""))
    if not d or d in ("news.google.com", "bing.com", "msn.com"):
        return (s.get("name") or d or "?").lower().split(" (")[0]
    return d

def same_story(group):
    """True when one distinctive word appears in most member titles: one story retold, not a flap."""
    from collections import Counter
    c = Counter()
    for r, _, _ in group:
        place_words = tokens(r.get("place") or "")
        c.update(w for w in tokens(r.get("title")) if len(w) >= 5 and w not in place_words)
    return bool(c) and c.most_common(1)[0][1] >= max(3, 0.6 * len(group))

def flap_watch(reports, radius_km=150, hours=72, min_sources=3, lookback_days=10):
    pts = []
    for r in reports:
        if r.get("kind") != "sighting" or r.get("lat") is None:
            continue
        t = parse_time(r)
        if not t or NOW - t > timedelta(days=lookback_days):
            continue
        doms = {pub_key(s) for s in r.get("sources", [])}
        pts.append((r, t, doms))
    def near(a, b):
        return abs((a[1] - b[1]).total_seconds()) <= hours * 3600 and haversine(a[0]["lat"], a[0]["lon"], b[0]["lat"], b[0]["lon"]) <= radius_km
    # every member must be within radius/time of the cluster's anchor report (no chaining)
    cands = []
    for i, p in enumerate(pts):
        mem = [q for q in pts if near(p, q)]
        doms = set().union(*[x[2] for x in mem])
        if len(mem) >= min_sources and len(doms) >= min_sources:
            cands.append((len(doms), len(mem), i, mem, doms))
    cands.sort(key=lambda c: (-c[0], -c[1]))
    used, clusters, skipped_story = set(), [], []
    for nd, nm, i, mem, doms in cands:
        mem = [x for x in mem if x[0]["id"] not in used]
        doms = set().union(*[x[2] for x in mem]) if mem else set()
        if len(mem) < min_sources or len(doms) < min_sources:
            continue
        if same_story(mem):
            skipped_story.append(sorted({x[0].get("place") or "" for x in mem})[:3])
            used.update(x[0]["id"] for x in mem)
            continue
        used.update(x[0]["id"] for x in mem)
        g = mem
        lat = sum(x[0]["lat"] for x in g) / len(g)
        lon = sum(x[0]["lon"] for x in g) / len(g)
        ts = sorted(x[1] for x in g)
        clusters.append({"center": [round(lat, 3), round(lon, 3)], "reports": len(g), "independentSources": len(doms),
                         "places": sorted({x[0].get("place") or "" for x in g})[:12], "ids": [x[0]["id"] for x in g],
                         "from": iso(ts[0]), "to": iso(ts[-1]), "sourceDomains": sorted(doms)[:15]})
    clusters.sort(key=lambda c: -c["reports"])
    return {"checkedAt": NOW_ISO, "confirmed": bool(clusters), "clusters": clusters, "setAsideSameStory": skipped_story,
            "rule": f"Automatic flag only when {min_sources}+ separate sighting reports from {min_sources}+ different source sites fall within {radius_km} km and {hours} hours of each other (last {lookback_days} days). "
                    "Groups where most titles retell one story (same distinctive word) are set aside as one event, not a flap. This is a screening rule, not proof that anything unusual happened; one widely syndicated story can still trip it, so read the sources.",
            "summary": None if not clusters else f"{len(clusters)} cluster(s) met the rule; largest: {clusters[0]['reports']} reports near {', '.join(clusters[0]['places'][:3])}."}


# ---------------------------------------------------------------- screening helpers (Grok-Page-equivalent rules)
EXCLUDED = os.path.join(ROOT, "docs", "data", "excluded.json")
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed-grok.json")
EXCLUDED_CAP = 2500

def make_src(it, url, pub, relay=False):
    role = "original report" if (it.get("structured") or it["family"] in ("Reddit", "UFO Meldpunt Nederland")) else "media report"
    if relay and role == "media report":
        role = "media republish"
    return {"name": it.get("publisher") or domain(url), "url": url, "published": iso(pub), "role": role,
            "title": it["title"][:200], "via": it["family"] + (f" / {it['edition']}" if it.get("edition") else ""), "accessed": NOW_ISO,
            "availability": {"status": "available", "lastCheckedAt": NOW_ISO, "httpStatus": 200, "reason": "listed in feed at sweep time"}}

PERSON_OF = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+(?:, | )(?:of|from|de|da|di|aus|van)\b")

def place_text(it):
    """Title + summary without the publisher's name (Google News appends it) and without 'Firstname Lastname, of' person names."""
    t = it.get("title", "") + ". " + (it.get("summary") or "")
    pub = (it.get("publisher") or "").strip()
    if pub and len(pub) > 2:
        t = t.replace(pub, " ")
    return PERSON_OF.sub(lambda m: m.group(0).split()[-1], t)

GENERIC = set("object objects mysterious mystery strange spotted filmed captured sighted sighting sightings bizarre unidentified video footage lights flying "
              "military airbase report reported witness witnesses objeto misterioso extraño captan avistamiento oggetto misterioso avvistato".split())

def same_event(a_toks, a_lat, a_lon, r):
    """Same story at the same place (within 60 km): overlapping title words, or one shared distinctive word (e.g. 'jellyfish')."""
    if a_lat is None or r.get("lat") is None:
        return False
    if haversine(a_lat, a_lon, r["lat"], r["lon"]) > 60:
        return False
    rt = r.get("_toks") or tokens(r.get("title"))
    if jacc(a_toks, rt) >= 0.15:
        return True
    pw = tokens(r.get("place") or "")
    return any(len(w) >= 6 and w not in GENERIC and w not in pw for w in (a_toks & rt))

def _confident_place(place, family=None):
    """YouTube titles often capitalize ordinary words; only keep a pin with real context."""
    if not place:
        return None
    if (family or "") != "YouTube":
        return place
    sig = place.get("context_signals") or {}
    if sig.get("prep") or sig.get("admin") or sig.get("country_mentioned"):
        return place
    return None

def locate_item(gaz, it):
    hint = it.get("place_hint")
    place = None
    fam = it.get("family")
    if hint:
        place = gaz.locate(hint, it.get("region"))
        if not place and it.get("probed_lat") is None:
            place = gaz.locate(hint + ".", it.get("region"))
    if it.get("probed_lat") is not None and it.get("probed_lon") is not None:
        plat, plon = float(it["probed_lat"]), float(it["probed_lon"])
        if place and haversine(place["lat"], place["lon"], plat, plon) <= 150:
            return _confident_place(place, fam) or place
        p = dict(place) if place and haversine(place["lat"], place["lon"], plat, plon) <= 1500 else {}
        p.update({"lat": round(plat, 4), "lon": round(plon, 4), "place": hint or p.get("place") or "location named in post",
                  "precision": f"approximate: Probed.space geocode of the place named in the post ('{hint}'); not a witness-provided position", "gid": None,
                  "context_signals": {"prep": True, "admin": False, "country_mentioned": True}})
        return p
    if not place:
        place = gaz.locate(place_text(it), it.get("region"))
    return _confident_place(place, fam)

def recheck_auto_locations(reports, gaz):
    """Clear automatic pins the current gazetteer no longer stands behind (stoplist / weak YouTube titles)."""
    n = 0
    for r in reports:
        if r.get("origin") != "auto" or r.get("lat") is None:
            continue
        s0 = (r.get("sources") or [{}])[0]
        fam = (r.get("feed") or "").split(" / ")[0]
        it = {"title": r.get("title") or "", "summary": r.get("summary") or "",
              "publisher": s0.get("name") or "", "family": fam}
        place = locate_item(gaz, it)
        same = False
        if place:
            if r.get("gid") and place.get("gid") == r.get("gid"):
                same = True
            elif haversine(place["lat"], place["lon"], r["lat"], r["lon"]) <= 50:
                same = True
        if same:
            continue
        from geo import COMMON
        m = re.search(r"match on '([^']+)'", r.get("precision") or "")
        matched = m.group(1).lower() if m else ""
        if fam == "YouTube" or matched in COMMON or (not place and "gazetteer match" in (r.get("precision") or "")):
            for k in ("lat", "lon", "place", "country", "continent", "gid", "tz"):
                r[k] = None
            r["precision"] = "no location found in source text; earlier automatic placement removed (ambiguous or stoplisted place name)"
            n += 1
    return n

def appearance_of(it, summary):
    st = it.get("structured") or {}
    bits = []
    if st.get("shape"):
        bits.append(f"Shape: {st['shape']}")
    if st.get("witness_count"):
        bits.append(f"{st['witness_count']} witness(es) per post")
    if st.get("duration_s"):
        bits.append(f"duration about {round(st['duration_s'] / 60)} min per post" if st["duration_s"] >= 60 else f"duration about {st['duration_s']} s per post")
    lead = re.split(r"(?<=[.!?])\s", summary or "", maxsplit=1)[0][:240]
    return "; ".join(bits + ([lead] if lead else [])) or None

def screening_record(a):
    return {"rules": "v%d Grok-Page-equivalent screening" % SCREEN_VERSION, "decision": a["decision"], "score": a.get("score"),
            "sourceTier": a.get("tierBasis"), "reasons": a.get("reasons", [])[:8], "at": NOW_ISO}

def load_excluded():
    if os.path.exists(EXCLUDED):
        try:
            with open(EXCLUDED, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"about": "Items the automatic sweep read but did NOT log as sightings, with the rule reasons. Kept so nothing is silently lost; not shown on the map.",
            "items": []}

def log_excluded(ex, it, url, pub, a, record=None):
    e = {"title": (it.get("title") or "")[:220], "url": url, "publisher": it.get("publisher") or domain(url), "published": iso(pub) if pub else it.get("publishedAt"),
         "family": it.get("family") or it.get("feed"), "decision": "excluded", "score": a.get("score"), "reasons": a.get("reasons", [])[:8], "excludedAt": NOW_ISO}
    if record is not None:
        e["formerRecord"] = record
    ex["items"].insert(0, e)

def save_excluded(ex):
    # Distinct report ids always stay (shared listing-page URLs must not collapse
    # separate sightings). Id-less screening rows still dedupe by URL.
    ex["items"] = GATE.merge_excluded_items(ex.get("items") or [], normalize_url=norm_url)[:EXCLUDED_CAP]
    ex["updatedAt"] = NOW_ISO
    ex["rules"] = RULES_TEXT
    tmp = EXCLUDED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ex, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, EXCLUDED)

RULES_TEXT = ("Same inclusion rule as the Grok Page: log only a concrete, newly reported sighting - a described observation (lights, shape, motion) "
              "with a first-hand witness, a witness-report database entry, or local media relaying a resident's report or footage - tied to a place. "
              "Not logged: general UFO news, politics/disclosure/hearings, declassified files, documentaries/TV/podcasts, explainers and questions, "
              "opinion/theories, listicles, events/talks, and anything that mentions only past years (historical rehash). Military exercises, launches, "
              "re-entries and airspace closures are context rings only, never proof. Witness databases rank above news; aggregator/entertainment sites "
              "need much stronger signals. Duplicates and reposts are merged as extra sources. A logged sighting must have a reported location, and if its evidence grade is 2 or below it also needs two or more independent corroborating reports (not republishes of one clip).")

def rescreen(reports, excluded, gaz):
    """Apply the current rules to automatic records from older sweeps (idempotent). Hand-reviewed seed records are kept as-is."""
    kept, out_n, changed, into_seed = [], 0, 0, 0
    seed_keys = {norm_url(s.get("url", "")) for r in reports if r.get("origin") == "seed" for s in r.get("sources", []) if s.get("url")}
    seed_keys.discard("")
    for r in reports:
        if r.get("origin") == "auto" and any(norm_url(s.get("url", "")) in seed_keys for s in r.get("sources", []) if s.get("url")):
            into_seed += 1   # same report already in the hand-reviewed Grok Page records: keep the reviewed one
            continue
        if r.get("origin") != "auto" or r.get("screenVersion") == SCREEN_VERSION:
            kept.append(r)
            continue
        s0 = (r.get("sources") or [{}])[0]
        fam = (r.get("feed") or "").split(" / ")[0]
        # re-check automatic geocodes against the cleaned text (publisher names and person names caused bad dots)
        if r.get("lat") is not None and r.get("place"):
            m = re.search(r"match on '([^']+)'", r.get("precision") or "")
            clean_t = place_text({"title": r.get("title", ""), "summary": r.get("summary", ""), "publisher": s0.get("name", "")})
            if m and m.group(1) not in clean_t:
                for k in ("lat", "lon", "place", "country", "continent", "gid"):
                    r[k] = None
                r["precision"] = "no reliable location in source text; earlier automatic placement removed (matched a publisher or person name)"
        place = {"precision": r.get("precision") or "", "gid": r.get("gid")} if r.get("lat") is not None else None
        st = {"is_report": True} if fam in ("UFO Meldpunt Nederland", "Probed", "Aliens.co.il", "UFO Hunters", "MUFON") else {}
        a = assess(r.get("title", ""), r.get("summary", ""), publisher=s0.get("name", ""), url=s0.get("url", ""), family=fam, place=place,
                   now_year=NOW.year, structured=st)
        if a["decision"] == "exclude":
            log_excluded(excluded, {"title": r.get("title"), "publisher": s0.get("name"), "family": fam, "publishedAt": r.get("publishedAt")},
                         s0.get("url"), None, a, record={k: r[k] for k in ("id", "kind", "marker", "sweptAt", "place", "lat", "lon", "sources") if k in r})
            out_n += 1
            continue
        r["kind"] = "sighting" if a["decision"] == "sighting" else "context"
        r["marker"], r["markerBasis"] = a["marker"], a["basis"] + " (re-screened)"
        if r["kind"] == "sighting":
            r["evidence"] = a.get("evidence")
        r["screening"], r["screenVersion"] = screening_record(a), SCREEN_VERSION
        changed += 1
        kept.append(r)
    # merge older duplicates of one story at one place (same rule the sweep uses for new items)
    final, merged = [], 0
    for r in kept:
        hit = None
        if r.get("origin") == "auto" and r.get("lat") is not None:
            tk = tokens(r.get("title"))
            for f in final:
                if f.get("origin") == "auto" and f.get("kind") == r.get("kind") and same_event(tk, r["lat"], r["lon"], f) and \
                        abs((parse_time(f) or NOW) - (parse_time(r) or NOW)) <= timedelta(days=7):
                    hit = f
                    break
        if hit:
            have = {norm_url(s.get("url", "")) for s in hit["sources"]}
            for s in r.get("sources", []):
                if norm_url(s.get("url", "")) not in have:
                    s = dict(s); s["role"] = "media republish" if s.get("role") == "media report" else s.get("role")
                    hit["sources"].append(s)
            merged += 1
            continue
        final.append(r)
    return final, {"excluded": out_n, "reclassified": changed, "mergedDuplicates": merged, "sameAsReviewedRecord": into_seed}

def sync_seed(reports):
    """Add hand-reviewed Grok Page records (scraper/seed-grok.json) that the archive lacks; refresh seed records in place."""
    if not os.path.exists(SEED):
        return 0
    with open(SEED, encoding="utf-8") as f:
        seed = json.load(f).get("reports", [])
    idx = {r["id"]: i for i, r in enumerate(reports)}
    n = 0
    for s in seed:
        if s["id"] in idx:
            old = reports[idx[s["id"]]]
            if old.get("origin") == "seed":
                av = {norm_url(x.get("url", "")): x.get("availability") for x in old.get("sources", [])}
                for x in s.get("sources", []):   # keep link-check history
                    if av.get(norm_url(x.get("url", ""))):
                        x["availability"] = av[norm_url(x.get("url", ""))]
                if old.get("skyCheck") and all(old.get(k) == s.get(k) for k in ("eventDate", "eventTimeLocal", "tz", "lat", "lon", "precision")):
                    s["skyCheck"] = old["skyCheck"]   # same time/place: keep the result computed with orbit data of that time
                reports[idx[s["id"]]] = s
        else:
            reports.append(s); n += 1
    return n

def run_sky_checks(reports, args, cap=None):
    cap = int(os.environ.get("WNTR_SKY_CAP", "300")) if cap is None else cap
    if args.no_sky:
        return {"skipped": "disabled"}
    todo = [r for r in reports if r.get("kind") == "sighting" and SK.needs_check(r, NOW)]
    todo.sort(key=lambda r: (
        0 if GATE.has_media(r) else 1,
        -((r.get("grade") or {}).get("level") or 0),
        r.get("sweptAt") or "",
    ))
    todo = todo[:cap]
    if not todo:
        return {"computed": 0}
    t0 = time.time()
    def fetch(url):
        try:
            r = session.get(url, timeout=(10, 60))
            return r if r.ok else None
        except Exception:
            return None
    sky = SK.Sky(os.environ.get("WNTR_SKY_CACHE", os.path.join(ROOT, ".cache", "sky")), get=fetch)
    n = checked = 0
    for r in todo:
        if time.time() - t0 > float(os.environ.get("WNTR_SKY_BUDGET", "120")):
            break
        r["skyCheck"] = SK.sky_check(sky, r, NOW)
        n += 1
        checked += r["skyCheck"]["status"] == "checked"
    return {"computed": n, "withTimeAndPlace": checked, "seconds": round(time.time() - t0), "notes": sky.notes[:5]}

# ---------------------------------------------------------------- main
def load():
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    return {"meta": {}, "reports": [], "flapWatch": {}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-linkcheck", action="store_true")
    ap.add_argument("--no-fetch", action="store_true", help="only apply seed sync + re-screening (testing)")
    ap.add_argument("--no-sky", action="store_true", help="skip Sky Check")
    args = ap.parse_args()
    os.makedirs(STATE, exist_ok=True)
    db = load()
    reports = db.get("reports", [])
    gaz = Gazetteer(os.path.join(STATE, "geocache.json"), nominatim_cap=int(os.environ.get("WNTR_NOMINATIM_CAP", "10")), user_agent=UA)
    excluded = load_excluded()
    seed_added = sync_seed(reports)
    reports, rescreen_stats = rescreen(reports, excluded, gaz)
    loc_fixed = recheck_auto_locations(reports, gaz)
    print(f"seed records added: {seed_added}; re-screen: {rescreen_stats}; stale geocodes cleared: {loc_fixed}", flush=True)
    excluded_urls = {norm_url(e["url"]) for e in excluded["items"] if e.get("url")}
    by_id = {r["id"]: r for r in reports}
    # Gate-excluded sightings stay eligible to receive a new independent source (and maybe come back).
    gate_held = {}
    for item in excluded.get("items") or []:
        rec = item.get("formerRecord") if isinstance(item, dict) and item.get("gate") else None
        if isinstance(rec, dict) and rec.get("id") and rec["id"] not in by_id:
            by_id[rec["id"]] = rec
            rec["_gateHeld"] = True
            gate_held[rec["id"]] = item
            if (rec.get("sweptAt") or "") >= iso(NOW - timedelta(days=7))[:10]:
                pass  # added to recent below once recent exists
    known = {}
    for r in list(reports) + [by_id[i] for i in gate_held]:
        for s in r.get("sources", []):
            if s.get("url"):
                known[norm_url(s["url"])] = r["id"]

    tasks = [] if args.no_fetch else fetch_tasks(args.quick, known)
    print(f"Fetching {len(tasks)} source requests with {WORKERS} workers, budget {TIME_BUDGET:.0f}s", flush=True)
    raw = run_fetch(tasks)
    print(f"Fetch phase done in {time.time() - T0:.0f}s, {len(raw)} raw items", flush=True)
    def _media_rank(it):
        st = it.get("structured") or {}
        if st.get("media") or it.get("mediaAttached"):
            return 0
        text = (it.get("title") or "") + " " + (it.get("summary") or "")
        if re.search(r"\b(?:video|footage|photo|photograph|clip|filmed|dashcam|vídeo|foto)\b", text, re.I):
            return 1
        return 2
    raw.sort(key=_media_rank)

    recent = [r for r in reports if r.get("kind") in ("sighting", "context") and (r.get("sweptAt") or "") >= iso(NOW - timedelta(days=7))[:10]]
    cutoff7 = iso(NOW - timedelta(days=7))[:10]
    for rec in [by_id[i] for i in gate_held]:
        if rec not in recent and rec.get("kind") in ("sighting", "context", None) and (rec.get("sweptAt") or "") >= cutoff7:
            recent.append(rec)
    added = merged = skipped_old = dropped = 0
    for it in raw:
        url = it.get("url")
        if not url or not it.get("title"):
            continue
        key = norm_url(url)
        alt = norm_url(it["alt_url"]) if it.get("alt_url") else None
        if key in known or key in excluded_urls:
            continue
        if alt and alt in known:   # same witness post already logged via another relay -> add this relay as a source
            dup = by_id.get(known[alt])
            if dup is not None and not any(norm_url(s["url"]) == key for s in dup["sources"]):
                dup["sources"].append(make_src(it, url, it.get("published"), relay=True))
                known[key] = dup["id"]; merged += 1
            continue
        pub = it.get("published")
        if pub and NOW - pub > timedelta(days=MAX_AGE_DAYS):
            skipped_old += 1
            continue
        title, summary = it["title"], it.get("summary", "")
        ctext = (title + " . " + summary).lower()
        # cheap pre-filter before geocoding: off-topic/entertainment, or no UFO wording on a general news feed
        if _any(EXCLUDE, ctext) or (not _any(UFO, ctext) and not it.get("structured") and it["family"] not in ("UFO Meldpunt Nederland", "UFO*BC", "GEIPAN")):
            dropped += 1
            continue
        toks = tokens(title)
        dup = None
        for r in recent:
            if jacc(toks, r.get("_toks") or tokens(r.get("title"))) >= 0.55:
                dup = r
                break
        structured = dict(it.get("structured") or {})
        if it["family"] == "UFO Meldpunt Nederland":
            structured["is_report"] = True
        # screen once assuming the best case (a precise place); only geocode items that could still qualify
        a0 = assess(title, summary, publisher=it.get("publisher") or domain(url), url=url, family=it["family"],
                    place={"precision": "city", "gid": "probe"}, now_year=NOW.year, structured=structured)
        if a0["decision"] == "exclude" and dup is None:
            a0["reasons"] = [x for x in a0["reasons"] if x != "named place"]
            log_excluded(excluded, it, url, pub, a0)
            excluded_urls.add(key)
            dropped += 1
            continue
        place = None if dup else locate_item(gaz, it)
        a = assess(title, summary, publisher=it.get("publisher") or domain(url), url=url, family=it["family"], place=place,
                   now_year=NOW.year, structured=structured)
        if dup is None and place and a["decision"] != "exclude":
            for r in recent:
                if r.get("kind") == ("sighting" if a["decision"] == "sighting" else "context") and same_event(toks, place["lat"], place["lon"], r):
                    dup = r
                    break
        if dup is not None and a["decision"] != "exclude":
            if not any(norm_url(s["url"]) == key for s in dup["sources"]):
                dup["sources"].append(make_src(it, url, pub, relay=True))
                if a.get("marker") == "yellow" and dup.get("marker") == "red":
                    dup["marker"], dup["markerBasis"] = "yellow", a["basis"] + " (from an added source)"
            known[key] = dup["id"]
            merged += 1
            continue
        if a["decision"] == "exclude":
            # YouTube: a first-hand-looking video with no confident place still becomes
            # a sighting record so the admission gate can exclude it as no-location
            # (not only a screening drop). Compilations and off-topic titles stay screened out.
            if it.get("family") == "YouTube" and a0.get("decision") != "exclude" and dup is None:
                a = dict(a0)
                a["reasons"] = [x for x in (a.get("reasons") or []) if x != "named place"]
                a["reasons"].append("no confident place in title/description; left unmapped for the admission gate")
            else:
                log_excluded(excluded, it, url, pub, a)
                excluded_urls.add(key)
                dropped += 1
                continue
        kind = "sighting" if a["decision"] == "sighting" else "context"
        rid = "auto-" + hashlib.sha1(key.encode()).hexdigest()[:12]
        ev_local = it.get("event_local")
        rep = {"id": rid, "origin": "auto", "kind": kind, "marker": a["marker"], "markerBasis": a["basis"],
               "title": title[:220], "summary": summary[:700], "appearance": appearance_of(it, summary) if kind == "sighting" else None,
               "evidence": a.get("evidence") if kind == "sighting" else "Context item, not a sighting",
               "screening": screening_record(a), "screenVersion": SCREEN_VERSION,
               "reporterType": it.get("reporterType", "unknown"),
               "reporterTypeBasis": "Member of the public on a civilian reporting site" if it.get("reporterType") else "Automated sweep cannot verify who the witness is",
               "publishedAt": iso(pub), "eventAt": iso(pub) if ev_local and not it.get("event_date") else None,
               "eventDate": it.get("event_date") or (ev_local[:10] if ev_local and re.match(r"\d{4}-\d\d-\d\d", ev_local) else (iso(pub)[:10] if pub else None)),
               "eventTimeLocal": ev_local,
               "timeBasis": "Witness-reported sighting date/time" if ev_local else "Publication time (sighting time not parsed)",
               "sweptAt": NOW_ISO, "sources": [make_src(it, url, pub)], "feed": it["family"] + (f" / {it['edition']}" if it.get("edition") else ""),
               "lat": place["lat"] if place else None, "lon": place["lon"] if place else None,
               "place": place["place"] if place else None, "country": place.get("country") if place else None,
               "continent": place.get("continent") if place else None, "tz": (place.get("tz") if place else None) or it.get("event_tz"),
               "precision": place["precision"] if place else "no location found in source text; not mapped", "gid": place.get("gid") if place else None}
        if structured.get("shape"):
            rep["shapeHint"] = structured["shape"]
        if structured.get("witness_count"):
            rep["witnessCount"] = structured["witness_count"]
        if structured.get("media"):
            rep["mediaAttached"] = True
        if structured.get("probed_context"):
            rep["explanations"] = ["Probed.space context note: " + x for x in structured["probed_context"][:3]]
        if it.get("alt_url"):
            rep["sources"].append({"name": "Original post (as linked by " + it["family"] + ")", "url": it["alt_url"], "role": "original report",
                                   "via": it["family"], "accessed": NOW_ISO, "note": "Link taken from the relay page; may be blocked to automated readers",
                                   "availability": {"status": "unchecked"}})
            known[alt] = rid
        reports.append(rep)
        by_id[rid] = rep
        rep["_toks"] = toks
        recent.append(rep)
        known[key] = rid
        added += 1
        stat(it["family"], kept=1)

    for r in reports:
        r.pop("_toks", None)

    # evidence grade for every sighting (cheap, deterministic), including gate-held copies we may re-admit
    for r in reports + [by_id[i] for i in gate_held if by_id[i] not in reports]:
        if r.get("kind") == "sighting":
            r["grade"] = grade(r)
        r.pop("_gateHeld", None)
    # If a held record gained a new source during this sweep, put it back in reports so apply_gate can re-admit it.
    for rid, item in list(gate_held.items()):
        rec = by_id.get(rid)
        if rec is not None and rec not in reports:
            reports.append(rec)
    reports, excluded["items"], gate_stats = GATE.apply_gate(
        reports, excluded.get("items") or [],
        sighting=lambda r: (r.get("kind") or "sighting") == "sighting",
    )
    print("admission gate:", gate_stats, flush=True)
    sky_stats = run_sky_checks(reports, args)
    print("sky check:", sky_stats, flush=True)
    lc = (0, 0) if args.no_linkcheck else link_check(reports)
    gaz.save_cache()
    fw = flap_watch(reports)
    reports.sort(key=lambda r: (r.get("sweptAt") or "", r.get("publishedAt") or ""), reverse=True)
    window_start = iso(NOW - timedelta(hours=24))
    def ts(r):
        v = r.get("sweptAt") or ""
        try:
            return iso(datetime.fromisoformat(v.replace("Z", "+00:00")))
        except Exception:
            return v
    last24 = [r for r in reports if ts(r) >= window_start]
    meta = db.get("meta", {})
    meta.update({
        "title": "WNTR:\\\\Project StarFire UFO Sighting Tracker",
        "generatedBy": "scraper/sweep.py (rule-based, no AI)",
        "lastSweepAt": NOW_ISO,
        "sweepCount": int(meta.get("sweepCount", 0)) + 1,
        "reportCount": len(reports),
        "mappedLast24h": sum(1 for r in last24 if r.get("lat") is not None),
        "noLocationCount": sum(1 for r in reports if r.get("lat") is None),
        "grading": {"version": GRADE_VERSION, "levels": {str(k): v for k, v in __import__("grading").LABELS.items()}},
        "skyCheck": {"version": SK.SKY_VERSION, "lastRun": sky_stats},
        "screening": {"version": SCREEN_VERSION, "rules": RULES_TEXT, "excludedLog": "data/excluded.json",
                      "excludedLogged": len(excluded["items"]), "lastRescreen": rescreen_stats, "seedAddedThisSweep": seed_added},
        "admissionGate": {"version": GATE.GATE_VERSION, "rule": GATE.GATE_RULE, "lastRun": gate_stats},
        "lastSweep": {"rawItems": len(raw), "added": added, "mergedAsExtraSource": merged, "droppedNotRelevant": dropped,
                      "skippedOlderThan7d": skipped_old, "linksChecked": lc[0], "linksNewlyUnavailable": lc[1]},
        "sourcesStatus": list(status.values()),
        "schedule": "GitLab pipeline schedules at 4 AM and 4 PM America/Denver" if os.environ.get("GITLAB_CI") else "GitHub Actions cron every hour, on the hour",
        "sweepSeconds": round(time.time() - T0),
    })
    db = {"meta": meta, "reports": reports, "flapWatch": fw}
    save_excluded(excluded)
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DATA)
    with open(os.path.join(STATE, "sweep-log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": NOW_ISO, **meta["lastSweep"], "sources": {k: {x: v[x] for x in ("requests", "ok", "failed", "items", "kept")} for k, v in status.items()}}) + "\n")
    print(json.dumps(meta["lastSweep"], indent=1))
    for s in status.values():
        print(f"  {s['name']}: requests {s['requests']} ok {s['ok']} failed {s['failed']} skipped {s.get('skipped', 0)} items {s['items']} kept {s['kept']}")

if __name__ == "__main__":
    main()
