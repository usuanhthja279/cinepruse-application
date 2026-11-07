#!/usr/bin/env python3
"""Schedule-aware District snapshot collector. Permission-gated live fetch; offline planning.
No seat-layout calls, no anti-bot bypass, no claim that unavailable seats equal sold tickets.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from district_extractor import extract_snapshot, get_page_html, make_url, slugify_city

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
PRE_SHOW_MINUTES = 5

def parse_local(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)

def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("An aware datetime is required")
    return dt.astimezone(UTC).isoformat(timespec="seconds")

def show_start(show: dict) -> datetime | None:
    value = show.get("show_datetime_ist")
    return parse_local(value) if value else None

def pre_show_target(show: dict, minutes: int = PRE_SHOW_MINUTES) -> datetime | None:
    start = show_start(show)
    return start - timedelta(minutes=minutes) if start else None

def upcoming_pre_show_plan(shows: list[dict], target_date: date,
                           observed_at: datetime, minutes: int = PRE_SHOW_MINUTES) -> list[dict]:
    """Pure scheduler plan; excludes shows already started and other dates."""
    result = []
    for row in shows:
        start = show_start(row)
        if not start or start.date() != target_date or start <= observed_at.astimezone(IST):
            continue
        target = start - timedelta(minutes=minutes)
        result.append({
            "session_key": row["session_key"], "city": row.get("source_city"),
            "cinema": row.get("cinema_name"),
            "show_start_ist": start.isoformat(timespec="seconds"),
            "pre_show_scan_ist": target.isoformat(timespec="seconds"),
            "planning_status": ("future" if target > observed_at.astimezone(IST)
                                else "late_discovery"),
        })
    return sorted(result, key=lambda x: (x["pre_show_scan_ist"], x["session_key"]))

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id TEXT NOT NULL, city TEXT NOT NULL, actual_city TEXT,
    observed_at_utc TEXT NOT NULL, reason TEXT NOT NULL,
    requested_at_utc TEXT, status TEXT NOT NULL, show_count INTEGER,
    raw_path TEXT, error TEXT, service_date_ist TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    capture_id INTEGER NOT NULL REFERENCES captures(id),
    movie_id TEXT NOT NULL, city TEXT NOT NULL, session_key TEXT NOT NULL,
    show_datetime_ist TEXT NOT NULL, cinema_id TEXT, cinema_name TEXT,
    total_seats INTEGER, available_seats INTEGER, unavailable_seats INTEGER,
    estimated_gross_inr REAL, pricing_complete INTEGER,
    PRIMARY KEY(capture_id, session_key)
);
CREATE INDEX IF NOT EXISTS idx_observations_lookup ON observations(movie_id,city,session_key,capture_id);
CREATE INDEX IF NOT EXISTS idx_observations_service_day ON observations(movie_id,substr(show_datetime_ist,1,10),session_key,capture_id);

CREATE TABLE IF NOT EXISTS cinema_location_observations (
    capture_id INTEGER NOT NULL REFERENCES captures(id),
    cinema_id TEXT NOT NULL, cinema_name TEXT, address TEXT,
    latitude REAL, longitude REAL, source_url TEXT, observed_at_utc TEXT NOT NULL,
    PRIMARY KEY(capture_id,cinema_id,cinema_name,address,latitude,longitude)
);
CREATE INDEX IF NOT EXISTS idx_cinema_locations_id ON cinema_location_observations(cinema_id);

CREATE TABLE IF NOT EXISTS final_jobs (
    movie_id TEXT NOT NULL, city TEXT NOT NULL, session_key TEXT NOT NULL,
    show_datetime_ist TEXT NOT NULL, target_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', capture_id INTEGER,
    note TEXT,
    PRIMARY KEY(movie_id, city, session_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_due ON final_jobs(status,target_utc);
CREATE TABLE IF NOT EXISTS kv_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if "service_date_ist" not in {row[1] for row in conn.execute("PRAGMA table_info(captures)")}:
        try:
            conn.execute("ALTER TABLE captures ADD COLUMN service_date_ist TEXT")
        except sqlite3.OperationalError as exc:
            # Multiple scheduler workers can open the DB together during first migration.
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_service_date "
                 "ON captures(movie_id,service_date_ist,city,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_service_day "
                 "ON observations(movie_id,substr(show_datetime_ist,1,10),session_key,capture_id)")
    return conn

def state_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None

def state_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO kv_state(key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()

def location_coordinate(value, limit):
    try:
        number=float(value)
        return number if math.isfinite(number) and -limit<=number<=limit else None
    except (TypeError,ValueError,OverflowError):
        return None

def record_snapshot(conn: sqlite3.Connection, snapshot: dict, observed_at: datetime,
                    reason: str, target_date: date, raw_path: str | None = None,
                    requested_at: datetime | None = None, final_minutes: int = 5) -> int:
    """Persist observations/history, then schedule per-show pre-start readings."""
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must have a timezone")
    meta = snapshot["metadata"]
    requested = meta["source_city"]
    actual = meta["actual_city"]
    if actual != requested:
        raise ValueError(f"City redirect: requested {requested}, got {actual}. Do not count fallback.")
    shows = snapshot["shows"]
    with conn:
        cur = conn.execute(
            "INSERT INTO captures(movie_id,city,actual_city,observed_at_utc,reason,"
            "requested_at_utc,status,show_count,raw_path,service_date_ist) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(meta["movie_id"]),requested,actual,to_utc_iso(observed_at),reason,
             to_utc_iso(requested_at) if requested_at else None,"ok",len(shows),raw_path,target_date.isoformat()))
        capture_id = cur.lastrowid
        seen_cinemas = set()
        for show in shows:
            start = show_start(show)
            if not start or start.date() != target_date:
                continue
            key = show["session_key"]
            cinema_id = str(show.get("cinema_id") or "").strip()
            address=show.get("cinema_address")
            if address is not None and not isinstance(address,str):
                address=json.dumps(address,ensure_ascii=False,default=str)
            latitude=location_coordinate(show.get("latitude"),90)
            longitude=location_coordinate(show.get("longitude"),180)
            name=show.get("cinema_name") or ""
            if not isinstance(name,str):name=str(name)
            venue=(cinema_id,name,address,latitude,longitude)
            if cinema_id and venue not in seen_cinemas and (address or latitude is not None or longitude is not None):
                conn.execute("INSERT OR IGNORE INTO cinema_location_observations VALUES (?,?,?,?,?,?,?,?)",
                    (capture_id,cinema_id,name,address,latitude,longitude,meta.get("source_url"),to_utc_iso(observed_at)))
                seen_cinemas.add(venue)
            conn.execute(
                "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (capture_id,str(meta["movie_id"]),requested,key,
                 start.isoformat(timespec="seconds"),str(show.get("cinema_id") or ""),
                 show.get("cinema_name"),show.get("total_seats"),
                 show.get("available_seats"),show.get("unavailable_seats"),
                 show.get("estimated_gross_inr"),1 if show.get("pricing_complete") else 0))
            target = start - timedelta(minutes=final_minutes)
            if target > observed_at.astimezone(IST):
                status, note = "pending", None
            elif observed_at.astimezone(IST) < start:
                status, note = "late_discovery", "Pre-show threshold passed before show was discovered"
            else:
                status, note = "missed", "Show began before this scan; cannot infer final count"
            conn.execute(
                "INSERT OR IGNORE INTO final_jobs(movie_id,city,session_key,show_datetime_ist,"
                "target_utc,status,note) VALUES (?,?,?,?,?,?,?)",
                (str(meta["movie_id"]),requested,key,start.isoformat(timespec="seconds"),
                 to_utc_iso(target),status,note))
        # Mark due jobs captured only if matching show was actually seen before start time.
        # A previous hourly snapshot on the final threshold can satisfy the final job.
        for job in conn.execute(
            "SELECT session_key,show_datetime_ist FROM final_jobs "
            "WHERE movie_id=? AND city=? AND status='pending' AND target_utc<=?",
            (str(meta["movie_id"]),requested,to_utc_iso(observed_at))).fetchall():
            start = parse_local(job["show_datetime_ist"])
            found = conn.execute("SELECT 1 FROM observations WHERE capture_id=? AND session_key=?",
                                 (capture_id,job["session_key"])).fetchone()
            if observed_at.astimezone(IST) >= start:
                status, note = "missed", "Show started before final scan"
            elif found:
                status, note = "captured", "Observed after target and before show start"
            else:
                status, note = "not_visible", "Show absent from pre-show source page"
            conn.execute("UPDATE final_jobs SET status=?,capture_id=?,note=? "
                         "WHERE movie_id=? AND city=? AND session_key=?",
                         (status,capture_id,note,str(meta["movie_id"]),requested,job["session_key"]))
    return capture_id

def due_final_jobs(conn: sqlite3.Connection, now: datetime, movie_id: str,
                   city: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM final_jobs WHERE status='pending' AND movie_id=? AND city=? "
        "AND target_utc<=? ORDER BY target_utc",
        (str(movie_id),city,to_utc_iso(now))).fetchall()

def next_final_job(conn: sqlite3.Connection, movie_id: str, city: str) -> datetime | None:
    row = conn.execute(
        "SELECT MIN(target_utc) AS t FROM final_jobs "
        "WHERE status='pending' AND movie_id=? AND city=?", (str(movie_id),city)).fetchone()
    return datetime.fromisoformat(row["t"]) if row and row["t"] else None

def prune_started_jobs(conn: sqlite3.Connection, now: datetime) -> int:
    """Never call a disappearing/started show a successful pre-show scan."""
    with conn:
        rows = conn.execute(
            "SELECT movie_id,city,session_key,show_datetime_ist FROM final_jobs "
            "WHERE status='pending'").fetchall()
        expired = [r for r in rows if parse_local(r["show_datetime_ist"]) <= now.astimezone(IST)]
        for r in expired:
            conn.execute("UPDATE final_jobs SET status='missed',note='Show started before scheduled scan' "
                         "WHERE movie_id=? AND city=? AND session_key=?",
                         (r["movie_id"],r["city"],r["session_key"]))
    return len(expired)

def last_hour_proxy(conn: sqlite3.Connection, movie_id: str, city: str,
                    at: datetime, tolerance_minutes: int = 10) -> dict:
    """Last-hour net *unavailable seats* of comparable sessions. Never 'tickets sold'."""
    at_iso = to_utc_iso(at)
    latest = conn.execute(
        """SELECT o.*,c.observed_at_utc FROM observations o JOIN captures c ON c.id=o.capture_id
           WHERE o.movie_id=? AND o.city=? AND c.observed_at_utc<=?
           ORDER BY c.observed_at_utc DESC""", (str(movie_id),city,at_iso)).fetchall()
    by_session = {}
    for row in latest:
        by_session.setdefault(row["session_key"],row)
    net = 0
    matched = 0
    excluded = 0
    for key, current in by_session.items():
        start = parse_local(current["show_datetime_ist"])
        if start <= at.astimezone(IST):
            # Show has started; do not calculate 'current hour' using expired inventory.
            continue
        # Ignore stale present-day values: "current" must be sampled near requested at.
        if abs((at - datetime.fromisoformat(current["observed_at_utc"])).total_seconds()) > tolerance_minutes * 60:
            excluded += 1
            continue
        old = conn.execute(
            """SELECT o.*,c.observed_at_utc FROM observations o JOIN captures c ON c.id=o.capture_id
               WHERE o.movie_id=? AND o.city=? AND o.session_key=?
                 AND c.observed_at_utc BETWEEN ? AND ?
               ORDER BY c.observed_at_utc DESC LIMIT 1""",
            (str(movie_id),city,key,to_utc_iso(at-timedelta(minutes=60+tolerance_minutes)),
             to_utc_iso(at-timedelta(minutes=60-tolerance_minutes)))).fetchone()
        if not old or current["unavailable_seats"] is None or old["unavailable_seats"] is None \
           or current["total_seats"] != old["total_seats"]:
            excluded += 1
            continue
        matched += 1
        net += current["unavailable_seats"] - old["unavailable_seats"]
    return {"net_unavailable_seat_change":net if matched else None,
            "comparable_sessions":matched,"excluded_sessions":excluded,
            "label":"Net change in unavailable seats (proxy; may include holds/blocks)"}

def log_error(conn: sqlite3.Connection, movie_id: str, city: str,
              now: datetime, reason: str, msg: str, service_date: str | None = None) -> None:
    with conn:
        conn.execute("INSERT INTO captures(movie_id,city,observed_at_utc,reason,status,error,service_date_ist) "
                     "VALUES(?,?,?,?,?,?,?)", (movie_id,city,to_utc_iso(now),reason,"error",msg,service_date))

def scan(conn: sqlite3.Connection, args, now: datetime, reason: str, store: Path) -> int:
    if not args.acknowledge_permission:
        raise RuntimeError("Live mode requires --acknowledge-permission; it does not grant provider permission")
    url = make_url(args.movie_slug,args.movie_id,args.city,args.date)
    print(f"[{now.astimezone(IST).isoformat(timespec='seconds')}] {reason} scan: {args.city}", flush=True)
    try:
        html = get_page_html(url)
        at = datetime.now(UTC)
        parsed = extract_snapshot(html,source_url=url,source_city=args.city,
                                  expected_movie_id=str(args.movie_id),
                                  snapshot_utc=to_utc_iso(at))
        cid = record_snapshot(conn,parsed,at,reason,date.fromisoformat(args.date),
                              requested_at=now,
                              final_minutes=args.final_minutes)
        print(f"  capture #{cid}: {len(parsed['shows'])} source show rows, "
              f"{len([s for s in parsed['shows'] if s['show_date_ist']==args.date])} target-date shows",flush=True)
        return cid
    except Exception as exc:
        log_error(conn,str(args.movie_id),args.city,datetime.now(UTC),reason,str(exc),args.date)
        raise

def run_loop(args) -> int:
    if not args.acknowledge_permission:
        raise RuntimeError("Live collection must be explicitly permission-gated")
    target_date=date.fromisoformat(args.date)
    start=datetime.combine(target_date,datetime.min.time(),IST)
    end=start+timedelta(days=1)
    db=open_db(Path(args.store)/"smart_collector.sqlite")
    state_key=f"hourly:{args.movie_id}:{args.city}:{args.date}"
    try:
        print(f"Collector ARMED for {args.movie_slug}/{args.city} on {args.date} IST; "
              f"starts {start.isoformat()}, ends {end.isoformat()}. Ctrl+C to stop.",flush=True)
        while True:
            now=datetime.now(IST)
            if now < start:
                time.sleep(min(args.poll_seconds,max(0.1,(start-now).total_seconds())))
                continue
            if now >= end:
                print("Target day ended; exiting.",flush=True)
                return 0
            prune_started_jobs(db,now)
            # Critical priority: pre-show jobs supersede hourly work for the same page.
            due=due_final_jobs(db,now,str(args.movie_id),args.city)
            last=state_get(db,state_key)
            hour_slot=now.replace(minute=0,second=0,microsecond=0)
            pending_hourly = last is None or parse_local(last) < hour_slot
            reason="pre_show" if due else ("baseline" if last is None and now.minute==0
                                           else "catch_up" if last is None else "hourly")
            if due or pending_hourly:
                try:
                    scan(db,args,now,reason,Path(args.store))
                except Exception as exc:
                    print(f"Capture FAILED: {exc}",file=sys.stderr,flush=True)
                    if "403" in str(exc) or "429" in str(exc):
                        print("Provider restricted access: halting without retry.",file=sys.stderr)
                        return 2
                    # Retry later on a fresh poll; not rapid-fire retry.
                    time.sleep(max(args.retry_seconds,args.poll_seconds))
                    continue
                if pending_hourly:
                    state_set(db,state_key,hour_slot.isoformat())
                if args.once:
                    return 0
                continue
            next_hour=hour_slot+timedelta(hours=1)
            next_final=next_final_job(db,str(args.movie_id),args.city)
            wake=next_hour if next_final is None else min(next_hour,next_final.astimezone(IST))
            seconds=max(0.1,(wake-now).total_seconds())
            time.sleep(min(args.poll_seconds,seconds))
    except KeyboardInterrupt:
        print("Interrupted; persisted data remains.",flush=True)
        return 130
    finally:
        db.close()

def main() -> int:
    p=argparse.ArgumentParser(description="Schedule-aware offline plan / permission-gated District collector")
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-fixture",type=Path,help="Make an offline showtime scan plan, no network")
    mode.add_argument("--live-authorized",action="store_true",
                      help="Run live only with provider approval and --acknowledge-permission")
    p.add_argument("--date",required=True,help="Target IST service date, YYYY-MM-DD")
    p.add_argument("--movie-id",default="176276")
    p.add_argument("--movie-slug",default="ramayana")
    p.add_argument("--city",default="kolkata")
    p.add_argument("--observed-at",help="Offline fixture capture timestamp (ISO, local IST by default)")
    p.add_argument("--final-minutes",type=int,default=5)
    p.add_argument("--poll-seconds",type=float,default=5.0)
    p.add_argument("--retry-seconds",type=float,default=120.0)
    p.add_argument("--store",type=Path,default=Path("collector_data"))
    p.add_argument("--acknowledge-permission",action="store_true")
    p.add_argument("--once",action="store_true",help="Take one authorized capture, persist it, and exit")
    args=p.parse_args()
    date.fromisoformat(args.date)
    if args.final_minutes<1 or args.final_minutes>30: p.error("--final-minutes must be 1..30")
    if args.poll_seconds<1 or args.retry_seconds<30: p.error("Poll >=1s; retry delay >=30s")
    args.city=slugify_city(args.city)
    if args.plan_fixture:
        captured=parse_local(args.observed_at) if args.observed_at else datetime.now(IST)
        snapshot=extract_snapshot(args.plan_fixture.read_text(encoding="utf-8"),
                                  source_city=args.city,expected_movie_id=str(args.movie_id),
                                  snapshot_utc=to_utc_iso(captured))
        jobs=upcoming_pre_show_plan(snapshot["shows"],date.fromisoformat(args.date),
                                   captured,args.final_minutes)
        print(json.dumps({"mode":"OFFLINE_FIXTURE_ONLY","target_date_ist":args.date,
                          "baseline_at_ist":captured.isoformat(),"target_shows":len(jobs),
                          "pre_show_jobs":jobs},indent=2,ensure_ascii=False))
        return 0
    if not args.acknowledge_permission:
        p.error("Live mode needs --acknowledge-permission; that flag does not confer access rights")
    return run_loop(args)

if __name__=="__main__":
    raise SystemExit(main())
