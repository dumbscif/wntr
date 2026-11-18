"""Honest rule-based relevance and marker classification (no AI)."""
import re

UFO = [r"\bufos?\b", r"\buaps?\b", r"\bovnis?\b", r"\bóvnis?\b", r"\bufó\b", r"\bнло\b", r"不明飛行物", r"未確認飛行物体",
       r"미확인\s?비행", r"\bunidentified (?:flying|aerial|anomalous)", r"\borbs?\b", r"\b(?:strange|mysterious|unexplained|unknown|eerie|bright) (?:lights?|objects?|craft)\b",
       r"\bmystery drones?\b", r"\bunidentified drones?\b", r"\bdrone sightings?\b", r"luces? (?:extrañas|misteriosas)", r"objeto (?:volador )?no identificado",
       r"luzes? (?:estranhas|misteriosas)", r"objeto (?:voador )?não identificado", r"lumières? (?:étranges|mystérieuses)", r"objet volant non identifié",
       r"seltsame lichter", r"mysteriöse lichter", r"unbekannte(?:s|n)? flugobjekt", r"luci (?:strane|misteriose)", r"oggetto volante non identificato",
       r"vreemde lichten", r"onbekend (?:vliegend )?object", r"tajemnicze światła", r"niezidentyfikowany obiekt", r"garip ışık", r"tanımlanamayan",
       r"неопознанн", r"загадочн\w* (?:огн|свет)", r"невідом\w* об", r"\bufo\b", r"ユーフォー", r"\bufo目撃", r"飞碟", r"飛碟", r"비행물체",
       r"tic.?tac", r"\btriangle craft\b", r"\bblack triangle\b", r"fenómeno aéreo", r"fenômeno aéreo", r"\bfanu\b"]
SIGHT = [r"spotted", r"sighting", r"sighted", r"seen (?:over|above|in|near|hovering)", r"\bfilmed\b", r"captured on (?:camera|video)", r"caught on (?:camera|video)",
         r"witness", r"reported seeing", r"lights? (?:over|above)", r"appeared (?:over|above|in the sky)", r"in the (?:night )?sky", r"hovering", r"recorded",
         r"avist", r"captan", r"captaron", r"grab(?:an|aron|ó)", r"aparec", r"en el cielo", r"flagr", r"filmad", r"no céu", r"aperçu", r"observ", r"dans le ciel",
         r"filmé", r"gesichtet", r"sichtung", r"am himmel", r"gefilmt", r"avvist", r"in cielo", r"nel cielo", r"ripres", r"waarneming", r"waargenomen", r"gespot",
         r"boven ", r"目撃", r"撮影", r"上空", r"목격", r"포착", r"하늘", r"目擊", r"拍到", r"出現", r"заметил", r"видел", r"сняли", r"в небе", r"помітил", r"в небі", r"у небі",
         r"zauważ", r"nagra", r"na niebie", r"görüldü", r"gökyüzü", r"görüntülen", r"himlen", r"taivaalla", r"на небе", r"pozorov", r"pe cer", r"στον ουρανό", r"terlihat", r"di langit"]
CONTEXT = [r"hearing", r"congress", r"pentagon", r"\baaro\b", r"disclosure", r"senat", r"\bbill\b", r"legislation", r"documentary", r"whistleblower", r"report(?:ed)? to congress",
           r"national security", r"declassif", r"nasa", r"audiencia", r"congreso", r"audiência", r"congresso", r"divulgação", r"desclasific", r"ministry of defen",
           r"\bnorad\b", r"faa\b", r"lawmakers", r"intelligence"]
