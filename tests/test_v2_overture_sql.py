"""Tests for src.v2.overture_sql — release detection and SQL builders. No BigQuery required."""

import datetime as dt
import re
import unittest

from src.v2 import overture_sql, settings

TARGET = "my-proj.raw.raw_overture_places"


class DetectReleaseTests(unittest.TestCase):
    def test_uses_date_like_label(self):
        labels = {"owner": "carto", "overture_release": "2026-10-15_0"}
        got = overture_sql.detect_release(labels, dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc))
        self.assertEqual(got, "2026-10-15")

    def test_underscore_dates_are_normalized(self):
        got = overture_sql.detect_release({"version": "v2026_09_17"}, dt.datetime(2026, 9, 20))
        self.assertEqual(got, "2026-09-17")

    def test_falls_back_to_modified_date(self):
        got = overture_sql.detect_release({}, dt.datetime(2026, 10, 20, 8, 0))
        self.assertEqual(got, "2026-10-20")


class SnapshotSqlTests(unittest.TestCase):
    def setUp(self):
        self.sql = overture_sql.build_snapshot_insert(
            TARGET, settings.OVERTURE_PLACES_TABLE, settings.LA_BBOX, settings.OVERTURE_FOOD_REGEX
        )

    def test_targets_and_parameters(self):
        self.assertIn(f"INSERT INTO `{TARGET}`", self.sql)
        self.assertIn("@snapshot_release", self.sql)
        self.assertIn("@snapshot_date", self.sql)

    def test_bbox_filter_uses_configured_box(self):
        b = settings.LA_BBOX
        self.assertIn(f"ST_INTERSECTSBOX(geometry, {b['xmin']}, {b['ymin']}, {b['xmax']}, {b['ymax']})", self.sql)

    def test_payload_keeps_full_row_without_geometry(self):
        self.assertIn("* EXCEPT (geometry)", self.sql)
        self.assertIn("TO_JSON_STRING(t)", self.sql)

    def test_food_regex_compiles_and_filters_sensibly(self):
        pattern = re.compile(settings.OVERTURE_FOOD_REGEX)
        for hit in ['"primary":"mexican_restaurant"', '"primary":"cocktail_bar"', '"primary":"coffee_shop"']:
            self.assertTrue(pattern.search(hit), hit)
        for miss in ['"primary":"public_school"', '"primary":"barber"', '"primary":"delivery_service"']:
            self.assertFalse(pattern.search(miss), miss)

    def test_rejects_bad_table_names(self):
        with self.assertRaises(ValueError):
            overture_sql.build_snapshot_insert("raw_overture_places; drop", "a.b.c", settings.LA_BBOX, "x")


class ReleaseSqlTests(unittest.TestCase):
    def test_count_and_delete_are_scoped_to_one_release(self):
        self.assertIn("WHERE snapshot_release = @snapshot_release", overture_sql.build_release_count_sql(TARGET))
        self.assertIn("WHERE snapshot_release = @snapshot_release", overture_sql.build_release_delete_sql(TARGET))


if __name__ == "__main__":
    unittest.main()
