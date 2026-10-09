# Tutorial E: authoring and revising records

Writing `comuvia/0.1` records by hand is mostly mechanics: the same eight envelope fields on every record, the two shapes of `content`, a successor that points to the right predecessor, and pins that must move when their target is corrected. This tutorial removes those mechanics with an **example helper**, [`record_authoring.py`](record_authoring.py), built only on the public `comuvia` 0.1.0 API. It is not part of the package. It does not decide anything you have to decide: which claim, which evidence, which resolution rule, or whether a value is unknown.

Everything runs offline against the installed `comuvia` wheel, reusing tutorial D's fixture in `fixtures/synthetic/dependency-correction/`. The runnable script [`tutorial_e_authoring.py`](tutorial_e_authoring.py) checks every value this page states:

```sh
python tutorial_e_authoring.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
```

## What `validate` already tells you

`comuvia.validate` already reports each of these mistakes precisely, with a JSON Pointer and a code. The helper keeps those reports unchanged; `explain` only adds a hint.

| Mistake | `validate` reports | Hint added by `explain` |
|---|---|---|
| A schema string such as `comuvia/0.1.0` | `/schema` `unsupported_schema_version` | Let `new_record` set it |
| Missing fields | one `missing_required_field` per field, at its pointer | State an unknown value with a marker |
| A malformed content digest | `/content/digest` `malformed_digest` | Use the content builders |
| `retained: true` with a marker digest | `/content/digest` `malformed_digest` | Use `unretained_content` with markers for bytes you did not keep |
| Custom data at the top level | `/<key>` `unrecognized_member` | Put it under `extensions`, with a key such as `org.example.topic/v1` |
| A value outside an enumeration, such as `access: "internal"` | `/access` `invalid_value` | The allowed values, read from the packaged schema: `private, public, restricted` |
| A wrong predecessor | `/predecessor` `invalid_predecessor` | Use `revise` |
| A timestamp without an offset | `/recorded_at` `invalid_timestamp` | RFC 3339 with an explicit offset, such as `2026-10-04T14:00:00Z` |

`explain(issues)` returns `AuthoringIssue(pointer, code, message, hint)` values. **Codes are stable; hints are only explanation.** The allowed values come from the schemas shipped in the package, following their references into `common.json`, so `data_origin` lists `observed, synthetic`.

## The helper

Every refusal is an `AuthoringError`, a `ValueError` whose `issues` are sorted `AuthoringIssue` values and whose message starts with `authoring_refused:`. Core issues pass through unchanged, with a hint.

**`new_record(record_type, record_id, *, data_origin, recorded_by, recorded_at, fields)`** returns revision 1:
- `schema` is set to `comuvia/0.1`, with `revision: 1` and `predecessor: null`;
- the three provenance values are used exactly as given;
- the rest is a copy of `fields`.

It adds no other field, no marker, no time and no default. It refuses:
- `missing_provenance`, when `data_origin`, `recorded_by` or `recorded_at` is absent, `None` or empty;
- `protected_field`, when `fields` contains an envelope key;
- then any core `validate` issue.

**`revise(previous, *, recorded_by, recorded_at, replace=None, repin=(), data_origin=None)`** returns the next revision; `previous` is never changed. In order:
1. It copies `previous`.
2. It replaces each key in `replace` **whole, at the top level**. Nothing is merged: to change one nested value, copy the object, edit the copy and pass the whole object.
3. It applies `repin`.
4. It sets `revision` to `previous` + 1, `predecessor` to `reference_to(previous)`, and the given `recorded_by` and `recorded_at`. It keeps `data_origin` unless `data_origin=` is given.

It refuses:
- an invalid `previous`, with its core issues;
- `protected_field`, for an envelope key in `replace`;
- `missing_provenance`;
- `recorded_before_predecessor`, when `recorded_at` is an earlier instant than the previous one, compared exactly with offsets applied: `2027-01-20T04:59:59-05:00` is earlier than `2027-01-20T10:00:00Z`, while `05:00:00-05:00` is the same instant;
- `not_a_successor` and `pin_not_found`, for `repin`;
- `no_change`, when nothing else is refused and the successor would equal `previous` apart from `revision`, `predecessor`, `recorded_by` and `recorded_at`;
- then any core `validate` issue.

