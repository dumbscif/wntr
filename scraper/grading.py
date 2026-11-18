"""Evidence grade (1-5), computed only from what the record itself contains. No AI, no guessing.

  5  Official or sensor confirmation: a military/government/police body confirmed or identified THIS report,
     or radar/sensor data is cited.
  4  Photo or video: media is linked from the record (or the cited post/article is itself the footage).
  3  Multiple witnesses: two or more witnesses or separate reports are stated.
  2  First-hand witness: the witness's own report (report form, own post) or a named witness quoted by media.
  1  Single unverified claim: anonymous, second-hand, relayed, or no detail.

Then the grade is LOWERED one step for each missing basic (never below 1):
  - account is second-hand / relayed with the original not opened
  - no sighting date recorded
  - no location recorded
The grade says how well documented a report is, not what the object was. An official identification
(e.g. "it was Starlink") is strong documentation of an ordinary explanation.
"""
import re

GRADE_VERSION = 1
LABELS = {1: "Single unverified claim", 2: "First-hand witness", 3: "Multiple witnesses", 4: "Photo / video", 5: "Official or sensor confirmation"}

NEG = r"(?:no|not|without|unconfirmed|unverified|lacks?|never)\b[^.;]{0,40}"
OFFICIAL = re.compile(r"\b(?:official(?:ly)?|air force|ministry|mod\b|usaf|navy|army|police|sheriff|coast guard|faa\b|aaro\b|ahac\b|cridovni|government|"
                      r"military|defen[cs]e (?:ministry|department)|authority|authorities|airport director|romatsa|aeronautical authority)\b[^.;]{0,80}"
                      r"\b(?:confirm|identif|statement|stated|said|attribut|explain)", re.I)
SENSOR = re.compile(r"\b(?:radar|sensor data|infrared sensor|flir|all-sky camera network|meteor camera network|seismic)\b", re.I)
MEDIA_WORDS = re.compile(r"\b(?:video|videos|footage|photo|photos|photograph|clip|dashcam|security[- ]camera|image files?|filmed|vídeo|foto|imagen|grab(?:an|aron|ó)|capta(?:n|ron|do))\b", re.I)
MULTI = re.compile(r"\b(?:multiple|many|several|numerous|two|three|four|five|six|seven|eight|nine|ten|\d{1,3}|dozens of|hundreds of)\s+(?:named\s+|stated\s+|separate\s+|independent\s+)?"
                   r"(?:witness|witnesses|residents|observers|people|users|callers|drivers|passengers|pilots|amateur astronomers|videos|reports|observers)\b|\bresidents'|\bresident videos\b|"
                   r"\bmulti-locality\b|\bwitnesses\b", re.I)
SECOND = re.compile(r"\b(?:second-hand|secondhand|relay(?:ed)? (?:listing|post)|automated relay|repost|summary only|public summary only|via aggregator|original (?:post|source|filmer)[^.;]{0,30}not|"
                    r"known only via|secondary summary|credited to)\b", re.I)
FIRST = re.compile(r"\b(?:first-hand|firsthand|self-submitted|own (?:post|report)|named (?:witness|passenger|civilian|resident)|interview|resident (?:video|footage)|"
                   r"witness (?:video|report|account)|form submission|report form|submitted)\b", re.I)
FIRST_SITES = ("ufomeldpunt.nl", "ufo-hunters.com", "mufoncms.com", "nuforc.org", "ufokarte.de", "ufobc.ca", "ufosighting.report")


def grade(r):
    """r: archive record (GitLab events.json schema). Returns {level, label, reasons[], version}."""
    ev = " ".join(str(r.get(k) or "") for k in ("evidence", "appearance"))
    narr = str(r.get("narrative") or r.get("summary") or "")
    title = str(r.get("title") or "")
    media = [m for m in (r.get("media") or []) if isinstance(m, dict) and m.get("url")]
    srcs = r.get("sources") or []
    urls = " ".join(s.get("url", "") for s in srcs).lower()
    auto = r.get("origin") == "auto"
    reasons = []

    official = r.get("marker") == "yellow" or bool(OFFICIAL.search(ev) and not re.search(NEG + r"official", ev, re.I))
    sensor = (not auto) and bool(SENSOR.search(ev)) and not re.search(r"\bno\b[^.;]{0,30}(?:radar|sensor)", ev, re.I)
    media_linked = bool(media)
    media_source = False
    if not media_linked and auto:
        # automatic records: the cited post/article is itself the footage only when the source says so in its headline
        media_source = bool(MEDIA_WORDS.search(title)) or bool(r.get("mediaAttached"))
    witnesses = r.get("witnessCount") or 0
    multi = (r.get("reportCount") or 1) >= 2 or witnesses >= 2 or bool(MULTI.search(ev)) or (auto and bool(re.search(r"\b(?:residents|vecinos|witnesses|testigos|moradores)\b", title, re.I)))
    if re.search(r"\bsingle\b", ev, re.I) and not re.search(r"\b(?:two|three|\d+) (?:stated )?witnesses\b", ev, re.I) and witnesses < 2 and (r.get("reportCount") or 1) < 2:
        multi = False
    second = bool(SECOND.search(ev))
    first = bool(FIRST.search(ev)) or any(s in urls for s in FIRST_SITES) or str(r.get("reporterTypeBasis") or "").startswith("Member of the public") \
        or (auto and any((s.get("role") == "original report") for s in srcs) and not second)

    if official or sensor:
        level = 5
        reasons.append(("Official/military/police statement about this report is cited" + (" (automatic keyword rule: read the source)" if auto else "")) if official else "Radar or sensor data is cited")
    elif media_linked or media_source:
        level = 4
        reasons.append(f"{len(media)} photo/video link(s) recorded" if media_linked else "Cited post/article presents the photo or video (not archived here)")
    elif multi:
        level = 3
        reasons.append("Two or more witnesses or separate reports are stated")
    elif first:
        level = 2
        reasons.append("First-hand account (witness's own report or named witness)")
    else:
        level = 1
        reasons.append("Single claim with no first-hand, media or official support recorded")
    if level < 4 and re.search(r"(?:video|photo)s?[^.;]{0,30}(?:claimed|referenced|not verified|but url not)", ev, re.I):
        reasons.append("Media mentioned but not verified, so not counted")
    if level < 3 and multi is False and witnesses == 1:
        reasons.append("One witness stated")

    downs = []
    if second:
        downs.append("second-hand or relayed account (original not opened)")
    date = str(r.get("eventDate") or "")
    if not re.match(r"\d{4}-\d\d-\d\d", date):
        downs.append("no sighting date recorded")
    if r.get("lat") is None or r.get("lon") is None:
        downs.append("no location recorded")
    final = max(1, level - len(downs))
    for d in downs:
        reasons.append("Lowered one step: " + d)
    return {"level": final, "label": LABELS[final], "basis": LABELS[level], "reasons": reasons, "version": GRADE_VERSION}
