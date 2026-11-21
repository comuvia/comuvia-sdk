# Building the 0.1.3 distributions

`comuvia` 0.1.3 is byte-reproducible from a checkout of tag `v0.1.3` of this repository. Build from the tag: later commits can change files that the source distribution includes, such as the package changelog. `SHA256SUMS` in this directory, added only when the owner approves the release, lists the approved digests of **the comuvia 0.1.3 pair only**:
- `comuvia-0.1.3-py3-none-any.whl`;
- `comuvia-0.1.3.tar.gz`.

`foreglass` 0.1.0 is already published and is not uploaded again by this line. The build still produces its two files, because the recipe builds both packages, and `check` reports them as not for upload.

## The recipe

The same recipe as 0.1.0 ([`release/0.1.0/BUILD.md`](../0.1.0/BUILD.md)), 0.1.1 ([`release/0.1.1/BUILD.md`](../0.1.1/BUILD.md)) and 0.1.2 ([`release/0.1.2/BUILD.md`](../0.1.2/BUILD.md)):

| Input | Value |
|---|---|
| Source | `packages/comuvia` and `packages/foreglass` in the checkout; each version is its source `__version__` |
| Build backend | `flit_core` 3.12.0, pinned by version and wheel hash in [`build-constraints.txt`](build-constraints.txt) (byte-identical to 0.1.0's, 0.1.1's and 0.1.2's) |
| `SOURCE_DATE_EPOCH` | `1767225600` (2026-01-01T00:00:00Z), always set explicitly |
| Order | the sdist first, then the wheel built from that sdist |
| Wheel entries | record Unix as the creating system on every platform |
| Line endings | as committed: `.gitattributes` pins every text file in the packages to LF |

`SOURCE_DATE_EPOCH` sets the timestamp of every member in the archives. It is not a release date.

## Build and check

```sh
python -I tools/build_release.py build --out dist-release/0.1.3
python -I tools/build_release.py check dist-release/0.1.3
```

`tools/build_release.py` takes comuvia's version to choose this directory. `build` writes four distributions, `SHA256SUMS` and `manifest.json`:
- `comuvia-0.1.3-py3-none-any.whl` and `comuvia-0.1.3.tar.gz`;
- the accompanying `foreglass` pair (reported by `check` as not for upload).

`check` compares exactly the files listed in `release/0.1.3/SHA256SUMS`, and requires each one: it must match the staged `SHA256SUMS` and `manifest.json`. `check` refuses if `release/0.1.3/SHA256SUMS` is absent.
