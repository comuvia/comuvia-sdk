# Tutorial G: reviewing an exact edition

A newsroom asks a reviewer to approve an explainer, with its captions and claim map, for one destination. Later the underlying figure is corrected and a new edition is drafted. Is the earlier approval still valid for what is about to be published? This tutorial binds a review to the **exact bytes** of an edition and shows when that review stops being current.

Everything runs offline against the installed `comuvia` wheel, using `fixtures/synthetic/edition-review/`: a fictional explainer about port fees. **Every approval in the fixture is fictional and labelled as such; none is anyone's real approval.** The logic is an example helper, [`edition_review.py`](edition_review.py), built on the public `comuvia` 0.1.0 API and the helpers of tutorials D and E. The runnable script [`tutorial_g_edition_review.py`](tutorial_g_edition_review.py) checks every value this page states:

```sh
python tutorial_g_edition_review.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
```

## What it is, and what it is not

- **An exact binding.** A review pins each member of an edition and the summary the reviewer saw, by record digest, and the bytes are checked against those records.
- **Not authentication.** `decided_by` is a string the application supplies, and `authentication` is always `"none"`. Nothing here proves who decided.
- **Not a publication gate.** The helper answers a question; it stops nothing. Your application must call it at its own publication step and act on the answer.
- **Not a materiality judgment.** Any change to a pinned member makes the review stale, even one character. If a change does not matter, your application records that by issuing a **new review of the new edition**; it never reuses the old one.

## The artifacts

Each is an `artifact_descriptor` built with tutorial E's helpers. JSON artifacts are exactly `comuvia.canonicalize(object)`.

| `content_schema` | Content |
|---|---|
| `review-summary/1` | The exact text shown to the reviewer: the decision asked for, the edition and its limits |
| `edition-review/1` | `edition`; `members` (one or more `{"role", "pin"}`, unique roles, sorted by role); `summary` (a pin); `status` (`pending`, `approved`, `changes_requested` or `internal_only`); `destinations` (sorted, unique); `decided_by`; `decided_at`; `authentication` (`"none"`); `fixture`; `note` |
| `contribution/1` | Who contributed what, as the application supplies it: contributor, role, model (or a marker), inputs, outputs, and whether it was adopted, modified or rejected. A pattern only |

**Decision rules.**
- A `pending` review has markers for `decided_by` and `decided_at`: no approver and no time exist until a decision does.
- Any other status needs a `decided_by` text and a `decided_at` timestamp.
- `fixture` is true exactly when the record's `data_origin` is `synthetic`, and a decided fixture's `decided_by` starts with `fixture:`.
- **A decision is a new revision** of the review record: here, `pending` r1 and then `approved` r2. The pending revision is kept.

Reviews, summaries and contributions carry **no dependency-profile derivation edges**. They refer to an edition; they are not derived from it. So tutorial D's `impact` never marks them `affected`.

## `review_status`

```python
review_status(review, records, contents, *, current_members=None, changed=None, destination=None)
```

| State | Meaning | Reasons, in order |
|---|---|---|
| `invalid` | The review artifact itself fails | `content_digest_mismatch`, `malformed_review`, `pending_has_decision`, `decision_incomplete`, `unsupported_authentication`, `fixture_flag_conflict`, `fixture_not_labelled` |
| `broken` | A pin no longer holds | `member_missing`, `member_mismatch`, `member_bytes_changed`, `summary_missing`, `summary_mismatch`, `summary_bytes_changed` |
| `stale` | The review is intact, but no longer current | `member_superseded` (a later revision of a member exists); `summary_superseded`; `edition_members_changed` (`current_members` differs); `member_affected` (`changed` reaches a member through `impact`) |
| `current` | None of the above | none |

Each member is reported as `match`, `superseded`, `affected`, `mismatch`, `missing` or `bytes_changed`.

A review checked against an older edition is still `current` for that edition. Staleness is relative to the records you pass in and to `current_members`.

**`covers`** is true only when the review is `current`, its status is `approved`, a `destination` is given, and that destination is among its `destinations`. Otherwise `covers_reasons` says why: `not_current`, `decision_pending` or `not_approved`, `no_destination`, `destination_not_approved`.

## Walking through the checks

1. **The bundle is clean.** Every record validates, every content matches, and tutorial D's profile check reports nothing.
2. **Pending and approved.**
   - Edition 1's pending review is `current` but covers nothing: `decision_pending`.
   - Its fictional approval covers `local-review-page`. For `public-site` the answer is `destination_not_approved`; with no destination given, it is `no_destination`.
3. **Case 1: a changed edition makes the review stale.** With edition 2's article and summary in the bundle, and edition 2 as the current members, edition 1's approval is `stale`: `member_superseded`, `summary_superseded` and `edition_members_changed`. It covers nothing (`not_current`). Edition 2's own review is `current` and still `pending`.
4. **Case 2: a correction preserves prior evidence.**
   - The corrected fee makes the claim map r1 and article r1 `affected`, each with a corrected latest revision. The contribution and the reviews are not flagged.
   - Passing the correction as `changed` adds `member_affected` to edition 1's review.
   - The eight earlier records keep their digests when the five later ones are appended to a store, and edition 1's review stays intact.
5. **No materiality judgment.** A new article edition that differs by one character makes edition 1's review `stale` with `member_superseded`.
6. **Broken pins.** Altered article bytes give `member_bytes_changed`, a removed caption record gives `member_missing`, and altered summary bytes give `summary_bytes_changed`.
7. **Invalid reviews.** Each of these gives exactly its reason:
   - a pending review with a decider gives `pending_has_decision`;
   - an approval without a time gives `decision_incomplete`;
   - `authentication: "signed"` gives `unsupported_authentication`;
   - `fixture: false` on a synthetic record gives `fixture_flag_conflict`;
   - a fixture approval by `"Owner"` gives `fixture_not_labelled`;
   - unsorted members, duplicate roles or an empty member list each give `malformed_review`;
   - altered review bytes give `content_digest_mismatch`.
8. **Fictional labelling.** Every decided review in the fixture is a labelled fixture.
9. **Contributions.** The contribution's pin to article r1 is `superseded` once article r2 exists, a historical statement that stays true. `impact` does not flag it. Its references live in its own content, which tutorial E's `stale_pins` reads when given that content with the contribution's identity.

## Limits

- No authentication, signature or identity proof; `decided_by` is only a label.
- No publication control; an application must call the helper and act on it.
- No materiality judgment; any change to a member makes a review stale.
- Schema validation never makes a claim true.
- Example-level only: there is no review type in the `comuvia` package. The records are ordinary `comuvia/0.1` records.
