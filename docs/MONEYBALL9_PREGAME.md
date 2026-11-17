# Moneyball 9 prospective scouting

Base recovery commit 353301768fa42ac6106d5fda6320dab88507a018.

## Installation

Install requirements.txt and run pytest. This incremental branch adds a descriptive pregame layer and exact regular-season rank bounds. The existing feed workflow generates an NFL-only scouting artifact after its existing steps. Its schedule and Apps Script triggers are unchanged. Merge this branch to enable that workflow step. Apps Script deployment and automatic dashboard consumption remain pending.

Local entry point, using frozen inputs available at the decision timestamp

```sh
python moneyball9_pregame.py --plays /path/pbp.parquet --schedule /path/games.csv --feed /path/observed.json.gz --season 2026 --week 11 --observed-at 2026-11-17T15:55:00Z --cutoff 2026-11-17T15:55:00Z > /private/pregame.json
python -m pytest -q
node tests/test_moneyball8_apps_script.js
node tests/test_moneyball82_apps_script.js
```

Optional --events accepts a JSON array with subject, kind, source URL, origin, publishedAt, observedAt, class, mechanism, counterargument and invalidation. The caller supplies verified timestamps. Input revisions first observed after a historical cutoff are excluded. Sources sharing an origin count once for an identical event. Timestamp validity cannot establish the truth of a news assertion. Automated news ingestion remains pending.

## Data contracts

PBP uses regular-season pass/run plays strictly before the target week, last four observed games. Report sack and hit rates with a dropback denominator, neutral pass rate and PROE with their observed sample size. Neutral means score margin at most seven in quarters one through three. Hits are not pressure rate. Unavailable pressure, blitz and route fields remain null.

Player windows reuse the existing ETL, including source coverage, optional charted first reads, red-zone opportunities and partial snap observations. A four-row window can span absences. Check the actual week list and coverage before inferring continuity. Counts in third-down/two-minute fields are opportunities, not participation rates.

select_vintage chooses the latest archived forecast released before a player's kickoff. Historical source revisions are not point-in-time training data. Original archives stay immutable.

rank_bounds enumerates all binary outcomes up to 22 remaining games, in memory-bounded batches. It allows either order for standings ties and excludes tied matchups. The output is a range of feasible ranks, not an odds estimate. League IDs, rosters and private negotiations remain caller-owned inputs outside this repository.

## Promotion and validation

No numeric model is promoted by this layer. Current forecasts retain their existing model and explicit limits. Existing seven/nine-slot optimizers remain the scenario entry points. Pass complete league-scored projections and verified availability before interpreting results as league forecasts.

Collect the artifact, input checksums, timestamp, alert, causal mechanism and actual chosen substitute before each kickoff. Evaluate the next four completed weeks without retuning. Report errors against the frozen baseline, interval coverage only for a frozen interval policy, and false alerts at the event level. Evaluate decision regret only over alternatives actually available before lock. Hold out later weeks before considering a numerical adjustment.

The existing validation report labels the selected deployment policy as prospective-validation pending. Repeated refreshes of a past target week do not constitute independent forecasts. Future availability, QB sensitivity to pressure, OL injuries, validated joint distributions, market acceptance and championship Monte Carlo remain unimplemented.

## Recovery

Revert this branch's commit to remove its workflow step and modules. Existing forecast artifacts and history are unaffected. The pregame artifact is retained for 90 days by Actions and should be exported for longer prospective evaluation.
