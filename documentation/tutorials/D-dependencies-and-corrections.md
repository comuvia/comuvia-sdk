# Tutorial D: declared dependencies and the impact of a correction

A fictional port publishes quarterly container throughput. An annual total, a chart and a stress simulation are built from it. Then the source corrects one quarter. Which outputs are now out of date, which are untouched, and which cannot be judged? This tutorial records the dependencies, appends the correction without rewriting anything, and answers that question honestly.

Everything runs offline against the installed `comuvia` wheel, using the synthetic records in `fixtures/synthetic/dependency-correction/`. The dependency logic is an **example helper**, [`dependency_profile.py`](dependency_profile.py), built only on the public `comuvia` 0.1.0 API. It is not part of the package. The runnable script [`tutorial_d_dependencies.py`](tutorial_d_dependencies.py) performs every step below and checks every value this page states:

```sh
python tutorial_d_dependencies.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
```

## What `comuvia` 0.1.0 checks, and what it leaves to you

| Layer | Checked by the package | Not checked |
|---|---|---|
| `validate` | Each record's shape. `predecessor` is `null` at revision 1 and otherwise names the same record at the previous revision. Extension keys look like `name.name/vN` | Anything inside `extensions`, which is hashed and preserved but never interpreted |
| `verify(body, content=, records=)` | The record digest, retained bytes against `content`, and every reference in a core field, `predecessor` included | References inside `extensions` |
| `RecordStore.append` | Refuses unresolved or mismatched core references, and a second body for the same record revision | Extension pins: a record whose extension pins nothing real is stored |
| `revision_conflicts`, `latest_revisions` | Duplicate bodies; the latest revision of each record | Which dependents a correction affects |
| `data_origin` | `observed` or `synthetic` | "Derived" cannot be stated in a core field. Only `artifact_descriptor` has `units` |

So a dependency kept in an extension is only as good as the code that checks it. That is what the helper does, for one documented profile.

**What stays with you, the application:**
- capture the inputs you actually consumed, when you consume them;
- decide whether your declared inputs are complete;
- decide whether an unchanged basis lets you reuse a result;
- own your selectors, models, change triggers and private data;
- make any claim about truth, causation or correctness.

## The profile `org.comuvia.dependencies/v1`

The profile is one object under `extensions["org.comuvia.dependencies/v1"]` of a `resource_snapshot` or `artifact_descriptor`. A record without it is not profiled. Every key below is required and none may be added. As everywhere in `comuvia/0.1`, "unknown" is stated, never left out.

| Key | Value | Meaning |
|---|---|---|
| `value_origin` | `observed`, `derived`, `synthetic` or `none` | What kind of values the artifact holds. `none` is for a method, configuration or text with no data values. It is separate from `data_origin`, which says whether the record describes real or invented material |
| `meaning` | Exactly `measure`, `unit`, `period` and `geography`, each a non-empty string or an `unknown` or `withheld` marker | Never filled in by the helper. If an `artifact_descriptor`'s `units` is a list and `meaning.unit` is a string, the list must contain it |
| `coverage` | `complete`, `partial` or `unknown` | The producer's statement about whether `depends_on` lists every input. No code can check it |
| `depends_on` | 0 to 64 edges, in any order | The declared inputs |

Each edge has exactly three keys:
- `role`: `data_input`, `method` or `assumption`;
- `pin`: a `comuvia.reference_to(...)` value, which pins one exact revision by its digest, or a marker for an input you know about but cannot pin;
- `selection`: what part of the input was used, as text or a marker. It is recorded and **never interpreted**: every dependent of a superseded edition is flagged, whatever it selected.

**Origin rules.** An `observed` record has no `data_input` edge. A `derived` record has at least one. A record with `data_origin: "observed"` cannot have `value_origin: "synthetic"`.

**Each edge resolves to one state:**

| State | When |
|---|---|
| `match` | The pinned revision is in the bundle with the pinned digest |
| `mismatch` | It is there with a different digest |
| `missing` | It is not there |
| `marker` | The pin is an `unknown` or `withheld` marker |

Only `match` edges are followed.

## The example graph

| Record | `value_origin` | Declared inputs |
|---|---|---|
| `src-calder-quarterly` r1, r2 | observed: quarterly TEU, 2026 | none |
| `method-annual-sum`, `model-calder-stress` | none | none |
| `synth-shock-path` | synthetic | none |
| `res-calder-annual` r1, r2 | derived: annual TEU | the source (r1 or r2), the method |
| `chart-calder-quarterly` r1 | derived | the source r1 |
| `sim-calder-stress` r1, r2 | derived | the result (r1 or r2), the shock path, the model |
| `src-calder-fuel`, `out-calder-fuel` | observed; derived | none; the fuel source |
| `out-calder-mixed` | derived, coverage **partial** | the fuel source |

Every record has `data_origin: "synthetic"`, because all of it is invented.

## Step 1: check the bundle

`check_bundle(records, contents)` returns every core issue (from `validate` and `revision_conflicts`) and every profile issue, sorted, each with the record, a JSON Pointer and a code. With `contents`, it also checks retained bytes through `comuvia.verify`. The committed bundle has no issues. Every record validates, every retained file matches its record's digest, and every `predecessor` resolves as `match`.

