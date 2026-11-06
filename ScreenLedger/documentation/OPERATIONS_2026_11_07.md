# Midnight extraction operations — 7 November 2026 (India)

## Decision gate before executing any live command

- Current packaged extractor: **District.in** saved-HTML/Next.js parser. Its network mode has not been verified live. BookMyShow Android/runtime prototype is separately archived and **not integrated** with this scheduler.
- A source's availability from your browser or emulator **does not itself grant permission** for automated collection. Use only an authorized API/feed/acquisition arrangement. On 403/429 or an access challenge, stop and investigate permissions; do not bypass.
- First service area is **Kolkata** only until one successful authorized end-to-end run and source/city verification. Broader national data is a later phase.

## At or before 23:55 IST on Friday, 6 November

In Windows PowerShell, within the extracted package:

```powershell
cd .\collector
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe smart_collector.py --plan-fixture .\fixtures\ramayana_kolkata_2026-11-06.html --date 2026-11-06 --observed-at "2026-11-06T20:26:56+05:30"
```

The offline fixture plan prints a list of pre-start scan jobs for the old snapshot **without any network request**. Verify the source name and movie identity. In particular `--movie-id 176276` applies to a **sample District** film identifier, not automatically to BMS.

## Launch for 00:00 IST on Saturday, 7 November

**Only if the provider explicitly permits the corresponding live acquisition and you have tested one authorized source read:**

```powershell
# Run this in a PowerShell window you keep running. The script self-installs,
# re-runs tests, and the Python loop waits for 00:00 IST if started early.
.\START_AT_MIDNIGHT.ps1 -AuthorizedLive -Date 2026-11-07 -City kolkata
```

One baseline fetch happens near `00:00` (or immediately with `catch_up` when the process starts late). Every hour, the collector takes another page snapshot, and it inserts earlier `T-5` jobs for future screenings. Every parsed observation is committed to `collector_data/smart_collector.sqlite`; source HTML is processed in memory and discarded.

To run from `powershell.exe` if local script policy blocks file invocation:

```powershell
powershell -ExecutionPolicy Bypass -File .\START_AT_MIDNIGHT.ps1 -AuthorizedLive -Date 2026-11-07 -City kolkata
```

Do not start a second copy pointing at the same SQLite file. The starter requires an open terminal; it is not configured as a Windows background service. For unattended reliability, Codex should later implement a controlled Windows Task Scheduler service with single-instance locking and monitoring.

## Confirm at 00:05 IST

In a **second** PowerShell window:

```powershell
cd .\collector
.\GET_STATUS.ps1 -Date 2026-11-07 -City kolkata
Get-Content .\collector_data\status_2026-11-07_kolkata.json
```

Expected for a genuine successful run: `snapshot_count` at least 1, a nonempty `recent_captures` row with `status=ok`, and a meaningful show registry if the provider returned shows. **No row, no coverage claim.** Zero known shows does not establish zero screenings when a source failed. If requested city and actual city differ, the capture is rejected for the expected city.

## At 00:30 for a show scheduled at 00:35

Confirm a `pre_show` capture near 00:30 appears in `recent_captures`; the corresponding final job changes from `pending` to `captured` if that session is present before the show start. If it was first discovered after T-5, it is `late_discovery`; if missing or unreachable, report `not_visible`/`missed`, not false zero.

At 01:00 the next hourly capture must **not** erase the 00:35 show's pre-show value. Last-hour proxy only exists if enough comparable observations are available. The 00:00 and 01:00 readings should be compared for identical future sessions, not added together.

## Stop/restart and failure handling

- Stop cleanly with Ctrl+C; existing SQLite/raw files persist.
- Re-run the same authorized command to resume; source state is persisted. Missed previous hourly windows cannot be reconstructed from newer snapshots and must remain gaps.
- On 403/429 the live loop stops. Do **not** keep retrying or bypass. If HTML no longer has the expected payload, mark a parser failure and keep the last valid data with freshness warnings.
- Prioritize source correctness over uptime. A silent missing-show result can corrupt a 'tickets sold' metric more than a visible error.
- Keep provider timestamps separate from your device clock if source actually supplies server timestamps; log timezone and clock skew for deadline-quality evaluation.