**`repin`** is a list of `(old, new)` pairs, where `new` is a later revision of the same record as `old`; otherwise `not_a_successor`. Every value anywhere in the body, core fields and extensions alike, that equals `reference_to(old)` exactly becomes `reference_to(new)`. `predecessor` is not touched. If no such value exists: `pin_not_found`. This is how a dependent moves onto a corrected target: a new revision of the dependent, with the old one kept as it was.

**Content builders:**
- `snapshot_content(data, media_type)`, for a `resource_snapshot` whose bytes you keep: `retained: true` plus the length and digest of `data`;
- `unretained_content(media_type, *, byte_length, digest)`, for bytes you did not keep: `retained: false` and exactly the values you state, real or markers. Nothing is defaulted;
- `descriptor_content(data, media_type)`, for an `artifact_descriptor`: no `retained` key.

Passing anything but bytes gives `invalid_content_input`.

**`stale_pins(records)`** is read-only. It reports every pin outside `predecessor`, in core fields and every extension, whose state is:
- `superseded`: it matches, but the bundle holds a later revision of the target;
- `mismatch`: the target's digest differs;
- `missing`: the target is not in the bundle.

Pins to the latest revision are not reported. It complements tutorial D's profile check rather than replacing it.

## Walking through the checks

1. **Creating records.** A snapshot and a descriptor, built from bytes in memory, validate, and `verify` confirms that their content matches. The two content shapes differ only by `retained`.
2. **The round trip.** All 13 records of tutorial D's fixture are rebuilt from their parts:
   - revision 1 with `new_record`, its content from the retained bytes, and its pins from the rebuilt targets;
   - revision 2 with `revise`. The annual result and the stress simulation get their new pins **through `repin`**, not by copying them.

   Every rebuilt digest equals the committed one, so the helper adds and changes nothing.
3. **Provenance.**
   - A missing, `None` or empty provenance value gives `missing_provenance` at its pointer.
   - An invalid one reaches the core codes, each with its hint: `invalid_value` for `data_origin`, with its allowed values; `invalid_identifier` for `recorded_by`; `invalid_timestamp` for `recorded_at`.
   - A new record holds exactly the envelope and the caller's fields.
4. **Protected fields.** Each envelope key in `fields` or `replace` gives `protected_field`. `data_origin` changes only through `data_origin=`.
5. **The reported failures.** Eight hand-written mistakes are explained: the table above, with three missing fields and both digest cases.
6. **Revisions.**
   - The earlier-time and no-change cases are refused, and so is an invalid previous record.
   - A successor has the next revision and pins its predecessor exactly; the previous record is untouched.
   - Replacing `content` with the descriptor shape on a snapshot is refused with `/content/retained` `missing_required_field`, which shows that `replace` does not merge.
7. **Moving pins.**
   - Pairing a record with another id, or with an equal or earlier revision, gives `not_a_successor`; a pair the record does not pin gives `pin_not_found`.
   - Moving the chart onto the corrected source changes the pin inside its dependency extension and leaves the old chart unchanged.
   - Tutorial D's profile check then sees no broken pin.
8. **Stale pins.** In the fixture, exactly three pins are `superseded`: chart r1 and result r1 to source r1, and simulation r1 to result r1. A tampered target gives `mismatch`; a removed one gives `missing`.
9. **Unknown stays unknown.** Revising one unrelated field leaves every marker in the record identical.
10. **The store.** The rebuilt chain appends to a `RecordStore`. Earlier digests are unchanged, `verify` is ok, and there are no revision conflicts.

## Limits

- The helper removes mechanics, not judgment. It cannot choose the right claim, evidence or resolution rule, and it never infers a fact. It never fills, changes or removes an `unknown` or `withheld` marker, and never derives a publication time from a recording time.
- It does not re-implement validation: every field check is `comuvia.validate`.
- Some friction is in the 0.1 schema itself and stays: there is no "not applicable" marker, "derived" has no core field, and an extension key's `/` must be written as `~1` in a JSON Pointer.
- It is an example, not package behavior. Records it builds are ordinary `comuvia/0.1` records that every 0.1 tool reads unchanged; the round trip shows that byte for byte.
