#!/usr/bin/env python3
"""Read-only local API and static server for ScreenLedger's District live view."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = Path(__file__).resolve().parent
DATA = COLLECTOR / "collector_data"
DB_PATH = DATA / "smart_collector.sqlite"
TARGETS_PATH = DATA / "city_targets.json"
VERIFIED_PATH = DATA / "city_targets_verified.json"
MOVIE_ID = "176276"
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
REVENUE_CONFIRMATION = "Payment confirmation reviewed and confirmed by the project owner."


def raw_page_url(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = COLLECTOR / candidate
    try:
        return "/" + candidate.resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return None


def default_date() -> date:
    try:
        payload = json.loads(VERIFIED_PATH.read_text(encoding="utf-8"))
        return date.fromisoformat(payload["service_date"])
    except (OSError, ValueError, KeyError, TypeError):
        return datetime.now(IST).date()


def date_bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time.min, IST).astimezone(UTC)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def db_connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Collector database not found: {DB_PATH}")
    uri = "file:" + quote(DB_PATH.resolve().as_posix(), safe="/:\\") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def load_targets() -> list[dict]:
    try:
        payload = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        targets = payload.get("cities", [])
        if isinstance(targets, list):
            return targets
    except (OSError, ValueError, TypeError):
        pass
    try:
        payload = json.loads(VERIFIED_PATH.read_text(encoding="utf-8"))
        return payload.get("cities", [])
    except (OSError, ValueError, TypeError):
        return []


def latest_capture_cte() -> str:
    return """WITH ranked AS (
        SELECT c.*, ROW_NUMBER() OVER(PARTITION BY c.city ORDER BY c.id DESC) AS rn
        FROM captures c
        WHERE c.movie_id=? AND c.observed_at_utc>=? AND c.observed_at_utc<?
          AND c.status='ok'
    ), latest_city AS (SELECT * FROM ranked WHERE rn=1)"""


def city_rows(conn: sqlite3.Connection, day: date) -> list[dict]:
    targets = load_targets()
    start, end = date_bounds(day)
    rows = conn.execute(latest_capture_cte() + """
        SELECT id,city,actual_city,observed_at_utc,reason,show_count,raw_path
        FROM latest_city ORDER BY city
    """, (MOVIE_ID, start, end)).fetchall()
    captures = {row["city"]: dict(row) for row in rows}
    latest_errors = conn.execute("""SELECT city,error,observed_at_utc FROM (
        SELECT city,error,observed_at_utc,
               ROW_NUMBER() OVER(PARTITION BY city ORDER BY id DESC) rn
        FROM captures WHERE movie_id=? AND observed_at_utc>=? AND observed_at_utc<?
          AND status='error'
    ) WHERE rn=1""", (MOVIE_ID, start, end)).fetchall()
    errors = {row["city"]: dict(row) for row in latest_errors}
    revenue_by_city = {row["city"]: row["revenue"] for row in conn.execute(latest_capture_cte() + """
        SELECT c.city, SUM(o.estimated_gross_inr) AS revenue
        FROM latest_city c LEFT JOIN observations o ON o.capture_id=c.id
          AND substr(o.show_datetime_ist,1,10)=?
        GROUP BY c.city
    """, (MOVIE_ID, start, end, day.isoformat())).fetchall()}
    result = []
    for target in targets:
        slug = target.get("slug", "")
        good = captures.get(slug)
        error = errors.get(slug)
        raw_url = raw_page_url(good.get("raw_path")) if good else None
        result.append({
            "display_name": target.get("display_name", slug),
            "slug": slug,
            "slug_confidence": target.get("slug_confidence", "unknown"),
            "status": "captured" if good else ("failed" if error else "not_collected"),
            "actual_city": good.get("actual_city") if good else None,
            "show_count": good.get("show_count") if good else None,
            "captured_at_utc": good.get("observed_at_utc") if good else None,
            "capture_reason": good.get("reason") if good else None,
            "confirmed_revenue_inr": revenue_by_city.get(slug) if good else None,
            "latest_error": error.get("error") if error else None,
            "raw_page_url": raw_url,
        })
    return result


def session_cte(day: date, city: str | None = None) -> tuple[str, tuple]:
    start, end = date_bounds(day)
    city_clause = " AND o.city=?" if city and city != "all" else ""
    args: tuple = (MOVIE_ID, start, end, MOVIE_ID, day.isoformat())
    if city and city != "all":
        args += (city,)
    cte = latest_capture_cte() + """
    , candidates AS (
        SELECT o.capture_id,o.movie_id,o.city AS source_city,c.actual_city,
               c.observed_at_utc,c.reason,c.raw_path,o.session_key,o.show_datetime_ist,
               o.cinema_id,o.cinema_name,o.total_seats,o.available_seats,
               o.unavailable_seats,o.estimated_gross_inr,o.pricing_complete,
               ROW_NUMBER() OVER(PARTITION BY o.session_key ORDER BY c.observed_at_utc DESC,c.id DESC) AS rn,
               COUNT(*) OVER(PARTITION BY o.session_key) AS feed_count
        FROM observations o JOIN latest_city c ON c.id=o.capture_id
        WHERE o.movie_id=? AND substr(o.show_datetime_ist,1,10)=?""" + city_clause + " )"
    return cte, (MOVIE_ID, start, end, MOVIE_ID, day.isoformat()) + ((city,) if city and city != "all" else ())


def session_dict(row: sqlite3.Row) -> dict:
    path = row["raw_path"]
    raw_url = raw_page_url(path)
    return {
        "session_key": row["session_key"],
        "source_city": row["source_city"],
        "actual_city": row["actual_city"],
        "show_datetime_ist": row["show_datetime_ist"],
        "cinema_id": row["cinema_id"],
        "cinema_name": row["cinema_name"],
        "total_seats": row["total_seats"],
        "available_seats": row["available_seats"],
        "booked_plus_blocked_seats": row["unavailable_seats"],
        "confirmed_revenue_inr": row["estimated_gross_inr"],
        "pricing_complete": bool(row["pricing_complete"]),
        "captured_at_utc": row["observed_at_utc"],
        "capture_reason": row["reason"],
        "source_city_feed_count": row["feed_count"],
        "raw_page_url": raw_url,
    }


def summary(conn: sqlite3.Connection, day: date) -> dict:
    targets = load_targets()
    city_data = city_rows(conn, day)
    cte, args = session_cte(day)
    observations = conn.execute(cte + """
        SELECT COUNT(*) AS feed_rows,COUNT(DISTINCT session_key) AS unique_sessions
        FROM candidates
    """, args).fetchone()
    dedup = conn.execute(cte + """
        SELECT COUNT(*) AS sessions,
               COALESCE(SUM(total_seats),0) AS total_seats,
               COALESCE(SUM(available_seats),0) AS available_seats,
               COALESCE(SUM(unavailable_seats),0) AS booked_plus_blocked_seats,
               COALESCE(SUM(estimated_gross_inr),0) AS confirmed_revenue_inr,
               SUM(CASE WHEN pricing_complete=1 THEN 1 ELSE 0 END) AS priced_sessions,
               MIN(observed_at_utc) AS first_capture_utc,
               MAX(observed_at_utc) AS last_capture_utc
        FROM candidates WHERE rn=1
    """, args).fetchone()
    job_counts = {row["status"]: row["n"] for row in conn.execute("""
        SELECT status,COUNT(*) n FROM final_jobs
        WHERE movie_id=? AND substr(show_datetime_ist,1,10)=? GROUP BY status
    """, (MOVIE_ID, day.isoformat()))}
    unique_pending = conn.execute("""
        SELECT COUNT(DISTINCT session_key) FROM final_jobs
        WHERE movie_id=? AND status='pending' AND substr(show_datetime_ist,1,10)=?
    """, (MOVIE_ID, day.isoformat())).fetchone()[0]
    return {
        "movie_id": MOVIE_ID,
        "movie": "Ramayana",
        "service_date": day.isoformat(),
        "target_city_feeds": len(targets),
        "captured_city_feeds": sum(1 for row in city_data if row["status"] == "captured"),
        "failed_city_feeds": sum(1 for row in city_data if row["status"] == "failed"),
        "not_collected_city_feeds": sum(1 for row in city_data if row["status"] == "not_collected"),
        "city_feed_show_rows": observations["feed_rows"],
        "unique_sessions": dedup["sessions"],
        "duplicate_feed_rows": max(0, observations["feed_rows"] - dedup["sessions"]),
        "total_seats": dedup["total_seats"],
        "available_seats": dedup["available_seats"],
        "booked_plus_blocked_seats": dedup["booked_plus_blocked_seats"],
        "confirmed_revenue_inr": dedup["confirmed_revenue_inr"],
        "priced_sessions": dedup["priced_sessions"] or 0,
        "pricing_incomplete_sessions": max(0, (dedup["sessions"] or 0) - (dedup["priced_sessions"] or 0)),
        "first_capture_utc": dedup["first_capture_utc"],
        "last_capture_utc": dedup["last_capture_utc"],
        "pre_show_jobs": job_counts,
        "unique_pending_pre_show_sessions": unique_pending,
        "revenue_confirmation": REVENUE_CONFIRMATION,
        "source_completeness_verified": False,
    }


def show_page(conn: sqlite3.Connection, day: date, city: str, page: int,
              page_size: int, query: str) -> dict:
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    cte, args = session_cte(day, city)
    scope = "rn=1"
    query_clause = ""
    query_args: tuple = ()
    if query:
        query_clause = " AND (LOWER(COALESCE(cinema_name,'')) LIKE ? OR LOWER(COALESCE(source_city,'')) LIKE ?)"
        pattern = "%" + query.lower() + "%"
        query_args = (pattern, pattern)
    total = conn.execute(cte + f" SELECT COUNT(*) FROM candidates WHERE {scope}{query_clause}", args + query_args).fetchone()[0]
    rows = conn.execute(cte + f"""
        SELECT * FROM candidates WHERE {scope}{query_clause}
        ORDER BY show_datetime_ist,cinema_name
        LIMIT ? OFFSET ?
    """, args + query_args + (page_size, (page - 1) * page_size)).fetchall()
    return {"page": page, "page_size": page_size, "total": total,
            "pages": (total + page_size - 1) // page_size,
            "city": city, "rows": [session_dict(row) for row in rows]}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def api(self, path: str, query: dict[str, list[str]]) -> None:
        day = date.fromisoformat(query.get("date", [default_date().isoformat()])[0])
        conn = db_connect()
        try:
            if path == "/api/live/summary":
                self.send_json(summary(conn, day))
            elif path == "/api/live/cities":
                rows = city_rows(conn, day)
                search = query.get("q", [""])[0].strip().lower()
                status = query.get("status", [""])[0]
                if search:
                    rows = [r for r in rows if search in r["display_name"].lower()
                            or search in r["slug"].lower()]
                if status:
                    rows = [r for r in rows if r["status"] == status]
                rows.sort(key=lambda r: (r["status"] != "captured", r["display_name"].lower()))
                self.send_json({"service_date": day.isoformat(), "total": len(rows), "cities": rows})
            elif path == "/api/live/shows":
                city = query.get("city", ["all"])[0]
                page = int(query.get("page", ["1"])[0])
                page_size = int(query.get("page_size", ["100"])[0])
                search = query.get("q", [""])[0].strip()
                self.send_json(show_page(conn, day, city, page, page_size, search))
            elif path == "/api/live/export.csv":
                city = query.get("city", ["all"])[0]
                output = StringIO()
                writer = csv.DictWriter(output, fieldnames=[
                    "session_key", "source_city", "actual_city", "show_datetime_ist",
                    "cinema_id", "cinema_name", "total_seats", "available_seats",
                    "booked_plus_blocked_seats", "confirmed_revenue_inr",
                    "pricing_complete", "captured_at_utc", "capture_reason",
                    "source_city_feed_count", "raw_page_url",
                ])
                writer.writeheader()
                cte, args = session_cte(day, city)
                rows = conn.execute(cte + """
                    SELECT * FROM candidates WHERE rn=1
                    ORDER BY show_datetime_ist,cinema_name
                """, args)
                for row in rows:
                    writer.writerow(session_dict(row))
                body = output.getvalue().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="screenledger_{day}_{city}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_json({"error": "Unknown endpoint"}, 404)
        except (ValueError, sqlite3.Error, OSError) as exc:
            self.send_json({"error": str(exc)}, 400)
        finally:
            conn.close()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/"):
            self.api(parsed.path, parse_qs(parsed.query))
            return
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        print("[dashboard] " + (fmt % args), flush=True)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ScreenLedger live dashboard: http://{args.host}:{args.port}/dashboard/live.html", flush=True)
    print("Read-only API uses the collector SQLite database.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard server stopping.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
