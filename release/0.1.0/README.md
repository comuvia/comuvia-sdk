# Release 0.1.0: `comuvia` and `foreglass`

This directory identifies the exact 0.1.0 files and shows how to rebuild and verify them.

| File | Content |
|---|---|
| [`SHA256SUMS`](SHA256SUMS) | The approved SHA-256 digests of the four distributions |
| [`BUILD.md`](BUILD.md) | The fixed build recipe, the staging directory and the pre-upload rehash |
| [`build-constraints.txt`](build-constraints.txt) | The build backend, `flit_core` 3.12.0, pinned by version and wheel hash |

## What each package is built from

Each package's two files are built only from its own directory and the recipe. Changes elsewhere in the repository, such as documentation, tools or workflows, do not change them.

| Package | Source directory | Git tree id of that directory | Files |
|---|---|---|---|
| `comuvia` | `packages/comuvia` | `e2ca578ee67e943a90b472c5e66566f2e2f5aadc` | `comuvia-0.1.0-py3-none-any.whl`, `comuvia-0.1.0.tar.gz` |
| `foreglass` | `packages/foreglass` | `558ead19f111a7341649dfdb6d68e797062e2e27` | `foreglass-0.1.0-py3-none-any.whl`, `foreglass-0.1.0.tar.gz` |

To check a checkout, compare `git rev-parse HEAD:packages/comuvia` and `git rev-parse HEAD:packages/foreglass` with the table. Then rebuild as in [`BUILD.md`](BUILD.md) and compare the files with `SHA256SUMS`. The public commit and tag of the release are recorded after publication, in the release notes, not in this directory.

- **`comuvia`** has no runtime dependencies. The wheel holds `src/comuvia` (code, the ten JSON Schemas and the `binary-brier-v1` rule) and metadata from `pyproject.toml` and `README.md`. The sdist adds `tests/`, `CHANGELOG.md` and `LICENSE`.
- **`foreglass`** depends on `comuvia>=0.1.0,<0.2` and was tested with the `comuvia` 0.1.0 wheel listed in `SHA256SUMS`. Its sdist includes its tests, a synthetic ForeGlass-format fixture and a throwaway test CA used only by the transport tests.

## Verify a download before installing it

Do not let an installer fetch and build a package before its bytes are checked: `pip download` can run a build backend on an sdist before any checksum is compared. Instead:

```sh
python -I tools/verify_download.py --index pypi --package comuvia --out verified
```

This reads `https://pypi.org/pypi/comuvia/0.1.0/json` and downloads the listed wheel and sdist as raw bytes. It writes them to `verified/` only if each file's SHA-256 equals both the digest the index declares and the digest in `SHA256SUMS`. It installs and builds nothing. Use `--index testpypi` for TestPyPI.

Then install only from the verified file:

```sh
python -m pip install --no-index --no-deps verified/comuvia-0.1.0-py3-none-any.whl
```

For `foreglass`, verify both packages into the same directory and install both wheels from it with `--no-index`. Build a downloaded sdist only in an isolated step, with the same recipe:

```sh
python -I tools/build_release.py wheel-from-sdist verified/comuvia-0.1.0.tar.gz --out rebuilt
```

This fails unless the wheel built from the sdist equals the approved wheel.

## Tested platforms

The runtime code and tests in these files (`src/` and `tests/` of both packages) are unchanged from the release matrix recorded in [Python compatibility](../../documentation/architecture/python-compatibility.md): CPython 3.11, 3.12 and 3.13 on Windows x86-64 and on Linux x86-64 (Debian containers without network). These exact files were then checked on CPython 3.13 on Windows x86-64 and CPython 3.11 on Linux x86-64. Each check ran the package tests, tutorials A, B and C, and a command-line scenario from the installed wheels.

## Dependencies and rights

- **Runtime:** `comuvia` none; `foreglass` only `comuvia`.
- **Build (not shipped):** `flit_core` 3.12.0 (BSD-3-Clause). The recipe also documents `uv` 0.11.21 (MIT OR Apache-2.0) as an optional frontend.
- **Test-only (not shipped, optional):** `jsonschema` and `rfc8785` enable extra agreement checks in the `comuvia` tests.
- **License:** Apache License 2.0; `LICENSE` is the unmodified text (11,358 bytes, SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`).
- **Content:** original work. Every fixture and test vector is synthetic and fictional, and locators use the reserved `example.org` domain. The RFC 8785 test cases reproduce the RFC's published examples as test data, with their source cited. The ForeGlass-format fixture copies only the *format* of a public artifact, no bytes or text of it.
