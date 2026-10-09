# Fixture F: point-forecast error evidence

Status: valid `comuvia/0.1` `artifact_descriptor` records with the `org.comuvia.dependencies/v1` profile. [Tutorial F](../../../documentation/tutorials/F-point-forecast-error.md) and its script check every value in `expected.json`. The arithmetic is example-level: it is not a `comuvia` scoring rule, and it says nothing about any provider's skill.

## Provenance

Original synthetic content. The economy "Calder", its statistics office and the three providers (Alder, Birch and Cedar Forecasts) are fictional. Locators use `example.org` or `urn:example:` names and are never dereferenced. Every record has `data_origin: "synthetic"`. There is no `source/` folder: every artifact is a descriptor, with its bytes in `artifacts/`.

## The records (13)

| Record | Artifact (`content_schema`) | Content |
|---|---|---|
| `target-calder-growth-2027q1` r1 | `point-target/1` | Real output growth, seasonally adjusted annual rate, `percent`, 2027-Q1, settled by `outcome-calder-growth-2027q1`, edition `first_release` |
| `rule-point-error` r1 | `point-error-rule/1` | The frozen example rule; its bytes' digest is `RULE_DIGEST` |
| `fc-alder-…`, `fc-birch-…`, `fc-cedar-…` r1 | `point-forecast/1` | Point forecasts `"3.0"`, `"2.0"` and `"2.5"`, issued 2027-03-20 to 2027-03-25, each with an earlier information cutoff; upstream lineage `undisclosed` |
| `outcome-calder-growth-2027q1` r1, r2 | `point-outcome/1` | r1: `"2.6"`, mis-keyed. r2: the correction to `"2.5"`. Same edition, same publication time (2027-04-28T12:30:00Z), recorded later |
| `err-alder-…`, `err-birch-…`, `err-cedar-…` r1, r2 | `point-error-result/1` | r1 against outcome r1; r2 built with `revise(…, repin=[(outcome r1, outcome r2)])` |

The results, in percentage points (squared errors in percentage points squared):

| Forecast | Against outcome r2 (2.5) | Against outcome r1 (2.6) |
|---|---|---|
| Alder, 3.0 | `0.5`, `0.5`, `0.25` | `0.4`, `0.4`, `0.16` |
| Birch, 2.0 | `-0.5`, `0.5`, `0.25` | `-0.6`, `0.6`, `0.36` |
| Cedar, 2.5 | `0`, `0`, `0` | `-0.1`, `0.1`, `0.01` |

## Files

| Path | Role |
|---|---|
| `artifacts/<id>.r<revision>.json` | Each descriptor's exact bytes: `comuvia.canonicalize(object)`, no trailing newline. Git stores them unconverted (`-text -eol`) |
| `records/<id>.r<revision>.json` | The 13 committed records |
| `expected.json` | The rule's canonical bytes and digest, every content and record identity, and every result object |
