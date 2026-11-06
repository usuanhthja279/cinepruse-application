# Codex prompt — Discover District's actual supported cities and save a verified catalog

## Goal
Extend the existing `district_movie_extractor` project. Discover and save the *actual* supported city/location roster for **District Movies** (`https://www.district.in/movies/`) based on source-provided location metadata, not a generated population list. Preserve the existing `district_extractor.py`, its offline extraction tests, and the user's collection rule: **all unavailable seats (including blocked/held) are assumed booked for an *estimated* gross value**. This is not verified box-office revenue.

## Known facts / constraints
- The user's November 6, 2026 Ramayana/Kolkata HTML contains Next.js `__NEXT_DATA__` show/cinema/session data and supports offline parsing.
- The published movies landing page visibly has a **Select Location** control, plus links to some popular city pages such as `/movies/mumbai-movie-tickets`. Those links alone are **not** a complete city roster.
- `cities_500_candidates.csv` is a manually prioritized **unverified candidate list**; do not label it as District-supported.
- District's Terms of Service restrict scraping/crawling, reverse engineering and circumventing access controls. **Do not run automatic discovery, reverse engineer private APIs, evade CAPTCHAs/403/429, rotate proxies, harvest credentials, or scrape hundreds of city pages without written permission/approved access.** Prefer obtaining a complete authorized city export or official feed. Browser inspection may be used to learn visible data structures; use a user-provided or authorized export for bulk processing.

## Phase 1 — Investigate location selector and document evidence
1. Read `README.md`, `district_extractor.py`, `city_catalog.py`, and the current tests. Keep existing behavior working.
2. In an ordinary interactive browser, inspect `https://www.district.in/movies/` and its visible **Select Location** interface. Record what the site actually displays: popular cities, search result UI, city/state labels, metro-region aliases and whether the list is paginated or virtualized.
3. Inspect the publicly rendered HTML/embedded Next.js JSON and, where authorized, the location-selector network response visible in browser DevTools. **Document observed URL, response JSON schema, field names, whether it is complete or paginated, and whether access/use is authorized. Never guess endpoint names.** Avoid relying on hardcoded build IDs.
4. If the complete roster is exposed by a permitted official JSON feed/export, save a sanitized response (no cookies, tokens, personal data) under `data/cities_raw/` with acquisition date and source metadata. If only a partial list is available, save it with `completeness=partial` and explicitly report that the full roster remains unverified.
5. If authorization is missing, stop live acquisition. Continue with offline importing of any user-provided exported data, and describe how to obtain permission or a licensed city catalog.

## Phase 2 — Normalize all received city records
Extend `city_catalog.py` as necessary to accept authorized HTML/JSON/CSV saved files without accessing the network, with tests for the **actual** observed schema.

Write:
- `data/cities/district_cities.csv`
- `data/cities/district_cities.json`
- `data/cities/city_aliases.json`
- `data/cities/discovery_report.json`
- A raw input provenance manifest in `data/cities_raw/README.md`

Required normalized columns: `name`, `slug`, `city_id`, `state`, `latitude`, `longitude`, `source`, `source_path`, `confidence`, `checked_at_utc`. Add `is_active` / `has_movie_inventory` only if explicitly evidenced. Do not invent missing IDs/coordinates or claim a slug inferred from a name is source-verified.

Normalization rules:
- Deduplicate by source-provided city ID, otherwise by canonical source slug; flag slug-to-ID conflicts for human review.
- Preserve city display name, state/region, raw city ID, raw slug and any observed aliases. Example: **Delhi NCR** should not be split into fabricated standalone city feeds.
- Distinguish cities, localities, theaters and metro regions; don't count cinema entries as cities.
- If a data source includes a `total_count` and pages/cursors, record proof that every page is present. If the selector only returns 20 popular results, say **partial**.
- Existing `cities_500_candidates.csv` stays under a *candidate* filename; never overwrite a source-verified file with guesses.

## Phase 3 — City coverage, prioritization and 99% target
- Establish separate counts for (a) all source-supported locations, (b) locations with cinemas, (c) locations with active shows for **one selected film**, and (d) incremental unique shows for **all films** over the same date window. A city in the selector may not currently have movie inventory.
- Do not equate population ranking with show-count ranking.
- If approved aggregate show-session data is available, deduplicate by movie ID + cinema ID + provider/session ID + show time. Metro boundary feeds can overlap.
- Rank 500 locations by marginal/incremental unique session contribution to all-film show coverage, not arbitrary city order. Calculate `coverage_pct = unique_sessions_in_top_500 / unique_sessions_in_all_verified_locations * 100` and record the data window. **Never report 99% until supported by a measured numerator and denominator.**
- Where no authorized complete show census exists, export `top_500_candidates.csv` with `coverage_pct=null` and clear evidence/status flags.

## Phase 4 — Connect with movie extractor
- Use `district_extractor.py --cities-file ...` only when specifically authorized. Default to offline saved-HTML parsing; keep network collection opt-in and low volume.
- Respect `--max-cities`, request pacing, error logs and 403/429 stop; no login automation or booking requests.
- Preserve collection math: `assumed_booked = total_seats - available_seats`, `estimated_gross = sum((category_total - category_available) * category_ticket_price)`, including blocked seats. Label all outputs as estimated/assumed. Never count multiple polling snapshots or overlapping city lists as separate tickets.
- Empty/blocked/error responses are **unknown**, not proof of zero shows.

## Tests and acceptance criteria
1. Unit tests cover actual saved city schema, dedup, aliases, incomplete lists, missing city IDs, missing slugs, blank/malformed records and JSON/CSV parity.
2. An offline command must reproduce the existing **117 Ramayana Kolkata shows / 29 cinemas / 410 seat-category rows**, with **7,202 assumed booked seats** and **₹3,948,610 estimated gross** from the saved HTML.
3. All generated city files have explicit provenance and verification status.
4. The report states the count of discovered unique cities and whether the *complete District roster* was proven. If not, it says **NOT VERIFIED**.
5. No code or documentation suggests the top 500 truly cover 99% without a measured census.
6. Output a concise implementation summary: observed location data source/schema, file paths, record counts, completeness proof or blocker, commands and test results.

## Start here
Inspect the local repository first, then run the offline parser and city-catalog sample tests. Design the discovery around observed, authorized data rather than guessing District API paths. Do **not** create a fake city list and call it official.
