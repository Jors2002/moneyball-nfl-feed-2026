# moneyball-nfl-feed-2026
Moneyball GM 5.0 - NFL Analytics


## Moneyball 8.0

Forecast comparison, legal lineup optimization, evidence gates and incremental publication now live alongside 5/6/7/7.1/7.2. See [implementation and reproducibility](docs/MONEYBALL8_IMPLEMENTATION.md). NFL-only outputs remain public; private league analyses must be written outside the checkout. No Sleeper mutation is implemented.


## Role change evidence (8.1)

Consume `data/_MONEYBALL8_ROLE_2026.json.gz` with the matching original forecast vintage before using historical opportunities for a decision. The role sidecar retains original points and vetoes unreviewed utilization discrepancies; no numeric adjustment was promoted. See [diagnosis, validation and operating boundaries](docs/MONEYBALL81_ROLES.md).
