"""Tutorial A: a source-linked statement, honestly excluded.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_a_narrative.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

Every value the tutorial states is checked; the script exits non-zero if one differs.
"""

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

import comuvia
from comuvia import RecordStore


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL A CHECK FAILED: {message}")


def cli(*args):
    """Run the installed command line; return (exit code, JSON output)."""
    result = subprocess.run([sys.executable, "-I", "-m", "comuvia", "--json", *args], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture = Path(args.fixtures) / "narrative-conditional"
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    out = {"tutorial": "A", "comuvia": comuvia.__version__}

    def record(name):
        return comuvia.load_record((fixture / "records" / f"{name}.json").read_bytes())

    # 1. Retain the transcript's exact bytes as a snapshot.
    transcript_path = fixture / "source" / "harbor-weekly-e42-transcript.txt"
    transcript = transcript_path.read_bytes()
    snapshot = record("res-harbor-weekly-e42-transcript")
    identity = comuvia.verify(snapshot, content=transcript)
    check(identity.content_identity == "match", "transcript bytes match the snapshot")
    check(identity.timestamp_assurance == "unavailable", "timestamp assurance is unavailable")
    out["transcript"] = {
        "byte_length": len(transcript),
        "content_digest": comuvia.content_digest(transcript),
        "content_identity": identity.content_identity,
        "timestamp_assurance": identity.timestamp_assurance,
    }
    check(out["transcript"]["byte_length"] == 530, "530 bytes")

    # 2. The verbatim assertion, checked against the bytes; a paraphrase marked verbatim fails.
    assertion = record("asr-harbor-weekly-e42-ilsley-freight")
    selectors = comuvia.check_selector(assertion, transcript, snapshot=snapshot)
    check(selectors.result == "match", "the verbatim quote and its selectors match the bytes")
    paraphrase = copy.deepcopy(assertion)
    paraphrase["quote"]["exact"] = "Freight problems may get worse next winter if the canal shuts."
    paraphrase["selector"]["text_quote"] = {"unknown": "paraphrase_has_no_exact_text"}
    paraphrase["selector"]["text_position"] = {"unknown": "paraphrase_has_no_exact_text"}
    wrong = comuvia.check_selector(paraphrase, transcript)
    check(wrong.result == "mismatch" and [i.code for i in wrong.issues] == ["quote_mismatch"],
          "a paraphrase marked verbatim gives quote_mismatch")
    out["selectors"] = {"verbatim": selectors.result, "checked": list(selectors.checked),
                        "paraphrase_marked_verbatim": [i.code for i in wrong.issues]}

    # 3. The analyst's interpretation is a separate record with its own author and time.
    interpretation = record("int-ilsley-freight-analyst-1")
    check(interpretation["author"] == "analyst:example-analyst-1", "the analyst is the author")
    check(interpretation["author"] != assertion["recorded_by"], "the speaker's record is not the interpretation")
    check(interpretation["recorded_at"] > assertion["recorded_at"], "the interpretation is later")
    out["interpretation"] = {"author": interpretation["author"], "status": interpretation["status"],
                             "frozen_at": interpretation["frozen_at"],
                             "extraction_confidence_is_probability": False}

    # 4. Store all three records (append-only, single writer).
    store = work / "store-a"
    RecordStore.create(store)
    with RecordStore(store, writer=True) as writer:
        for body in (snapshot, assertion, interpretation):
            writer.append(body)
    check(RecordStore(store).verify().ok, "store verify is OK")

    # 5. Evaluate: both candidates are excluded by name; 0.85 is never a probability.
    report = comuvia.evaluate(RecordStore(store).records())
    reasons = {r.record["id"]: list(r.reasons) for r in report.results}
    check(report.counts["candidates"] == 2 and report.counts["excluded"] == 2 and report.counts["eligible"] == 0,
          "2 candidates, 2 excluded, 0 eligible")
    check(reasons["asr-harbor-weekly-e42-ilsley-freight"] == ["no_declared_probability", "conditional_scenario", "no_pinned_question"],
          "assertion reasons")
    check(reasons["int-ilsley-freight-analyst-1"] == ["not_a_forecast", "conditional_scenario"], "interpretation reasons")
    report_json = json.dumps(report.as_json())
    check("0.85" not in report_json, "0.85 appears nowhere in the evaluation report")
    out["evaluation"] = {"counts": report.counts, "reasons": reasons, "aggregate": report.as_json()["aggregate"]}

    # 6. The same through the command line.
    code, verified = cli("store", "verify", str(store))
    check(code == 0 and verified["ok"], "comuvia store verify")
    code, evaluated = cli("evaluate", "--store", str(store))
    check(code == 0 and evaluated["counts"]["excluded"] == 2 and evaluated["aggregate"] is None, "comuvia evaluate")
    code, checked = cli("verify", str(fixture / "records" / "asr-harbor-weekly-e42-ilsley-freight.json"),
                        "--content", str(transcript_path), "--store", str(store))
    check(code == 0 and checked["selector"]["result"] == "match", "comuvia verify --content")
    out["cli"] = {"store_verify": verified["ok"], "evaluate_excluded": evaluated["counts"]["excluded"],
                  "verify_selector": checked["selector"]["result"], "scope": verified["scope"]}

    out["not_proven"] = [
        "timestamp assurance is unavailable: no time value is independently verified",
        "a hash proves byte identity only, not truth, authorship or publication",
        "one example says nothing about predictive skill",
    ]
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print("Tutorial A passed: every stated value was reproduced.")
        print(json.dumps(out["evaluation"], indent=2))


if __name__ == "__main__":
    main()
