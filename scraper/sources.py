"""Every public, no-key source the sweep reads. Add or remove entries freely."""
from urllib.parse import quote_plus

# (label, hl, gl, ceid, [queries])  -- Google News RSS search, one per country edition.
EN = ["UFO sighting", "UAP sighting", "strange lights sky", "mystery drones sighting"]
ES = ["avistamiento ovni", "luces extrañas cielo", "ovni captan"]
PT = ["avistamento óvni", "luzes estranhas céu", "ovni flagrado"]
GOOGLE_EDITIONS = [
    ("United States", "en-US", "US", "US:en", EN + ["unidentified object sky"]),
    ("United Kingdom", "en-GB", "GB", "GB:en", EN),
    ("Canada (English)", "en-CA", "CA", "CA:en", EN),
    ("Canada (French)", "fr-CA", "CA", "CA:fr", ["ovni observation", "lumières étranges ciel"]),
    ("Australia", "en-AU", "AU", "AU:en", EN),
    ("New Zealand", "en-NZ", "NZ", "NZ:en", EN[:2]),
    ("Ireland", "en-IE", "IE", "IE:en", EN[:2]),
    ("India", "en-IN", "IN", "IN:en", EN),
    ("India (Hindi)", "hi", "IN", "IN:hi", ["यूएफओ देखा", "आसमान में रहस्यमयी रोशनी"]),
    ("Philippines", "en-PH", "PH", "PH:en", EN[:3]),
    ("South Africa", "en-ZA", "ZA", "ZA:en", EN[:3]),
    ("Nigeria", "en-NG", "NG", "NG:en", EN[:2]),
    ("Kenya", "en-KE", "KE", "KE:en", EN[:2]),
    ("Singapore", "en-SG", "SG", "SG:en", EN[:2]),
    ("Malaysia", "en-MY", "MY", "MY:en", EN[:2]),
    ("Pakistan", "en-PK", "PK", "PK:en", EN[:2]),
    ("Mexico", "es-419", "MX", "MX:es-419", ES),
    ("Argentina", "es-419", "AR", "AR:es-419", ES),
    ("Chile", "es-419", "CL", "CL:es-419", ES),
    ("Colombia", "es-419", "CO", "CO:es-419", ES),
    ("Peru", "es-419", "PE", "PE:es-419", ES[:2]),
    ("Uruguay", "es-419", "UY", "UY:es-419", ES[:2]),
    ("Venezuela", "es-419", "VE", "VE:es-419", ES[:2]),
    ("US (Spanish)", "es-419", "US", "US:es-419", ES[:2]),
    ("Spain", "es", "ES", "ES:es", ES),
    ("Brazil", "pt-BR", "BR", "BR:pt-419", PT),
    ("Portugal", "pt-PT", "PT", "PT:pt-150", PT[:2]),
    ("France", "fr", "FR", "FR:fr", ["ovni observation", "lumières étranges ciel", "ovni aperçu"]),
    ("Belgium (French)", "fr", "BE", "BE:fr", ["ovni observation"]),
    ("Switzerland (German)", "de", "CH", "CH:de", ["UFO Sichtung"]),
    ("Germany", "de", "DE", "DE:de", ["UFO Sichtung", "seltsame Lichter Himmel", "Drohnen Sichtung"]),
    ("Austria", "de", "AT", "AT:de", ["UFO Sichtung"]),
    ("Italy", "it", "IT", "IT:it", ["avvistamento ufo", "luci strane cielo"]),
    ("Netherlands", "nl", "NL", "NL:nl", ["ufo waarneming", "vreemde lichten lucht", "drones gespot"]),
    ("Belgium (Dutch)", "nl", "BE", "BE:nl", ["ufo waarneming"]),
    ("Sweden", "sv", "SE", "SE:sv", ["ufo observation", "ufo himlen"]),
    ("Norway", "no", "NO", "NO:no", ["ufo observasjon", "drone observert"]),
    ("Denmark", "da", "DK", "DK:da", ["ufo observation", "droner observeret"]),
    ("Finland", "fi", "FI", "FI:fi", ["ufo havainto"]),
    ("Poland", "pl", "PL", "PL:pl", ["UFO na niebie", "dziwne światła na niebie"]),
    ("Czechia", "cs", "CZ", "CZ:cs", ["UFO pozorování"]),
    ("Romania", "ro", "RO", "RO:ro", ["OZN observat"]),
    ("Hungary", "hu", "HU", "HU:hu", ["ufó észlelés"]),
    ("Greece", "el", "GR", "GR:el", ["UFO ουρανό"]),
    ("Turkey", "tr", "TR", "TR:tr", ["UFO görüldü", "gökyüzünde garip ışık"]),
    ("Ukraine", "uk", "UA", "UA:uk", ["НЛО небо", "НЛО помітили"]),
    ("Russia", "ru", "RU", "RU:ru", ["НЛО в небе", "НЛО заметили"]),
    ("Israel", "he", "IL", "IL:he", ["עב\"ם"]),
    ("Arabic (Egypt)", "ar", "EG", "EG:ar", ["جسم طائر مجهول"]),
    ("Arabic (Saudi)", "ar", "SA", "SA:ar", ["أضواء غامضة في السماء"]),
    ("Japan", "ja", "JP", "JP:ja", ["UFO 目撃", "未確認飛行物体"]),
    ("South Korea", "ko", "KR", "KR:ko", ["UFO 목격", "미확인 비행물체"]),
    ("Taiwan", "zh-TW", "TW", "TW:zh-Hant", ["UFO 目擊", "不明飛行物"]),
    ("Hong Kong", "zh-HK", "HK", "HK:zh-Hant", ["UFO 目擊"]),
    ("China (Simplified)", "zh-CN", "CN", "CN:zh-Hans", ["UFO 目击", "不明飞行物"]),
    ("Indonesia", "id", "ID", "ID:id", ["UFO terlihat", "cahaya misterius langit"]),
    ("Vietnam", "vi", "VN", "VN:vi", ["UFO xuất hiện"]),
    ("Thailand", "th", "TH", "TH:th", ["ยูเอฟโอ"]),
]

