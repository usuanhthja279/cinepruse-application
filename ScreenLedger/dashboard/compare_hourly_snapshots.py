#!/usr/bin/env python3
"""Compare two saved ScreenLedger unique-screening CSV snapshots.

The comparison matches the same movie, venue, showtime, and capacity. It only
counts future screenings captured roughly one hour apart and keeps increases,
releases/corrections, coverage changes, and incomplete pricing separate.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "data" / "district_hourly_runs_2026-11-07"
REQUIRED = {
    "session_key", "captured_at_ist", "show_datetime_ist", "cinema_id",
    "cinema_name", "total_seats", "available_seats",
}


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp has no timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def normal_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        return list(reader)


def read_coverage(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _decimal(row: dict[str, str], key: str) -> Decimal | None:
    value = (row.get(key) or "").strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _prepare(row: dict[str, str], movie_id: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        key = (row.get("session_key") or "").strip()
        if not key:
            return None, "missing_session_key"
        captured = parse_time(row.get("captured_at_ist", ""))
        showtime = parse_time(row.get("show_datetime_ist", ""))
        total = int(row.get("total_seats", ""))
        available = int(row.get("available_seats", ""))
        if total < 0 or available < 0 or available > total:
            return None, "invalid_seat_counts"
    except (ValueError, TypeError):
        return None, "invalid_required_value"

    city = (row.get("source_city_slug") or "").strip().casefold()
    cinema_id = (row.get("cinema_id") or "").strip()
    cinema_name = (row.get("cinema_name") or "").strip()
    venue = f"id:{cinema_id}" if cinema_id else f"name:{normal_text(cinema_name)}"
    if venue in {"id:", "name:"}:
        return None, "missing_venue"

    derived_booked = total - available
    source_booked_text = (row.get("booked_plus_blocked_seats") or "").strip()
    source_booked = derived_booked if not source_booked_text else int(source_booked_text)
    if source_booked != derived_booked:
        return None, "booked_seat_field_mismatch"

    revenue = _decimal(row, "confirmed_revenue_inr")
    pricing_complete = (row.get("pricing_complete") or "").strip().casefold() in {
        "true", "1", "yes",
    }
    return {
        "session_key": key,
        "movie_id": str(movie_id),
        "venue": venue,
        "cinema_id": cinema_id,
        "cinema_name": cinema_name,
        "source_city_slug": city,
        "showtime": showtime,
        "captured_at": captured,
        "total_seats": total,
        "available_seats": available,
        "booked_seats": source_booked,
        "revenue": revenue,
        "pricing_complete": pricing_complete,
        "base_key": (str(movie_id), venue, showtime),
        "stable_key": (str(movie_id), venue, showtime, total),
    }, None


def _collapse(rows: list[dict[str, str]], movie_id: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    issues: Counter[str] = Counter()
    for raw in rows:
        row, error = _prepare(raw, movie_id)
        if error:
            issues[error] += 1
        elif row:
            grouped[row["session_key"]].append(row)

    collapsed: list[dict[str, Any]] = []
    for key, group in grouped.items():
        if len(group) == 1:
            collapsed.append(group[0])
            continue
        core = {
            (r["base_key"], r["total_seats"], r["available_seats"],
             r["booked_seats"], r["revenue"], r["pricing_complete"])
            for r in group
        }
        if len(core) != 1:
            issues["conflicting_duplicate_session_key"] += len(group)
            continue
        issues["duplicate_rows_collapsed"] += len(group) - 1
        collapsed.append(max(group, key=lambda r: r["captured_at"]))
    return collapsed, issues


def _index_unique(rows: list[dict[str, Any]], key_name: str) -> tuple[dict[Any, dict[str, Any]], set[Any]]:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key_name]].append(row)
    unique = {key: items[0] for key, items in groups.items() if len(items) == 1}
    return unique, {key for key, items in groups.items() if len(items) != 1}


def _coverage_stats(rows: list[dict[str, str]]) -> dict[str, Any]:
    statuses = Counter((r.get("capture_status") or "unknown").strip() for r in rows)
    captured_slugs = {
        (r.get("city_slug") or "").strip().casefold()
        for r in rows if (r.get("capture_status") or "").strip() == "captured"
    }
    times = [parse_time(r["captured_at_ist"]) for r in rows if r.get("captured_at_ist")]
    return {
        "target_city_feed_count": len(rows),
        "captured_city_feed_count": statuses.get("captured", 0),
        "failed_city_feed_count": statuses.get("failed", 0),
        "not_collected_city_feed_count": statuses.get("not_collected_this_hour", 0),
        "other_status_counts": {k: v for k, v in sorted(statuses.items())
                                 if k not in {"captured", "failed", "not_collected_this_hour"}},
        "capture_window_utc": _time_window(times),
        "_captured_slugs": captured_slugs,
    }


def _time_window(times: list[datetime]) -> dict[str, str] | None:
    if not times:
        return None
    return {"start": min(times).isoformat(timespec="seconds"),
            "end": max(times).isoformat(timespec="seconds")}


def _public_coverage(stats: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in stats.items() if not k.startswith("_")}


def _public_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def compare_rows(
    previous_rows: list[dict[str, str]],
    current_rows: list[dict[str, str]],
    *,
    movie_id: str,
    previous_coverage: list[dict[str, str]] | None = None,
    current_coverage: list[dict[str, str]] | None = None,
    interval_target_minutes: int = 60,
    interval_tolerance_minutes: int = 10,
) -> dict[str, Any]:
    """Compare rows and produce a compact, auditable matched-session dataset."""
    previous, previous_issues = _collapse(previous_rows, movie_id)
    current, current_issues = _collapse(current_rows, movie_id)
    prev_by_key, prev_duplicate_keys = _index_unique(previous, "session_key")
    curr_by_key, curr_duplicate_keys = _index_unique(current, "session_key")
    used_prev: set[int] = set()
    used_curr: set[int] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    exclusions: Counter[str] = Counter()

    prev_ids = {id(r): r for r in previous}
    curr_ids = {id(r): r for r in current}
    for key in sorted(set(prev_by_key) & set(curr_by_key)):
        a, b = prev_by_key[key], curr_by_key[key]
        used_prev.add(id(a)); used_curr.add(id(b))
        if a["base_key"] != b["base_key"]:
            exclusions["session_key_collision"] += 1
        elif a["total_seats"] != b["total_seats"]:
            exclusions["capacity_changed"] += 1
        else:
            pairs.append((a, b, "session_key"))

    prev_remaining = [r for r in previous if id(r) not in used_prev]
    curr_remaining = [r for r in current if id(r) not in used_curr]
    prev_by_stable, prev_ambiguous = _index_unique(prev_remaining, "stable_key")
    curr_by_stable, curr_ambiguous = _index_unique(curr_remaining, "stable_key")
    for key in sorted(set(prev_by_stable) & set(curr_by_stable), key=repr):
        a, b = prev_by_stable[key], curr_by_stable[key]
        used_prev.add(id(a)); used_curr.add(id(b))
        pairs.append((a, b, "stable_fields"))
        exclusions["renamed_session_key_matches"] += 1

    prev_remaining = [r for r in previous if id(r) not in used_prev]
    curr_remaining = [r for r in current if id(r) not in used_curr]
    prev_by_base, prev_base_ambiguous = _index_unique(prev_remaining, "base_key")
    curr_by_base, curr_base_ambiguous = _index_unique(curr_remaining, "base_key")
    for key in sorted(set(prev_by_base) & set(curr_by_base), key=repr):
        a, b = prev_by_base[key], curr_by_base[key]
        used_prev.add(id(a)); used_curr.add(id(b))
        if a["total_seats"] != b["total_seats"]:
            exclusions["capacity_changed"] += 1
        else:
            exclusions["ambiguous_identity"] += 1

    for key in prev_ambiguous | curr_ambiguous | prev_base_ambiguous | curr_base_ambiguous:
        exclusions["ambiguous_identity_groups"] += 1

    prev_cov = _coverage_stats(previous_coverage or [])
    curr_cov = _coverage_stats(current_coverage or [])
    added_cities = curr_cov["_captured_slugs"] - prev_cov["_captured_slugs"]
    lost_cities = prev_cov["_captured_slugs"] - curr_cov["_captured_slugs"]
    current_coverage_rows = {
        (r.get("city_slug") or "").strip().casefold(): r
        for r in (current_coverage or [])
    }
    previous_coverage_rows = {
        (r.get("city_slug") or "").strip().casefold(): r
        for r in (previous_coverage or [])
    }

    valid: list[dict[str, Any]] = []
    interval_minutes: list[float] = []
    for a, b, match_method in pairs:
        interval = (b["captured_at"] - a["captured_at"]).total_seconds() / 60
        if abs(interval - interval_target_minutes) > interval_tolerance_minutes:
            exclusions["capture_interval_outside_tolerance"] += 1
            continue
        if b["showtime"] <= b["captured_at"]:
            exclusions["show_started_by_current_capture"] += 1
            continue
        delta = b["booked_seats"] - a["booked_seats"]
        revenue_delta = None
        if (a["pricing_complete"] and b["pricing_complete"]
                and a["revenue"] is not None and b["revenue"] is not None):
            revenue_delta = b["revenue"] - a["revenue"]
        interval_minutes.append(interval)
        valid.append({
            "session_key_previous": a["session_key"],
            "session_key_current": b["session_key"],
            "session_key_changed": a["session_key"] != b["session_key"],
            "match_method": match_method,
            "source_city_slug_previous": a["source_city_slug"],
            "source_city_slug_current": b["source_city_slug"],
            "cinema_id": a["cinema_id"] or b["cinema_id"],
            "cinema_name": a["cinema_name"] or b["cinema_name"],
            "show_datetime_ist": _public_time(b["showtime"].astimezone()),
            "capture_previous_utc": _public_time(a["captured_at"]),
            "capture_current_utc": _public_time(b["captured_at"]),
            "capture_interval_minutes": round(interval, 2),
            "capacity": a["total_seats"],
            "booked_plus_blocked_previous": a["booked_seats"],
            "booked_plus_blocked_current": b["booked_seats"],
            "net_booked_change": delta,
            "positive_booked_change": max(delta, 0),
            "released_or_corrected_seats": abs(min(delta, 0)),
            "confirmed_revenue_previous_inr": _money(a["revenue"]) if a["revenue"] is not None else None,
            "confirmed_revenue_current_inr": _money(b["revenue"]) if b["revenue"] is not None else None,
            "confirmed_revenue_change_inr": _money(revenue_delta) if revenue_delta is not None else None,
            "revenue_comparable": revenue_delta is not None,
        })

    prev_used = {id(a) for a, _, _ in pairs}
    curr_used = {id(b) for _, b, _ in pairs}
    new_rows = [r for r in current if id(r) not in used_curr and id(r) not in curr_used]
    disappeared_rows = [r for r in previous if id(r) not in used_prev and id(r) not in prev_used]

    comparable_revenue = [r for r in valid if r["revenue_comparable"]]
    revenue_complete = bool(valid) and len(comparable_revenue) == len(valid)
    seat_changes = [r["net_booked_change"] for r in valid]
    revenue_changes = [Decimal(str(r["confirmed_revenue_change_inr"]))
                       for r in comparable_revenue]

    new_city_slugs = sorted({r["source_city_slug"] for r in new_rows if r["source_city_slug"]})
    disappeared_city_slugs = sorted({r["source_city_slug"] for r in disappeared_rows if r["source_city_slug"]})
    newly_seen_in_new_coverage = sum(1 for r in new_rows if r["source_city_slug"] in added_cities)
    disappeared_with_lost_coverage = sum(1 for r in disappeared_rows if r["source_city_slug"] in lost_cities)

    matched_ids = {r["session_key_current"] for r in valid}
    return {
        "schema_version": 1,
        "movie_id": str(movie_id),
        "service_date_ist": (current_rows[0].get("service_date_ist") if current_rows else None),
        "comparison": {
            "previous_hour_ist": (previous_rows[0].get("collection_hour_ist") if previous_rows else None),
            "current_hour_ist": (current_rows[0].get("collection_hour_ist") if current_rows else None),
            "target_interval_minutes": interval_target_minutes,
            "allowed_interval_minutes": [interval_target_minutes - interval_tolerance_minutes,
                                         interval_target_minutes + interval_tolerance_minutes],
            "matched_future_session_count": len(valid),
            "matched_session_key_changed_count": sum(r["session_key_changed"] for r in valid),
            "new_session_count": len(new_rows),
            "new_session_count_from_newly_covered_cities": newly_seen_in_new_coverage,
            "disappeared_session_count": len(disappeared_rows),
            "disappeared_count_from_lost_coverage": disappeared_with_lost_coverage,
            "capacity_changed_count": exclusions["capacity_changed"],
            "ambiguous_identity_count": exclusions["ambiguous_identity"] + exclusions["ambiguous_identity_groups"],
            "session_key_collision_count": exclusions["session_key_collision"],
            "capture_interval_excluded_count": exclusions["capture_interval_outside_tolerance"],
            "already_started_excluded_count": exclusions["show_started_by_current_capture"],
            "invalid_previous_rows": sum(previous_issues.values()),
            "invalid_current_rows": sum(current_issues.values()),
            "duplicate_previous_rows_collapsed": previous_issues["duplicate_rows_collapsed"],
            "duplicate_current_rows_collapsed": current_issues["duplicate_rows_collapsed"],
            "seat_change": {
                "positive_booked_plus_blocked_seats": sum(max(change, 0) for change in seat_changes),
                "released_or_corrected_seats": sum(abs(min(change, 0)) for change in seat_changes),
                "net_booked_plus_blocked_seat_change": sum(seat_changes),
            },
            "confirmed_revenue_change_inr": {
                "available": revenue_complete,
                "value": _money(sum(revenue_changes, Decimal("0"))) if revenue_complete else None,
                "comparable_session_count": len(comparable_revenue),
                "incomplete_pricing_session_count": len(valid) - len(comparable_revenue),
            },
            "capture_interval_minutes": {
                "min": round(min(interval_minutes), 2) if interval_minutes else None,
                "median": round(sorted(interval_minutes)[len(interval_minutes)//2], 2) if interval_minutes else None,
                "max": round(max(interval_minutes), 2) if interval_minutes else None,
            },
        },
        "coverage": {
            "previous": _public_coverage(prev_cov),
            "current": _public_coverage(curr_cov),
            "newly_covered_city_feed_count": len(added_cities),
            "no_longer_captured_city_feed_count": len(lost_cities),
            "newly_covered_city_slugs": sorted(added_cities),
            "no_longer_captured_city_slugs": sorted(lost_cities),
            "new_session_city_slugs": new_city_slugs,
            "disappeared_session_city_slugs": disappeared_city_slugs,
        },
        "quality": {
            "session_matching": "movie_id + venue + showtime + capacity; session_key used as a fast path",
            "current_show_filter": "showtime must be later than its current snapshot capture time",
            "coverage_warning": "Snapshot totals cannot be interpreted as last-hour sales when city-feed coverage differs.",
            "revenue_warning": "Revenue change is unavailable unless every matched session has complete confirmed-revenue values at both captures.",
            "previous_data_issues": dict(sorted(previous_issues.items())),
            "current_data_issues": dict(sorted(current_issues.items())),
            "comparison_exclusions": dict(sorted(exclusions.items())),
            "duplicate_unique_session_keys": {
                "previous_count": len(prev_duplicate_keys), "current_count": len(curr_duplicate_keys),
            },
        },
    }


def build_from_files(
    previous_path: Path,
    current_path: Path,
    *,
    movie_id: str,
    previous_coverage_path: Path | None = None,
    current_coverage_path: Path | None = None,
    interval_tolerance_minutes: int = 10,
) -> dict[str, Any]:
    result = compare_rows(
        read_csv(previous_path), read_csv(current_path), movie_id=movie_id,
        previous_coverage=read_coverage(previous_coverage_path),
        current_coverage=read_coverage(current_coverage_path),
        interval_tolerance_minutes=interval_tolerance_minutes,
    )
    result["source_files"] = {
        "previous_unique_screenings_csv": previous_path.name,
        "current_unique_screenings_csv": current_path.name,
        "previous_city_coverage_csv": previous_coverage_path.name if previous_coverage_path else None,
        "current_city_coverage_csv": current_coverage_path.name if current_coverage_path else None,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path,
                        default=RUN_DIR / "unique_screenings_2026-11-07_0100_IST.csv")
    parser.add_argument("--current", type=Path,
                        default=RUN_DIR / "unique_screenings_2026-11-07_0200_IST.csv")
    parser.add_argument("--previous-coverage", type=Path,
                        default=RUN_DIR / "city_coverage_2026-11-07_0100_IST.csv")
    parser.add_argument("--current-coverage", type=Path,
                        default=RUN_DIR / "city_coverage_2026-11-07_0200_IST.csv")
    parser.add_argument("--movie-id", default="176276")
    parser.add_argument("--interval-tolerance-minutes", type=int, default=10)
    parser.add_argument("--output", type=Path,
                        default=RUN_DIR / "matched_delta_2026-11-07_0100_0200.json")
    args = parser.parse_args()
    result = build_from_files(
        args.previous, args.current, movie_id=args.movie_id,
        previous_coverage_path=args.previous_coverage,
        current_coverage_path=args.current_coverage,
        interval_tolerance_minutes=args.interval_tolerance_minutes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = result["comparison"]
    print(f"Wrote {args.output}; matched {summary['matched_future_session_count']} future sessions; "
          f"net assumed booked-seat change {summary['seat_change']['net_booked_plus_blocked_seat_change']:+,}; "
          f"revenue delta available={summary['confirmed_revenue_change_inr']['available']}")


if __name__ == "__main__":
    main()
