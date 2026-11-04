# Apps Script 8.0 consumer

The extension consumes only the public NFL schema-80 forecast. It does not send
league identifiers, player requests, rosters or credentials to the source host.
The complete private `Code.gs` must be built from the existing stable 7.2.1 code;
the private source is deliberately not committed to this public repository.

```sh
python apps_script/build_complete.py --source /private/7.2.1.gs --output /private/Code.gs
node --check < /private/Code.gs
node tests/test_moneyball8_apps_script.js
```

The builder rejects an already extended source, refuses an unknown hook anchor,
checks duplicate function declarations and verifies that all prior functions
remain. The resulting file adds an optional guarded call after the 7.2 evaluator.
A feed failure does not stop the core documents or the older modules.

Replace the complete `Code.gs` in the same Apps Script project. Save, then run:

1. `probarMoneyball8` — offline schema and invalid-input checks.
2. `probarFuenteRealMoneyball8` — checks the real feed without writing sheets.
3. `actualizarMoneyball8` — updates only `MB8_PROYECCIONES` and `MB8_CALIDAD`.
4. `verificarMoneyball8` — checks the private manifest and sheet readback.

Do not rerun `instalarMoneyball`: the existing scheduler calls the extended
`actualizarMoneyball` automatically. No new trigger is created by this module.
`menuMoneyball8` is optional for a spreadsheet-bound project; a standalone
project can use the Apps Script function picker.

The new source must match the current NFL target week and be no older than 72
hours; unavailable source data leaves prior sheets untouched. Partial writes
attempt rollback from the preceding values. Google services are not atomic:
inspect the manifest after a hard timeout before trusting visible tabs.

The feed does not model K/DST, current injury availability or championship odds.
Published PPR projections and 80% intervals are conditional on recorded games;
technical validation does not demonstrate interval calibration or predictive edge.
