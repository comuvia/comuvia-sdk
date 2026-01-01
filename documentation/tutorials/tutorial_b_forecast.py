"""Tutorial B: a declared-probability forecast, its outcome and a correction.

Runs offline against an installed comuvia wheel and the repository fixtures:

    python tutorial_b_forecast.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

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

EVALUATED = {"evaluated_at": "2027-02-17T00:00:00Z", "recorded_by": "evaluator:tutorial-b",
             "recorded_at": "2027-02-17T00:00:00Z"}


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL B CHECK FAILED: {message}")


def cli(*args):
    result = subprocess.run([sys.executable, "-I", "-m", "comuvia", "--json", *args], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None


def display(loss):
    """Two decimal places, rounded half to even on the exact binary64 value (Python's format)."""
    return f"{loss:.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture = Path(args.fixtures) / "structured-binary"
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    out = {"tutorial": "B", "comuvia": comuvia.__version__}

    names = ["q-port-calder-teu-2027-01", "fc-lantern-port-calder-teu-2027-01",
             "res-port-calder-bulletin-2027-01-first", "out-port-calder-teu-2027-01"]
    bodies = {n: comuvia.load_record((fixture / "records" / f"{n}.json").read_bytes()) for n in names}
    bulletin = (fixture / "source" / "port-calder-bulletin-2027-01.csv").read_bytes()
    check(comuvia.verify(bodies[names[2]], content=bulletin).content_identity == "match", "bulletin bytes match")

    # 1. Question, forecast, bulletin snapshot and outcome, stored.
    store = work / "store-b"
    RecordStore.create(store)
    with RecordStore(store, writer=True) as writer:
        for name in names:
            writer.append(bodies[name])

        # 2. Evaluate: loss 0.09000000000000002, displayed as 0.09.
        records = writer.records()
        report = comuvia.evaluate(records)
        (result,) = report.results
        check(result.status == "scored" and json.dumps(result.loss) == "0.09000000000000002", "loss 0.09000000000000002")
        check(display(result.loss) == "0.09", "displayed as 0.09")
        (first,) = comuvia.evaluation_records(report, records, **EVALUATED)
        writer.append(first)

        # 3. Reproduce the stored evaluation from its pinned inputs.
        check(comuvia.reproduce(first, writer.records()).result == "match", "reproduce gives match")

        # 4. Correct a recording error: outcome revision 2 with resolved_value 0.
        outcome_r1 = bodies["out-port-calder-teu-2027-01"]
        r1_file = store / "records" / (comuvia.record_digest(outcome_r1).removeprefix("sha256:") + ".json")
        r1_bytes = r1_file.read_bytes()
        correction = copy.deepcopy(outcome_r1)
        correction.update(revision=2, predecessor=comuvia.reference_to(outcome_r1), resolved_value=0,
                          recorded_at="2027-02-20T10:00:00Z")
        writer.append(correction)
        records = writer.records()
        corrected = comuvia.evaluate(records)
        (result2,) = corrected.results
        check(json.dumps(result2.loss) == "0.48999999999999994" and display(result2.loss) == "0.49", "new loss 0.48999999999999994")
        for body in comuvia.evaluation_records(corrected, records, **EVALUATED):
            writer.append(body)

    reader = RecordStore(store)
    check(r1_file.read_bytes() == r1_bytes, "the r1 outcome bytes are unchanged")
    check(comuvia.reproduce(first, reader.records()).result == "match", "the r1 evaluation still reproduces")
    check(reader.latest()[("outcome", "out-port-calder-teu-2027-01")]["revision"] == 2, "the latest view shows r2")
    report_verify = reader.verify()
    check(report_verify.ok, "store verify is OK")
    out["evaluation"] = {
        "first": {"loss": result.loss, "display": display(result.loss)},
        "after_correction": {"loss": result2.loss, "display": display(result2.loss)},
        "display_rounding": "2 decimal places, round half to even on the exact binary64 value",
        "r1_bytes_unchanged": True,
        "r1_evaluation_reproduces": True,
        "latest_outcome_revision": 2,
        "aggregate": None,
    }

    # 5. The same through the command line (a second, fresh store).
    cli_store = str(work / "store-b-cli")
    check(cli("store", "init", cli_store)[0] == 0, "comuvia store init")
    check(cli("store", "append", cli_store, *[str(fixture / "records" / f"{n}.json") for n in names])[0] == 0, "comuvia store append")
    code, evaluated = cli("evaluate", "--store", cli_store, "--append", "--evaluated-at", EVALUATED["evaluated_at"],
                          "--recorded-by", EVALUATED["recorded_by"], "--recorded-at", EVALUATED["recorded_at"])
    check(code == 0 and json.dumps(evaluated["results"][0]["loss"]) == "0.09000000000000002", "comuvia evaluate --append")
    code, reproduced = cli("reproduce", "--store", cli_store)
    check(code == 0 and [r["result"] for r in reproduced["results"]] == ["match"], "comuvia reproduce")
    code, verified = cli("store", "verify", cli_store)
    check(code == 0 and verified["ok"] and "reproduce" in verified["scope"], "comuvia store verify states its scope")
    out["cli"] = {"loss": evaluated["results"][0]["loss"], "reproduce": reproduced["results"][0]["result"],
                  "store_verify": verified["ok"], "scope": verified["scope"]}

    out["not_proven"] = [
        "timestamp assurance is unavailable: issued_at is declared by the provider",
        "store verify checks identity and references, not whether an evaluation is correct; reproduce does that",
        "one forecast and one outcome say nothing about predictive skill",
    ]
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print("Tutorial B passed: every stated value was reproduced.")
        print(json.dumps(out["evaluation"], indent=2))


if __name__ == "__main__":
    main()
