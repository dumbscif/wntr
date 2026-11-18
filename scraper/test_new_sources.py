"""Parsers for sources added in the 2026-11-18 vital-source expansion."""
import unittest
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import witness_sources as W

UFOBC_FIXTURE = """
<html><body>
Reported 8-Nov-2026<br>Winter 1993, Surrey BC : (Nighttime) A massive craft hovered silently.
<hr>
Reported 3-Nov-2026<br>26-Sept-2026, Cranbrook, BC : (7:15am) I live in Cranbrook. Photo: clip.JPG
Reported 21-July-2026<br>July 21 2021, Highway 97 , BC : (6:15 pm) Held this one for a while.
Reported 4-Feb-2026<br>Early-August-2025, Barnhartvale, BC : Hello UFO BC, unusual experience.
</body></html>
"""

GEIPAN_FIXTURE = """
<html><body><h2>Liste des cas</h2>
<a href="/fr/cas/2026-01-01234-papeete">PAPEETE (987) 12.01.2026</a>
Classification : A Département : Polynésie française Date de mise à jour : 26/02/2026
<a href="/fr/cas/2026-01-00001-rumilly">RUMILLY (74) 01.01.2026</a>
Classification : A Département : Haute-Savoie
</body></html>
"""

class TestUfoBc(unittest.TestCase):
    def test_parses_distinct_listing_rows(self):
        items = W.parse_ufobc(UFOBC_FIXTURE)
        self.assertEqual(len(items), 4)
        urls = [i["url"] for i in items]
        self.assertEqual(len(set(urls)), 4)
        self.assertTrue(all("#case-" in u for u in urls))
        by_place = {i["place_hint"]: i for i in items}
        self.assertIn("Surrey BC, Canada", by_place)
        self.assertIn("Cranbrook, BC, Canada", by_place)
        self.assertIn("Barnhartvale, BC, Canada", by_place)
        self.assertTrue(by_place["Cranbrook, BC, Canada"]["structured"]["media"])
        self.assertFalse(by_place["Surrey BC, Canada"]["structured"]["media"])
        self.assertEqual(by_place["Surrey BC, Canada"]["published"],
                         datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(by_place["Surrey BC, Canada"]["event_local"], "Winter 1993")

class TestGeipan(unittest.TestCase):
    def test_parses_case_links(self):
        # reuse fetch_geipan internals by calling the same regex path via a stub
        class R:
            def __init__(self, text):
                self.text = text
                self.content = text.encode()
                self.reason = "OK"
        got = []
        def get(url, fam, **kw):
            got.append(url)
            return R(GEIPAN_FIXTURE)
        stats = []
        def stat(fam, **kw):
            stats.append(kw)
        items = W.fetch_geipan(get, stat)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i["url"].startswith("https://www.cnes-geipan.fr/fr/cas/") for i in items))
        self.assertEqual(items[0]["event_date"], "2026-01-12")
        self.assertIn("PAPEETE", (items[0]["place_hint"] or items[0]["title"]).upper())

if __name__ == "__main__":
    unittest.main()
