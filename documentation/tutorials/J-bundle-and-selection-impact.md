# Tutorial J: packaged profiles, selection-aware impact and whole-bundle verification

Tutorials D, E, G and H introduced example helpers beside their pages (`dependency_profile.py`, `record_authoring.py`, `edition_review.py` and `pinned_evaluation.py`). From `comuvia` 0.1.3, those capabilities ship inside the `comuvia` wheel itself — with zero runtime dependencies and zero network access — alongside selection-aware dependency impact (`org.comuvia.dependencies/v2`), deterministic quote locating (`locate_quote`), audiovisual `media_time` checks, and whole-bundle verification (`verify_bundle` and `comuvia bundle verify`).

Everything runs offline against the installed `comuvia` wheel and the synthetic fixtures in `fixtures/synthetic/`:

```sh
python tutorial_j_bundle_and_selection.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
```

## 1. Packaged parity with Tutorials D, G and H

Importing only from `comuvia` and `comuvia.profiles` (without loading the standalone tutorial helper modules):

- `comuvia.profiles.dependencies.impact(records, src2)` on `fixtures/synthetic/dependency-correction/` reproduces `expected.json`'s `impact_of_source_correction` byte for byte;
- `comuvia.profiles.edition_review.review_status(...)` on `fixtures/synthetic/edition-review/` reproduces `expected.json`'s `review_status` entries byte for byte;
- `comuvia.check_embedded(...)` and `comuvia.check_expectation(...)` on `fixtures/synthetic/pinned-evaluation/` reproduce that fixture's embedded-reference counts and `tail_removed` checks.

## 2. Selection-aware impact (`org.comuvia.dependencies/v2`)

In `org.comuvia.dependencies/v1`, `depends_on[].selection` is uninterpreted text, so revising one quarter in a multi-quarter table flags every dependent of that table without distinguishing which dependents actually read the revised quarter.

`org.comuvia.dependencies/v2` keeps the exact `v1` envelope (`value_origin`, `meaning`, `coverage`, `depends_on`) and allows `selection` on an edge to be a structured selector:

| `selection.kind` | Keys | What is compared between `r1` and `r2` |
|---|---|---|
| `json_pointer` | `kind`, `pointer` | RFC 8785 canonical bytes of the JSON value at `pointer` |
| `text_quote` | `kind`, `exact`, `prefix`, `suffix` | Unique anchored quote occurrence in UTF-8 bytes |
| `byte_range` | `kind`, `start`, `end` | Exact byte slice `[start:end]` |
| `line_range` | `kind`, `start`, `end` | 1-based inclusive UTF-8 line slice |

When a container moves from `r1` to `r2`, any dependent still pinning `r1` remains `affected` (its pin was superseded and requires re-pinning or review), and `impact(records, changed, contents=...)` adds `selection_status`:

- `unchanged`: every matched dependency path to the superseded container traverses structured `v2` selections whose extracted slices in `r1` and `r2` are verified and identical, `meaning` did not change, and the dependent's closure is `complete` with only `match` edges;
- `changed`: `meaning` changed, or a structured selection resolved to different bytes;
- `unscoped`: free-text/marker selection, incomplete coverage, or unverified bytes.

Moving a dependent onto `r2` uses `comuvia.revise(record, ..., repin=[(src_r1, src_r2)])`, and `comuvia.stale_pins(records)` confirms no `superseded`, `mismatch` or `missing` pins remain.

## 3. Deterministic quote locating and audiovisual `media_time` checks

`comuvia.locate_quote(exact, content)` locates `exact` in UTF-8 bytes, refuses missing (`quote_mismatch`) or repeated (`ambiguous_quote`, unless `occurrence=` disambiguates via widened prefix/suffix context) quotes, and returns a schema-valid `selector`. For recordings with timed transcripts or caption cues, `check_selector(assertion, content, snapshot=..., media_duration=..., timed_segments=...)` also checks that `selector.media_time` (`start_seconds`, `end_seconds`) lies within `media_duration` and contains the quoted speech.

## 4. Whole-bundle verification (`verify_bundle` and `comuvia bundle verify`)

`comuvia.verify_bundle(source, contents=..., require_retained_content=True, check_selectors=True, check_profiles=True, check_embedded_pins=True, expectation_manifest=...)` verifies an entire store or JSONL export in one offline call:

1. schema validation, core reference digests and `revision_conflicts`;
2. retained file bytes against `resource_snapshot` and `artifact_descriptor` digests;
3. `check_selector` across every `source_assertion`;
4. `dependencies` and `edition-review/1` profile integrity (`RecordStore` also enforces dependency profiles at write/verify time when `check_profiles=True` or `--profiles` is passed);
5. embedded pins and `{file|path, sha256}` references inside JSON payloads;
6. an independently retained `expectation()` manifest (`missing`, `unexpected`, `changed`, `tail_removed`).

## Limitations

- `selection_status == "unchanged"` proves byte equality of the declared slice, not whether a downstream narrative or review still applies; re-pinning and review policy stay with the application.
- `verify_bundle` checks identities, selectors, profiles and expectations offline; it never fetches URLs, verifies block chains or establishes empirical truth.
