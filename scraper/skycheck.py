"""Sky Check: what was overhead or happening near a report's sighting time and place.

Free, no-login data only:
  * Starlink + bright satellites/ISS: CelesTrak GP element sets (TLE), propagated with SGP4.
    Orbit data are only trusted within 14 days of their epoch, so old sightings skip this check.
  * Rocket launches: Launch Library 2 (The Space Devs) free API, one cached request per ~12 h.
  * Sun, Moon, bright planets: JPL DE421 ephemeris via skyfield.
  * Major meteor showers: fixed IMO calendar table.
  * Flights and re-entries: not checked (no free historical source without a login).
Results are possible explanations to compare, never verdicts.
"""
import json, math, os, re, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SKY_VERSION = 1
DENVER = ZoneInfo("America/Denver")
UA = "WNTR-UFO-Archive/1.0 (public sighting archive; Sky Check)"
TLE_MAX_AGE_H = 10          # re-download CelesTrak sets at most every 10 h (CelesTrak asks for <= every 2 h)
LAUNCH_MAX_AGE_H = 11
TLE_TRUST_DAYS = 14
LAUNCH_WINDOW_DAYS = 60
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# IMO major showers: (name, start (m,d), end (m,d), peak (m,d))
SHOWERS = [("Quadrantids", (12, 28), (1, 12), (1, 3)), ("Lyrids", (4, 14), (4, 30), (4, 22)), ("Eta Aquariids", (4, 19), (5, 28), (5, 6)),
           ("Southern Delta Aquariids", (7, 12), (8, 23), (7, 30)), ("Perseids", (7, 17), (8, 24), (8, 12)), ("Draconids", (10, 6), (10, 10), (10, 8)),
           ("Orionids", (10, 2), (11, 7), (10, 21)), ("Southern Taurids", (9, 10), (11, 20), (10, 10)), ("Northern Taurids", (10, 20), (12, 10), (11, 12)),
           ("Leonids", (11, 6), (11, 30), (11, 17)), ("Geminids", (12, 4), (12, 20), (12, 14)), ("Ursids", (12, 17), (12, 26), (12, 22))]
COARSE = re.compile(r"state|province|country|region|arbitrary|centre|center|admin|not a sighting position|area|route|county-level|approximate: probed", re.I)


def denver(dt, with_date=True):
    l = dt.astimezone(DENVER)
    s = l.strftime("%-I:%M %p ") + l.tzname()
    return (l.strftime("%b %-d, ") + s) if with_date else s


def compass(az):
    return COMPASS[int((az % 360) / 22.5 + 0.5) % 16]


def height_words(alt):
    return "low" if alt < 20 else "high" if alt > 60 else "mid-sky"


# ------------------------------------------------------------------ sighting time
_CLOCK = re.compile(r"(?<![\d:])(\d{1,2})[:.h](\d{2})(?:\s*([ap])\.?\s?m\.?)?(?![\d])", re.I)
_TITLE_DT = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? (\d{1,2}),? (\d{4}),? (\d{1,2}):(\d{2})\s*([ap])\.?m\.?", re.I)
_APPROX = re.compile(r"\b(?:about|approx|approximately|around|roughly|circa|ca\.|between|inferred|estimated|unclear)\b|~|–|-\s*\d", re.I)


