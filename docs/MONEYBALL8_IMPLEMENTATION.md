# MONEYBALL 8.0 — implementation and continuation

Verified 2026-11-04. This is a tested forecasting/decision foundation, not a calibrated championship engine.

## Implemented

| Component | Verification | Remaining boundary |
|---|---|---|
| Position PPR models | Real nflverse 2023–2026, chronological backtests, four candidate models | Conditional on recorded games; no availability or matchup |
| Incremental pipeline | End-to-end real CSV acquisition, SHA-256 provenance, atomic publication, archived vintages | Revised historical data; not historical publication snapshots |
| Nine-slot optimizer | Exact DP checked against brute force, locks/IR/byes/null handling | Requires supplied same-week forecasts/availability for all nine slots |
| Trade/waiver scenarios | Bilateral ownership/cuts/three explicit horizons; private case executable | No invented future-week forecasts or waiver entitlement |
| Official evidence | Real Chiefs HTTP200 extraction and contradiction rejection | One publisher prototype; event hour missing; no medical model |
| League reconstruction | Ten-roster settings/scoring/standings/bracket validator | Tie rules and full future schedule remain unverified |
| Apps Script | Complete private builder, rollback/checkpoint and tested public adapter | Actual Google project installation/execution not available from repository |

## Measured quality

The predeclared policy selected models on 2024, estimated residual intervals on 2025 weeks 1–8, and used 2025 weeks 9–18 as a promotion validation. Its frozen assessment uses 2026 weeks 4–8. All candidate forecasts use only strictly earlier event weeks. Source files are revised snapshots: publication-time availability and missed-game bias are not solved.

| Position | n 2026 | Frozen evaluated MAE | Recent4 MAE | Opportunities MAE | Deployed |
|---|---:|---:|---:|---:|---|
| QB | 129 | 6.3326 | 6.6722 | 6.3326 | opportunity_ridge |
| RB | 197 | 6.0447 | 6.3110 | 5.9866 | opportunity_ridge |
| WR | 323 | 5.8468 | 6.1910 | 5.8165 | opportunity_ridge |
| TE | 145 | 5.8083 | 5.9261 | 5.4399 | opportunity_ridge |

Because the simple opportunity model beat more complex candidates on the latest comparison, deployment retains the better simple alternative. That deployment choice used 2026 weeks 4–8: its observed error is a retrospective comparison, NOT an independent estimate of the newly selected policy. `deployment_status=PROSPECTIVE_VALIDATION_PENDING`. Do not relabel the selection partition as a test. The full report preserves every candidate, RMSE, bias, sample size and interval coverage. TE intervals did not establish 80% coverage.

## Reproduce without league access

```bash
python -m pip install -r requirements.txt
python -m pytest -q
node tests/test_moneyball8_apps_script.js
python moneyball8_pipeline.py --source-gzip data/_MONEYBALL_FEED_2026.json.gz --output data/_MONEYBALL8_FORECAST_2026.json.gz --pass-int-points -1
```

The interception parameter is a generic scoring adjustment from the nflverse default −2. Other custom scoring still needs reconciliation. Historical caches reduce downloads; cached vintages are not immutable upstream truth. Forecast files archive by data/model/scoring fingerprint. No roster, manager, private trade or waiver input is published. Private case outputs refuse git checkout destinations.

## Stable version and automation

Stable pre-8 base: `028dcd669c5a11a42e4524418f445df374a1939c`. Existing 5/6/7/7.1/7.2 modules, data and cron times remain. The existing NFL feed workflow now runs tests and adds the 8.0 pipeline; there is no duplicate schedule. The optional forecast step retains the prior valid feed on failure; consumers reject stale/wrong-week feeds. A new PR/manual test workflow runs the whole Python and JS suites.

The complete private Code.gs is produced from the exact 7.2.1 original with `apps_script/build_complete.py`; it preserves all 115 original function declarations and inserts one isolated hook. Do not upload private Code.gs or league snapshots to this public repository.

## Continue exactly here

1. Install and verify complete Code.gs in the same existing Apps Script project. Do not reinstall triggers.
2. Preserve the first Week 9 forecast vintage before kickoff; evaluate it after results with availability cohorts, decision regret and interval coverage. Do not retune using its results and call the same week a test.
3. Add schedule/bye/lock joins and K/DST custom scoring forecasts before trusting nine-player totals.
4. Generalize official practice ingestion beyond Chiefs with explicit event-date confidence and contradictions.
5. Train and validate participation/absence and joint player-score dependence; reconcile scoring edge categories.
6. Confirm standings tie rules, remaining matchups and bracket before a Monte Carlo module. No championship percentages are emitted yet.
7. Evaluate future-week/15–17 projections, actual replacement availability and two current market references before actionable trades.

## Sources and licenses

See NOTICE_LICENCIAS.md. Models use nflverse weekly player statistics (CC-BY 4.0); no premium routes/tracking or FTN features enter 8.0. DynastyProcess identity crosswalk repository declares GPL v3; the raw CSV is not redistributed here. Official Chiefs report extraction retains minimal facts/source and rejects ambiguous timestamps. Sleeper private operations are read-only.
