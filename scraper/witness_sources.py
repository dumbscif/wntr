"""Witness-report databases the Grok Page sweeps rely on, read without AI or keys.
Each fetcher returns items in the sweep's common format. Every parser is defensive:
if a site changes layout it yields nothing (logged), never invented data."""
import html, json, re
from datetime import datetime, timezone

def _rsc(text):
    """Join a Next.js page's streamed RSC payload into one string."""
    out = []
    for c in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', text, flags=re.S):
        try:
            out.append(json.loads('"' + c + '"'))
        except Exception:
            pass
    return "".join(out)

def _objects_with(s, key):
    """Yield JSON objects in s that contain "key": by brace-matching from each '{"id":' start."""
    for m in re.finditer(r'\{"id":"[0-9a-f-]{36}","title":', s):
        depth, i, instr, esc = 0, m.start(), False, False
        while i < len(s):
            ch = s[i]
            if instr:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': instr = False
            else:
                if ch == '"': instr = True
                elif ch == "{": depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
            i += 1
        chunk = s[m.start():i + 1]
        if key in chunk:
            try:
                yield json.loads(chunk)
            except Exception:
                continue

def _dt(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

PROBED_OK = {"sighting_report", "video", "photo"}   # 'named_sources', 'rumor', 'opinion' = stories/hearsay -> not used

def fetch_probed(get, stat):
    fam = "Probed"
    r = get("https://probed.space/sightings", fam)
    if not r:
        return []
    s = _rsc(r.text)
    out, seen = [], 0
    for o in _objects_with(s, '"evidence_type"'):
        seen += 1
        if o.get("claim_type") != "sighting" or o.get("evidence_type") not in PROBED_OK:
            continue
        page = f"https://probed.space/sightings/{o['id']}"
        orig = o.get("canonical_url") or ""
        sub = (o.get("sources") or {}).get("name") or "Probed"
        out.append({"title": html.unescape(o.get("title") or "")[:220], "summary": html.unescape(o.get("snippet") or "")[:700], "url": page,
                    "published": _dt(o.get("published_at")), "publisher": f"Probed.space relay of {sub} (witness post)", "family": fam,
                    "edition": sub, "region": None, "topic_feed": True, "alt_url": orig if orig.startswith("http") else None,
                    "place_hint": o.get("location_name"), "probed_lat": o.get("location_lat"), "probed_lon": o.get("location_lng"),
                    "structured": {"is_report": True, "shape": o.get("sighting_shape") if o.get("sighting_shape") not in (None, "unknown") else None,
                                   "witness_count": o.get("witness_count"), "media": o.get("evidence_type") in ("video", "photo") or bool(o.get("thumbnail_url")),
                                   "duration_s": o.get("sighting_duration_seconds"), "probed_evidence_type": o.get("evidence_type"),
                                   "probed_context": (o.get("sighting_context") or {}).get("explanationCandidates") or []}})
    stat(fam, items=seen)
    return out

def fetch_aliens(get, stat, known, norm_url, cap=12):
    fam = "Aliens.co.il"
    r = get("https://aliens.co.il/en/feed", fam)
    if not r:
        return []
    s = _rsc(r.text)
    hrefs = []
    for m in re.finditer(r'\{"label":"sighting","title":"((?:[^"\\]|\\.)*)","href":"(/feed/p/[0-9a-f-]{36})","at":(\d+)\}', s):
        u = "https://aliens.co.il/en" + m.group(2)
        if u not in [h[0] for h in hrefs]:
            hrefs.append((u, m.group(1), int(m.group(3))))
    stat(fam, items=len(hrefs))
    out = []
    for u, title, at in hrefs:
        if norm_url(u) in known or len(out) >= cap:
            continue
        p = get(u, fam, delay=0.3)
        if not p:
            continue
        post = None
        for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', p.text, re.S):
            try:
                data = json.loads(blob)
            except Exception:
                continue
            for d in (data if isinstance(data, list) else [data]):
                if isinstance(d, dict) and d.get("@type") == "SocialMediaPosting":
                    post = d
        if not post:
            continue
        shared = (post.get("sharedContent") or {}).get("url")
        author = (post.get("author") or {}).get("name") or "social post"
        out.append({"title": html.unescape(post.get("headline") or title)[:220], "summary": html.unescape(post.get("text") or "")[:700], "url": u,
                    "published": _dt(post.get("datePublished")) or datetime.fromtimestamp(at / 1000, timezone.utc),
                    "publisher": f"Aliens.co.il summary of {author} (witness post)", "family": fam, "edition": author, "region": None,
                    "topic_feed": True, "alt_url": shared, "structured": {"is_report": True, "media": bool(post.get("image"))}})
    return out

def fetch_ufo_hunters(get, stat):
    fam = "UFO Hunters"
    r = get("https://www.ufo-hunters.com/", fam)
    if not r:
        return []
    out = []
    blocks = re.findall(r'<a class="no-underline block" href="(/sightings/search/[^"]+)">(.*?)</a>', r.text, re.S)
    stat(fam, items=len(blocks))
    for href, body in blocks:
        head = re.search(r'itemprop="headline" content="([^"]+)"', body)
        created = re.search(r'itemprop="dateCreated" content="(\d{4}-\d\d-\d\d)"', body)
        pubd = re.search(r'itemprop="datePublished" content="(\d{4}-\d\d-\d\d)"', body)
        name = re.search(r'itemprop="name"[^>]*>\s*(.*?)\s*</h4>', body, re.S)
        shape = re.search(r"uppercase\">([^<]*)</span>", body)
        desc = re.search(r'itemprop="dateCreated"[^>]*>\s*(.*?)\s*</p>', body, re.S)
        if not head or not created:
            continue
        place = html.unescape(re.sub(r"\s+", " ", name.group(1))).strip() if name else None
        sh = html.unescape(shape.group(1)).strip() if shape else ""
        out.append({"title": html.unescape(head.group(1)).replace("  ", " "), "summary": ((sh + " shape. ") if sh else "") + html.unescape(re.sub(r"\s+", " ", desc.group(1) if desc else "")),
                    "url": "https://www.ufo-hunters.com" + href, "published": _dt((pubd or created).group(1) + "T12:00:00+00:00"),
                    "publisher": "UFO Hunters (witness report)", "family": fam, "edition": None, "region": None, "topic_feed": True,
                    "place_hint": place, "event_local": created.group(1), "reporterType": "civilian",
                    "structured": {"is_report": True, "shape": sh or None}})
    return out

def fetch_mufon(get, stat):
    fam = "MUFON"
    r = get("https://mufoncms.com/last_20_public.html", fam)
    if not r:
        return []
    out = []
    rows = re.findall(r"<tr>\s*<td align=center>(\d+)</td>(.*?)</tr>", r.text, re.S)
    stat(fam, items=len(rows))
    for case, rest in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", rest, re.S)
        if len(tds) < 5:
            continue
        sub, ev, desc, city, region = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", x)).strip() for x in tds[:5]]
        media = "href=" in (tds[5] if len(tds) > 5 else "")
        cc = region.split(",")[-1].strip()
        out.append({"title": f"MUFON case {case}: {desc[:150]}", "summary": f"{desc} ({city}, {region}; event date {ev}, submitted {sub})",
                    "url": f"https://mufoncms.com/last_20_public.html#case-{case}", "published": _dt(sub + "T12:00:00+00:00"),
                    "publisher": "MUFON Case Management System (witness report)", "family": fam, "edition": None, "region": cc if len(cc) == 2 else None,
                    "topic_feed": True, "place_hint": f"{city}, {region}", "event_local": ev, "event_date": ev, "reporterType": "civilian",
                    "structured": {"is_report": True, "media": media}})
    return out


# --- added 2026-11-18: vital-source expansion (public pages/feeds only) ---

_MONTH = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
_MONTH.update({m[:3]: i for m, i in list(_MONTH.items())})
_MONTH["sept"] = 9

def _parse_day_mon_year(s):
    m = re.search(r"(\d{1,2})[-/\s]+([A-Za-z]{3,9})[-/\s]+(\d{4})", s or "")
    if not m:
        return None
    mon = _MONTH.get(m.group(2).lower())
    if not mon:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(1)), 12, 0, tzinfo=timezone.utc)
    except Exception:
        return None

