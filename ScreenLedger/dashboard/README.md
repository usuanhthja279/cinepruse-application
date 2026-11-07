# ScreenLedger — Official India State Geometry Integration (v4)

## Movie Intelligence UI v2

The dashboard is a faithful implementation of the supplied Claude reference shell and visual system: the same Fraunces/Manrope fonts, warm light and plum dark themes, spacing, panels, charts, map treatment, flip-card motion, drawer, and responsive layout. It keeps the reference five routes—Overview, Pulse, Map, Shows, and Capture engine—and uses the project’s real saved exports and read-only live API instead of the mockup payload. Theme preference persists. The latest completed service-date capture is selected automatically, and refresh runs every five minutes.

The reference HTML's embedded demo dataset is not used. Hourly figures are loaded from the committed JSON/CSV snapshots. The currently committed November 7 data has six capture windows (00:00–05:00 IST); availability and failures are reported separately. Matched-session movement is shown only when eligible sessions exist, so the 00:00→01:00 interval appears as unavailable because its saved comparison has no matched future sessions.

## Current Movie Intelligence data flow (November 2026)

Movie Intelligence combines two real-data paths:

- The saved hourly history, comparisons, and city coverage load from the published JSON/CSV files under `dashboard/data/`.
- The **Advance booking captures** panel reads the local read-only API at `/api/live/dates`, `/api/live/summary?date=YYYY-MM-DD`, `/api/live/cities?date=YYYY-MM-DD`, and `/api/live/shows?date=YYYY-MM-DD`. It selects by **service date** (the show date being monitored), so a capture made on November 7 for November 9 appears under November 9. Search, safe server-side sort, daypart filters, paging, and the detail drawer use deduplicated screening rows from the same API.

Start the local API and static dashboard from PowerShell in `collector/` using `.\START_LIVE_DASHBOARD.ps1`, then open `http://127.0.0.1:8765/dashboard/index.html`. Advance captures refresh every five minutes alongside hourly history. The local database must be writable by the collector once so it can add `captures.service_date_ist`; this migration is automatic and adds an index. The dashboard API itself is read-only. Shows filters accept an allow-listed sort key and one of the reference dayparts; the API never evaluates client-supplied SQL.

New successful and failed collector attempts both store `service_date_ist`. For older captures without that field, the API infers a date only from successful observations that all belong to one show date; it uses the collection day for legacy failures. Empty legacy advance captures cannot be reliably assigned to a future date and are left out of that date’s coverage. Failed and uncollected city feeds remain unknown, not zero shows. City feeds overlap, so show and seat totals are deduplicated by session key. Revenue uses the project owner’s confirmed payment basis; listings with incomplete pricing are counted separately.

`collector/tests/test_service_date_dashboard.py` covers capture-day versus show-date selection, legacy inference, coverage failures, and cross-city session deduplication. Run the full collector suite from `collector/` with `python -m unittest discover -s tests -v`.

The ScreenLedger movie-first dashboard now includes a **local automatic downloader and validated geometry embedder**, using only the Government of India National Water Data Portal's Survey of India state-boundary GeoJSON archive. It preserves the state/city/cinema drilldowns from v3.

**Current package status:** This delivery **does not contain the actual official polygon coordinates**: the source URL was verified on the official government website, but this execution environment could not resolve the government's download host. The 36-region index still works, and the map area intentionally remains blank until the government file is fetched. Do not claim the north boundary has already been verified.

## Get the official state boundaries into the HTML

On Windows PowerShell, unzip this package, `cd` into the folder, then run:

```powershell
py -3 fetch_and_embed_soi_map.py
```

The script downloads the official `state_NWIC_GeoJSON.zip`, validates its structure and all 36 state/UT identifiers (including separate Jammu and Kashmir and Ladakh), hashes the archive, and **overwrites `index.html` with the extracted GeoJSON embedded inside**. Open the HTML in Chrome or Edge; the state polygons should now be available immediately without relying on cross-origin browser requests. The script produces `soi_geometry_provenance.json` and keeps the original ZIP for audit. You can rerun it safely after an upstream update.

