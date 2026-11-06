# Codex implementation handoff — v3 official India geography

Work **on the current branch** of the existing District extractor/UI project; do not redesign unrelated pages. Treat `index.html` as the state-navigation interaction prototype, not a live analytics implementation.

## Goals

1. Retain the movie search → Ramayana → seven analytics views from v2.
2. Replace unsourced India silhouette with **actual Survey of India-compatible official state/UT polygons**. Align the international border with SoI's latest 2026 political map, including complete Jammu & Kashmir/Ladakh depiction. Never use the obsolete v2 silhouette or an unsourced generic global border dataset as a fallback.
3. Show a state choropleth with hover data (shows, weighted unavailable occupancy, last-hour matched movements, estimated listed seat value, coverage/freshness), click → state detail, then district/city/venue drilldown. Support keyboard, touchscreen, responsiveness, focus management, and no-data state.
4. Only aggregate observed data from real extractor results; the prototype's ten-city replay is simulated, and this must remain explicit.

## Source acquisition and verification

- From `https://surveyofindia.gov.in/pages/political-map-of-india`, obtain the English 13th edition/2026 political map; use it as authoritative **cartographic reference**.
- From `https://nwdp.nwic.gov.in/dataset/state-boundary`, download the government-hosted state boundary GeoJSON ZIP; inspect its revision and actual feature names/geometry. It may be older than the 2026 SoI map. Check the northern boundary against the map; if discrepant, obtain corrected authoritative vector geography instead of editing a disputed polygon by guesswork.
- From `https://nwdp.nwic.gov.in/dataset/district-boundary` or the Survey of India administrative database, acquire district geography. Validate state/district code joins.
- Document dataset source URLs, actual download checksums, edition dates, validation results, and terms of use. Build a local validated `states.geojson` / `districts.geojson` from the authoritative dataset for production.
- If download unavailable or revision uncertain, **do not invent shapes or claim successful map verification**. Keep the state index and show explicit boundary-unavailable state.

## Aggregations and UX

- Structure joins: `movie -> performance date -> observed show -> physical cinema -> official district -> official state`. Keep `source_city_feed` as provenance, not a geographic truth.
- Deduplicate by stable screening/session key across overlapping District city feeds.
- Preserve every observed show throughout its performance day, freeze last reliable pre-start reading if listing disappears, and flag stale/missing/cancelled shows.
- State + district + city totals use seat-capacity-weighted occupancy and a ticket-value proxy that includes booked and blocked seats. Avoid paid-sales claims.
- The last-hour figure compares **matching show-category keys** in consecutive snapshots and excludes brand-new sessions from like-for-like movement. Distinguish net increase, positive increase, and seat releases. Return `null` until two comparable observations exist.
- On hover, show name, show count, occupancy, last-hour movement, unavailable-seat value and observed-at. On click, open a responsive state-detail surface with city/district/cinema tabs and a back path to India.
- For West Bengal, show Kolkata, Howrah, Serampore from the verified saved file. Durgapur and Siliguri show unknown/not collected until collection is performed. Do not extrapolate Kolkata feed values to the state.
- All states/UTs (28 states + 8 UTs) should be navigable with accessible search even when polygon shape isn't available.

## Acceptance tests

- `index.html` works standalone without build dependencies; no existing views break.
- Official state polygons render as discrete selectable regions, including small UTs/islands, with tooltip and hover/focus. A polygon must be mapped by official region code, not its array index or approximate centroid.
- Distinct Jammu & Kashmir and Ladakh features appear and are verified against the correct SoI map before any 'official border' claim.
- State click changes scope; district click shows associated cities/venues; navigation handles back/reset on mobile.
- Verified West Bengal shows 117 shows / 29 cinemas / 27,663 capacity / 7,202 unavailable / ₹39,48,610 assumed value; no last-hour figure from one snapshot.
- State totals are consistent with sums of de-duplicated underlying cinema/session figures; no double counts across feed overlaps.
- No-city/no-state states show **Not collected**, never 0% or ₹0 unless observed and verified.
- Demo mode has an unmistakable simulated label; date/clock in IST.
- Record automated tests, real browser screenshots and actual source-provenance evidence in the repo.
