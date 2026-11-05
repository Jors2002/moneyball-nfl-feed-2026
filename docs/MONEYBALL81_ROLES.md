# MONEYBALL 8.1 — role-change detection

## Exact diagnosis

At stable base ec3b519, Emanuel Wilson (Sleeper11435 / GSIS00-0038797) has an explicit Week8 row in the utilization feed: offensive snaps0, share0. The 2026 stats_player table has rows only through his Week7. `feature_rows()` and the RB opportunity model consume carries/targets from observed statistical rows, not the available snap history. The four last box-score games are Weeks4–7: carries21/20/14/24 (mean19.75), targets4/2/1/1 (mean2). The <=2-week recency gate accepts the Week9 request. Hence the unchanged reference15.327PPR despite a Week8 role collapse. The issue combines missing statistical rows, observation-based aggregation, unused snaps and unchecked decision consumption.

## What changed

- `moneyball8_roles.py`: independent positional utilization diagnostics. Latest shock versus prior3-game median; disjoint recent2 versus previous2 for sustained increases.
- `moneyball8_role_data.py`: identity-safe stats/snaps join, missing outcomes remain null, multi-team duplicate weeks remain ambiguous. Offensive zero requires an explicit source row; interpreting it as tactical non-use additionally requires positive participation evidence in any phase.
- `moneyball8_role_pipeline.py`: separate version81 evidence sidecar matched to original forecast vintage; complete272-game schedule validates explicit byes. No original forecast file or historical vintage is changed by this module.
- `moneyball8_role_validate.py`: expanding temporal original-opportunity vs learned role-candidate comparison, residual intervals, MAE/RMSE/bias/coverage and week-cluster bootstrap.
- `moneyball5_etl.py`: retains team/game/source/ST participation evidence previously discarded during Parquet column selection; old keys/schema preserved.
- Decision engine and private case study: flagged role blocks automatic projected totals. Missing sidecar blocks the new case-study workflow. Generic optimizer keeps backward compatibility; role-aware callers supply `roleDecisionAllowed`.
- Apps Script: adds MB8_ALERTAS_ROL, reference warnings, readable quality audit rows, sidecar/vintage verification and checkpoint compatibility with two-tab8.0 snapshots. No new trigger.

The numeric forecast model and its original8.0 pipeline remain unchanged deliberately. A separate workflow step publishes role evidence. Missing or incompatible sidecars mark forecasts unverified instead of silently clearing them.

## Threshold design and causal boundaries

Tail alert thresholds use2023 only:95th percentile among negative snap-share changes per position; gain boundaries use the95th percentile of positive min(recent2)-mean(previous2). These are alert-budget thresholds, not calibrated probabilities or causal classification. An observed active player with0 offensive snaps receives a descriptive zero-participation alert independently of the magnitude tail. No Wilson-specific haircut or player-ID branch exists.

BYE, INACTIVE, uncovered snapshots, ambiguous multi-team weeks and fewer than3 prior comparable snap observations are distinct. A fall during a documented injury is confounded; teammate returns/absences and QB switches require dated, verified context no later than the decision. Otherwise cause is UNKNOWN. Two elevated recent games describe observed persistence, not guaranteed future volume. Routes/TPRR remain null unless supplied by the authorized existing source.

Current Seattle context comes from the official Nov2 report with published2026-11-02T23:48:24.878Z and modified2026-11-03T07:03:03.937Z. It confirms Charbonnet and Price active, not a causal effect size. NFLverse/PFR Week8: Wilson0 offensive/7ST snaps, Price30/48%, Charbonnet23/37%, Holani11/17%.

## Retrospective comparison

Design:2023 alert calibration;2024W1–8 residual intervals;2024W9–18 development validation;2025 frozen retrospective audit. Historical releases are revised snapshots and model family already existed: do not call this a prospective trial or reconstruct publication-time availability from download time. Total paired forecasts6944 across development/audit training periods.

| Position | n2025 | Original8 MAE | Role candidate MAE | Original bias | Candidate bias | Original80% coverage | Candidate80% coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| QB | 404 | 6.4904 | 6.5984 | -0.0586 | 0.3923 | 82.673% | 81.188% |
| RB | 674 | 5.9524 | 6.0096 | -0.4169 | -0.0286 | 77.300% | 76.261% |
| WR | 1007 | 5.6761 | 5.6777 | 0.4148 | 0.4929 | 82.522% | 81.331% |
| TE | 441 | 4.9140 | 4.8497 | 0.1496 | 0.2806 | 81.406% | 82.086% |

Candidate NOT PROMOTED: overallQB/RB/WR MAE did not improve, TE gain is uncertain and the review cohort worsens. The abrupt-loss subset is much smaller (QB2/RB12/WR12/TE8 in2025); promising conditional errors there cannot establish complete-population benefit. The full mapped snap universe contains145 zero-offense active participants without a fantasy outcome in2025 (190 in2024); among them, baseline-eligible missing outcomes are {'2024': 1, '2025': 1}. None is fabricated as0PPR. A recovery proxy is reported separately and is not false-positive rate against causal truth.

Week-cluster paired bootstrap intervals are in data/_MONEYBALL8_ROLE_VALIDATION.json. All evaluated models share the exact same observed-outcome cohort. Production has no numeric adjustment, so original point predictions/conditional MAE are unchanged; alert/veto benefits are a decision-safety change, not a claimed predictive-accuracy improvement.

## Wilson before/after

| Field | Before | After |
|---|---|---|
| Historical reference |15.327|15.327 preserved|
| Latest offense |Unused by model|Observed0 snaps /0%|
| Prior share |Not a forecasting input|Median Weeks5–7=48%|
| Role |Unverified generic label|ABRUPT_PARTICIPATION_LOSS|
| Adjusted PPR |None|None: not validated|
| Automatic decision projection |15.327 could be consumed|Null until role review|
| Availability probability |None|None|

## Reproduce

Use the existing cache, avoiding repeated downloads. Download public snap_counts CSVs2023–2025 once and retain them with hashes.

```bash
python -m pytest -q
node tests/test_moneyball8_apps_script.js
python moneyball8_role_validate.py --cache-dir .cache/moneyball8 --snap-dir /local/snap_cache --output data/_MONEYBALL8_ROLE_VALIDATION.json --policy-output data/role_policy_v81.json
python moneyball8_role_pipeline.py --forecast data/_MONEYBALL8_FORECAST_2026.json.gz --source-gzip data/_MONEYBALL_FEED_2026.json.gz --output data/_MONEYBALL8_ROLE_2026.json.gz
```

The existing schedule remains unchanged. Role pipeline failure retains the prior sidecar; consumers reject mismatched/stale versions and require review. Installing complete private Code.gs is still needed for the existing Google Apps Script scheduler to write the new tab automatically. No live Apps Script installation is claimed by repository tests.

## Preserved and pending

Original Week9 forecast vintages are byte-locked by tests (including Wilson15.327). No historical deletion or Sleeper mutation. No league data enters public source. NFLverse stats/snaps attribution and existing licenses retained; role model does not use premium routes/tracking.

Pending: independently labeled causal role changes; broader official context ingestion; complete fantasy outcomes for snap-only participants; prospective alert decision-regret/coverage audit; numeric adjustment only after adequate evidence.

Verification:169 Python tests and37 JavaScript tests, full Code.gs syntax and legacy7/7.1/7.2/8 installation fixtures pass. A bounded-noise stable-role control includes400 synthetic cases with no alerts; this is NOT a real-world specificity estimate.
