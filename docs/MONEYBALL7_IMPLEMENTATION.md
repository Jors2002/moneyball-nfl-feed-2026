# Moneyball 7.0: implementation status and safety gate

## Purpose
This branch implements **only the first incremental, testable piece** of the
user's Moneyball 7 prompt: a read-only, deterministic, time-safe scouting trend
engine over the existing validated Moneyball 5 feed. It is **not** a prediction
model, waiver executor, or full Moneyball 7 release.

## Baseline verified (2026-11-04)
- Existing `moneyball5_etl.py`: normalized Sleeper-ID data, box score,
  partial snaps and PBP/FTN, optional routes with explicit licensing.
- Existing `moneyball6_validate.py`: schema, coverage and missingness checks.
- Connected Google Drive manifest: 2026 week 8 box/snaps/PBP coverage, routes
  **unavailable**, and injury rows **without verifiable publication timestamps**.
- Private league information is outside this public repository.

## What this change adds
- `moneyball7_scout.py`: disjoint previous (up to 2 games) vs recent (2 games)
  observed utilization averages, with per-metric denominators and data status.
- Hard `as_of_week` cutoff for reproducible no-future-data retrospective use.
- Unavailable values remain missing; no conversions to zero, no claimed causal
  mechanism, no model probabilities, no simulated targets-per-route.
- `tests/test_moneyball7_scout.py`: chronology, minimum samples, duplicate
  rows, schema, input immutability, boolean/NaN exclusion.
- Isolated PR CI with read-only permissions and **no secrets**.

## Evidence and boundaries
The implementation is a module and tests; it does not change scheduled
automation, Apps Script, Google Docs, waivers or Sleeper league settings.
Existing 5/6 sources are unchanged. Do **not** call Moneyball 7 deployed until
both the integration and acceptance tests are verified.

## Next implementation gates (not implemented)
1. Add validated data provenance and publishable quality report by metric.
2. Extend PBP opportunity features where play attribution is verified;
   label individual third-down/two-minute participation **unknown** if only
   team-level PBP exists.
3. Incorporate official, timestamped injury/practice reports with permissions.
4. Defense/kicker matchup features using verified league scoring.
5. Private league-side replacement, cut-watch and trade opportunity engine.
6. Playoff-horizon optimization and historical walk-forward backtesting.
7. Apps Script and dashboard integration only after backup, schema-compatible
   migration and permission review.

## Acceptance checklist for this PR
- [ ] CI green (pytest).
- [ ] Demonstrated missing routes do not become zeros.
- [ ] Historical as-of weeks exclude future weeks.
- [ ] No existing production files edited.
- [ ] No private roster or credentials committed.
