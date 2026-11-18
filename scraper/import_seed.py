#!/usr/bin/env python3
"""One-time import of the hand-curated WNTR archive (events.json from the original
UFO Sighting Watch project) into docs/data/events.json. Safe to re-run: existing ids
are kept, seed fields refreshed.

    python scraper/import_seed.py /path/to/ufo-sighting-watch/events.json
"""
import json, os, sys
from gate import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data", "events.json")

def src(s):
    av = s.get("availability") or {}
    return {k: v for k, v in {
        "name": s.get("name"), "url": s.get("url"), "published": s.get("published") or s.get("date"),
        "role": s.get("role"), "title": s.get("title"), "note": s.get("note"), "accessed": s.get("accessed"),
        "limited": s.get("limited"),
        "availability": {"status": av.get("status", "unchecked"), "lastCheckedAt": av.get("lastCheckedAt"),
                         "httpStatus": av.get("httpStatus"), "firstUnavailableAt": av.get("firstUnavailableAt"),
                         "reason": av.get("reason")},
    }.items() if v is not None}

def g(e, *keys):
    for k in keys:
        if e.get(k) not in (None, "", []):
            return e[k]
    return None

def convert_event(e):
    marker = e.get("marker", "red")
    return {
        "id": e["id"], "origin": "seed", "kind": "sighting", "marker": marker,
        "markerBasis": {"red": "Civilian/unknown sighting claim (hand-reviewed)", "yellow": "Hand-reviewed: cited military/government/police confirmation or military witness; not confirmation of an alien craft",
                        "blue": "Hand-reviewed: alleged testing claim"}.get(marker, ""),
        "title": g(e, "label", "location_label") or e["id"], "place": g(e, "label", "location_label"),
        "country": e.get("country"), "continent": e.get("continent"), "lat": e.get("lat"), "lon": e.get("lon"),
        "precision": g(e, "precision", "coord_precision"), "tz": g(e, "tz", "sighting_tz"),
        "eventDate": g(e, "date", "sighting_date"), "eventTimeLocal": g(e, "timeLocal", "sighting_time_local"),
        "eventTimeDenver": g(e, "timeDenver", "sighting_time_denver"), "publishedText": g(e, "published", "publication_date"),
        "sweptAt": e.get("sweptAt") or e.get("discovered"), "reporterType": e.get("reporterType", "unknown"),
        "reporterTypeBasis": e.get("reporterTypeBasis"), "allegedTesting": bool(g(e, "allegedTesting", "alleged_testing")),
        "appearance": e.get("appearance"), "narrative": e.get("narrative"), "summary": e.get("narrative"),
        "evidence": g(e, "evidence", "evidence_status"), "explanations": g(e, "explanations", "explanations_noted") or [],
        "shape": e.get("shapeCategory"), "reportCount": g(e, "count", "report_count"),
        "media": [{"type": m.get("type"), "url": m.get("url")} for m in (e.get("media") or []) if isinstance(m, dict) and m.get("url")],
        "corrections": e.get("corrections"), "sources": [src(s) for s in e.get("sources", [])],
        "feed": "Hand-curated WNTR archive (Nov 2026)",
    }

def convert_osint(o):
    return {
        "id": o["id"], "origin": "seed", "kind": "context", "marker": "cyan",
        "markerBasis": "OSINT/context item (hand-reviewed); not a field sighting",
        "title": o.get("title"), "place": o.get("location_label"), "lat": o.get("lat"), "lon": o.get("lon"),
        "country": o.get("country"), "continent": o.get("continent"),
        "eventDate": o.get("event_date"), "publishedText": o.get("publication_date"),
        "sweptAt": o.get("sweptAt") or o.get("discovered") or (o.get("publication_date") or "") + "T12:00:00-07:00",
        "summary": o.get("summary"), "narrative": o.get("summary"), "relevance": o.get("relevance"),
        "precision": o.get("precision") or ("no public coordinates" if o.get("lat") is None else None),
        "reporterType": "unknown", "sources": [src(s) for s in o.get("sources", [])],
        "feed": "Hand-curated WNTR archive (Nov 2026)",
    }

def main(path):
    with open(path, encoding="utf-8") as f:
        seed = json.load(f)
    db = {"meta": {}, "reports": [], "flapWatch": {}}
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            db = json.load(f)
    by_id = {r["id"]: r for r in db["reports"]}
    n = 0
    for e in seed.get("events", []):
        rec = convert_event(e)
        ev = evaluate(rec)
        if not ev["admit"]:
            continue
        by_id[e["id"]] = rec; n += 1
    for o in seed.get("osint", []):
        by_id[o["id"]] = convert_osint(o); n += 1
    db["reports"] = sorted(by_id.values(), key=lambda r: r.get("sweptAt") or "", reverse=True)
    db["meta"]["seedImport"] = {"from": "UFO Sighting Watch hand-curated archive", "items": n,
                                "seedLastChecked": seed.get("meta", {}).get("lastChecked")}
    db["meta"]["reportCount"] = len(db["reports"])
    if seed.get("flapWatch") and not db.get("flapWatch"):
        db["flapWatch"] = {"seedAssessment": seed["flapWatch"]}
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    print(f"imported {n} seed items; archive now {len(db['reports'])} reports")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../ufo-sighting-watch/events.json")
