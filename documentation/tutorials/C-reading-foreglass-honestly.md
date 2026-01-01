# Tutorial C: reading ForeGlass honestly

ForeGlass publishes its forecasts as files: a verification ledger, an OpenTimestamps proof, a ledger archive index and index readings. `foreglass` reads those files, keeps their exact bytes, and turns into `comuvia` records **only what the files actually declare**. This tutorial shows that on a synthetic ForeGlass-format ledger, and what it means for evaluation.

Everything runs offline against the installed `comuvia` and `foreglass` wheels, using `fixtures/synthetic/foreglass-ledger/`. That fixture holds fictional content in the public byte format: CRLF line endings, ASCII with escapes, and 12 lanes. The runnable script [`tutorial_c_foreglass.py`](tutorial_c_foreglass.py) performs every step and checks every value stated here about the fixture:

```sh
python -m pip install comuvia-0.1.0-py3-none-any.whl foreglass-0.1.0-py3-none-any.whl
python tutorial_c_foreglass.py --fixtures fixtures/synthetic --work ./tutorial-c
```

## 1. Intake: exact bytes, and a replay is never "live"

```python
archive = foreglass.SnapshotArchive.create("snapshots")
result = archive.intake(foreglass.replay_bundle(files), declared_roles=["ledger", "ledger_ots", "archive_index", "fragility_latest"])
result.verified, result.accepted        # True, False
result.issues[0].code                   # "replay_not_accepted"
```

The bytes are retained unchanged, CRLF line endings included, and re-hashed before anything is accepted. Fixture bytes are `synthetic`, so they can never become the accepted live snapshot.

Unknown provider fields are reported, not fatal. Lane 11 carries outcome keys (`outcome_normalization_unsupported`) and an unknown field (`unrecognized_provider_field`).

## 2. The lane catalog keeps declared meanings

- `lo`/`hi` carry **no declared coverage level**, so `coverage_level` is always unknown. One engine interval is a scenario span (`val == hi`).
- `due` is the provider's grading date, not a target period.
- `sealed_at` is a registration date with no time of day.
- **`built` is a build date, not a publication time.**
- Two lanes sit exactly at the provider's cut lengths (320 and 220 characters). `possibly_truncated` flags them as a *labelled length heuristic*, not as a fact.
- **A reading is not a probability.** `read_reading(...)` gives `is_forecast=False` and `probability=None`, and keeps its caveat verbatim.

## 3. Normalization: map what is declared, name the rest

`foreglass.normalize(snapshot, recorded_at=...)` gives **7 questions and 8 forecasts** from the 9 binary lanes. Not mapped:

| Lanes | Reason |
|---|---|
| 2 interval lanes, 1 point lane | `unsupported_output_kind`: **interval and point lanes are not scored in 0.1** |
| 1 binary lane with a blank `qid` | `no_pinned_question`: no identity is fabricated |

Each mapped forecast has:

- a question whose text and rule are the provider's `statement` and `criteria`, verbatim;
- `issued_at` equal to the day-precision `sealed_at`;
- an explicit unknown `information_cutoff`;
- unknown target period, deadlines, vintage and model version;
- the provider's caveats and units preserved.

A lane that publishes no unit gets the unit marker `provider_declares_no_unit`. A model-conditional caveat becomes an unresolved condition. Every snapshot's `source_published_at` is unknown (`source_declares_build_date_only`), because `built` is never used as a publication time.

## 4. Evaluation: 0 eligible, every reason named

```python
report["evaluation"]["counts"]   # candidates 8, eligible 0, excluded 8
```

Every forecast is excluded by name:

- **Every forecast:** `incomplete_question` and `missing_required_time`, because the public files declare no information cutoff, target period or forecast deadline; and `no_outcome_recorded`.
- **Some forecasts additionally:**
  - `conditional_scenario` for the model-conditional lane;
  - `retrospective_registration` where the outcome was published before registration;
  - `resolution_rule_incomplete` where the criteria may be truncated.

**Under the current public ledger shape, no lane is eligible, because there is no information cutoff.** This describes the published metadata, not the quality of the forecasts. A replay of the real public ledger gives 78 forecasts in 11 questions, also 0 eligible. That build is identified by its digest, not by a date: `built: "2026-09-09"`, `sha256:3c97f09f67ca416bce27da2c10d5269ebe2f153e15b035a7f0d92d00f5ea6a45`, read on 2026-09-24. The script does not check these three figures, because no bytes of the real ledger are in this repository.

## 5. Store the records

All records are appended to a `comuvia` `RecordStore`, and `store verify` reports OK.

## Opt-in live read

`--live` makes **explicit network requests** to `https://foreglass.ai` for the ledger and the archive index, through `PublicClient`:

- https only, on the host allow-list;
- at most 3 re-checked redirects;
- a 4 MiB cap;
- timeouts and a total deadline;
- at most 2 retries.

It then runs intake (a live read can be accepted) and normalization. The tests never run it, and neither does the script unless you pass `--live`.

## What this does not prove

- **Timestamp assurance is unavailable.** The `.ots` proof is retained as bytes and not verified.
- **A digest proves byte identity only,** not the truth of any forecast.
- **0 eligible is not a verdict on skill.** It follows from the published metadata.