EXCLUDE = [r"video ?game", r"\btrailer\b", r"box office", r"\balbum\b", r"\bconcert\b", r"rapper", r"\bcrypto", r"\bnft\b", r"\btoy\b", r"festival", r"premiere",
           r"ufo ?50", r"ufo361", r"ufo catcher", r"\brecipe\b", r"\bbaseball\b", r"\bsoccer\b", r"\bfootball\b", r"funko", r"\bmovie\b", r"\bfilm review\b",
           r"\bhoroscope\b", r"lottery", r"\bsale\b", r"discount", r"\bufo (?:cookie|burger|pizza)", r"\bufo kick", r"\bufo tank\b", r"ufo club", r"ufo 37",
           r"fortnite", r"\bnetflix\b", r"\bsci-?fi\b", r"\bserie\b", r"\bseries\b", r"\bpodcast\b"]
CONFIRM_ACTOR = r"(military|air force|army|navy|marines|police|officials?|authorit|government|pentagon|norad|ministry|defen[cs]e|coast guard|faa|space force|sheriff|" \
                r"fuerza aérea|fuerzas armadas|ejército|armada|policía|gobierno|força aérea|exército|polícia|governo|armée|gendarmerie|bundeswehr|polizei|aeronautica|" \
                r"carabinieri|polizia|politie|defensie|自衛隊|軍|경찰|군|警方|軍方|минобороны|полиция|военн|policja|wojsko|ordu|jandarma|nasa|space agency|cnes|aaro|ahac)"
CONFIRM_VERB = r"(confirm|identified|said (?:it|the object|the lights) (?:was|were)|explained|attributed|determined|verified|confirmó|identificó|confirmou|identificou|confirme|identifié|" \
               r"bestätigt|identifiziert|confermat|identificat|bevestig|geïdentificeerd|確認|확인|证实|證實|подтверд|potwierdz|doğruladı)"
TEST = r"(secret (?:aircraft|craft|test|program)|military test|weapons? test|test flight|testing (?:of )?(?:a |an )?(?:new |secret |classified |experimental )?(?:aircraft|drone|craft|weapon)|" \
       r"classified (?:aircraft|craft|drone|program)|experimental (?:aircraft|craft|drone)|prueba militar|pruebas militares|teste militar|testes militares|essai militaire|" \
       r"militärische(?:r|n)? test|test militare|militaire test|軍事実験|군사 시험|試射)"
STRIP_TAGS = re.compile(r"<[^>]+>")

def _any(pats, text):
    return any(re.search(p, text) for p in pats)

def classify(title, summary):
    """Return (kind, marker, basis) or None to drop. kind: sighting|context."""
    text = (title + " " + summary).lower()
    if _any(EXCLUDE, text):
        return None
    if not _any(UFO, text):
        return None
    sight = _any(SIGHT, text)
    context = _any(CONTEXT, text)
    if not sight:
        if context:
            return ("context", "cyan", "OSINT/context: UFO/UAP news without a described local sighting (keyword rule)")
        return None
    # yellow only when one sentence names an official actor AND a confirm/identify verb
    for sent in re.split(r"(?<=[.!?。！？])\s+|\n", text):
        if re.search(CONFIRM_ACTOR, sent) and re.search(CONFIRM_VERB, sent):
            return ("sighting", "yellow", "Source text states officials/military/police confirmed or identified something (keyword rule; read the source)")
    if re.search(TEST, text):
        return ("sighting", "blue", "Source text mentions alleged testing of secret/experimental craft (keyword rule; allegation only)")
    return ("sighting", "red", "Civilian/unknown sighting claim (default rule); not verified")

