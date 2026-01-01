"""Tutorial C: reading ForeGlass honestly.

Runs offline against installed comuvia and foreglass wheels and the repository's synthetic
ForeGlass-format fixture:

    python tutorial_c_foreglass.py --fixtures <repo>/fixtures/synthetic --work <empty directory>

Every value the tutorial states is checked; the script exits non-zero if one differs.
The live read is opt-in (``--live``): it makes explicit network requests to the public
ForeGlass site and is never run unless asked.
"""

import argparse
import datetime
import json
from pathlib import Path

import comuvia
import foreglass
from comuvia import RecordStore

RECORDED_AT = "2026-09-21T00:00:00Z"


def check(condition, message):
    if not condition:
        raise SystemExit(f"TUTORIAL C CHECK FAILED: {message}")


def replay(fixture: Path, work: Path) -> dict:
    out = {}
    files = {
        "ledger": (fixture / "source" / "ledger.json").read_bytes(),
        "ledger_ots": (fixture / "source" / "ledger.json.ots").read_bytes(),
        "archive_index": (fixture / "source" / "ledger-archive-index.json").read_bytes(),
        "fragility_latest": (fixture / "source" / "fragility-latest.json").read_bytes(),
    }
    roles = list(files)

    # 1. Intake: exact bytes verified and retained; a replay is never the accepted live snapshot.
    archive = foreglass.SnapshotArchive.create(work / "snapshots")
    result = archive.intake(foreglass.replay_bundle(files), declared_roles=roles)
    check(result.verified and not result.accepted, "the replay verifies but is not accepted")
    check([i.code for i in result.issues] == ["replay_not_accepted"], "named replay_not_accepted")
    check(archive.accepted() is None, "no accepted live snapshot exists")
    snapshot = archive.load(result.snapshot_id)
    check(snapshot.artifacts["ledger"].data == files["ledger"], "ledger bytes retained exactly (CRLF included)")
    out["intake"] = {"verified": result.verified, "accepted": result.accepted,
                     "drift": sorted({(f.code, f.field) for f in result.findings})}

    # 2. The lane catalog keeps each field's declared meaning.
    catalog = foreglass.LaneCatalog.from_bytes(files["ledger"])
    check(catalog.counts_by_kind() == {"binary": 9, "interval": 2, "point": 1}, "12 lanes by kind")
    span = catalog.select(kind="interval", arm="engine")[0]
    check(span.val == span.hi and span.coverage_level == {"unknown": "provider_declares_no_coverage_level"},
          "an engine interval is a scenario span with unknown coverage")
    check(span.declared_probability is None, "an interval lane has no declared probability")
    truncated = [l.id for l in catalog.lanes if any(l.possibly_truncated.values())]
    check(len(truncated) == 2, "two lanes sit exactly at the provider's cut lengths")
    check("not a publication time" in foreglass.FIELD_MEANINGS["built"], "built is a build date")
    reading = foreglass.read_reading(files["fragility_latest"])
    check(reading.is_forecast is False and reading.probability is None, "a reading is not a probability")
    out["catalog"] = {"by_kind": catalog.counts_by_kind(), "built": catalog.built,
                      "possibly_truncated_lanes": truncated, "reading_is_forecast": reading.is_forecast}

    # 3. Normalization maps only what is declared, and names everything else.
    normalized = foreglass.normalize(snapshot, recorded_at=RECORDED_AT)
    report = normalized.report
    check(report["mapped"]["questions"] == 7 and report["mapped"]["forecasts"] == 8, "7 questions, 8 forecasts")
    check({k: len(v) for k, v in report["not_mapped"].items()} == {"no_pinned_question": 1, "unsupported_output_kind": 3},
          "interval and point lanes are not scored; a blank qid gets no identity")
    snapshots = [r for r in normalized.records if r["record_type"] == "resource_snapshot"]
    check(all(r["source_published_at"] == {"unknown": "source_declares_build_date_only"} for r in snapshots),
          "built never becomes source_published_at")
    check({r["data_origin"] for r in normalized.records} == {"synthetic"}, "replayed records are synthetic")
    out["normalization"] = {"mapped": {"questions": 7, "forecasts": 8}, "not_mapped": report["not_mapped"]}

    # 4. Evaluation: 0 eligible, every reason named.
    counts = report["evaluation"]["counts"]
    check(counts["eligible"] == 0 and counts["excluded"] == 8, "0 eligible, 8 excluded")
    for item in report["evaluation"]["results"]:
        check("missing_required_time" in item["reasons"] and "incomplete_question" in item["reasons"],
              "no information cutoff and no pinned deadlines: every forecast is excluded by name")
    out["evaluation"] = {"counts": counts, "reasons": {r["forecast"]: r["reasons"] for r in report["evaluation"]["results"]}}

    # 5. Store the records; the store verifies.
    store = work / "store-c"
    RecordStore.create(store)
    with RecordStore(store, writer=True) as writer:
        for record in normalized.records:
            writer.append(record)
    check(RecordStore(store).verify().ok, "store verify is OK")
    out["store"] = {"records": len(normalized.records), "verify_ok": True}
    return out


def live(work: Path) -> dict:
    """Opt-in: explicit reads of the public artifacts, retained outside the repository."""
    client = foreglass.PublicClient()
    roles = ["ledger", "archive_index"]
    bundle = client.fetch_bundle(roles)
    archive = foreglass.SnapshotArchive.create(work / "live-snapshots")
    result = archive.intake(bundle, declared_roles=roles)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = foreglass.normalize(archive.accepted(), recorded_at=now).report if result.accepted else None
    return {
        "reads": {r: {"url": a.final_url, "status": a.status, "bytes": a.byte_length, "sha256": a.sha256}
                  for r, a in bundle.items()},
        "accepted": result.accepted,
        "issues": [i.code for i in result.issues],
        "mapped": report and report["mapped"],
        "evaluation": report and report["evaluation"]["counts"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--live", action="store_true", help="also read the public artifacts (network)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    out = {"tutorial": "C", "comuvia": comuvia.__version__, "foreglass": foreglass.__version__}
    out.update(replay(Path(args.fixtures) / "foreglass-ledger", work))
    if args.live:
        out["live"] = live(work)
    out["stated"] = [
        "interval and point lanes are not scored in 0.1",
        "a reading is not a probability",
        "built is a build date, not a publication time",
        "under the current public shape no lane is eligible: there is no information cutoff",
    ]
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True, default=list))
    else:
        print("Tutorial C passed: every stated value was reproduced.")
        print(json.dumps(out["evaluation"]["counts"], indent=2))


if __name__ == "__main__":
    main()
