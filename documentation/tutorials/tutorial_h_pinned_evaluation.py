"""Tutorial H: checking a consumer's own pinned evaluation.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_h_pinned_evaluation.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

It uses the example helpers beside this file (``pinned_evaluation.py``, ``record_authoring.py``
and ``dependency_profile.py``; none is part of the comuvia package). The providers, values and
release are fictional. Every value the tutorial states is checked; the script exits non-zero if
one differs.
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the helpers; package_smoke runs this with -I

import comuvia  # noqa: E402
import dependency_profile as dp  # noqa: E402
import pinned_evaluation as pv  # noqa: E402
import record_authoring as ra  # noqa: E402

DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}")


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL H CHECK FAILED: {message}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture = Path(args.fixtures) / "pinned-evaluation"
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    records = [comuvia.load_record(p.read_bytes()) for p in sorted((fixture / "records").glob("*.json"))]
    # The explicit locator map: fixture-relative path -> bytes. Nothing is found by guessing names.
    files = {p.relative_to(fixture).as_posix(): p.read_bytes()
             for folder in ("source", "artifacts") for p in sorted((fixture / folder).iterdir())}
    by_digest = {comuvia.content_digest(data): data for data in files.values()}
    contents = {dp.key_of(b): by_digest[b["content"]["digest"]] for b in records}
    by = {(b["id"], b["revision"]): b for b in records}
    result1, result2 = by[("result-calder-nowcast", 1)], by[("result-calder-nowcast", 2)]
    release1, release2 = by[("release-calder-2027q1-advance", 1)], by[("release-calder-2027q1-advance", 2)]
    wren, vintages = by[("fc-wren-calder-growth", 1)], by[("vintages-calder-2027q1", 1)]
    out = {"records": len(records)}
    check(len(records) == 11, "11 records")

    def locator_for(bundle, file_map):
        def locate(locator):
            if isinstance(locator, tuple):
                body = next((b for b in bundle if dp.key_of(b) == locator), None)
                return comuvia.canonicalize(body) if body is not None else None
            return file_map.get(locator)
        return locate

    locate = locator_for(records, files)
    payloads = {"result_r1": json.loads(contents[dp.key_of(result1)]), "result_r2": json.loads(contents[dp.key_of(result2)]),
                "outcome_manifest": json.loads(files["artifacts/outcome-manifest.json"])}

    # 1. The bundle is clean.
    check(dp.check_bundle(records, contents) == [], "the dependency profile reports no issue")
    for body in records:
        check(comuvia.validate(body) == [], f"{body['id']} validates")
        result = comuvia.verify(body, content=contents[dp.key_of(body)], records=records)
        check(result.content_identity == "match" and all(r.result == "match" for r in result.references), f"{body['id']} identity")

    # 2. Every embedded reference matches; an exemption is explicit and carries its reason.
    for name, payload in payloads.items():
        report = pv.check_embedded(payload, locate)
        stored_counts = expected["embedded"][name]  # recorded before the "ambiguous" state existed; unchanged
        check(report["ok"] and {k: report["counts"][k] for k in stored_counts} == stored_counts
              and report["counts"]["ambiguous"] == 0, f"{name}: every embedded reference matches")
    kinds = sorted({r["kind"] for r in pv.check_embedded(payloads["result_r1"], locate)["references"]})
    check(kinds == ["locator", "pin"], "both kinds: locator references and a comuvia pin")
    exempted = pv.check_embedded(payloads["result_r1"], locate, exempt={"artifacts/scoring.py": "code identity reviewed separately"})
    code = [r for r in exempted["references"] if r["locator"] == "artifacts/scoring.py"][0]
    check(code["state"] == "exempt" and code["reason"] == "code identity reviewed separately" and exempted["ok"], "an explicit exemption")

    # 3. Retained bytes altered and re-described consistently: the record verifies, the payload does not.
    altered_bytes = files["source/wren-forecasts.csv"].replace(b"2.9", b"3.4")
    redescribed = copy.deepcopy(wren)
    redescribed["content"] = ra.snapshot_content(altered_bytes, wren["content"]["media_type"])
    check(comuvia.verify(redescribed, content=altered_bytes).content_identity == "match", "the re-described record verifies")
    bundle = [redescribed if b is wren else b for b in records]
    report = pv.check_embedded(payloads["result_r1"], locator_for(bundle, {**files, "source/wren-forecasts.csv": altered_bytes}))
    states = {r["locator"]: r["state"] for r in report["references"] if r["kind"] == "locator"}
    check(states["source/wren-forecasts.csv"] == "mismatch" and not report["ok"], "the embedded reference catches it")

    # 4. Malformed digests and unresolvable locators.
    broken = copy.deepcopy(payloads["result_r1"])
    broken["rows"][0]["source"]["raw_sha256"] = "not-a-digest"
    broken["rows"][1]["source"]["file"] = "source/nowhere.csv"
    broken["protocol"]["raw_sha256"] = broken["protocol"]["raw_sha256"] + "\n"
    states = {r["pointer"]: r["state"] for r in pv.check_embedded(broken, locate)["references"]}
    check(states["/rows/0/source"] == "malformed" and states["/protocol"] == "malformed", "malformed digests")
    check(states["/rows/1/source"] == "missing", "an unresolvable locator is missing")

    # 5. An independently retained expectation.
    stored = expected["expectation"]
    check(pv.expectation(records) == stored and pv.check_expectation(records, stored)["ok"], "the bundle meets its expectation")
    without_tail = [b for b in records if b is not result2]
    report = pv.check_expectation(without_tail, stored)
    check(report["tail_removed"] == ["artifact_descriptor/result-calder-nowcast"]
          and report["missing"] == ["artifact_descriptor/result-calder-nowcast/r2"], "a removed correction tail")
    check(pv.check_expectation(records + [redescribed], stored)["unexpected"] == [], "same key, so not unexpected")
    extra = copy.deepcopy(vintages)
    extra["id"] = "vintages-calder-extra"
    check(pv.check_expectation(records + [extra], stored)["unexpected"] == ["resource_snapshot/vintages-calder-extra/r1"], "unexpected")
    check(pv.check_expectation(bundle, stored)["changed"] == ["resource_snapshot/fc-wren-calder-growth/r1"], "changed")
    out["expectation"] = "missing, unexpected, changed and tail_removed reported"

    # 5b. Ambiguous shapes and preflight, built in memory.
    two_locators = copy.deepcopy(payloads["result_r1"])
    two_locators["protocol"]["file"] = two_locators["protocol"]["path"]
    two_digests = copy.deepcopy(payloads["result_r1"])
    two_digests["outcome_manifest"]["sha256"] = two_digests["outcome_manifest"]["raw_sha256"]
    for label, payload, pointer in (("path and file", two_locators, "/protocol"),
                                    ("two equal digest keys", two_digests, "/outcome_manifest")):
        report = pv.check_embedded(payload, locate)
        state = [r["state"] for r in report["references"] if r["pointer"] == pointer]
        check(state == ["ambiguous"] and not report["ok"] and report["counts"]["ambiguous"] == 1, f"{label} is ambiguous")
    exempted = pv.check_embedded(two_digests, locate, exempt={"/outcome_manifest": "reviewed: both keys hold the same digest"})
    check([r["state"] for r in exempted["references"] if r["pointer"] == "/outcome_manifest"] == ["exempt"], "an ambiguity exempted with a reason")
    check(pv.preflight(records)["ok"] and pv.preflight(records, stored)["ok"], "the committed bundle passes preflight")
    duplicated = records + [copy.deepcopy(result1)]
    check(pv.preflight(duplicated)["duplicate_keys"] == ["artifact_descriptor/result-calder-nowcast/r1"], "duplicate_keys")
    conflicting = copy.deepcopy(result1)
    conflicting["recorded_by"] = "recorder:someone-else"
    check(pv.preflight(records + [conflicting])["conflicting_keys"] == ["artifact_descriptor/result-calder-nowcast/r1"], "conflicting_keys")
    repeated = copy.deepcopy(stored)
    repeated["entries"].append(dict(repeated["entries"][0]))
    first = repeated["entries"][0]
    check(pv.preflight(records, repeated)["expected_duplicates"] == [f"{first['record_type']}/{first['id']}/r{first['revision']}"],
          "expected_duplicates")
    inflated = copy.deepcopy(stored)
    inflated["latest"]["artifact_descriptor/result-calder-nowcast"] = 3
    check(pv.preflight(records, inflated)["expected_latest_mismatch"] == ["artifact_descriptor/result-calder-nowcast"],
          "expected_latest_mismatch")
    for label, bundle, manifest in (("duplicate", duplicated, stored), ("conflict", records + [conflicting], stored),
                                    ("repeated entry", records, repeated), ("inflated latest", records, inflated)):
        refused = pv.check_expectation(bundle, manifest)
        check(not refused["ok"] and not refused["preflight"]["ok"]
              and refused["missing"] == refused["unexpected"] == refused["changed"] == refused["tail_removed"] == [],
              f"check_expectation refuses a {label} before comparing")
    out["preflight"] = "duplicate_keys, conflicting_keys, expected_duplicates and expected_latest_mismatch refused"

    # 6. Three correction classes, kept separate.
    status = lambda report, rid, rev: {(e["record"]["id"], e["record"]["revision"]): e for e in report["records"]}[(rid, rev)]  # noqa: E731
    transcription = dp.impact(records, result2)
    check(status(transcription, "report-calder-nowcast", 1)["status"] == "affected", "a transcription correction reaches the report")
    check(json.loads(contents[dp.key_of(result2)])["rows"][1]["value"] == "2.9"
          and json.loads(contents[dp.key_of(result1)])["rows"][1]["value"] == "2.8", "r1 keeps its slip; r2 corrects it")
    erratum = dp.impact(records, release2)
    check(status(erratum, "manifest-calder-outcome", 1)["status"] == "affected", "an official erratum reaches the outcome manifest")
    check(b"Erratum" in contents[dp.key_of(release2)] and b"Erratum" not in contents[dp.key_of(release1)], "the original page is kept")
    vintage_key = dp.key_of(vintages)
    for body in records:
        if body is vintages:
            continue
        pins = [(e["pin"]["record_type"], e["pin"]["id"], e["pin"]["revision"])
                for e in dp.profile_of(body)["depends_on"] if not comuvia.is_marker(e["pin"])]
        check(vintage_key not in pins, f"{body['id']} does not depend on the later vintage")
    check(pv.check_embedded(payloads["result_r1"], locate)["ok"], "the first-release evaluation still holds with the later vintage present")
    comuvia.RecordStore.create(work / "store")
    with comuvia.RecordStore(work / "store", writer=True) as store:
        order = sorted(records, key=lambda b: (b["revision"], records.index(b)))
        for body in order:
            store.append(body)
        digests = {(e["record_type"], e["id"], e["revision"]): e["digest"] for e in stored["entries"]}
        check(all(comuvia.record_digest(store.get(*k)) == d for k, d in digests.items()), "every record keeps its digest")
        check(store.verify().ok, "store verify is ok")

    # 7. No RFC 3339 time is invented: issue and release dates are dates.
    for path, data in files.items():
        check(DATE_TIME.search(data.decode("utf-8")) is None, f"{path} holds no date-time")
    for row in payloads["result_r2"]["rows"]:
        check(row["issue_date_precision"] == "date-only" and comuvia.is_marker(row["information_set"]), "date-only, unknown information set")
    check(payloads["result_r2"]["foreglass"]["state"] == "unavailable", "ForeGlass is unavailable, not substituted")

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("Tutorial H passed:", json.dumps(out))


if __name__ == "__main__":
    main()