def clean(s):
    import html
    s = STRIP_TAGS.sub(" ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# =====================================================================================
# Grok-Page-equivalent screening (v2). Deterministic rules, no AI.
# The Grok Page logs only NEWLY reported, CONCRETE sightings: a described observation
# (what was seen) tied to a place, from a witness, witness-report database, or local
# media relaying a resident's report/footage. News stories about UFOs in general,
# politics/disclosure, documentaries/TV, explainers, opinion, listicles and historical
# rehashes are not sightings. Military/launch/airspace items are context only.
# =====================================================================================
SCREEN_VERSION = 2

# Witness-report databases and first-hand reporting sites (tier 1 for sightings).
WITNESS_SITES = ("ufomeldpunt.nl", "mufoncms.com", "mufon.com", "nuforc.org", "probed.space", "aliens.co.il", "ufo-hunters.com",
                 "ufosighting.report", "ufokarte.de", "ufobc.ca", "ufowatch.com", "enigmalabs.io", "ovni-expert.com", "unexplained.ie",
                 "ufoindex.com", "toshitan-ufo.com", "reddit.com")
# Entertainment / explainer / aggregator publishers: never enough on their own.
LOW_TRUST = ("history on msn", "history.com", "britannica", "unilad", "ladbible", "starlust", "science & vie", "inkl", "screenrant", "cbr.com",
             "gamerant", "collider", "ign", "cinemablend", "corrierenerd", "l'urlo", "urlo", "supereva", "xataka", "yeni akit", "ancient aliens",
             "giant freakin robot", "the debrief", "liberation times", "open minds", "nacionale", "mysterious universe", "ufosightingsdaily")
OFFICIAL_SITES = (".mil", ".gov", "aaro.mil", "faa.gov", "police.", "defence.gov", "defensa.")

# Stories ABOUT UFOs that are not a sighting report (rejected unless a concrete new sighting is also described).
STORY = [r"\bdocumentar", r"\bdocuseries\b", r"\bseason \d", r"\bepisode\b", r"\btv show\b", r"\bstreaming\b", r"\bnetflix\b", r"ancient aliens",
         r"\bpodcast\b", r"\binterview\b", r"\bbook\b", r"\bnovel\b", r"\bopinion\b", r"\bop-ed\b", r"\bcolumn\b", r"\bmy thoughts\b", r"\btheory\b", r"\btheories\b",
         r"conspira", r"\bteor[ií]a", r"\btop \d+\b", r"\b\d+ (?:best|most|strangest|famous|weirdest)\b", r"list in full", r"\bexplained\b", r"\bexplainer\b",
         r"\bwhat (?:is|are|did|was)\b(?! (?:this|that|it)\b)", r"\bwhy (?:is|are|do|does|did)\b", r"\bhow (?:do|does|did|to)\b", r"\banniversar", r"\byears ago\b", r"\bdecades?\b",
         r"\bhistoric(?:al)?\b", r"\bhistory of\b", r"\blegend\b", r"\bleyenda\b", r"\blenda\b", r"\bmyth\b", r"\bfolklore\b", r"\bepicentr", r"\bhotspot\b",
         r"declassif", r"desclasific", r"desclassific", r"\bfiles?\b", r"\barchiv(?:o|os|es)\b", r"\bdocuments?\b", r"\bdisclosure\b", r"\bdivulga",
         r"\bcongress", r"\bcongreso\b", r"\bsenat", r"\bhearing\b", r"\baudiencia\b", r"\bbill\b", r"\blegislation\b", r"\blawmakers?\b", r"\bwhistleblower",
         r"\bformer (?:defense|pentagon|navy|intelligence|aaro)\b", r"\bofficial claims\b", r"\bclaims ufos are real\b", r"\baliens? (?:are|exist)\b",
         r"\bextraterrestri", r"\bseti\b", r"\bastronaut", r"\bloeb\b", r"\bkirkpatrick\b", r"\belizondo\b", r"\bgrusch\b", r"\bmaussan\b", r"\btrump\b",
         r"\bpresident\b", r"\bmiller\b", r"\bharmonica\b", r"\bjingle bells\b", r"\bholy site\b", r"\binspires\b", r"\bcomic\b", r"\bmuseum\b",
         r"\bexhibit", r"\bconference\b", r"\bconvention\b", r"\bfestival\b", r"\bcourse\b", r"\bstudy\b", r"\bscientists? (?:say|warn)\b",
         r"\breport(?:s)? to congress\b", r"\bannual report\b", r"\bbudget\b", r"\bufo chief\b", r"\bufo investigator\b", r"\brevisiting\b", r"\brecap\b",
         r"\bcompilation\b", r"\bstrangest\b", r"\bweirdest\b", r"\bburchett\b", r"\bon fox news\b", r"\bnewsnation\b", r"\bcongress(?:man|woman)\b", r"\bweeks ago\b", r"\bpredict", r"\bentities\b", r"\bmy (?:strange )?research\b", r"\bchannel(?:ing|led)\b", r"\bitc\b", r"\bcharla\b", r"\bconferencia\b", r"\blecture\b", r"\bwebinar\b", r"\bshostak\b", r"\bexpects\b", r"\bprofec", r"\bprophec", r"\bbaba vanga\b", r"\bsistema di\b", r"\broundup\b", r"\bweekly\b", r"\bmonthly\b"]
# First-hand / concrete-sighting language.
FIRSTHAND = [r"\bi (?:saw|seen|see|filmed|recorded|caught|captured|spotted|noticed|witnessed|watched|took)\b", r"\bwe (?:saw|seen|filmed|recorded|spotted|noticed|witnessed|watched)\b",
             r"\bmy (?:husband|wife|son|daughter|mom|mother|dad|father|friend|boyfriend|girlfriend|neighbou?r|family|kids?)\b", r"\b(?:last|to)night\b", r"\bthis (?:morning|evening)\b",
             r"\bwhat (?:did i|is this|was this|was that|is that)\b", r"\bresidents?\b", r"\bvecinos?\b", r"\bmoradores?\b", r"\bhabitantes\b", r"\bwitness(?:es|ed)?\b",
             r"\btestigos?\b", r"\btestemunhas?\b", r"\bdrivers?\b", r"\bmotoristas?\b", r"\bpilots?\b", r"\bpilotos?\b", r"\bpassengers?\b",
             r"\b(?:seen|spotted|sighted|observed|filmed|recorded|photographed) (?:over|above|in|near|from|at|on)\b", r"\bcaptured on (?:camera|video|film)\b",
             r"\bcaught on (?:camera|video)\b", r"\bcaptan\b", r"\bcaptaron\b", r"\bcaptado\b", r"\bgraban\b", r"\bgrabaron\b", r"\bgrabado\b", r"\bfilmad[oa]\b",
             r"\bflagrad[oa]\b", r"\bregistran\b", r"\bregistrad[oa]\b", r"\breportan\b", r"\bavistan\b", r"\bavistad[oa]\b", r"\bavvistat[oa]\b", r"\bgesichtet\b",
             r"\bgefilmt\b", r"\bwaargenomen\b", r"\bgespot\b", r"\bzauważ", r"\bnagra", r"\bзаметил", r"\bсняли\b", r"目撃", r"撮影", r"목격", r"포착", r"目擊", r"拍到",
             r"\bsighting report\b", r"\bmelding\b", r"\bwaarneming\b", r"\bsichtung\b", r"\bfirst-hand\b"]
# Description of the observed thing (shape, light, motion).
OBSERVATION = [r"\borbs?\b", r"\bspheres?\b", r"\bsphère", r"\besferas?\b", r"\btriang", r"\bdisc\b", r"\bdisk\b", r"\bsaucer", r"\bcigar", r"\bsigaro\b", r"tic.?tac",
               r"\bchevron", r"\bdiamond", r"\bcylind", r"\bboomerang", r"\bfireball", r"\bbola de fuego", r"\blights?\b", r"\bluz\b", r"\bluces\b", r"\bluzes?\b",
               r"\blumi[eè]re", r"\bluci\b", r"\blichter?\b", r"\blichten\b", r"\bświatł", r"\bогн", r"\bсвет", r"\bglow", r"\bbright\b", r"\bluminos", r"\bblink",
               r"\bflash", r"\bpuls", r"\bhover", r"\bsuspend", r"\bstationary\b", r"\bmotionless\b", r"\bsilent\b", r"\bzigzag", r"\berratic", r"\bdart",
               r"\bshot off\b", r"\bvanish", r"\bdisappear", r"\bdesapareci", r"\bshape", r"\bformation\b", r"\bin formation\b", r"\bobjects?\b", r"\bobjeto\b",
               r"\bobjet\b", r"\boggetto\b", r"\bobjekt\b", r"\bcraft\b", r"\bdrones?\b", r"\bstreak", r"\bestela\b", r"\btrail\b", r"\bbeam\b", r"\bplasma\b",
               r"\bfl(?:y|ying|ew) (?:over|above|across|past)\b", r"\bmoving\b", r"\bmoved\b", r"\bcrossing\b", r"\bufo\b", r"\bovni\b", r"\buap\b",
               r"\borange\b", r"\bred\b", r"\bwhite\b", r"\bgreen\b", r"\bnaranja\b", r"\brojo\b", r"\bblanc", r"\bin the (?:night )?sky\b", r"\ben el cielo\b",
               r"\bno céu\b", r"\bdans le ciel\b", r"\bam himmel\b", r"\bnel cielo\b", r"\bin cielo\b", r"\bna niebie\b", r"\bв небе\b", r"上空", r"하늘"]
CONCRETE_TIME = [r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm|a\.m\.|p\.m\.|h)?\b", r"\b(?:last|to)night\b", r"\byesterday\b", r"\bthis (?:morning|evening|week)\b", r"\bayer\b",
                 r"\banoche\b", r"\bontem\b", r"\bhier\b", r"\bgestern\b", r"\bieri\b", r"\bgisteren\b", r"\bwczoraj\b", r"\bвчера\b", r"\bviernes 13\b",
                 r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}\b", r"\b\d{1,2} (?:de )?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ene|abr|ago|dic|noviembre|octubre|novembro|outubro)",
                 r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b", r"\b(?:lunes|martes|miércoles|jueves|viernes|sábado|domingo)\b", r"\b20\d\d-\d\d-\d\d\b", r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"]
