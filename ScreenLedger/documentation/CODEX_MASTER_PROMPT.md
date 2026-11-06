# Copy/paste this entire prompt to Codex in the actual ScreenLedger / cinema analytics working tree

You are integrating an existing **ScreenLedger movie analytics** project. **Do not restart, rearchitect unrelated parts, or switch branches.** The package I supplied includes `collector/` (District offline extractor v2 + new `smart_collector.py`, `collector_status.py`, unit tests and PowerShell launch commands) and `dashboard/` (movie-first prototype and official-map geometry importer). Read `README_START_HERE.md` and `documentation/PHASE_PLAN_AND_DATA_RULES.md` first. Current date is 2026-11-06 IST and planned first service date is **2026-11-07**, beginning 00:00 IST.

## Goal

**Prioritize getting a real, auditable, approved extraction running at midnight**, then refine scheduling and UI. Source scope matters: the existing Python extractor parses saved **District.in** Next.js HTML. It is not a tested BookMyShow collector. A previous `cinepulse_mvp` prototype relates to a different Android/emulator workflow. Before using any source, determine precisely which platform has documented permission and a working capture path. If approval is absent or live source cannot be verified, test offline and report the blocker; do not fabricate live numbers.

## P0 — in the first implementation batch

1. Inventory the current repo, report existing codepaths/configuration and source dependencies. Preserve the active branch and avoid unrelated changes.
2. Copy/merge source code from `collector/` into the existing backend module; preserve working parser and its existing tests, and do not discard any existing snapshots.
3. Run `py -3 -m venv .venv`, install `collector/requirements.txt`, then `python -m unittest discover -s tests -v`. Existing package has **15 tests passing in its build environment**; re-run locally and fix environment-specific failures. Confirm `--plan-fixture` uses saved November 6 HTML with **NO** network request.
4. Validate exactly one live authorized movie+city+service-date response: correct actual/source city, stable show/session/venue IDs, `show_datetime_ist` timezone, capacity/tier records, room/screen identity, capture timestamp, and source error propagation. Stop on 403/429 or changed HTML; no bypass. If source is BookMyShow, build a real provider adapter and tests rather than passing BMS HTML to the District parser.
5. Prepare a persistent run for the service date **2026-11-07 IST**, starting **00:00**. The collector must wait when launched early, do a marked `catch_up` if launched late, and survive restart without resetting the history. Start it locally only when provider authorization and operator instruction permit. Do NOT claim the collector ran if it did not.
6. On every successful capture, write raw source archive and parsed session observations to SQLite. On failure, record error with time and `city/movie/date` context. Keep persisted DB outside volatile build folders. Provide console verification commands and an operator runbook.

## P1 — critical time-aware scan rule

For every newly discovered future show, persist a scan at **T minus 5 minutes**. Example: hourly poll at **00:00** discovers a **00:35** screening: fetch again at **00:30**, then preserve that result even when the screening has vanished from **01:00** page. The 00:30 capture is a final **pre-show inventory reading**, not guaranteed actual sold tickets. Compare a `T-10` fallback if T-5 is missing due to provider cutoff or scan latency.

Keep an append-only per-session history. Use persistent priority scheduling so a near-start show gets precedence over large country/city sweeps. Avoid duplicate network calls when one authorized movie/city page fetch can satisfy nearby jobs. Coalesce responsibly, preserving the before-start deadline, and never fire a page request per session if one page already contains them all. All time comparisons must be timezone-aware; no UTC midnight mixups. Mark `on_time`, `late_discovery`, `not_visible`, `missed`, `failed` separately.

## P2 — reliability and stats

Distinguish session uniqueness from snapshot uniqueness, redirected-city fallbacks from true coverage, and known zero shows from missing source. A disappearing show should retain its last valid *before-start* count, not become a zero record. If an old reading is the latest, expose freshness and quality. One-hour signal can only be computed from comparable matching shows around one hour apart; capacity changes or incomplete coverage must be excluded or flagged. The number is **net unavailable-seat change**, potentially negative due to hold releases, *not tickets booked*. `gross proxy = SUM(unavailable seats × quoted tier price)` is a hypothetical value and must never be named actual revenue. Simulated UI values never get promoted to live data without genuine captures.

## P3 — link the dashboard

Preserve movie-first home search (current+historical), Ramayana detail page, today/hour/daypart summaries, hourly chart, India map → state/UT → district/city → cinema drilldown and data-health views. Show source, data date and simulation status on every view. Wire `collector_status.py` or a normalized API only after the actual collection passes acceptance; do not invent state/city coverage. Preserve the v4 official GIS downloader and waiting state. Download/validate **official Government of India/NWIC/Survey of India** geometry and visually compare against the 2026 political map; do not substitute unofficial polygon coordinates.

## Deliverables from Codex

A. Implementation changes on the **existing branch**, grouped by P0/P1/P2/P3 with minimal diffs and meaningful commits.

B. `OPERATIONS_2026_11_07.md`: exact Windows PowerShell command to run at midnight, dependency setup, source authorization decision, expected logs and status checks, restart/recovery procedures, guardrails, and troubleshooting.

C. Test evidence: parser fixture unchanged (117 shows, 29 cinemas, 27,663 total and 7,202 **unavailable** seats, hypothetical ₹39,48,610), 00:35→00:30 timing test, provider mismatch and cutoff tests, persistence/restart tests, 403/429 stop tests, missing-show/late-discovery test, no double-counting and correct last-hour interval test. Show the command and results rather than saying tests passed without running them.

D. A brief status report: **implemented/tested**, **not yet verified live**, **blocked**, **next phase**. Make sure you don't describe the offline v2 sample or simulated nationwide replay as November 7 live data. Call out that official GeoJSON actual polygons remain pending until fetched/visually verified.

E. A priority-ordered punchlist so we can expand only after the first authorized collector runs correctly.

**Do not run unauthorized scraping or modify bookings/accounts. Never claim permission from the existence of a CLI flag. Never silently relabel District as BookMyShow.**