def google_news_feeds(window="when:3d"):
    for label, hl, gl, ceid, queries in GOOGLE_EDITIONS:
        for q in queries:
            url = f"https://news.google.com/rss/search?q={quote_plus(q + ' ' + window)}&hl={hl}&gl={gl}&ceid={ceid}"
            yield {"source": "Google News", "edition": label, "region": gl, "query": q, "url": url}

BING_MARKETS = [
    ("en-US", "US", ["UFO sighting", "UAP sighting", "strange lights sky"]), ("en-GB", "GB", ["UFO sighting"]),
    ("en-CA", "CA", ["UFO sighting"]), ("en-AU", "AU", ["UFO sighting"]), ("en-IN", "IN", ["UFO sighting"]),
    ("es-MX", "MX", ["avistamiento ovni"]), ("es-ES", "ES", ["avistamiento ovni"]), ("es-AR", "AR", ["ovni"]),
    ("pt-BR", "BR", ["óvni avistamento"]), ("fr-FR", "FR", ["ovni"]), ("de-DE", "DE", ["UFO Sichtung"]),
    ("it-IT", "IT", ["avvistamento ufo"]), ("nl-NL", "NL", ["ufo"]), ("ja-JP", "JP", ["UFO 目撃"]),
    ("pl-PL", "PL", ["UFO"]), ("tr-TR", "TR", ["UFO"]),
]

def bing_feeds():
    for mkt, cc, qs in BING_MARKETS:
        for q in qs:
            yield {"source": "Bing News", "edition": mkt, "region": cc, "query": q,
                   "url": f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss&mkt={mkt}"}

REDDIT_SUBS = ["UFOs", "UFOB", "aliens", "HighStrangeness", "UAP", "UFOsightings", "ufo"]
MASTODON_TAGS = ["ufo", "uap", "ufosighting", "ufos"]
EXTRA_RSS = [
    ("Open Minds UFO News", "https://www.openminds.tv/feed"),
    ("Liberation Times", "https://www.liberationtimes.com/home?format=rss"),
]
MELDPUNT_HOME = "https://www.ufomeldpunt.nl/"