# Report nouns used by news relays of a local sighting.
SIGHT_NOUN = [r"\bsightings?\b", r"\bavistamientos?\b", r"\bavistamentos?\b", r"\bavvistament", r"\bobservation\b", r"\bsichtung", r"\bwaarneming",
              r"\bobserva(?:do|da|ción|ção)\b", r"\brevelan v[ií]deo\b", r"\bv[ií]deo (?:capta|muestra|shows)\b", r"\bviral video\b", r"\bcaptured\b", r"\bspotted\b",
              r"\bfilmed\b", r"\bappeared (?:over|above|in)\b", r"\baparec(?:e|en|ió|ieron)\b", r"\bapareceu\b", r"\bavistan\b", r"\breportan\b"]
# Second-hand hearsay rather than a sighting.
HEARSAY = [r"\bthere is talk\b", r"\btalk of\b", r"\brumou?rs?\b", r"\bsupposedly\b", r"\bsomeone told me\b", r"\bneighbou?r (?:is|says|told)\b", r"\bi heard (?:that|there)\b"]
# Questions / chatter that are not reports.
CHATTER = [r"^are you guys", r"^does anyone", r"^anyone else", r"^is it just me", r"^why is every", r"^thoughts on", r"^my thoughts", r"^opinion",
           r"^revisiting", r"^discussion", r"^meta\b", r"^\[?meta\]?", r"\bhot take\b", r"^which country", r"^how do you", r"^what did the", r"^who'?s handling",
           r"^when ringing", r"^\d+ years ago"]
