# Tutorial A: a source-linked statement, honestly excluded

A speaker on a fictional logistics programme says: *"Freight disruption could intensify next winter if the canal closes."* It sounds like a prediction. This tutorial records it faithfully and shows why `comuvia` does **not** score it.

Everything runs offline against the installed `comuvia` wheel, using the synthetic records in `fixtures/synthetic/narrative-conditional/`. The runnable script [`tutorial_a_narrative.py`](tutorial_a_narrative.py) performs every step below and checks every value this page states:

```sh
python -m pip install comuvia-0.1.0-py3-none-any.whl
python tutorial_a_narrative.py --fixtures fixtures/synthetic --work ./tutorial-a
```

## 1. Keep the source bytes exactly

The transcript is 530 bytes of UTF-8 text. A `resource_snapshot` records its content digest and byte length, alongside what was and was not captured. The programme's published date is known only to the day, so it stays `{"date": "2026-01-14", "precision": "day"}` and is never expanded to midnight.

```python
import comuvia
transcript = open("fixtures/synthetic/narrative-conditional/source/harbor-weekly-e42-transcript.txt", "rb").read()
snapshot = comuvia.load_record(open(".../records/res-harbor-weekly-e42-transcript.json", "rb").read())
comuvia.verify(snapshot, content=transcript).content_identity   # "match"
comuvia.content_digest(transcript)   # "sha256:604226cc5ad7c6b0f67408802241504ddc56de6f6ffd892ce6fe355ec6f07fe9"
```

Changing a single line ending, adding a byte order mark or appending a newline makes content identity `mismatch`.

## 2. Record the statement verbatim, and check it against the bytes

The `source_assertion` quotes the speaker exactly. It points at the transcript by reference, including the transcript record's digest, and selects the words by text quote and by code-point position 407–474. The speaker gave no probability, so `stated_probability` is `null`: a known absence, not an unknown value.

```python
comuvia.check_selector(assertion, transcript, snapshot=snapshot).result      # "match"
```

A paraphrase that claims to be verbatim is caught:

```python
paraphrase["quote"]["exact"] = "Freight problems may get worse next winter if the canal shuts."
comuvia.check_selector(paraphrase, transcript).issues[0].code                # "quote_mismatch"
```

## 3. Keep the analyst's reading separate

An analyst later reads the statement as a claim about a freight-delay index above 120 between December 2026 and February 2027. That reading is an `interpretation`:

- a separate record with its own author (`analyst:example-analyst-1`), frozen time and stated assumptions;
- the speaker is never its author;
- its `extraction.confidence` of 0.85 is confidence in the *reading*, not a probability of the event.

## 4. Store and evaluate

```python
from comuvia import RecordStore
RecordStore.create("store-a")
with RecordStore("store-a", writer=True) as store:
    for body in (snapshot, assertion, interpretation):
        store.append(body)
report = comuvia.evaluate(RecordStore("store-a").records())
```

Result: 2 candidates, **0 eligible**, 2 excluded, and every reason is named:

| Record | Exclusion reasons |
|---|---|
| the assertion | `no_declared_probability`, `conditional_scenario`, `no_pinned_question` |
| the interpretation | `not_a_forecast`, `conditional_scenario` |

The value `0.85` appears nowhere in the report, and there is no aggregate score.

## 5. The same from the command line

```sh
comuvia store verify store-a
comuvia evaluate --store store-a
comuvia verify asr-harbor-weekly-e42-ilsley-freight.json --content harbor-weekly-e42-transcript.txt --store store-a
```

`store verify` reports OK. `evaluate` reports the same two exclusions. `verify` reports the reference to the snapshot as `match` and the selector check as `match`. Add `--json` for machine-readable output.

## What this does not prove

- **Timestamp assurance is unavailable.** No time in these records is independently verified.
- **A digest proves byte identity only.** It says nothing about whether the statement is true, who really said it, or when it was published.
- **One example is not skill.** Nothing here measures anyone's predictive ability.
