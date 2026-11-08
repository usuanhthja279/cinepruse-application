import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smart_collector import (parse_local, pre_show_target, upcoming_pre_show_plan,
                             open_db, record_snapshot, due_final_jobs, last_hour_proxy,
                             prune_started_jobs, state_get, state_set, collect_all_languages, scan)

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
    def test_generic_landing_page_is_unresolved_not_an_empty_capture(self):
        args = SimpleNamespace(movie_slug='ramayana', movie_id='176276', city='ambikapur', date='2026-11-10')
        payload = {'props': {'pageProps': {'data': {'cityName':'', 'serverState': {
            'movieData': {'176276': {'movie': {'name':'Ramayana'}}},
            'queryState': {'frmtid':'','fromdate':''}}}}}}
        with patch('smart_collector.get_page_html', return_value='landing'), \
             patch('smart_collector.extract_next_data', return_value=payload):
            with self.assertRaisesRegex(ValueError, 'generic movie landing'):
                collect_all_languages(args)

    def test_capture_show_count_only_counts_requested_date(self):
        snap = fixture(show='2026-11-08T10:00:00+05:30')
        cid = record_snapshot(self.db, snap, parse_local('2026-11-07T00:00:00'), 'baseline', self.day)
        self.assertEqual(self.db.execute('SELECT show_count FROM captures WHERE id=?',(cid,)).fetchone()[0], 0)

    def test_all_language_pages_are_combined_and_wrong_format_fails(self):
        args = SimpleNamespace(movie_slug='ramayana', movie_id='176276', city='kolkata', date='2026-11-07')
        def payload(html):
            selected = 'tel' if html == 'default' else 'hin'
            state = {'queryState': {'frmtid': selected}, 'movieContents': {'176276': {
                'languageFormatGroups': [{'language':'Telugu','fmtGrpId':'tel'},
                                         {'language':'Hindi','fmtGrpId':'hin'}]}}}
            return {'props': {'pageProps': {'data': {'serverState': state}}}}
        def snapshot(html, **kwargs):
            result = fixture()
            result['shows'][0]['session_key'] = html
            result['shows'][0]['language'] = kwargs['language']
            return result
        with patch('smart_collector.get_page_html', side_effect=['default','other']) as fetch, \
             patch('smart_collector.extract_next_data', side_effect=payload), \
             patch('smart_collector.extract_snapshot', side_effect=snapshot):
            result = collect_all_languages(args)
            self.assertEqual({s['language'] for s in result['shows']}, {'Hindi','Telugu'})
            self.assertIn('frmtid=hin', fetch.call_args_list[1].args[0])
        with patch('smart_collector.get_page_html', side_effect=['default','default']), \
             patch('smart_collector.extract_next_data', side_effect=payload), \
             patch('smart_collector.extract_snapshot', side_effect=snapshot):
            with self.assertRaisesRegex(ValueError, 'unexpected language format'):
                collect_all_languages(args)

    def test_language_auditorium_and_screen_format_are_persisted(self):
        snap = fixture()
        snap['shows'][0].update(language='Hindi', auditorium='Screen 1', screen_format='4DX-3D', format_group_id='fmt')
        cid = record_snapshot(self.db, snap, parse_local('2026-11-07T00:00:00'), 'baseline', self.day)
        row = self.db.execute('SELECT language,auditorium,screen_format,format_group_id FROM observation_details WHERE capture_id=?', (cid,)).fetchone()
        self.assertEqual(tuple(row), ('Hindi','Screen 1','4DX-3D','fmt'))

    def test_failed_language_fetch_cannot_publish_partial_success(self):
        args = SimpleNamespace(acknowledge_permission=True, movie_slug='ramayana',
                               movie_id='176276', city='kolkata', date='2026-11-07', final_minutes=5)
        with patch('smart_collector.collect_all_languages', side_effect=ValueError('language format failed')):
            with self.assertRaisesRegex(ValueError, 'language format failed'):
                scan(self.db, args, parse_local('2026-11-07T00:00:00'), 'baseline', Path(self.temp.name))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM captures WHERE status='ok'").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM captures WHERE status='error'").fetchone()[0], 1)

    def test_existing_capture_database_is_migrated_for_service_date(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.sqlite'
            conn = sqlite3.connect(path)
            conn.execute('''CREATE TABLE captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT, movie_id TEXT NOT NULL, city TEXT NOT NULL,
                actual_city TEXT, observed_at_utc TEXT NOT NULL, reason TEXT NOT NULL,
                requested_at_utc TEXT, status TEXT NOT NULL, show_count INTEGER,
                raw_path TEXT, error TEXT)''')
            conn.commit()
            conn.close()
            migrated = open_db(path)
            columns = {row[1] for row in migrated.execute('PRAGMA table_info(captures)')}
            indexes = {row[1] for row in migrated.execute('PRAGMA index_list(captures)')}
            migrated.close()
        self.assertIn('service_date_ist', columns)
        self.assertIn('idx_captures_service_date', indexes)

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
        self.assertEqual(self.db.execute('SELECT DISTINCT service_date_ist FROM captures').fetchone()[0],
                         '2026-11-07')

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