def _strip_html(chunk):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", chunk, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    return s

def parse_ufobc(text):
    """Parse UFO*BC recent_v2.htm listing (FrontPage HTML; reports share one page)."""
    out = []
    pat = re.compile(r"Reported\s+(\d{1,2}[-/\s]+[A-Za-z]{3,9}[-/\s]+\d{4})", re.I)
    matches = list(pat.finditer(text))
    for i, m in enumerate(matches):
        submitted = _parse_day_mon_year(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body_html = text[m.end():end]
        body = _strip_html(body_html)
        # "26-Sept-2026, Cranbrook, BC : (Nighttime)" or "Winter 1993, Surrey BC"
        head = body[:240]
        ev, place = None, None
        hm = re.match(
            r"[:\s]*((?:(?:Early|Mid|Late|Winter|Spring|Summer|Fall|Autumn)[-\s]+)*"
            r"(?:\d{1,2}[-/\s]+[A-Za-z]{3,9}[-/\s]+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|[A-Za-z]{3,9}[-/\s,]+\d{4}|\d{4}))"
            r"(?:,\s*([^:]{3,80}))?",
            head, re.I)
        if hm:
            ev = re.sub(r"\s+", " ", hm.group(1)).strip()
            place = (hm.group(2) or "").split(":")[0].strip(" .") or None
        if place and not re.search(r"\b(Canada|BC|AB|SK|MB|ON|QC|NS|NB|PE|NL|YT|NT|NU|British Columbia|Alberta|Ontario|Quebec)\b", place, re.I):
            place = place + ", British Columbia, Canada"
        elif place and "Canada" not in place:
            place = place + ", Canada"
        media = bool(re.search(r"\.(?:jpe?g|png|gif|webp|mp4|mov|m4v|avi)(?:\b|\")", body_html, re.I))
        slug_src = (place or ev or m.group(1) or str(i)).lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug_src).strip("-")[:48] or str(i)
        date_key = submitted.strftime("%Y%m%d") if submitted else f"row{i}"
        url = f"https://www.ufobc.ca/Sightings/recent_v2.htm#case-{date_key}-{slug}"
        title_place = place or "British Columbia"
        title = f"UFO*BC report ({title_place})"
        if ev:
            title += f", {ev}"
        out.append({
            "title": title[:220],
            "summary": body[:700],
            "url": url,
            "published": submitted,
            "publisher": "UFO*BC (witness report)",
            "family": "UFO*BC",
            "edition": "BC",
            "region": "CA",
            "topic_feed": True,
            "place_hint": place,
            "event_local": ev,
            "event_date": (ev[:10] if ev and re.match(r"\d{4}-\d\d-\d\d", ev) else (submitted.strftime("%Y-%m-%d") if submitted and not ev else None)),
            "reporterType": "civilian",
            "structured": {"is_report": True, "media": media},
        })
    return out

