"""Tutorial D: declared dependencies and the impact of a correction.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_d_dependencies.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

It uses the example helper ``dependency_profile.py`` beside this file (the profile
``org.comuvia.dependencies/v1``; not part of the comuvia package). Every value the tutorial
states is checked; the script exits non-zero if one differs.
"""

import argparse
import copy
import hashlib
import json
import random
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the helper; package_smoke runs this with -I

import comuvia  # noqa: E402
import dependency_profile as dp  # noqa: E402

NS = dp.NAMESPACE


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL D CHECK FAILED: {message}")


def ref(record_type, record_id, revision):
    return {"record_type": record_type, "id": record_id, "revision": revision}


def codes_for(issues, record=None):
    return {i.code for i in issues if record is None or i.record == record}


def statuses(report):
    return {(e["record"]["id"], e["record"]["revision"]): e for e in report["records"]}


def load(fixture: Path):
    records = [comuvia.load_record(p.read_bytes()) for p in sorted((fixture / "records").glob("*.json"))]
    files = {}
    for folder in ("source", "artifacts"):
        for path in sorted((fixture / folder).iterdir()):
            files[comuvia.content_digest(path.read_bytes())] = path.read_bytes()
    contents = {dp.key_of(b): files[b["content"]["digest"]] for b in records}
    return records, contents


