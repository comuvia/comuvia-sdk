# comuvia changelog

## 0.1.0 — 2026-10-01

First release, published on PyPI on 2026-10-01 from tag `v0.1.0`. The copy of this file inside the 0.1.0 source distribution was written before the upload and still calls this version a release candidate.

- **Records.** Nine `comuvia/0.1` record types with packaged JSON Schemas: `resource_snapshot`, `source_assertion`, `interpretation`, `assessment`, `question`, `forecast`, `outcome`, `evaluation` and `artifact_descriptor`. Unknown and withheld markers, day-precision values, required `limitations` codes, and namespaced `extensions`.
- **Strict parsing and validation** with named refusal codes, including a fixed nesting limit of 64 and refusal of integer literals that binary64 would change.
- **Identity.** RFC 8785 canonicalization (in-repository encoder, checked against the RFC's examples and an independent implementation), SHA-256 record and content digests, references that carry digests, `verify`, `revision_conflicts` and `check_selector`.
- **Store.** `RecordStore`: single writer (an OS lock on a persistent `writer.lock`), append-only, crash-safe appends, a read-time latest view, and `verify`, which reports each problem by name and states the checkpoint detection limit.
- **Evaluation.** The packaged `binary-brier-v1` rule descriptor, version `1`, pinned by digest. Every failing eligibility check is reported, including unknown question members, indeterminate day-precision order and limitation exclusions. There is no aggregate score. `evaluation_records` and `reproduce` are included.
- **CLI.** The `comuvia` console script, with `--json` and exit codes 0/1/2, and no network command.
- **No runtime dependencies.** Apache-2.0.

Pre-release development versions (`0.1.0.dev0`) and their scoring-rule descriptors are not supported. An evaluation that pins a pre-release rule digest reproduces as `unavailable` (`rule_not_found`).
