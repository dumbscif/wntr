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
from classify import classify, clean, CONTEXT, _any
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
FAMILY_LIMIT = {"Google News": 8, "Bing News": 6, "Reddit": 1, "Mastodon": 2, "UFO Meldpunt Nederland": 3}
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
        return urlunparse(("", host, p.path.rstrip("/"), "", q, ""))[2:]
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
    # interleave families so a time-budget cut never starves one whole source family
    fams = {}
    for t in tasks:
        fams.setdefault(t[0], []).append(t)
    order = sorted(fams.values(), key=len)
    out = []
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
    args = ap.parse_args()
    os.makedirs(STATE, exist_ok=True)
    db = load()
    reports = db.get("reports", [])
    by_id = {r["id"]: r for r in reports}
    known = {}
    for r in reports:
        for s in r.get("sources", []):
            if s.get("url"):
                known[norm_url(s["url"])] = r["id"]
    gaz = Gazetteer(os.path.join(STATE, "geocache.json"), nominatim_cap=int(os.environ.get("WNTR_NOMINATIM_CAP", "10")), user_agent=UA)

    tasks = fetch_tasks(args.quick, known)
    print(f"Fetching {len(tasks)} source requests with {WORKERS} workers, budget {TIME_BUDGET:.0f}s", flush=True)
    raw = run_fetch(tasks)
    print(f"Fetch phase done in {time.time() - T0:.0f}s, {len(raw)} raw items", flush=True)

    recent = [r for r in reports if (r.get("sweptAt") or "") >= iso(NOW - timedelta(days=7))[:10]]
    added = merged = skipped_old = dropped = 0
    for it in raw:
        url = it.get("url")
        if not url or not it.get("title"):
            continue
        key = norm_url(url)
        if key in known:
            continue
        pub = it.get("published")
        if pub and NOW - pub > timedelta(days=MAX_AGE_DAYS):
            skipped_old += 1
            continue
        title, summary = it["title"], it.get("summary", "")
        ctext = (("UFO " if it.get("topic_feed") else "") + title + " " + summary)
        c = classify(ctext, "")
        if it.get("forced_kind") and not c:
            c = ("sighting", "red", "Witness report on a civilian UFO reporting site; not verified")
        if not c:
            dropped += 1
            continue
        kind, marker, basis = c
        if it.get("topic_feed") and it["family"] in ("Reddit", "Mastodon") and kind == "context":
            dropped += 1  # social chatter without a described sighting
            continue
        toks = tokens(title)
        src = {"name": it.get("publisher") or domain(url), "url": url, "published": iso(pub), "role": "original report" if it.get("forced_kind") or it["family"] in ("Reddit", "Mastodon") else "media report",
               "title": title[:200], "via": f"{it['family']}" + (f" / {it['edition']}" if it.get("edition") else ""), "accessed": NOW_ISO,
               "availability": {"status": "available", "lastCheckedAt": NOW_ISO, "httpStatus": 200, "reason": "listed in feed at sweep time"}}
        # title-similarity duplicate -> extra source on existing report
        dup = None
        for r in recent:
            if jacc(toks, r.get("_toks") or tokens(r.get("title"))) >= 0.55:
                dup = r
                break
        place = None
        if not dup:
            place = gaz.locate(it["place_hint"], "NL") if it.get("place_hint") else None
            if not place:
                place = gaz.locate(title + ". " + summary, it.get("region"))
            if place and place.get("gid"):
                for r in recent:
                    if r.get("gid") == place["gid"] and r.get("kind") == kind and jacc(toks, r.get("_toks") or tokens(r.get("title"))) >= 0.15:
                        dup = r
                        break
        years = [int(y) for y in re.findall(r"\b(19[4-9]\d|20[0-4]\d)\b", title + " " + summary)]
        if kind == "sighting" and years and not it.get("event_local") and max(years) < NOW.year and NOW.year not in years:
            kind, marker, basis = "context", "cyan", f"Mentions only older year(s) ({max(years)}); likely a historical or resurfaced case, not a new sighting (keyword rule)"
        if not dup and kind == "sighting" and not place and _any(CONTEXT, ctext.lower()):
            kind, marker, basis = "context", "cyan", "OSINT/context: official/political UFO news with no local sighting place (keyword rule)"
        if dup:
            if not any(norm_url(s["url"]) == key for s in dup["sources"]):
                src["role"] = "media republish" if src["role"] == "media report" else src["role"]
                dup["sources"].append(src)
                if marker == "yellow" and dup.get("marker") == "red":
                    dup["marker"], dup["markerBasis"] = marker, basis + " (from an added source)"
            known[key] = dup["id"]
            merged += 1
            continue
        rid = "auto-" + hashlib.sha1(key.encode()).hexdigest()[:12]
        rep = {"id": rid, "origin": "auto", "kind": kind, "marker": marker if (place or kind == "context") else marker,
               "markerBasis": basis, "title": title[:220], "summary": summary[:700],
               "reporterType": it.get("reporterType", "unknown"), "reporterTypeBasis": "Automated sweep cannot verify who the witness is" if not it.get("reporterType") else "Member of the public on a civilian reporting site",
               "publishedAt": iso(pub), "eventAt": iso(pub) if it.get("event_local") else None,
               "eventDate": iso(pub)[:10] if pub else None, "eventTimeLocal": it.get("event_local"),
               "timeBasis": "Witness-reported sighting time" if it.get("event_local") else "Publication time (sighting time not parsed)",
               "sweptAt": NOW_ISO, "sources": [src], "feed": src["via"],
               "lat": place["lat"] if place else None, "lon": place["lon"] if place else None,
               "place": place["place"] if place else None, "country": place["country"] if place else None,
               "continent": place.get("continent") if place else None, "tz": (place.get("tz") if place else None) or it.get("event_tz"),
               "precision": place["precision"] if place else "no location found in source text; not mapped", "gid": place.get("gid") if place else None}
        if kind == "context" and rep["lat"] is not None:
            rep["marker"] = "cyan"
        reports.append(rep)
        by_id[rid] = rep
        rep["_toks"] = toks
        recent.append(rep)
        known[key] = rid
        added += 1
        stat(it["family"], kept=1)

    for r in reports:
        r.pop("_toks", None)

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
        "title": "UFO Sighting Archive: WNTR",
        "generatedBy": "scraper/sweep.py (rule-based, no AI)",
        "lastSweepAt": NOW_ISO,
        "sweepCount": int(meta.get("sweepCount", 0)) + 1,
        "reportCount": len(reports),
        "mappedLast24h": sum(1 for r in last24 if r.get("lat") is not None),
        "noLocationCount": sum(1 for r in reports if r.get("lat") is None),
        "lastSweep": {"rawItems": len(raw), "added": added, "mergedAsExtraSource": merged, "droppedNotRelevant": dropped,
                      "skippedOlderThan7d": skipped_old, "linksChecked": lc[0], "linksNewlyUnavailable": lc[1]},
        "sourcesStatus": list(status.values()),
        "schedule": "GitLab pipeline schedules at 4 AM and 4 PM America/Denver" if os.environ.get("GITLAB_CI") else "GitHub Actions cron 11:00 and 23:00 UTC = 4 AM / 4 PM MST (5 AM / 5 PM during MDT)",
        "sweepSeconds": round(time.time() - T0),
    })
    db = {"meta": meta, "reports": reports, "flapWatch": fw}
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
