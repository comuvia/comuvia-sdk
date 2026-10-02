# Contributing

Issues are welcome: bug reports, documentation problems and questions, at [github.com/comuvia/comuvia-sdk/issues](https://github.com/comuvia/comuvia-sdk/issues). Report security problems privately, as described in [SECURITY.md](SECURITY.md).

## The 0.1 contract is frozen

The following do not change within 0.1.x. A change to any of them is a new schema, rule or format version, not an edit:

- the `comuvia/0.1` record shapes, their JSON Schemas and the record digest;
- the `binary-brier-v1` rule, version `1`;
- the names in `comuvia.__all__` and `foreglass.__all__`, and the reason codes;
- the command-line exit codes;
- the record store format `comuvia-store/1`.

Bug fixes, documentation, tests and new synthetic fixtures are the right size for a pull request. Keep a pull request small and describe what it changes and how you checked it.

## Tests run offline

No test needs network access or credentials. Build both packages with the release recipe and check the installed wheels in fresh virtual environments, outside the checkout. The build step downloads the pinned build backend from PyPI, unless `--find-links` points to a local copy of its wheel.

```sh
python -I tools/package_smoke.py build --out <new empty directory>
python -I tools/package_smoke.py check --dist <that directory>/dist --work <another empty directory> \
    --tutorials documentation/tutorials --fixtures fixtures/synthetic
```

`check` runs both packages' tests, tutorials A, B and C, and a command-line scenario, with an audit hook that refuses network events.

The repository tools have their own tests, which need only `git`:

```sh
python -I -m unittest discover -s tools/tests
```

## Content

- Fixtures and test data are synthetic. Do not add real personal data, third-party text or data, or credentials.
- By submitting a contribution you agree that it is licensed under the [Apache License 2.0](LICENSE), as its section 5 describes.
