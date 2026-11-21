"""Tests for ``comuvia.bundle`` (verify_bundle, check_embedded, expectation) and new CLI commands."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from comuvia import (
    RecordStore,
    canonicalize,
    check_embedded,
    check_expectation,
    descriptor_content,
    expectation,
    locate_quote,
    new_record,
    preflight,
    reference_to,
    revise,
    snapshot_content,
    verify_bundle,
)
from comuvia.cli import main as cli_main
from comuvia.profiles import dependencies as dp


def _run_cli(*args: str) -> tuple[int, dict | str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli_main(list(args))
    text = buf.getvalue()
    if "--json" in args and text.strip():
        return code, json.loads(text)
    return code, text


class BundleAndCliTest(unittest.TestCase):
    def _build_sample_bundle(self):
        src_bytes = b"Official filing: revenue grew 12 percent in Q4."
        src_r1 = new_record(
            "resource_snapshot",
            "src-filing",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:00:00Z",
            resource_type="filing",
            locator="https://example.org/filing.txt",
            captured_at="2027-01-10T10:00:00Z",
            source_published_at={"date": "2027-01-10", "precision": "day"},
            source_version="1",
            content=snapshot_content(src_bytes, "text/plain; charset=utf-8"),
            language="en",
            captured_assets=["filing_txt"],
            not_captured=[],
            extensions={
                dp.NAMESPACE: {
                    "value_origin": "observed",
                    "meaning": {"measure": "revenue_growth", "unit": "percent", "period": "2026Q4", "geography": "US"},
                    "coverage": "complete",
                    "depends_on": [],
                }
            },
        )
        quote = "revenue grew 12 percent in Q4"
        asr = new_record(
            "source_assertion",
            "asr-filing-rev",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:05:00Z",
            resource=reference_to(src_r1),
            quote={"exact": quote, "verbatim": True, "language": "en", "translation": None},
            selector=locate_quote(quote, src_bytes),
            attributed_to={"name": "Synthetic Corp", "basis": "filing"},
            assertion_kind="factual_claim",
            stated_probability=None,
        )
        art_payload = {
            "source_pin": reference_to(src_r1),
            "source_file": {
                "file": "filing.txt",
                "sha256": hashlib.sha256(src_bytes).hexdigest(),
            },
        }
        art_bytes = canonicalize(art_payload)
        art = new_record(
            "artifact_descriptor",
            "art-summary",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:10:00Z",
            content=descriptor_content(art_bytes, "application/json"),
            content_schema="summary-card/1",
            origin={"name": "Synthetic Analyzer", "locator": "https://example.org/analyzer"},
            published_at={"date": "2027-01-10", "precision": "day"},
            retrieved_at="2027-01-10T10:10:00Z",
            units=["percent"],
            rights_reference={"unknown": "synthetic"},
            access="public",
            locator="https://example.org/summary.json",
            extensions={
                dp.NAMESPACE: {
                    "value_origin": "derived",
                    "meaning": {"measure": "revenue_growth", "unit": "percent", "period": "2026Q4", "geography": "US"},
                    "coverage": "complete",
                    "depends_on": [{"role": "data_input", "pin": reference_to(src_r1), "selection": "revenue line"}],
                }
            },
        )
        return src_r1, src_bytes, asr, art, art_bytes

    def test_check_embedded_and_expectation_edge_cases(self):
        src_r1, src_bytes, asr, art, art_bytes = self._build_sample_bundle()
        payload = {
            "ok_pin": reference_to(src_r1),
            "ok_loc": {"file": "filing.txt", "sha256": hashlib.sha256(src_bytes).hexdigest()},
            "ambig": {"file": "a.txt", "path": "a.txt", "sha256": "0" * 64},
            "bad_hex": {"file": "filing.txt", "sha256": "not-hex"},
            "exempt_loc": {"file": "skip.bin", "sha256": "1" * 64},
        }

        def locate(target):
            if target == ("resource_snapshot", "src-filing", 1):
                return canonicalize(src_r1)
            if target == "filing.txt":
                return src_bytes
            return None

        emb = check_embedded(payload, locate, exempt={"skip.bin": "external_archive"})
        self.assertFalse(emb["ok"])
        self.assertEqual(emb["counts"]["match"], 2)
        self.assertEqual(emb["counts"]["ambiguous"], 1)
        self.assertEqual(emb["counts"]["malformed"], 1)
        self.assertEqual(emb["counts"]["exempt"], 1)

        # Expectation catches tail_removed when r2 is dropped.
        src_r2 = revise(
            src_r1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-11T10:00:00Z",
            source_version="2",
        )
        full_exp = expectation([src_r1, src_r2, asr, art])
        tail_check = check_expectation([src_r1, asr, art], full_exp)
        self.assertFalse(tail_check["ok"])
        self.assertEqual(tail_check["tail_removed"], ["resource_snapshot/src-filing"])
        self.assertEqual(tail_check["missing"], ["resource_snapshot/src-filing/r2"])

        # Preflight catches duplicate keys before comparing.
        dup_pf = preflight([src_r1, src_r1], full_exp)
        self.assertFalse(dup_pf["ok"])
        self.assertEqual(dup_pf["duplicate_keys"], ["resource_snapshot/src-filing/r1"])

    def test_verify_bundle_and_cli_round_trip(self):
        src_r1, src_bytes, asr, art, art_bytes = self._build_sample_bundle()
        contents = {
            ("resource_snapshot", "src-filing", 1): src_bytes,
            ("artifact_descriptor", "art-summary", 1): art_bytes,
        }
        exp = expectation([src_r1, asr, art])

        rep = verify_bundle(
            [src_r1, asr, art],
            contents=contents,
            require_retained_content=True,
            check_selectors=True,
            check_profiles=True,
            check_embedded_pins=True,
            locate_embedded=lambda loc: src_bytes if loc == "filing.txt" else None,
            expectation_manifest=exp,
        )
        self.assertTrue(rep.ok, rep.issues)
        self.assertEqual(rep.records_checked, 3)
        self.assertEqual(rep.contents_checked, 2)
        self.assertEqual(rep.selectors_checked, 1)
        self.assertEqual(rep.embedded_checked, 1)
        self.assertTrue(rep.expectation_checked)

        # Catch re-described altered bytes via embedded digest!
        altered_bytes = b"Official filing: revenue grew 99 percent in Q4."
        redescribed_src = new_record(
            "resource_snapshot",
            "src-filing",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:00:00Z",
            resource_type="filing",
            locator="https://example.org/filing.txt",
            captured_at="2027-01-10T10:00:00Z",
            source_published_at={"date": "2027-01-10", "precision": "day"},
            source_version="1",
            content=snapshot_content(altered_bytes, "text/plain; charset=utf-8"),
            language="en",
            captured_assets=["filing_txt"],
            not_captured=[],
        )
        caught = verify_bundle(
            [redescribed_src, art],
            contents={
                ("resource_snapshot", "src-filing", 1): altered_bytes,
                ("artifact_descriptor", "art-summary", 1): art_bytes,
            },
            check_profiles=False,
            check_embedded_pins=True,
            locate_embedded=lambda loc: altered_bytes if loc == "filing.txt" else None,
        )
        self.assertFalse(caught.ok)
        self.assertIn("embedded_reference_failed", {i.code for i in caught.issues})

        # CLI store --profiles and bundle expectation / verify round-trip.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_dir = root / "store"
            RecordStore.create(store_dir)
            for idx, rec in enumerate((src_r1, asr, art)):
                p = root / f"r{idx}.json"
                p.write_bytes(canonicalize(rec))
                code, _ = _run_cli("--json", "store", "append", "--profiles", str(store_dir), str(p))
                self.assertEqual(code, 0)

            code, sv = _run_cli("--json", "store", "verify", "--profiles", str(store_dir))
            self.assertEqual(code, 0)
            self.assertTrue(sv["ok"])
            self.assertTrue(sv["profiles_checked"])

            (root / "filing.txt").write_bytes(src_bytes)
            (root / "summary.json").write_bytes(art_bytes)
            cmap = root / "content-map.json"
            cmap.write_text(json.dumps({
                "resource_snapshot/src-filing/r1": "filing.txt",
                "artifact_descriptor/art-summary/r1": "summary.json",
            }), encoding="utf-8")
            emap = root / "embedded-map.json"
            emap.write_text(json.dumps({"filing.txt": "filing.txt"}), encoding="utf-8")
            exp_path = root / "expectation.json"

            code, _ = _run_cli("--json", "bundle", "expectation", str(store_dir), "--out", str(exp_path))
            self.assertEqual(code, 0)

            code, bv = _run_cli(
                "--json",
                "bundle",
                "verify",
                str(store_dir),
                "--content-map", str(cmap),
                "--require-content",
                "--check-embedded",
                "--embedded-map", str(emap),
                "--expectation", str(exp_path),
            )
            self.assertEqual(code, 0, bv)
            self.assertTrue(bv["ok"])
            self.assertEqual(bv["records_checked"], 3)
            self.assertEqual(bv["selectors_checked"], 1)

            # D4.3: --embedded-map without --check-embedded still checks embedded references!
            code, bv_auto_emb = _run_cli(
                "--json",
                "bundle",
                "verify",
                str(store_dir),
                "--content-map", str(cmap),
                "--embedded-map", str(emap),
            )
            self.assertEqual(code, 0, bv_auto_emb)
            self.assertEqual(bv_auto_emb["embedded_checked"], 1)

            # D4.1: Path confinement rejects traversal, absolute, UNC and device paths in content-map.
            outside_file = root.parent / "outside-probe.txt"
            sub_dir = root / "sub"
            sub_dir.mkdir()
            for bad_rel in ("../outside.txt", str(outside_file.resolve()), r"\\192.0.2.1\share\x", "CON.json"):
                bad_map = sub_dir / "bad-map.json"
                bad_map.write_text(json.dumps({"resource_snapshot/src-filing/r1": bad_rel}), encoding="utf-8")
                code, res = _run_cli("--json", "bundle", "verify", str(store_dir), "--content-map", str(bad_map))
                self.assertEqual(code, 1)
                self.assertEqual(res["issues"][0]["code"], "invalid_content_input")

            # D4.2: bundle expectation refuses corrupted store and malformed/blank-line JSONL.
            bad_jsonl = root / "bad.jsonl"
            bad_jsonl.write_bytes(canonicalize(src_r1) + b"\n\n" + canonicalize(asr) + b"\n")
            code, _ = _run_cli("--json", "bundle", "expectation", str(bad_jsonl))
            self.assertEqual(code, 1)

            with (store_dir / "index.jsonl").open("ab") as idx_fh:
                idx_fh.write(b'{"torn":')
            code, _ = _run_cli("--json", "bundle", "expectation", str(store_dir))
            self.assertEqual(code, 1)

    def test_d3_bool_as_int_and_malformed_expectation_refusals(self):
        src_r1, src_bytes, asr, art, _ = self._build_sample_bundle()
        r1_pin = reference_to(src_r1)

        # check_embedded rejects bool revision and unhashable record_type without crashing.
        bool_pin_payload = {
            "bool_rev": {**r1_pin, "revision": True},
            "list_rt": {**r1_pin, "record_type": []},
        }
        emb = check_embedded(bool_pin_payload, lambda target: canonicalize(src_r1))
        self.assertFalse(emb["ok"])
        self.assertEqual(emb["counts"]["malformed"], 2)
        self.assertEqual(emb["counts"]["match"], 0)

        # preflight, check_expectation and verify_bundle reject bool revisions and malformed manifests cleanly.
        malformed_manifests = [
            {"entries": [{**r1_pin, "revision": True}], "latest": {}},
            {"entries": [r1_pin], "latest": {"resource_snapshot/src-filing": True}},
            [],
            {"entries": "not-a-list", "latest": {}},
            {"entries": [{"record_type": "resource_snapshot", "id": "src-filing", "revision": 1}], "latest": {}},
        ]
        for bad_exp in malformed_manifests:
            pf = preflight([src_r1], bad_exp)  # type: ignore[arg-type]
            self.assertFalse(pf["ok"], bad_exp)
            ce = check_expectation([src_r1], bad_exp)  # type: ignore[arg-type]
            self.assertFalse(ce["ok"], bad_exp)
            vb = verify_bundle([src_r1], check_profiles=False, expectation_manifest=bad_exp)  # type: ignore[arg-type]
            self.assertFalse(vb.ok, bad_exp)
            self.assertIn("expectation_failed", {i.code for i in vb.issues})


if __name__ == "__main__":
    unittest.main()
