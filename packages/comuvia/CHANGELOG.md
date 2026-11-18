# comuvia changelog

## 0.1.2 — 2026-11-18

Additive usability, typing, store portability/checkpoint, and detached proof-parsing improvements on the unchanged `comuvia/0.1` schema and `comuvia-store/1` layout. Zero runtime dependencies; existing 0.1.0 and 0.1.1 records, stores and evaluations remain byte-for-byte compatible.

- **PEP 561 typing (`comuvia/py.typed`, `comuvia.types`).** Ships `py.typed` and `comuvia.types` (generated deterministically from `schemas/v0_1/*.json` by `tools/sync_vectors.py` and imported on demand).
- **Usability improvements.**
  - `schema_dir()` returns the packaged `v0_1` schema resource directory; `schema_files()` remains available as a deprecated alias with unchanged return type.
  - `new_record(record_type, id, *, data_origin, recorded_by, recorded_at, **fields)` and `revise(record, *, data_origin, recorded_by, recorded_at, **changes)` remove mechanical envelope boilerplate (`schema`, `revision`, `predecessor`) while requiring explicit provenance (`data_origin` is never silently inherited), refusing protected envelope overrides (`protected_field`), and validating through `validate()`.
  - Supplying `retained` inside `artifact_descriptor.content` still fails with `unrecognized_member` at `/content/retained` and now explains `"artifact_descriptor content always identifies retained bytes; omit 'retained'"`.
- **Store JSONL portability and tamper-evident checkpoints.**
  - `RecordStore.export_jsonl(path=None)` verifies the store and emits canonical RFC 8785 JSONL records in sequence order; `RecordStore.import_jsonl(source)` pre-validates parsing, schemas, references and revision conflicts across the whole batch before appending.
  - `RecordStore.checkpoint()` emits a `comuvia-checkpoint/1` prefix commitment over `index.jsonl`; `RecordStore.verify(checkpoint=...)` detects tail truncation, store replacement or prefix alteration (`checkpoint_mismatch`, `checkpoint_invalid`) while permitting later append-only extensions.
  - CLI subcommands added: `comuvia store export`, `comuvia store import`, `comuvia store checkpoint`, and `comuvia store verify --checkpoint`.
- **Neutral OpenTimestamps detached proof parser (`comuvia.ots`).**
  - `comuvia.ots` (`parse_proof`, `Proof`, `Attestation`, `ProofError`, `check_proof_digest`) parses `.ots` headers, bounded operation trees and attestations offline, and `comuvia verify --ots <proof.ots>` inspects standalone proofs or checks them alongside records/content (`proof_invalid`, `proof_digest_mismatch`). Attestations are never verified against Bitcoin or calendars (`timestamp_assurance` remains `"unavailable"`).

## 0.1.1 — 2026-10-14

A repair of invalid-input handling. Results for valid input are unchanged, byte for byte.

- **`evaluate`, `evaluation_records` and `reproduce` refuse invalid input.**
  - They run `validate` on every input record first, and on the evaluation passed to `reproduce`.
  - If any record is invalid, they raise `RefusalError` with every issue. Each pointer is prefixed with `/<index>`, the record's position in the input, or with `/evaluation`.
  - No partial report is returned. This is fail-closed: an invalid record that pairs with nothing still refuses the call.
  - In 0.1.0, records passed in memory were scored even when `validate` refused them, for example a probability of 1.2 or a `resolved_value` of 2. Records read from a store were already validated.
- **`validate` refuses non-finite numbers.** A NaN, `+inf` or `-inf` float at any schema-checked position gives `non_finite_number`, the code strict parsing already uses, and no range check runs on it.
  - In 0.1.0 an in-memory NaN passed `validate`.
  - **In-memory infinity changes code:** where 0.1.0 gave `out_of_range`, 0.1.1 gives `non_finite_number`.
  - Top-level `extensions` stay unchecked by `validate`, as before.
- **Records are JSON-shaped: arrays must be lists.** A tuple where the schema expects an array (for example `limitations=()`) is refused as `invalid_type`. 0.1.0's `evaluate` scored such records, although its `validate` already refused them.
- **No change** to the schemas, the `binary-brier-v1` descriptor, the reason vocabulary, `verify`, the store or the CLI.

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
