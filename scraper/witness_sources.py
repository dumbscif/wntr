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
