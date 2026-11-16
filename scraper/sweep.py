#!/usr/bin/env python3
"""WNTR UFO Sighting Archive - automated sweep. No AI, no API keys.

Reads public feeds, keeps UFO/UAP sighting reports with a source link, geocodes place
names offline, classifies marker colour by keyword rules, merges duplicates, checks old
links, recomputes Flap Watch, and writes docs/data/events.json.

    python scraper/sweep.py               # full sweep
    python scraper/sweep.py --quick       # fewer Google queries (testing)
    python scraper/sweep.py --no-linkcheck
"""
import argparse, hashlib, json, os, re, sys, time
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

def stat(family, **kw):
    s = status.setdefault(family, {"name": family, "requests": 0, "ok": 0, "failed": 0, "items": 0, "kept": 0, "errors": []})
    for k, v in kw.items():
        if k == "error":
            if len(s["errors"]) < 3:
                s["errors"].append(v[:160])
        else:
            s[k] += v

BUDGET = {"Google News": 480, "Bing News": 180, "Reddit": 150, "Mastodon": 90, "GDELT": 60, "UFO Meldpunt Nederland": 120}
_started = {}

def get(url, family, delay=0.0, retries=1, **kw):
    t0 = _started.setdefault(family, time.time())
    if time.time() - t0 > BUDGET.get(family, 180):
        stat(family, requests=1, failed=1, error="time budget reached; remaining requests skipped this sweep")
        return None
    if delay:
        time.sleep(delay)
    stat(family, requests=1)
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=(10, 20), **kw)
            if r.status_code in (429, 503) and attempt < retries:
                time.sleep(8 * (attempt + 1))
                continue
            if r.ok:
                stat(family, ok=1)
                return r
            stat(family, failed=1, error=f"HTTP {r.status_code} {url[:90]}")
            return None
        except Exception as e:
            if attempt >= retries:
                stat(family, failed=1, error=f"{type(e).__name__} {url[:90]}")
                return None
            time.sleep(3)

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
    r = get(fetch["url"], family, delay=fetch.get("delay", 1.2))
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

def fetch_google(quick):
    items = []
    feeds = list(S.google_news_feeds())
    if quick:
        feeds = feeds[::6]
    for f in feeds:
        items += feed_items(f, "Google News")
    return items

def fetch_bing():
    items = []
    for f in S.bing_feeds():
        items += feed_items(f, "Bing News")
    return items

def fetch_reddit():
    items = []
    for sub in S.REDDIT_SUBS:
        f = {"url": f"https://www.reddit.com/r/{sub}/new/.rss?limit=50", "delay": 10, "topic_feed": True, "edition": "r/" + sub}
        for it in feed_items(f, "Reddit", raw_name=f"Reddit r/{sub} (user post)"):
            items.append(it)
    return items

def fetch_mastodon():
    items = []
    for tag in S.MASTODON_TAGS:
        r = get(f"https://mastodon.social/api/v1/timelines/tag/{tag}?limit=40", "Mastodon", delay=1)
        if not r:
            continue
        try:
            posts = r.json()
        except Exception:
            continue
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

def fetch_extra_rss():
    items = []
    for name, url in S.EXTRA_RSS:
        items += feed_items({"url": url, "edition": name}, "Specialist UFO news RSS", raw_name=name)
    return items

def fetch_gdelt():
    r = get(S.GDELT_URL, "GDELT", delay=6, retries=1)
    if not r:
        return []
    try:
        arts = r.json().get("articles", [])
    except Exception:
        stat("GDELT", error="non-JSON reply (rate limited?)")
        return []
    stat("GDELT", items=len(arts))
    out = []
    for a in arts:
        try:
            dt = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            dt = None
        out.append({"title": clean(a.get("title", "")), "summary": "", "url": a.get("url"), "published": dt,
                    "publisher": a.get("domain"), "family": "GDELT", "edition": a.get("sourcecountry"), "region": None, "topic_feed": False})
    return out

def fetch_meldpunt(known_urls):
    r = get(S.MELDPUNT_HOME, "UFO Meldpunt Nederland", delay=1)
    if not r:
        return []
    links = []
    for m in re.finditer(r'href="(https://www\.ufomeldpunt\.nl/melding/\d+-[^"#]+)"', r.text):
        if m.group(1) not in links:
            links.append(m.group(1))
    stat("UFO Meldpunt Nederland", items=len(links))
    out = []
    for link in links[:20]:
        if norm_url(link) in known_urls:
            continue
        p = get(link, "UFO Meldpunt Nederland", delay=1.5)
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
def link_check(reports, limit=80):
    cands = []
    for r in reports:
        for s in r.get("sources", []):
            if not s.get("url", "").startswith("http"):
                continue
            av = s.setdefault("availability", {"status": "unchecked"})
            last = av.get("lastCheckedAt") or "1970-01-01T00:00:00Z"
            cands.append((last, s))
    cands.sort(key=lambda x: x[0])
    checked = flagged = 0
    for last, s in cands[:limit]:
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if NOW - last_dt < timedelta(days=3):
                continue
        except Exception:
            pass
        code = None
        try:
            h = session.head(s["url"], timeout=15, allow_redirects=True)
            code = h.status_code
            if code in (403, 405, 400, 501):
                g = session.get(s["url"], timeout=15, allow_redirects=True, stream=True)
                code = g.status_code
                g.close()
        except Exception:
            code = None
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
        time.sleep(0.3)
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
    gaz = Gazetteer(os.path.join(STATE, "geocache.json"), nominatim_cap=int(os.environ.get("WNTR_NOMINATIM_CAP", "20")), user_agent=UA)

    raw = []
    for name, fn in [("Google News", lambda: fetch_google(args.quick)), ("Bing News", fetch_bing), ("Reddit", fetch_reddit),
                     ("Mastodon", fetch_mastodon), ("Specialist UFO news RSS", fetch_extra_rss), ("GDELT", fetch_gdelt),
                     ("UFO Meldpunt Nederland", lambda: fetch_meldpunt(known))]:
        try:
            got = fn()
        except Exception as e:  # one broken source never stops the sweep
            stat(name, failed=1, error=f"crash {type(e).__name__}: {e}")
            got = []
        print(f"{name}: {len(got)} raw items", flush=True)
        raw += got

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
        "schedule": "GitHub Actions cron 11:00 and 23:00 UTC = 4 AM / 4 PM MST (5 AM / 5 PM during MDT)",
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
        print(f"  {s['name']}: requests {s['requests']} ok {s['ok']} failed {s['failed']} items {s['items']} kept {s['kept']}")

if __name__ == "__main__":
    main()
