"""Gazetteer must not pin generic/capitalized words in YouTube-style titles."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import Gazetteer, COMMON, PREP_BEFORE
import sweep as SW

class TestStoplistAndContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Gazetteer(nominatim_cap=0)

    def loc(self, text, region=None):
        return self.g.locate(text, region)

    def test_stoplist_contains_requested_words(self):
        for w in ("real", "america", "américa", "sol", "luz"):
            self.assertIn(w, COMMON)

    def test_ovni_real_is_not_braga(self):
        t = "Un Testigo Grabó un OVNI Real con una Cámara — Lo Que Ocurrió Después Sigue Siendo Inexplicable"
        self.assertIsNone(self.loc(t))
        # the old bug: last letter of OVNI ('i', a Nordic/Italian prep) looked like "in Real"
        self.assertFalse(PREP_BEFORE.search("testigo grabó un ovni "))

    def test_over_america_is_not_buenos_aires_town(self):
        t = "WORLD ALERT! The TRUTH about the UFO that appeared over America. A stunning luminous object appeared in the sky on the night of November 13, 2026."
        self.assertIsNone(self.loc(t))

    def test_sol_and_luz_alone_are_not_places(self):
        self.assertIsNone(self.loc("Luces extrañas sobre Sol en el cielo"))
        self.assertIsNone(self.loc("Avistamiento de una Luz misteriosa de noche"))

    def test_real_with_region_still_allowed(self):
        p = self.loc("Sighting in Real, Braga, Portugal")
        self.assertIsNotNone(p)
        self.assertEqual(p["cc"], "PT")
        self.assertIn("Real", p["place"])

    def test_known_city_with_region(self):
        p = self.loc("UFO sighting over Phoenix, Arizona last night")
        self.assertIsNotNone(p)
        self.assertEqual(p["cc"], "US")
        self.assertIn("Phoenix", p["place"])

    def test_over_alaska(self):
        p = self.loc("Strange Object JUST SPOTTED in the Sky Over ALASKA... People Are FREAKING OUT!")
        self.assertIsNotNone(p)
        self.assertEqual(p["cc"], "US")
        self.assertIn("Alaska", p["place"])

    def test_eastern_pennsylvania_is_not_fiji(self):
        p = self.loc("Object in the Sky Over Eastern Pennsylvania")
        self.assertIsNotNone(p)
        self.assertEqual(p["cc"], "US")
        self.assertIn("Pennsylvania", p["place"])
        self.assertNotIn("Fiji", p["place"])

    def test_santiago_chile(self):
        p = self.loc("ovni sobre Santiago, Chile")
        self.assertIsNotNone(p)
        self.assertEqual(p["cc"], "CL")

class TestYouTubeLocateAndRecheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Gazetteer(nominatim_cap=0)

    def test_youtube_requires_confident_context(self):
        it = {"title": "Un Testigo Grabó un OVNI Real con una Cámara", "summary": "", "family": "YouTube"}
        self.assertIsNone(SW.locate_item(self.g, it))
        it = {"title": "The TRUTH about the UFO that appeared over America", "summary": "", "family": "YouTube"}
        self.assertIsNone(SW.locate_item(self.g, it))
        it = {"title": "Strange Object JUST SPOTTED in the Sky Over ALASKA", "summary": "", "family": "YouTube"}
        p = SW.locate_item(self.g, it)
        self.assertIsNotNone(p)
        self.assertIn("Alaska", p["place"])

    def test_recheck_clears_misfired_youtube_pins(self):
        reports = [
            {"id": "auto-7d5bc4922102", "origin": "auto", "kind": "sighting",
             "title": "Un Testigo Grabó un OVNI Real con una Cámara — Lo Que Ocurrió Después Sigue Siendo Inexplicable",
             "summary": "Hay cosas que la gente ...", "feed": "YouTube / ovni avistamiento video 2026",
             "place": "Real, Braga, Portugal", "country": "Portugal", "lat": 41.5584, "lon": -8.4433,
             "gid": "2735418", "precision": "city/town-level approximation from gazetteer match on 'Real'; not an object position",
             "sources": [{"url": "https://www.youtube.com/watch?v=Ai4pVLnOi_k", "name": "YouTube"}]},
            {"id": "auto-4fce3b2f4288", "origin": "auto", "kind": "sighting",
             "title": "WORLD ALERT! The TRUTH about the UFO that appeared over America",
             "summary": "A stunning luminous object appeared in the sky on the night of November 13, 2026.",
             "feed": "YouTube / ovni avistamiento video 2026",
             "place": "América, Buenos Aires, Argentina", "country": "Argentina", "lat": -35.4977, "lon": -62.9743,
             "gid": "12035905", "precision": "city/town-level approximation from gazetteer match on 'America'; not an object position",
             "sources": [{"url": "https://www.youtube.com/watch?v=Kt_vER7hMLg", "name": "YouTube"}]},
            {"id": "auto-keep-alaska", "origin": "auto", "kind": "sighting",
             "title": "Strange Object JUST SPOTTED in the Sky Over ALASKA... People Are FREAKING OUT!",
             "summary": "", "feed": "YouTube / UFO sighting November 2026",
             "place": "Alaska, United States", "country": "United States", "lat": 61.281, "lon": -148.361,
             "gid": "a1:US.AK", "precision": "state/province-level only (population-weighted centre of GeoNames towns in 'Alaska'); NOT a sighting position",
             "sources": [{"url": "https://www.youtube.com/watch?v=ivO_-9PM5e0", "name": "YouTube"}]},
        ]
        n = SW.recheck_auto_locations(reports, self.g)
        self.assertEqual(n, 2)
        by = {r["id"]: r for r in reports}
        self.assertIsNone(by["auto-7d5bc4922102"]["lat"])
        self.assertIsNone(by["auto-4fce3b2f4288"]["place"])
        self.assertIn("no location found in source text", by["auto-7d5bc4922102"]["precision"])
        self.assertIsNotNone(by["auto-keep-alaska"]["lat"])
        self.assertIn("Alaska", by["auto-keep-alaska"]["place"])

        # gate then excludes the two, keeps Alaska
        import gate as GATE
        from grading import grade
        for r in reports:
            r["mediaAttached"] = True
            r["grade"] = grade(r) if r.get("kind") == "sighting" else None
        kept, excl, stats = GATE.apply_gate(reports, [], sighting=lambda r: r.get("kind") == "sighting")
        kept_ids = {r["id"] for r in kept}
        self.assertIn("auto-keep-alaska", kept_ids)
        self.assertNotIn("auto-7d5bc4922102", kept_ids)
        self.assertNotIn("auto-4fce3b2f4288", kept_ids)
        self.assertEqual(stats["excludedNoLocation"], 2)
        reasons = {(e.get("id"), (e.get("reasons") or [None])[0]) for e in excl}
        self.assertIn(("auto-7d5bc4922102", GATE.REASON_NO_LOCATION), reasons)
        self.assertIn(("auto-4fce3b2f4288", GATE.REASON_NO_LOCATION), reasons)

if __name__ == "__main__":
    unittest.main()
