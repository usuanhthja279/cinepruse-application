import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smart_collector import (parse_local, pre_show_target, upcoming_pre_show_plan,
                             open_db, record_snapshot, due_final_jobs, last_hour_proxy,
                             prune_started_jobs, state_get, state_set)

IST = ZoneInfo('Asia/Kolkata')

def fixture(unavailable=40, at='2026-11-07T00:00:00+05:30',
            show='2026-11-07T00:35:00+05:30', city='kolkata'):
    return {
        'metadata': {'movie_id':'176276','source_city':city,'actual_city':city},
        'shows': [
            {'session_key':'screen-A-session-1','source_city':city,'show_datetime_ist':show,
             'cinema_id':'44','cinema_name':'Fixture Cinema','total_seats':100,
             'available_seats':100-unavailable,'unavailable_seats':unavailable,
             'estimated_gross_inr':unavailable*200.0,'pricing_complete':True}
        ],
        'areas':[],
    }

class SmartCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dbpath = Path(self.temp.name)/'snap.sqlite'
        self.db = open_db(self.dbpath)
        self.day = date(2026,11,7)
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_1235_show_gets_1230_scan(self):
        show = fixture()['shows'][0]
        self.assertEqual(pre_show_target(show),parse_local('2026-11-07T00:30:00'))
        plan=upcoming_pre_show_plan([show],self.day,parse_local('2026-11-07T00:00:00'))
        self.assertEqual(plan[0]['pre_show_scan_ist'],'2026-11-07T00:30:00+05:30')
        self.assertEqual(plan[0]['planning_status'],'future')

    def test_persist_before_and_after_pre_show_scan(self):
        first=fixture(40)
        record_snapshot(self.db, first,parse_local('2026-11-07T00:00:00'),'baseline',self.day)
        self.assertFalse(due_final_jobs(self.db,parse_local('2026-11-07T00:29:59'),'176276','kolkata'))
        self.assertEqual(len(due_final_jobs(self.db,parse_local('2026-11-07T00:30:00'),'176276','kolkata')),1)
        second=fixture(52)
        record_snapshot(self.db,second,parse_local('2026-11-07T00:30:02'),'pre_show',self.day)
        self.assertFalse(due_final_jobs(self.db,parse_local('2026-11-07T00:31:00'),'176276','kolkata'))
        self.assertEqual(self.db.execute('SELECT status FROM final_jobs').fetchone()['status'],'captured')
        self.assertEqual(self.db.execute('SELECT count(*) n FROM observations').fetchone()['n'],2)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM captures').fetchone()['n'],2)

    def test_late_discovery_not_fake_on_time_scan(self):
        record_snapshot(self.db,fixture(30),parse_local('2026-11-07T00:31:00'),'late_baseline',self.day)
        self.assertEqual(self.db.execute('SELECT status FROM final_jobs').fetchone()['status'],'late_discovery')

    def test_expired_show_missed_no_false_zero(self):
        record_snapshot(self.db,fixture(30),parse_local('2026-11-07T00:00:00'),'baseline',self.day)
        prune_started_jobs(self.db,parse_local('2026-11-07T00:35:01'))
        self.assertEqual(self.db.execute('SELECT status FROM final_jobs').fetchone()['status'],'missed')
        self.assertEqual(self.db.execute('SELECT count(*) n FROM observations').fetchone()['n'],1)

    def test_last_hour_net_change_not_sales(self):
        later='2026-11-07T02:00:00+05:30'
        record_snapshot(self.db,fixture(20,show=later),parse_local('2026-11-07T00:00:00'),'baseline',self.day)
        record_snapshot(self.db,fixture(33,show=later),parse_local('2026-11-07T01:00:00'),'hourly',self.day)
        delta=last_hour_proxy(self.db,'176276','kolkata',parse_local('2026-11-07T01:00:10'))
        self.assertEqual(delta['net_unavailable_seat_change'],13)
        self.assertEqual(delta['comparable_sessions'],1)
        self.assertIn('proxy',delta['label'])

    def test_redirect_not_counted(self):
        snapshot=fixture()
        snapshot['metadata']['actual_city']='mumbai'
        with self.assertRaises(ValueError):
            record_snapshot(self.db,snapshot,parse_local('2026-11-07T00:00:00'),'baseline',self.day)

    def test_resume_state_survives_reopening(self):
        state_set(self.db,'hourly:176276:kolkata:2026-11-07','2026-11-07T00:00:00+05:30')
        self.db.close()
        self.db=open_db(self.dbpath)
        self.assertEqual(state_get(self.db,'hourly:176276:kolkata:2026-11-07'),'2026-11-07T00:00:00+05:30')

    def test_other_dates_not_counted(self):
        record_snapshot(self.db,fixture(show='2026-11-08T00:35:00+05:30'),
                        parse_local('2026-11-07T00:00:00'),'baseline',self.day)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM observations').fetchone()['n'],0)

if __name__=='__main__': unittest.main()