def by_id(records, record_id, revision=1):
    return next(b for b in records if b["id"] == record_id and b["revision"] == revision)


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
    records, contents = load(fixture)
    out = {"records": len(records)}
    src1, src2 = by_id(records, "src-calder-quarterly", 1), by_id(records, "src-calder-quarterly", 2)
    check(len(records) == 13, "13 committed records")

    # 1. The committed bundle is clean, and core identity holds for every record.
    check(dp.check_bundle(records, contents) == [], "the bundle has no issues")
    expected_digests = {(e["record"]["id"], e["record"]["revision"]): e["record"]["digest"] for e in expected["record_identity"]}
    for body in records:
        check(comuvia.validate(body) == [], f"{body['id']} r{body['revision']} validates")
        result = comuvia.verify(body, expected_digest=expected_digests[(body["id"], body["revision"])],
                                content=contents[dp.key_of(body)], records=records)
        check(result.record_identity == "match" and result.content_identity == "match", f"{body['id']}: identity")
        check(all(r.result == "match" for r in result.references), f"{body['id']}: core references match")
    out["bundle"] = "clean"

    # 2. The source correction: exactly these statuses, in any record order, equal to expected.json.
    report = dp.impact(records, src2)
    check(report == expected["impact_of_source_correction"], "the impact report equals expected.json")
    for seed in (1, 2, 3):
        shuffled = records[:]
        random.Random(seed).shuffle(shuffled)
        check(dp.impact(shuffled, src2) == report, f"order-independent (shuffle {seed})")
    status = statuses(report)
    groups = {s: sorted(k for k, e in status.items() if e["status"] == s) for s in ("affected", "unaffected", "unknown")}
    check(groups["affected"] == [("chart-calder-quarterly", 1), ("res-calder-annual", 1), ("sim-calder-stress", 1)], "affected set")
    check(groups["unaffected"] == [("method-annual-sum", 1), ("model-calder-stress", 1), ("out-calder-fuel", 1),
                                   ("res-calder-annual", 2), ("sim-calder-stress", 2), ("src-calder-fuel", 1),
                                   ("synth-shock-path", 1)], "unaffected set")
    check(groups["unknown"] == [("out-calder-mixed", 1)] and status[("out-calder-mixed", 1)]["reasons"] == ["partial_coverage"],
          "the partial-coverage output is unknown")
    q1 = ref("resource_snapshot", "src-calder-quarterly", 1)
    check(status[("res-calder-annual", 1)]["path"] == [ref("artifact_descriptor", "res-calder-annual", 1), q1], "result path")
    check(status[("chart-calder-quarterly", 1)]["path"] == [ref("artifact_descriptor", "chart-calder-quarterly", 1), q1], "chart path")
    check(status[("sim-calder-stress", 1)]["path"] == [ref("artifact_descriptor", "sim-calder-stress", 1),
                                                       ref("artifact_descriptor", "res-calder-annual", 1), q1], "simulation path")
    check(status[("res-calder-annual", 1)]["latest_status"] == "unaffected", "the result is corrected by its r2")
    check(status[("sim-calder-stress", 1)]["latest_status"] == "unaffected", "the simulation is corrected by its r2")
    check(status[("chart-calder-quarterly", 1)]["latest"]["revision"] == 1
          and status[("chart-calder-quarterly", 1)]["latest_status"] == "affected", "the chart needs review")
    check(report["change"] == {"content_changed": True, "meaning_changed": False, "dependencies_changed": False,
                               "changed_fields": ["captured_at", "content", "recorded_at", "source_published_at", "source_version"]},
          "change summary")
    check(report["coverage"] == "partial", "report coverage is partial while anything is unknown")
    check(status[("sim-calder-stress", 1)]["synthetic_in_closure"] and not status[("res-calder-annual", 1)]["synthetic_in_closure"],
          "the synthetic shock path is reported in the simulation's closure only")
    out["impact"] = {s: [f"{i}/r{r}" for i, r in keys] for s, keys in groups.items()}

    # 3. Old identities are retained when the corrections are appended.
    r2_keys = {("src-calder-quarterly", 2), ("res-calder-annual", 2), ("sim-calder-stress", 2)}
    before = [b for b in records if (b["id"], b["revision"]) not in r2_keys]
    after = [b for b in records if (b["id"], b["revision"]) in r2_keys]
    check(len(before) == 10, "10 records predate the correction")
    comuvia.RecordStore.create(work / "store")
    with comuvia.RecordStore(work / "store", writer=True) as store:
        for body in before:
            store.append(body)
        first = {dp.key_of(b): comuvia.record_digest(store.get(*dp.key_of(b))) for b in before}
        for body in sorted(after, key=lambda b: ["src-calder-quarterly", "res-calder-annual", "sim-calder-stress"].index(b["id"])):
            store.append(body)
        check(all(comuvia.record_digest(store.get(*k)) == d == expected_digests[(k[1], k[2])] for k, d in first.items()),
              "the 10 earlier records keep their digests")
        check(store.verify().ok, "store verify is ok")
    check(comuvia.revision_conflicts(records) == [], "no revision conflicts")

    # 4. The core boundary: the store accepts a dangling extension pin; the profile does not.
    orphan = copy.deepcopy(by_id(records, "out-calder-fuel"))
    orphan["id"] = "out-calder-orphan"
    orphan["extensions"][NS]["depends_on"][0]["pin"] = {
        "record_type": "resource_snapshot", "id": "src-calder-nowhere", "revision": 1,
        "digest": "sha256:" + hashlib.sha256(b"nothing is pinned here").hexdigest()}
    check(comuvia.validate(orphan) == [], "the orphan is a valid 0.1 record")
    with comuvia.RecordStore(work / "store", writer=True) as store:
        store.append(orphan)  # core append ignores extensions
    bundle = records + [orphan]
    check(codes_for(dp.check_bundle(bundle), "artifact_descriptor/out-calder-orphan/r1") == {"missing_pin"}, "missing_pin in the bundle")
    orphan_status = statuses(dp.impact(bundle, src2))[("out-calder-orphan", 1)]
    check(orphan_status["status"] == "unknown" and orphan_status["reasons"] == ["missing_pin"], "a missing pin is unknown, never unaffected")
    out["core_boundary"] = "store accepted the dangling extension pin; profile reported missing_pin"

    # 5. A tampered dependency, and tampered retained bytes.
    fuel = by_id(records, "src-calder-fuel")
    tampered = copy.deepcopy(fuel)
    tampered["source_version"] = "silently_edited"
    bundle = [tampered if b is fuel else b for b in records]
    issues = dp.check_bundle(bundle)
    check({(i.record, i.code) for i in issues if i.code == "pin_mismatch"}
          == {("artifact_descriptor/out-calder-fuel/r1", "pin_mismatch"), ("artifact_descriptor/out-calder-mixed/r1", "pin_mismatch")},
          "both dependents report pin_mismatch")
    tampered_report = dp.impact(bundle, src2)
    check(statuses(tampered_report)[("out-calder-fuel", 1)]["reasons"] == ["pin_mismatch"], "the fuel output becomes unknown")
    check(tampered_report["coverage"] == "partial", "overall coverage is partial")
    altered = dict(contents)
    altered[dp.key_of(src1)] = contents[dp.key_of(src1)] + b"2026-Q5,1,first\n"
    check(codes_for(dp.check_bundle(records, altered)) == {"content_digest_mismatch"}, "altered bytes give content_digest_mismatch")

    # 6. A withheld input.
    withheld = copy.deepcopy(by_id(records, "out-calder-fuel"))
    withheld["extensions"][NS]["depends_on"][0]["pin"] = {"withheld": "supplier_confidential"}
    bundle = [withheld if b["id"] == "out-calder-fuel" else b for b in records]
    entry = statuses(dp.impact(bundle, src2))[("out-calder-fuel", 1)]
    check(entry["status"] == "unknown" and entry["reasons"] == ["withheld_pin"], "a withheld pin is unknown")

    # 7. Stale mutual pins: two mismatches, no cycle, and the walk terminates.
    def stub(record_id, pins):
        body = copy.deepcopy(by_id(records, "out-calder-fuel"))
        body["id"] = record_id
        body["extensions"][NS]["depends_on"] = [by_id(records, "out-calder-fuel")["extensions"][NS]["depends_on"][0]] + [
            {"role": "data_input", "pin": p, "selection": "whole record"} for p in pins]
        return body
    a0, b0 = stub("out-mutual-a", []), stub("out-mutual-b", [])
    a1, b1 = stub("out-mutual-a", [comuvia.reference_to(b0)]), stub("out-mutual-b", [comuvia.reference_to(a0)])
    mutual = statuses(dp.impact(records + [a1, b1], src2))
    for name in ("out-mutual-a", "out-mutual-b"):
        check([e["state"] for e in mutual[(name, 1)]["edges"]] == ["match", "mismatch"], f"{name}: one stale mutual pin")
        check(mutual[(name, 1)]["reasons"] == ["pin_mismatch"], f"{name}: unknown with pin_mismatch")

    # The cycle refusal is defensive: real digests cannot form one. Show it with a broken digest function.
    real_digest = comuvia.record_digest

    def broken(body):
        if body.get("id") in ("out-cycle-a", "out-cycle-b"):
            return "sha256:" + hashlib.sha256(body["id"].encode()).hexdigest()
        return real_digest(body)
    ca = stub("out-cycle-a", [{**comuvia.reference_to(b0), "id": "out-cycle-b", "digest": broken({"id": "out-cycle-b"})}])
    cb = stub("out-cycle-b", [{**comuvia.reference_to(a0), "id": "out-cycle-a", "digest": broken({"id": "out-cycle-a"})}])
    with mock.patch.object(dp.comuvia, "record_digest", broken):
        try:
            dp.impact(records + [ca, cb], src2)
            check(False, "a cycle is refused")
        except dp.DependencyCycle as refusal:
            check(str(refusal).startswith("dependency_cycle"), "dependency_cycle refusal")

    # 8. A correction to meaning only.
    meaning_only = copy.deepcopy(src1)
    meaning_only["revision"] = 2
    meaning_only["predecessor"] = comuvia.reference_to(src1)
    meaning_only["extensions"][NS]["meaning"]["unit"] = "TEU (twenty-foot equivalent units)"
    meaning_only["recorded_at"] = "2027-02-12T08:00:00Z"
    bundle = before + [meaning_only]
    meaning_report = dp.impact(bundle, meaning_only)
    check(meaning_report["change"]["content_changed"] is False and meaning_report["change"]["meaning_changed"] is True,
          "meaning changed, content did not")
    check(sorted(k for k, e in statuses(meaning_report).items() if e["status"] == "affected") == groups["affected"],
          "the same affected set")

    # 9. Every profile issue code, each from one minimal mutation of a leaf record, and change_not_successor.
    mixed = by_id(records, "out-calder-mixed")
    name = "artifact_descriptor/out-calder-mixed/r1"
    fuel_pin = mixed["extensions"][NS]["depends_on"][0]

    def mutate(change):
        body = copy.deepcopy(mixed)
        change(body)
        return [body if b is mixed else b for b in records]
    profile = lambda b: b["extensions"][NS]  # noqa: E731
    cases = {
        "unsupported_profile_version": lambda b: b["extensions"].update({"org.comuvia.dependencies/v2": {}}),
        "invalid_profile": lambda b: profile(b).pop("coverage"),
        "unsupported_role": lambda b: profile(b)["depends_on"].append({**fuel_pin, "role": "calibration", "pin": {"unknown": "x"}}),
        "duplicate_pin": lambda b: profile(b)["depends_on"].append(dict(fuel_pin)),
        "observed_has_inputs": lambda b: profile(b).update(value_origin="observed"),
        "derived_without_inputs": lambda b: profile(b)["depends_on"][0].update(role="method"),
        "origin_conflict": lambda b: (b.update(data_origin="observed"), profile(b).update(value_origin="synthetic")),
        "unit_conflict": lambda b: profile(b)["meaning"].update(unit="TEU"),
        "missing_pin": lambda b: profile(b)["depends_on"][0]["pin"].update(id="src-calder-nowhere"),
        "pin_mismatch": lambda b: profile(b)["depends_on"][0]["pin"].update(digest="sha256:" + "a" * 64),
        "limit_exceeded": lambda b: profile(b)["depends_on"].extend(
            {"role": "assumption", "pin": {"unknown": f"input_{n}"}, "selection": "whole"} for n in range(64)),
    }
    for code, change in cases.items():
        check(codes_for(dp.check_bundle(mutate(change)), name) == {code}, f"{code} from one mutation")
    newline = mutate(lambda b: profile(b)["depends_on"][0]["pin"].update(digest=fuel_pin["pin"]["digest"] + "\n"))
    check(codes_for(dp.check_bundle(newline), name) == {"invalid_profile"}, "a digest with a trailing newline is not a pin")
    altered = dict(contents)
    altered[dp.key_of(mixed)] = b"{}\n"
    check(codes_for(dp.check_bundle(records, altered)) == {"content_digest_mismatch"}, "content_digest_mismatch")
    try:
        dp.impact(records, src1)
        check(False, "revision 1 is refused")
    except dp.ChangeNotSuccessor as refusal:
        check(str(refusal).startswith("change_not_successor"), "change_not_successor refusal")
    out["refusal_codes"] = sorted([*cases, "content_digest_mismatch", "change_not_successor", "dependency_cycle"])

    # 10. Limits: 65 edges.
    check(len(mutate(cases["limit_exceeded"])[records.index(mixed)]["extensions"][NS]["depends_on"]) == 65, "65 edges")

    # 11. A long chain: 2,000 derived records whose ids sort from the deep end. No recursion limit.
    chain, previous = [], src1
    for position in range(2000):
        body = copy.deepcopy(by_id(records, "chart-calder-quarterly"))
        body["id"] = f"chain-{2000 - position:05d}"
        body["extensions"][NS]["depends_on"] = [{"role": "data_input", "pin": comuvia.reference_to(previous), "selection": "all"}]
        chain.append(body)
        previous = body
    chain_status = statuses(dp.impact(records + chain, src2))
    check(all(chain_status[(b["id"], 1)]["status"] == "affected" for b in chain), "every chain record is affected")
    check(len(chain_status[("chain-00001", 1)]["path"]) == 2001, "the deepest path has 2,001 steps")
    out["long_chain"] = len(chain)

    # 12. An invalid v1 profile: unknown with invalid_profile, and its dependents see an unprofiled input.
    m1 = copy.deepcopy(by_id(records, "chart-calder-quarterly"))
    m1["id"] = "chart-calder-invalid"
    m1["extensions"][NS]["note"] = "an extra key the profile does not allow"
    reader = copy.deepcopy(by_id(records, "out-calder-fuel"))
    reader["id"] = "out-reads-invalid"
    reader["extensions"][NS]["depends_on"].append({"role": "data_input", "pin": comuvia.reference_to(m1), "selection": "all"})
    invalid = statuses(dp.impact(records + [m1, reader], src2))
    check(invalid[("chart-calder-invalid", 1)]["status"] == "unknown"
          and invalid[("chart-calder-invalid", 1)]["reasons"] == ["invalid_profile"]
          and "path" not in invalid[("chart-calder-invalid", 1)], "an invalid profile is unknown with invalid_profile")
    check(invalid[("out-reads-invalid", 1)]["reasons"] == ["unprofiled_input"], "its dependent sees an unprofiled input")

    out["limitations"] = list(dp.LIMITATIONS)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("Tutorial D passed:", json.dumps(out["impact"]))


if __name__ == "__main__":
    main()
