# Comuvia evidence records and the ForeGlass reader

This repository holds two independently versioned Python distributions, maintained by Comuvia LLC:

| Package | Status | What it is |
|---|---|---|
| [`comuvia`](packages/comuvia/) | **0.1.0** on [PyPI](https://pypi.org/project/comuvia/0.1.0/), alpha · Apache-2.0 | Offline, provider-neutral evidence and prediction records: strict validation, RFC 8785 identity, an append-only single-writer store, and binary evaluation with named exclusions and reproducible results. No runtime dependencies |
| [`foreglass`](packages/foreglass/) | **0.1.0** on [PyPI](https://pypi.org/project/foreglass/0.1.0/), alpha · Apache-2.0 | An optional reader for the existing public ForeGlass artifacts. It reads them explicitly and within bounds, retains exact bytes and normalizes only their declared semantics. For the current public ledger shape that honestly yields 0 eligible forecasts. Depends only on `comuvia>=0.1.0,<0.2` |

`comuvia` keeps free-form statements separate from their interpretations, and scores only explicitly eligible structured forecasts. It does not claim a truth score, independent timestamp assurance, predictive skill or an industry standard.

## Install

```sh
pip install comuvia      # the core library and the comuvia command
pip install foreglass    # the optional ForeGlass reader; also installs comuvia
```

Each package README has a short first example: [`comuvia`](packages/comuvia/README.md), [`foreglass`](packages/foreglass/README.md).

To check the files against the approved digests before installing anything, see [verify a download before installing it](release/0.1.0/README.md#verify-a-download-before-installing-it).

## Documentation

- [Tutorial A: a source-linked statement, honestly excluded](documentation/tutorials/A-source-linked-statement.md)
- [Tutorial B: a declared-probability forecast, its outcome and a correction](documentation/tutorials/B-declared-probability-forecast.md)
- [Tutorial C: reading ForeGlass honestly](documentation/tutorials/C-reading-foreglass-honestly.md)
- [Tutorial D: declared dependencies and the impact of a correction](documentation/tutorials/D-dependencies-and-corrections.md)
- [Tutorial E: authoring and revising records](documentation/tutorials/E-authoring-and-revising-records.md)
- [Tutorial F: point-forecast error evidence](documentation/tutorials/F-point-forecast-error.md)
- [Tutorial G: reviewing an exact edition](documentation/tutorials/G-reviewing-an-exact-edition.md)
- [Tutorial H: checking a consumer's own pinned evaluation](documentation/tutorials/H-pinned-consumer-evaluation.md)
- [Working with 0.1 records: five details that surprise new users](documentation/guides/working-with-0.1-records.md)
- [Record store: layout, lock, crash safety and limits](documentation/architecture/record-store.md)
- [Python compatibility and build tooling](documentation/architecture/python-compatibility.md)
- [Release 0.1.0: digests, build recipe and download verification](release/0.1.0/)

## Releases

| Version | Published | Packages | Source |
|---|---|---|---|
| 0.1.0 | 2026-10-01 | [`comuvia` 0.1.0](https://pypi.org/project/comuvia/0.1.0/) and [`foreglass` 0.1.0](https://pypi.org/project/foreglass/0.1.0/) | Tag `v0.1.0` |

**Why the first commit looks older than the release.** The first public commit carries a fixed date, 2026-01-01T00:00:00Z, so that anyone can re-create it byte for byte from the same inputs. GitHub therefore shows it as months old, and in time zones west of UTC as 31 December 2025. The publication date is the PyPI upload date above. Later commits carry the real time at which they were made.

## Building and checking

The tools in `tools/` use the Python standard library only.

```sh
python -I tools/package_smoke.py build --out <new empty directory outside the checkout>
python -I tools/package_smoke.py check --dist <out>/dist --work <another empty directory> \
    --tutorials documentation/tutorials --fixtures fixtures/synthetic
```

`build` produces byte-reproducible wheels and sdists with the pinned release recipe and inspects their contents. `check` installs them from local files only, with no index, into fresh virtual environments, and runs the package tests, the tutorials and a CLI scenario with an audit hook that refuses network events.

The exact 0.1.0 release files are rebuilt from tag `v0.1.0` with [`release/0.1.0/BUILD.md`](release/0.1.0/BUILD.md). Later commits update the package changelogs, which the source distributions include, so only the tag reproduces all four files. Releases are published only by the manually approved [release workflow](.github/workflows/release.yml), which refuses any file whose digest differs from [`release/0.1.0/SHA256SUMS`](release/0.1.0/SHA256SUMS).

## Contributing and security

Issues and small pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).

## License

This repository is licensed under the [Apache License 2.0](LICENSE). Both distributions declare it in their package metadata (`License-Expression: Apache-2.0`). The fixtures are original synthetic data.
