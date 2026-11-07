# Claude UI implementation report

## Result

Integrated the reference's visual direction into the existing Movie Intelligence dashboard without importing its embedded demo dataset. The dashboard now presents Overview, Pulse, Map, Shows, and Capture engine routes, with a separate show-date selector for advance captures and hourly snapshot selector for saved exports. A compact theme control persists light/dark preference and defaults to the operating-system theme.

The screens continue to use committed hourly summaries/CSVs and the existing read-only live service. The overview and collector health read the selected real snapshot; Pulse now displays its selected matched-session movement, releases, net change, and revenue delta only when available; Shows contains the saved screening explorer; future service-date rows come through the existing paginated API; Map remains coverage-only and recognizes the actual town, settlement, and curated mapping status values. The first comparison with zero eligible matches now shows an unavailable state rather than a zero-change result.

The app retains the project's confirmed-revenue label and booked-plus-blocked basis per the owner's payment-confirmation instruction. This is an application accounting assumption, not a claim that District responses themselves contain payment events.

## Files changed

- `dashboard/index.html` — reference font/theme assets, five-route nav, and dedicated Shows view.
- `dashboard/assets/claude_ui.css` — responsive warm-light/plum-dark tokens, editorial cards, focus styling, and reduced-motion fallback.
- `dashboard/assets/movie_intelligence.js` — theme persistence, route labels/current-page semantics, focus return/trap for the map drawer, and zero-match comparison handling.
- `dashboard/README.md` — documented the updated UI and real data sources.
- `dashboard/tests/test_screenledger_data.py` — expected windows now match the six real committed captures.
- `dashboard/tests/test_claude_ui_contract.py` — new static integration guards.
- `dashboard/documentation/CLAUDE_UI_INTEGRATION_PLAN.md` — audit, lineage, and verification plan.

## Data and gaps

The committed summary currently contains `00:00`–`05:00` IST. It records 557 feeds at midnight, 1,012 at each of 01:00–04:00, and 931 at 05:00. The 00:00→01:00 delta has no eligible matched future sessions and is withheld. The map can show city-feed mapping coverage but cannot assign cinema bookings or revenue to states because there is no verified venue-to-state crosswalk. The page still depends on the local service for advance-date live captures; when it is unavailable, that view reports an explicit service error while saved hourly data remains available.

The handoff asks for visual screenshots, map border review, Lighthouse metrics, and browser-level mobile/keyboard testing. This environment could not reach the local dashboard port and no browser automation runtime was available, so those visual checks and screenshots are still outstanding. This report does not claim they have happened.
