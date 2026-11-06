# Codex follow-up: real data dashboard + official India state map

Do this **after** validated data extraction and scheduling. Read `dashboard/MAP_SOURCE_AND_RELEASE_CHECKLIST.md`, `dashboard/CODEX_INDIA_MAP_V3_HANDOFF.md`, `documentation/PHASE_PLAN_AND_DATA_RULES.md` and `dashboard/index.html`. Preserve the movie-first design and its existing local interactions.

1. Implement a normalized API/export from collector with show/venue/city/state/movie/day, snapshots and final-pre-show data, observed times and freshness/provenance flags. Ensure `null` ≠ zero, fixture/simulated ≠ live.
2. Home page: currently tracked movies in cards plus a searchable film archive; film selection opens a date-scoped detail with today KPIs, dayparts and hourly net unavailable seat changes.
3. India: official state boundaries, all 28 states + 8 UTs; no wrong or placeholder north shape. Hover states shows show count, weighted availability/occupancy proxy, estimated hypothetical seat value and coverage. On click, drill into a state with city/district and cinema tabs, show count, occupancy proxy, last-hour net unavailable-seat change, and per-show pre-start status; let a user drill to a cinema. Do not mark uncollected regions as zero.
4. Geometry source must be Government of India NWIC state-boundary GeoJSON with Survey of India producer attribution; use provided `fetch_and_embed_soi_map.py` and verify SHA, 36 normalized features, J&K and Ladakh separation and exact comparison with official 2026 political map. Verify license for intended use. Do not replace missing features with unofficial third-party data.
5. Responsive mobile layout, accessibility and at least one screenshot/test for each view; record whether map is real official geometry or import placeholder. No synthetic nationwide figures in live UI.

Provide a delta list, test results, verification evidence and remaining tasks. No unrelated redesign and no change of branch.
