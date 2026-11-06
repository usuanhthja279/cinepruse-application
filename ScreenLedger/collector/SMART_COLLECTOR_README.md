# Schedule-aware collector reference (add-on to offline District extractor v2)

**The original `district_extractor.py` parser is not replaced.** `smart_collector.py` adds a Windows-launchable local scheduler with hourly + T-5 scan planning, SQLite observations and final-job persistence. It uses the parser's permission-gated plain HTML GET path and does **not** claim to have tested live provider data. The adapter is District-specific; BookMyShow requires a separate validated adapter.

### Commands

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe smart_collector.py --plan-fixture fixtures/ramayana_kolkata_2026-11-06.html --date 2026-11-06 --observed-at '2026-11-06T20:26:56+05:30'

# This requires independently established provider permission and a live-source check.
.\START_AT_MIDNIGHT.ps1 -AuthorizedLive -Date 2026-11-07 -City kolkata

# After live collection actually creates the database:
.\GET_STATUS.ps1 -Date 2026-11-07 -City kolkata
```

### Current implementation boundaries

- One movie, one source city and one IST service date per active collector process. Scale later after concurrency/locking and source request budget tests.
- The collector waits until midnight if started early, records an immediate catch-up if late, and exits after that date; SQLite `kv_state` survives restart.
- Each authorized city/movie page read captures **all currently visible sessions**; it doesn't fetch every individual seat-layout page. Jobs are keyed per show but the actual network request is page-level.
- `final_jobs` statuses: `pending`, `captured`, `late_discovery`, `not_visible`, `missed`. Missing data is never interpreted as zero sales.
- `captures`, `observations`, `final_jobs` and `kv_state` tables persist every observed session and state. `collector_status.py` makes an auditable JSON report, not a production API.
- `last_hour_proxy` compares stable future sessions around T and T-60 minutes within a ±10-minute window; it reports **net unavailable-seat movement**, not sales. `estimated_gross` also includes hypothetical blocked/held inventory value.
- The phase 2 Codex prompt is deliberately explicit about still-missing T-10 fallback, coalescing, single-instance enforcement, robust API/service design and real provider validation.