# Context-only (OSINT) topics: map as cyan rings only with a real place, never as a sighting.
OSINT = [r"\bairspace\b", r"\bespacio aéreo\b", r"\bground stop\b", r"\bgrounded\b", r"\bflights? (?:halted|suspended|grounded)\b", r"\bsuspensión de vuelos\b",
         r"\bcierre aéreo\b", r"\bairport (?:closed|closure|disruption)\b", r"\bdrone incursion", r"\bair alert", r"\bscrambl", r"\bintercept", r"\bmilitary exercise",
         r"\bwar ?games?\b", r"\bflares?\b", r"\brocket launch", r"\blaunch(?:ed)? (?:from|of)\b", r"\bstarship\b", r"\bfalcon 9\b", r"\bsoyuz\b", r"\bre-?entry\b",
         r"\breentr", r"\bstarlink\b", r"\bsatellite train\b", r"\bpursue release\b", r"\baaro (?:release|case|report)"]
EXPLAINED = [r"\bno eran ovnis\b", r"\bnot (?:a |an )?(?:ufo|alien)s?\b", r"\bera el cohete\b", r"\bwas (?:a |the )?(?:rocket|starlink|satellite|balloon|drone|kite|planet|meteor)\b",
             r"\b(?:fue|era|eran) (?:el |la |los |un |una )?(?:cohete|starlink|satélite|globo|meteoro|dron)", r"\bidentified as\b", r"\bresult of\b",
             r"\baclara\b", r"\bexplican?\b", r"\bexplanation\b"]

