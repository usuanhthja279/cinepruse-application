# District Movie Extractor v2 — offline-first Python proof of concept

## Current ScreenLedger integration

At each process restart and each IST date rollover, the scheduler starts a new discovery pass over the full city target list for the live date and each of the three advance dates. After each date's discovery pass finishes, later sweeps use that date's roster of cities with successful captures containing shows on that service date. Existing captures and pre-show jobs are retained. Advance sweeps start at the configured :20 and :35 slots and share capacity with live and pre-show scans, so they can begin late during a busy sweep.

Each live city capture discovers District's advertised language format identifiers and fetches each language page without applying a screen-format filter. Shows from all returned pages are merged into one city capture. Language, auditorium, screen format and format group are stored in `observation_details`; older observations have no corresponding details until recollected. If a language page fails or returns a different format or city, the city capture fails instead of publishing a partial success. Multiple language requests increase run time and can delay pre-show scans; monitor the due-time logs. District's response determines which details are available.

`multi_city_scheduler.py` records each attempt's requested service date, while `smart_collector.py` stores it in `captures.service_date_ist`. A successful capture stores only screenings for that requested show date. On an existing database the collector adds this nullable column and an index at startup; historical rows remain null until safely attributable.

The multi-city scheduler shares a fixed five-worker pool. A city appears in the hourly roster only after a successful initial live-date capture; each advance service date starts with the full selector target list, then persists a separate roster containing only cities with successful captures that actually listed shows for that date. D+1 scans repeat every two hours, and D+2/D+3 scans repeat every three hours. When multiple advance dates are due, their city queues are interleaved so D+1 cannot starve D+2 or D+3. Due pre-show city scans take priority: simultaneous due cities borrow up to all five existing workers, while new hourly and advance work pauses until the urgent backlog drains. It never creates extra threads during a burst. SQLite uses WAL with a busy timeout; workers skip repeated schema setup, and stale-job cleanup defers if a concurrent write holds the database. Pre-show readings are useful only before show start; a scan that finishes after the show starts cannot be treated as a final pre-show reading.

`live_dashboard_server.py` serves a read-only API for Movie Intelligence. `/api/live/dates` lists recorded service dates, and the date-scoped summary, city-coverage, screening, and CSV routes select captures by service date rather than by capture timestamp. Legacy successful captures are attributed only when their screening rows identify exactly one date; legacy empty advance captures are not guessed into a date. The prototype calls these routes every five minutes and exposes future-date screening rows, confirmed revenue on the project owner's supplied payment basis, pricing completeness, and city coverage.

Start the API and dashboard from PowerShell in this folder with `.\START_LIVE_DASHBOARD.ps1`. The API reads `collector_data/smart_collector.sqlite` in read-only mode. The database and any raw provider pages are local runtime artifacts and must stay out of Git; parsed exports and source code may be versioned.

Run the tests with `python -m unittest discover -s tests -v`. The service-date API behavior has regression coverage in `tests/test_service_date_dashboard.py`.

This project parses **user-saved movie page HTML** and extracts cinema/show/session data from embedded Next.js `__NEXT_DATA__` JSON. It now calculates **estimated gross collections by assuming every unavailable seat, including blocked/held inventory, is booked at the listed category price**. It also includes an **offline city-catalog importer**, a 500-location **candidate** list, and a Codex prompt for discovering the *actual* supported cities through authorized data.

**Tested using the attached November 6, 2026 Ramayana/Kolkata HTML.** It does not independently verify live fetch access, all supported District cities or true ticket-sales revenue.

## Quick start — Windows PowerShell

Extract the ZIP and open PowerShell inside the `district_movie_extractor` folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# No website access needed — run the saved HTML fixture:
.\.venv\Scripts\python.exe district_extractor.py --html fixtures/ramayana_kolkata_2026-11-06.html --city kolkata --out output

