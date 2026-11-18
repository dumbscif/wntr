"""Offline place-name geocoding with an optional, rate-limited Nominatim fallback.

Never invents coordinates: if nothing in the text matches a known place, returns None
and the report goes to the "no location" list.
"""
import json, math, os, re, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# Single words that are also city names but usually mean something else in headlines.
COMMON = set("""
of the a an and or but police mobile reading march may june july august nice sale bath wells university
date most long early late best mission orange victoria marion florence lincoln jackson washington clinton
franklin hamilton alien aliens ufo uap ovni drone drones light lights sky star stars mars venus
moon sun earth space news video photo photos watch live update new old north south east west central
big little green red blue white black gold golden silver crystal hope liberty independence union unity
concord harmony paradise eden bethlehem goshen sharon salem? deal hurt rich worth chance surprise plenty
mexico? colombia? santa san la el los las le les de del di da do dos das des du van von der den het
tv cnn bbc abc cbs nbc fox reuters ap afp uk us usa eu un nato nasa faa raf usaf mod aaro pentagon
sunday monday tuesday wednesday thursday friday saturday january february april september october november december
enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre
lunes martes miércoles jueves viernes sábado domingo
reddit youtube tiktok instagram facebook twitter x google bing yahoo
trump biden obama musk schumer luna burchett
nov dec oct sep sept aug jan feb mar apr jun jul ham ground stop laguna much more less many man men woman women boy girl home house city town village state county province
jersey
real america américa sol luz paz flor cielo estrella alba aurora mundo world
truth verdad alerta alert breaking misterio
eastern western northern southern
norte oeste
luna solis
""".replace("?", "").split())

PREPS = r"(?:in|over|near|above|at|from|outside|across|around|en|sobre|cerca de|em|no|na|nos|nas|perto de|à|au|aux|près de|au-dessus de|bei|über|nahe|in der nähe von|im|am|nad|w|we|koło|pod|над|в|во|під|у|di|a|sopra|vicino a|boven|bij|te|op|i|på|över|ved|yakınında|'da|'de)"
# Directional adjectives that may sit between a preposition and a region ("over Eastern Pennsylvania").
DIR_ADJ = r"(?:eastern|western|northern|southern|north|south|east|west|central|northeastern|northwestern|southeastern|southwestern)"
# 'i' / 'a' / 'en' etc. must be whole words; otherwise "OVNI Real" looks like a preposition + place.
PREP_BEFORE = re.compile(r"(?<![\w])" + PREPS + r"\s+(?:the\s+)?(?:(?:state|province|county|city|town|region) of\s+)?(?:" + DIR_ADJ + r"\s+)?$", re.I)

CA_PROV = {"AB": "01", "BC": "02", "MB": "03", "NB": "04", "NL": "05", "NS": "07", "ON": "08", "PE": "09",
           "QC": "10", "SK": "11", "YT": "12", "NT": "13", "NU": "14"}

COUNTRY_ALIASES = {
    "US": ["united states", "usa", "u.s.", "estados unidos", "eua", "états-unis", "vereinigte staaten", "stati uniti", "美国", "美國", "アメリカ", "미국", "сша"],
    "GB": ["uk", "united kingdom", "britain", "england", "scotland", "wales", "reino unido", "royaume-uni", "inglaterra"],
    "MX": ["méxico", "mexico"], "BR": ["brasil", "brazil"], "ES": ["españa", "spain", "espanha"],
    "DE": ["deutschland", "germany", "alemania", "alemanha"], "IT": ["italia", "italy"],
    "NL": ["nederland", "netherlands", "holland", "países bajos"], "JP": ["japan", "日本", "japón", "japão"],
    "KR": ["south korea", "korea", "한국", "韓国", "corea del sur"], "TW": ["taiwan", "台灣", "臺灣"],
    "CN": ["china", "中国", "中國"], "RU": ["russia", "россия", "rusia", "rússia"], "UA": ["ukraine", "україна", "украина", "ucrania", "ucrânia"],
    "AR": ["argentina"], "CL": ["chile"], "UY": ["uruguay", "uruguai"], "PE": ["perú", "peru"], "CO": ["colombia", "colômbia"],
    "FR": ["france", "francia", "frança"], "PL": ["polska", "poland", "polonia"], "TR": ["türkiye", "turkey", "turquía"],
    "PH": ["philippines", "pilipinas", "filipinas"], "IN": ["india", "भारत"], "AU": ["australia", "austrália"],
    "CA": ["canada", "canadá"], "ZA": ["south africa", "sudáfrica"], "PT": ["portugal"], "IE": ["ireland", "irlanda"],
    "NZ": ["new zealand"], "SE": ["sweden", "sverige"], "NO": ["norway", "norge"], "DK": ["denmark", "danmark"],
    "FI": ["finland", "suomi"], "CZ": ["czech", "česko"], "RO": ["romania", "românia"], "GR": ["greece", "ελλάδα"],
    "HU": ["hungary", "magyarország"], "ID": ["indonesia"], "VN": ["vietnam", "việt nam"], "TH": ["thailand", "ประเทศไทย"],
    "IL": ["israel", "ישראל"], "EG": ["egypt", "مصر"], "SA": ["saudi arabia", "السعودية"], "AE": ["uae", "emirates", "الإمارات"],
}

