# Fixture H: a consumer's pinned evaluation

Status: valid `comuvia/0.1` records. [Tutorial H](../../../documentation/tutorials/H-pinned-consumer-evaluation.md) and its script check every value in `expected.json`.

## Provenance

Original synthetic content. The economy "Calder", its statistics release and the two providers, Kestrel Nowcast and Wren Staff Tracker, are fictional. So are every forecast, outcome and script. Locators use `example.org` or `urn:example:` names and are never dereferenced. Every record has `data_origin: "synthetic"`. Issue and release dates are **dates only**: no source or artifact file contains a time of day.

## The records (11)

| Record | Kind | Content |
|---|---|---|
| `fc-kestrel-calder-growth`, `fc-wren-calder-growth` | snapshots, `source/` | Date-only forecast archives for 2027Q1 |
| `release-calder-2027q1-advance` r1, r2 | snapshots, `source/` | The advance release (2.6 percent, released 2027-04-28); r2 adds an official erratum that changes no estimate |
| `vintages-calder-2027q1` | snapshot, `source/` | A later vintage table (advance, second, third estimates) that the evaluation does not use |
| `protocol-calder-nowcast` | descriptor | The pre-registered protocol: boundary 2027-03-29, "issued strictly before the boundary date", information sets unknown |
| `code-calder-scoring` | descriptor | A fictional scoring script |
| `manifest-calder-outcome` | descriptor | The outcome manifest; it embeds `{file, raw_sha256}` for release page r1 |
| `result-calder-nowcast` r1, r2 | descriptors | The consumer's result. It embeds `{file or path, raw_sha256 or content_sha256}` references to its inputs and one `comuvia` pin to the protocol record. r1 mis-transcribes Wren's value (2.8); r2 corrects it to 2.9 |
| `report-calder-nowcast` | descriptor | A report derived from result r1 |

## Files

| Path | Role |
|---|---|
| `source/` | The five snapshots' exact bytes, unconverted (`-text -eol`) |
| `artifacts/` | The six descriptors' exact bytes (two result revisions), unconverted |
| `records/<id>.r<revision>.json` | The 11 committed records |
| `expected.json` | Content and record identities, the expectation (`pinned_evaluation.expectation`), and the embedded-reference counts |