## Step 2: the impact of the correction

The source's r2 corrects one quarter. `impact(records, changed)` with that r2 gives each other profiled record exactly one status:

| Status | Rule | In the example |
|---|---|---|
| `affected` | A path of `match` edges leads to a superseded edition, here source r1 | result r1, chart r1, simulation r1 |
| `unaffected` | No such path, **and** every record reachable through `match` edges, itself included, has `coverage: "complete"` and only `match` edges | method, model, shock path, result r2, simulation r2, fuel source, fuel output |
| `unknown` | Otherwise, with reasons: `missing_pin`, `withheld_pin`, `unknown_pin`, `pin_mismatch`, `partial_coverage`, `unknown_coverage`, `unprofiled_input` (a `match` pin to a record without a valid v1 profile) | the fuel-per-call output: `partial_coverage` |
| `unknown`, reason `invalid_profile` | The record's own v1 profile is invalid (`check_bundle` names the problem). It has no path and is never followed | none in the committed fixture; the script shows one |

For each `affected` record, the report gives:
- the path, shortest first;
- the record's latest revision in the bundle;
- that revision's own status.

In the example:

| Record | Path | Latest revision | Meaning |
|---|---|---|---|
| Result r1 | result r1 → source r1 | r2, `unaffected` | corrected |
| Simulation r1 | simulation r1 → result r1 → source r1 | r2, `unaffected` | corrected |
| Chart r1 | chart r1 → source r1 | r1 itself | **needs review** |

The fuel output is unrelated and stays `unaffected`. The fuel-per-call output is `unknown`: its producer said its inputs are only partly declared, so nothing can say it is untouched.

The report also says what changed between the two source editions: `content_changed`, `meaning_changed`, `dependencies_changed`, and `changed_fields`, which lists every top-level field that differs except `revision` and `predecessor`. Its `coverage` is `complete` only when no record is `unknown`, and it is `partial` here. For each record it notes whether a `synthetic` record is in its closure, as the stress simulation's is. The report is the same whatever order the records come in, and it equals `expected.json`.

## Step 3: nothing is rewritten

The ten records that existed before the correction go into a `RecordStore`, and then the three r2 records are appended. All ten keep their digests, `store verify` is ok, and there are no revision conflicts. A correction is a new revision. The chart, which has no successor, still pins source r1, and that is exactly why it is flagged.

## Step 4: what the store does not check

A record whose extension pins a record that does not exist is a valid 0.1 record, and `RecordStore.append` accepts it, because core checks skip extensions. `check_bundle` reports it as `missing_pin`, and `impact` makes it `unknown` (`missing_pin`), never `unaffected`.

## Step 5: tampering, withheld inputs and stale pins

- **A tampered input.** If a pinned record's body is edited, its dependents' pins become `mismatch`. `check_bundle` reports `pin_mismatch`, the dependents become `unknown` (`pin_mismatch`), and the report's coverage is `partial`.
- **Tampered bytes.** If retained bytes are edited, `check_bundle` reports `content_digest_mismatch`.
- **A withheld input.** A `withheld` pin makes its record `unknown` (`withheld_pin`).
- **Stale mutual pins.** Two records that pin each other at stale digests give two `mismatch` edges. The walk ends normally. A real cycle cannot form through `match` edges, because each digest commits to the digests it pins. The helper still checks for one and refuses with `dependency_cycle`; the script shows that refusal only by deliberately breaking the digest function.

## Step 6: a correction to meaning only

A source r2 with the same bytes but a different `meaning.unit` reports `content_changed: false` and `meaning_changed: true`. It flags the same three records as the bytes correction did. A change of meaning matters even when every number is equal.

## Refusals and issue codes

Profile issue codes from `check_bundle`:
- `unsupported_profile_version`: an `org.comuvia.dependencies/vN` key other than v1. The helper refuses to guess;
- `invalid_profile`: a missing, extra or ill-typed key;
- `unsupported_role`, `duplicate_pin`;
- `observed_has_inputs`, `derived_without_inputs`, `origin_conflict`, `unit_conflict`;
- `missing_pin`, `pin_mismatch`;
- `content_digest_mismatch`;
- `limit_exceeded`: more than 10,000 records or 64 edges.

Core issues from `validate` and `revision_conflicts` pass through unchanged.

`impact` raises instead of returning a partial report:
- `change_not_successor`: the changed record is not revision 2 or later in the bundle, or its `predecessor` does not resolve as `match`;
- `dependency_cycle`.

The script triggers each one. The walk uses no recursion, so a long chain is not a problem; the script checks a chain of 2,000 derived records.

## Limitations

- A declared dependency does not prove causation, completeness or correctness.
- Digests prove byte and record identity, not truth.
- There is no independent time evidence: declared times are as recorded.
- Coverage is the producer's statement; an omitted input cannot be detected.
- `selection` is not interpreted, so a dependent that used only an unchanged part of a corrected source is still flagged. Pruning by selection is your decision.
- Re-checking an unchanged basis creates nothing new. Whether a new target or a changed input requires recomputation is your decision; this profile only records the evidence.
- This is an example profile, not package behavior. Records using it are ordinary `comuvia/0.1` records that every 0.1 tool reads unchanged.
