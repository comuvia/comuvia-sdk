# Working with `comuvia` 0.1 records

This page covers five details of the `comuvia/0.1` records that often surprise people the first time they build records by hand, and how to handle each one with `comuvia` 0.1.0. None of them is a bug. They follow from the frozen 0.1 contract, in which every field is required and "not known" is always stated rather than left out.

The Python blocks run in order, in one session, against an installed `comuvia` 0.1.0. They use synthetic values only.

## 1. Two kinds of `content`

`resource_snapshot` and `artifact_descriptor` both have a `content` object. The rules differ, because the two record types say different things.

| | `resource_snapshot.content` | `artifact_descriptor.content` |
|---|---|---|
| What it describes | The bytes of a resource you read, which you may or may not have kept | A file you hold, such as a dataset, article or chart |
| `retained` | Required: `true` or `false` | Not allowed |
| `byte_length`, `digest` | Real values when `retained` is `true`. Otherwise each may be an `unknown` or `withheld` marker | Always real values |
| `media_type` | A media type or a marker | Always a media type |

A descriptor always identifies bytes that exist, so it has neither a `retained` flag nor markers. If you reuse a snapshot's `content` object in a descriptor, validation refuses it:

```python
import comuvia

csv_bytes = b"month,container_teu,release\n2027-01,385120,first\n"
descriptor = {
    "schema": comuvia.SCHEMA_VERSION,
    "record_type": "artifact_descriptor",
    "id": "art-example-bulletin-2027-01",
    "revision": 1,
    "predecessor": None,
    "data_origin": "synthetic",
    "content": {
        "media_type": "text/csv; charset=utf-8",
        "byte_length": len(csv_bytes),
        "digest": comuvia.content_digest(csv_bytes),
    },
    "content_schema": "month,container_teu,release",
    "origin": {"name": "Example statistical bulletin (fictional)", "locator": "https://example.org/bulletins/"},
    "published_at": {"date": "2027-02-15", "precision": "day"},
    "retrieved_at": "2027-02-16T09:30:00Z",
    "units": ["TEU"],
    "rights_reference": {"unknown": "rights_not_reviewed"},
    "access": "public",
    "locator": "https://example.org/bulletins/2027-01.csv",
    "recorded_by": "recorder:example",
    "recorded_at": "2027-02-16T09:50:00Z",
}
assert comuvia.validate(descriptor) == []

snapshot_style = dict(descriptor, content=dict(descriptor["content"], retained=True))
assert [(i.pointer, i.code) for i in comuvia.validate(snapshot_style)] == [("/content/retained", "unrecognized_member")]
```

A marker in a descriptor's `digest` gives `malformed_digest`.

## 2. `schema_files()` returns a directory

Despite its plural name, `comuvia.schema_files()` returns the packaged schema **directory**, an `importlib.resources` traversable that is often a `pathlib.Path`. Iterating over it directly raises `TypeError`, so call `.iterdir()`:

```python
folder = comuvia.schema_files()
names = sorted(path.name for path in folder.iterdir())
assert len(names) == 10  # one schema per record type, plus common.json
assert "common.json" in names and "source_assertion.json" in names
```

## 3. Text resources and `media_time`

A `source_assertion` selector must give all three of `text_quote`, `text_position` and `media_time`, even when the source is plain text.

0.1 has two markers for a value you cannot give:
- `{"unknown": "<code>"}`: the value exists, but you do not know it;
- `{"withheld": "<code>"}`: you know the value but do not disclose it.

Neither says "this does not apply", and 0.1 has no third marker. A plain-text resource has no timeline, so its `media_time` does not exist. The closest 0.1 can say is an `unknown` marker whose code and note state that the field does not apply:

```json
"media_time": {"unknown": "not_applicable", "note": "text resource: it has no timeline"}
```

Read this value as "does not apply", not as a missing time. A consumer that treats every `unknown` as missing data should check for the `not_applicable` code.

A recording or video does have a timeline. If you kept only its transcript, the timing exists but you do not know it, and that is a true `unknown`. The synthetic [narrative fixture](../../fixtures/synthetic/narrative-conditional/README.md) records `{"unknown": "caption_timing_not_retained"}` this way.

## 4. Result objects are frozen dataclasses

`SelectorCheck`, `Verification`, `ReferenceCheck`, `EvaluationReport`, `CandidateResult`, `Reproduction`, `StoreReport`, `StoreEntry`, `ScoringRule` and `Issue` are frozen dataclasses. A dataclass field can belong to each instance rather than to the class, so `dir()` of a class can miss fields. `dir(comuvia.SelectorCheck)`, for example, lists none of its three. Use `dataclasses.fields()`, `help()` or `dir()` of an instance:

```python
import dataclasses

assert [field.name for field in dataclasses.fields(comuvia.SelectorCheck)] == ["result", "checked", "issues"]
```

## 5. The record envelope

Every record starts with the same eight fields:
- `schema`, `record_type`, `id`, `revision` and `predecessor`;
- `data_origin`, `recorded_by` and `recorded_at`.

0.1.0 has no record builder, so most projects write a small helper. Two helpers are enough. They are a pattern, not part of the library. They fill only the mechanical fields, and they deliberately have no default for who recorded a record or when:

```python
def envelope(record_type, record_id, *, data_origin, recorded_by, recorded_at):
    """The envelope of a first revision."""
    return {"schema": comuvia.SCHEMA_VERSION, "record_type": record_type, "id": record_id,
            "revision": 1, "predecessor": None, "data_origin": data_origin,
            "recorded_by": recorded_by, "recorded_at": recorded_at}


def next_revision(record, *, recorded_by, recorded_at, **changes):
    """A corrected copy of ``record``: the next revision, pointing to the revision it replaces."""
    return {**record, **changes, "revision": record["revision"] + 1,
            "predecessor": comuvia.reference_to(record),
            "recorded_by": recorded_by, "recorded_at": recorded_at}


first = {**descriptor, **envelope("artifact_descriptor", descriptor["id"], data_origin="synthetic",
                                  recorded_by="recorder:example", recorded_at="2027-02-16T09:50:00Z")}
corrected = next_revision(first, recorded_by="recorder:example", recorded_at="2027-02-17T08:00:00Z",
                          units=["TEU (twenty-foot equivalent units)"])
assert comuvia.validate(first) == [] and comuvia.validate(corrected) == []
assert corrected["predecessor"]["digest"] == comuvia.record_digest(first)
```

A correction is a new revision, never an edit of the earlier record. [Tutorial B](../tutorials/B-declared-probability-forecast.md) corrects an outcome this way. [Tutorial E](../tutorials/E-authoring-and-revising-records.md) turns these two helpers into an example module that also refuses missing provenance and protected fields, and finds stale pins.
