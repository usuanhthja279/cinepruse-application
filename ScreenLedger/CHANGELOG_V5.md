# New in consolidated midnight handoff v5

- Recovered, preserved and included original v1–v4 dashboard, v1/v2 extractor and CinePulse archives in `legacy_archives/`.
- Set most recent v4 movie-first HTML and the NWIC/Survey of India geometry **importer** as active UI. Original map geometry **is still not included/verified**.
- Added `collector/smart_collector.py`: a persistent SQLite event scheduler with one baseline/hourly page fetch and **per-show T-5 final capture jobs**; append-only observations, last valid data retained after a show disappears, date and timezone normalization, city mismatch exclusion, error tracking and graceful stop on access restrictions.
- Added `collector/collector_status.py`: auditable JSON status, counts, final-scan statuses and net unavailable-seat movement for comparable hourly samples.
- Added `collector/START_AT_MIDNIGHT.ps1` + `GET_STATUS.ps1`: user-operated Windows setup, tests, explicit authorized-live gate, 7 November IST launch and status inspection.
- Added 8 new smart-scheduling tests, increasing total test count from 7 to **15 passing** locally.
- Added midnight operator runbook, prioritized phased roadmap, one comprehensive Codex master prompt and separate scheduling and UI/GIS prompts.
- **Not implemented or verified**: permitted production provider access, live source reliability, BookMyShow adapter integration, actual government GeoJSON polygons, actual ticket sale counts, fully automatic T-10 safety scan, and multi-city deadline optimization. Those are expressly phased for Codex.
