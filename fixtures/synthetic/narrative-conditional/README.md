# Fixture A: narrative conditional statement with a later interpretation

Status: valid `comuvia/0.1` records (OSS-1A). References carry computed record digests, and `expected.json` records them. The evaluator reproduces the exclusions in `expected.json` (OSS-1B); the `fixture-a-narrative` case in `packages/comuvia/tests/vectors/evaluation.json` checks them.

## Provenance

Original synthetic content written for the Comuvia SDK. Every programme, person, place and organisation is fictional. Locators use the reserved `example.org` domain and must never be dereferenced. Nothing is derived from a private or third-party source. Every record carries `data_origin: "synthetic"`.

The values were frozen during the project's design review (OSS-0 review, section 5.1); `expected.json` records the results they must produce.

## Files

| Path | Role |
|---|---|
| `source/harbor-weekly-e42-transcript.txt` | Exact retained bytes: UTF-8 without BOM, ASCII only, LF, 530 bytes, `sha256:604226cc5ad7c6b0f67408802241504ddc56de6f6ffd892ce6fe355ec6f07fe9`. Git stores it unconverted (`-text -eol`) |
| `records/res-…json` | Resource snapshot of the transcript. `source_version` is unknown; `source_published_at` has day precision only |
| `records/asr-…json` | The speaker's conditional statement, selected by text quote and code-point position 407–474 (end-exclusive). `media_time` is unknown. `stated_probability: null` records that the speaker stated no probability |
| `records/int-…json` | An analyst's later interpretation. The analyst, not the speaker, is the author. `extraction.confidence` (0.85) is confidence in the reading, not an event probability |
| `expected.json` | Content and record identity, timestamp assurance, and the exclusions a later evaluator must report |

## Shape decisions (OSS-1A)

- A period is `{"start", "end", "inclusive", "precision": "day"}` with date strings. It is never expanded to timestamps.
- `condition` is `{"text", "state", "note"}`. OSS-0's `condition.status` was renamed to `state`, so it no longer reuses the outcome-status vocabulary. `state: "unresolved"` means that the condition itself is undefined and unresolved.
- `source_published_at` has no basis member: it always means the source-declared date. An inferred date is not recorded there.

`tools/sync_vectors.py` recomputes the reference digests; `tools/check_fixtures.py` checks them.
