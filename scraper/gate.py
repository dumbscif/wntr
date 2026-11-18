"""Admission gate (owner rule, 2026-11-18).

Do not map, log or archive a sighting report that:
  (a) has no reported location, OR
  (b) has evidence grade <= 2 AND fewer than two independent corroborating
      reports (distinct witnesses/sources for the same event, not reposts
      of one clip).

Context/OSINT items are not sighting reports and are never moved by this gate.
Reports that later gain a location, a higher grade, or enough corroboration
are re-admitted from the excluded file.

This module is the single implementation used by the Grok Page archive
(`ufo-sighting-watch/gate.py` is a thin runner) and by the public-site sweep.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

DENVER = ZoneInfo("America/Denver")
GATE_VERSION = 1
GATE_RULE = (
    "Owner rule 2026-11-18: do not map, log or archive a sighting that has no "
    "reported location, or that has evidence grade 2 or below and fewer than "
    "two independent corroborating reports (distinct witnesses/sources for the "
    "same event, not reposts of one clip)."
)
REASON_NO_LOCATION = "no reported location"
REASON_WEAK = "weak uncorroborated evidence (grade <= 2, fewer than two independent reports)"

# Placeholders that mean "we do not have a reported place", not a coarse but named one.
NO_PLACE = {
    "", "unknown", "unspecified", "not reported", "n/a", "none", "null",
    "location not reported", "not specified", "no location", "place not reported",
}
# Precision text that means the source gave no place at all (not "county only").
NO_LOCATION_PRECISION = re.compile(
    r"no location found in source text"
    r"|unmapped:\s*no public (?:encounter )?location"
    r"|no public encounter location is given",
    re.I,
)

# Witness/report wording. Does not treat "two minutes" / "two years" as corroboration.
MULTI = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|\d{1,3}|multiple|several|many)\s+"
    r"(?:named\s+|stated\s+|separate\s+|independent\s+|other\s+|more\s+)?"
    r"(?:witnesses|reports|residents|observers|callers|pilots)\b"
    r"|\bat least\s+(?:two|three|\d+)\s+(?:other\s+)?(?:people|witnesses|residents|observers)\b"
    r"|\b(?:two|three|\d+)\s+witnesses?\s+stated\b"
    r"|\bmultiple witnesses\b"
    r"|\bseparate reports\b"
    r"|\bindependent (?:reports|witnesses)\b",
    re.I,
)
# Roles / names that are the same report again (listing, republish, relay of the same post).
RELAY_ROLES = {"database listing", "media republish"}
RELAY_NAME = re.compile(r"original post\b|as linked by\b|case table\b|public listing\b", re.I)

def _now_denver():
    return datetime.now(DENVER).isoformat(timespec="seconds")


def _grade(r):
    g = r.get("evidenceGrade") or r.get("grade") or {}
    if isinstance(g, dict):
        level = g.get("level")
        return int(level) if isinstance(level, (int, float)) else None, g
    return None, {}


def _place_text(r):
    for k in ("place", "label", "geographyLocation", "location_label", "location"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def has_reported_location(r) -> bool:
    """True when the record itself names or coordinates a place.

    Coarse but stated places (a county, a province, 'Farm in England') count.
    A missing place with recorded lat/lon also counts. Only 'no location
    found / not reported' (or empty place and no coordinates) fails.
    """
    prec = str(r.get("precision") or "")
    place = _place_text(r)
    named = bool(place) and place.lower() not in NO_PLACE and "not specified" not in place.lower()
    has_coords = r.get("lat") is not None and r.get("lon") is not None
    # A named place or recorded coordinates means a location was reported, even
    # if a precision note mentions a second person's location "not given".
    if named or has_coords:
        return True
    prec = str(r.get("precision") or "")
    if NO_LOCATION_PRECISION.search(prec):
        return False
    return False


def _int_field(r, *keys):
    n = 0
    for k in keys:
        v = r.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v >= n:
            n = int(v)
    return n


def _source_independent_count(r) -> int:
    """Count distinct original/media-report sources, collapsing relays and reposts.

    This is a lower-bound helper only. Database listings, 'media republish'
    roles, and 'Original post (as linked by …)' entries are the same report
    again and do not count. Two news write-ups of one clip are still easy to
    over-count, so admit() does not rely on this alone when an explicit
    report/witness count is present; it is used only as a ceiling-safe
    supplement when those fields are missing and the text also claims
    multiple witnesses.
    """
    seen = set()
    n = 0
    for s in r.get("sources") or []:
        if not isinstance(s, dict):
            continue
        role = (s.get("role") or "").strip().lower()
        name = str(s.get("name") or "")
        if role in RELAY_ROLES or RELAY_NAME.search(name) or s.get("via"):
            continue
        url = str(s.get("url") or "").split("?")[0].rstrip("/").lower()
        host = urlparse(url).netloc.lower().lstrip("www.") if url else ""
        key = url or name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if role in ("original report", "media report", "first-hand report", "") or not role:
            n += 1
    return n


def independent_corroboration_count(r) -> int:
    """How many independent witnesses/reports the record itself supports.

    Uses (in descending trust): explicit count / reportCount / witnessCount;
    grade basis 'Multiple witnesses' or reasons that say two or more witnesses
    or separate reports; numbers parsed from the evidence/narrative text.

    Source-URL counts are not used as the primary figure: an original post
    plus a database listing, or several republishes of one clip, are not
    independent corroboration.
    """
    n = _int_field(r, "count", "reportCount", "witnessCount")
    g = r.get("evidenceGrade") or r.get("grade") or {}
    reasons = g.get("reasons") if isinstance(g, dict) else None
    basis = (g.get("basis") if isinstance(g, dict) else "") or ""
    text = " ".join(
        str(x) for x in (
            r.get("evidence"), r.get("narrative"), r.get("summary"),
            basis, " ".join(reasons or []),
        ) if x
    )
    if basis == "Multiple witnesses" or any(
        "Two or more witnesses or separate reports" in str(x) for x in (reasons or [])
    ):
        n = max(n, 2)
    for m in MULTI.finditer(text):
        # "no independent witnesses" / "not multiple reports" are not corroboration.
        lead = text[max(0, m.start() - 24):m.start()].lower()
        if re.search(r"\b(?:no|not|without|lacks?|zero|never)\s+(?:\w+\s+){0,3}$", lead + " "):
            continue
        if re.search(r"\bno\s+$", lead):
            continue
        chunk = m.group(0)
        num = re.search(r"\d{1,3}", chunk)
        words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "multiple": 2, "several": 2, "many": 2}
        val = int(num.group(0)) if num else next((words[w] for w in words if w in chunk.lower()), 2)
        if val >= 2:
            n = max(n, val)
    return n if n >= 1 else 1


def has_media(r) -> bool:
    media = r.get("media") or []
    if any(isinstance(m, dict) and m.get("url") for m in media):
        return True
    return bool(r.get("mediaAttached"))


def is_sighting(r) -> bool:
    kind = r.get("kind")
    if kind:
        return kind == "sighting"
    # Grok Page events.json entries have no kind; they are all sightings.
    # OSINT lives in a separate array.
    return "marker" in r and r.get("marker") in ("red", "blue", "yellow") or "evidenceGrade" in r or "label" in r or r.get("origin") in ("seed", "auto")


def evaluate(r) -> dict:
    """Return {admit, reason, grade, corroboration, hasLocation, hasMedia} for a sighting."""
    loc = has_reported_location(r)
    level, _ = _grade(r)
    if level is None:
        try:
            from grading import grade as _compute_grade
            computed = _compute_grade(r)
            # Do not mutate the caller's record; use the computed level only.
            r = dict(r)
            r["grade"] = computed
            level, _ = computed.get("level"), computed
            level = computed.get("level")
        except Exception:
            pass
    corr = independent_corroboration_count(r)
    media = has_media(r)
    if not loc:
        return {"admit": False, "reason": REASON_NO_LOCATION, "grade": level,
                "corroboration": corr, "hasLocation": False, "hasMedia": media}
    if level is not None and level <= 2 and corr < 2:
        return {"admit": False, "reason": REASON_WEAK, "grade": level,
                "corroboration": corr, "hasLocation": True, "hasMedia": media}
    # Ungraded sighting: require location (already passed) and treat missing
    # grade as not yet meeting the evidence bar unless corroboration is already 2+.
    if level is None and corr < 2:
        return {"admit": False, "reason": REASON_WEAK, "grade": level,
                "corroboration": corr, "hasLocation": True, "hasMedia": media}
    return {"admit": True, "reason": None, "grade": level,
            "corroboration": corr, "hasLocation": True, "hasMedia": media}


def sort_key(r):
    """Default display/search rank: media first, then higher grade, then newest."""
    level, _ = _grade(r)
    swept = r.get("sweptAt") or r.get("discovered") or r.get("publishedAt") or ""
    label = _place_text(r) or r.get("title") or r.get("id") or ""
    return (0 if has_media(r) else 1, -(level or 0), swept, label)


def _item_id(obj, record=None):
    if isinstance(obj, dict) and obj.get("id"):
        return obj["id"]
    rec = obj.get("formerRecord") if isinstance(obj, dict) else None
    if isinstance(rec, dict) and rec.get("id"):
        return rec["id"]
    if isinstance(record, dict) and record.get("id"):
        return record["id"]
    return None


def _exclusion_record(r, ev, when, url=None):
    """Public-site excluded.json item, or a wrapper around a Grok event."""
    srcs = r.get("sources") or []
    first_url = url or next((s.get("url") for s in srcs if isinstance(s, dict) and s.get("url")), None)
    return {
        "id": r.get("id"),
        "title": (r.get("title") or r.get("label") or r.get("id") or "")[:220],
        "url": first_url,
        "publisher": (srcs[0].get("name") if srcs and isinstance(srcs[0], dict) else None),
        "published": r.get("publishedAt") or r.get("published") or r.get("eventDate"),
        "family": r.get("feed") or r.get("origin"),
        "decision": "excluded",
        "gate": "location-or-evidence-2026-11-18",
        "gateVersion": GATE_VERSION,
        "reasons": [ev["reason"]],
        "grade": ev.get("grade"),
        "corroboration": ev.get("corroboration"),
        "excludedAt": when,
        "formerRecord": r,
    }


def _recover_record(item):
    if not isinstance(item, dict):
        return None
    rec = item.get("formerRecord")
    if isinstance(rec, dict) and rec.get("id"):
        rec = dict(rec)
        rec.pop("exclusion", None)
        return rec
    # Grok-style: the excluded object may be the event itself plus an exclusion block.
    if item.get("id") and (item.get("evidenceGrade") or item.get("narrative") or item.get("label")):
        rec = {k: v for k, v in item.items() if k not in ("exclusion", "decision", "gate", "gateVersion", "reasons", "formerRecord", "excludedAt", "corroboration")}
        # If we stored the event as-is with an 'exclusion' key only
        if "marker" in item or "evidenceGrade" in item or "label" in item:
            return rec if rec.get("id") else None
    return None


def apply_gate(records: list, excluded_items: list, *, now=None, sighting=None):
    """Split sighting reports into admitted vs excluded; re-admit when they pass.

    `records` is the live list (Grok `events` or public `reports`).
    `excluded_items` is the existing excluded list (Grok `events` or public `items`).
    Context/OSINT entries in `records` are always kept.
    Returns (kept, excluded, stats).
    """
    when = now or _now_denver()
    is_s = sighting or (lambda r: (r.get("kind") or "sighting") == "sighting" or "kind" not in r)

    kept, new_excl = [], []
    stats = {
        "considered": 0, "admitted": 0, "excludedNoLocation": 0,
        "excludedWeak": 0, "readmitted": 0, "contextKept": 0,
        "alreadyExcluded": 0,
    }

    live_by_id = {r.get("id"): r for r in records if r.get("id")}

    # Re-admit: prefer a live copy (it may have gained sources, a grade, or a place)
    # over the snapshot stored when the report was first excluded.
    still_excluded = []
    seen_ids = set()
    for item in excluded_items:
        # Leave screening/news exclusions untouched; only this gate's entries can come back.
        if not (isinstance(item, dict) and (item.get("gate") or item.get("gateVersion"))):
            still_excluded.append(item)
            continue
        rec = _recover_record(item)
        if rec is None or not is_s(rec):
            still_excluded.append(item)
            continue
        eid = rec.get("id")
        if eid and eid in live_by_id:
            rec = live_by_id[eid]
        ev = evaluate(rec)
        if ev["admit"]:
            kept.append(rec)
            stats["readmitted"] += 1
            if eid:
                seen_ids.add(eid)
        else:
            if isinstance(item, dict):
                item = dict(item)
                item["formerRecord"] = rec
                item["reasons"] = [ev["reason"]]
                item["grade"] = ev.get("grade")
                item["corroboration"] = ev.get("corroboration")
                item["gate"] = "location-or-evidence-2026-11-18"
                item["id"] = eid
            still_excluded.append(item)
            if eid:
                seen_ids.add(eid)

    for r in records:
        if r.get("id") in seen_ids:
            if not any(x.get("id") == r.get("id") for x in kept):
                stats["alreadyExcluded"] += 1
            continue
        if not is_s(r):
            kept.append(r)
            stats["contextKept"] += 1
            continue
        stats["considered"] += 1
        ev = evaluate(r)
        if ev["admit"]:
            kept.append(r)
            stats["admitted"] += 1
        else:
            new_excl.append(_exclusion_record(r, ev, when))
            if ev["reason"] == REASON_NO_LOCATION:
                stats["excludedNoLocation"] += 1
            else:
                stats["excludedWeak"] += 1

    excluded = new_excl + still_excluded
    stats["remaining"] = sum(1 for r in kept if is_s(r))
    stats["excludedTotal"] = stats["excludedNoLocation"] + stats["excludedWeak"]
    return kept, excluded, stats


def excluded_item_key(item, *, normalize_url=None):
    """Stable identity for an excluded row: report id if present, else URL, else title.

    Witness-database case pages often share one listing URL (MUFON last-20,
    UFO*BC, Probed, ufosighting.report). Deduping only by URL would drop
    distinct reports. Id-less screening rows still key by URL.
    """
    if not isinstance(item, dict):
        return None
    eid = item.get("id")
    if eid:
        return ("id", str(eid))
    url = (item.get("url") or "").strip()
    if url:
        if normalize_url:
            try:
                url = normalize_url(url) or url
            except Exception:
                pass
        return ("url", url)
    title = (item.get("title") or "").strip()
    return ("title", title) if title else None


def merge_excluded_items(*lists, normalize_url=None):
    """Union excluded lists without dropping distinct report ids.

    Id-less screening rows still collapse to one entry per URL (or title).
    When two rows share a key, keep the one with a gate/formerRecord, else
    the earlier row (callers should pass newest-first lists).
    """
    def score(e):
        return (
            1 if e.get("gate") or e.get("gateVersion") else 0,
            1 if e.get("formerRecord") else 0,
            1 if e.get("id") else 0,
            e.get("excludedAt") or "",
        )

    by, order, anon = {}, [], 0
    for lst in lists:
        for e in lst or []:
            if not isinstance(e, dict):
                continue
            k = excluded_item_key(e, normalize_url=normalize_url)
            if k is None:
                anon += 1
                k = ("anon", anon)
            if k not in by:
                by[k] = e
                order.append(k)
            elif score(e) > score(by[k]):
                by[k] = e
    return [by[k] for k in order]


def excluded_ids(excluded_items: Iterable) -> set:
    out = set()
    for item in excluded_items or []:
        if not isinstance(item, dict):
            continue
        if item.get("id"):
            out.add(item["id"])
        rec = item.get("formerRecord")
        if isinstance(rec, dict) and rec.get("id"):
            out.add(rec["id"])
    return out


def refresh_grok_meta(d, when=None):
    ev = d.get("events") or []
    meta = d.setdefault("meta", {})
    meta["event_count"] = len(ev)
    meta["osint_count"] = len(d.get("osint") or [])
    meta["red_locations"] = sum(1 for e in ev if e.get("marker") == "red")
    meta["blue_locations"] = sum(1 for e in ev if e.get("marker") == "blue")
    meta["yellow_locations"] = sum(1 for e in ev if e.get("marker") == "yellow")
    meta["media_report_count"] = sum(1 for e in ev if has_media(e))
    meta["media_link_count"] = sum(len(e.get("media") or []) for e in ev)
    rc = {}
    for e in ev:
        t = e.get("reporterType") or "unknown"
        rc[t] = rc.get(t, 0) + 1
    meta["reporter_counts"] = rc
    windows = {}
    for e in ev:
        w = e.get("window")
        if w:
            windows[w] = windows.get(w, 0) + 1
    if windows:
        meta["windows"] = windows
    return meta


def apply_grok_files(events_path, excluded_path, page_data_path=None, *, dry=False):
    with open(events_path, encoding="utf-8") as f:
        d = json.load(f)
    excluded_doc = {"about": "Sighting reports removed from the live log by the 2026-11-18 location/evidence gate. On-disk archives are kept; these reports are not shown and are not re-archived.",
                    "rule": GATE_RULE, "updatedAt": None, "events": []}
    if os.path.exists(excluded_path):
        with open(excluded_path, encoding="utf-8") as f:
            existing = json.load(f)
        if isinstance(existing, dict):
            excluded_doc.update({k: existing[k] for k in existing if k != "events" or existing.get("events")})
            excluded_doc["events"] = existing.get("events") or existing.get("items") or []
        elif isinstance(existing, list):
            excluded_doc["events"] = existing
    kept, excluded, stats = apply_gate(
        d.get("events") or [], excluded_doc["events"],
        sighting=lambda r: True,  # every events[] entry is a sighting
    )
    d["events"] = kept
    refresh_grok_meta(d)
    when = _now_denver()
    excluded_doc["events"] = excluded
    excluded_doc["updatedAt"] = when
    excluded_doc["rule"] = GATE_RULE
    excluded_doc["stats"] = {k: stats[k] for k in stats}
    if not dry:
        _atomic_json(events_path, d)
        _atomic_json(excluded_path, excluded_doc)
        if page_data_path:
            _write_page_data(d, page_data_path)
    return d, excluded_doc, stats


def apply_public_files(events_path, excluded_path, *, dry=False):
    with open(events_path, encoding="utf-8") as f:
        d = json.load(f)
    if os.path.exists(excluded_path):
        with open(excluded_path, encoding="utf-8") as f:
            ex = json.load(f)
    else:
        ex = {"about": "Items the automatic sweep read but did NOT log as sightings, with the rule reasons.", "items": []}
    kept, excluded, stats = apply_gate(
        d.get("reports") or [], ex.get("items") or [],
        sighting=lambda r: (r.get("kind") or "sighting") == "sighting",
    )
    d["reports"] = kept
    meta = d.setdefault("meta", {})
    meta["reportCount"] = len(kept)
    meta["noLocationCount"] = sum(1 for r in kept if r.get("kind") == "sighting" and not has_reported_location(r))
    meta["admissionGate"] = {"version": GATE_VERSION, "rule": GATE_RULE, "lastRun": stats}
    ex["items"] = excluded
    ex["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry:
        _atomic_json(events_path, d, indent=None)
        _atomic_json(excluded_path, ex, indent=None)
    return d, ex, stats


def _write_page_data(d, path):
    """Compact grade + Sky Check payload for the Grok Page (same shape as grade_sky.py)."""
    STD_NC = {"Re-entries", "Aircraft"}
    page = {}
    for e in d.get("events") or []:
        g, sc = e.get("evidenceGrade") or {}, e.get("skyCheck") or {}
        if sc.get("status") == "checked":
            items = [[i["check"], i["result"], 1 if i.get("flag") else 0] + ([i["url"]] if i.get("url") else [])
                     for i in sc.get("items") or [] if i.get("check") not in STD_NC]
            s = ["c",
                 (sc.get("atDenver") or "")
                 + (" (approximate time, wider window)" if sc.get("approximate") else "")
                 + " · " + (sc.get("timeBasis") or "")
                 + (" · location approximate" if sc.get("locationApproximate") else ""),
                 items]
        else:
            s = ["u", sc.get("reason") or "Sky Check unavailable", []]
        page[e["id"]] = [g.get("level") or 0, g.get("reasons") or [], s]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(page, f, ensure_ascii=False, separators=(",", ":"))


def _atomic_json(path, obj, indent=2):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if indent is None:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
            f.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Apply the 2026-11-18 location/evidence admission gate.")
    ap.add_argument("--events", help="events.json (Grok) or docs/data/events.json (public)")
    ap.add_argument("--excluded", help="excluded.json path")
    ap.add_argument("--page-data", help="Optional grade-sky/page-data.json to rewrite from remaining Grok events")
    ap.add_argument("--public", action="store_true", help="Public-site schema (reports[] / items[])")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.events or not args.excluded:
        ap.error("--events and --excluded are required")
    if args.public:
        _, _, stats = apply_public_files(args.events, args.excluded, dry=args.dry_run)
    else:
        _, _, stats = apply_grok_files(args.events, args.excluded, args.page_data, dry=args.dry_run)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
