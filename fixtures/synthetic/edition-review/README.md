# Fixture G: a review bound to an exact edition

Status: valid `comuvia/0.1` `artifact_descriptor` records. [Tutorial G](../../../documentation/tutorials/G-reviewing-an-exact-edition.md) and its script check every value in `expected.json`.

**Every approval in this fixture is fictional.** Each decided review has `fixture: true`, `data_origin: "synthetic"` and `decided_by: "fixture:fictional-reviewer"`. None of them is anyone's approval of anything, and `authentication` is always `"none"`.

## Provenance

Original synthetic content: a short explainer about port fees in the fictional Port Calder setting. All figures, texts and roles are invented. Locators use `example.org` or `urn:example:` names and are never dereferenced. There is no `source/` folder; every artifact's bytes are in `artifacts/`.

## The records (13)

| Record | Revisions | Content |
|---|---|---|
| `res-calder-fee-2026` | r1, r2 | Average fee per call: `"1840"`, corrected to `"1804"` |
| `claims-calder-fees` | r1, r2 | Claim map (one calculation claim, one interpretation), derived from the result r1 or r2 |
| `article-calder-fees` | r1, r2 | Markdown article derived from the claim map; r2 carries the corrected figure and one corrected sentence |
| `captions-calder-fees` | r1 | WebVTT captions |
| `summary-calder-fees` | r1, r2 | The exact `review-summary/1` text shown to the reviewer for edition 1 or edition 2 |
| `contribution-calder-fees-draft` | r1 | A `contribution/1` pattern: inputs claim map r1, output article r1, model identity unknown |
| `review-calder-fees-edition-1` | r1 `pending`, r2 `approved` (fictional) for `local-review-page` | Members: article r1, captions r1, claim map r1; summary r1 |
| `review-calder-fees-edition-2` | r1 `pending` | Members: article r2, captions r1, claim map r2; summary r2 |

Only the result, claim map and article carry dependency-profile derivation edges. The summaries, contribution and reviews keep their references in their own content.

## Files

| Path | Role |
|---|---|
| `artifacts/<id>.r<revision>.<ext>` | Each descriptor's exact bytes. Git stores them unconverted (`-text -eol`) |
| `records/<id>.r<revision>.json` | The 13 committed records |
| `expected.json` | Every content and record identity, and the `review_status` reports for the pending, approved and case 1 checks |
