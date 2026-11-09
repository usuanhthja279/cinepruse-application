from types import SimpleNamespace
from datetime import datetime
from pathlib import Path
import json
import tempfile
import unittest

import requests

from multi_city_scheduler import (classify_failure, fail_due_pre_show_jobs, due_pre_show_cities,
                                 expire_stale_pre_show_jobs, advance_slots,
                                 round_robin_advance_targets,
                                 urgent_worker_limit,load_advance_targets,write_advance_roster,
                                 start_discovery_epoch,advance_targets_for_epoch,write_verified_roster,
                                 city_targets)
from smart_collector import IST, open_db


class MultiCityRetryPolicyTests(unittest.TestCase):
    def test_verified_city_aliases_share_one_request_and_preserve_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cities.json'
            path.write_text(json.dumps({'letters': {'C': {'cities': [
                'Chikballapur', 'Chikkaballapura'
            ]}}}), encoding='utf-8')
            targets, report = city_targets(path)
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0]['slug'], 'chikkaballapura')
            self.assertEqual(targets[0]['aliases'], ['Chikkaballapura'])
            self.assertEqual(report['selector_entries'], 2)
            self.assertEqual(report['unique_request_slugs'], 1)
            self.assertEqual(report['repeated_labels_or_aliases_collapsed'], 1)

    def test_restart_and_midnight_reset_city_discovery_without_erasing_pre_show(self):
        from datetime import date
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp); db = open_db(store / 'collector.sqlite')
            db.executemany('INSERT INTO kv_state(key,value) VALUES(?,?)', [
                ('multi_initial_complete:176276:2026-11-09','1'),
                ('multi_baseline:176276:2026-11-09:alpha','ok'),
                ('multi_hourly:176276:2026-11-09:alpha','old'),
                ('multi_advance:176276:2026-11-10:alpha','old'),
                ('multi_final_retry:176276:2026-11-09:alpha','keep'),
            ]); db.commit()
            day = date(2026,11,9)
            started, needs_full = start_discovery_epoch(db, '176276', day, datetime(2026,11,9,0,0,tzinfo=IST))
            self.assertEqual(db.execute("SELECT value FROM kv_state WHERE key='multi_final_retry:176276:2026-11-09:alpha'").fetchone()[0], 'keep')
            for key in ('multi_initial_complete:176276:2026-11-09', 'multi_baseline:176276:2026-11-09:alpha', 'multi_hourly:176276:2026-11-09:alpha', 'multi_advance:176276:2026-11-10:alpha'):
                self.assertIsNone(db.execute('SELECT value FROM kv_state WHERE key=?',(key,)).fetchone())
            targets = [{'slug':'alpha'},{'slug':'beta'}]
            (store/'city_targets_advance_176276_2026-11-10.json').write_text('{"cities":[{"slug":"alpha"}]}',encoding='utf8')
            future=date(2026,11,10)
            self.assertEqual(advance_targets_for_epoch(store,'176276',future,targets,needs_full),targets)
            needs_full.remove(future)
            self.assertEqual(advance_targets_for_epoch(store,'176276',future,targets,needs_full),[{'slug':'alpha'}])
            db.executemany("INSERT INTO captures(movie_id,city,observed_at_utc,reason,status,show_count,service_date_ist) VALUES(?,?,?,?,?,?,?)",[
                ('176276','alpha','2026-11-08T18:00:00+00:00','baseline','ok',1,day.isoformat()),
                ('176276','beta',started,'baseline','ok',1,day.isoformat())])
            report=write_verified_roster(store,targets,'176276',day,db,started)
            self.assertEqual([x['slug'] for x in report['cities']],['beta'])
            db.close()

    def test_incomplete_language_metadata_retries(self):
        self.assertEqual(classify_failure(ValueError('District did not provide language format identifiers; capture incomplete')),
                         (True, 'incomplete_language_metadata'))
        self.assertEqual(classify_failure(ValueError('District returned a generic movie landing without city or show listings')),
                         (True, 'generic_movie_landing'))

    def test_default_daily_advance_times_start_after_midnight(self):
        from datetime import date
        day = date(2026, 11, 9)
        self.assertEqual(advance_slots(datetime(2026,11,9,0,19,tzinfo=IST), day), [])
        self.assertEqual([(d.isoformat(), t.strftime('%H:%M')) for d,t in
                          advance_slots(datetime(2026,11,9,0,20,tzinfo=IST), day)],
                         [('2026-11-10','00:20')])
        self.assertEqual([(d.isoformat(), t.strftime('%H:%M')) for d,t in
                          advance_slots(datetime(2026,11,9,0,35,tzinfo=IST), day)],
                         [('2026-11-10','00:20'),('2026-11-11','00:35'),('2026-11-12','00:35')])

    def test_due_advance_dates_are_interleaved_instead_of_starving_later_dates(self):
        from datetime import date
        schedules = [
            (date(2026, 11, 10), datetime(2026, 11, 9, 0, 20, tzinfo=IST),
             [{'slug': 'alpha'}, {'slug': 'beta'}]),
            (date(2026, 11, 11), datetime(2026, 11, 9, 0, 35, tzinfo=IST),
             [{'slug': 'alpha'}, {'slug': 'beta'}]),
            (date(2026, 11, 12), datetime(2026, 11, 9, 0, 35, tzinfo=IST),
             [{'slug': 'alpha'}, {'slug': 'beta'}]),
        ]
        result = list(round_robin_advance_targets(schedules))
        self.assertEqual([(day.isoformat(), target['slug']) for day, _, target in result], [
            ('2026-11-10', 'alpha'), ('2026-11-11', 'alpha'),
            ('2026-11-12', 'alpha'), ('2026-11-10', 'beta'),
            ('2026-11-11', 'beta'), ('2026-11-12', 'beta'),
        ])

    def test_due_pre_show_cities_are_ordered_by_earliest_deadline(self):
        from datetime import date
        with tempfile.TemporaryDirectory() as temp:
            db = open_db(Path(temp) / "collector.sqlite")
            db.executemany("INSERT INTO final_jobs(movie_id,city,session_key,show_datetime_ist,target_utc,status) VALUES(?,?,?,?,?,'pending')", [
                ("176276", "alpha", "a", "2026-11-08T21:05:00+05:30", "2026-11-08T15:30:00+00:00"),
                ("176276", "zeta", "z", "2026-11-08T21:03:00+05:30", "2026-11-08T15:28:00+00:00"),
                ("176276", "later", "l", "2026-11-08T21:10:00+05:30", "2026-11-08T15:35:00+00:00"),
            ])
            db.commit()
            due = due_pre_show_cities(db, "176276", date(2026, 11, 8), datetime(2026, 11, 8, 21, 1, tzinfo=IST))
            self.assertEqual([row["city"] for row in due], ["zeta", "alpha"])
            db.close()

    def test_stale_pre_show_jobs_expire_without_touching_current_or_future_jobs(self):
        from datetime import date
        with tempfile.TemporaryDirectory() as temp:
            db = open_db(Path(temp) / "collector.sqlite")
            db.executemany("INSERT INTO final_jobs(movie_id,city,session_key,show_datetime_ist,target_utc,status) "
                           "VALUES (?,?,?,?,?,'pending')", [
                ("176276", "old", "old", "2026-11-08T20:45:00+05:30", "2026-11-08T15:10:00+00:00"),
                ("176276", "due", "due", "2026-11-08T21:05:00+05:30", "2026-11-08T15:30:00+00:00"),
                ("176276", "future", "future", "2026-11-08T21:20:00+05:30", "2026-11-08T15:45:00+00:00"),
            ])
            db.commit()
            affected = expire_stale_pre_show_jobs(
                db, "176276", date(2026, 11, 8), datetime(2026, 11, 8, 21, 1, tzinfo=IST))
            statuses = {r["session_key"]: r["status"] for r in db.execute(
                "SELECT session_key,status FROM final_jobs")}
            db.close()
        self.assertEqual(affected, 1)
        self.assertEqual(statuses, {"old": "failed", "due": "pending", "future": "pending"})

    def test_pre_show_bursts_borrow_workers_within_fixed_pool(self):
        self.assertEqual([urgent_worker_limit(n) for n in range(6)],[0,1,2,3,4,5])
        self.assertEqual(urgent_worker_limit(50),5)

    def test_advance_roster_starts_full_then_keeps_cities_with_listings(self):
        from datetime import date
        with tempfile.TemporaryDirectory() as temp:
            store=Path(temp);db=open_db(store/'collector.sqlite');day=date(2026,11,8)
            targets=[{'slug':'alpha'},{'slug':'beta'},{'slug':'gamma'}]
            self.assertEqual(load_advance_targets(store,'176276',day,targets),targets)
            db.executemany("INSERT INTO captures(movie_id,city,observed_at_utc,reason,status,show_count,service_date_ist) VALUES(?,?,?,?,?,?,?)",[
                ('176276','alpha','2026-11-08T00:20:00+00:00','advance','ok',4,day.isoformat()),
                ('176276','beta','2026-11-08T00:20:00+00:00','advance','ok',0,day.isoformat()),
                ('176276','gamma','2026-11-08T00:20:00+00:00','advance','error',None,day.isoformat())])
            roster=write_advance_roster(store,db,targets,'176276',day,datetime(2026,11,8,5,50,tzinfo=IST))
            self.assertEqual(roster['cities_with_listings'],1)
            self.assertEqual([t['slug'] for t in load_advance_targets(store,'176276',day,targets)],['alpha'])
            db.close()
    def test_advance_schedule_today_and_midnight_reset(self):
        from datetime import date
        first = date(2026, 11, 7)
        self.assertEqual(advance_slots(datetime(2026, 11, 7, 13, 19, tzinfo=IST), first, 13), [])
        at_1320 = advance_slots(datetime(2026, 11, 7, 13, 20, tzinfo=IST), first, 13)
        self.assertEqual([(d.isoformat(), s.strftime('%H:%M')) for d, s in at_1320], [('2026-11-08', '13:20')])
        at_1335 = advance_slots(datetime(2026, 11, 7, 13, 35, tzinfo=IST), first, 13)
        self.assertEqual([s.strftime('%H:%M') for _, s in at_1335], ['13:20', '13:35', '13:35'])
        after_midnight = advance_slots(datetime(2026, 11, 8, 0, 35, tzinfo=IST), first)
        self.assertEqual([(d.isoformat(), s.strftime('%H:%M')) for d, s in after_midnight],
                         [('2026-11-09', '00:20'), ('2026-11-10', '00:35'), ('2026-11-11', '00:35')])

    def test_evening_restart_aligns_both_advance_slots(self):
        from datetime import date
        first = date(2026, 11, 8)
        self.assertEqual(advance_slots(datetime(2026, 11, 8, 21, 19, tzinfo=IST), first, 21), [])
        slots = advance_slots(datetime(2026, 11, 8, 21, 35, tzinfo=IST), first, 21)
        self.assertEqual([(d.isoformat(), s.strftime('%H:%M')) for d, s in slots],
                         [('2026-11-09', '21:20'), ('2026-11-10', '21:35'),
                          ('2026-11-11', '21:35')])
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
