# Codex follow-up: correctness-first scheduling review

Review `collector/smart_collector.py`, the SQLite schema and `collector/tests/test_smart_collector.py` as an initial **reference implementation**, not as proof the source is live. Continue on the current branch.

Add deterministic fake-clock end-to-end tests for: midnight 2026-11-07 IST, 00:35 show + 00:30 final scan, 00:36 adjacent show coalescing without timing loss, pre-show capture absent from provider response, provider early booking cutoff with T-10 fallback, show discovered at 00:33, 01:00 page no longer listing 00:35, crash after fetch before DB commit, duplicate job replay, restart at 00:25, multiple cities, city redirects, source 403/429 and partial data.

Refine the priority queue so page-level (movie, city, date, provider) tasks can satisfy multiple session deadlines with explicit freshness tolerance. Enforce per-provider authorized request budgets, concurrency limits and deadlines; log missed targets, actual scan offset, source latency and queue wait. Store full event/audit history, immutable raw capture ID, source hash and clear `final_observed_at`. Do not skip a final scan because an hourly observation happened much earlier than T-5. Do not use snapshots after session start as 'final'.

Separate `raw_html`, parsed `observations`, normalized `show_registry`, `capture_events`, and scheduled jobs. Add migrations for existing DBs. Recompute `last_hour_net_unavailable` from paired observations at T and T-60±tolerance for sessions stable in both; emit null if there are no comparable pairs. Verify cancellations/format changes/capacity changes and maintain per-show price-category histories. Add explicit collection completeness and "not verified sales" labels.

Deliver tested code, benchmark requests/hour and deadline adherence, migration plan, test output, and a short review of unavoidable accuracy limits.
