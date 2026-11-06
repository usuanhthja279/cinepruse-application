# ScreenLedger — unified Codex handoff and midnight collector kit

**Prepared for the India Standard Time service day Saturday, 7 November 2026.**

## What is in the ZIP

- `collector/` — working **District.in offline HTML parser** (original v2, unchanged core extraction), new `smart_collector.py` showtime scheduler, SQLite observation history, offline plan, status-export code, tests and Windows PowerShell scripts. This is the active engineering starting point.
- `dashboard/index.html` — most recent v4 responsive movie-first dashboard, election-style India → state/UT → district/city → cinema drilldown. Official boundaries are **not installed**; the map intentionally shows a loading/import state until verified geometry is supplied.
- `dashboard/fetch_and_embed_soi_map.py` — import/download and validate the official government GeoJSON ZIP; **this handoff does not contain the real polygons**.
- `dashboard/MAP_SOURCE_AND_RELEASE_CHECKLIST.md`, `dashboard/CODEX_INDIA_MAP_V3_HANDOFF.md`, `dashboard/verified_snapshot.json` — map verification, older UI details and offline verified Kolkata sample.
- `documentation/` — the new phased implementation plan and copy/paste Codex prompts.
- `legacy_archives/` — the prior complete v1–v3 design/extractor/prototype ZIPs, official-map v4 ZIP and CinePulse Android/runtime proof of concept, preserved unmodified for reference.
- `previews/` — latest available preview images from v3.
- `manifest.json` — list of included artifacts and SHA-256 checksums.

## 1. What is truly ready?

| Component | Status |
|---|---|
| District offline parser, November 6 Kolkata fixture | Tested; 117 shows, 29 cinemas |
| Smart scheduler: hourly + 5-minute-before-show scans | Reference implementation; 15 offline unit tests pass |
| Persistent SQLite per-show history | Implemented and tested locally |
| Live collector using District HTML | **Not verified against the live provider**; explicit authorization and Windows test required |
| BookMyShow Android emulator / API capture | Separate previous proof of concept, **not connected to this District parser/scheduler** |
| Movie search, state/city/cinema UI | Prototype present; not live connected |
| Official Survey of India / NWIC map polygons | **Not embedded**; run supplied map downloader and check political-map provenance |
| Real sales / collections | **Not obtainable from unavailable seats alone**. Treat estimates as proxies |

The 6 November Kolkata fixture shows 27,663 seats; 7,202 *unavailable*, including possible blocked/held inventory; ₹39,48,610 is hypothetical gross from listed seat-category prices. **Do not label these as verified tickets sold or box-office receipts.** The nationwide hourly UI replay is simulated.

## 2. Priority before midnight

1. Open `documentation/CODEX_MASTER_PROMPT.md` and paste into Codex in the actual project repo. Work on the current branch and integrate rather than rewrite unrelated areas.
2. In `collector/`, install dependencies and run tests: `py -3 -m venv .venv`, then `\.venv\Scripts\python.exe -m pip install -r requirements.txt`, then `\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
3. Inspect the current provider/source path: **District collector** is not equivalent to the user's **BookMyShow Android extraction**. Choose the one with documented authorized access; do not silently combine their data.
4. Prove a single live authorized capture returns the intended city and date, stable session IDs, valid times, seat counts and non-empty data; stop if access restrictions occur.
5. If the source is valid and permitted, run the collector by midnight: `powershell -ExecutionPolicy Bypass -File .\START_AT_MIDNIGHT.ps1 -AuthorizedLive -Date 2026-11-07 -City kolkata`. The script waits for 00:00 IST when started early, and runs an immediate catch-up if launched after 00:00. **Running this command is a local user action; this package does not start remote collection.**
6. If access is **not** approved or not validated, use fixture plan/tests. Do not treat the offline mode as real capture.

## 3. Why a 12:35 AM show needs 12:30 AM

At **00:00** capture the show's baseline if listed, then queue a second scan at **00:30** (show starts at **00:35**). The 01:00 hourly scan might no longer list that show. Capture at **00:30** is its last *pre-show inventory observation*. Snapshot T-5 is a configurable safety rule, not proof that every sale is observed; if bookings stop early, a T-10 fallback may be needed. Never write zeros for disappeared shows; preserve their most recent valid pre-start record and completeness flag.

See `documentation/PHASE_PLAN_AND_DATA_RULES.md` for later phases and precise metric rules.

## 4. Fast local CLI

```powershell
cd collector
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# No network: test old snapshot and its scheduled pre-show scans.
.\.venv\Scripts\python.exe smart_collector.py --plan-fixture fixtures/ramayana_kolkata_2026-11-06.html --date 2026-11-06 --observed-at '2026-11-06T20:26:56+05:30'

# Only if provider permission exists and a real authorized capture was validated:
.\START_AT_MIDNIGHT.ps1 -AuthorizedLive -Date 2026-11-07 -City kolkata

# Inspect collected records, once the live collector has actually run:
.\GET_STATUS.ps1 -Date 2026-11-07 -City kolkata
```

## 5. Source scope

The active core module is named `district_extractor.py` because the earlier saved HTML is from **District.in**, not BookMyShow. The BookMyShow 78.8K hourly figure discussed earlier was a separate observed UI metric and is not included in the District example dataset. If the actual production source will be BookMyShow, Codex should implement a provider adapter with the same normalized model and approval controls, rather than calling the District parser on BMS content.