# Validate the parser and collection calculation:
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Inspect collection estimates:
Get-Content output\unique_collection_summary.json
Import-Csv output\shows.csv | Select-Object -First 5 movie_name,cinema_name,show_datetime_ist,assumed_booked_seats,estimated_gross_inr | Format-Table
```

If `py` is not available, replace `.\.venv\Scripts\python.exe` with `python` after creating the virtual environment. Python **3.10+** is required. The `tzdata` dependency supports timezone conversion on Windows.

### Expected results from the supplied HTML

| Metric | Value |
|---|---:|
| Movie / city | Ramayana / Kolkata |
| Cinemas | 29 |
| Unique sessions (single captured date) | 117 |
| Seat category records | 410 |
| Total seat slots | 27,663 |
| Available seat slots | 20,461 |
| **Assumed booked + blocked seats** | **7,202** |
| **Assumed occupancy** | **26.03%** |
| **Estimated gross ticket value** | **₹3,948,610 (₹39.49 lakh)** |

**This is not actual collection.** The calculation treats even blocked/held/unavailable seats as assumed bookings, excludes unobserved sessions and may exclude additional booking fees/taxes. It represents a single snapshot, not cumulative sales over time.

For each seat tier: `assumed_booked = total - available` and `estimated_gross_inr = assumed_booked * displayed_price`. The total is the sum over all priced tiers. If some show/category data is missing, `estimated_gross_inr` is null and a separate known-priced subtotal is provided rather than pretending there is full-price coverage.

## Output files

- `output/shows.csv` — original source rows, show date/time in IST, cinema IDs, seat counts, **assumed bookings and estimated gross**.
- `output/seat_categories.csv` — per-tier seat count, ticket price and estimated gross.
- `output/city_results.csv` — per-source-city show counts and collection estimates.
- `output/unique_shows.csv` — deduplicated cinema sessions across processed city snapshots.
- `output/unique_seat_categories.csv` — category records aligned with the selected unique sessions.
- `output/unique_collection_summary.json` — **deduplicated** estimated gross, assumed bookings, data completeness and warnings.
- `output/metadata.json` — movie details / available screening dates.
- `output/snapshots.json` — normalized source snapshots for auditing.
- `output/errors.json` — present only if a requested live extraction fails.

## Generate city CSV/JSON from an authorized saved catalog

The package has an **illustrative three-city input fixture**. It is **not** District's official export:

```powershell
.\.venv\Scripts\python.exe city_catalog.py --source-file fixtures/sample_authorized_city_export.json --out city_catalog_output
Get-Content city_catalog_output\city_discovery_report.json
Import-Csv city_catalog_output\cities_discovered.csv | Format-Table
```

Replace the `--source-file` path with a legitimately obtained full city list in `.json`, `.csv` or saved `.html` format. The importer makes **zero network requests** and saves `cities_discovered.csv`, `cities_discovered.json` and `city_discovery_report.json`. The report always marks full roster verification as **false** because it cannot prove an input dump was complete. Codex must collect provenance, published counts and pagination evidence before treating it as exhaustive.

The bundled `cities_500_candidates.csv` has 500 **heuristic candidate** cities, not a verified list of District-supported locations or a demonstrated 99% show-coverage ranking. Use `CODEX_CITY_DISCOVERY_PROMPT.md` to guide Codex in obtaining and validating the actual roster. A proper ranking requires an authorized cross-city census of unique show sessions across **all movies**, not just Ramayana.

## URL format and permission-gated live mode

A movie's URL can be parameterized as follows:

`https://www.district.in/movies/{movie-slug}-movie-tickets-in-{city-slug}-MV{movie-id}`

Example: `https://www.district.in/movies/ramayana-movie-tickets-in-kolkata-MV176276`.

District's published Terms of Service restrict copying/scraping/crawling and circumventing access limitations. Use a licensed/approved feed if you need ongoing live collection; **do not run the following mode unless you have permission**. Its opt-in flag acknowledges permission but does not grant it.

```powershell
# Single city (only after approved access):
.\.venv\Scripts\python.exe district_extractor.py --fetch --acknowledge-permission --movie-slug ramayana --movie-id 176276 --city kolkata --out output_live

# Source-verified city list, small authorized test only:
.\.venv\Scripts\python.exe district_extractor.py --fetch --acknowledge-permission --cities-file city_catalog_output/cities_discovered.csv --max-cities 2 --delay 10 --out output_two_cities
```

The fetcher stops on 403/429 and does not bypass blocks, log in, book seats, or contact any seat-layout endpoint. Dates may be requested using `--date YYYY-MM-DD`; `--format-id` can be provided if determined from actual page data. There is no claim that any movie is available in all cities.

## Notes

- Venue/film booking URLs and changing showtimes must be verified against source records; never fabricate sessions.
- `showTime` in the supplied fixture is UTC without an offset; the program converts it to IST. Reconfirm this field across other films before scaling.
- `source_city` vs `actual_city` detects location fallback/redirect; a mismatched city should not count as verified coverage.
- The deduplicated output uses the newest captured snapshot of a session if multiple city records overlap. Historical snapshots are preserved separately; they are never summed as separate sales.
- For any city or film not present, missing/failed data means **unknown** rather than zero shows until a valid complete response proves otherwise.
- `CODEX_CITY_DISCOVERY_PROMPT.md` contains the implementation task for Codex, including source provenance, aliases, completeness checks and a measured top-500 coverage target.
