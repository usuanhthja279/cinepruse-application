#!/usr/bin/env python3
"""Export the 1 a.m. through 4 a.m. District hourly capture windows.

Exports parsed collector data only. Raw HTML, the collector database, and error
payloads are intentionally excluded. Each hourly window uses the latest successful
hourly capture per city; failures and cities not reached are retained in coverage.
"""
from __future__ import annotations

import csv
import json
import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(__file__).resolve().parent / "collector_data"
DB_PATH = STORE / "smart_collector.sqlite"
TARGETS_PATH = STORE / "city_targets.json"
IST = ZoneInfo("Asia/Kolkata")
MOVIE_ID = "176276"

CITY_FIELDS = ["service_date_ist", "collection_hour_ist", "display_name", "city_slug",
               "capture_status", "capture_id", "captured_at_ist", "attempts_in_hour",
               "show_count", "error_category"]
SHOW_FIELDS = ["service_date_ist", "collection_hour_ist", "source_city_slug", "actual_city",
               "captured_at_ist", "session_key", "show_datetime_ist", "cinema_id",
               "cinema_name", "total_seats", "available_seats",
               "booked_plus_blocked_seats", "confirmed_revenue_inr", "pricing_complete"]
UNIQUE_FIELDS = ["service_date_ist", "collection_hour_ist", "session_key", "source_city_slug",
                 "source_city_feed_count", "actual_city", "captured_at_ist",
                 "show_datetime_ist", "cinema_id", "cinema_name", "total_seats",
                 "available_seats", "booked_plus_blocked_seats", "confirmed_revenue_inr",
                 "pricing_complete"]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def error_category(error: str | None) -> str:
    value = (error or "").lower()
    if "404" in value:
        return "http_404"
    if "403" in value:
        return "http_403"
    if "429" in value:
        return "http_429"
    if "resolve" in value or "connectionerror" in value or "timeout" in value:
        return "connection_error"
    if "movie" in value and ("missing" in value or "not found" in value):
        return "missing_movie_data"
    if value:
        return "other_capture_error"
    return ""


def capture_local_time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(IST).isoformat(timespec="seconds")