def _hits(pats, text):
    return [p for p in pats if re.search(p, text)]

def source_tier(publisher, url, family):
    p, u = (publisher or "").lower(), (url or "").lower()
    if any(s in u for s in OFFICIAL_SITES):
        return 0, "official/government site"
    if family in ("UFO Meldpunt Nederland", "MUFON", "Probed", "Aliens.co.il", "UFO Hunters") or any(s in u for s in WITNESS_SITES):
        return 1, "witness-report database or first-hand post"
    if any(s in p or s in u for s in LOW_TRUST):
        return 3, "aggregator/entertainment/explainer publisher"
    return 2, "news outlet"

def assess(title, summary, *, publisher="", url="", family="", place=None, now_year=2026, structured=None):
    """Screen one item like the Grok Page sweeps do.
    Returns dict(decision='sighting'|'context'|'exclude', marker, basis, reasons[], score, tier, evidence)."""
    structured = structured or {}
    t = (title or "").strip()
    text = (t + " . " + (summary or "")).lower()
    tl = t.lower()
    reasons = []
    tier, tier_basis = source_tier(publisher, url, family)
    if _any(EXCLUDE, text):
        return {"decision": "exclude", "reasons": ["entertainment/product/off-topic keyword"], "score": -99, "tier": tier}
    ufo = _any(UFO, text) or tier == 1 or structured.get("is_report")
    if not ufo:
        return {"decision": "exclude", "reasons": ["no UFO/UAP or unexplained-object wording"], "score": -99, "tier": tier}
    story = _hits(STORY, tl)
    story_body = _hits(STORY, text)
    first = _hits(FIRSTHAND, text)
    obs = _hits(OBSERVATION, text)
    when = _hits(CONCRETE_TIME, text)
    chatter = _hits(CHATTER, tl)
    osint = _hits(OSINT, text)
    osint_title = _hits(OSINT, tl)
    hearsay = _hits(HEARSAY, text)
    years = [int(y) for y in re.findall(r"\b(19[4-9]\d|20[0-4]\d)\b", t + " " + (summary or ""))]
    for m in re.finditer(r"\b\d{1,2}[/.-]\d{1,2}[/.-](\d{2})\b", t):   # 02/04/25 style dates in titles
        yy = 2000 + int(m.group(1))
        if 2000 <= yy <= now_year:
            years.append(yy)
    old_only = bool(years) and max(years) < now_year and now_year not in years
    score = 0
    score += {0: 3, 1: 4, 2: 1, 3: -3}[tier]
    noun = _hits(SIGHT_NOUN, text)
    if first: score += 3; reasons.append("first-hand/witness wording")
    elif noun: score += 2; reasons.append("sighting-report wording")
    if obs: score += min(3, len(obs)); reasons.append("describes what was seen")
    if when: score += 1; reasons.append("concrete sighting time/date")
    if place: score += 2 if (place.get("precision") or "").startswith(("city", "town", "exact", "neighbourhood", "point")) or place.get("gid") else 1; reasons.append("named place")
    if structured.get("witness_count"): score += 1
    if structured.get("media"): score += 1; reasons.append("photo/video attached")
    if story: score -= 4 * min(2, len(story)); reasons.append("story/news-about-UFOs wording in title: " + ", ".join(re.sub(r"\\b|\\", "", s) for s in story[:3]))
    elif story_body and tier >= 2: score -= 2; reasons.append("story wording in summary")
    if chatter: score -= 5; reasons.append("question/discussion post, not a report")
    if hearsay: score -= 4; reasons.append("second-hand hearsay, not a witness account")
    if old_only: score -= 6; reasons.append(f"mentions only older year(s) ({max(years)}): historical/resurfaced, not a new sighting")
    if tier == 3 and not first: score -= 2
    out = {"score": score, "tier": tier, "tierBasis": tier_basis}
    # ---- decision
    described = bool(obs or structured.get("shape"))
    concrete = described and bool(first or tier <= 1 or structured.get("is_report") or (tier == 2 and noun))
    if place is None:
        reasons.append("no geolocatable place in the source text")
    if osint_title and not first:
        concrete = False   # an airspace/launch/military headline is context, not a sighting
    if hearsay and not structured.get("is_report"):
        concrete = False
    if concrete and score >= 6 and not chatter and not old_only and not story and (place is not None or (score >= 9 and tier <= 1)):
        out["decision"] = "sighting"
        if place is None:
            reasons.append("kept unmapped: strong first-hand report but no place could be geolocated")
    elif osint and place is not None and not old_only and not chatter and tier in (0, 2) and len(story) < 2 \
            and family not in ("Mastodon", "Reddit"):
        out["decision"] = "context"
        reasons.append("military/launch/airspace/official context")
    else:
        out["decision"] = "exclude"
        if not concrete:
            reasons.append("no concrete first-hand sighting described")
        if score < 6:
            reasons.append(f"screening score {score} < 6")
    out["reasons"] = reasons
    if out["decision"] == "context":
        out.update(marker="cyan", basis="OSINT/context (rule): military, launch, airspace or official item near a place; context only, never proof of a sighting")
        return out
    if out["decision"] != "sighting":
        return out
    # ---- marker (same meaning as the Grok Page)
    marker, basis = "red", "Civilian/unknown sighting report (screening rule); not verified"
    for sent in re.split(r"(?<=[.!?。！？])\s+|\n", text):
        if re.search(CONFIRM_ACTOR, sent) and re.search(CONFIRM_VERB, sent) and \
                not re.search(r"\b(?:no|not|never|without|unconfirmed|unverified|hasn't|has not|have not|haven't|nobody|nor|ni|sin|não|nicht|non)\b", sent):
            marker, basis = "yellow", "Source text says officials/military/police confirmed or identified THIS sighting (keyword rule; read the source). Not confirmation of anything exotic."
            break
    if marker == "red" and re.search(TEST, text):
        marker, basis = "blue", "Source text alleges testing of secret/experimental craft (allegation only)"
    out.update(marker=marker, basis=basis)
    # ---- evidence status, worded like the Grok Page
    who = {0: "Official source", 1: "Single first-hand report on " + (publisher or "a witness-report site"), 2: "News report (" + (publisher or "outlet") + ") relaying a resident/witness sighting",
           3: "Aggregator write-up"}[tier]
    media = "photo/video attached or described" if (structured.get("media") or re.search(r"\b(?:video|footage|photo|clip|filmed|captured|grab|capta|vídeo|foto|imagen)", text)) else "no media"
    expl = "; an explanation is reported in the source" if _any(EXPLAINED, text) else ""
    out["evidence"] = f"{who}; {media}; not independently verified{expl} (automatic screening)"
    return out
