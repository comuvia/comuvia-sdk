"""Tutorial J: packaged profiles, selection-aware impact and whole-bundle verification.

Runs offline against an installed comuvia wheel (using zero external tutorial helper
modules) and the repository fixtures:

    python tutorial_j_bundle_and_selection.py --fixtures <repo>/fixtures/synthetic --work <empty directory>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import comuvia
from comuvia.cli import main as cli_main
from comuvia.profiles import dependencies as dp
from comuvia.profiles import edition_review as er


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"TUTORIAL J CHECK FAILED: {message}")


def _load_fixture_records_and_contents(fixture: Path) -> tuple[list[dict], dict[tuple, bytes]]:
    records = [comuvia.load_record(p.read_bytes()) for p in sorted((fixture / "records").glob("*.json"))]
    by_digest: dict[str, bytes] = {}
    for sub in ("source", "artifacts"):
        folder = fixture / sub
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                raw = path.read_bytes()
                by_digest[comuvia.content_digest(raw)] = raw
    contents = {
        dp.key_of(b): by_digest[b["content"]["digest"]]
        for b in records
        if isinstance(b.get("content"), dict) and isinstance(b["content"].get("digest"), str)
        and b["content"]["digest"] in by_digest
    }
    return records, contents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", required=True, help="path to fixtures/synthetic")
    parser.add_argument("--work", required=True, help="an empty working directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    fixtures = Path(args.fixtures)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    # 1. Exact parity with Tutorials D, G and H using only packaged comuvia modules.
    d_records, d_contents = _load_fixture_records_and_contents(fixtures / "dependency-correction")
    d_expected = json.loads((fixtures / "dependency-correction" / "expected.json").read_text(encoding="utf-8"))
    check(dp.check_bundle(d_records, d_contents) == [], "Tutorial D bundle clean via packaged dependencies")
    src2 = next(b for b in d_records if b["id"] == "src-calder-quarterly" and b["revision"] == 2)
    check(dp.impact(d_records, src2) == d_expected["impact_of_source_correction"],
          "packaged dependencies.impact equals Tutorial D expected.json")

    g_records, g_contents = _load_fixture_records_and_contents(fixtures / "edition-review")
    g_expected = json.loads((fixtures / "edition-review" / "expected.json").read_text(encoding="utf-8"))
    later_keys = {
        ("res-calder-fee-2026", 2),
        ("claims-calder-fees", 2),
        ("article-calder-fees", 2),
        ("summary-calder-fees", 2),
        ("review-calder-fees-edition-2", 1),
    }
    g_earlier = [b for b in g_records if (b["id"], b["revision"]) not in later_keys]
    rev1_r1 = next(b for b in g_records if b["id"] == "review-calder-fees-edition-1" and b["revision"] == 1)
    rev1_r2 = next(b for b in g_records if b["id"] == "review-calder-fees-edition-1" and b["revision"] == 2)
    rev1_members = json.loads(g_contents[er.key_of(rev1_r2)])["members"]
    check(
        er.review_status(rev1_r1, g_earlier, g_contents, destination="local-review-page")
        == g_expected["review_status"]["edition_1_pending"],
        "packaged edition_review pending matches Tutorial G expected.json",
    )
    check(
        er.review_status(rev1_r2, g_earlier, g_contents, current_members=rev1_members, destination="local-review-page")
        == g_expected["review_status"]["edition_1_approved_local"],
        "packaged edition_review approved_local matches Tutorial G expected.json",
    )

    h_fixture = fixtures / "pinned-evaluation"
    h_records, h_contents = _load_fixture_records_and_contents(h_fixture)
    h_expected = json.loads((h_fixture / "expected.json").read_text(encoding="utf-8"))
    h_files = {
        p.relative_to(h_fixture).as_posix(): p.read_bytes()
        for sub in ("source", "artifacts")
        for p in sorted((h_fixture / sub).iterdir())
    }

    def h_locate(loc):
        if isinstance(loc, tuple):
            rec = next((b for b in h_records if dp.key_of(b) == loc), None)
            return comuvia.canonicalize(rec) if rec is not None else None
        return h_files.get(loc)

    res1 = next(b for b in h_records if b["id"] == "result-calder-nowcast" and b["revision"] == 1)
    emb_r1 = comuvia.check_embedded(json.loads(h_contents[dp.key_of(res1)]), h_locate)
    check(emb_r1["ok"] and emb_r1["counts"]["match"] == h_expected["embedded"]["result_r1"]["match"],
          "packaged check_embedded matches Tutorial H expected.json")
    h_exp = comuvia.expectation(h_records)
    without_r2 = [b for b in h_records if not (b["id"] == "result-calder-nowcast" and b["revision"] == 2)]
    check(comuvia.check_expectation(without_r2, h_exp)["tail_removed"] == ["artifact_descriptor/result-calder-nowcast"],
          "packaged check_expectation detects tail_removed")

    # 2. Selection-aware v2 dependency impact, quote locating, media_time and repin.
    meaning = {"measure": "container_teu", "unit": "TEU", "period": "2027", "geography": "SynthHarbor"}
    table_r1_bytes = comuvia.canonicalize({"quarters": {"Q1": "410", "Q2": "425"}, "summary": "Q1 settled at 410 TEU; Q2 preliminary 425 TEU."})
    table_r2_bytes = comuvia.canonicalize({"quarters": {"Q1": "410", "Q2": "432"}, "summary": "Q1 settled at 410 TEU; Q2 revised 432 TEU."})

    src_r1 = comuvia.new_record(
        "resource_snapshot",
        "src-harbor-table",
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-01T09:00:00Z",
        resource_type="dataset",
        locator="https://example.org/harbor/2027.json",
        captured_at="2027-04-01T09:00:00Z",
        source_published_at={"date": "2027-04-01", "precision": "day"},
        source_version="1",
        content=comuvia.snapshot_content(table_r1_bytes, "application/json"),
        language="en",
        captured_assets=["harbor_json"],
        not_captured=[],
        extensions={dp.NAMESPACE_V2: {"value_origin": "observed", "meaning": meaning, "coverage": "complete", "depends_on": []}},
    )
    src_r2 = comuvia.revise(
        src_r1,
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-05T09:00:00Z",
        enforce_monotonic_time=True,
        require_change=True,
        content=comuvia.snapshot_content(table_r2_bytes, "application/json"),
        source_version="2",
    )

    q1_card_bytes = comuvia.canonicalize({"quarter": "Q1", "teu": "410", "table_sha256": hashlib.sha256(table_r1_bytes).hexdigest(), "file": "table-r1.json"})
    q2_card_bytes = comuvia.canonicalize({"quarter": "Q2", "teu": "425"})
    card_q1_r1 = comuvia.new_record(
        "artifact_descriptor",
        "art-card-q1",
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-01T10:00:00Z",
        content=comuvia.descriptor_content(q1_card_bytes, "application/json"),
        content_schema="harbor-card/1",
        origin={"name": "Synthetic Harbor Desk", "locator": "https://example.org/desk"},
        published_at={"date": "2027-04-01", "precision": "day"},
        retrieved_at="2027-04-01T10:00:00Z",
        units=["TEU"],
        rights_reference={"unknown": "synthetic"},
        access="public",
        locator="https://example.org/cards/q1.json",
        extensions={
            dp.NAMESPACE_V2: {
                "value_origin": "derived",
                "meaning": meaning,
                "coverage": "complete",
                "depends_on": [{
                    "role": "data_input",
                    "pin": comuvia.reference_to(src_r1),
                    "selection": {"kind": "json_pointer", "pointer": "/quarters/Q1"},
                }],
            }
        },
    )
    card_q2_r1 = comuvia.new_record(
        "artifact_descriptor",
        "art-card-q2",
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-01T10:05:00Z",
        content=comuvia.descriptor_content(q2_card_bytes, "application/json"),
        content_schema="harbor-card/1",
        origin={"name": "Synthetic Harbor Desk", "locator": "https://example.org/desk"},
        published_at={"date": "2027-04-01", "precision": "day"},
        retrieved_at="2027-04-01T10:05:00Z",
        units=["TEU"],
        rights_reference={"unknown": "synthetic"},
        access="public",
        locator="https://example.org/cards/q2.json",
        extensions={
            dp.NAMESPACE_V2: {
                "value_origin": "derived",
                "meaning": meaning,
                "coverage": "complete",
                "depends_on": [{
                    "role": "data_input",
                    "pin": comuvia.reference_to(src_r1),
                    "selection": {"kind": "json_pointer", "pointer": "/quarters/Q2"},
                }],
            }
        },
    )

    clip_transcript = b"Harbor operations confirmed Q1 settled at 410 TEU with zero berth backlog."
    clip_snap = comuvia.new_record(
        "resource_snapshot",
        "src-harbor-briefing",
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-01T10:10:00Z",
        resource_type="transcript",
        locator="https://example.org/harbor/briefing.txt",
        captured_at="2027-04-01T10:10:00Z",
        source_published_at={"date": "2027-04-01", "precision": "day"},
        source_version="1",
        content=comuvia.snapshot_content(clip_transcript, "text/plain; charset=utf-8"),
        language="en",
        captured_assets=["briefing_txt"],
        not_captured=["video_stream"],
    )
    quote_exact = "Q1 settled at 410 TEU with zero berth backlog"
    asr = comuvia.new_record(
        "source_assertion",
        "asr-harbor-q1",
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-01T10:15:00Z",
        resource=comuvia.reference_to(clip_snap),
        quote={"exact": quote_exact, "verbatim": True, "language": "en", "translation": None},
        selector=comuvia.locate_quote(quote_exact, clip_transcript, media_time={"start_seconds": 4.0, "end_seconds": 9.5}),
        attributed_to={"name": "Synthetic Port Director", "basis": "speech_transcript"},
        assertion_kind="factual_claim",
        stated_probability=None,
    )
    timed_chk = comuvia.check_selector(
        asr,
        clip_transcript,
        snapshot=clip_snap,
        media_duration=15.0,
        timed_segments=[{"start": 3.8, "end": 9.6, "text": "Harbor operations confirmed Q1 settled at 410 TEU with zero berth backlog."}],
    )
    check(timed_chk.result == "match" and "media_time" in timed_chk.checked, "media_time verified against speech segments")

    v2_contents = {
        dp.key_of(src_r1): table_r1_bytes,
        dp.key_of(src_r2): table_r2_bytes,
        dp.key_of(card_q1_r1): q1_card_bytes,
        dp.key_of(card_q2_r1): q2_card_bytes,
        dp.key_of(clip_snap): clip_transcript,
    }
    imp = dp.impact([src_r1, src_r2, card_q1_r1, card_q2_r1], src_r2, contents=v2_contents)
    imp_by_id = {r["record"]["id"]: r for r in imp["records"]}
    check(imp_by_id["art-card-q1"]["selection_status"] == "unchanged", "Q1 slice unchanged across r1 -> r2")
    check(imp_by_id["art-card-q2"]["selection_status"] == "changed", "Q2 slice changed across r1 -> r2")

    # Repin Q1 card onto src_r2 without recomputing Q1's number, and update Q2 card.
    q1_card_r2_bytes = comuvia.canonicalize({"quarter": "Q1", "teu": "410", "table_sha256": hashlib.sha256(table_r2_bytes).hexdigest(), "file": "table-r2.json"})
    card_q1_r2 = comuvia.revise(
        card_q1_r1,
        data_origin="synthetic",
        recorded_by="recorder:tutorial-j",
        recorded_at="2027-04-05T10:00:00Z",
        repin=[(src_r1, src_r2)],
        content=comuvia.descriptor_content(q1_card_r2_bytes, "application/json"),
    )
    check(comuvia.stale_pins([src_r2, card_q1_r2]) == [], "no stale pins on repinned latest set")

    # 3. Store with --profiles and CLI bundle verify.
    store_dir = work / "store"
    comuvia.RecordStore.create(store_dir)
    all_records = [src_r1, src_r2, card_q1_r1, card_q1_r2, card_q2_r1, clip_snap, asr]
    with comuvia.RecordStore(store_dir, writer=True) as store:
        for rec in all_records:
            store.append(rec, check_profiles=True)

    files_dir = work / "files"
    files_dir.mkdir()
    file_entries = {
        "resource_snapshot/src-harbor-table/r1": ("table-r1.json", table_r1_bytes),
        "resource_snapshot/src-harbor-table/r2": ("table-r2.json", table_r2_bytes),
        "artifact_descriptor/art-card-q1/r1": ("card-q1-r1.json", q1_card_bytes),
        "artifact_descriptor/art-card-q1/r2": ("card-q1-r2.json", q1_card_r2_bytes),
        "artifact_descriptor/art-card-q2/r1": ("card-q2-r1.json", q2_card_bytes),
        "resource_snapshot/src-harbor-briefing/r1": ("briefing.txt", clip_transcript),
    }
    cmap = {}
    for rec_key, (fname, data) in file_entries.items():
        (files_dir / fname).write_bytes(data)
        cmap[rec_key] = fname
    cmap_path = files_dir / "content-map.json"
    cmap_path.write_text(json.dumps(cmap, indent=2), encoding="utf-8")
    emap_path = files_dir / "embedded-map.json"
    emap_path.write_text(json.dumps({"table-r1.json": "table-r1.json", "table-r2.json": "table-r2.json"}, indent=2), encoding="utf-8")
    exp_path = work / "expectation.json"

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_exp = cli_main(["--json", "bundle", "expectation", str(store_dir), "--out", str(exp_path)])
    check(rc_exp == 0, "bundle expectation CLI succeeded")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_ver = cli_main([
            "--json",
            "bundle",
            "verify",
            str(store_dir),
            "--content-map", str(cmap_path),
            "--require-content",
            "--check-embedded",
            "--embedded-map", str(emap_path),
            "--expectation", str(exp_path),
        ])
    cli_report = json.loads(buf.getvalue())
    check(rc_ver == 0 and cli_report["ok"] and cli_report["selectors_checked"] == 1, "bundle verify CLI passed")

    rt = comuvia.runtime_identity()
    check(rt["package"] == "comuvia" and rt["version"] == comuvia.__version__, "runtime_identity matches __version__")

    summary = {
        "tutorial": "J",
        "records": len(all_records),
        "selection_statuses": {
            "art-card-q1": imp_by_id["art-card-q1"]["selection_status"],
            "art-card-q2": imp_by_id["art-card-q2"]["selection_status"],
        },
        "cli": {"bundle_verify": cli_report["ok"], "selectors_checked": cli_report["selectors_checked"]},
    }
    if args.json:
        print(json.dumps(summary))
    else:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
