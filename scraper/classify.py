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
