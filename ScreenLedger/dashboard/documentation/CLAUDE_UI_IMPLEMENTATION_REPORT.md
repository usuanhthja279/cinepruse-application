# Claude reference UI port — implementation report

## Result

Movie Intelligence now uses the supplied reference’s shell, exact stylesheet, five navigation paths, typography, colors, card flip, responsive layout, chart language, map hover/focus treatment, and screening detail drawer. Its embedded demo payload is not used. The views read the checked-in hourly exports and the local read-only API for service-date captures. The newest available service date is selected on initial load and newly published dates are adopted on the five-minute refresh.

The Shows view keeps the reference search, sort, daypart, and paging controls. Future-date queries use allow-listed server-side sorting and time filters so the same controls apply across API pages. Map drilldown is restricted to verified and candidate city-label mapping; it does not allocate cinema or revenue totals to states.

## Accounting and data display

The app retains the project owner’s confirmed-revenue wording and booked-plus-blocked seat basis. It keeps failed or uncollected feeds as unknown, not zero. An hourly comparison appears only when it contains matched sessions; advance service-date views do not borrow a same-day hourly curve or comparison. Incomplete pricing remains visible as incomplete.

## Verification

- `node --check dashboard/assets/movie_intelligence.js` passes.
- All 10 dashboard data and UI contract tests pass.
- All 26 collector tests pass, including service-date search sorting and daypart tests.
- Browser inspection confirmed the Overview, Pulse, Map, Shows, and Capture engine routes render; the newest service-date view loaded 1,009 captured feeds and 12,023 deduplicated screenings.
- CSS is the extracted stylesheet from the supplied reference HTML; layout and animation classes are retained.

## Limits

The local API is required for advance-date summaries and show pages. It can take several seconds to return while the collector database is busy; the page keeps the saved hourly overview responsive and uses a loading state instead of displaying a false zero. The state map describes city-label mapping coverage only.
