# Claude UI integration plan

## Audit and preservation checklist

- Use the supplied Claude reference for the editorial visual language: Fraunces and Manrope type, parchment light theme, near-black/plum dark theme, amber/coral/teal accents, rounded cards, poster treatment, and compact charting.
- Keep the five user-facing routes: Overview, Pulse, Map, Shows, and Capture engine. Keep date and capture selectors separate.
- Treat the supplied HTML's embedded `D` object as demonstration-only. It is not a source of project metrics.
- Preserve the user's confirmed-revenue accounting instruction in the application. Preserve its booked-plus-blocked seat basis and payment-confirmation note. Do not claim independent payment reconciliation.
- Show matched-session deltas only when there is a non-empty, eligible matched comparison. A zero-match export is unavailable, not a zero-ticket change. Keep negative and release movements.
- Keep geography limited to the existing 36-region display geometry and city-feed coverage. The city-to-state reference is not a cinema-to-state allocation.
- Keep the UI read-only against the existing service. No collector process, scheduler, DB, or raw HTML changes are included.

## Component and data map

| UI component | Current source | Interpretation |
| --- | --- | --- |
| Overview snapshot KPIs and capture selector | `dashboard/data/district_hourly_runs_latest.json` and selected `run_summaries.json` | Saved District hourly export; as-of time comes from generated metadata. |
| Matched hourly movement chart | `matched_delta_*.json` referenced by the summary | Identical eligible sessions only; zero-match comparison is withheld. |
| Saved screening table | `unique_screenings_<date>_<hour>_IST.csv` | Deduplicated saved hourly capture, client-side search and page controls. |
| Advance service-date list and summary | Read-only `/api/live/dates` and `/api/live/summary` | Current captured future service dates and latest capture metadata. |
| Advance screening rows | Read-only `/api/live/shows` | Server-side paging and filtering by service date. |
| Map and state drawer | `india_state_map_simplified.geojson`, `city_state_mapping_2026-11-07.csv`, selected-run coverage CSV | Selector-label coverage only. No cinema or state revenue assignment. |
| Capture engine | Hourly run summaries and selected-run city coverage | Captured, failed, and uncollected feeds remain distinct. |

## Data audit findings

The checked-in summary currently contains six capture windows, `00:00` through `05:00` IST, and five adjacent comparison files. The actual source records show 557 captured feeds at `00:00`; 1,012 at each `01:00` through `04:00`; and 931 at `05:00`. For `01:00`, 309 feeds are marked failed. At `02:00` through `04:00`, the same 309 are not collected in that window, not failed. `05:00` has 390 not collected. This differs from the handoff's example values, so the UI follows the committed JSON instead.

The `00:00` to `01:00` comparison has zero matched future sessions; it must display as awaiting comparable captures. The next four comparisons have matched sessions and real stored positive, released/corrected, and net seat changes.

## Current API contract and gaps

The existing service exposes `/api/live/dates`, `/api/live/summary?date=...`, `/api/live/cities?date=...`, `/api/live/shows?...`, and `/api/live/export.csv`. The UI consumes dates, summary, and paginated shows. It does not need a new endpoint for this UI update. State-level cinema rollups, a verified venue-to-state mapping, and a complete official city roster remain unavailable and are deliberately not synthesized.

## Files planned/changed

- `dashboard/index.html`: five-route shell, data-bound Pulse metrics, and route for saved screening exploration.
- `dashboard/assets/claude_ui.css`: reference-aligned responsive light/dark styling and motion/accessibility rules.
- `dashboard/assets/movie_intelligence.js`: saved theme, route semantics, focus-safe map drawer, and zero-match handling.
- `dashboard/tests/test_screenledger_data.py`: align capture-window assertion with the committed data.
- `dashboard/tests/test_claude_ui_contract.py`: guard visual tokens, route wiring, and demo-data exclusion.
- `dashboard/README.md`: current UI and data flow.
- This plan and `CLAUDE_UI_IMPLEMENTATION_REPORT.md`.

## Verification plan

Run dashboard data tests, collector unit tests (read-only validation only), JavaScript syntax check, HTML structure check, and static route/theme contract tests. If Playwright and a browser are installed, use them for route, theme, keyboard, 390px and desktop viewport checks. No visual screenshot claim is made without an actual browser run.
