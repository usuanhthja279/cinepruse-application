# Phase plan and engineering acceptance criteria

**Run date:** Saturday, 7 November 2026 (IST, UTC+05:30). Start-of-day baseline **00:00 IST**, with all timestamps stored in UTC and rendered in IST. End-of-day boundary is **2026-11-08 00:00 IST**. A "day" must refer to the screening's **local calendar date**, not the extraction's UTC day.

## Phase 0 — pre-midnight critical path (now)

**P0.1** Verify the source. `district_extractor.py` is proven with a saved District HTML only. Confirm authorized provider access; preserve provider-specific provenance (District vs BMS), film ID, city slug, service date, payload capture time, actual city (detect redirect), session identifiers, per-tier capacity/availability and price. If the live source changes or returns 403/429, stop; no evasion, no rapid retries.

**P0.2** Run the included `15` offline unit tests and `--plan-fixture` command. Confirm Windows 3.10+ zoneinfo/tzdata support. Free up disk space; keep app/emulator process overhead low if a permitted BookMyShow acquisition adapter is selected. Prefer reliable collection over maximizing cities before the first successful run.

**P0.3** Start **one authorized movie + one verified city** at 00:00. Capture raw response and normalized snapshot; persist only after parsing validates. Verify at 00:05 that `captures` and `observations` are populated. If no valid source, record a failure, **not** false zero data. Never present an offline fixture as a midnight collection.

## Phase 1 — dynamic showtime-aware scheduler (critical)

At baseline `00:00` get the complete currently listed schedule for the selected film/day and build a registry keyed by `provider + movie + city + cinema + provider_session_id + show_start_ist + format`. Keep both source IDs and a stable normalized key. Persist historical observations as append-only. Never sum repeated snapshots as new sales.

For **each** future show, schedule a **T-5 minutes** capture. Example:

| Local IST time | Event | Action |
|---|---|---|
| 00:00 | Hourly baseline | Discover 00:35 show, record available/unavailable seats, schedule 00:30 |
| 00:30 | Pre-show | Re-fetch same movie + city page, record 00:35 final pre-show availability |
| 00:35 | Screening begins | Freeze last valid pre-start observation for that screening |
| 01:00 | Next hourly scan | Discover/update other screenings, **do not erase** the now-absent 00:35 screening |

Implement a persistent priority queue where `pre_show` has precedence over `hourly`; coalesce jobs when the same page fetch covers multiple nearby screenings (after measuring how early a fetch may safely satisfy each T-5 target). For shows first discovered *after* T-5 but before show start, save their immediate observation as `late_discovery`, not on-time final. For shows already begun, status is `missed`, not `sold_out` or zero. Flag missed/late schedules in dashboard data-health view.

The reference scheduler currently includes the hourly+T-5 loop, SQLite persistence, crash/restart state, tests and a single source-city fetch adapter. Codex should add request-budget instrumentation, bounded parallelism **after provider approval**, T-10 fallback where observed provider cutoff warrants it, and enough lead time to avoid a long national scan blocking a near-start scan. No busy-looping or circumventing rate limits.

**Acceptance:** fake clock test proves 00:35 show gets 00:30 pre-show scan even when 01:00 will not show it; tests cover 00:01/23:59, late starts, retries, 403/429, persisted restart, redirect, vanished shows and no duplicate snapshots as sales.

## Phase 2 — reliable daily extraction and inventory completeness

Capture, for each snapshot: `captured_at_utc`, provider, movie ID, source and actual city, requested service date, cinema + screen + session key, show start IST, total/available/unavailable seats, price tiers, availability status, fetch reason, parser version, error status, and source hash or raw response path. Track scheduled, first-seen, last-seen and last-valid-prestart, not just latest. When source lists future dates, do not assign those sessions to today's totals. Make date parser and midnight boundaries explicit. Store successful extracts in SQLite and raw payload archive before adding large-scale Postgres.

Check provider page response completeness; compare returned show dates with expected target date. No inference of 'no shows' if HTTP errors, redirected city, missing Next.js data, or partial payload. On a valid complete zero-show source, permit zero with a `verified_empty` status. Data health is a core view, not secondary UI.

**Acceptance:** local persisted run recoverable after process restart, no duplicate session counts across repeat fetches/city aliases, and auditable raw record for every statistic.

## Phase 3 — metrics (only after interval comparison is valid)

For a **single screening** at one timestamp: `unavailable_proxy = total_seats - available_seats` and `inventory_occupancy_proxy = unavailable_proxy / total_seats`. This includes blocked/held seats and **is not verified tickets sold**.

For a **one-hour change**: compare the *same stable session* at times near `T` and `T-60 minutes`, only when inventory capacity is unchanged and both readings are valid. `delta_unavailable = unavailable(T) - unavailable(T-60m)`; it can be negative because holds are released. Flag incomplete pairs rather than silently treating all newly discovered sessions as zero at T-60. `collector_status.py` reports the number of comparable sessions. A 30-minute comparison must be labeled a 30-minute comparison, not hourly.

