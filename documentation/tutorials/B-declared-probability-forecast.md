# Tutorial B: a declared-probability forecast, its outcome and a correction

A fictional provider forecasts a 70% probability that Port Calder's first published January 2027 container throughput will be below 400,000 TEU. The first release says 386,500 TEU. This tutorial scores that forecast, reproduces the score from pinned inputs, and then corrects a recording error without rewriting history.

Everything runs offline against the installed `comuvia` wheel, using the synthetic records in `fixtures/synthetic/structured-binary/`. The runnable script [`tutorial_b_forecast.py`](tutorial_b_forecast.py) performs every step below and checks every value this page states:

```sh
python -m pip install comuvia-0.1.0-py3-none-any.whl
python tutorial_b_forecast.py --fixtures fixtures/synthetic --work ./tutorial-b
```

## 1. Four records

- A pinned **question**: its unit, target period, resolution rule and source, first-release vintage, and deadlines.
- The provider's **forecast**: probability 0.7, unconditional, issued before the deadline, with an information cutoff before issue.
- A **snapshot** of the 49-byte bulletin excerpt, whose bytes match its content digest.
- The **outcome**: resolved, value 1, with the snapshot as evidence.

References carry record digests, so the store refuses an outcome whose question reference points at a different body.

## 2. Evaluate

```python
import comuvia
from comuvia import RecordStore
report = comuvia.evaluate(RecordStore("store-b").records())
report.results[0].loss          # 0.09000000000000002
f"{report.results[0].loss:.2f}"  # "0.09"
```

The packaged rule `binary-brier-v1` computes the loss in binary64 as `d = p − o; loss = d * d`: (0.7 − 1)² gives exactly `0.09000000000000002`. The display value `0.09` is rounded to two decimal places, half to even, on that exact binary64 value. Every eligibility check is listed in the rule descriptor, and there is no aggregate mean or skill score.

## 3. Store the evaluation and reproduce it

```python
(evaluation,) = comuvia.evaluation_records(report, records, evaluated_at="2027-02-17T00:00:00Z",
                                           recorded_by="evaluator:tutorial-b", recorded_at="2027-02-17T00:00:00Z")
comuvia.reproduce(evaluation, records).result    # "match"
```

An evaluation record pins the forecast, the outcome and the rule descriptor by digest, and `reproduce` re-derives the result from exactly those inputs.

## 4. Correct a recording error by appending

Suppose the outcome was recorded wrongly. The correction is **outcome revision 2**, whose `predecessor` references revision 1 by digest, with `resolved_value: 0`:

- the new evaluation gives `0.48999999999999994`, displayed as `0.49`;
- the bytes of revision 1 on disk are unchanged;
- the revision 1 evaluation still reproduces `0.09000000000000002`;
- the "latest" view, derived at read time, shows revision 2.

## 5. Verify the store, and know what it checks

`comuvia store verify` reports OK. It checks **identity**: body bytes against their digests, the index, and references. It does **not** check whether a stored evaluation's result is correct. A forged but well-formed evaluation would store; run `comuvia reproduce` for any evaluation you rely on.

## 6. The same from the command line

```sh
comuvia store init store-b-cli
comuvia store append store-b-cli q-port-calder-teu-2027-01.json fc-lantern-port-calder-teu-2027-01.json \
    res-port-calder-bulletin-2027-01-first.json out-port-calder-teu-2027-01.json
comuvia evaluate --store store-b-cli --append --evaluated-at 2027-02-17T00:00:00Z --recorded-by evaluator:tutorial-b
comuvia reproduce --store store-b-cli
comuvia store verify store-b-cli
```

The loss is `0.09000000000000002`, `reproduce` reports `match`, and `store verify` reports OK and states its scope. Exit codes are 0 for success (exclusions are results, not errors), 1 for a refusal or mismatch, and 2 for a usage error.

## What this does not prove

- **Timestamp assurance is unavailable.** `issued_at` is what the provider declared; nothing here proves the forecast existed before the outcome.
- **A digest proves byte and record identity only,** not truth or authorship.
- **One forecast and one outcome say nothing about predictive skill.**
