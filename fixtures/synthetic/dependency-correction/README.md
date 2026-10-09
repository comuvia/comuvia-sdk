# Fixture D: declared dependencies and a source correction

Status: valid `comuvia/0.1` records that carry the example profile `org.comuvia.dependencies/v1` in their `extensions`. [Tutorial D](../../../documentation/tutorials/D-dependencies-and-corrections.md) and its script check every value in `expected.json`.

## Provenance

Original synthetic content written for the Comuvia SDK, in the fictional Port Calder setting. All quantities, sources, methods and outputs are invented. Locators use the reserved `example.org` domain or `urn:example:` names and are never dereferenced. Every record carries `data_origin: "synthetic"`. The profile's `value_origin` says the role the values play inside the example: `observed` means "plays the role of an observed source".

## The graph (13 records)

| Record | Profile | Declared inputs |
|---|---|---|
| `src-calder-quarterly` r1, r2 | observed quarterly container throughput, TEU, 2026-Q1 to Q4. r2 corrects Q3 from 99,800 to 98,900 | none |
| `method-annual-sum` r1 | none: a method document | none |
| `model-calder-stress` r1 | none: a model configuration | none |
| `synth-shock-path` r1 | synthetic shock multipliers | none |
| `res-calder-annual` r1, r2 | derived annual total: 401,750 TEU at r1, 400,850 TEU at r2 | `data_input`: the source (r1 or r2); `method`: the annual-sum method |
| `chart-calder-quarterly` r1 | derived chart of the quarters | `data_input`: source r1. It has no successor |
| `sim-calder-stress` r1, r2 | derived stressed total, the annual total × 0.92 (the shock path's minimum) | `data_input`: the result (r1 or r2) and the shock path; `method`: the model |
| `src-calder-fuel` r1 | observed monthly bunker fuel, tonnes | none |
| `out-calder-fuel` r1 | derived quarterly fuel total; coverage complete | `data_input`: the fuel source. Unrelated to the correction |
| `out-calder-mixed` r1 | derived fuel per vessel call; coverage **partial**, because its vessel-call source is not pinned | `data_input`: the fuel source |

## Files

| Path | Role |
|---|---|
| `source/` | The exact bytes of the three `resource_snapshot` records, one file each. Git stores them unconverted (`-text -eol`) |
| `artifacts/` | The exact bytes of the ten `artifact_descriptor` records, one file each, also unconverted |
| `records/<id>.r<revision>.json` | The 13 committed records |
| `expected.json` | Content and record identities, and the impact report of the source correction (`src-calder-quarterly` r2) |

Only these 13 records are committed. Tutorial D builds every mutated case in memory: tampering, withheld and missing pins, stale mutual pins, a meaning-only correction and each issue code. `tools/check_fixtures.py` checks the file-to-record correspondence and every digest.
