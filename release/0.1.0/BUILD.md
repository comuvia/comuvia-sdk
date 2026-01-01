# Building the 0.1.0 distributions

The four 0.1.0 files are byte-reproducible from a checkout of this repository. [`SHA256SUMS`](SHA256SUMS) lists their approved SHA-256 digests.

## The recipe

| Input | Value |
|---|---|
| Source | `packages/comuvia` and `packages/foreglass` in the checkout |
| Build backend | `flit_core` 3.12.0, pinned by version and wheel hash in [`build-constraints.txt`](build-constraints.txt) |
| `SOURCE_DATE_EPOCH` | `1767225600` (2026-01-01T00:00:00Z), always set explicitly |
| Order | the sdist first, then the wheel built from that sdist |
| Wheel entries | record Unix as the creating system on every platform |
| Line endings | as committed: `.gitattributes` pins every text file in the packages to LF |

`SOURCE_DATE_EPOCH` sets the timestamp of every member in the archives. It is not a release date. An inherited or different value, or a different backend version, still gives valid packages, but different bytes.

Two platform effects are neutralized so that Windows and Linux give identical files:

- Python's `zipfile` records the creating system of each wheel entry as MS-DOS on Windows and Unix elsewhere, and `flit_core` 3.12.0 does not normalize it. `tools/build_release.py` records Unix everywhere.
- File contents and modes are read from the working tree. Build from a Git checkout: `.gitattributes` gives LF line endings on every platform, and Git checks files out without the executable bit. A copy that bypasses Git can differ. For example, a Windows folder mounted into a Linux container shows every file as executable.

## Build with the standard library (the release workflow's path)

```sh
python -I tools/build_release.py build --out dist-release/0.1.0
python -I tools/build_release.py check dist-release/0.1.0
```

`build` creates a fresh virtual environment and installs the pinned backend with `pip --require-hashes`. It then calls the backend's build hooks with the fixed `SOURCE_DATE_EPOCH`, whatever the environment says. `--find-links <directory>` installs the backend from a local copy of its wheel instead of the index. The output directory receives the four distributions, `SHA256SUMS` and `manifest.json`, and nothing else.

`check` fails unless the directory holds exactly those six files and each distribution matches the staged `SHA256SUMS`, `manifest.json` and the approved `release/0.1.0/SHA256SUMS`.

## Build with uv (Linux)

On Linux, uv 0.11.21 gives the same four files. `--no-config` ignores user and project uv settings; `--require-hashes` enforces the backend's wheel hash. On Windows, uv gives the same sdists, but its wheels differ in the creating-system field described above, so use `tools/build_release.py` there.

```sh
export SOURCE_DATE_EPOCH=1767225600
for package in comuvia foreglass; do
  uv build --no-config --build-constraint release/0.1.0/build-constraints.txt --require-hashes \
      "packages/$package" --out-dir dist-uv
done
(cd dist-uv && sha256sum --check ../release/0.1.0/SHA256SUMS)
```

## Staging directory

Release files are staged in `dist-release/0.1.0/`, which Git ignores. It holds exactly:

- `comuvia-0.1.0-py3-none-any.whl`, `comuvia-0.1.0.tar.gz`, `foreglass-0.1.0-py3-none-any.whl` and `foreglass-0.1.0.tar.gz`;
- `SHA256SUMS` for those four files;
- `manifest.json`: names, sizes, digests, the recipe, the source commit and package tree ids, and the interpreter used.

Immediately before any upload, rehash the staged files:

```sh
python -I tools/build_release.py check dist-release/0.1.0
```

The release workflow ([`.github/workflows/release.yml`](../../.github/workflows/release.yml)) does not upload staged files. It rebuilds on its own runner with the same recipe, and uploads only if its files match `SHA256SUMS`.
