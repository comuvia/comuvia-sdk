# Building the 0.1.1 distributions

comuvia 0.1.1 is byte-reproducible from a checkout of tag `v0.1.1` of this repository. Build from the tag: later commits can change files that the source distribution includes, such as the package changelog. `SHA256SUMS` in this directory, added only when the owner approves the release, lists the approved digests of **the comuvia 0.1.1 pair only**:
- `comuvia-0.1.1-py3-none-any.whl`;
- `comuvia-0.1.1.tar.gz`.

`foreglass` 0.1.0 is already published and is never uploaded again. The build still produces its two files, because the recipe builds both packages, and `check` reports them as not for upload.

## The recipe

The same recipe as 0.1.0 ([`release/0.1.0/BUILD.md`](../0.1.0/BUILD.md)):

| Input | Value |
|---|---|
| Source | `packages/comuvia` and `packages/foreglass` in the checkout; each version is its source `__version__` |
| Build backend | `flit_core` 3.12.0, pinned by version and wheel hash in [`build-constraints.txt`](build-constraints.txt) (byte-identical to 0.1.0's) |
| `SOURCE_DATE_EPOCH` | `1767225600` (2026-01-01T00:00:00Z), always set explicitly |
| Order | the sdist first, then the wheel built from that sdist |
| Wheel entries | record Unix as the creating system on every platform |
| Line endings | as committed: `.gitattributes` pins every text file in the packages to LF |

`SOURCE_DATE_EPOCH` sets the timestamp of every member in the archives. It is not a release date.

## Build and check

```sh
python -I tools/build_release.py build --out dist-release/0.1.1
python -I tools/build_release.py check dist-release/0.1.1
```

`tools/build_release.py` takes comuvia's version to choose this directory. `build` writes four distributions, `SHA256SUMS` and `manifest.json`:
- `comuvia-0.1.1-py3-none-any.whl` and `comuvia-0.1.1.tar.gz`;
- `foreglass-0.1.0-py3-none-any.whl` and `foreglass-0.1.0.tar.gz`.

`check` compares exactly the files listed in `release/0.1.1/SHA256SUMS`, and requires each one: it must match the staged `SHA256SUMS` and `manifest.json`. Any other built file is reported as not for upload. `check` refuses if `release/0.1.1/SHA256SUMS` is absent.

The release workflow ([`.github/workflows/release.yml`](../../.github/workflows/release.yml)) does not upload staged files. It rebuilds on its own runner with the same recipe, and uploads a package only if that package's pair is listed in the approved `SHA256SUMS`. A `foreglass` dispatch for 0.1.1 therefore fails before publishing. Release 0.1.0 is unchanged and is still built from tag `v0.1.0`.
