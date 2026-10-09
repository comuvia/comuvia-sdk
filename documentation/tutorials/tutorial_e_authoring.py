"""Tutorial E: authoring and revising records.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_e_authoring.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

It uses the example helper ``record_authoring.py`` beside this file (not part of the comuvia
package) and the dependency-correction fixture of tutorial D. Every value the tutorial states
is checked; the script exits non-zero if one differs.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the helpers; package_smoke runs this with -I

import comuvia  # noqa: E402
import dependency_profile as dp  # noqa: E402
import record_authoring as ra  # noqa: E402

AT = "2027-03-01T09:00:00Z"
BY = "recorder:example-authoring"


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL E CHECK FAILED: {message}")


def refused(call):
    """The AuthoringError a call raises (the check fails if it succeeds)."""
    try:
        call()
    except ra.AuthoringError as error:
        return error
    raise SystemExit(f"TUTORIAL E CHECK FAILED: expected a refusal from {call}")


def key(body):
    return (body["record_type"], body["id"], body["revision"])


def markers(value, pointer=""):
    if comuvia.is_marker(value):
        yield pointer, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from markers(v, f"{pointer}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from markers(v, f"{pointer}/{i}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture = Path(args.fixtures) / "dependency-correction"
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    committed = {key(b): b for b in (comuvia.load_record(p.read_bytes()) for p in sorted((fixture / "records").glob("*.json")))}
    files = {comuvia.content_digest(p.read_bytes()): p.read_bytes()
             for folder in ("source", "artifacts") for p in sorted((fixture / folder).iterdir())}
    out = {}

    # 1. Creation from in-memory bytes.
    tide = b"hour,water_level_m\n00,1.20\n06,3.85\n12,1.05\n18,3.90\n"
    snapshot = ra.new_record("resource_snapshot", "src-example-tide", data_origin="synthetic", recorded_by=BY, recorded_at=AT, fields={
        "resource_type": "statistical_table", "locator": "https://example.org/synthetic/tide.csv",
        "language": {"unknown": "source_declares_no_language"}, "source_version": "first_release",
        "source_published_at": {"date": "2027-02-28", "precision": "day"}, "captured_at": AT,
        "captured_assets": ["tide_csv"], "not_captured": ["full_table"],
        "content": ra.snapshot_content(tide, "text/csv; charset=utf-8")})
    chart_bytes = b"<svg xmlns=\"http://www.w3.org/2000/svg\"/>\n"
    descriptor = ra.new_record("artifact_descriptor", "chart-example-tide", data_origin="synthetic", recorded_by=BY, recorded_at=AT, fields={
        "content": ra.descriptor_content(chart_bytes, "image/svg+xml"), "content_schema": {"unknown": "no_declared_schema"},
        "origin": {"name": "Example authoring tutorial (fictional)", "locator": "https://example.org/synthetic/"},
        "published_at": {"unknown": "not_published"}, "retrieved_at": AT, "units": ["m"],
        "rights_reference": "Original synthetic example content.", "access": "private", "locator": "urn:example:chart-tide"})
    for body, data in ((snapshot, tide), (descriptor, chart_bytes)):
        check(comuvia.validate(body) == [], f"{body['id']} validates")
        check(comuvia.verify(body, content=data).content_identity == "match", f"{body['id']} content matches")
    check("retained" not in descriptor["content"] and snapshot["content"]["retained"] is True, "the two content shapes")
    error = refused(lambda: ra.snapshot_content("text, not bytes", "text/plain"))
    check(error.codes == ["invalid_content_input"], "non-bytes content is refused")

    # 2. Identity round trip: rebuild all 13 committed records from their parts.
    rebuilt = {}

    def pins_to_rebuilt(extensions):
        result = copy.deepcopy(extensions)
        for edge in result[dp.NAMESPACE]["depends_on"]:
            if not comuvia.is_marker(edge["pin"]):
                edge["pin"] = comuvia.reference_to(rebuilt[(edge["pin"]["record_type"], edge["pin"]["id"], edge["pin"]["revision"])])
        return result

    def content_of(body):
        data = files[body["content"]["digest"]]
        builder = ra.snapshot_content if body["record_type"] == "resource_snapshot" else ra.descriptor_content
        return builder(data, body["content"]["media_type"])

    first = sorted(k for k in committed if k[2] == 1)
    while len(rebuilt) < len(first):
        for k in first:
            body = committed[k]
            targets = [(e["pin"]["record_type"], e["pin"]["id"], e["pin"]["revision"])
                       for e in body["extensions"][dp.NAMESPACE]["depends_on"] if not comuvia.is_marker(e["pin"])]
            if k in rebuilt or any(t not in rebuilt for t in targets):
                continue
            fields = {f: v for f, v in body.items() if f not in ra.ENVELOPE}
            fields["content"] = content_of(body)
            fields["extensions"] = pins_to_rebuilt(body["extensions"])
            rebuilt[k] = ra.new_record(k[0], k[1], data_origin=body["data_origin"], recorded_by=body["recorded_by"],
                                       recorded_at=body["recorded_at"], fields=fields)
    repinned = []
    for record_type, record_id in (("resource_snapshot", "src-calder-quarterly"), ("artifact_descriptor", "res-calder-annual"),
                                   ("artifact_descriptor", "sim-calder-stress")):
        old, new = committed[(record_type, record_id, 1)], committed[(record_type, record_id, 2)]
        replace = {f: new[f] for f in new if f not in ra.ENVELOPE and f != "extensions" and new[f] != old[f]}
        replace["content"] = content_of(new)
        repin = []
        if new["extensions"] != old["extensions"]:  # only the dependency pins differ: move them, do not copy them
            moved = [(old_pin, new_pin) for old_pin, new_pin in zip(
                (e["pin"] for e in old["extensions"][dp.NAMESPACE]["depends_on"]),
                (e["pin"] for e in new["extensions"][dp.NAMESPACE]["depends_on"])) if old_pin != new_pin]
            repin = [(rebuilt[(p["record_type"], p["id"], p["revision"])], rebuilt[(q["record_type"], q["id"], q["revision"])])
                     for p, q in moved]
            repinned.append(record_id)
        rebuilt[key(new)] = ra.revise(rebuilt[key(old)], recorded_by=new["recorded_by"], recorded_at=new["recorded_at"],
                                      replace=replace, repin=repin)
    expected_digests = {(e["record"]["record_type"], e["record"]["id"], e["record"]["revision"]): e["record"]["digest"]
                        for e in expected["record_identity"]}
    check(len(rebuilt) == 13, "13 records rebuilt")
    check(all(comuvia.record_digest(b) == expected_digests[k] for k, b in rebuilt.items()), "every rebuilt digest equals expected.json")
    check(repinned == ["res-calder-annual", "sim-calder-stress"], "two revision 2 records were built through repin")
    out["round_trip"] = {"records": 13, "through_repin": repinned}

    # 3. Provenance: absent, None or empty gives missing_provenance; invalid values reach the core codes.
    base = {"data_origin": "synthetic", "recorded_by": BY, "recorded_at": AT}
    fields = {f: v for f, v in committed[("artifact_descriptor", "method-annual-sum", 1)].items() if f not in ra.ENVELOPE}
    for name in ra.PROVENANCE:
        for value in ("absent", None, ""):
            given = {k: v for k, v in base.items() if k != name}
            if value != "absent":
                given[name] = value
            error = refused(lambda: ra.new_record("artifact_descriptor", "method-x", fields=fields, **given))
            check([(i.pointer, i.code) for i in error.issues] == [(f"/{name}", "missing_provenance")], f"{name} {value!r}")
    for name, value, code in (("data_origin", "estimated", "invalid_value"), ("recorded_by", "bad id", "invalid_identifier"),
                              ("recorded_at", "2027-03-01 09:00", "invalid_timestamp")):
        error = refused(lambda: ra.new_record("artifact_descriptor", "method-x", fields=fields, **{**base, name: value}))
        check([(i.pointer, i.code) for i in error.issues] == [(f"/{name}", code)], f"invalid {name} gives {code}")
    check(refused(lambda: ra.new_record("artifact_descriptor", "method-x", fields=fields, **{**base, "data_origin": "estimated"}))
          .issues[0].hint == "Allowed values: observed, synthetic.", "the data_origin hint lists the allowed values")
    check(refused(lambda: ra.new_record("artifact_descriptor", "method-x", fields=fields, **{**base, "recorded_at": "2027-03-01 09:00"}))
          .issues[0].hint != "", "the timestamp hint shows the required form")
    made = ra.new_record("artifact_descriptor", "method-x", fields=fields, **base)
    check(set(made) == set(ra.ENVELOPE) | set(fields), "no field beyond the envelope and the caller's fields")

    # 4. Protected fields.
    for name in ra.ENVELOPE:
        error = refused(lambda: ra.new_record("artifact_descriptor", "method-x", fields={**fields, name: "x"}, **base))
        check(("/" + name, "protected_field") in [(i.pointer, i.code) for i in error.issues], f"{name} protected in fields")
        error = refused(lambda: ra.revise(made, recorded_by=BY, recorded_at="2027-03-02T09:00:00Z", replace={name: "x"}))
        check(("/" + name, "protected_field") in [(i.pointer, i.code) for i in error.issues], f"{name} protected in replace")
    observed = ra.revise(made, recorded_by=BY, recorded_at="2027-03-02T09:00:00Z", data_origin="observed")
    check(observed["data_origin"] == "observed" and made["data_origin"] == "synthetic", "data_origin changes only through data_origin=")

    # 5. The reported consumer failures, through explain.
    snap = committed[("resource_snapshot", "src-calder-quarterly", 1)]
    desc = committed[("artifact_descriptor", "res-calder-annual", 2)]

    def broken(body, change):
        body = copy.deepcopy(body)
        change(body)
        return ra.explain(comuvia.validate(body))
    cases = [
        (snap, lambda b: b.update(schema="comuvia/0.1.0"), [("/schema", "unsupported_schema_version")], True),
        (desc, lambda b: [b.pop(f) for f in ("locator", "units", "access")],
         [("/access", "missing_required_field"), ("/locator", "missing_required_field"), ("/units", "missing_required_field")], True),
        (desc, lambda b: b["content"].update(digest="sha256:XYZ"), [("/content/digest", "malformed_digest")], True),
        (snap, lambda b: b["content"].update(digest={"unknown": "not_kept"}), [("/content/digest", "malformed_digest")], True),
        (desc, lambda b: b.update(my_note="kept here"), [("/my_note", "unrecognized_member")], True),
        (desc, lambda b: b.update(access="internal"), [("/access", "invalid_value")], True),
        (desc, lambda b: b["predecessor"].update(revision=5), [("/predecessor", "invalid_predecessor")], True),
        (desc, lambda b: b.update(recorded_at="2027-02-10T15:30:00"), [("/recorded_at", "invalid_timestamp")], True),
    ]
    for body, change, wanted, hinted in cases:
        issues = broken(body, change)
        check([(i.pointer, i.code) for i in issues] == wanted, f"failure {wanted}")
        check(all(i.hint for i in issues) == hinted, f"hints for {wanted}")
    access = broken(desc, lambda b: b.update(access="internal"))[0]
    check(access.hint == "Allowed values: private, public, restricted.", "the access hint lists exactly the three values")
    check("extensions" in broken(desc, lambda b: b.update(my_note="kept here"))[0].hint, "custom data points to extensions")
    out["explained_failures"] = len(cases)

    # 6. Revision errors and guarantees.
    src1 = rebuilt[("resource_snapshot", "src-calder-quarterly", 1)]
    frozen = copy.deepcopy(src1)
    check(refused(lambda: ra.revise(src1, recorded_by=BY, recorded_at="2027-01-19T10:00:00Z", replace={"source_version": "x"})).codes
          == ["recorded_before_predecessor"], "a correction cannot be recorded before its predecessor")
    check(refused(lambda: ra.revise(src1, recorded_by=BY, recorded_at="2027-01-20T04:59:59-05:00", replace={"source_version": "x"})).codes
          == ["recorded_before_predecessor"], "offsets are applied: 04:59:59-05:00 is one second before 10:00:00Z")
    check(ra.revise(src1, recorded_by=BY, recorded_at="2027-01-20T05:00:00-05:00", replace={"source_version": "x"})["revision"] == 2,
          "the same instant (05:00:00-05:00 is 10:00:00Z) is not earlier")
    check(refused(lambda: ra.revise(src1, recorded_by=BY, recorded_at=AT)).codes == ["no_change"], "an unchanged successor is refused")
    check(ra.instant("2027-03-20T14:00:00Z") is not None and ra.instant("2027-03-20T14:00:00Z\n") is None,
          "a trailing newline is not part of a timestamp")
    bad = copy.deepcopy(src1)
    bad["schema"] = "comuvia/0.1.0"
    check(refused(lambda: ra.revise(bad, recorded_by=BY, recorded_at=AT, replace={"source_version": "x"})).codes
          == ["unsupported_schema_version"], "an invalid previous is refused")
    successor = ra.revise(src1, recorded_by=BY, recorded_at=AT, replace={"source_version": "x"})
    check(successor["revision"] == 2 and successor["predecessor"] == comuvia.reference_to(src1), "revision + 1 and predecessor")
    check(src1 == frozen and comuvia.record_digest(src1) == comuvia.record_digest(frozen), "previous is unchanged")
    descriptor_shape = {"media_type": "text/csv; charset=utf-8", "byte_length": 1, "digest": comuvia.content_digest(b"x")}
    check([(i.pointer, i.code) for i in refused(lambda: ra.revise(src1, recorded_by=BY, recorded_at=AT,
                                                                  replace={"content": descriptor_shape})).issues]
          == [("/content/retained", "missing_required_field")], "replace substitutes content whole; it does not merge")
    new_extensions = copy.deepcopy(src1["extensions"])
    new_extensions[dp.NAMESPACE]["meaning"]["unit"] = "TEU (twenty-foot equivalent units)"
    check(ra.revise(src1, recorded_by=BY, recorded_at=AT, replace={"extensions": new_extensions})["extensions"] == new_extensions,
          "a nested object is replaced exactly as given")

    # 7. Safe successor pins.
    src2 = rebuilt[("resource_snapshot", "src-calder-quarterly", 2)]
    chart1 = rebuilt[("artifact_descriptor", "chart-calder-quarterly", 1)]
    fuel = rebuilt[("resource_snapshot", "src-calder-fuel", 1)]
    res1, res2 = rebuilt[("artifact_descriptor", "res-calder-annual", 1)], rebuilt[("artifact_descriptor", "res-calder-annual", 2)]
    for pair in ((src1, fuel), (src2, src1), (src1, src1)):
        check(refused(lambda: ra.revise(chart1, recorded_by=BY, recorded_at=AT, repin=[pair])).codes[0] == "not_a_successor",
              "not_a_successor")
    check([(i.pointer, i.code) for i in refused(lambda: ra.revise(chart1, recorded_by=BY, recorded_at=AT, repin=[(res1, res2)])).issues]
          == [("/repin/0", "pin_not_found")], "pin_not_found")
    chart_before = copy.deepcopy(chart1)
    chart2 = ra.revise(chart1, recorded_by=BY, recorded_at=AT, repin=[(src1, src2)])
    check(chart2["extensions"][dp.NAMESPACE]["depends_on"][0]["pin"] == comuvia.reference_to(src2), "the extension pin moved")
    check(chart1 == chart_before, "the old dependent is unchanged")
    codes = {i.code for i in dp.check_bundle(list(rebuilt.values()) + [chart2])}
    check(not codes & {"pin_mismatch", "missing_pin"}, "the profile sees no broken pin")

    # 8. Stale pins.
    bundle = list(rebuilt.values())
    stale = ra.stale_pins(bundle)
    check([(e["record"]["id"], e["record"]["revision"], e["pin"]["id"], e["pin"]["revision"], e["state"]) for e in stale] == [
        ("chart-calder-quarterly", 1, "src-calder-quarterly", 1, "superseded"),
        ("res-calder-annual", 1, "src-calder-quarterly", 1, "superseded"),
        ("sim-calder-stress", 1, "res-calder-annual", 1, "superseded")], "exactly the three superseded pins")
    check(all(e["pointer"] == "/extensions/org.comuvia.dependencies~1v1/depends_on/0/pin" for e in stale), "pointers")
    tampered = copy.deepcopy(fuel)
    tampered["source_version"] = "silently_edited"
    states = {(e["record"]["id"], e["state"]) for e in ra.stale_pins([tampered if b is fuel else b for b in bundle])}
    check({("out-calder-fuel", "mismatch"), ("out-calder-mixed", "mismatch")} <= states, "a tampered target gives mismatch")
    states = {(e["record"]["id"], e["state"]) for e in ra.stale_pins([b for b in bundle if b is not fuel])}
    check({("out-calder-fuel", "missing"), ("out-calder-mixed", "missing")} <= states, "a removed target gives missing")
    out["stale_pins"] = len(stale)

    # 9. Unknown stays unknown.
    method = rebuilt[("artifact_descriptor", "method-annual-sum", 1)]
    revised = ra.revise(method, recorded_by=BY, recorded_at=AT, replace={"rights_reference": "Original synthetic example; reviewed."})
    check(dict(markers(revised)) == dict(markers(method)) and len(dict(markers(method))) >= 6, "every marker is unchanged")

    # 10. Store.
    comuvia.RecordStore.create(work / "store")
    order = sorted(rebuilt, key=lambda k: (k[2], first.index(k) if k in first else 0))
    with comuvia.RecordStore(work / "store", writer=True) as store:
        earlier = []
        for k in order:
            store.append(rebuilt[k])
            if k[2] == 1:
                earlier.append(k)
        check(all(comuvia.record_digest(store.get(*k)) == expected_digests[k] for k in earlier), "earlier digests unchanged")
        check(store.verify().ok, "store verify is ok")
    check(comuvia.revision_conflicts(bundle) == [], "no revision conflicts")

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("Tutorial E passed:", json.dumps(out))


if __name__ == "__main__":
    main()
