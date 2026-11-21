# Release 0.1.3: `comuvia`

This directory identifies the `comuvia` 0.1.3 build recipe and shows how to rebuild and verify the distributions. `foreglass` was not re-released by this line: 0.1.0 remains compatible without re-upload (`comuvia>=0.1.0,<0.2`).

| File | Content |
|---|---|
| `SHA256SUMS` | The approved SHA-256 digests of the two `comuvia` 0.1.3 distributions (written at release approval; until present, `build_release.py check`, `verify_download.py` and the release workflow refuse 0.1.3) |
| [`BUILD.md`](BUILD.md) | The build recipe, unchanged from 0.1.0, 0.1.1 and 0.1.2, and the pre-upload check |
| [`build-constraints.txt`](build-constraints.txt) | The build backend, `flit_core` 3.12.0, pinned by version and wheel hash (byte-identical to 0.1.0's, 0.1.1's and 0.1.2's) |

## What changed

`comuvia` 0.1.3 is a strictly additive `0.1` release: all `comuvia/0.1` JSON Schemas, record digests, `comuvia-store/1` storage layout, and `binary-brier-v1` scoring behavior are unchanged.

- **Packaged profiles and selection-aware impact (`comuvia.profiles`):**
  - `comuvia.profiles.dependencies` packages `org.comuvia.dependencies/v1` and adds `org.comuvia.dependencies/v2` with structured `selection` descriptors (`json_pointer`, `text_quote`, `byte_range`, `line_range`) so `impact(..., contents=...)` reports `selection_status` (`unchanged`, `changed` or `unscoped`) on affected dependents when a container is revised.
  - `comuvia.profiles.edition_review` packages `edition-review/1`, `review-summary/1` and `contribution/1` (`review_status`).
  - Opt-in profile checking on `verify(..., check_profiles=True)`, `RecordStore.append(..., check_profiles=True)`, `RecordStore.import_jsonl(..., check_profiles=True)`, `RecordStore.verify(..., check_profiles=True)` and `comuvia store verify --profiles`.
- **Pin-cascade and content builders:** `revise(..., repin=..., require_change=..., enforce_monotonic_time=...)`, `stale_pins()`, `snapshot_content()`, `unretained_content()`, `descriptor_content()`, `not_applicable_marker()`, `is_not_applicable()` and `runtime_identity()`.
- **Deterministic quote locating and audiovisual `media_time` verification:** `locate_quote()` and `check_selector(..., media_duration=..., timed_segments=...)`.
- **Whole-bundle verification and independent expectations:** `verify_bundle()`, `check_embedded()`, `preflight()`, `expectation()`, `check_expectation()`, and `comuvia bundle verify | expectation`.

See the [`comuvia` changelog](../../packages/comuvia/CHANGELOG.md) and [Tutorial J](../../documentation/tutorials/J-bundle-and-selection-impact.md).

## What it is built from

| Package | Source directory | Git tree id of that directory at `v0.1.3` | Files |
|---|---|---|---|
| `comuvia` | `packages/comuvia` | `0262a7e03a9f27d2d6327f41560edbecf85f42f5` | `comuvia-0.1.3-py3-none-any.whl`, `comuvia-0.1.3.tar.gz` |

To check the release source, compare `git rev-parse v0.1.3:packages/comuvia` with the table. Later commits on `main` may change files that the source distribution includes, so check out tag `v0.1.3`, rebuild as in [`BUILD.md`](BUILD.md) and compare the files with `SHA256SUMS`.

| File | SHA-256 | Bytes |
|---|---|---|
| `comuvia-0.1.3-py3-none-any.whl` | `f842fc63b632fcb24dd97bf5c94638f1893a9df0cbbf98425f7a464a4e6e65b7` | 93,309 |
| `comuvia-0.1.3.tar.gz` | `fa569376e36ecf1c2e6936e817ddd7b8de0ee8b18144164e6f7a1fcfece7bc24` | 132,758 |

## Verify a download before installing it

Do not let an installer fetch and build a package before its bytes are checked. Instead:

```sh
python -I tools/verify_download.py --index pypi --package comuvia --version 0.1.3 --out verified
```

This reads `https://pypi.org/pypi/comuvia/0.1.3/json` and downloads the listed wheel and sdist as raw bytes. It writes them to `verified/` only if each file's SHA-256 equals both the digest the index declares and the digest in `SHA256SUMS`. It installs and builds nothing. Use `--index testpypi` for TestPyPI. Before approval, the command refuses with `"release/0.1.3/SHA256SUMS is absent"`.

Then install only from the verified file:

```sh
python -m pip install --no-index --no-deps verified/comuvia-0.1.3-py3-none-any.whl
```

To use `foreglass` with it, verify `foreglass` 0.1.0 as described in [release 0.1.0](../0.1.0/README.md#verify-a-download-before-installing-it), into the same directory, and install both wheels from it with `--no-index`.

Build a downloaded sdist only in an isolated step, with the same recipe, from a checkout of tag `v0.1.3`:

```sh
python -I tools/build_release.py wheel-from-sdist verified/comuvia-0.1.3.tar.gz --out rebuilt
```

This fails unless the wheel built from the sdist equals the approved wheel.

## Tested platforms

Before release, the 0.1.3 files are installed from local files into fresh environments (`tools/package_smoke.py check`) with `comuvia` package tests, `foreglass` 0.1.0's tests against `comuvia` 0.1.3, and tutorials A to H plus J passing under the network-blocking audit hook. See [Python compatibility](../../documentation/architecture/python-compatibility.md).

## Dependencies and rights

As for [0.1.0](../0.1.0/README.md#dependencies-and-rights): no runtime dependencies, `flit_core` 3.12.0 to build, Apache License 2.0, and original synthetic test data.
