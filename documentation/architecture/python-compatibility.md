# Python compatibility and build tooling

Status: MEASURED. The 0.1.0 claim rests on the release matrix below; [release 0.1.0](../../release/0.1.0/README.md#tested-platforms) records the recheck of the final files.
Last updated: 2026-09-25, US Eastern time

The decision was frozen during the project's design review (OSS-0). This page records what has been measured against it.

## Decision

| Item | Value |
|---|---|
| `requires-python` | `>=3.11` for both `comuvia` and `foreglass`, with no upper cap |
| Why 3.11 | The first intended consumer applications run CPython 3.11 and 3.12 images. Python 3.11 also parses `Z` and most ISO 8601 forms in `datetime.fromisoformat` |
| Claimed for `comuvia` 0.1.0 | CPython 3.11, 3.12 and 3.13 on Windows x86-64 and Linux x86-64, all measured on the installed wheel (see [Measured interpreters](#measured-interpreters-known)) |
| Version classifiers | `comuvia` 0.1.0 and `foreglass` 0.1.0 each name `3.11`, `3.12` and `3.13`, plus `Operating System :: Microsoft :: Windows` and `POSIX :: Linux`: exactly the measured rows |
| Out of scope | 3.14+, PyPy, free-threaded builds, macOS, ARM, platform-specific extras |

## Measured interpreters (known)

All six rows passed the same installed check on 2026-09-24 against the same four artifacts. Each check covers two environments. In the core-only environment, `import foreglass` raises `ModuleNotFoundError`. In the core+client environment, `foreglass` resolves `comuvia` from local artifacts. The [build and check commands](../../README.md#building-and-checking) and `tools/package_smoke.py` state what each check asserts.

| CPython | Platform | Interpreter source | Network during install and import |
|---|---|---|---|
| 3.13.14 | Windows 11 x86-64 | Host interpreter | Not blocked at the OS level. Installs use `--no-index`, and the audit hook proves the imports make no request |
| 3.11.15 | Windows 11 x86-64 | uv-managed (`uv python install 3.11`) | Same as above |
| 3.12.13 | Windows 11 x86-64 | uv-managed (`uv python install 3.12`) | Same as above |
| 3.11.16 | Linux x86-64 (Debian) | `python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9` | Container run with `--network none` |
| 3.12.14 | Linux x86-64 (Debian) | `python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9` | Container run with `--network none` |
| 3.13.15 | Linux x86-64 (Debian) | `python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0` | Container run with `--network none` |

**Limit:** the rows were first measured on the OSS-0 skeletons. OSS-1A and OSS-1B each re-ran all six rows against the implemented package. The OSS-1B run covered records, validation, canonicalization, the record store, evaluation and the installed `comuvia` console script, and ran the test-only conformance checks on 3.13.14 and 3.11.15 (Windows). The store's POSIX lock path (`fcntl.flock`) is exercised only in the Linux rows, and the Windows path (`msvcrt.locking`) only in the Windows rows. OSS-1C ran all six rows on the `comuvia` 0.1.0 candidate wheel, including both tutorials and the CLI scenario. OSS-2A ran all six rows again with the `foreglass` reader, intake and normalization tests from the installed wheels, offline, using an injected transport. OSS-1C repeats the matrix for the candidate. The Linux rows are containers on a Windows host, not a separate Linux machine.

## Unverified targets

- Linux x86-64 outside Debian-based containers, for example the consumers' own base images. The consumer image families are CPython 3.11/3.12, which is the same range measured here.
- Any interpreter or platform in the out-of-scope row above.

## Build tooling

| Role | Selection | Measured version |
|---|---|---|
| Build frontend | `tools/build_release.py` (standard library and pip) builds the sdist, then the wheel from that sdist, and records Unix as each wheel entry's creating system | Identical bytes on Windows and in a Linux container; `uv build` 0.11.21 gives the same bytes on Linux |
| Build backend | `flit_core>=3.12,<4` (PEP 517); release builds pin exactly 3.12.0 by wheel hash in `release/0.1.0/build-constraints.txt` | flit_core 3.12.0 (`Generator: flit 3.12.0`) |
| Install check | Standard-library `venv` plus the bundled `pip` with `--no-index --find-links`, `--only-binary :all:` and `PIP_CONFIG_FILE` set to the null device | pip bundled with each interpreter |
| Reproducibility | `SOURCE_DATE_EPOCH` is always `1767225600` (2026-01-01T00:00:00Z); see [`release/0.1.0/BUILD.md`](../../release/0.1.0/BUILD.md) | Byte-identical on Windows and in a Linux container |

Hatchling was considered first; version 1.32.4 was tried and not selected. The sdist contained the repository-root `.gitignore` despite `only-include`. Its source (`SdistBuilder.get_default_build_data`) force-includes the nearest `.gitignore` up to the Git root without checking `ignore-vcs`. The only in-backend workarounds add another unlisted file. `flit_core` takes an explicit sdist include list, does not read version-control state and has no dependencies of its own.
