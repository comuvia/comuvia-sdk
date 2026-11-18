# Release 0.1.2: `comuvia`

This directory identifies the exact `comuvia` 0.1.2 files and shows how to rebuild and verify them. `foreglass` was not re-released: 0.1.0 remains compatible without re-upload (`comuvia>=0.1.0,<0.2`).

| File | Content |
|---|---|
| `SHA256SUMS` | The approved SHA-256 digests of the two `comuvia` 0.1.2 distributions (written at release approval; until present, `build_release.py check`, `verify_download.py` and the release workflow refuse 0.1.2) |
| [`BUILD.md`](BUILD.md) | The build recipe, unchanged from 0.1.0 and 0.1.1, and the pre-upload check |
| [`build-constraints.txt`](build-constraints.txt) | The build backend, `flit_core` 3.12.0, pinned by version and wheel hash (byte-identical to 0.1.0's and 0.1.1's) |

## What changed

`comuvia` 0.1.2 is a strictly additive `0.1` release: all `comuvia/0.1` JSON Schemas, record digests, `comuvia-store/1` storage layout, and `binary-brier-v1` scoring behavior are unchanged.

- **PEP 561 typing:** `comuvia/py.typed` and schema-derived `TypedDict` definitions in `comuvia.types` (imported on demand).
- **Usability improvements:** `schema_dir()` (`schema_files()` kept as a deprecated alias), minimal envelope builders `new_record()` and `revise()` (explicit `data_origin`, `recorded_by`, `recorded_at`, validated via `validate()`), and a specific validation message when `retained` is supplied on `artifact_descriptor.content`.
- **Store portability and checkpoints:** `RecordStore.export_jsonl()`, `RecordStore.import_jsonl()`, `RecordStore.checkpoint()`, and `RecordStore.verify(checkpoint=...)`, plus `comuvia store export | import | checkpoint | verify --checkpoint`.
- **Detached OpenTimestamps proof parsing:** `comuvia.ots` (`parse_proof`, `Proof`, `Attestation`, `ProofError`, `check_proof_digest`) and `comuvia verify --ots <proof.ots>`. Proofs are parsed offline and never checked against Bitcoin or calendars (`timestamp_assurance` remains `unavailable`).

See the [`comuvia` changelog](../../packages/comuvia/CHANGELOG.md).

## What it is built from

| Package | Source directory | Git tree id of that directory at `v0.1.2` | Files |
|---|---|---|---|
| `comuvia` | `packages/comuvia` | `a2e5a26cc84a7404c5c2eb943c054fed727cf7e9` | `comuvia-0.1.2-py3-none-any.whl`, `comuvia-0.1.2.tar.gz` |

To check the release source, compare `git rev-parse v0.1.2:packages/comuvia` with the table. Later commits on `main` may change files that the source distribution includes, so check out tag `v0.1.2`, rebuild as in [`BUILD.md`](BUILD.md) and compare the files with `SHA256SUMS`.

| File | SHA-256 | Bytes |
|---|---|---|
| `comuvia-0.1.2-py3-none-any.whl` | `0df831f7556231e3eba62b3886e20d50a663fb140a706cb0cb28c7ec898fe299` | 67,032 |
| `comuvia-0.1.2.tar.gz` | `4ec4f45afbb9256d947b228c087fcf4ab2872fb4a993629009fc96c637ade7d6` | 97,282 |

## Verify a download before installing it

Do not let an installer fetch and build a package before its bytes are checked. Instead:

```sh
python -I tools/verify_download.py --index pypi --package comuvia --version 0.1.2 --out verified
```

This reads `https://pypi.org/pypi/comuvia/0.1.2/json` and downloads the listed wheel and sdist as raw bytes. It writes them to `verified/` only if each file's SHA-256 equals both the digest the index declares and the digest in `SHA256SUMS`. It installs and builds nothing. Use `--index testpypi` for TestPyPI. Before approval, the command refuses with `"release/0.1.2/SHA256SUMS is absent"`.

Then install only from the verified file:

```sh
python -m pip install --no-index --no-deps verified/comuvia-0.1.2-py3-none-any.whl
```

To use `foreglass` with it, verify `foreglass` 0.1.0 as described in [release 0.1.0](../0.1.0/README.md#verify-a-download-before-installing-it), into the same directory, and install both wheels from it with `--no-index`.

Build a downloaded sdist only in an isolated step, with the same recipe, from a checkout of tag `v0.1.2`:

```sh
python -I tools/build_release.py wheel-from-sdist verified/comuvia-0.1.2.tar.gz --out rebuilt
```

This fails unless the wheel built from the sdist equals the approved wheel.

## Tested platforms

Before release, the 0.1.2 files were installed from local files into fresh environments on CPython 3.11, 3.12 and 3.13 on Windows x86-64 (`tools/package_smoke.py check`). On each, the `comuvia` package tests (67), `foreglass` 0.1.0's tests against `comuvia` 0.1.2 (39), and tutorials A to H passed, with no network event under the audit hook. The supported Python versions are unchanged from 0.1.0 (3.11 to 3.13); see [Python compatibility](../../documentation/architecture/python-compatibility.md).

## Dependencies and rights

As for [0.1.0](../0.1.0/README.md#dependencies-and-rights): no runtime dependencies, `flit_core` 3.12.0 to build, Apache License 2.0, and original synthetic test data.
