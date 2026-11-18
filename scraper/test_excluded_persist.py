"""Regression: excluded records with distinct ids must survive a shared listing URL."""
import unittest
import gate


def _item(eid, url, title="t"):
    return {"id": eid, "url": url, "title": title, "decision": "excluded",
            "gate": "location-or-evidence-2026-11-18", "reasons": ["weak uncorroborated evidence (grade <= 2, fewer than two independent reports)"]}


class ExcludedPersist(unittest.TestCase):
    def test_shared_listing_url_keeps_every_id(self):
        listing = "https://mufoncms.com/last_20_public.html"
        items = [_item(f"evt-a-{i}", listing, f"Case {i}") for i in range(4)]
        items.append({"title": "Unrelated screening", "url": listing, "decision": "excluded",
                      "reasons": ["screening score 4 < 6"]})
        kept = gate.merge_excluded_items(items)
        ids = {e.get("id") for e in kept if e.get("id")}
        self.assertEqual(ids, {f"evt-a-{i}" for i in range(4)})

    def test_idless_rows_still_dedupe_by_url(self):
        url = "https://example.com/story"
        a = {"title": "Newer", "url": url, "decision": "excluded", "excludedAt": "2026-11-18T20:00:00Z"}
        b = {"title": "Older", "url": url, "decision": "excluded", "excludedAt": "2026-11-01T00:00:00Z"}
        kept = gate.merge_excluded_items([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title"], "Newer")

    def test_union_recovers_ids_missing_from_live_copy(self):
        live = [_item("evt-kept", "https://ufosighting.report/")]
        repo = live + [_item("evt-dropped", "https://ufosighting.report/")]
        kept = gate.merge_excluded_items(live, repo)
        self.assertEqual({e["id"] for e in kept}, {"evt-kept", "evt-dropped"})


if __name__ == "__main__":
    unittest.main()
