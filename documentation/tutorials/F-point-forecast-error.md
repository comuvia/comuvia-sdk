# Tutorial F: point-forecast error evidence

Three fictional providers forecast a fictional economy's growth rate as single numbers. The statistics office publishes the outcome, then corrects a keying error. This tutorial records each forecast, the outcome and each error with exact pins, keeps the evaluation made before the correction, and shows what refuses to be scored.

Everything runs offline against the installed `comuvia` wheel, using `fixtures/synthetic/point-error/`. The logic is an **example helper**, [`point_error_example.py`](point_error_example.py), built on the public `comuvia` 0.1.0 API and the example helpers of tutorials D and E. The runnable script [`tutorial_f_point_error.py`](tutorial_f_point_error.py) checks every value this page states:

```sh
python tutorial_f_point_error.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
```

## Why descriptors, and what this is not

In `comuvia/0.1`, a `forecast` record holds only a binary probability (`output.kind` is `binary_probability`), and an `outcome` value is 0 or 1. A number such as "growth will be 3.0%" cannot be a 0.1 `forecast`. Turning it into a probability would be wrong. So every input and result here is an **`artifact_descriptor`** whose retained bytes hold the meaning, and whose `content_schema` names the kind:

| `content_schema` | Holds |
|---|---|
| `point-target/1` | What is forecast: measure, unit, period and geography, and which outcome record and edition settle it |
| `point-error-rule/1` | The frozen rule. Its bytes' digest is `RULE_DIGEST` |
| `point-forecast/1` | A provider's value as a **decimal string**, `output_kind`, unit, issue time, information cutoff, and whether its upstream lineage is `undisclosed` or `declared` |
| `point-outcome/1` | The observed value as a decimal string, its `edition`, `status` and publication time |
| `point-error-result/1` | The signed, absolute and squared error, the units, exact pins to the target, forecast and outcome, and the rule's identity |

Every artifact is exactly `comuvia.canonicalize(object)`. Every key is required and none may be added.

**This is example arithmetic, not a `comuvia` scoring rule.** It does not touch `binary-brier-v1`, and it produces no aggregate, no ranking and no skill score. The results are synthetic and show mechanics only; they are not evidence about any provider.

## The rule

- **Errors.** Signed error = forecast − outcome; absolute error = |forecast − outcome|; squared error = (forecast − outcome)².
- **Exact arithmetic.** Everything is computed with `Decimal`, never with a float. Results are plain decimal strings with no exponent and no trailing zeros, and zero is `"0"`, never `"-0"`. `0.1` against `0.3` gives exactly `-0.2`, `0.2` and `0.04`, where floating point would give −0.19999999999999998.
- **Units.** For a target in `percent`, the error unit is **percentage points** and the squared unit is **percentage points squared**: a difference of two percentages is not a percent. Any other unit `u` gives `u` and `u squared`.

## Eligibility

A forecast is scored only if nothing below applies. The reasons come in this order, and every applicable reason is reported, not just the first.

| Reason | When |
|---|---|
| `content_digest_mismatch` | An input's retained bytes differ from its descriptor |
| `malformed_input` | An input is not the expected canonical JSON object with exactly its keys |
| `rule_unavailable` | The rule bytes are not the frozen rule |
| `unsupported_output_kind` | The forecast is a `probability`, or anything but `point` or `conditional_point`. There is no conversion |
| `conditional_not_scored` | The forecast is a `conditional_point` |
| `target_mismatch`, `measure_mismatch`, `period_mismatch` | The forecast or outcome differs from the target |
| `unit_mismatch` | A stated unit differs from the target's |
| `missing_unit` | A forecast or outcome unit is a marker |
| `missing_cutoff` | The information cutoff is a marker |
| `impossible_time_order` | The cutoff is later than the issue time |
| `post_outcome_forecast` | The forecast was issued at or after the outcome's publication. Instants are compared exactly, with offsets applied |
| `missing_outcome` | The target's outcome record is not in the bundle |
| `unresolved_outcome` | The outcome's `status` is not `resolved` |
| `outcome_edition_mismatch` | The outcome's edition is not the target's edition |
| `malformed_value` | A value is not a plain decimal string, for example `NaN`, `Infinity`, `1e1`, an empty string or a JSON number |

`evaluate_point` uses the **latest revision** of the outcome the target names. `evaluate_bundle` evaluates the latest revision of every forecast against the target it names. It returns counts only: candidates, scored and excluded.

## A correction is not a new vintage

The outcome's r1 was mis-keyed as 2.6 and was corrected to 2.5 as r2: the **same edition** and the same publication time, recorded later. A later *vintage*, such as a second release, would be a different `edition`. The target names the edition it is settled by, so a different edition gives `outcome_edition_mismatch` rather than a new score.

| Forecast | Against r2 (2.5) | Against r1 (2.6) |
|---|---|---|
| Alder, 3.0 | `0.5`, `0.5`, `0.25` | `0.4`, `0.4`, `0.16` |
| Birch, 2.0 | `-0.5`, `0.5`, `0.25` | `-0.6`, `0.6`, `0.36` |
| Cedar, 2.5 | `0`, `0`, `0` | `-0.1`, `0.1`, `0.01` |

The results against r1 stay in the bundle, unchanged, and still pin r1. Their successors are new revisions built with tutorial E's `revise(…, repin=[(outcome r1, outcome r2)])`. Tutorial D's `impact` marks the three r1 results `affected`, each with a corrected latest revision.

## Reproduction

`reproduce(result, records, contents)` recomputes a stored result from **its own pins**, not from the latest revisions:
- `match`: the recomputation gives byte-identical bytes;
- `mismatch`: a consistently re-described but forged result;
- `unavailable`, with reasons: the result's or an input's bytes changed (`content_digest_mismatch`), an input is absent (`missing_input`), an input's body changed (`pin_mismatch`), the rule is not the frozen rule (`rule_unavailable`), the result's pins disagree with its dependency profile (`malformed_input`), or the pinned inputs are now excluded.

No tampered case gives `match`. The script checks each one.

## ForeGlass and real providers

No real forecast is evaluated here. The published ForeGlass files declare no information cutoff, target period or forecast deadline, so a ForeGlass point forecast stays **unavailable**: it is refused, never filled in. The script shows a ForeGlass-shaped forecast, with markers for its unit and cutoff, excluded with `missing_unit` and `missing_cutoff`.

## Limits

- Example-level only: no `comuvia` rule, schema or API. A future core numeric evaluation needs a new rule descriptor, separate from `binary-brier-v1`, and a point-output schema.
- Synthetic results show mechanics, not skill. There is no aggregate.
- A probability is never converted to a point value, or the reverse.
- Digests prove identity, not truth, and there is no independent time evidence.