def export_hour(conn: sqlite3.Connection, targets: list[dict], hour: int,
                service_date: str, out: Path) -> dict:
    all_caps = conn.execute("""
        SELECT id,city,actual_city,observed_at_utc,status,show_count,error,reason
        FROM captures WHERE movie_id=? ORDER BY id
    """, (MOVIE_ID,)).fetchall()
    hour_caps: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for cap in all_caps:
        local = datetime.fromisoformat(cap["observed_at_utc"]).astimezone(IST)
        if (local.date().isoformat() == service_date and local.hour == hour
                and cap["status"] in {"ok", "error"}):
            if cap["reason"] in {"baseline", "hourly", "retry"}:
                hour_caps[cap["city"]].append(cap)

    selected: dict[str, sqlite3.Row] = {}
    coverage: list[dict] = []
    for target in targets:
        slug = target["slug"]
        attempts = hour_caps.get(slug, [])
        successes = [c for c in attempts if c["status"] == "ok"]
        if successes:
            latest = max(successes, key=lambda c: c["id"])
            selected[slug] = latest
            status = "captured"
        elif attempts:
            latest = max(attempts, key=lambda c: c["id"])
            status = "failed"
        else:
            latest = None
            status = "not_collected_this_hour"
        coverage.append({
            "service_date_ist": service_date,
            "collection_hour_ist": f"{hour:02d}:00",
            "display_name": target.get("display_name", slug),
            "city_slug": slug,
            "capture_status": status,
            "capture_id": latest["id"] if latest else "",
            "captured_at_ist": capture_local_time(latest["observed_at_utc"]) if latest else "",
            "attempts_in_hour": len(attempts),
            "show_count": latest["show_count"] if latest and latest["status"] == "ok" else "",
            "error_category": error_category(latest["error"]) if latest and latest["status"] != "ok" else "",
        })
    write_csv(out / f"city_coverage_{service_date}_{hour:02d}00_IST.csv", CITY_FIELDS, coverage)

    feed_rows: list[dict] = []
    session_rows: dict[str, list[dict]] = defaultdict(list)
    for slug, capture in selected.items():
        obs = conn.execute("""
            SELECT session_key,city,show_datetime_ist,cinema_id,cinema_name,
                   total_seats,available_seats,unavailable_seats,estimated_gross_inr,pricing_complete
            FROM observations WHERE capture_id=? AND substr(show_datetime_ist,1,10)=?
            ORDER BY show_datetime_ist,cinema_name
        """, (capture["id"], service_date)).fetchall()
        captured_at = capture_local_time(capture["observed_at_utc"])
        for row in obs:
            item = {
                "service_date_ist": service_date,
                "collection_hour_ist": f"{hour:02d}:00",
                "source_city_slug": slug,
                "actual_city": capture["actual_city"] or "",
                "captured_at_ist": captured_at,
                "session_key": row["session_key"],
                "show_datetime_ist": row["show_datetime_ist"],
                "cinema_id": row["cinema_id"],
                "cinema_name": row["cinema_name"],
                "total_seats": row["total_seats"],
                "available_seats": row["available_seats"],
                "booked_plus_blocked_seats": row["unavailable_seats"],
                "confirmed_revenue_inr": row["estimated_gross_inr"],
                "pricing_complete": bool(row["pricing_complete"]),
            }
            feed_rows.append(item)
            session_rows[row["session_key"]].append(item)
    feed_rows.sort(key=lambda x: (x["show_datetime_ist"], x["source_city_slug"], x["cinema_name"]))
    write_csv(out / f"city_feed_screenings_{service_date}_{hour:02d}00_IST.csv", SHOW_FIELDS, feed_rows)

    unique_rows: list[dict] = []
    for session_key, rows in session_rows.items():
        latest = max(rows, key=lambda x: x["captured_at_ist"])
        unique_rows.append({**latest, "source_city_feed_count": len({x["source_city_slug"] for x in rows})})
    unique_rows.sort(key=lambda x: (x["show_datetime_ist"], x["cinema_name"]))
    write_csv(out / f"unique_screenings_{service_date}_{hour:02d}00_IST.csv", UNIQUE_FIELDS, unique_rows)

    captured_n = sum(row["capture_status"] == "captured" for row in coverage)
    failed_n = sum(row["capture_status"] == "failed" for row in coverage)
    not_collected_n = sum(row["capture_status"] == "not_collected_this_hour" for row in coverage)
    revenue = sum(float(row["confirmed_revenue_inr"] or 0) for row in unique_rows)
    return {
        "service_date_ist": service_date,
        "collection_hour_ist": f"{hour:02d}:00",
        "scheduled_reason": "hourly",
        "target_city_feeds": len(targets),
        "captured_city_feeds": captured_n,
        "failed_city_feeds": failed_n,
        "not_collected_this_hour_city_feeds": not_collected_n,
        "city_feed_observation_rows": len(feed_rows),
        "unique_session_count": len(unique_rows),
        "duplicate_city_feed_rows": len(feed_rows) - len(unique_rows),
        "total_seats": sum(int(r["total_seats"] or 0) for r in unique_rows),
        "available_seats": sum(int(r["available_seats"] or 0) for r in unique_rows),
        "booked_plus_blocked_seats": sum(int(r["booked_plus_blocked_seats"] or 0) for r in unique_rows),
        "confirmed_revenue_inr": revenue,
        "confirmed_revenue_basis": "Per project-owner payment confirmation; calculated from booked-plus-blocked seat value in the saved collector records.",
        "source_city_roster_slug_completeness_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Collector service date in YYYY-MM-DD")
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    service_date = datetime.fromisoformat(args.date).date().isoformat()
    db_path = args.store / "smart_collector.sqlite"
    targets_path = args.store / "city_targets.json"
    out = args.output or ROOT / "dashboard" / "data" / f"district_hourly_runs_{service_date}"
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    target_data = json.loads(targets_path.read_text(encoding="utf-8"))
    targets = target_data.get("cities", [])
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        hours = sorted({datetime.fromisoformat(row[0]).astimezone(IST).hour
                        for row in conn.execute("SELECT observed_at_utc FROM captures WHERE movie_id=? AND status IN ('ok','error') AND reason IN ('baseline','hourly','retry')", (MOVIE_ID,))
                        if datetime.fromisoformat(row[0]).astimezone(IST).date().isoformat() == service_date})
        summaries = [export_hour(conn, targets, hour, service_date, out) for hour in hours]
    finally:
        conn.close()
    out.mkdir(parents=True, exist_ok=True)
    comparison_files = []
    sys.path.insert(0, str(ROOT / "dashboard"))
    from compare_hourly_snapshots import build_from_files
    for previous, current in zip(summaries, summaries[1:]):
        prev_hour = previous["collection_hour_ist"].replace(":", "")
        curr_hour = current["collection_hour_ist"].replace(":", "")
        name = f"matched_delta_{service_date}_{prev_hour}_{curr_hour}.json"
        result = build_from_files(
            out / f"unique_screenings_{service_date}_{prev_hour}_IST.csv",
            out / f"unique_screenings_{service_date}_{curr_hour}_IST.csv",
            movie_id=MOVIE_ID,
            previous_coverage_path=out / f"city_coverage_{service_date}_{prev_hour}_IST.csv",
            current_coverage_path=out / f"city_coverage_{service_date}_{curr_hour}_IST.csv",
        )
        (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        comparison_files.append(name)
    generated = datetime.now(IST).isoformat(timespec="seconds")
    summary_path = out / "run_summaries.json"
    summary_path.write_text(
        json.dumps({"movie": "Ramayana", "movie_id": MOVIE_ID, "service_date_ist": service_date,
                    "timezone": "Asia/Kolkata", "generated_at_ist": generated,
                    "runs": summaries, "comparisons": comparison_files}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest = ROOT / "dashboard" / "data" / "district_hourly_runs_latest.json"
    temp_manifest = manifest.with_suffix(".json.tmp")
    temp_manifest.write_text(json.dumps({"service_date_ist": service_date,
                                         "directory": out.relative_to(ROOT / "dashboard").as_posix(),
                                         "generated_at_ist": generated}, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_manifest.replace(manifest)
    print(f"Published {len(summaries)} hourly snapshots for {service_date} at {generated}", flush=True)


if __name__ == "__main__":
    main()