def sighting_instant(r):
    """Return (utc_datetime, approximate, basis) or (None, None, reason). Never guesses a missing clock time or zone."""
    tzname = r.get("tz")
    tl = r.get("eventTimeLocal") or ""
    date = (r.get("eventDate") or "").strip()
    try:
        tz = ZoneInfo(tzname) if tzname else None
    except Exception:
        tz = None
    if r.get("eventAt") and str(r.get("timeBasis", "")).lower().startswith("witness") and _CLOCK.search(tl or ""):
        try:
            return datetime.fromisoformat(r["eventAt"].replace("Z", "+00:00")).astimezone(timezone.utc), bool(_APPROX.search(tl)), "witness-reported time"
        except Exception:
            pass
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", date)
    c = _CLOCK.search(tl)
    if m and c:
        if tz is None:
            return None, None, "sighting time zone not recorded"
        h, mi, ap = int(c.group(1)), int(c.group(2)), (c.group(3) or "").lower()
        if ap == "p" and h < 12: h += 12
        if ap == "a" and h == 12: h = 0
        if h > 23 or mi > 59:
            return None, None, "sighting time could not be read"
        local = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), h, mi, tzinfo=tz)
        approx = bool(_APPROX.search(tl) or _APPROX.search(date[10:]))
        return local.astimezone(timezone.utc), approx, "date and local time as recorded"
    t = _TITLE_DT.search((r.get("title") or "") + " " + (r.get("summary") or "")[:300])
    if t and tz is not None:
        h, mi = int(t.group(4)), int(t.group(5))
        if t.group(6).lower() == "p" and h < 12: h += 12
        if t.group(6).lower() == "a" and h == 12: h = 0
        try:
            local = datetime(int(t.group(3)), MONTHS[t.group(1).lower()[:3]], int(t.group(2)), h, mi, tzinfo=tz)
            return local.astimezone(timezone.utc), False, "date and time stated in the report headline"
        except Exception:
            pass
    if m and not c:
        return None, None, "sighting time not reported (date only)"
    return None, None, "sighting time not reported"


