# Tutorial H: checking a consumer's own pinned evaluation

An application has already compared forecasts with an outcome: its own protocol, scoring code, outcome manifest and result file, each pinning the others by digest. This tutorial does not score anything again. It wraps that existing evaluation in `comuvia` records and checks that every reference inside it still holds. It also checks that nothing was removed relative to an expectation kept elsewhere, and keeps different kinds of correction apart.

Everything runs offline against the installed `comuvia` wheel, using `fixtures/synthetic/pinned-evaluation/`. The providers, release, values and script are **fictional**. The logic is an example helper, [`pinned_evaluation.py`](pinned_evaluation.py), built on the public `comuvia` 0.1.0 API. The runnable script [`tutorial_h_pinned_evaluation.py`](tutorial_h_pinned_evaluation.py) checks every value this page states:

```sh
python tutorial_h_pinned_evaluation.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
```

## Why not tutorial F

Tutorial F evaluates point forecasts whose issue time and information cutoff are exact timestamps. A real provider often publishes only a **date**, and does not say what information its forecast used. Inventing a time of day or an information cutoff to fit tutorial F would be false. So:
- **Dates stay dates.** Issue dates keep `issue_date_precision: "date-only"`, and eligibility is "issued strictly before the boundary date".
- **Unknowns stay unknown.** A provider's information set is an `unknown` marker.
- **The consumer scores.** Its result holds the errors; the SDK checks identities and references, and never recomputes a score.

## Wrapping the evaluation

Each file becomes a record:
- external originals (forecast files, the release page, a later vintage table) as `resource_snapshot`s;
- the protocol, code, outcome manifest, result and a report as `artifact_descriptor`s.

Tutorial D's dependency profile links them: the result has `data_input` edges to the manifest and forecast files, a `method` edge to the code and an `assumption` edge to the protocol. The manifest has a `data_input` edge to the release page.

## References embedded in a payload

A consumer's own files often refer to their inputs **inside their content**, for example `{"file": "source/wren-forecasts.csv", "raw_sha256": "…"}`. None of `comuvia`'s core checks, nor tutorials D to G, look inside a payload for these. `check_embedded(payload, locate)` does:

- It finds every `comuvia.reference_to` pin, and every object with a locator key (`path` or `file`) and a digest key (`sha256`, `raw_sha256` or `content_sha256`). A digest is 64 lowercase hex digits, bare or prefixed `sha256:`, and must match in full.
- It resolves each locator **only** through the `locate` callable you supply, from an explicit map. It never guesses by file name. For a pin, `locate` receives `(record_type, id, revision)` and returns that record's canonical bytes.
- Each reference is `match`, `mismatch`, `missing` (no bytes found), `malformed`, `ambiguous`, or `exempt` (named by you, with a reason).
- An object with more than one locator key, such as `path` and `file`, or more than one digest key, such as `sha256` and `raw_sha256`, is `ambiguous` whatever its values. It is never resolved by guessing which key was meant.

This catches what a record check alone cannot. If the retained bytes of a forecast file are altered and their record is **re-described consistently**, the record verifies against the new bytes. The result's embedded reference still holds the original digest, so it reports `mismatch`.

## An independent expectation

`expectation(records)` lists every record key and digest, and the latest revision of each id. Keep it somewhere **other than** the bundle it describes. `check_expectation(records, expected)` then reports:
- `missing`: an expected record is gone;
- `unexpected`: a record that was not expected;
- `changed`: same key, different digest;
- `tail_removed`: an id whose latest revision is now older than expected, which is what silently deleting a correction looks like.

An expectation stored next to the records, and replaceable with them, proves nothing. One retained independently detects what the records alone cannot.

**Before comparing,** `preflight(records, expected)` reports:
- `duplicate_keys`: the same record key more than once, with the same digest;
- `conflicting_keys`: the same key with different bodies;
- `expected_duplicates`: a key repeated in the expected manifest;
- `expected_latest_mismatch`: the manifest's `latest` disagrees with its own entries.

`check_expectation` runs it first and compares nothing while it fails. Without it, a duplicate would silently collapse to one entry.

## Three kinds of correction, kept apart

| Kind | In the fixture | What happens |
|---|---|---|
| **Transcription correction** | Result r1 copied one provider's value wrongly (2.8 instead of 2.9); r2 corrects it | A new revision of the result. Its dependent report becomes `affected` under `impact`. r1 keeps its slip and its digest |
| **Official erratum** | The release page's r2 adds an erratum notice; no estimate changes | A new revision of the snapshot. The outcome manifest, which pins r1, becomes `affected`. The original page is kept |
| **Later vintage** | A later table with second and third estimates | A separate record. Nothing in the evaluation depends on it, and the first-release evaluation still verifies |

## Walking through the checks

1. **The bundle is clean.** Every record validates, every content matches, and tutorial D's profile check reports nothing.
2. **Embedded references match.** Both result revisions have 6 matching references each, one of them a `comuvia` pin; the manifest has 1. An exemption is explicit and carries its reason.
3. **Re-described bytes are caught.** Altered forecast bytes with a consistently re-described snapshot verify as a record, but the result's embedded reference reports `mismatch`.
4. **Bad references are named.** A digest that is not 64 hex digits, including one ending in a newline, is `malformed`; an unresolvable locator is `missing`.
5. **The expectation check.** Removing result r2 gives `tail_removed` and `missing`; an extra record is `unexpected`; an altered record is `changed`.
   - **Ambiguity:** `path` and `file` together, or `sha256` and `raw_sha256` together (even with equal values), give `ambiguous`.
   - **Preflight:** a duplicated record gives `duplicate_keys`, and a same-key different body gives `conflicting_keys`. A duplicated expected entry gives `expected_duplicates`, and an inflated `latest` gives `expected_latest_mismatch`. `check_expectation` refuses each before comparing.
6. **The correction classes,** as in the table. Every record keeps its digest in a `RecordStore`.
7. **No invented time.** No source or artifact file contains a date-time. Issue and release dates are dates, and the provider information sets are unknown. ForeGlass is `unavailable`, never substituted.

## Limits

- The SDK computes no score here; the consumer's own result holds the errors.
- A digest identifies bytes; it does not prove a forecast was issued on its stated date, or what it knew.
- `locate` decides what bytes are checked. A wrong locator map checks the wrong bytes, so keep it explicit.
- The record envelopes carry their own required recording times (`recorded_at` and similar). Those are when the records were made, not when any forecast was issued.
- Example-level only: no new `comuvia` API. The records are ordinary `comuvia/0.1` records.
