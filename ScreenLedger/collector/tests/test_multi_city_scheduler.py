from types import SimpleNamespace
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

import requests

from multi_city_scheduler import classify_failure, fail_due_pre_show_jobs, advance_slots
from smart_collector import IST, open_db


class MultiCityRetryPolicyTests(unittest.TestCase):
    def test_advance_schedule_today_and_midnight_reset(self):
        from datetime import date
        first = date(2026, 11, 7)
        self.assertEqual(advance_slots(datetime(2026, 11, 7, 13, 19, tzinfo=IST), first), [])
        at_1320 = advance_slots(datetime(2026, 11, 7, 13, 20, tzinfo=IST), first)
        self.assertEqual([(d.isoformat(), s.strftime('%H:%M')) for d, s in at_1320], [('2026-11-08', '13:20')])
        at_1335 = advance_slots(datetime(2026, 11, 7, 13, 35, tzinfo=IST), first)
        self.assertEqual([s.strftime('%H:%M') for _, s in at_1335], ['13:20', '13:35', '13:35'])
        after_midnight = advance_slots(datetime(2026, 11, 8, 0, 35, tzinfo=IST), first)
        self.assertEqual([(d.isoformat(), s.strftime('%H:%M')) for d, s in after_midnight],
                         [('2026-11-09', '00:20'), ('2026-11-10', '00:35'), ('2026-11-11', '00:35')])
    def test_permanent_pre_show_failure_settles_only_due_jobs_for_that_city(self):
        with tempfile.TemporaryDirectory() as temp:
            db = open_db(Path(temp) / "collector.sqlite")
            db.executemany("INSERT INTO final_jobs(movie_id,city,session_key,show_datetime_ist,target_utc,status) "
                           "VALUES (?,?,?,?,?,'pending')", [
                ("176276", "kothapeta", "due-1", "2026-11-07T10:20:00+05:30", "2026-11-07T04:45:00+00:00"),
                ("176276", "kothapeta", "future", "2026-11-07T11:00:00+05:30", "2026-11-07T05:30:00+00:00"),
                ("176276", "other-city", "other", "2026-11-07T10:20:00+05:30", "2026-11-07T04:45:00+00:00"),
            ])
            db.commit()
            affected = fail_due_pre_show_jobs(
                db, "176276", "kothapeta", datetime(2026, 11, 7, 10, 18, tzinfo=IST),
                "unrecognized_page")
            statuses = {r["session_key"]: r["status"] for r in db.execute(
                "SELECT session_key,status FROM final_jobs")}
            db.close()
        self.assertEqual(affected, 1)
        self.assertEqual(statuses, {"due-1": "failed", "future": "pending", "other": "pending"})

    def test_retryable_transport_errors(self):
        self.assertEqual(classify_failure(requests.Timeout("timed out")), (True, "timeout"))
        self.assertEqual(classify_failure(requests.ConnectionError("connection reset")),
                         (True, "connection_error"))

    def test_retryable_server_error(self):
        error = requests.HTTPError("server error", response=SimpleNamespace(status_code=503))
        self.assertEqual(classify_failure(error), (True, "http_503"))

    def test_client_and_parse_errors_are_permanent(self):
        not_found = requests.HTTPError("not found", response=SimpleNamespace(status_code=404))
        self.assertEqual(classify_failure(not_found), (False, "http_404"))
        self.assertEqual(classify_failure(
            ValueError("No movie metadata found; do not interpret as zero shows")),
            (False, "unrecognized_page"))
        self.assertEqual(classify_failure(ValueError("City redirect: requested foo, got bar")),
                         (False, "city_mismatch"))
