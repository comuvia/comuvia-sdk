# Fixture B: structured declared-probability forecast from a synthetic provider

Status: valid `comuvia/0.1` records (OSS-1A). References carry computed record digests, and `expected.json` records them. The evaluator reproduces the losses and counts in `expected.json` (OSS-1B); the `fixture-b-*` cases in `packages/comuvia/tests/vectors/evaluation.json` check them.

## Provenance

Original synthetic content written for the Comuvia SDK. The provider "Lantern Forecasts", Port Calder and its authority are fictional. The provider is deliberately not ForeGlass: the core rules must hold for any provider. Locators use the reserved `example.org` domain and must never be dereferenced. Every record carries `data_origin: "synthetic"`.

The values were frozen during the project's design review (OSS-0 review, section 5.2); `expected.json` records the results they must produce.

## Files

| Path | Role |
|---|---|
| `source/port-calder-bulletin-2027-01.csv` | Exact retained bytes: UTF-8 without BOM, LF, 49 bytes, `sha256:f9bcfff9fe5b9670049d90519b9e66b9fbdab7734f3a4053e5a4cce18e059c77`. Git stores it unconverted (`-text -eol`) |
| `records/q-…json` | Pinned binary question: unit, target period, resolution rule and source, first-release vintage, deadlines |
| `records/fc-…json` | Provider forecast with declared probability 0.7, unconditional (`conditions: []`) |
| `records/res-…json` | Snapshot of the first-release bulletin excerpt |
| `records/out-…json` | Resolved outcome, value 1 (386500 TEU is below 400000) |
| `expected.json` | Identities, eligibility checks, binary64 losses (`0.09000000000000002`, counterfactual `0.48999999999999994`) and counts |

## Shape decisions (OSS-1A)

- A period is `{"start", "end", "inclusive", "precision": "day"}`. `observed.period` holds the outcome's observation period.
- `resolution_rule` is text only. It includes the frozen rule that a missing qualifying value by the resolution deadline gives `unresolved`. There is no structured threshold in 0.1.
- `resolution_source` is `{"name", "locator"}`.
- The question and the forecast carry `limitations: []`, meaning no known limitations (required since OSS-2A part 0).
- Every snapshot requires `language`, `captured_assets` and `not_captured`, as a value or a marker. The bulletin snapshot records `language` as unknown (`source_declares_no_language`), `captured_assets: ["bulletin_excerpt_csv"]` and `not_captured: ["full_bulletin"]`.
- The frozen table gives no `recorded_by`/`recorded_at` for the bulletin snapshot. This fixture uses `recorder:example-resolver` / `2027-02-16T09:45:00Z`: after capture at 09:30 and before the outcome record at 10:00.

`tools/sync_vectors.py` recomputes the reference digests; `tools/check_fixtures.py` checks them.