def fetch_ufobc(get, stat):
    fam = "UFO*BC"
    r = get("https://www.ufobc.ca/Sightings/recent_v2.htm", fam)
    if not r:
        return []
    try:
        text = r.content.decode("cp1252", errors="replace")
    except Exception:
        text = r.text or ""
    if "Just a moment" in text[:500] or "cf-browser-verification" in text[:2000]:
        stat(fam, failed=1, error="Cloudflare challenge; listing not parsed")
        return []
    out = parse_ufobc(text)
    stat(fam, items=len(out))
    return out

def fetch_geipan(get, stat):
    """Official GEIPAN public case list (HTML search page). Soft-fails on 5xx."""
    fam = "GEIPAN"
    pages = [
        "https://www.cnes-geipan.fr/fr/recherche/cas",
        "https://cnes-geipan.fr/fr/recherche/cas",
    ]
    text = ""
    for u in pages:
        r = get(u, fam)
        if not r:
            continue
        text = r.text or ""
        if "502 Server Error" not in text[:400] and len(text) > 200 and (
            "Liste des cas" in text or "/cas/" in text
        ):
            break
        text = ""
    if not text:
        return []
    out, seen = [], set()
    for m in re.finditer(r'href="([^"]*(?:/fr)?/cas/[^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I):
        href, label = m.group(1), _strip_html(m.group(2))
        if href.startswith("/"):
            href = "https://www.cnes-geipan.fr" + href
        if href in seen:
            continue
        seen.add(href)
        # nearby classification / date / department often sit in the parent block
        window = text[max(0, m.start() - 200):m.end() + 400]
        win = _strip_html(window)
        clas = re.search(r"Classification\s*:\s*([A-D]\d?)", win, re.I)
        dept = re.search(r"D[ée]partement\s*:\s*([^.]{2,60})", win, re.I)
        d = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", win)
        published = None
        ev = None
        if d:
            try:
                published = datetime(int(d.group(3)), int(d.group(2)), int(d.group(1)), 12, 0, tzinfo=timezone.utc)
                ev = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
            except Exception:
                pass
        place = label
        # "PAPEETE (987) 12.01.2026" -> place Papeete
        pm = re.match(r"(.+?)\s*(?:\((\d+)\))?\s*(?:\d{2}[./]\d{2}[./]\d{4})?$", label)
        if pm:
            place = pm.group(1).strip()
        if dept:
            dname = dept.group(1).strip()
            if dname.lower() not in (place or "").lower():
                place = f"{place}, {dname}" if place else dname
        elif place and "France" not in place:
            place = place + ", France"
        summary = win[:700]
        if clas:
            summary = f"GEIPAN classification {clas.group(1)}. " + summary
        out.append({
            "title": f"GEIPAN case: {label}"[:220],
            "summary": summary,
            "url": href,
            "published": published,
            "publisher": "GEIPAN / CNES (official case file)",
            "family": fam,
            "edition": "FR",
            "region": "FR",
            "topic_feed": True,
            "place_hint": place,
            "event_local": ev,
            "event_date": ev,
            "reporterType": "civilian",
            "structured": {"is_report": True, "media": False, "geipan_class": clas.group(1) if clas else None},
        })
        if len(out) >= 30:
            break
    stat(fam, items=len(out))
    return out

def fetch_youtube(stat, cap=8):
    """Recent sighting videos via yt-dlp ytsearch (no download). Soft-fail if missing or blocked."""
    import shutil, subprocess, sys
    fam = "YouTube"
    exe = shutil.which("yt-dlp")
    argv_base = None
    if exe:
        argv_base = [exe]
    else:
        try:
            import yt_dlp  # noqa: F401
            argv_base = [sys.executable, "-m", "yt_dlp"]
        except Exception:
            stat(fam, skipped=1, error="yt-dlp not installed; YouTube search skipped")
            return []
    queries = ["UFO sighting November 2026", "ovni avistamiento video 2026"]
    out, seen = [], set()
    for q in queries:
        argv = argv_base + [
            "--flat-playlist", "--dump-json", "--no-download", "--no-warnings",
            "--socket-timeout", "12", "--playlist-end", str(cap),
            f"ytsearch{cap}:{q}",
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=25)
        except Exception as e:
            stat(fam, failed=1, error=f"{type(e).__name__}: {e}")
            continue
        if proc.returncode != 0 and not proc.stdout.strip():
            err = (proc.stderr or "yt-dlp failed")[:160]
            stat(fam, failed=1, error=err)
            continue
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            vid = o.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            title = (o.get("title") or "").strip()
            if not title:
                continue
            url = o.get("url") or o.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
            if url and not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={vid}"
            ch = o.get("channel") or o.get("uploader") or "YouTube"
            desc = (o.get("description") or "")[:700]
            published = _dt(o.get("upload_date") or o.get("timestamp") or o.get("release_timestamp"))
            # yt-dlp upload_date is YYYYMMDD
            if published is None and o.get("upload_date") and re.match(r"^\d{8}$", str(o["upload_date"])):
                s = str(o["upload_date"])
                try:
                    published = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), 12, 0, tzinfo=timezone.utc)
                except Exception:
                    pass
            out.append({
                "title": title[:220],
                "summary": desc or title,
                "url": url,
                "published": published,
                "publisher": f"YouTube / {ch} (video)",
                "family": fam,
                "edition": q,
                "region": None,
                "topic_feed": True,
                "mediaAttached": True,
                "reporterType": "unknown",
                "structured": {"media": True},
            })
    stat(fam, items=len(out), ok=1 if out else 0)
    return out
