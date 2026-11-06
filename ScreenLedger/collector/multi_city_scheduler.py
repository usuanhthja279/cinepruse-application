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


def baseline_key(movie_id: str, target_date: date, city: str) -> str:
    return f"multi_baseline:{movie_id}:{target_date}:{city}"


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
                          target_date: date, db) -> dict:
    verified = [target for target in targets
                if state_get(db, baseline_key(movie_id, target_date, target["slug"])) == "ok"]
    report = {"service_date": target_date.isoformat(), "movie_id": str(movie_id),
              "verified_city_count": len(verified), "initial_target_count": len(targets),
              "source_completeness_verified": False,
              "note": "Only cities with a successful validated capture are included. "
                      "This is an operational allowlist, not proof the selector roster is complete.",
              "cities": verified}
    path = store / "city_targets_verified.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


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
    seen = set()
    targets = []
    duplicates = 0
    for label in labels:
        slug = slugify_city(label)
        if not slug or slug in seen:
            duplicates += 1
            continue
        seen.add(slug)
        targets.append({"display_name": label, "slug": slug,
                        "slug_confidence": "verified_sample" if slug in {
                            "mumbai", "delhi-ncr", "bengaluru", "hyderabad", "chennai",
                            "pune", "kolkata", "ahmedabad", "jaipur", "lucknow"}
                        else "inferred_from_selector_label"})
    report = {"selector_entries": len(labels), "unique_request_slugs": len(targets),
              "repeated_labels_or_aliases_collapsed": duplicates,
              "source_completeness_verified": False,
              "slug_note": "Only sampled major-city slugs were live-verified. Other URL slugs are normalized from selector display labels; city mismatches are rejected.",
              "cities": targets}
    return targets, report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cities", type=Path, required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--movie-id", default="176276")
    p.add_argument("--movie-slug", default="ramayana")
    p.add_argument("--store", type=Path, default=Path("collector_data"))
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--retry-seconds", type=int, default=30)
    p.add_argument("--max-retries", type=int, default=1,
                   help="Maximum retries per city between successful hourly captures")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--acknowledge-permission", action="store_true")
    args = p.parse_args()
    target_date = date.fromisoformat(args.date)
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
    start = datetime.combine(target_date, datetime.min.time(), IST)
    end = start + timedelta(days=1)
    db.execute("INSERT INTO kv_state(key,value) VALUES (?,?) ON CONFLICT(key) DO NOTHING",
               (f"multi_city_started:{args.movie_id}:{target_date}", datetime.now(UTC).isoformat()))
    db.commit()
    run_started_at = state_get(db, f"multi_city_started:{args.movie_id}:{target_date}")
    refresh_baseline_statuses(db, targets, args.movie_id, target_date, run_started_at)
    print(f"MULTI-CITY COLLECTOR: {len(targets)} unique URL slugs, {args.movie_slug}/{args.movie_id}, "
          f"service date {target_date} IST; four hourly workers plus one reserved T-5 worker.", flush=True)
    print(f"Coverage caveat: {report['slug_note']}", flush=True)
    print(f"Data store: {args.store.resolve()}; parsed captures only (raw pages are not retained); live log: {log_path.resolve()}", flush=True)

    running: dict[concurrent.futures.Future, tuple[str, str]] = {}
    busy_final_cities: set[str] = set()
    failure = threading.Event()
    retry_counts = {"scheduled": 0, "recovered": 0, "exhausted": 0, "permanent": 0}
    retry_categories: dict[str, int] = {}
    last_retry_summary = time.monotonic()
    dashboard_dirty = False
    last_dashboard_publish = 0.0
    verified_report = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix="district") as pool:
        try:
            while datetime.now(IST) < start:
                time.sleep(min(1, (start - datetime.now(IST)).total_seconds()))
            while datetime.now(IST) < end:
                now = datetime.now(IST)
                initial_complete_key = f"multi_initial_complete:{args.movie_id}:{target_date}"
                initial_complete = state_get(db, initial_complete_key) == "1"
                if not initial_complete and all(
                    state_get(db, baseline_key(args.movie_id, target_date, t["slug"])) in {"ok", "failed"}
                    for t in targets
                ):
                    state_set(db, initial_complete_key, "1")
                    verified_report = write_verified_roster(args.store, targets, args.movie_id,
                                                             target_date, db)
                    initial_complete = True
                    print(f"INITIAL CITY SWEEP COMPLETE: {verified_report['verified_city_count']} of "
                          f"{verified_report['initial_target_count']} targets returned valid data; "
                          f"hourly scans will now use only the saved verified roster.", flush=True)
                active_targets = targets
                if initial_complete:
                    if verified_report is None:
                        verified_report = write_verified_roster(args.store, targets, args.movie_id,
                                                                 target_date, db)
                    active_targets = verified_report["cities"]
                # Completed jobs update hourly state; exceptions are logged by scan().
                for future in list(running):
                    if not future.done():
                        continue
                    city, reason = running.pop(future)
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
                        retry_key = f"multi_retry:{args.movie_id}:{target_date}:{city}"
                        retry_count_key = f"multi_retry_count:{args.movie_id}:{target_date}:{city}"
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
                        retry_key = f"multi_retry:{args.movie_id}:{target_date}:{city}"
                        retry_count_key = f"multi_retry_count:{args.movie_id}:{target_date}:{city}"
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
                            db.execute("DELETE FROM kv_state WHERE key IN (?,?)", (retry_key, retry_count_key))
                            db.commit()
                            if reason in ("baseline", "retry") and state_get(
                                db, f"multi_initial_complete:{args.movie_id}:{target_date}") != "1":
                                state_set(db, baseline_key(args.movie_id, target_date, city), "failed")
                        else:
                            retry_counts["permanent"] += 1
                            disposition = "not retryable; check city slug or source response"
                            db.execute("DELETE FROM kv_state WHERE key IN (?,?)", (retry_key, retry_count_key))
                            db.commit()
                            if reason in ("baseline", "retry") and state_get(
                                db, f"multi_initial_complete:{args.movie_id}:{target_date}") != "1":
                                state_set(db, baseline_key(args.movie_id, target_date, city), "failed")
                        print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] FAILED {reason}: {city} "
                              f"[{category}; {disposition}]: {exc}", file=sys.stderr, flush=True)
                        if "403" in str(exc) or "429" in str(exc):
                            failure.set()

                if failure.is_set():
                    print("District access restriction detected; stopping all new requests.", file=sys.stderr, flush=True)
                    break

                # Keep one worker free so due T-5 scans never queue behind the hourly sweep.
                due_rows = db.execute("""SELECT DISTINCT city FROM final_jobs
                    WHERE movie_id=? AND status='pending' AND target_utc<=?
                    ORDER BY city""", (str(args.movie_id), now.astimezone(UTC).isoformat())).fetchall()
                for row in due_rows:
                    city = row["city"]
                    if city in busy_final_cities or sum(r == "pre_show" for _, r in running.values()) >= 1:
                        continue
                    worker_values = vars(args).copy()
                    worker_values.update(city=city, date=target_date.isoformat(),
                                         acknowledge_permission=True, final_minutes=5)
                    worker_args = SimpleNamespace(**worker_values)
                    f = pool.submit(_scan_new_connection, worker_args, "pre_show", args.store)
                    running[f] = (city, "pre_show")
                    busy_final_cities.add(city)
                    print(f"[{now.isoformat(timespec='seconds')}] PRIORITY T-5 scan queued: {city}", flush=True)
                    break

                # Refill at most four hourly slots. Each city is due once per local hour.
                hourly_active = sum(reason != "pre_show" for _, reason in running.values())
                if hourly_active < 4:
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
                time.sleep(1)
                if dashboard_dirty and time.monotonic() - last_dashboard_publish >= 300:
                    exporter = Path(__file__).with_name("export_public_hourly_runs.py")
                    result = subprocess.run(
                        [sys.executable, str(exporter), "--date", target_date.isoformat(),
                         "--store", str(args.store.resolve())],
                        cwd=str(Path(__file__).resolve().parents[1]),
                        capture_output=True, text=True, check=False,
                    )
                    if result.returncode == 0:
                        print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] Dashboard data refreshed: "
                              f"{result.stdout.strip()}", flush=True)
                        dashboard_dirty = False
                    else:
                        print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] Dashboard refresh failed: "
                              f"{result.stderr.strip() or result.stdout.strip()}", file=sys.stderr, flush=True)
                    last_dashboard_publish = time.monotonic()
                if time.monotonic() - last_retry_summary >= 60:
                    emit_retry_summary(retry_counts, retry_categories)
                    last_retry_summary = time.monotonic()
        except KeyboardInterrupt:
            print("Interrupted by operator; pending state and captures remain in SQLite.", flush=True)
        finally:
            emit_retry_summary(retry_counts, retry_categories, final=True)
            for f in running:
                f.cancel()
            db.close()
            sys.stdout, sys.stderr = original_out, original_err
            log_file.close()
    if dashboard_dirty:
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
    db = open_db(store / "smart_collector.sqlite")
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
