# comuvia

`comuvia` is an offline, provider-neutral library for evidence and prediction records. It keeps exact source bytes separate from record identity. Statements, interpretations, assessments and declared probabilities are distinct record types, and a missing value stays explicitly unknown or withheld. Only explicitly eligible structured forecasts are scored; every other candidate is reported with named exclusion reasons.

Version 0.1.0 · Apache-2.0 · Python 3.11–3.13 · no runtime dependencies · no network access.

## Install

```sh
pip install comuvia
```

This installs the `comuvia` library and the `comuvia` command. There are no dependencies.

## First steps

```python
import comuvia

# Strict parsing refuses ambiguous JSON, by name.
try:
    comuvia.parse_json(b'{"p": 0.7, "p": 0.3}')
except comuvia.RefusalError as refusal:
    print(sorted(refusal.codes))            # ['duplicate_member']

# Identity is SHA-256 over RFC 8785 canonical bytes.
body = comuvia.parse_json('{"b": 1.0, "a": "synthetic"}')
print(comuvia.canonicalize(body))           # b'{"a":"synthetic","b":1}'
print(comuvia.record_digest(body))          # sha256:cc77f650...
```

To score a forecast, take the synthetic records from the [source repository](https://github.com/comuvia/comuvia-sdk) and run this from its root:

```sh
git clone https://github.com/comuvia/comuvia-sdk
cd comuvia-sdk
```

```python
import pathlib
import comuvia

folder = pathlib.Path("fixtures/synthetic/structured-binary/records")
records = [comuvia.load_record(path.read_bytes()) for path in sorted(folder.glob("*.json"))]
report = comuvia.evaluate(records)
(result,) = report.results
print(result.status, result.loss)           # scored 0.09000000000000002
```

## Tutorials

Two offline tutorials walk through the API and the `comuvia` command. Each has a script that checks every value the page states:

- [A: a source-linked statement, honestly excluded](https://github.com/comuvia/comuvia-sdk/blob/main/documentation/tutorials/A-source-linked-statement.md): `python documentation/tutorials/tutorial_a_narrative.py --fixtures fixtures/synthetic --work ./tutorial-a`
- [B: a declared-probability forecast, its outcome and a correction](https://github.com/comuvia/comuvia-sdk/blob/main/documentation/tutorials/B-declared-probability-forecast.md): `python documentation/tutorials/tutorial_b_forecast.py --fixtures fixtures/synthetic --work ./tutorial-b`

Run them from the repository root. Every person, organisation and value in the [fixtures](https://github.com/comuvia/comuvia-sdk/tree/main/fixtures/synthetic) is fictional.

## Capabilities

| Capability | What it does | API | CLI |
|---|---|---|---|
| Record types | Nine `comuvia/0.1` types: `resource_snapshot`, `source_assertion`, `interpretation`, `assessment`, `question`, `forecast`, `outcome`, `evaluation`, `artifact_descriptor`. JSON Schemas ship in the package | `schema_files()`, `RECORD_TYPES` | — |
| Strict parsing | Refuses duplicate members, invalid UTF-8, a BOM, unpaired surrogates, non-finite numbers, integers binary64 would change, and nesting deeper than 64 | `parse_json` | — |
| Validation | Refusals with named codes and JSON Pointers; unknown and withheld markers; day-precision values; namespaced `extensions` | `validate`, `load_record` | `comuvia validate` |
| Identity | RFC 8785 canonical bytes; SHA-256 record and content digests; references that carry digests; separate record, content and reference results | `canonicalize`, `record_digest`, `content_digest`, `reference_to`, `verify`, `revision_conflicts` | `comuvia digest`, `comuvia verify` |
| Selector check | A verbatim quote, its prefix/suffix and its code-point position, checked against retained bytes | `check_selector` | `comuvia verify --content` |
| Record store | Single writer, append-only, crash-safe; corrections are successor revisions; a "latest" view derived at read time; `verify` names each problem | `RecordStore` | `comuvia store init/append/verify/show/repair` |
| Evaluation | The packaged `binary-brier-v1` rule: every failing eligibility check named, all counts shown, raw binary64 losses, **no aggregate score** | `evaluate`, `load_rule` | `comuvia evaluate` |
| Reproduction | Re-derives a stored evaluation from the forecast, outcome and rule it pins by digest | `evaluation_records`, `reproduce` | `comuvia evaluate --append`, `comuvia reproduce` |

## What 0.1.0 promises

- **Record shapes.** The `comuvia/0.1` shapes are frozen: the packaged schemas, and the record digest (SHA-256 over RFC 8785 bytes of the whole body). Any change is a new schema version.
- **Scoring rule.** `binary-brier-v1` version `1`, `sha256:9a0180cf0678614b3d423ca8e641bff9805e8582ce898438d8586251f96877c1`. A changed rule is a new version; a stored evaluation pins its rule by digest.
- **Names.** The names in `comuvia.__all__` and the reason-code strings in `comuvia.reasons`.
- **Exit codes.** The CLI exit codes: 0 success (exclusions are results, not errors), 1 refusal or mismatch, 2 usage error.
- **Store format.** The store directory format `comuvia-store/1`.

**Provisional in 0.1.0:** the CLI's human-readable output and the layout of its `--json` output, and the wording of issue messages. Reason *codes* are stable; message *text* is not.

## Limitations

- **Store detection limit.** `store verify` cannot detect removal of complete index lines at the end, or replacement of a whole store, without an independently retained checkpoint. Checkpoints are not in 0.1.0.
- **Lock scope.** The writer lock is an operating-system lock on `writer.lock`. It coordinates `comuvia` processes on one machine and is not tested on network file systems. Readers never lock.
- **Share exported records, not a store directory.** `writer.lock` holds the current or last writer's pid, host name and time. Share or publish records as record files, for example via `comuvia store show --json --bodies`, not by copying a raw store directory.
- **Day-precision ordering.** A value known only to the day may be any instant of that date at UTC offsets −12:00 to +14:00. Its order against a timestamp inside that window is reported as indeterminate (`indeterminate_time_order`), never guessed.
- **Rule scope.** 0.1.0 scores only unconditional binary forecasts with a declared probability against a resolved binary outcome. There are no interval, point or conditional scorers, and no aggregate, skill or relative scores.
- **Locators.** They are recorded for provenance and never dereferenced. Locators with userinfo credentials are refused, but tokens in query strings (signed URLs) cannot be detected in general: **do not record secret or signed locators.**
- **What a digest proves.** Byte or record identity only. It does not prove truth, authorship or publication time. Timestamp assurance is always reported as `unavailable`, and signatures and proofs are not part of 0.1.0.
- **Scope of `store verify`.** It checks identity, not evaluation correctness. Run `reproduce` for any stored evaluation you rely on.

## Tests

The `tests/` directory in the source distribution checks an installed wheel against language-neutral vectors in `tests/vectors/`. Run it with `python -m unittest discover -s tests`. The optional `jsonschema` and `rfc8785` libraries enable extra agreement checks; they are test-only.

## Source, issues and security

- Source, release checksums and build recipe: [github.com/comuvia/comuvia-sdk](https://github.com/comuvia/comuvia-sdk) ([`release/0.1.0`](https://github.com/comuvia/comuvia-sdk/tree/main/release/0.1.0))
- Issues: [github.com/comuvia/comuvia-sdk/issues](https://github.com/comuvia/comuvia-sdk/issues)
- Reporting a vulnerability: [SECURITY.md](https://github.com/comuvia/comuvia-sdk/blob/main/SECURITY.md)
