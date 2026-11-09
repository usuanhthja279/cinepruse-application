#!/usr/bin/env python3
"""District all-city scheduler with hourly sweep and reserved pre-show worker.

City display labels are converted to URL slugs using the known project aliases;
redirects/city mismatches are rejected by the existing collector validation.
Four workers service the hourly sweep and one is reserved for T-5 scans.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import requests

from district_extractor import slugify_city
from smart_collector import IST, UTC, open_db, parse_local, scan, state_get, state_set


def advance_slots(now: datetime, first_day: date,
                  first_day_hour: int = 0) -> list[tuple[date, datetime]]:
    """Return the latest due advance slot for each of the next three service dates."""
    now = now.astimezone(IST)
    result = []
    for offset, interval, minute in ((1, 2, 20), (2, 3, 35), (3, 3, 35)):
        first_hour = first_day_hour if now.date() == first_day else 0
        first = now.replace(hour=first_hour, minute=minute, second=0, microsecond=0)
        if now < first:
            continue
        elapsed = int((now - first).total_seconds() // (interval * 3600))
        result.append((now.date() + timedelta(days=offset), first + timedelta(hours=interval * elapsed)))
    return result


def round_robin_advance_targets(
        schedules: list[tuple[date, datetime, list[dict]]]):
    """Yield one city per due service date per pass to prevent date starvation."""
    active = [(service_day, slot, iter(targets))
              for service_day, slot, targets in schedules]
    while active:
        next_active = []
        for service_day, slot, targets in active:
            try:
                target = next(targets)
            except StopIteration:
                continue
            yield service_day, slot, target
            next_active.append((service_day, slot, targets))
        active = next_active


def urgent_worker_limit(due_city_count: int, pool_size: int = 5) -> int:
    """Borrow idle pool capacity for due pre-show bursts; never grow the pool."""
    if due_city_count <= 0:
        return 0
    return min(max(1, pool_size), due_city_count)


def classify_failure(exc: Exception) -> tuple[bool, str]:
    """Return whether a failure is plausibly transient and a stable category."""
    if isinstance(exc, requests.Timeout):
        return True, "timeout"
    if isinstance(exc, requests.ConnectionError):
        return True, "connection_error"
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = response.status_code if response is not None else None
        if status in (408, 425) or (status is not None and 500 <= status < 600):
            return True, f"http_{status}"
        return False, f"http_{status or 'unknown'}"
    message = str(exc).lower()
    if 'generic movie landing without city or show listings' in message:
        return True, 'generic_movie_landing'
    if 'did not provide language format identifiers' in message:
        return True, 'incomplete_language_metadata'
    if "no movie metadata found" in message:
        return False, "unrecognized_page"
    if "city redirect" in message:
        return False, "city_mismatch"
    if "404" in message:
        return False, "http_404"
    return False, "non_retryable"


def emit_retry_summary(counts: dict[str, int], categories: dict[str, int], *, final: bool = False) -> None:
    label = "Final retry outcome summary" if final else "Retry outcome summary"
    detail = ", ".join(f"{name}={count}" for name, count in sorted(categories.items())) or "none"
    print(f"{label}: scheduled={counts['scheduled']}, recovered={counts['recovered']}, "
          f"exhausted={counts['exhausted']}, permanent_failures={counts['permanent']}; "
          f"failure_types: {detail}", flush=True)


def fail_due_pre_show_jobs(db, movie_id: str, city: str, now: datetime,
                           category: str, *, exhausted: bool = False) -> int:
    reason = "exhausted retries" if exhausted else "permanent source error"
    with db:
        cur = db.execute(
            "UPDATE final_jobs SET status='failed',note=? "
            "WHERE movie_id=? AND city=? AND status='pending' AND target_utc<=?",
            (f"Pre-show scan {reason}: {category}", str(movie_id), city,
             now.astimezone(UTC).isoformat()),
        )
    return cur.rowcount


def expire_stale_pre_show_jobs(db, movie_id: str, service_day: date, now: datetime) -> int:
    """Do not let old T-5 jobs crowd out the current hourly sweep."""
    cutoff = (now - timedelta(minutes=10)).astimezone(UTC).isoformat()
    previous_timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]
    db.execute("PRAGMA busy_timeout=1000")
    try:
        with db:
            cur = db.execute(
                "UPDATE final_jobs SET status='failed',note='Missed T-5 capture window' "
                "WHERE movie_id=? AND status='pending' AND substr(show_datetime_ist,1,10)=? "
                "AND target_utc<?",
                (str(movie_id), service_day.isoformat(), cutoff),
            )
        return cur.rowcount
    finally:
        db.execute(f"PRAGMA busy_timeout={int(previous_timeout)}")


def due_pre_show_cities(db, movie_id: str, service_day: date, now: datetime):
    return db.execute("""SELECT city, MIN(target_utc) AS earliest_due FROM final_jobs
        WHERE movie_id=? AND status='pending' AND target_utc<=? AND substr(show_datetime_ist,1,10)=?
        GROUP BY city ORDER BY earliest_due, city""",
        (str(movie_id), now.astimezone(UTC).isoformat(), service_day.isoformat())).fetchall()


def baseline_key(movie_id: str, target_date: date, city: str) -> str:
    return f"multi_baseline:{movie_id}:{target_date}:{city}"


def start_discovery_epoch(db, movie_id: str, target_date: date, now: datetime) -> tuple[str, set[date]]:
    """Start a new full-city pass without changing capture or pre-show history."""
    movie_id = str(movie_id)
    day = target_date.isoformat()
    future_days = {target_date + timedelta(days=n) for n in (1, 2, 3)}
    started_at = now.astimezone(UTC).isoformat(timespec='seconds')
    with db:
        for prefix in ('multi_baseline', 'multi_hourly', 'multi_retry', 'multi_retry_count'):
            key_prefix = f'{prefix}:{movie_id}:{day}:'
            db.execute('DELETE FROM kv_state WHERE substr(key,1,?)=?', (len(key_prefix), key_prefix))
        db.execute('DELETE FROM kv_state WHERE key=?', (f'multi_initial_complete:{movie_id}:{day}',))
        for future in future_days:
            for prefix in ('multi_advance', 'multi_advance_complete'):
                key_prefix = f'{prefix}:{movie_id}:{future.isoformat()}:'
                db.execute('DELETE FROM kv_state WHERE substr(key,1,?)=?', (len(key_prefix), key_prefix))
        db.execute('INSERT INTO kv_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (f'multi_city_started:{movie_id}:{day}', started_at))
    return started_at, future_days


def refresh_baseline_statuses(db, targets: list[dict], movie_id: str,
                              target_date: date, started_at: str) -> None:
    """Resume initial discovery from captures saved by this run, including older runner versions."""
    for target in targets:
        city = target["slug"]
        key = baseline_key(movie_id, target_date, city)
        if state_get(db, key):
            continue
        rows = db.execute("""SELECT status FROM captures WHERE movie_id=? AND city=?
            AND observed_at_utc>=? AND reason IN ('baseline','retry')""",
                          (str(movie_id), city, started_at)).fetchall()
        if rows:
            status = "ok" if any(row["status"] == "ok" for row in rows) else "failed"
            state_set(db, key, status)


def write_verified_roster(store: Path, targets: list[dict], movie_id: str,
                          target_date: date, db, observed_since: str | None = None) -> dict:
    latest_with_listings={row["city"] for row in db.execute("""SELECT c.city FROM captures c
        JOIN (SELECT city,MAX(id) id FROM captures WHERE movie_id=? AND service_date_ist=?
              AND status='ok' AND (? IS NULL OR observed_at_utc>=?) GROUP BY city) latest ON latest.id=c.id
        WHERE c.show_count>0""",(str(movie_id),target_date.isoformat(), observed_since, observed_since)).fetchall()}
    verified = [target for target in targets if target["slug"] in latest_with_listings]
    report = {"service_date": target_date.isoformat(), "movie_id": str(movie_id),
              "verified_city_count": len(verified), "initial_target_count": len(targets),
              "source_completeness_verified": False,
              "note": "Only cities whose latest successful service-date capture listed shows are included. "
                      "This is an operational allowlist, not proof the selector roster is complete.",
              "cities": verified}
    path = store / "city_targets_verified.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def advance_roster_path(store: Path, movie_id: str, service_day: date) -> Path:
    return store / f"city_targets_advance_{movie_id}_{service_day.isoformat()}.json"


def load_advance_targets(store: Path, movie_id: str, service_day: date,
                         all_targets: list[dict]) -> list[dict]:
    """Use all selector cities until the first advance sweep is complete."""
    path=advance_roster_path(store,movie_id,service_day)
    if not path.exists():return all_targets
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
        return payload.get("cities",[])
    except (OSError,ValueError,TypeError):
        return all_targets


def advance_targets_for_epoch(store: Path, movie_id: str, service_day: date,
                              all_targets: list[dict], needs_full: set[date]) -> list[dict]:
    return all_targets if service_day in needs_full else load_advance_targets(store, movie_id, service_day, all_targets)


def write_advance_roster(store: Path, db, targets: list[dict], movie_id: str,
                         service_day: date, slot: datetime, observed_since: str | None = None) -> dict:
    rows=db.execute("""SELECT city,show_count FROM (
        SELECT city,show_count,ROW_NUMBER() OVER(PARTITION BY city ORDER BY id DESC) rn
        FROM captures WHERE movie_id=? AND service_date_ist=? AND reason='advance' AND status='ok'
          AND (? IS NULL OR observed_at_utc>=?)
        ) WHERE rn=1 AND show_count>0""",(str(movie_id),service_day.isoformat(),observed_since,observed_since)).fetchall()
    present={row["city"] for row in rows}
    cities=[target for target in targets if target["slug"] in present]
    payload={"movie_id":str(movie_id),"service_date":service_day.isoformat(),
             "initial_slot_ist":slot.isoformat(),"initial_target_count":len(targets),
             "cities_with_listings":len(cities),"cities":cities}
    advance_roster_path(store,movie_id,service_day).write_text(
        json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    return payload


class Tee:
    def __init__(self, *streams):
        self.streams = streams
        self.lock = threading.Lock()

    def write(self, value):
        with self.lock:
            for stream in self.streams:
                stream.write(value)
                stream.flush()
        return len(value)

    def flush(self):
        with self.lock:
            for stream in self.streams:
                stream.flush()


def city_targets(path: Path) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = [name for letter in data["letters"].values() for name in letter["cities"]]
    seen = {}
    targets = []
    duplicates = 0
    for label in labels:
        slug = slugify_city(label)
        if not slug:
            duplicates += 1
            continue
        if slug in seen:
            seen[slug].setdefault('aliases', []).append(label)
            duplicates += 1
            continue
        target = {"display_name": label, "slug": slug,
                        "slug_confidence": "verified_sample" if slug in {
                            "mumbai", "delhi-ncr", "bengaluru", "hyderabad", "chennai",
                            "pune", "kolkata", "ahmedabad", "jaipur", "lucknow", "bhilai", "baghapurana", "bodi", "chikkaballapura"}
                        else "inferred_from_selector_label"}
        seen[slug] = target
        targets.append(target)
    report = {"selector_entries": len(labels), "unique_request_slugs": len(targets),
              "repeated_labels_or_aliases_collapsed": duplicates,
              "source_completeness_verified": False,
              "slug_note": "Only sampled city slugs were live-verified. Other URL slugs are normalized from selector display labels; city mismatches are rejected.",
              "cities": targets}
    return targets, report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cities", type=Path, required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--movie-id", default="176276")
    p.add_argument("--movie-slug", default="ramayana")
    p.add_argument("--start-at", help="Delay this launch until the given IST datetime")
    p.add_argument("--first-day-hour", type=int, default=0,
                   help="IST hour anchoring today's advance :20 and :35 cycles")
    p.add_argument("--store", type=Path, default=Path("collector_data"))
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--retry-seconds", type=int, default=30)
    p.add_argument("--max-retries", type=int, default=1,
                   help="Maximum retries per city between successful hourly captures")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--acknowledge-permission", action="store_true")
    args = p.parse_args()
    target_date = date.fromisoformat(args.date)
    first_day = target_date
    if args.workers != 5:
        p.error("This run reserves four hourly workers and one pre-show worker; workers must be 5")
    targets, report = city_targets(args.cities)
    if args.plan_only:
        print(json.dumps({k: v for k, v in report.items() if k != "cities"}, indent=2))
        print("Sample targets:", json.dumps(targets[:12], ensure_ascii=False))
        return 0
    if not args.acknowledge_permission:
        p.error("Live mode requires provider authorization and --acknowledge-permission")

    args.store.mkdir(parents=True, exist_ok=True)
    (args.store / "city_targets.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logs_dir = args.store / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"multi_city_{target_date.isoformat()}.log"
    log_file = log_path.open("a", encoding="utf-8", buffering=1)
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee(original_out, log_file), Tee(original_err, log_file)
    db = open_db(args.store / "smart_collector.sqlite")
    start = parse_local(args.start_at) if args.start_at else datetime.combine(target_date, datetime.min.time(), IST)
    if not 0 <= args.first_day_hour <= 23:
        p.error("--first-day-hour must be from 0 to 23")
    end = start + timedelta(days=1)
    run_started_at, advance_needs_full = start_discovery_epoch(db, args.movie_id, target_date, datetime.now(UTC))
    announced_advance_days = set()
    print(f"MULTI-CITY COLLECTOR: {len(targets)} unique URL slugs, {args.movie_slug}/{args.movie_id}, "
          f"service date {target_date} IST; four hourly workers plus one reserved T-5 worker.", flush=True)
    print(f"Coverage caveat: {report['slug_note']}", flush=True)
    print(f"Data store: {args.store.resolve()}; parsed captures only (raw pages are not retained); live log: {log_path.resolve()}", flush=True)
    print(f"FULL-CITY DISCOVERY ARMED: {target_date}, {len(targets)} live targets; "
          "each advance date also starts with the full target list", flush=True)

    running: dict[concurrent.futures.Future, tuple[str, str]] = {}
    busy_final_cities: set[str] = set()
    failure = threading.Event()
    retry_counts = {"scheduled": 0, "recovered": 0, "exhausted": 0, "permanent": 0}
    retry_categories: dict[str, int] = {}
    last_retry_summary = time.monotonic()
    dashboard_dirty = False
    last_dashboard_publish = 0.0
    scheduler_db_seconds = 0.0
    scheduler_db_samples = 0
    last_scheduler_metrics = time.monotonic()
    last_db_lock_warning = 0.0
    dashboard_process = None
    dashboard_output = None
    verified_report = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix="district") as pool:
        try:
            while datetime.now(IST) < start:
                time.sleep(min(1, (start - datetime.now(IST)).total_seconds()))
            while True:
                now = datetime.now(IST)
                if now.date() != target_date and not running:
                    target_date = now.date()
                    run_started_at, advance_needs_full = start_discovery_epoch(db, args.movie_id, target_date, datetime.now(UTC))
                    announced_advance_days.clear()
                    verified_report = None
                    print(f"NEW DAILY FULL-CITY DISCOVERY: {target_date}, {len(targets)} targets", flush=True)
                rollover_pending = now.date() != target_date
                initial_complete_key = f"multi_initial_complete:{args.movie_id}:{target_date}"
                initial_complete = state_get(db, initial_complete_key) == "1"
                if not initial_complete and all(
                    state_get(db, baseline_key(args.movie_id, target_date, t["slug"])) in {"ok", "failed"}
                    for t in targets
                ):
                    state_set(db, initial_complete_key, "1")
                    verified_report = write_verified_roster(args.store, targets, args.movie_id,
                                                             target_date, db, run_started_at)
                    initial_complete = True
                    print(f"INITIAL CITY SWEEP COMPLETE: {verified_report['verified_city_count']} of "
                          f"{verified_report['initial_target_count']} targets returned valid data; "
                          f"hourly scans will now use only the saved verified roster.", flush=True)
                active_targets = targets
                if initial_complete:
                    if verified_report is None:
                        verified_report = write_verified_roster(args.store, targets, args.movie_id,
                                                                 target_date, db, run_started_at)
                    active_targets = verified_report["cities"]
                # Rebuild the roster once per completed batch, rather than once per city.
                roster_dirty = False
                # Completed jobs update hourly state; exceptions are logged by scan().
                for future in list(running):
                    if not future.done():
                        continue
                    city, reason = running.pop(future)
                    if reason.startswith("advance|"):
                        _, service_day, slot_text = reason.split("|", 2)
                        key = f"multi_advance:{args.movie_id}:{service_day}:{city}"
                        retry_key = f"{key}:retry"
                        try:
                            future.result()
                            state_set(db, key, slot_text)
                            db.execute("DELETE FROM kv_state WHERE key=?", (retry_key,))
                            db.commit()
                            print(f"Advance capture completed: {city}, {service_day}, slot {slot_text}", flush=True)
                        except Exception as exc:
                            retryable, category = classify_failure(exc)
                            if retryable and not state_get(db, retry_key):
                                state_set(db, retry_key, (now + timedelta(seconds=args.retry_seconds)).isoformat())
                            else:
                                state_set(db, key, slot_text)
                                db.execute("DELETE FROM kv_state WHERE key=?", (retry_key,))
                                db.commit()
                            print(f"Advance capture failed: {city}, {service_day} [{category}]: {exc}", file=sys.stderr, flush=True)
                        continue
                    if reason != "pre_show":
                        dashboard_dirty = True
                    if reason == "pre_show":
                        busy_final_cities.discard(city)
                    try:
                        future.result()
                        if reason in ("baseline", "retry") and state_get(
                            db, f"multi_initial_complete:{args.movie_id}:{target_date}") != "1":
                            state_set(db, baseline_key(args.movie_id, target_date, city), "ok")
                        if reason != "pre_show":
                            slot = datetime.now(IST).replace(minute=0, second=0, microsecond=0)
                            state_set(db, f"multi_hourly:{args.movie_id}:{target_date}:{city}", slot.isoformat())
                            if state_get(db,f"multi_initial_complete:{args.movie_id}:{target_date}")=="1":
                                roster_dirty = True
                        retry_prefix = "multi_final_retry" if reason == "pre_show" else "multi_retry"
                        retry_key = f"{retry_prefix}:{args.movie_id}:{target_date}:{city}"
                        retry_count_key = f"{retry_prefix}_count:{args.movie_id}:{target_date}:{city}"
                        if state_get(db, retry_key):
                            if reason == "retry":
                                retry_counts["recovered"] += 1
                                print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] RETRY RECOVERED: {city}", flush=True)
                            db.execute("DELETE FROM kv_state WHERE key IN (?,?)", (retry_key, retry_count_key))
                            db.commit()
                        print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] completed {reason}: {city}", flush=True)
                    except Exception as exc:
                        retryable, category = classify_failure(exc)
                        retry_categories[category] = retry_categories.get(category, 0) + 1
                        retry_prefix = "multi_final_retry" if reason == "pre_show" else "multi_retry"
                        retry_key = f"{retry_prefix}:{args.movie_id}:{target_date}:{city}"
                        retry_count_key = f"{retry_prefix}_count:{args.movie_id}:{target_date}:{city}"
                        attempts = int(state_get(db, retry_count_key) or 0)
                        if retryable and attempts < args.max_retries:
                            attempts += 1
                            retry_counts["scheduled"] += 1
                            state_set(db, retry_count_key, str(attempts))
                            state_set(db, retry_key,
                                      (datetime.now(IST) + timedelta(seconds=args.retry_seconds)).isoformat())
                            disposition = f"retry {attempts}/{args.max_retries} in {args.retry_seconds}s"
                        elif retryable:
                            retry_counts["exhausted"] += 1
                            disposition = "retry limit reached; waiting for next hourly cycle"
                            if reason != "pre_show":
                                state_set(db, f"multi_hourly:{args.movie_id}:{target_date}:{city}",
                                          now.replace(minute=0, second=0, microsecond=0).isoformat())
                            db.execute("DELETE FROM kv_state WHERE key IN (?,?)", (retry_key, retry_count_key))
                            db.commit()
                            if reason == "pre_show":
                                fail_due_pre_show_jobs(db, args.movie_id, city, now, category,
                                                       exhausted=True)
                            if reason in ("baseline", "retry") and state_get(
                                db, f"multi_initial_complete:{args.movie_id}:{target_date}") != "1":
                                state_set(db, baseline_key(args.movie_id, target_date, city), "failed")
                        else:
                            retry_counts["permanent"] += 1
                            disposition = "not retryable; check city slug or source response"
                            if reason != "pre_show":
                                state_set(db, f"multi_hourly:{args.movie_id}:{target_date}:{city}",
                                          now.replace(minute=0, second=0, microsecond=0).isoformat())
                            db.execute("DELETE FROM kv_state WHERE key IN (?,?)", (retry_key, retry_count_key))
                            db.commit()
                            if reason == "pre_show":
                                fail_due_pre_show_jobs(db, args.movie_id, city, now, category)
                            if reason in ("baseline", "retry") and state_get(
                                db, f"multi_initial_complete:{args.movie_id}:{target_date}") != "1":
                                state_set(db, baseline_key(args.movie_id, target_date, city), "failed")
                        print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] FAILED {reason}: {city} "
                              f"[{category}; {disposition}]: {exc}", file=sys.stderr, flush=True)
                        if "403" in str(exc) or "429" in str(exc):
                            failure.set()

                if roster_dirty:
                    metric_start = time.perf_counter()
                    verified_report = write_verified_roster(args.store, targets, args.movie_id, target_date, db, run_started_at)
                    scheduler_db_seconds += time.perf_counter() - metric_start
                    scheduler_db_samples += 1

                if failure.is_set():
                    print("District access restriction detected; stopping all new requests.", file=sys.stderr, flush=True)
                    break

                if rollover_pending:
                    time.sleep(1)
                    continue

                # After the first full scan for each future service date, retain
                # only cities whose successful response actually listed shows.
                for service_day, advance_slot in advance_slots(now, first_day, args.first_day_hour):
                    if service_day in advance_needs_full and service_day not in announced_advance_days:
                        print(f"ADVANCE FULL-CITY SWEEP DUE: {service_day}, {len(targets)} targets, "
                              f"slot {advance_slot.isoformat()}", flush=True)
                        announced_advance_days.add(service_day)
                    complete_key = (f"multi_advance_complete:{args.movie_id}:"
                                    f"{service_day}:{advance_slot.isoformat()}")
                    if state_get(db, complete_key) == "1":
                        continue
                    roster_path=advance_roster_path(args.store,args.movie_id,service_day)
                    cycle_targets=advance_targets_for_epoch(args.store,args.movie_id,service_day,targets,advance_needs_full)
                    cycle_done=all(
                        (last:=state_get(db,f"multi_advance:{args.movie_id}:{service_day}:{target['slug']}"))
                        and parse_local(last)>=advance_slot for target in cycle_targets)
                    if cycle_done:
                        roster=write_advance_roster(args.store,db,cycle_targets,args.movie_id,service_day,advance_slot,run_started_at)
                        state_set(db, complete_key, "1")
                        advance_needs_full.discard(service_day)
                        print(f"ADVANCE SWEEP COMPLETE: {roster['cities_with_listings']} of "
                              f"{roster['initial_target_count']} current targets have listings for {service_day}; "
                              "later scans use the refreshed service-date roster.",flush=True)

                # Due pre-show scans have priority. A single city uses one worker;
                # simultaneous cities borrow idle pool slots up to the fixed pool
                # ceiling. Routine sweeps pause until the urgent backlog drains.
                metric_start = time.perf_counter()
                try:
                    expired = expire_stale_pre_show_jobs(db, args.movie_id, target_date, now)
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                        raise
                    expired = 0
                    if time.monotonic() - last_db_lock_warning >= 30:
                        print(f"SQLite busy during stale-job cleanup; deferring cleanup while scans continue: {exc}",
                              file=sys.stderr, flush=True)
                        last_db_lock_warning = time.monotonic()
                if expired:
                    print(f"[{now.isoformat(timespec='seconds')}] Expired {expired} stale T-5 jobs", flush=True)
                due_rows = due_pre_show_cities(db, args.movie_id, target_date, now)
                scheduler_db_seconds += time.perf_counter() - metric_start
                scheduler_db_samples += 1
                eligible_due = []
                due_by_city = {}
                for row in due_rows:
                    city = row["city"]
                    final_retry_key = f"multi_final_retry:{args.movie_id}:{target_date}:{city}"
                    final_retry_at = state_get(db, final_retry_key)
                    if final_retry_at and parse_local(final_retry_at) > now:
                        continue
                    if city in busy_final_cities:
                        continue
                    eligible_due.append(city)
                    due_by_city[city] = row["earliest_due"]
                pre_show_active = sum(r == "pre_show" for _, r in running.values())
                urgent_limit = urgent_worker_limit(len(eligible_due), pool_size=5)
                slots_available = max(0, 5 - len(running))
                pre_show_to_start = min(max(0, urgent_limit - pre_show_active), slots_available)
                for city in eligible_due[:pre_show_to_start]:
                    worker_values = vars(args).copy()
                    worker_values.update(city=city, date=target_date.isoformat(),
                                         acknowledge_permission=True, final_minutes=5)
                    worker_args = SimpleNamespace(**worker_values)
                    f = pool.submit(_scan_new_connection, worker_args, "pre_show", args.store)
                    running[f] = (city, "pre_show")
                    busy_final_cities.add(city)
                    delay = max(0.0, (datetime.now(UTC) - parse_local(due_by_city[city])).total_seconds())
                    print(f"[{now.isoformat(timespec='seconds')}] PRIORITY T-5 scan queued: {city} "
                          f"due={due_by_city[city]} delay_seconds={delay:.1f}", flush=True)

                # Refill at most four hourly slots. Each city is due once per local hour.
                hourly_active = sum(reason != "pre_show" for _, reason in running.values())
                urgent_backlog = bool(eligible_due) or pre_show_active > 0
                if hourly_active < 4 and not urgent_backlog:
                    slot = now.replace(minute=0, second=0, microsecond=0)
                    for target in active_targets:
                        city = target["slug"]
                        retry_key = f"multi_retry:{args.movie_id}:{target_date}:{city}"
                        retry_at = state_get(db, f"multi_retry:{args.movie_id}:{target_date}:{city}")
                        if retry_at and parse_local(retry_at) > now:
                            continue
                        if not initial_complete and state_get(
                            db, baseline_key(args.movie_id, target_date, city)) in {"ok", "failed"}:
                            continue
                        last = state_get(db, f"multi_hourly:{args.movie_id}:{target_date}:{city}")
                        if last and parse_local(last) >= slot:
                            continue
                        if any(c == city and r != "pre_show" for c, r in running.values()):
                            continue
                        worker_values = vars(args).copy()
                        worker_values.update(city=city, date=target_date.isoformat(),
                                             acknowledge_permission=True, final_minutes=5)
                        worker_args = SimpleNamespace(**worker_values)
                        reason = ("retry" if retry_at else ("baseline" if last is None else "hourly"))
                        f = pool.submit(_scan_new_connection, worker_args, reason, args.store)
                        running[f] = (city, reason)
                        hourly_active += 1
                        print(f"[{now.isoformat(timespec='seconds')}] {reason} scan queued: {city} "
                              f"({hourly_active}/4 hourly workers)", flush=True)
                        if hourly_active >= 4:
                            break
                # Advance sweeps borrow idle scan workers; the fifth remains reserved for T-5.
                if hourly_active < 4 and not urgent_backlog:
                    schedules = [
                        (service_day, advance_slot,
                         advance_targets_for_epoch(args.store, args.movie_id, service_day,
                                                   targets, advance_needs_full))
                        for service_day, advance_slot in
                        advance_slots(now, first_day, args.first_day_hour)
                    ]
                    for service_day, advance_slot, target in round_robin_advance_targets(schedules):
                        if hourly_active >= 4:
                            break
                        city = target["slug"]
                        key = f"multi_advance:{args.movie_id}:{service_day}:{city}"
                        last = state_get(db, key)
                        retry_at = state_get(db, f"{key}:retry")
                        if last and parse_local(last) >= advance_slot:
                            continue
                        if retry_at and parse_local(retry_at) > now:
                            continue
                        same_date_running = any(
                            c == city and reason.startswith(f"advance|{service_day.isoformat()}|")
                            for c, reason in running.values()
                        )
                        if same_date_running:
                            continue
                        worker_values = vars(args).copy()
                        worker_values.update(city=city, date=service_day.isoformat(),
                                             acknowledge_permission=True, final_minutes=5)
                        f = pool.submit(_scan_new_connection, SimpleNamespace(**worker_values), "advance", args.store)
                        running[f] = (city, f"advance|{service_day}|{advance_slot.isoformat()}")
                        hourly_active += 1
                time.sleep(1)
                if dashboard_process is not None and dashboard_process.poll() is not None:
                    code = dashboard_process.returncode
                    dashboard_output.close()
                    dashboard_process = None
                    if code:
                        dashboard_dirty = True
                        print(f"Dashboard refresh failed: exit {code}", file=sys.stderr, flush=True)
                    else:
                        print("Dashboard data refreshed", flush=True)
                if dashboard_dirty and dashboard_process is None and time.monotonic() - last_dashboard_publish >= 300:
                    exporter = Path(__file__).with_name("export_public_hourly_runs.py")
                    try:
                        dashboard_output = (logs_dir / "dashboard_export.log").open("a", encoding="utf-8")
                        dashboard_process = subprocess.Popen(
                            [sys.executable, str(exporter), "--date", target_date.isoformat(),
                             "--store", str(args.store.resolve())],
                            cwd=str(Path(__file__).resolve().parents[1]),
                            stdout=dashboard_output, stderr=subprocess.STDOUT,
                        )
                        dashboard_dirty = False
                    except OSError as exc:
                        if dashboard_output is not None:
                            dashboard_output.close()
                        print(f"Dashboard refresh could not start: {exc}", file=sys.stderr, flush=True)
                    last_dashboard_publish = time.monotonic()
                if time.monotonic() - last_retry_summary >= 60:
                    emit_retry_summary(retry_counts, retry_categories)
                    last_retry_summary = time.monotonic()
                if time.monotonic() - last_scheduler_metrics >= 60:
                    print(f"Scheduler measured DB work: {scheduler_db_seconds:.3f}s "
                          f"across {scheduler_db_samples} due-check and roster operations", flush=True)
                    scheduler_db_seconds = 0.0
                    scheduler_db_samples = 0
                    last_scheduler_metrics = time.monotonic()
        except KeyboardInterrupt:
            print("Interrupted by operator; pending state and captures remain in SQLite.", flush=True)
        finally:
            emit_retry_summary(retry_counts, retry_categories, final=True)
            for f in running:
                f.cancel()
            db.close()
            sys.stdout, sys.stderr = original_out, original_err
            log_file.close()
    if dashboard_dirty and dashboard_process is None:
        exporter = Path(__file__).with_name("export_public_hourly_runs.py")
        result = subprocess.run(
            [sys.executable, str(exporter), "--date", target_date.isoformat(),
             "--store", str(args.store.resolve())],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            print(f"Final dashboard data refresh: {result.stdout.strip()}", flush=True)
        else:
            print(f"Final dashboard refresh failed: {result.stderr.strip() or result.stdout.strip()}",
                  file=sys.stderr, flush=True)
    return 2 if failure.is_set() else 0


def _scan_new_connection(args, reason: str, store: Path):
    db = open_db(store / "smart_collector.sqlite", initialize=False, timeout=60.0)
    try:
        started = time.perf_counter()
        capture_id = scan(db, args, datetime.now(IST), reason, store)
        print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] capture {capture_id} {reason} "
              f"{args.city} completed in {time.perf_counter()-started:.2f}s", flush=True)
        return capture_id
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
