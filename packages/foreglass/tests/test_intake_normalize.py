"""Intake, lane catalog and normalization against the synthetic ForeGlass-format fixture."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import comuvia
from comuvia import RecordStore

import foreglass
from foreglass import Artifact, LaneCatalog, SnapshotArchive, normalize, read_reading, replay_bundle
from foreglass.normalize import EXTENSION, question_id

FIXTURE = Path(__file__).resolve().parent / "vectors" / "foreglass-ledger"
EXPECTED = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
FILES = {
    "ledger": (FIXTURE / "source" / "ledger.json").read_bytes(),
    "ledger_ots": (FIXTURE / "source" / "ledger.json.ots").read_bytes(),
    "archive_index": (FIXTURE / "source" / "ledger-archive-index.json").read_bytes(),
    "fragility_latest": (FIXTURE / "source" / "fragility-latest.json").read_bytes(),
}
ROLES = ("ledger", "ledger_ots", "archive_index", "fragility_latest")
RECORDED_AT = "2026-09-21T00:00:00Z"


def live(files=FILES):
    """Artifacts shaped like live reads (observed), built from fixture bytes for offline tests."""
    return {
        role: Artifact(role, data, f"https://foreglass.ai/{role}", f"https://foreglass.ai/{role}", 200,
                       "2026-09-21T00:00:00.000000Z", "application/json")
        for role, data in files.items()
    }


class FixtureFormat(unittest.TestCase):
    def test_ledger_matches_the_public_byte_format(self):
        ledger = FILES["ledger"]
        self.assertEqual((len(ledger), hashlib.sha256(ledger).hexdigest()), (EXPECTED["ledger"]["byte_length"], EXPECTED["ledger"]["sha256"]))
        self.assertTrue(ledger.endswith(b"}\r\n"))
        self.assertEqual(ledger.count(b"\n"), ledger.count(b"\r\n"))
        self.assertTrue(all(byte < 128 for byte in ledger))
        document = comuvia.parse_json(ledger)
        self.assertEqual(list(document), ["_schema", "tier", "built", "registry_schema", "seal", "counts", "lanes", "commitments"])
        self.assertEqual(document["counts"]["included"], len(document["lanes"]))


class Intake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = SnapshotArchive.create(Path(self.tmp.name) / "snapshots")

    def tearDown(self):
        self.tmp.cleanup()

    def accept_baseline(self):
        result = self.archive.intake(live(), declared_roles=ROLES)
        self.assertEqual((result.verified, result.accepted, result.issues), (True, True, ()))
        return result.snapshot_id, (Path(self.tmp.name) / "snapshots" / "accepted.json").read_bytes()

    def test_complete_bundle_is_retained_byte_for_byte(self):
        snapshot_id, _ = self.accept_baseline()
        accepted = self.archive.accepted()
        self.assertEqual(accepted.snapshot_id, snapshot_id)
        for role in ROLES:
            self.assertEqual(accepted.artifacts[role].data, FILES[role], role)
            self.assertEqual(accepted.manifest["roles"][role]["sha256"], "sha256:" + hashlib.sha256(FILES[role]).hexdigest())
        self.assertIn(b"\r\n", accepted.artifacts["ledger"].data)

    def test_failures_leave_the_accepted_snapshot_untouched(self):
        snapshot_id, pointer = self.accept_baseline()
        ledger = FILES["ledger"]
        wrong_schema = ledger.replace(b"foreglass.verification-ledger/v1", b"foreglass.verification-ledger/v2")
        wrong_counts = ledger.replace(b'"included": 12', b'"included": 13')
        self.assertNotEqual(wrong_counts, ledger)
        other_index = FILES["archive_index"].replace(hashlib.sha256(ledger).hexdigest().encode(), b"0" * 64)
        declared_wrong = dict(live())
        declared_wrong["ledger"] = Artifact("ledger", ledger, None, None, 200, None, None, declared_sha256="sha256:" + "0" * 64)
        cases = {
            "parse_refused": (live({**FILES, "ledger": ledger[: len(ledger) // 2]}), ROLES),
            "incomplete_intake": ({k: v for k, v in live().items() if k != "ledger_ots"}, ROLES),
            "schema_mismatch": (live({**FILES, "ledger": wrong_schema}), ROLES),
            "counts_mismatch": (live({**FILES, "ledger": wrong_counts}), ROLES),
            "digest_mismatch": (declared_wrong, ROLES),
            "archive_index_mismatch": (live({**FILES, "archive_index": other_index}), ROLES),
        }
        self.assertEqual(set(cases), set(EXPECTED["intake"].values()) - {"accepted", "verified, never accepted as the live snapshot"})
        for code, (bundle, roles) in cases.items():
            with self.subTest(code):
                result = self.archive.intake(bundle, declared_roles=roles)
                self.assertEqual((result.verified, result.accepted), (False, False))
                self.assertEqual({i.code for i in result.issues}, {code})
                self.assertEqual(self.archive.accepted().snapshot_id, snapshot_id)
                self.assertEqual((Path(self.tmp.name) / "snapshots" / "accepted.json").read_bytes(), pointer)

    def test_replay_is_verified_but_never_accepted(self):
        result = self.archive.intake(replay_bundle(FILES), declared_roles=ROLES)
        self.assertEqual((result.verified, result.accepted), (True, False))
        self.assertEqual({i.code for i in result.issues}, {"replay_not_accepted"})
        self.assertIsNone(self.archive.accepted())
        self.assertEqual(self.archive.load(result.snapshot_id).data_origin, "synthetic")

    def test_retained_snapshot_is_reverified_before_the_pointer_moves(self):
        snapshot_id, pointer = self.accept_baseline()
        retained = Path(self.tmp.name) / "snapshots" / "snapshots" / snapshot_id / "1.bin"
        retained.write_bytes(retained.read_bytes() + b"tampered")
        result = self.archive.intake(live(), declared_roles=ROLES)
        self.assertEqual((result.accepted, {i.code for i in result.issues}), (False, {"digest_mismatch"}))
        self.assertEqual((Path(self.tmp.name) / "snapshots" / "accepted.json").read_bytes(), pointer)

    def test_drift_is_reported_not_fatal(self):
        result = self.archive.intake(live(), declared_roles=ROLES)
        found = [{"lane": f.where.removeprefix("lane:"), "field": f.field, "code": f.code} for f in result.findings]
        self.assertEqual(found, EXPECTED["drift"])

    def test_nesting_limit_applies_to_the_ledger(self):
        deep = b"[" * 70 + b"]" * 70
        result = self.archive.intake(live({**FILES, "ledger": deep}), declared_roles=ROLES)
        self.assertEqual({i.code for i in result.issues}, {"parse_refused"})
        self.assertIn("nesting_too_deep", result.issues[0].message)


class Catalog(unittest.TestCase):
    def test_declared_meanings_and_filters(self):
        catalog = LaneCatalog.from_bytes(FILES["ledger"])
        self.assertEqual(catalog.counts_by_kind(), EXPECTED["lanes"]["by_kind"])
        span = catalog.select(arm="engine", kind="interval")[0]
        self.assertEqual(span.val, span.hi)
        self.assertEqual(span.coverage_level, {"unknown": "provider_declares_no_coverage_level"})
        self.assertIsNone(span.declared_probability)
        rate = catalog.select(metric="lantern_rate_cut")[0]
        self.assertEqual(rate.possibly_truncated, {"statement": False, "criteria": True})
        self.assertEqual(rate.full_unit, "indicator over quarter (event = policy rate cut announced)")
        self.assertEqual(len(catalog.select(caveat_id="outcome-published-before-seal")), 1)
        self.assertEqual(len(catalog.select(due_from="2026-12-01", due_to="2026-12-31")), 4)
        slowdown = catalog.select(metric="lantern_slowdown_2027h1")[0]
        self.assertEqual((slowdown.unit, slowdown.full_unit), ("", None))
        bridge = catalog.select(metric="lantern_bridge_opening")[0]
        self.assertEqual(set(bridge.unknown_fields), {"outcome", "graded_at", "horizon_days"})
        self.assertIn("not a target period", foreglass.FIELD_MEANINGS["due"])

    def test_reading_is_never_a_forecast(self):
        reading = read_reading(FILES["fragility_latest"])
        self.assertEqual((reading.is_forecast, reading.probability), (False, None))
        self.assertTrue(reading.caveats and "not a forecast" in reading.caveats[0])


class Normalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = normalize(live(), recorded_at=RECORDED_AT)
        cls.replay = normalize(replay_bundle(FILES), recorded_at=RECORDED_AT)

    def test_expected_mapping_and_evaluation(self):
        report, expected = self.result.report, EXPECTED
        self.assertEqual(report["lanes"], {"total": expected["lanes"]["count"], "by_kind": expected["lanes"]["by_kind"]})
        self.assertEqual((report["mapped"]["questions"], report["mapped"]["forecasts"]),
                         (expected["mapping"]["questions"], expected["mapping"]["forecasts"]))
        self.assertEqual(sorted(report["mapped"]["lanes"]), sorted(expected["mapping"]["mapped"]))
        not_mapped = {lane: reason for reason, lanes in report["not_mapped"].items() for lane in lanes}
        self.assertEqual(not_mapped, expected["mapping"]["not_mapped"])
        self.assertEqual(report["evaluation"]["counts"], expected["evaluation"]["counts"])
        forecasts = {r["id"]: r for r in self.result.records if r["record_type"] == "forecast"}
        for item in report["evaluation"]["results"]:
            lane = forecasts[item["forecast"]]["extensions"][EXTENSION]["lane_id"]
            self.assertEqual(item["reasons"], expected["evaluation"]["reasons"][lane], lane)
            self.assertEqual(forecasts[item["forecast"]]["limitations"], expected["mapping"]["mapped"][lane]["limitations"], lane)
            if "question_unit" in expected["mapping"]["mapped"][lane]:
                question = next(r for r in self.result.records if r["id"] == forecasts[item["forecast"]]["question"]["id"])
                self.assertEqual(question["unit"], expected["mapping"]["mapped"][lane]["question_unit"])
        self.assertNotIn("malformed_lane", report["not_mapped"])
        families = {forecasts[f]["extensions"][EXTENSION]["lane_id"]: forecasts[f]["forecast_family"] for f in forecasts}
        for group in expected["mapping"]["same_family"]:
            self.assertEqual(len({families[lane] for lane in group}), 1)

    def test_every_record_validates_and_every_reference_verifies(self):
        records = self.result.records
        for record in records:
            self.assertEqual(comuvia.validate(record), [], record["id"])
            check = comuvia.verify(record, records=records)
            self.assertTrue(all(r.result == "match" for r in check.references), record["id"])
        snapshots = [r for r in records if r["record_type"] == "resource_snapshot"]
        for snapshot in snapshots:
            role = snapshot["extensions"][EXTENSION]["role"]
            self.assertEqual(comuvia.verify(snapshot, content=FILES[role]).content_identity, "match")
        with tempfile.TemporaryDirectory() as tmp:
            RecordStore.create(Path(tmp) / "store")
            with RecordStore(Path(tmp) / "store", writer=True) as store:
                for record in records:
                    store.append(record)
            self.assertTrue(RecordStore(Path(tmp) / "store").verify().ok)

    def test_what_never_happens(self):
        records = self.result.records
        forecasts = [r for r in records if r["record_type"] == "forecast"]
        catalog = LaneCatalog.from_bytes(FILES["ledger"])
        lanes = {lane.id: lane for lane in catalog.lanes}
        mapped_lanes = {f["extensions"][EXTENSION]["lane_id"] for f in forecasts}
        self.assertFalse({l for l in mapped_lanes if lanes[l].kind != "binary"}, "interval or point lane became a forecast")
        for forecast in forecasts:
            lane = lanes[forecast["extensions"][EXTENSION]["lane_id"]]
            self.assertEqual(forecast["output"]["probability"], lane.val)
            self.assertNotIn(forecast["output"]["probability"], {lane.lo, lane.hi, lane.raw.get("naive_value")} - {lane.val})
            self.assertEqual(forecast["issued_at"], {"date": lane.sealed_at, "precision": "day"})
            self.assertEqual(forecast["information_cutoff"], {"unknown": "provider_declares_no_information_cutoff"})
        text = json.dumps([r for r in records if r["record_type"] != "resource_snapshot"])
        self.assertNotIn("coverage_level", text)
        for snapshot in (r for r in records if r["record_type"] == "resource_snapshot"):
            self.assertEqual(snapshot["source_published_at"], {"unknown": "source_declares_build_date_only"})
        blank = [l for l in catalog.lanes if not l.qid]
        self.assertTrue(blank)
        self.assertFalse({l.id for l in blank} & mapped_lanes)
        reading_value = read_reading(FILES["fragility_latest"]).reading
        self.assertNotIn(reading_value, [f["output"]["probability"] for f in forecasts])

    def test_core_refusal_is_an_internal_error_not_a_lane_label(self):
        import sys

        module = sys.modules["foreglass.normalize"]  # the package attribute is the function
        original = module._question
        try:
            module._question = lambda *args: {**original(*args), "unit": ""}
            with self.assertRaises(foreglass.NormalizationError):
                normalize(live(), recorded_at=RECORDED_AT)
        finally:
            module._question = original

    def test_identity_derivations(self):
        self.assertEqual(question_id("q:harbor_berth_closure@2026-12-15"), "fg:q:harbor_5fberth_5fclosure_402026-12-15")
        self.assertNotEqual(foreglass.encode_identifier("a_40"), foreglass.encode_identifier("a@"))
        for record in self.result.records:
            if record["record_type"] == "question":
                self.assertEqual(record["id"], question_id(record["extensions"][EXTENSION]["qid"]))

    def test_data_origin_follows_the_source(self):
        self.assertEqual({r["data_origin"] for r in self.result.records}, {"observed"})
        self.assertEqual({r["data_origin"] for r in self.replay.records}, {"synthetic"})
        self.assertEqual(self.replay.report["evaluation"]["counts"]["eligible"], 0)


if __name__ == "__main__":
    unittest.main()
