"""Public synthetic checks; no native note files or account needed."""
import copy
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "examples"))
from notability import match_concepts, normalize_segments, align
from demo import fixtures
import json

class MatchingTests(unittest.TestCase):
    def test_rank_and_keep_separate_clocks(self):
        note, regions = fixtures()
        rows = match_concepts(note, regions)[0]["candidates"]
        self.assertEqual(rows[0]["segment_id"], "same-clock")
        self.assertTrue(rows[0]["temporal_overlap"])
        self.assertFalse(rows[1]["temporal_overlap"])
        self.assertEqual(rows[1]["basis"], "keyword_evidence")
        self.assertTrue(all(r["status"] == "candidate" for r in rows))

    def test_unknown_stroke_rejected(self):
        note, regions = fixtures()
        regions[0]["stroke_ids"] = ["missing"]
        with self.assertRaises(ValueError):
            match_concepts(note, regions)

    def test_cross_page_region_rejected(self):
        note, regions = fixtures()
        note["strokes"].append({"id": "synthetic-2", "page_id": "other-page"})
        regions[0]["stroke_ids"].append("synthetic-2")
        with self.assertRaises(ValueError):
            match_concepts(note, regions)

    def test_invalid_timestamps_rejected(self):
        for start, end in [(-1, 2), (4, 2), (float("nan"), 2)]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                normalize_segments([{"text": "demo", "start": start, "end": end}], "demo", "synthetic")

    def test_untimed_text_has_no_fabricated_clock(self):
        row = normalize_segments([{"text": "demo"}], "external", "synthetic")[0]
        self.assertIsNone(row["start"])
        self.assertIsNone(row["end"])

    def test_html_escaping_and_preserve_existing_output(self):
        note, regions = fixtures()
        note["segments"][0]["text"] = "<script>bad()</script> 큐"
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "note.json").write_text(json.dumps(note), encoding="utf-8")
            annotation = out / "regions.json"
            annotation.write_text(json.dumps(regions), encoding="utf-8")
            align(out, annotation)
            html = (out / "concepts.html").read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;bad()", html)
            self.assertNotIn("<script>bad()", html)
            with self.assertRaises(ValueError):
                align(out, annotation)

if __name__ == "__main__":
    unittest.main()