def haversine(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))

def _is_non_latin(s):
    return any(ord(c) > 0x24F for c in s)

class Gazetteer:
    def __init__(self, cache_path=None, nominatim_cap=20, user_agent="WNTR-UFO-Archive"):
        self.by_name = {}
        self.nonlatin = []  # (name, entry)
        self.cyr = []
        self.countries = {}
        self.country_names = {}
        self.admin1 = {}  # (cc, code) -> [names]
        self.cache_path = cache_path
        self.cache = {}
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                self.cache = json.load(f)
        self.nominatim_left = nominatim_cap
        self.ua = user_agent
        self._last_nom = 0.0
        self._load()

    def _load(self):
        with open(os.path.join(HERE, "countries.tsv"), encoding="utf-8") as f:
            for line in f:
                iso, name, cont = line.rstrip("\n").split("\t")
                self.countries[iso] = {"name": name, "continent": cont}
                self.country_names.setdefault(name.lower(), iso)
        for iso, names in COUNTRY_ALIASES.items():
            for n in names:
                self.country_names.setdefault(n.lower(), iso)
        with open(os.path.join(HERE, "admin1.tsv"), encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) < 3:
                    continue
                cc, code = p[0].split(".", 1)
                names = {p[1].lower(), p[2].lower()}
                if cc == "US":
                    names.add(code.lower())
                self.admin1[(cc, code)] = names
        for ab, code in CA_PROV.items():
            self.admin1.setdefault(("CA", code), set()).add(ab.lower())
        acc = {}
        with open(os.path.join(HERE, "gazetteer.tsv"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                gid, name, ascii_, alts, lat, lon, cc, a1, pop, tz = line.rstrip("\n").split("\t")
                e = {"gid": gid, "name": name, "lat": float(lat), "lon": float(lon), "cc": cc,
                     "a1": a1, "pop": int(pop), "tz": tz}
                k = (cc, a1)
                a = acc.setdefault(k, [0, 0.0, 0.0, tz, 0])
                w = max(int(pop), 1)
                a[0] += w; a[1] += float(lat) * w; a[2] += float(lon) * w
                if w > a[4]:
                    a[3], a[4] = tz, w
                for n in {name, ascii_}:
                    self.by_name.setdefault(n.lower(), []).append(e)
                for a in filter(None, alts.split("|")):
                    if _is_non_latin(a):
                        if re.search(r"[\u0400-\u04FF]", a):
                            if len(a) >= 4:
                                self.cyr.append((a, e))
                        elif len(a) >= 2:
                            self.nonlatin.append((a, e))
                    else:
                        self.by_name.setdefault(a.lower(), []).append(e)
        self.nonlatin.sort(key=lambda x: -len(x[0]))
        self.admin1_names = {n for names in self.admin1.values() for n in names if len(n) >= 4}
        self.a1_centroid = {}
        for k, v in acc.items():
            w = v[0] or 1
            self.a1_centroid[k] = (round(v[1] / w, 3), round(v[2] / w, 3), v[3])

    def save_cache(self):
        if self.cache_path:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=0, sort_keys=True)

    def countries_in(self, text):
        low = " " + text.lower() + " "
        found = set()
        for n, iso in self.country_names.items():
            if len(n) <= 3:
                if re.search(r"(?<![\w.])" + re.escape(n) + r"(?![\w])", low):
                    found.add(iso)
            elif n in low:
                found.add(iso)
        return found

    def _admin_near(self, e, after):
        names = self.admin1.get((e["cc"], e["a1"]), set())
        m = re.match(r"\s*,?\s*([A-Za-zÀ-ÿ .'-]{2,40})", after)
        if not m:
            return False
        nxt = m.group(1).strip().lower()
        for n in names:
            if nxt.startswith(n) and (len(nxt) == len(n) or not nxt[len(n)].isalpha()):
                return True
        cname = self.countries.get(e["cc"], {}).get("name", "").lower()
        return bool(cname) and nxt.startswith(cname)

    def _entry(self, e, how, matched, signals=None):
        a1names = sorted(self.admin1.get((e["cc"], e["a1"]), []), key=len, reverse=True)
        country = self.countries.get(e["cc"], {})
        label = e["name"] + (", " + a1names[0].title() if a1names and len(a1names[0]) > 2 else "") + ", " + country.get("name", e["cc"])
        out = {"place": label, "lat": e["lat"], "lon": e["lon"], "cc": e["cc"], "country": country.get("name", e["cc"]),
                "continent": country.get("continent"), "tz": e["tz"], "gid": e["gid"],
                "precision": f"city/town-level approximation from {how} match on '{matched}'; not an object position"}
        if signals:
            out["context_signals"] = signals
        return out

    def locate(self, text, region_cc=None):
        """Return best place dict or None. text = title + summary."""
        if not text:
            return None
        mentioned = self.countries_in(text)
        best, best_score = None, 0.0
        # Latin-script capitalized phrases
        for m in re.finditer(r"(?<![\w'])([A-ZÀ-Þ][\w'’.-]*(?:\s+(?:de|del|la|do|da|dos|das|of|upon|on|am|an|sur|le|di|y)?\s*[A-ZÀ-Þ][\w'’.-]*){0,3})", text):
            phrase = m.group(1).strip(" .'’-")
            words = phrase.split()
            for i in range(len(words)):
                for j in range(len(words), i, -1):
                    cand = " ".join(words[i:j]).strip(" .'’-")
                    key = cand.lower()
                    if len(key) < 3 or key not in self.by_name:
                        continue
                    single = (j - i == 1)
                    start = m.start(1) + phrase.find(cand) if phrase.find(cand) >= 0 else m.start(1)
                    before = text[max(0, start - 22):start].lower()
                    after = text[start + len(cand):start + len(cand) + 45]
                    prep = bool(PREP_BEFORE.search(before))
                    if key in self.country_names:
                        continue
                    # "Colorado", "Oregon", "Paraná", "Chiapas"... : treat as the state/province, not a same-named town
                    if single and key in self.admin1_names and not re.match(r"\s*,", after):
                        continue
                    ents = self.by_name[key]
                    maxpop = max(x["pop"] for x in ents)
                    adm = [x for x in ents if self._admin_near(x, after)]
                    if adm:
                        pick, admin = max(adm, key=lambda x: x["pop"]), True
                    else:
                        admin = False
                        if single and key in COMMON:
                            continue
                        men = [x for x in ents if x["cc"] in mentioned]
                        reg = [x for x in ents if region_cc and x["cc"] == region_cc]
                        if men:
                            pick = max(men, key=lambda x: x["pop"])
                        elif reg and max(reg, key=lambda x: x["pop"])["pop"] * 3 >= maxpop:
                            pick = max(reg, key=lambda x: x["pop"])
                        else:
                            pick = max(ents, key=lambda x: x["pop"])
                            # a same-named bigger place abroad with no supporting context: too ambiguous
                            if len({x["cc"] for x in ents}) > 1 and region_cc and pick["cc"] != region_cc and pick["pop"] < 1000000 and not prep:
                                continue
                    e = pick
                    score = math.log10(max(e["pop"], 1000))
                    if admin:
                        score += 8
                    if prep:
                        score += 4
                    if e["cc"] in mentioned:
                        score += 3
                    if region_cc and e["cc"] == region_cc:
                        score += 1.5
                    if not single:
                        score += 2
                    ok = admin or (prep and (e["pop"] >= 5000)) or (not single and e["pop"] >= 50000) \
                        or (e["pop"] >= 1000000 and (e["cc"] in mentioned or region_cc == e["cc"] or prep)) \
                        or (e["cc"] in mentioned and e["pop"] >= 100000)
                    if ok and score > best_score:
                        best, best_score = (e, "gazetteer", cand, {"prep": prep, "admin": admin, "country_mentioned": e["cc"] in mentioned}), score
        if _is_non_latin(text):
            for name, e in self.nonlatin:
                if name in text:
                    score = math.log10(max(e["pop"], 1000)) + len(name) * 0.8 + (3 if e["cc"] in mentioned else 0) + (1.5 if region_cc == e["cc"] else 0)
                    if len(name) == 2 and e["pop"] < 500000 and e["cc"] not in mentioned and region_cc != e["cc"]:
                        continue
                    if score > best_score:
                        best, best_score = (e, "gazetteer (native script)", name), score
            for name, e in self.cyr:
                if re.search(r"(?<![\u0400-\u04FF])" + re.escape(name[:-1]) + r"[\u0400-\u04FF]{0,3}(?![\u0400-\u04FF])", text):
                    score = math.log10(max(e["pop"], 1000)) + 3 + (3 if e["cc"] in mentioned else 0)
                    if score > best_score:
                        best, best_score = (e, "gazetteer (Cyrillic)", name), score
        if best:
            return self._entry(*best)
        a = self._admin1_match(text, mentioned, region_cc)
        if a:
            return a
        return self._nominatim(text)

    def _admin1_match(self, text, mentioned, region_cc):
        low = text.lower()
        best = None
        for (cc, code), names in self.admin1.items():
            if (cc, code) not in self.a1_centroid:
                continue
            for n in names:
                if len(n) < 4 or n in COMMON or n in self.country_names:
                    continue
                m = re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", low)
                if not m:
                    continue
                before = low[max(0, m.start() - 22):m.start()]
                prep = bool(PREP_BEFORE.search(before))
                if not (prep or cc in mentioned or (region_cc == cc and len(n) >= 6)):
                    continue
                if region_cc and cc != region_cc and cc not in mentioned:
                    continue
                score = len(n) + (5 if prep else 0) + (3 if cc in mentioned else 0)
                if not best or score > best[0]:
                    best = (score, cc, code, n, prep)
        for m in re.finditer(r",\s*([A-Z]{2})\b(?![a-z])", text):
            k = ("US", m.group(1))
            if k in self.a1_centroid and (not best or best[0] < 30):
                best = (30, "US", m.group(1), sorted(self.admin1[k], key=len)[-1], True)
        if not best:
            return None
        _, cc, code, n, had_prep = best
        lat, lon, tz = self.a1_centroid[(cc, code)]
        country = self.countries.get(cc, {})
        return {"place": n.title() + ", " + country.get("name", cc), "lat": lat, "lon": lon, "cc": cc, "country": country.get("name", cc),
                "continent": country.get("continent"), "tz": tz, "gid": f"a1:{cc}.{code}",
                "precision": f"state/province-level only (population-weighted centre of GeoNames towns in '{n.title()}'); NOT a sighting position",
                "context_signals": {"prep": bool(had_prep), "admin": True, "country_mentioned": cc in mentioned or bool(region_cc == cc)}}

    def _nominatim(self, text):
        m = re.search(r"\b(?:over|near|above|in)\s+((?:[A-Z][a-zà-ÿ'’-]+\s?){1,3})(?:,\s*([A-Z][A-Za-z .]{1,25}))?", text)
        if not m:
            return None
        q = m.group(1).strip() + (", " + m.group(2).strip() if m.group(2) else "")
        if q.lower() in COMMON or len(q) < 4:
            return None
        key = "nom:" + q.lower()
        if key in self.cache:
            return self.cache[key]
        if self.nominatim_left <= 0 or os.environ.get("WNTR_NO_NOMINATIM"):
            return None
        self.nominatim_left -= 1
        wait = 1.1 - (time.time() - self._last_nom)
        if wait > 0:
            time.sleep(wait)
        self._last_nom = time.time()
        res = None
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search",
                             params={"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1},
                             headers={"User-Agent": self.ua}, timeout=20)
            if r.ok and r.json():
                h = r.json()[0]
                if h.get("category") in ("place", "boundary") and h.get("addresstype") in (
                        "city", "town", "village", "municipality", "suburb", "hamlet", "county", "state_district"):
                    cc = (h.get("address", {}).get("country_code") or "").upper()
                    c = self.countries.get(cc, {})
                    res = {"place": h.get("display_name", q)[:120], "lat": round(float(h["lat"]), 4),
                           "lon": round(float(h["lon"]), 4), "cc": cc, "country": c.get("name", cc),
                           "continent": c.get("continent"), "tz": None, "gid": None,
                           "precision": f"approximate; OpenStreetMap Nominatim lookup of '{q}'; not an object position"}
        except Exception:
            return None
        self.cache[key] = res
        return res