# ------------------------------------------------------------------ data loading (cached)
class Sky:
    def __init__(self, cache_dir, get=None, log=print):
        self.dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.log = log
        self._get = get
        self.ts = self.eph = None
        self.sats = {}
        self.launches = None
        self.notes = []

    def _http(self, url, timeout=40):
        if self._get:
            r = self._get(url)
            return r.content if r is not None else None
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        return r.content if r.ok else None

    def _cached(self, name, url, max_age_h, validate):
        p = os.path.join(self.dir, name)
        fresh = os.path.exists(p) and (time.time() - os.path.getmtime(p)) < max_age_h * 3600
        if not fresh:
            try:
                body = self._http(url)
                if body and validate(body):
                    with open(p, "wb") as f:
                        f.write(body)
                else:
                    self.notes.append(f"{name}: download failed or invalid; using cached copy if any")
            except Exception as e:
                self.notes.append(f"{name}: {type(e).__name__}")
        return p if os.path.exists(p) else None

    def load_ephemeris(self):
        if self.eph is None:
            from skyfield.api import Loader
            ld = Loader(self.dir, verbose=False)
            self.ts = ld.timescale(builtin=True)
            self.eph = ld("de421.bsp")
        return self.eph

    def load_sats(self, group):
        if group in self.sats:
            return self.sats[group]
        from sgp4.api import Satrec, SatrecArray
        import numpy as np
        p = self._cached(f"tle-{group}.txt", f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle", TLE_MAX_AGE_H,
                         lambda b: b.count(b"\n1 ") > 10)
        if not p:
            self.sats[group] = None
            return None
        lines = [l.rstrip() for l in open(p, encoding="utf-8", errors="replace") if l.strip()]
        names, sats, intl, mm, epochs = [], [], [], [], []
        for i in range(0, len(lines) - 2, 3):
            n, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
            if not (l1.startswith("1 ") and l2.startswith("2 ")):
                continue
            try:
                s = Satrec.twoline2rv(l1, l2)
            except Exception:
                continue
            names.append(n.strip()); sats.append(s); intl.append(l1[9:14].strip()); mm.append(float(l2[52:63])); epochs.append(s.jdsatepoch + s.jdsatepochF)
        if not sats:
            self.sats[group] = None
            return None
        data = {"names": names, "arr": SatrecArray(sats), "intl": intl, "mm": np.array(mm), "epoch_jd": float(np.median(epochs)),
                "fetched": datetime.fromtimestamp(os.path.getmtime(p), timezone.utc)}
        self.sats[group] = data
        return data

    def load_launches(self, now):
        if self.launches is not None:
            return self.launches
        since = (now - timedelta(days=LAUNCH_WINDOW_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
        url = f"https://ll.thespacedevs.com/2.3.0/launches/?net__gte={since}&net__lte={now.strftime('%Y-%m-%dT%H:%M:%SZ')}&limit=100&mode=normal&ordering=net"
        def ok(b):
            try:
                return "results" in json.loads(b)
            except Exception:
                return False
        p = self._cached("launches.json", url, LAUNCH_MAX_AGE_H, ok)
        out = []
        if p:
            try:
                d = json.load(open(p, encoding="utf-8"))
                for x in d.get("results", []):
                    pad = x.get("pad") or {}
                    try:
                        lat, lon = float(pad.get("latitude")), float(pad.get("longitude"))
                    except Exception:
                        continue
                    out.append({"name": x.get("name"), "net": datetime.fromisoformat(x["net"].replace("Z", "+00:00")), "lat": lat, "lon": lon,
                                "pad": (pad.get("location") or {}).get("name") or pad.get("name"), "status": (x.get("status") or {}).get("abbrev"),
                                "url": "https://ll.thespacedevs.com/2.3.0/launches/" + x["id"] + "/"})
                self.launch_cover = (now - timedelta(days=LAUNCH_WINDOW_DAYS), datetime.fromtimestamp(os.path.getmtime(p), timezone.utc))
            except Exception as e:
                self.notes.append(f"launches.json unreadable: {e}")
        self.launches = out if p else None
        return self.launches


def _haversine(a, b, c, d):
    r = math.radians
    h = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


# ------------------------------------------------------------------ checks
def _sun_moon_planets(sky, dt, lat, lon):
    from skyfield.api import wgs84
    from skyfield import almanac
    eph = sky.load_ephemeris()
    t = sky.ts.from_datetime(dt)
    obs = eph["earth"] + wgs84.latlon(lat, lon)
    def altaz(key):
        a = obs.at(t).observe(eph[key]).apparent().altaz()
        return a[0].degrees, a[1].degrees
    sun_alt, sun_az = altaz("sun")
    if sun_alt > -0.833: sky_state = "daylight"
    elif sun_alt > -6: sky_state = "civil twilight (bright dusk/dawn)"
    elif sun_alt > -12: sky_state = "nautical twilight"
    elif sun_alt > -18: sky_state = "astronomical twilight"
    else: sky_state = "full dark"
    items = [{"check": "Sun", "result": f"Sun {sun_alt:.0f}° {'above' if sun_alt >= 0 else 'below'} the horizon ({sky_state})."}]
    m_alt, m_az = altaz("moon")
    frac = float(almanac.fraction_illuminated(eph, "moon", t)) * 100
    items.append({"check": "Moon", "result": (f"Moon {frac:.0f}% lit, {m_alt:.0f}° up in the {compass(m_az)} ({height_words(m_alt)})." if m_alt > 0 else f"Moon below the horizon ({frac:.0f}% lit)."),
                  "flag": m_alt > 0 and m_alt < 15})
    bright = []
    try:
        from skyfield.magnitudelib import planetary_magnitude
    except Exception:
        planetary_magnitude = None
    for name, key in [("Venus", "venus"), ("Jupiter", "jupiter barycenter"), ("Mars", "mars"), ("Saturn", "saturn barycenter"), ("Mercury", "mercury")]:
        alt, az = altaz(key)
        if alt <= 0:
            continue
        mag = None
        if planetary_magnitude:
            try:
                mag = float(planetary_magnitude(eph["earth"].at(t).observe(eph[key])))
            except Exception:
                mag = None
        if mag is None or mag <= 1.5:
            bright.append((mag if mag is not None else 9, f"{name} {('mag ' + format(mag, '.1f').replace('-', '−') + ', ') if mag is not None else ''}{alt:.0f}° up in the {compass(az)}"))
    bright.sort()
    if sun_alt > -3:
        items.append({"check": "Bright planets", "result": "Daylight/bright twilight: planets other than Venus are hard to see." + (" Up: " + "; ".join(b for _, b in bright) + "." if bright else "")})
    else:
        items.append({"check": "Bright planets", "result": ("Above the horizon: " + "; ".join(b for _, b in bright) + ". A bright planet, especially low in the sky, is a common 'hovering light'.") if bright else "No bright planet above the horizon.",
                      "flag": any(m <= -1.5 for m, _ in bright)})
    return sun_alt, items


def _showers(dt, sun_alt):
    d = (dt.month, dt.day)
    near, other = [], []
    for name, start, end, peak in SHOWERS:
        inside = (start <= d <= end) if start <= end else (d >= start or d <= end)
        if inside:
            pk = datetime(dt.year if not (peak[0] == 1 and dt.month == 12) else dt.year + 1, peak[0], peak[1], tzinfo=timezone.utc)
            if abs((dt - pk).total_seconds()) <= 3 * 86400:
                near.append(f"{name} near peak ({pk.strftime('%b %-d')})")
            else:
                other.append(name)
    if not near and not other:
        return {"check": "Meteor showers", "result": "No major meteor shower active."}
    txt = "; ".join(near + ([("also active: " if near else "Active (not near peak): ") + ", ".join(other)] if other else [])) + "."
    txt = txt[0].upper() + txt[1:]
    tail = " Bright meteors or fireballs are possible." if (near and sun_alt < -6) else (" (Meteors are rarely seen in daylight/twilight.)" if sun_alt >= -6 else "")
    return {"check": "Meteor showers", "result": txt + tail, "flag": bool(near) and sun_alt < -6}


def _sat_check(sky, dt, lat, lon, approx, group, label):
    import numpy as np
    from sgp4.api import jday
    data = sky.load_sats(group)
    if not data:
        return {"check": label, "result": "Not checked: orbit data could not be downloaded this sweep.", "retry": True}
    epoch = datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=data["epoch_jd"] - 2451545.0)
    gap = abs((dt - epoch).total_seconds()) / 86400
    if gap > TLE_TRUST_DAYS:
        return {"check": label, "result": f"Not checked: sighting is {gap:.0f} days from the available orbit data; positions would be unreliable."}
    win = 30 if approx else 10
    times = [dt + timedelta(minutes=m) for m in range(-win, win + 1)]
    jd = np.array([jday(t.year, t.month, t.day, t.hour, t.minute, t.second)[0] for t in times])
    fr = np.array([jday(t.year, t.month, t.day, t.hour, t.minute, t.second)[1] for t in times])
    err, r, _ = data["arr"].sgp4(jd, fr)                     # r: (nsat, ntime, 3) km, TEME
    tt = sky.ts.from_datetimes(times)
    theta = np.radians(tt.gmst * 15.0)                        # TEME -> Earth-fixed (polar motion ignored)
    c, s = np.cos(theta), np.sin(theta)
    x = c * r[..., 0] + s * r[..., 1]; y = -s * r[..., 0] + c * r[..., 1]; z = r[..., 2]
    la, lo = math.radians(lat), math.radians(lon)
    a, f = 6378.137, 1 / 298.257223563; e2 = f * (2 - f)
    N = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    ox, oy, oz = N * math.cos(la) * math.cos(lo), N * math.cos(la) * math.sin(lo), N * (1 - e2) * math.sin(la)
    dx, dy, dz = x - ox, y - oy, z - oz
    E = -math.sin(lo) * dx + math.cos(lo) * dy
    Nn = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    U = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    alt = np.degrees(np.arctan2(U, np.hypot(E, Nn))); az = np.degrees(np.arctan2(E, Nn)) % 360
    eph = sky.load_ephemeris()
    sun = eph["earth"].at(tt).observe(eph["sun"]).position.km.T  # (ntime, 3), equatorial frame
    sh = sun / np.linalg.norm(sun, axis=1)[:, None]
    proj = np.einsum("stk,tk->st", r, sh)
    perp = np.linalg.norm(r - proj[..., None] * sh[None, :, :], axis=2)
    sunlit = ~((proj < 0) & (perp < 6371.0))
    vis = (alt >= 10) & sunlit & (err == 0)
    idx = np.where(vis.any(axis=1))[0]
    span = f"±{win} min"
    if not len(idx):
        what = "Starlink satellite" if group == "starlink" else "ISS or bright satellite"
        return {"check": label, "result": f"No {what} sunlit and above 10° within {span} (orbit data from {epoch.strftime('%b %-d')})."}
    best = max(idx, key=lambda i: alt[i].max())
    j = int(alt[best].argmax())
    out = {"check": label, "flag": False}
    if group == "visual":
        iss = [i for i in idx if data["names"][i].startswith("ISS")]
        if iss:
            i = iss[0]; j = int(np.where(vis[i])[0][alt[i][vis[i]].argmax()])
            out["flag"] = True
            out["result"] = f"ISS visible: highest {alt[i, j]:.0f}° in the {compass(az[i, j])} at {denver(times[j], False)}. " \
                            f"{len(idx)} bright satellites/rocket bodies sunlit above 10° within {span}."
        else:
            out["result"] = f"{len(idx)} bright satellite(s)/rocket bodies sunlit above 10° within {span}; highest {data['names'][best].title()} at {alt[best, j]:.0f}° in the {compass(az[best, j])} ({denver(times[j], False)})."
        return out
    groups = {}
    for i in idx:
        groups.setdefault(data["intl"][i], []).append(i)
    train = max(groups.values(), key=len)
    low = [i for i in train if data["mm"][i] > 15.4]            # still low = recently launched, raising orbit
    now_n = int(vis[:, win].sum())
    msg = (f"At the reported time {now_n} Starlink satellite{'' if now_n == 1 else 's'} {'was' if now_n == 1 else 'were'} sunlit above 10° (most are faint; they are brightest soon after dusk or before dawn). "
           f"Highest in the ±{win} min window: {alt[best, j]:.0f}° in the {compass(az[best, j])} at {denver(times[j], False)}.")
    out["flag"] = False
    if len(low) >= 4:
        yr = "20" + data["intl"][train[0]][:2]
        msg += f" {len(low)} visible satellites are from one recent launch ({yr}-{data['intl'][train[0]][2:]}) still at low altitude: a 'string of lights' Starlink train is possible."
        out["flag"] = True
    out["result"] = msg
    return out


def _launch_check(sky, dt, lat, lon, now):
    ls = sky.load_launches(now)
    if ls is None:
        return {"check": "Rocket launches", "result": "Not checked: Launch Library 2 could not be reached this sweep.", "retry": True}
    if dt < now - timedelta(days=LAUNCH_WINDOW_DAYS - 1):
        return {"check": "Rocket launches", "result": f"Not checked: sighting is older than the {LAUNCH_WINDOW_DAYS}-day launch window kept in cache."}
    near = []
    for x in ls:
        dtm = (dt - x["net"]).total_seconds() / 60
        if -60 <= dtm <= 180:
            km = _haversine(lat, lon, x["lat"], x["lon"])
            if km <= 1600:
                near.append((km, x, dtm))
    if near:
        near.sort(key=lambda z: z[0])
        km, x, dtm = near[0]
        when = f"{abs(dtm):.0f} min {'before' if dtm >= 0 else 'after'} the reported time"
        return {"check": "Rocket launches", "flag": True, "url": x["url"],
                "result": f"{x['name']} launched from {x['pad']} at {denver(x['net'], False)}, {when}, {km:,.0f} km away. Launch and stage-separation plumes, especially at dusk or dawn, can look like glowing 'jellyfish' or spirals."}
    recent_sl = [x for x in ls if "starlink" in (x["name"] or "").lower() and timedelta(0) <= dt - x["net"] <= timedelta(days=5)]
    tail = f" Starlink launch in the previous 5 days: {recent_sl[-1]['name']} ({recent_sl[-1]['net'].strftime('%b %-d')}); fresh trains are brightest for a few days." if recent_sl else ""
    return {"check": "Rocket launches", "result": "No orbital launch within 1,600 km from 3 h before to 1 h after the reported time." + tail}


def sky_check(sky, r, now):
    """Compute one report's Sky Check dict (never raises)."""
    base = {"version": SKY_VERSION, "computedAt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z")}
    dt, approx, basis = sighting_instant(r)
    if dt is None:
        return {**base, "status": "unavailable", "reason": f"Sky Check unavailable: {basis}."}
    if r.get("lat") is None or r.get("lon") is None:
        return {**base, "status": "unavailable", "reason": "Sky Check unavailable: no sighting location recorded."}
    if dt > now + timedelta(hours=1):
        return {**base, "status": "unavailable", "reason": "Sky Check unavailable: recorded sighting time is in the future (likely a date error)."}
    lat, lon = float(r["lat"]), float(r["lon"])
    coarse = bool(COARSE.search(r.get("precision") or ""))
    items = []
    try:
        sun_alt, smp = _sun_moon_planets(sky, dt, lat, lon)
        items += smp
        items.append(_showers(dt, sun_alt))
    except Exception as e:
        return {**base, "status": "unavailable", "reason": f"Sky Check unavailable: ephemeris error ({type(e).__name__})."}
    if coarse:
        items.append({"check": "Starlink", "result": "Not checked: location is only approximate (state/region level), too coarse for satellite passes."})
        items.append({"check": "ISS & bright satellites", "result": "Not checked: location too approximate."})
    elif sun_alt > -4:
        items.append({"check": "Starlink", "result": "Not checked: satellites are not visible in daylight or bright twilight."})
    else:
        for grp, lab in (("starlink", "Starlink"), ("visual", "ISS & bright satellites")):
            try:
                items.append(_sat_check(sky, dt, lat, lon, approx, grp, lab))
            except Exception as e:
                items.append({"check": lab, "result": f"Not checked: computation error ({type(e).__name__}).", "retry": True})
    try:
        items.append(_launch_check(sky, dt, lat, lon, now))
    except Exception as e:
        items.append({"check": "Rocket launches", "result": f"Not checked: {type(e).__name__}.", "retry": True})
    items.append({"check": "Re-entries", "result": "Not checked: no free source publishes re-entry times and tracks."})
    items.append({"check": "Aircraft", "result": "Flight data not checked: no free historical flight-tracking source without a login."})
    for i in items:
        i["flag"] = bool(i.get("flag"))
        if "retry" in i:
            i["retry"] = bool(i["retry"])
    return {**base, "status": "checked", "at": dt.isoformat().replace("+00:00", "Z"), "atDenver": denver(dt), "approximate": bool(approx), "timeBasis": basis,
            "locationApproximate": coarse, "items": items, "retry": any(i.get("retry") for i in items),
            "note": "Possible explanations to compare with the account, not verdicts." + (" Time is approximate, so wider windows were used." if approx else "")}


def needs_check(r, now):
    sc = r.get("skyCheck")
    if not sc or sc.get("version") != SKY_VERSION:
        return True
    if sc.get("retry"):
        try:
            return now - datetime.fromisoformat(sc["at"].replace("Z", "+00:00")) < timedelta(days=TLE_TRUST_DAYS)
        except Exception:
            return False
    return False
