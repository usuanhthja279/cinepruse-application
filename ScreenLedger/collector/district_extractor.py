#!/usr/bin/env python3
"""Extract District movie/cinema/show/seat-category data from saved HTML.

Live acquisition is opt-in for use only with authorization and must not be used
for bypassing website controls or in violation of the website's terms.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

IST = ZoneInfo("Asia/Kolkata")
URL_PATTERN = re.compile(r"/movies/(?P<slug>[a-z0-9-]+)-movie-tickets-in-(?P<city>[a-z0-9-]+)-MV(?P<id>\d+)", re.I)
CITY_ALIASES = {
    "delhi": "delhi-ncr", "new-delhi": "delhi-ncr", "ncr": "delhi-ncr",
    "gurgaon": "delhi-ncr", "gurugram": "delhi-ncr", "noida": "delhi-ncr",
    "bangalore": "bengaluru", "visakhapatnam": "vizag", "vishakhapatnam": "vizag",
    "thiruvananthapuram": "trivandrum", "cochin": "kochi",
    "bombay": "mumbai", "calcutta": "kolkata", "baroda": "vadodara",
    "allahabad": "prayagraj", "panaji": "goa",
}
SHOW_FIELDS = [
    "snapshot_utc", "source_city", "actual_city", "movie_id", "movie_name", "format_group_id", "language",
    "show_date_ist", "show_time_ist", "show_datetime_ist", "cinema_id", "cinema_name",
    "cinema_chain", "cinema_address", "latitude", "longitude", "session_id", "provider_id",
    "provider_movie_id", "session_key", "auditorium", "screen_format", "premium_label", "subtitle",
    "total_seats", "available_seats", "unavailable_seats", "unavailable_pct",
    "seat_status", "min_price_inr", "max_price_inr", "booking_url",
    "assumed_booked_seats", "assumed_occupancy_pct", "estimated_gross_inr",
    "priced_assumed_booked_seats", "pricing_complete",
]
AREA_FIELDS = [
    "snapshot_utc", "source_city", "movie_id", "cinema_id", "cinema_name", "session_key",
    "show_datetime_ist", "category_code", "category_label", "price_inr", "total_seats",
    "available_seats", "unavailable_seats", "seat_status",
    "assumed_booked_seats", "estimated_gross_inr",
]


def slugify_city(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return CITY_ALIASES.get(value, value)


def make_url(movie_slug: str, movie_id: str | int, city: str, date: str | None = None,
             format_id: str | None = None) -> str:
    if not re.fullmatch(r"\d+", str(movie_id)):
        raise ValueError("movie_id must consist only of digits")
    name = re.sub(r"[^a-z0-9]+", "-", movie_slug.lower()).strip("-")
    if not name or not slugify_city(city):
        raise ValueError("movie slug and city are both required")
    url = f"https://www.district.in/movies/{name}-movie-tickets-in-{slugify_city(city)}-MV{movie_id}"
    query = {}
    if format_id:
        query["frmtid"] = format_id
    if date:
        datetime.strptime(date, "%Y-%m-%d")
        query["fromdate"] = date
    return url + ("?" + urlencode(query) if query else "")


def parse_movie_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.hostname != "www.district.in" or parsed.scheme != "https":
        raise ValueError("Only https://www.district.in movie URLs are supported")
    match = URL_PATTERN.fullmatch(parsed.path)
    if not match:
        raise ValueError("Expected /movies/{slug}-movie-tickets-in-{city}-MV{digits}")
    fields = match.groupdict()
    fields["query"] = parse_qs(parsed.query)
    return fields


_http_local = threading.local()


def get_page_html(url: str, timeout: float = 25.0) -> str:
    """One plain HTML GET. Do not retry or bypass 403 / 429 or challenge pages."""
    import requests
    if not hasattr(_http_local, "session"):
        _http_local.session = requests.Session()
    response = _http_local.session.get(url, timeout=timeout, headers={
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "DistrictMovieExtractor/0.1 (authorized research; HTML parser)",
    }, allow_redirects=True)
    if response.status_code in (403, 429):
        raise RuntimeError(f"District returned {response.status_code}; access restricted. Stopping, no retries.")
    response.raise_for_status()
    if "district.in" not in urlparse(response.url).hostname:
        raise RuntimeError("Unexpected redirect outside District")
    return response.text


def extract_next_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("script", id="__NEXT_DATA__")
    if not node or not node.get_text(strip=True):
        raise ValueError("No __NEXT_DATA__ found; page may be blocked, dynamic, or changed structure")
    try:
        return json.loads(node.get_text())
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in __NEXT_DATA__") from exc


def ist_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        # On the supplied page, showTime is a naive ISO string containing UTC time.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def safe_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def extract_snapshot(html: str, source_url: str | None = None, source_city: str | None = None,
                     expected_movie_id: str | None = None, snapshot_utc: str | None = None,
                     language: str | None = None) -> dict:
    payload = extract_next_data(html)
    page = payload.get("props", {}).get("pageProps", {}).get("data", {})
    state = page.get("serverState", {})
    movie_lookup = state.get("mdpV2MovieData", {})
    if not isinstance(movie_lookup, dict) or not movie_lookup:
        raise ValueError("No movie metadata found; do not interpret as zero shows")
    movie_id = str(expected_movie_id or page.get("contentId") or next(iter(movie_lookup)))
    movie_bundle = movie_lookup.get(movie_id)
    if not movie_bundle or not isinstance(movie_bundle.get("movie"), dict):
        raise ValueError(f"Movie ID {movie_id} absent in response; possible city redirect or page change")
    movie = movie_bundle["movie"]
    session_groups = state.get("movieSessions", {})
    if not isinstance(session_groups, dict):
        raise ValueError("Unexpected movieSessions type")

    requested_city = slugify_city(source_city or page.get("cityName") or "unknown")
    actual_city = slugify_city(page.get("cityName") or "unknown")
    stamp = snapshot_utc or datetime.now(timezone.utc).isoformat(timespec="seconds")
    available_dates = set()
    shows = []
    areas = []
    cinema_ids = set()
    seen = set()
    for format_group_id, group in session_groups.items():
        available_dates.update((group.get("data") or {}).get("sessionDates") or [])
        for cinema in group.get("arrangedSessions") or []:
            cin = cinema.get("data") or {}
            cinema_id = cinema.get("entityCode") or cin.get("id")
            cinema_name = cinema.get("entityName") or cin.get("name") or "Unknown cinema"
            for session in cinema.get("sessions") or []:
                show_dt = ist_datetime(session.get("showTime"))
                session_id = str(session.get("sid") or "")
                provider_id = session.get("pid")
                cid = session.get("cid") or cinema_id
                # Distinct provider sessions may share times; format ID also matters.
                key = ":".join(map(str, [cid, provider_id, session_id,
                                          session.get("mid") or "", session.get("showTime") or "", format_group_id]))
                if key in seen:
                    continue
                seen.add(key)
                cinema_ids.add(str(cinema_id))
                total = safe_int(session.get("total"))
                avail = safe_int(session.get("avail"))
                costs = [a.get("price") for a in (session.get("areas") or [])
                         if isinstance(a.get("price"), (int, float))]
                session_params = {
                    "encsessionid": session.get("encSessionId"),
                    "freeseating": "false", "fromsessions": "true", "type": "MOVIES",
                    "contentid": movie_id,
                }
                booking_url = ""
                if session_params["encsessionid"]:
                    booking_url = "https://www.district.in/movies/seat-layout/" + format_group_id + "?" + urlencode(session_params)
                category_rows = []
                category_total = 0
                category_available = 0
                priced_assumed_booked = 0
                category_unpriced = False
                known_gross = Decimal("0")
                for area in session.get("areas") or []:
                    a_total = safe_int(area.get("sTotal"))
                    a_avail = safe_int(area.get("sAvail"))
                    has_counts = (a_total is not None and a_avail is not None
                                  and 0 <= a_avail <= a_total)
                    count = a_total - a_avail if has_counts else None
                    price = area.get("price")
                    if has_counts:
                        category_total += a_total
                        category_available += a_avail
                    else:
                        category_unpriced = True
                    cost = None
                    if count is not None:
                        if price is not None:
                            try:
                                d_price = Decimal(str(price))
                                if not d_price.is_finite() or d_price < 0:
                                    raise InvalidOperation()
                                cost = d_price * count
                                priced_assumed_booked += count
                                known_gross += cost
                            except (InvalidOperation, ValueError):
                                category_unpriced = True
                        elif count > 0:
                            category_unpriced = True
                    category_rows.append({
                        "snapshot_utc": stamp, "source_city": requested_city, "movie_id": movie_id,
                        "cinema_id": cinema_id, "cinema_name": cinema_name, "session_key": key,
                        "show_datetime_ist": show_dt.isoformat() if show_dt else None,
                        "category_code": area.get("code"), "category_label": area.get("label"),
                        "price_inr": price, "total_seats": a_total, "available_seats": a_avail,
                        "unavailable_seats": count, "seat_status": area.get("seatStatus"),
                        "assumed_booked_seats": count,
                        "estimated_gross_inr": float(cost) if cost is not None else None,
                    })
                counts_valid = (total is not None and avail is not None and 0 <= avail <= total)
                pricing_complete = (counts_valid and bool(category_rows) and not category_unpriced
                                    and total == category_total and avail == category_available)
                assumed_booked = total - avail if counts_valid else None
                row = {
                    "snapshot_utc": stamp, "source_city": requested_city, "actual_city": actual_city,
                    "movie_id": movie_id, "movie_name": movie.get("name"), "format_group_id": format_group_id,
                    "language": language,
                    "show_date_ist": show_dt.date().isoformat() if show_dt else None,
                    "show_time_ist": show_dt.strftime("%H:%M") if show_dt else None,
                    "show_datetime_ist": show_dt.isoformat() if show_dt else None,
                    "cinema_id": cinema_id, "cinema_name": cinema_name,
                    "cinema_chain": cin.get("chainKey"), "cinema_address": cin.get("address"),
                    "latitude": cin.get("latitude"), "longitude": cin.get("longitude"),
                    "session_id": session_id, "provider_id": provider_id,
                    "provider_movie_id": session.get("mid"), "session_key": key,
                    "auditorium": session.get("audi"), "screen_format": session.get("scrnFmt"),
                    "premium_label": session.get("premiumLabel"), "subtitle": session.get("subtitle"),
                    "total_seats": total, "available_seats": avail,
                    "unavailable_seats": total - avail if total is not None and avail is not None else None,
                    "unavailable_pct": round(100 * (total - avail) / total, 2) if total and avail is not None else None,
                    "seat_status": session.get("seatStatus"), "min_price_inr": min(costs) if costs else None,
                    "max_price_inr": max(costs) if costs else None, "booking_url": booking_url,
                    "assumed_booked_seats": assumed_booked,
                    "assumed_occupancy_pct": round(100 * assumed_booked / total, 2) if total and counts_valid else None,
                    "estimated_gross_inr": float(known_gross) if pricing_complete else None,
                    "priced_assumed_booked_seats": priced_assumed_booked,
                    "pricing_complete": pricing_complete,
                }
                shows.append(row)
                areas.extend(category_rows)
    shows.sort(key=lambda s: (s["show_datetime_ist"] or "", str(s["cinema_name"])))
    total = sum(s["total_seats"] or 0 for s in shows)
    remaining = sum(s["available_seats"] or 0 for s in shows)
    priced_shows = [s for s in shows if s["pricing_complete"]]
    priced_gross = sum(Decimal(str(s["estimated_gross_inr"])) for s in priced_shows)
    result = {
        "metadata": {
            "snapshot_utc": stamp, "source_url": source_url,
            "source_city": requested_city, "actual_city": actual_city,
            "movie_id": movie_id, "movie_name": movie.get("name"),
            "duration_minutes": movie.get("duration"), "languages": movie.get("languages"),
            "release_date": movie.get("release_date"),
            "poster": movie.get("poster"), "available_dates": sorted(available_dates),
            "format_group_ids": list(session_groups),
            "cinemas_with_shows": len(cinema_ids), "shows": len(shows),
            "seat_categories": len(areas), "total_seats_across_shows": total,
            "available_seats_across_shows": remaining,
            "unavailable_seats_across_shows": total - remaining,
            "unavailable_pct": round(100 * (total - remaining) / total, 2) if total else None,
            "assumed_booked_seats_across_shows": total - remaining,
            "assumed_occupancy_pct": round(100 * (total - remaining) / total, 2) if total else None,
            "priced_show_count": len(priced_shows),
            "unpriced_show_count": len(shows) - len(priced_shows),
            "known_priced_gross_inr": float(priced_gross),
            "estimated_gross_inr": float(priced_gross) if len(priced_shows) == len(shows) else None,
            "collection_policy": "Count all unavailable seats, including blocked and held, as assumed booked; value at advertised area prices.",
            "coverage_note": "ESTIMATE only: unavailable/blocked seats are assumed booked. Not confirmed tickets sold, actual gross or net box office.",
        },
        "shows": shows, "areas": areas,
    }
    return result


def write_csv(path: Path, records: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def save_results(out: Path, all_results: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    all_shows = [r for x in all_results for r in x["shows"]]
    all_areas = [r for x in all_results for r in x["areas"]]
    summaries = [x["metadata"] for x in all_results]
    write_csv(out / "shows.csv", all_shows, SHOW_FIELDS)
    write_csv(out / "seat_categories.csv", all_areas, AREA_FIELDS)
    # One selected snapshot per real session across requested cities. The original
    # shows.csv and snapshots.json retain every source city for auditing.
    unique_shows = {}
    unique_categories = {}
    for result in all_results:
        categories_by_key = {}
        for area in result["areas"]:
            categories_by_key.setdefault(area["session_key"], []).append(area)
        for show in result["shows"]:
            # A session ID identifies the show; use time as a secondary safety check.
            # If missing, include the more specific composite session key.
            session_id = show.get("session_id")
            key = (str(show.get("movie_id")), str(show.get("cinema_id")),
                   str(show.get("provider_id")), str(session_id or show.get("session_key")),
                   str(show.get("show_datetime_ist")))
            existing = unique_shows.get(key)
            if existing is None or show["snapshot_utc"] >= existing["snapshot_utc"]:
                unique_shows[key] = show
                unique_categories[key] = categories_by_key.get(show["session_key"], [])
    deduped = sorted(unique_shows.values(), key=lambda x: (x.get("show_datetime_ist") or "", str(x.get("cinema_name"))))
    deduped_areas = [a for key in unique_shows for a in unique_categories[key]]
    write_csv(out / "unique_shows.csv", deduped, SHOW_FIELDS)
    write_csv(out / "unique_seat_categories.csv", deduped_areas, AREA_FIELDS)
    fully_priced = all(s["pricing_complete"] for s in deduped)
    known_gross = sum(Decimal(str(s["estimated_gross_inr"])) for s in deduped if s["pricing_complete"])
    total_seats = sum((s["total_seats"] or 0) for s in deduped)
    assumed_booked_seats = sum((s["assumed_booked_seats"] or 0) for s in deduped)
    rollup = {
        "source_cities": len(all_results), "raw_show_rows": len(all_shows),
        "unique_shows": len(deduped), "duplicates_removed": len(all_shows) - len(deduped),
        "total_seats": total_seats,
        "assumed_booked_seats": assumed_booked_seats,
        "assumed_occupancy_pct": round(100 * assumed_booked_seats / total_seats, 2) if total_seats else None,
        "priced_shows": sum(bool(s["pricing_complete"]) for s in deduped),
        "unpriced_shows": sum(not s["pricing_complete"] for s in deduped),
        "known_priced_gross_inr": float(known_gross),
        "estimated_gross_inr": float(known_gross) if fully_priced else None,
        "method": "Assume every unavailable seat, including blocked/held, is booked; multiply category-wise by advertised ticket price.",
        "warning": "Not actual sales or verified box-office collection; only latest snapshot per unique screening is counted."
    }
    (out / "unique_collection_summary.json").write_text(json.dumps(rollup, indent=2), encoding="utf-8")
    (out / "metadata.json").write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "snapshots.json").write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(out / "city_results.csv", summaries,
              ["snapshot_utc", "source_city", "actual_city", "movie_id", "movie_name",
               "cinemas_with_shows", "shows", "seat_categories", "total_seats_across_shows",
               "available_seats_across_shows", "unavailable_seats_across_shows", "unavailable_pct",
               "assumed_booked_seats_across_shows", "assumed_occupancy_pct", "priced_show_count",
               "unpriced_show_count", "known_priced_gross_inr", "estimated_gross_inr"])


def get_cities_file(path: Path, max_cities: int) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)
        if not rows.fieldnames or "slug" not in rows.fieldnames:
            raise ValueError("Cities CSV must include a slug column")
        cities = []
        for row in rows:
            if row["slug"] and row["slug"] not in cities:
                cities.append(slugify_city(row["slug"]))
            if len(cities) == max_cities:
                break
    return cities


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract movie shows and seat availability from District HTML")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", type=Path, help="Offline saved HTML file (no network requests)")
    source.add_argument("--fetch", action="store_true", help="Fetch pages only with permission/approved access")
    parser.add_argument("--url", help="Exact District movie URL (overrides movie/city pieces)")
    parser.add_argument("--movie-id", default="176276")
    parser.add_argument("--movie-slug", default="ramayana")
    parser.add_argument("--city", default="kolkata")
    parser.add_argument("--cities-file", type=Path, help="CSV with prioritized `slug` column (live mode)")
    parser.add_argument("--max-cities", type=int, default=1, help="Maximum city count (default 1)")
    parser.add_argument("--date", help="Single requested date YYYY-MM-DD (live mode)")
    parser.add_argument("--format-id", help="Optional format/language `frmtid` from page")
    parser.add_argument("--acknowledge-permission", action="store_true", help="Confirm you have permission to collect District data")
    parser.add_argument("--delay", type=float, default=10.0, help="Minimum pause between HTTP requests (seconds)")
    parser.add_argument("--out", type=Path, default=Path("output"))
    args = parser.parse_args()
    if args.max_cities < 1:
        parser.error("--max-cities must be >= 1")
    if args.fetch and not args.acknowledge_permission:
        parser.error("Live fetching requires --acknowledge-permission and compliance with District terms")
    if args.cities_file and (args.url or args.html):
        parser.error("--cities-file cannot be combined with --url or --html")
    if args.date:
        datetime.strptime(args.date, "%Y-%m-%d")
    if args.fetch and args.delay < 5:
        parser.error("--delay must be >= 5 seconds")
    if args.url:
        details = parse_movie_url(args.url)
        movie_id, movie_slug, city = details["id"], details["slug"], details["city"]
        format_id = args.format_id or ((details["query"].get("frmtid") or [None])[0])
        date = args.date or ((details["query"].get("fromdate") or [None])[0])
    else:
        movie_id, movie_slug, city = args.movie_id, args.movie_slug, args.city
        format_id, date = args.format_id, args.date
    city_list = get_cities_file(args.cities_file, args.max_cities) if args.cities_file else [slugify_city(city)]
    results = []
    errors = []
    if args.html:
        html = args.html.read_text(encoding="utf-8")
        source_url = args.url or make_url(movie_slug, movie_id, city)
        results.append(extract_snapshot(html, source_url=source_url,
                                        source_city=city, expected_movie_id=movie_id))
    else:
        for index, city in enumerate(city_list):
            if index:
                time.sleep(args.delay)
            url = make_url(movie_slug, movie_id, city, date, format_id)
            print(f"[{index+1}/{len(city_list)}] {city}: {url}", flush=True)
            try:
                html = get_page_html(url)
                captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                result = extract_snapshot(html, source_url=url, source_city=city,
                                          expected_movie_id=movie_id, snapshot_utc=captured_at)
                results.append(result)
                if result["metadata"]["actual_city"] != city:
                    print(f"  WARNING: requested {city}, page resolved {result['metadata']['actual_city']}", file=sys.stderr)
            except Exception as exc:
                errors.append({"city": city, "error": str(exc)})
                print(f"  ERROR: {exc}", file=sys.stderr)
                if "403" in str(exc) or "429" in str(exc):
                    print("Stopping all requests after access restriction.", file=sys.stderr)
                    break
    if not results:
        if errors:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
        raise RuntimeError("No city extracted successfully; review errors and saved page structure")
    save_results(args.out, results)
    if errors:
        (args.out / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    for result in results:
        meta = result["metadata"]
        print(f"SUCCESS {meta['movie_name']} / {meta['source_city']}: "
              f"{meta['cinemas_with_shows']} cinemas, {meta['shows']} shows, "
              f"{meta['seat_categories']} categories, "
              f"{meta['assumed_occupancy_pct']}% assumed occupancy, "
              f"estimated gross INR {meta['estimated_gross_inr']} (blocked + booked assumption; NOT actual revenue)")
        print(f"  Dates advertised: {', '.join(meta['available_dates'])}")
    print(f"Written files: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)
