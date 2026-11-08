# Release 0.1.1: `comuvia`

This directory identifies the exact `comuvia` 0.1.1 files and shows how to rebuild and verify them. `foreglass` was not re-released: 0.1.0 is still its current version, and its requirement `comuvia>=0.1.0,<0.2` admits `comuvia` 0.1.1.

| File | Content |
|---|---|
| [`SHA256SUMS`](SHA256SUMS) | The approved SHA-256 digests of the two `comuvia` 0.1.1 distributions |
| [`BUILD.md`](BUILD.md) | The build recipe, unchanged from 0.1.0, and the pre-upload check |
| [`build-constraints.txt`](build-constraints.txt) | The build backend, `flit_core` 3.12.0, pinned by version and wheel hash (byte-identical to 0.1.0's) |

## What changed

0.1.1 repairs invalid-input handling; results for valid input are unchanged, byte for byte. `evaluate`, `evaluation_records` and `reproduce` now validate every input record and refuse invalid input, and `validate` refuses NaN and infinity. See the [`comuvia` changelog](../../packages/comuvia/CHANGELOG.md).

## What it is built from

| Package | Source directory | Git tree id of that directory at `v0.1.1` | Files |
|---|---|---|---|
| `comuvia` | `packages/comuvia` | `e8b02fe90cd04fdca916df4193436e7cd3f8d7b6` | `comuvia-0.1.1-py3-none-any.whl`, `comuvia-0.1.1.tar.gz` |

To check the release source, compare `git rev-parse v0.1.1:packages/comuvia` with the table. Later commits on `main` may change files that the source distribution includes, so check out tag `v0.1.1`, rebuild as in [`BUILD.md`](BUILD.md) and compare the files with `SHA256SUMS`.

`comuvia` 0.1.1 was published on PyPI on 2026-10-14 from tag `v0.1.1`, which points to commit `82ac9595f44494ee0527619dec89ed8d9c8ad4c0`. The release workflow uploaded it to TestPyPI first, then to PyPI, through Trusted Publishing with attestations.

| File | SHA-256 | Bytes |
|---|---|---|
| `comuvia-0.1.1-py3-none-any.whl` | `aef7efc0efddc657e3430fb6a1fabd80e1ccfcfd442a2e0e632b8c9591181ee7` | 55,261 |
| `comuvia-0.1.1.tar.gz` | `3e4de2b4845625106f6e42ce26d5f920207e851db5d77ce1d2d3f3af4fe74be6` | 78,961 |

**Known cosmetic issue.** The package description shown on PyPI for 0.1.1 still opens with "Version 0.1.0", because the package README had not been updated when 0.1.1 was built. The package metadata correctly says 0.1.1. A published file cannot be changed, so this will be corrected in the next release.

## Verify a download before installing it

Do not let an installer fetch and build a package before its bytes are checked. Instead:

```sh
python -I tools/verify_download.py --index pypi --package comuvia --version 0.1.1 --out verified
```

This reads `https://pypi.org/pypi/comuvia/0.1.1/json` and downloads the listed wheel and sdist as raw bytes. It writes them to `verified/` only if each file's SHA-256 equals both the digest the index declares and the digest in `SHA256SUMS`. It installs and builds nothing. Use `--index testpypi` for TestPyPI. Without `--version`, the tool verifies 0.1.0.

Then install only from the verified file:

```sh
python -m pip install --no-index --no-deps verified/comuvia-0.1.1-py3-none-any.whl
```

To use `foreglass` with it, verify `foreglass` 0.1.0 as described in [release 0.1.0](../0.1.0/README.md#verify-a-download-before-installing-it), into the same directory, and install both wheels from it with `--no-index`.

Build a downloaded sdist only in an isolated step, with the same recipe, from a checkout of tag `v0.1.1`:

```sh
python -I tools/build_release.py wheel-from-sdist verified/comuvia-0.1.1.tar.gz --out rebuilt
```

This fails unless the wheel built from the sdist equals the approved wheel.

## Tested platforms

Before release, the 0.1.1 files were installed from local files into fresh environments on CPython 3.13 on Windows x86-64. There the package tests, the conformance tests, and tutorials A to H all passed, and `foreglass` 0.1.0's tests passed against `comuvia` 0.1.1. The supported Python versions are unchanged from 0.1.0 (3.11 to 3.13); see [Python compatibility](../../documentation/architecture/python-compatibility.md).

## Dependencies and rights

As for [0.1.0](../0.1.0/README.md#dependencies-and-rights): no runtime dependencies, `flit_core` 3.12.0 to build, Apache License 2.0, and original synthetic test data.
