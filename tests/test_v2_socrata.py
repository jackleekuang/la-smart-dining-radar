"""Tests for src.v2.socrata — pagination, watermark and SoQL building. No network required."""

import json
import unittest

from src.v2 import socrata


class BuildParamsTests(unittest.TestCase):
    def test_full_load_has_no_watermark_clause(self):
        params = socrata.build_params("naics", "722", None, 100, 0)
        self.assertEqual(params["$where"], "naics >= 722000 AND naics < 723000")
        self.assertEqual(params["$select"], "*, :id, :updated_at")
        self.assertEqual(params["$order"], ":id")

    def test_incremental_strips_timezone_suffix(self):
        params = socrata.build_params("naics", "722", "2026-10-01T12:00:00+00:00", 100, 200)
        self.assertIn(":updated_at > '2026-10-01T12:00:00'", params["$where"])
        self.assertEqual(params["$offset"], "200")

    def test_rejects_injection_in_field_name(self):
        with self.assertRaises(ValueError):
            socrata.build_params("naics' or 1=1 --", "722", None, 10, 0)

    def test_rejects_non_digit_prefix(self):
        with self.assertRaises(ValueError):
            socrata.build_params("naics", "72%", None, 10, 0)


class IterPagesTests(unittest.TestCase):
    def test_paginates_until_short_page(self):
        pages = [[{"a": i} for i in range(3)], [{"a": i} for i in range(3)], [{"a": 0}]]
        calls = []

        def fake_fetch(url, params, headers):
            calls.append(params["$offset"])
            return pages[len(calls) - 1]

        got = list(socrata.iter_pages(fake_fetch, "u", "naics", "722", None, 3))
        self.assertEqual([len(p) for p in got], [3, 3, 1])
        self.assertEqual(calls, ["0", "3", "6"])

    def test_empty_source_yields_nothing(self):
        got = list(socrata.iter_pages(lambda *_: [], "u", "naics", "722", None, 3))
        self.assertEqual(got, [])

    def test_exact_multiple_of_page_size_stops_on_empty_page(self):
        pages = [[{"a": 1}, {"a": 2}], []]
        calls = []

        def fake_fetch(url, params, headers):
            calls.append(params["$offset"])
            return pages[len(calls) - 1]

        got = list(socrata.iter_pages(fake_fetch, "u", "naics", "722", None, 2))
        self.assertEqual(len(got), 1)
        self.assertEqual(calls, ["0", "2"])


class ToRawRowsTests(unittest.TestCase):
    def test_keeps_full_payload_and_lifts_system_fields(self):
        row = {":id": "row-1", ":updated_at": "2026-10-01T00:00:00.000", "dba_name": "Café Ñ"}
        out = socrata.to_raw_rows([row], "2026-10-26T00:00:00+00:00")[0]
        self.assertEqual(out["source_row_id"], "row-1")
        self.assertEqual(out["source_updated_at"], "2026-10-01T00:00:00.000")
        self.assertEqual(json.loads(out["payload"]), row)
        self.assertIn("Café Ñ", out["payload"])  # ensure_ascii=False keeps names readable


if __name__ == "__main__":
    unittest.main()
