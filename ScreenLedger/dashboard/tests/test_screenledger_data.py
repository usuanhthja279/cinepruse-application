import sys
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_city_state_mapping import build, current_state
from compare_hourly_snapshots import compare_rows


def screening(key, capture, booked, *, pricing=True, revenue="250"):
    return {
        "service_date_ist": "2026-11-07", "collection_hour_ist": capture[11:16],
        "session_key": key, "source_city_slug": "mumbai", "actual_city": "Mumbai",
        "captured_at_ist": capture, "show_datetime_ist": "2026-11-07T12:30:00+05:30",
        "cinema_id": "cinema-1", "cinema_name": "Example Cinema", "total_seats": "100",
        "available_seats": str(100 - booked), "booked_plus_blocked_seats": str(booked),
        "confirmed_revenue_inr": revenue, "pricing_complete": str(pricing).lower(),
    }


class CityStateMappingTests(unittest.TestCase):
    def test_post_2011_admin_crosswalk(self):
        self.assertEqual(current_state("28", "007"), "Telangana")
        self.assertEqual(current_state("28", "002"), "Andhra Pradesh")
        self.assertEqual(current_state("01", "003"), "Ladakh")
        self.assertEqual(current_state("25", "000"), "Dadra & Nagar Haveli and Daman & Diu")

    def test_duplicate_selector_labels_are_retained_and_ncr_alias_is_labeled(self):
        roster = {"source_url": "https://www.district.in/movies/", "captured_at_local": "2026-11-07",
                  "letters": {"A": {"cities": ["Aurangabad", "Aurangabad", "Delhi/NCR"]}}}
        rows, provenance = build(roster, {"aurangabad": {"Maharashtra", "Bihar"}})
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["occurrence"] for r in rows[:2]], ["1", "2"])
        self.assertEqual(rows[0]["mapping_status"], "ambiguous_multiple_states")
        self.assertEqual(rows[2]["mapping_status"], "matched_curated_city_state")
        self.assertEqual(rows[2]["state_or_ut"], "Delhi")
        self.assertEqual(provenance["selector_labels"], 3)

    def test_unique_settlement_fallback_is_separately_labeled(self):
        roster = {"letters": {"A": {"cities": ["Smalltown"]}}}
        rows, _ = build(roster, {}, {"smalltown": {"Kerala"}})
        self.assertEqual(rows[0]["mapping_status"], "matched_exact_2011_settlement_name")
        self.assertEqual(rows[0]["state_or_ut"], "Kerala")

    def test_simplified_map_has_36_geographic_features(self):
        geo = json.loads((ROOT / "assets" / "india_state_map_simplified.geojson").read_text(encoding="utf-8"))
        self.assertEqual(len(geo["features"]), 36)
        points = []
        def visit(value):
            if isinstance(value, list) and len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
                points.append(value)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        for feature in geo["features"]:
            visit(feature["geometry"]["coordinates"])
        self.assertTrue(points)
        self.assertGreaterEqual(min(point[0] for point in points), 60)
        self.assertLessEqual(max(point[0] for point in points), 100)
        self.assertGreaterEqual(min(point[1] for point in points), 0)
        self.assertLessEqual(max(point[1] for point in points), 40)


class HourlyComparisonTests(unittest.TestCase):
    def test_hourly_snapshots_and_saved_comparisons_are_present(self):
        data_dir = ROOT / "data" / "district_hourly_runs_2026-11-07"
        summary = json.loads((data_dir / "run_summaries.json").read_text(encoding="utf-8"))
        hours = [r["collection_hour_ist"] for r in summary["runs"]]
        self.assertGreaterEqual(len(hours), 6)
        self.assertEqual(hours, sorted(set(hours)))
        comparison_files = sorted(data_dir.glob("matched_delta_2026-11-07_*.json"))
        self.assertTrue(comparison_files)
        for path in comparison_files:
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(result["comparison"]["matched_future_session_count"], 0)

    def test_positive_release_and_incomplete_revenue_are_separate(self):
        previous = [
            screening("same", "2026-11-07T01:00:00+05:30", 10),
            screening("down", "2026-11-07T01:00:00+05:30", 15),
        ]
        current = [
            screening("same", "2026-11-07T02:00:00+05:30", 13, pricing=False, revenue=""),
            screening("down", "2026-11-07T02:00:00+05:30", 12),
        ]
        result = compare_rows(previous, current, movie_id="176276")
        summary = result["comparison"]
        self.assertEqual(summary["matched_future_session_count"], 2)
        self.assertEqual(summary["seat_change"]["positive_booked_plus_blocked_seats"], 3)
        self.assertEqual(summary["seat_change"]["released_or_corrected_seats"], 3)
        self.assertEqual(summary["seat_change"]["net_booked_plus_blocked_seat_change"], 0)
        self.assertFalse(summary["confirmed_revenue_change_inr"]["available"])
        self.assertIsNone(summary["confirmed_revenue_change_inr"]["value"])


if __name__ == "__main__":
    unittest.main()
