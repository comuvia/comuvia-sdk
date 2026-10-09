"""Tutorial G: a review bound to an exact edition.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_g_edition_review.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

It uses the example helpers beside this file (``edition_review.py``, ``record_authoring.py`` and
``dependency_profile.py``; none is part of the comuvia package). Every value the tutorial states
is checked; the script exits non-zero if one differs. Every approval in the fixture is FICTIONAL.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the helpers; package_smoke runs this with -I

import comuvia  # noqa: E402
import dependency_profile as dp  # noqa: E402
import edition_review as er  # noqa: E402
import record_authoring as ra  # noqa: E402


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL G CHECK FAILED: {message}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture = Path(args.fixtures) / "edition-review"
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))
    records = [comuvia.load_record(p.read_bytes()) for p in sorted((fixture / "records").glob("*.json"))]
    files = {comuvia.content_digest(p.read_bytes()): p.read_bytes() for p in sorted((fixture / "artifacts").iterdir())}
    contents = {er.key_of(b): files[b["content"]["digest"]] for b in records}
    by = {(b["id"], b["revision"]): b for b in records}
    result1, result2 = by[("res-calder-fee-2026", 1)], by[("res-calder-fee-2026", 2)]
    article1 = by[("article-calder-fees", 1)]
    review1, review1_r2 = by[("review-calder-fees-edition-1", 1)], by[("review-calder-fees-edition-1", 2)]
    review2 = by[("review-calder-fees-edition-2", 1)]
    later_keys = {("res-calder-fee-2026", 2), ("claims-calder-fees", 2), ("article-calder-fees", 2),
                  ("summary-calder-fees", 2), ("review-calder-fees-edition-2", 1)}
    earlier = [b for b in records if (b["id"], b["revision"]) not in later_keys]
    later = [b for b in records if (b["id"], b["revision"]) in later_keys]
    out = {"records": len(records)}
    check(len(records) == 13 and len(earlier) == 8 and len(later) == 5, "13 records: 8 earlier, 5 later")

    def members(review):
        return json.loads(contents[er.key_of(review)])["members"]

    def status(review, bundle=records, mapping=contents, **kw):
        return er.review_status(review, bundle, mapping, **kw)

    def redescribe(body, change):
        obj = comuvia.parse_json(contents[er.key_of(body)])
        change(obj)
        data = comuvia.canonicalize(obj)
        new = copy.deepcopy(body)
        new["content"] = ra.descriptor_content(data, "application/json")
        return new, data

    # 1. The bundle is clean.
    check(dp.check_bundle(records, contents) == [], "the dependency profile reports no issue")
    for body in records:
        check(comuvia.validate(body) == [], f"{body['id']} validates")
        result = comuvia.verify(body, content=contents[er.key_of(body)], records=records)
        check(result.content_identity == "match" and all(r.result == "match" for r in result.references), f"{body['id']} identity")

    # 2. Pending and approved (edition 1, before any correction).
    pending = status(review1, earlier, destination="local-review-page")
    check(pending["state"] == "current" and not pending["covers"] and pending["covers_reasons"] == ["decision_pending"],
          "a pending review is current but covers nothing")
    local = status(review1_r2, earlier, current_members=members(review1_r2), destination="local-review-page")
    check(local["state"] == "current" and local["covers"] and local["covers_reasons"] == [], "approved for the local review page")
    public = status(review1_r2, earlier, current_members=members(review1_r2), destination="public-site")
    check(not public["covers"] and public["covers_reasons"] == ["destination_not_approved"], "not approved for the public site")
    check(status(review1_r2, earlier)["covers_reasons"] == ["no_destination"], "covers needs a destination")
    stored = expected["review_status"]
    check(stored["edition_1_pending"] == pending and stored["edition_1_approved_local"] == local
          and stored["edition_1_approved_public"] == public, "expected.json")

    # 3. Case 1: a changed material artifact makes the review stale.
    case1 = status(review1_r2, current_members=members(review2), destination="local-review-page")
    check(case1["state"] == "stale" and case1["reasons"] == ["member_superseded", "summary_superseded", "edition_members_changed"],
          "edition 1 is stale against edition 2")
    check(not case1["covers"] and case1["covers_reasons"] == ["not_current"], "a stale review covers nothing")
    check([(m["role"], m["state"]) for m in case1["members"]] == [("article", "superseded"), ("captions", "match"),
                                                                  ("claim_map", "superseded")], "member states")
    edition2 = status(review2, current_members=members(review2), destination="local-review-page")
    check(edition2["state"] == "current" and edition2["status"] == "pending", "edition 2 is current and pending")
    check(stored["case_1_edition_1_against_edition_2"] == case1 and stored["case_1_edition_2"] == edition2, "expected.json")

    # 4. Case 2: a correction preserves prior evidence.
    impact = {(e["record"]["id"], e["record"]["revision"]): e for e in dp.impact(records, result2)["records"]}
    for name in ("claims-calder-fees", "article-calder-fees"):
        check(impact[(name, 1)]["status"] == "affected" and impact[(name, 1)]["latest_status"] == "unaffected", f"{name} r1 affected, corrected")
    for name, revision in (("contribution-calder-fees-draft", 1), ("review-calder-fees-edition-1", 1),
                           ("review-calder-fees-edition-1", 2), ("review-calder-fees-edition-2", 1)):
        check(impact[(name, revision)]["status"] != "affected", f"{name} r{revision} carries no derivation edge")
    check("member_affected" in status(review1_r2, changed=result2)["reasons"], "the correction reaches edition 1's members")
    comuvia.RecordStore.create(work / "store")
    with comuvia.RecordStore(work / "store", writer=True) as store:
        for body in sorted(earlier, key=lambda b: (b["revision"], b["id"])):
            store.append(body)
        before = {er.key_of(b): comuvia.record_digest(store.get(*er.key_of(b))) for b in earlier}
        for body in sorted(later, key=lambda b: b["content_schema"] == er.REVIEW):
            store.append(body)
        check(all(comuvia.record_digest(store.get(*k)) == d for k, d in before.items()), "the 8 earlier records keep their digests")
        check(store.verify().ok, "store verify is ok")
    check(status(review1_r2)["state"] != "broken", "edition 1's review stays intact")

    # 5. No materiality judgment: one character still makes the review stale.
    one_char = ra.revise(article1, recorded_by="recorder:example-edition-review", recorded_at="2027-02-04T10:00:00Z",
                         replace={"content": ra.descriptor_content(contents[er.key_of(article1)].replace(b"1,840", b"1,841"),
                                                                    "text/markdown; charset=utf-8")})
    mapping = {**contents, er.key_of(one_char): contents[er.key_of(article1)].replace(b"1,840", b"1,841")}
    small = status(review1_r2, earlier + [one_char], mapping)
    check(small["state"] == "stale" and small["reasons"] == ["member_superseded"], "a one-character edition is still a new edition")
    check([m["state"] for m in small["members"] if m["role"] == "article"] == ["superseded"], "the member entry reports it")

    # 6. Broken pins.
    altered = dict(contents)
    altered[er.key_of(article1)] = contents[er.key_of(article1)] + b" "
    check(status(review1_r2, earlier, altered)["reasons"] == ["member_bytes_changed"], "altered article bytes")
    check(status(review1_r2, [b for b in earlier if b["id"] != "captions-calder-fees"])["reasons"] == ["member_missing"],
          "a removed member")
    altered = dict(contents)
    summary1 = by[("summary-calder-fees", 1)]
    altered[er.key_of(summary1)] = contents[er.key_of(summary1)] + b"x"
    broken = status(review1_r2, earlier, altered)
    check(broken["state"] == "broken" and broken["reasons"] == ["summary_bytes_changed"], "altered summary bytes")

    # 7. Each invalid reason once.
    marker = {"unknown": "no_decision_yet"}
    invalid = {
        "pending_has_decision": (review1, lambda o: o.update(decided_by="fixture:fictional-reviewer")),
        "decision_incomplete": (review1_r2, lambda o: o.update(decided_at=marker)),
        "unsupported_authentication": (review1_r2, lambda o: o.update(authentication="signed")),
        "fixture_flag_conflict": (review1_r2, lambda o: o.update(fixture=False)),
        "fixture_not_labelled": (review1_r2, lambda o: o.update(decided_by="Owner")),
    }
    for code, (review, change) in invalid.items():
        new, data = redescribe(review, change)
        report = status(new, earlier, {**contents, er.key_of(new): data})
        check(report["state"] == "invalid" and report["reasons"] == [code], f"{code}")
    for label, change in (("unsorted members", lambda o: o["members"].reverse()),
                          ("duplicate roles", lambda o: o["members"].__setitem__(1, {**o["members"][1], "role": "article"})),
                          ("empty members", lambda o: o.update(members=[]))):
        new, data = redescribe(review1_r2, change)
        check(status(new, earlier, {**contents, er.key_of(new): data})["reasons"] == ["malformed_review"], label)
    altered = {**contents, er.key_of(review1_r2): contents[er.key_of(review1_r2)] + b" "}
    check(status(review1_r2, earlier, altered)["reasons"] == ["content_digest_mismatch"], "altered review bytes")
    out["invalid_reasons"] = len(invalid) + 2

    # 8. Every decided review is labelled fictional.
    for body in records:
        if body["content_schema"] == er.REVIEW:
            obj = json.loads(contents[er.key_of(body)])
            if obj["status"] != "pending":
                check(obj["fixture"] is True and body["data_origin"] == "synthetic" and obj["decided_by"].startswith("fixture:"),
                      f"{body['id']} r{body['revision']} is labelled fictional")
            else:
                check(comuvia.is_marker(obj["decided_by"]) and comuvia.is_marker(obj["decided_at"]), "pending has no decision")

    # 9. Contributions: a historical reference, not a derivation.
    contribution = by[("contribution-calder-fees-draft", 1)]
    content = {"record_type": contribution["record_type"], "id": contribution["id"], "revision": contribution["revision"],
               "content": json.loads(contents[er.key_of(contribution)])}  # the contribution's own content, with its identity
    stale = [(s["pin"]["id"], s["pin"]["revision"], s["state"]) for s in ra.stale_pins(records + [content])
             if s["record"]["id"] == contribution["id"]]
    check(("article-calder-fees", 1, "superseded") in stale, "the contribution's pin to article r1 is superseded, and stays true")
    check(impact[("contribution-calder-fees-draft", 1)]["status"] == "unaffected", "impact does not flag the contribution")

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("Tutorial G passed:", json.dumps(out))


if __name__ == "__main__":
    main()
