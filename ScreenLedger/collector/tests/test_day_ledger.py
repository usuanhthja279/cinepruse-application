import csv
import sqlite3
import sys
from unittest.mock import patch, mock_open
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from day_ledger import day_ledger

class DayLedgerTests(unittest.TestCase):
    def setUp(self):
        self.cities={"mumbai":"Maharashtra","pune":"Maharashtra","lucknow":"Uttar Pradesh"}
        self.path=Path("ignored.csv")
        self.conn=sqlite3.connect(":memory:");self.conn.row_factory=sqlite3.Row
        self.conn.executescript("""CREATE TABLE captures(id INTEGER PRIMARY KEY,movie_id TEXT,status TEXT,service_date_ist TEXT,observed_at_utc TEXT);
        CREATE TABLE observations(capture_id INTEGER,movie_id TEXT,session_key TEXT,show_datetime_ist TEXT,cinema_id TEXT,cinema_name TEXT,total_seats INTEGER,available_seats INTEGER,unavailable_seats INTEGER,estimated_gross_inr REAL,pricing_complete INTEGER);""")
    def tearDown(self):self.conn.close()
    def test_latest_pre_show_across_all_captures_and_deduplication(self):
        self.conn.executemany("INSERT INTO captures VALUES(?,?,?,?,?)",[(1,"m","ok","2025-01-01","2025-01-01T06:00:00+00:00"),(2,"m","ok","2025-01-01","2025-01-01T07:00:00+00:00"),(3,"m","ok","2025-01-01","2025-01-01T09:00:00+00:00")])
        self.conn.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",[(1,"m","show","2025-01-01T14:00:00+05:30","1","Cinema, Mumbai",100,80,20,2000,1),(2,"m","show","2025-01-01T14:00:00+05:30","1","Cinema, Mumbai",100,60,40,4000,1),(3,"m","show","2025-01-01T14:00:00+05:30","1","Cinema, Mumbai",100,0,100,10000,1),(1,"m","other","2025-01-01T14:00:00+05:30","2","Cinema Mumbai",30,20,10,None,0)])
        with patch("day_ledger.load_locations",return_value={"1":{"state_or_ut":"Maharashtra","status":"address_and_boundary_agree"}}):
            result=day_ledger(self.conn,date(2025,1,1),"m")
        self.assertEqual(result["totals"]["unique_sessions"],2)
        self.assertEqual(result["totals"]["booked_plus_blocked_seats"],50)
        self.assertEqual(result["totals"]["confirmed_revenue_inr"],4000)
        self.assertEqual(result["totals"]["pricing_incomplete_sessions"],1)
        self.assertEqual(result["states"]["Maharashtra"]["booked_plus_blocked_seats"],40)
        self.assertEqual(result["unresolved"]["booked_plus_blocked_seats"],10)
    def test_conflicting_names_for_a_cinema_are_unassigned(self):
        self.conn.execute("INSERT INTO captures VALUES(?,?,?,?,?)",(1,"m","ok","2025-01-01","2025-01-01T06:00:00+00:00"))
        self.conn.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",[(1,"m","a","2025-01-01T14:00:00+05:30","same","Cinema, Mumbai",100,80,20,2000,1),(1,"m","b","2025-01-01T15:00:00+05:30","same","Cinema, Lucknow",100,80,20,2000,1)])
        with patch("day_ledger.load_locations",return_value={"same":{"state_or_ut":"","status":"needs_review"}}):
            result=day_ledger(self.conn,date(2025,1,1),"m")
        self.assertEqual(result["unresolved"]["unique_sessions"],2)
        self.assertEqual(result["cinema_mapping"][0]["status"],"needs_review")
        self.assertFalse(result["states"])

if __name__ == "__main__":unittest.main()
