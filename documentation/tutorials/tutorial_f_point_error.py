"""Tutorial F: point-forecast error evidence.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_f_point_error.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

It uses the example helpers beside this file (``point_error_example.py``, ``record_authoring.py``
and ``dependency_profile.py``; none is part of the comuvia package). Every value the tutorial
states is checked; the script exits non-zero if one differs. Synthetic arithmetic only: no
provider's skill is shown or claimed.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the helpers; package_smoke runs this with -I

import comuvia  # noqa: E402
import dependency_profile as dp  # noqa: E402
import point_error_example as pe  # noqa: E402
import record_authoring as ra  # noqa: E402

# The hand controls (percentage points; squared errors in percentage points squared).
HAND = {
    ("err-alder-calder-growth-2027q1", 2): ("0.5", "0.5", "0.25"),
    ("err-birch-calder-growth-2027q1", 2): ("-0.5", "0.5", "0.25"),
    ("err-cedar-calder-growth-2027q1", 2): ("0", "0", "0"),
    ("err-alder-calder-growth-2027q1", 1): ("0.4", "0.4", "0.16"),
    ("err-birch-calder-growth-2027q1", 1): ("-0.6", "0.6", "0.36"),
    ("err-cedar-calder-growth-2027q1", 1): ("-0.1", "0.1", "0.01"),
}


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL F CHECK FAILED: {message}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture = Path(args.fixtures) / "point-error"
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    records = [comuvia.load_record(p.read_bytes()) for p in sorted((fixture / "records").glob("*.json"))]
    files = {comuvia.content_digest(p.read_bytes()): p.read_bytes() for p in sorted((fixture / "artifacts").iterdir())}
    contents = {pe.key_of(b): files[b["content"]["digest"]] for b in records}
    by = {(b["id"], b["revision"]): b for b in records}
    target, rule = by[("target-calder-growth-2027q1", 1)], by[("rule-point-error", 1)]
    alder = by[("fc-alder-calder-growth-2027q1", 1)]
    out1, out2 = by[("outcome-calder-growth-2027q1", 1)], by[("outcome-calder-growth-2027q1", 2)]
    results = [b for b in records if b["content_schema"] == pe.RESULT]
    out = {"records": len(records)}
    check(len(records) == 13 and len(results) == 6, "13 records, 6 results")

    def redescribe(body, change, bundle=None, data=None):
        """A copy of ``body`` whose artifact object is changed and whose descriptor matches the new bytes."""
        obj = comuvia.parse_json(data if data is not None else contents[pe.key_of(body)])
        change(obj)
        new_bytes = comuvia.canonicalize(obj)
        new_body = copy.deepcopy(body)
        new_body["content"] = ra.descriptor_content(new_bytes, "application/json")
        return new_body, new_bytes

    def swapped(old, new, new_bytes, bundle=None, base=None):
        bundle = [new if b is old else b for b in (bundle or records)]
        mapping = dict(base or contents)
        mapping[pe.key_of(new)] = new_bytes
        return bundle, mapping

    # 1. The bundle is clean.
    check(dp.check_bundle(records, contents) == [], "the dependency profile reports no issue")
    for body in records:
        check(comuvia.validate(body) == [], f"{body['id']} validates")
        result = comuvia.verify(body, content=contents[pe.key_of(body)], records=records)
        check(result.content_identity == "match" and all(r.result == "match" for r in result.references), f"{body['id']} identity")
    check(contents[pe.key_of(rule)] == pe.RULE_BYTES and rule["content"]["digest"] == pe.RULE_DIGEST == expected["rule"]["digest"],
          "the rule bytes are the frozen rule")

    # 2. Hand controls.
    stored = {(e["record"]["id"], e["record"]["revision"]): e["result"] for e in expected["results"]}
    for body in results:
        obj = json.loads(contents[pe.key_of(body)])
        k = (body["id"], body["revision"])
        check((obj["signed_error"], obj["absolute_error"], obj["squared_error"]) == HAND[k], f"{k}: hand control")
        check(obj["error_unit"] == "percentage points" and obj["squared_unit"] == "percentage points squared", f"{k}: units")
        check(stored[k] == obj, f"{k}: expected.json")
    out["hand_controls"] = len(HAND)

    # 3. Exactness: 0.1 against 0.3.
    fc, fc_bytes = redescribe(alder, lambda o: o.update(value="0.1"))
    oc, oc_bytes = redescribe(out2, lambda o: o.update(value="0.3"))
    bundle, mapping = swapped(alder, fc, fc_bytes)
    bundle, mapping = swapped(out2, oc, oc_bytes, bundle, mapping)
    exact = pe.evaluate_point(bundle, mapping, target=target, rule=rule, forecast=fc)["result"]
    check((exact["signed_error"], exact["absolute_error"], exact["squared_error"]) == ("-0.2", "0.2", "0.04"), "exact decimal")
    check(0.1 - 0.3 != -0.2, "plain floating point would not give -0.2")

    # 4. A correction preserves earlier evaluations.
    check(all(pe.reproduce(b, records, contents)["status"] == "match" for b in results), "all six results reproduce")
    for body in results:
        pinned = json.loads(contents[pe.key_of(body)])["outcome"]
        check(pinned["revision"] == body["revision"], f"{body['id']} r{body['revision']} pins outcome r{body['revision']}")
    first = [b for b in records if b["revision"] == 1]
    comuvia.RecordStore.create(work / "store")
    with comuvia.RecordStore(work / "store", writer=True) as store:
        for body in first:
            store.append(body)
        before = {pe.key_of(b): comuvia.record_digest(store.get(*pe.key_of(b))) for b in first}
        for body in sorted((b for b in records if b["revision"] == 2), key=lambda b: b["content_schema"] != pe.OUTCOME):
            store.append(body)
        check(all(comuvia.record_digest(store.get(*k)) == d for k, d in before.items()), "earlier digests unchanged")
        check(store.verify().ok, "store verify is ok")
    impact = {(e["record"]["id"], e["record"]["revision"]): e for e in dp.impact(records, out2)["records"]}
    for body in results:
        entry = impact[(body["id"], body["revision"])]
        if body["revision"] == 1:
            check(entry["status"] == "affected" and entry["latest_status"] == "unaffected", f"{body['id']} r1 affected, corrected")
        else:
            check(entry["status"] == "unaffected", f"{body['id']} r2 unaffected")

    # 5. Each semantic reason once, from one in-memory change.
    def reasons_with(change_forecast=None, change_outcome=None, change_target=None):
        bundle, mapping, t, f = records, contents, target, alder
        if change_forecast:
            f, data = redescribe(alder, change_forecast)
            bundle, mapping = swapped(alder, f, data, bundle, mapping)
        if change_outcome:
            o, data = redescribe(out2, change_outcome)
            bundle, mapping = swapped(out2, o, data, bundle, mapping)
        if change_target:
            t, data = redescribe(target, change_target)
            bundle, mapping = swapped(target, t, data, bundle, mapping)
        report = pe.evaluate_point(bundle, mapping, target=t, rule=rule, forecast=f)
        return report.get("reasons", [])
    marker = {"unknown": "not_declared"}
    semantic = {
        "unsupported_output_kind": dict(change_forecast=lambda o: o.update(output_kind="probability")),
        "conditional_not_scored": dict(change_forecast=lambda o: o.update(output_kind="conditional_point")),
        "target_mismatch": dict(change_forecast=lambda o: o.update(target="another-target")),
        "measure_mismatch": dict(change_forecast=lambda o: o.update(measure="nominal output growth")),
        "unit_mismatch": dict(change_forecast=lambda o: o.update(unit="index points")),
        "missing_unit": dict(change_forecast=lambda o: o.update(unit=marker)),
        "period_mismatch": dict(change_forecast=lambda o: o.update(period="2027-Q2")),
        "missing_cutoff": dict(change_forecast=lambda o: o.update(information_cutoff=marker)),
        "impossible_time_order": dict(change_forecast=lambda o: o.update(information_cutoff="2027-03-21T00:00:00Z")),
        "post_outcome_forecast": dict(change_forecast=lambda o: o.update(issued_at="2027-04-28T08:30:00-04:00")),
        "missing_outcome": dict(change_target=lambda o: o.update(outcome_record="outcome-nowhere")),
        "unresolved_outcome": dict(change_outcome=lambda o: o.update(status="pending")),
        "outcome_edition_mismatch": dict(change_outcome=lambda o: o.update(edition="second_release")),
        "malformed_value": dict(change_forecast=lambda o: o.update(value="1e1")),
    }
    check(sorted(semantic) == sorted(pe.ELIGIBILITY[3:]), "all 14 semantic reasons are covered")
    for code, changes in semantic.items():
        check(reasons_with(**changes) == [code], f"{code} from one change")
    multi = reasons_with(change_forecast=lambda o: o.update(output_kind="conditional_point", period="2027-Q2", information_cutoff=marker))
    check(multi == ["conditional_not_scored", "period_mismatch", "missing_cutoff"], "several reasons, in eligibility order")
    out["semantic_reasons"] = len(semantic)

    # 6. Integrity: nothing tampered ever gives match.
    res_alder = by[("err-alder-calder-growth-2027q1", 2)]
    statuses = []
    altered = dict(contents)
    altered[pe.key_of(alder)] = contents[pe.key_of(alder)].replace(b'"3.0"', b'"3.1"')
    check(pe.evaluate_point(records, altered, target=target, rule=rule, forecast=alder)["reasons"] == ["content_digest_mismatch"],
          "altered forecast bytes are excluded")
    report = pe.reproduce(res_alder, records, altered)
    check(report["status"] == "unavailable" and "content_digest_mismatch" in report["reasons"], "and unavailable to reproduce")
    statuses.append(report["status"])
    edited = copy.deepcopy(out2)
    edited["rights_reference"] = "silently edited"
    report = pe.reproduce(res_alder, [edited if b is out2 else b for b in records], contents)
    check(report == {"status": "unavailable", "reasons": ["pin_mismatch"]}, "an edited outcome body gives pin_mismatch")
    statuses.append(report["status"])
    report = pe.reproduce(res_alder, [b for b in records if b is not alder], contents)
    check(report == {"status": "unavailable", "reasons": ["missing_input"]}, "a removed input gives missing_input")
    statuses.append(report["status"])
    new_rule, rule_bytes = redescribe(rule, lambda o: o.update(aggregate="mean"))
    bundle, mapping = swapped(rule, new_rule, rule_bytes)
    check(pe.evaluate_point(bundle, mapping, target=target, rule=new_rule, forecast=alder)["reasons"] == ["rule_unavailable"],
          "a re-described rule is unavailable")
    report = pe.reproduce(res_alder, bundle, mapping)
    check(report["status"] == "unavailable" and "rule_unavailable" in report["reasons"], "and unavailable to reproduce")
    statuses.append(report["status"])
    forged, forged_bytes = redescribe(res_alder, lambda o: o.update(signed_error="0.4"))
    bundle, mapping = swapped(res_alder, forged, forged_bytes)
    report = pe.reproduce(forged, bundle, mapping)
    check(report["status"] == "mismatch", "a consistently forged result gives mismatch")
    statuses.append(report["status"])
    repinned, repinned_bytes = redescribe(res_alder, lambda o: o.update(outcome=comuvia.reference_to(out1)))
    bundle, mapping = swapped(res_alder, repinned, repinned_bytes)
    report = pe.reproduce(repinned, bundle, mapping)
    check(report == {"status": "unavailable", "reasons": ["malformed_input"]}, "pins that disagree with the profile")
    statuses.append(report["status"])
    check("match" not in statuses, "no tampered case gives match")

    # 7. Bundle counts: no aggregate.
    committed = pe.evaluate_bundle(records, contents)
    check((committed["candidates"], committed["scored"], committed["excluded"]) == (3, 3, 0), "3 candidates, 3 scored")
    check(set(committed) == {"candidates", "scored", "excluded", "results"}, "counts only, no aggregate")

    def extra(new_id, change):
        body, data = redescribe(alder, change)
        body["id"] = new_id
        body["locator"] = f"urn:example:calder:{new_id}:r1"
        return body, data
    pine, pine_bytes = extra("fc-pine-calder-growth-2027q1", lambda o: o.update(output_kind="probability", value="0.7", provider="provider:pine-odds"))
    glass, glass_bytes = extra("fc-glass-calder-growth-2027q1", lambda o: o.update(unit=marker, information_cutoff=marker, provider="provider:glass-shaped"))
    bundle = records + [pine, glass]
    mapping = {**contents, pe.key_of(pine): pine_bytes, pe.key_of(glass): glass_bytes}
    report = pe.evaluate_bundle(bundle, mapping)
    check((report["candidates"], report["scored"], report["excluded"]) == (5, 3, 2), "5 candidates, 3 scored, 2 excluded")
    by_id = {r["forecast"]["id"]: r for r in report["results"]}
    check(by_id["fc-pine-calder-growth-2027q1"]["reasons"] == ["unsupported_output_kind"], "a probability is never scored")
    check(by_id["fc-glass-calder-growth-2027q1"]["reasons"] == ["missing_unit", "missing_cutoff"], "the ForeGlass-shaped forecast")
    out["bundle"] = {k: report[k] for k in ("candidates", "scored", "excluded")}

    # 8. Values that are not plain decimal strings.
    for value in ("NaN", "Infinity", "1e1", "", 3.0, "3.0\n", "3.0 "):
        check(reasons_with(change_forecast=lambda o, v=value: o.update(value=v)) == ["malformed_value"], f"{value!r} is malformed")
    check(reasons_with(change_forecast=lambda o: o.update(issued_at="2027-03-20T14:00:00Z\n")) == ["malformed_input"],
          "a time with a trailing newline is not a timestamp")

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("Tutorial F passed:", json.dumps(out))


if __name__ == "__main__":
    main()
