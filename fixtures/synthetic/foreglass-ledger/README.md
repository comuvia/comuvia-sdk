# Synthetic ForeGlass-format fixture (`foreglass-ledger`)

Status: synthetic test fixture for OSS-2A. `tools/make_foreglass_fixture.py` generates every file here; `--check` confirms the files are current. A byte-identical copy lives in `packages/foreglass/tests/vectors/foreglass-ledger/` for installed tests.

## Provenance

- **Content is original and fictional.** Every metric, value, statement, source, commitment and locator is made up; locators inside text use the reserved `example.org` domain. No bytes or text of the real public ForeGlass artifacts are copied.
- **Only the format was matched,** against the public artifacts read on 2026-09-24:
  - `https://foreglass.ai/verification-explorer/ledger.json`: build `built: "2026-09-09"`, 699,605 bytes, `sha256:3c97f09f67ca416bce27da2c10d5269ebe2f153e15b035a7f0d92d00f5ea6a45`;
  - the ledger archive `index.json` and the fragility `latest.json`.

  Structure only was inspected: key names and order, value types, `gkey` segmentation and line endings.

## Format matched

| File | Format |
|---|---|
| `source/ledger.json` | `_schema: "foreglass.verification-ledger/v1"`; the top-level keys `_schema, tier, built, registry_schema, seal, counts, lanes, commitments` in that order. 2-space indent, ASCII only with `\uXXXX` escapes (`\u00b7`, `\u2013`, `\u2014`), CRLF line endings and a trailing CRLF. Lane keys follow the published order. `counts.included` equals the number of lanes, and `counts.held` the number of commitments |
| `source/ledger.json.ots` | Synthetic bytes, labelled inside as **not** an OpenTimestamps proof. 0.1 verifies no proofs, so timestamp assurance stays `unavailable` |
| `source/ledger-archive-index.json` | `{schema, note, source_pack_bytes, files: [{file, bytes, sha256, ots}]}`, LF line endings, UTF-8 with a literal non-ASCII character. It lists this ledger by sha256 plus a second same-day entry `2026-09-20b.json`: identify a build by sha256, not by file name |
| `source/fragility-latest.json` | An index reading with `caveat`, indented LF JSON. It is a reading, never a forecast |

Git stores `source/` unconverted (`-text -eol`), so the CRLF bytes and their digest survive checkout.

## Lanes

1. Engine interval lane that is a scenario span (`val == hi`).
2. Interval lane whose 80% coverage appears only in its statement text.
3. Point lane, with `obsKey` and `marker`.
4. Binary lane with unit `probability` and an `(event = …)` `gkey`.
5. Binary `indicator over quarter` lane whose `criteria` is exactly 220 characters, cut mid-word.
6. Model-conditional binary lane (`crisis-hazard-model-conditional`), with `CI95` and `&middot;` in `predFull` and `lo`/`hi` set.
7. Binary lane with `outcome-published-before-seal`.
8. Binary lane with a blank `qid`.
9. Binary lane with `withheld_fields: ["source"]` and a statement of exactly 320 characters.
10. Second binary lane on lane 4's `qid` with a different arm; it shares lane 4's `gkey`.
11. Binary lane carrying unrecognized future outcome keys (`outcome`, `graded_at`) and an unknown field (`horizon_days`).
12. Valid binary lane that publishes no unit (`unit: ""`, empty third `gkey` segment), as two public lanes do. Its question unit is the unknown marker `provider_declares_no_unit`.

`expected.json` holds the hand-specified expectations: the mapping per lane, not-mapped reasons, limitations, drift findings, evaluation counts and reasons (0 eligible), the "never" list and the intake cases.
