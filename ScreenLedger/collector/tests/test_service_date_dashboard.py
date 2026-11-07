import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import live_dashboard_server as dashboard


class ServiceDateDashboardTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE captures (
                id INTEGER PRIMARY KEY, movie_id TEXT, city TEXT, actual_city TEXT,
                observed_at_utc TEXT, reason TEXT, requested_at_utc TEXT, status TEXT,
                show_count INTEGER, raw_path TEXT, error TEXT, service_date_ist TEXT
            );
            CREATE TABLE observations (
                capture_id INTEGER, movie_id TEXT, city TEXT, session_key TEXT,
                show_datetime_ist TEXT, cinema_id TEXT, cinema_name TEXT,
                total_seats INTEGER, available_seats INTEGER, unavailable_seats INTEGER,
                estimated_gross_inr REAL, pricing_complete INTEGER
            );
            CREATE TABLE final_jobs (
                movie_id TEXT, city TEXT, session_key TEXT, show_datetime_ist TEXT,
                status TEXT
            );
        """)
        self.targets = [
            {"slug": "mumbai", "display_name": "Mumbai"},
            {"slug": "pune", "display_name": "Pune"},
            {"slug": "jaipur", "display_name": "Jaipur"},
        ]
        with patch.object(dashboard, "load_targets", return_value=self.targets):
            self._capture(1, "mumbai", "2026-11-07T08:00:00+00:00", "2026-11-09", "ok", "shared")
            self._capture(2, "pune", "2026-11-07T08:01:00+00:00", "2026-11-09", "ok", "shared")
            self._capture(3, "jaipur", "2026-11-07T08:02:00+00:00", "2026-11-09", "error")
            # Newer today capture for Mumbai must not replace its future-date capture.
            self._capture(4, "mumbai", "2026-11-07T09:00:00+00:00", "2026-11-07", "ok", "today")

    def tearDown(self):
        self.conn.close()

    def _capture(self, cid, city, observed, service_date, status, session=None):
        self.conn.execute("""INSERT INTO captures
            (id,movie_id,city,actual_city,observed_at_utc,reason,status,show_count,error,service_date_ist)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, dashboard.MOVIE_ID, city, city.title(), observed, "advance", status,
             1 if session else 0, "404" if status == "error" else None, service_date))
        if session:
            self.conn.execute("""INSERT INTO observations VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, dashboard.MOVIE_ID, city, session, "2026-11-09T18:30:00+05:30",
                 "cinema-1", "Example Cinema", 100, 60, 40, 10000, 1))

    def test_future_date_captures_are_selected_by_service_date_not_capture_day(self):
        with patch.object(dashboard, "load_targets", return_value=self.targets):
            result = dashboard.city_rows(self.conn, date(2026, 11, 9))
        by_city = {row["slug"]: row for row in result}
        self.assertEqual(by_city["mumbai"]["status"], "captured")
        self.assertEqual(by_city["pune"]["status"], "captured")
        self.assertEqual(by_city["jaipur"]["status"], "failed")
        self.assertEqual(by_city["mumbai"]["service_date"], "2026-11-09")

    def test_future_summary_and_sessions_deduplicate_overlapping_city_feeds(self):
        with patch.object(dashboard, "load_targets", return_value=self.targets):
            result = dashboard.summary(self.conn, date(2026, 11, 9))
            page = dashboard.show_page(self.conn, date(2026, 11, 9), "all", 1, 100, "")
        self.assertEqual(result["captured_city_feeds"], 2)
        self.assertEqual(result["failed_city_feeds"], 1)
        self.assertEqual(result["unique_sessions"], 1)
        self.assertEqual(result["duplicate_feed_rows"], 1)
        self.assertEqual(result["booked_plus_blocked_seats"], 40)
        self.assertEqual(page["rows"][0]["source_city_feed_count"], 2)
        self.assertEqual(page["rows"][0]["capture_reason"], "advance")

    def test_legacy_capture_is_inferred_only_when_observations_identify_one_date(self):
        self.conn.execute("UPDATE captures SET service_date_ist=NULL WHERE id=1")
        with patch.object(dashboard, "load_targets", return_value=self.targets):
            future = dashboard.city_rows(self.conn, date(2026, 11, 9))
            today = dashboard.city_rows(self.conn, date(2026, 11, 7))
        self.assertEqual(next(row for row in future if row["slug"] == "mumbai")["status"], "captured")
        self.assertEqual(next(row for row in today if row["slug"] == "mumbai")["status"], "captured")

    def test_day_cache_is_per_date_and_expires_after_five_minutes(self):
        with patch.object(dashboard,"_LEDGER_CACHE",{}), patch.object(dashboard,"day_ledger",side_effect=lambda conn,day,movie:{"service_date":day.isoformat()}) as build, patch.object(dashboard.monotonic_time,"monotonic",side_effect=[0,10,10,301,301]):
            first=dashboard.cached_day_ledger(self.conn,date(2026,11,7))
            again=dashboard.cached_day_ledger(self.conn,date(2026,11,7))
            advance=dashboard.cached_day_ledger(self.conn,date(2026,11,8))
            refreshed=dashboard.cached_day_ledger(self.conn,date(2026,11,7))
        self.assertEqual(first,again)
        self.assertEqual(advance["service_date"],"2026-11-08")
        self.assertEqual(refreshed["service_date"],"2026-11-07")
        self.assertEqual(build.call_count,3)

    def test_available_dates_includes_future_service_date(self):
        dates = dashboard.available_service_dates(self.conn)
        self.assertEqual(dates[0]["service_date"], "2026-11-09")
        self.assertEqual(dates[0]["successful_captures"], 2)
        self.assertEqual(dates[0]["failed_captures"], 1)

    def test_screenings_accept_safe_sort_and_daypart_filters(self):
        self.conn.executemany("""INSERT INTO observations VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?)""", [
            (1, dashboard.MOVIE_ID, "mumbai", "morning", "2026-11-09T10:00:00+05:30",
             "c2", "Morning Cinema", 100, 20, 80, 8000, 1),
            (1, dashboard.MOVIE_ID, "mumbai", "evening", "2026-11-09T18:30:00+05:30",
             "c3", "Evening Cinema", 100, 90, 10, 1000, 1),
        ])
        with patch.object(dashboard, "load_targets", return_value=self.targets):
            morning = dashboard.show_page(self.conn, date(2026, 11, 9), "all", 1, 100, "", "fill", "morning")
            fullest = dashboard.show_page(self.conn, date(2026, 11, 9), "all", 1, 100, "", "fill", "all")
        self.assertEqual([row["session_key"] for row in morning["rows"]], ["morning"])
        self.assertEqual(fullest["rows"][0]["session_key"], "morning")


if __name__ == "__main__":
    unittest.main()