If Python cannot access the government ZIP directly, download the **GeoJSON ZIP** from [Government state-boundary dataset](https://nwdp.nwic.gov.in/dataset/state-boundary) using your normal browser, then run:

```powershell
py -3 fetch_and_embed_soi_map.py --archive "C:\Users\YOUR_USER\Downloads\state_NWIC_GeoJSON.zip"
```

The local-archive mode records its origin as **unverified local input**, so the SHA-256 attests to exactly which file you embedded but does not prove who published it.

## Boundaries and source requirements

- Primary source: [NWIC state boundary dataset, producer shown as Survey of India](https://nwdp.nwic.gov.in/dataset/state-boundary)
- Exact resource: [state_NWIC_GeoJSON.zip](https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_nwic_geojson.zip)
- Cartographic reference: [Survey of India Political Map, English 13th Edition/2026](https://surveyofindia.gov.in/pages/political-map-of-india)
- Source copyright policies: [National Water Data Portal](https://nwdp.nwic.gov.in/footer/copyrightPolicy) and [Survey of India](https://surveyofindia.gov.in/pages/public-awareness)

**Validation scope:** file-format checks, named state/UT coverage, finite geographic coordinates, geographic bounding-box sanity checks, and basic north-region presence. These tests **do not prove** that the political border matches the 2026 Survey of India political map. Compare the India outline, Ladakh, and Jammu and Kashmir against the official map before public deployment. Do not patch disputed or missing polygons from an unofficial global dataset.

The NWIC resource currently displays a `Other (Open)` license classification; its portal copyright policy generally permits accurate reuse with prominent attribution, but excludes separately identified third-party copyrighted material. A different Survey of India 1:15M outline product explicitly restricts commercial usage. **Do not assume commercial redistribution rights for every government GIS asset are identical**; confirm reuse of the particular government state-boundary data for your intended deployment.

## Dashboard data rules

The dashboard is backed by committed District hourly exports for November 7 and by the local read-only API for service-date captures. It does not use a simulated November 7 national replay. The saved run summary is the source of truth for hourly values; the newest manifest chooses the available export set. Future service dates are selected by the show date, not capture date.

Unavailable seats are counted as booked plus blocked under the project owner's accounting assumption, and the dashboard uses the project's confirmed-revenue label per the owner's separate payment confirmation. District inventory fields alone do not contain payment events. Rows with incomplete price details remain identified as such. Failed and uncollected feeds are unknown coverage, never zero shows. City feeds overlap, so national totals are deduplicated by session key. The map is limited to selector-label coverage; state cinema or revenue totals are not inferred from city names.

## Open the live collector ledger

The live District collector view is available at `live.html` when the local API is running. From PowerShell in `collector/`, run:

```powershell
.\START_LIVE_DASHBOARD.ps1
```

Then open `http://127.0.0.1:8765/dashboard/live.html`. The page reads the collector database through a local read-only API, lists all city targets and captured screening rows with paging, and deduplicates national session totals by `session_key`. City-feed rows can overlap, so per-city totals should not be added to produce the national total. Revenue is labeled **Confirmed revenue** per the project owner's payment confirmation; the database itself stores seat and listed-price fields, not payment receipts. The page displays the project owner's confirmation provenance and incomplete listed-price coverage.

## Files

- `index.html`: Movie Intelligence dashboard with Overview, Pulse, Map, Shows, and Capture engine routes.
- `assets/claude_ui.css`: reference-aligned responsive light/dark theme, typography, and focus/motion treatment.
- `fetch_and_embed_soi_map.py`: official NWIC ZIP download, JSON normalization, checks, and offline geometry embedding.
- `verified_snapshot.json`: unchanged Kolkata extracted reference metrics.
- `CODEX_INDIA_MAP_V3_HANDOFF.md`: previous v3 implementation roadmap.
- `MAP_SOURCE_AND_RELEASE_CHECKLIST.md`: provenance and acceptance checklist.
- `documentation/CLAUDE_UI_INTEGRATION_PLAN.md`: audit, component/data lineage, API contract, and test plan.
- `documentation/CLAUDE_UI_IMPLEMENTATION_REPORT.md`: implementation scope, data limits, and verification notes.

### Known test scope

The acquisition script passed local parsing/embedding tests using **temporary synthetic polygons** (these fixtures were deleted and are not included). A real end-to-end government download and browser geometry rendering could **not** be tested inside this environment because external DNS and headless browser navigation were blocked. The geometry is therefore **not yet installed** in this ZIP.