For **show-level final inventory**: use the last valid snapshot *strictly before show start* (prefer T-5); if never seen near start mark `partial`. For **day total proxy**: take **one** latest/final snapshot for each unique show whose local start is within the day; do **not** sum every polling snapshot. `price_tier × unavailable_seats` is a **hypothetical seat value**, not actual box-office receipts. Show a known-priced subtotal and unknown coverage if price tiers are incomplete.

For region/collection totals, normalize cinema→city→district→state/UT and avoid NCR/geographic fallbacks. State sums are only over successfully covered cities; label the geographic coverage percentage when a verified city roster exists. No claim of nationwide data from Kolkata alone.

**Acceptance:** every UI metric has a source/capture timestamp, `simulated|fixture|verified_snapshot|live_permitted` provenance, comparable denominator, and null/no-data behavior. No double counting.

## Phase 4 — launchable UI/API

Preserve existing movie-first overview with searchable current + historical movies. Movie detail: today summary, showtimes by daypart (morning, afternoon, evening, night, late night using local hour cutoffs), hourly net unavailable seat changes, cinema ranking, city table, data quality and movie/date selection. India map: official 28 states + 8 UTs; hover shows show count, weighted inventory occupancy proxy, hypothetical ticket value, capture/coverage status. Click opens state modal/page with cities (e.g., Kolkata, Howrah, Durgapur, Siliguri where actually collected) → cinemas → individual shows with final-capture quality. Charts distinguish historic daily vs hourly data and explain missing values.

Connect dashboard data only after an API/export explicitly marks the real source. Replace simulated values rather than presenting them as extracted. Provide reproducible feed fixtures and integration tests.

## Phase 5 — official India map

Use **only** the official [Government of India National Water Data Portal state-boundary GeoJSON](https://nwdp.nwic.gov.in/dataset/state-boundary), with Survey of India provenance as recorded in the v4 package. `dashboard/fetch_and_embed_soi_map.py` can validate and embed the downloaded archive. Confirm 36 state/UT features, Jammu & Kashmir and Ladakh separately, latitude/longitude ranges, clipping/simplification integrity, official map attribution/reuse rights, and human visual comparison against [Survey of India 2026 political map](https://surveyofindia.gov.in/pages/political-map-of-india). Do not replace official disputed northern boundaries with unofficial third-party shapes. Geometry is currently pending acquisition/verification; keep existing placeholder until complete.

## Phase 6 — city, movies and scaling

Increase from 1 approved city/film to a measured small cohort, then expand movie catalog, cinema mapping and historic records. Use provider-authorized city discovery; the 500 candidate cities are **not** confirmed supported locations. Rank by *measured unique screening coverage*, not name-population guesses. Schedule capacity and request budgets based on measured response latency and pre-show deadline slack, process hourlies opportunistically, back off on failures, and resume from SQLite. Add reporting/alerting for stale data and missed T-5 jobs, then production monitoring and release.

## Non-negotiable guardrails

- **No provider authorization → no live scraping.** A CLI permission flag is an acknowledgment, not a legal license.
- No seat-layout calls, booking actions, login automation, CAPTCHA circumvention, IP rotation, or evasion.
- Do not equate unavailable inventory with confirmed sold seats or estimates with actual box office.
- Do not compare unrelated provider sources as the same metric. Distinguish District from BookMyShow.
- Do not ship synthetic coordinates as Government of India geometry.
- No unrelated UI refactors; start extraction first.
# Current advance-booking data path

The implemented path is:

```text
multi-date scheduler (target service date)
  → smart_collector captures.service_date_ist
  → observations keyed by capture and screening session
  → read-only live API filters on service_date_ist
  → Movie Intelligence advance-booking date selector and paged screening table
```

The observation timestamp describes when District was checked; `service_date_ist` describes the date the scheduled show belongs to. These are separate dimensions. The API picks the latest attempt per city for the selected service date, counts an error as failed, and only uses successful captures to produce screening totals. Overlapping city results are ranked by stable `session_key`; they are not added as separate sessions. A failed request and an uncollected target are unknown coverage, not evidence of zero shows.

For pre-migration successful captures, the API can infer a service date from observations only when all rows on that capture agree on one date. Legacy errors may use their collection-day window. Empty legacy captures have no evidence to assign them to an advance date, so they stay unassigned. New captures and errors store the requested date explicitly. The UI refreshes this API every five minutes while keeping the saved hourly history and matched-hour comparison view intact.

The local database schema migration adds `captures.service_date_ist` and an index during collector startup. The live dashboard opens the database read-only. Keep the SQLite database and raw provider pages out of Git; version source, documentation, and parsed/public exports.
