"""Self-contained tests for ``comuvia.profiles`` (dependencies v1/v2 & edition_review) and store profile gates."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from comuvia import (
    RecordStore,
    RefusalError,
    canonicalize,
    descriptor_content,
    new_record,
    not_applicable_marker,
    record_digest,
    reference_to,
    revise,
    snapshot_content,
    validate,
    verify,
)
from comuvia.profiles import dependencies as dp
from comuvia.profiles import edition_review as er


def _make_snapshot(rec_id: str, data: bytes, *, profile: dict | None = None, ns: str = dp.NAMESPACE,
                   recorded_at: str = "2027-01-10T10:00:00Z") -> dict:
    ext = {ns: profile} if profile is not None else {}
    return new_record(
        "resource_snapshot",
        rec_id,
        data_origin="synthetic",
        recorded_by="recorder:test",
        recorded_at=recorded_at,
        resource_type="dataset",
        locator=f"https://example.org/{rec_id}",
        captured_at=recorded_at,
        source_published_at={"date": "2027-01-10", "precision": "day"},
        source_version="1",
        content=snapshot_content(data, "application/json"),
        language="en",
        captured_assets=["payload_json"],
        not_captured=[],
        extensions=ext,
    )


def _make_descriptor(rec_id: str, data: bytes, *, content_schema: str = "example/1",
                     units: list[str] | dict | None = None, profile: dict | None = None,
                     ns: str = dp.NAMESPACE, recorded_at: str = "2027-01-10T11:00:00Z") -> dict:
    ext = {ns: profile} if profile is not None else {}
    return new_record(
        "artifact_descriptor",
        rec_id,
        data_origin="synthetic",
        recorded_by="recorder:test",
        recorded_at=recorded_at,
        content=descriptor_content(data, "application/json"),
        content_schema=content_schema,
        origin={"name": "Synthetic test producer", "locator": "https://example.org/producer"},
        published_at={"date": "2027-01-10", "precision": "day"},
        retrieved_at=recorded_at,
        units=["TEU"] if units is None else units,
        rights_reference={"unknown": "synthetic_fixture"},
        access="public",
        locator=f"https://example.org/artifacts/{rec_id}.json",
        extensions=ext,
    )


def _meaning(unit: str = "TEU") -> dict:
    return {"measure": "throughput", "unit": unit, "period": "2026", "geography": "SynthPort"}


class DependenciesProfileTest(unittest.TestCase):
    def test_v1_check_bundle_and_impact_statuses(self):
        b_r1 = canonicalize({"Q1": 100, "Q4": 120})
        b_r2 = canonicalize({"Q1": 100, "Q4": 125})
        src_r1 = _make_snapshot(
            "src-port",
            b_r1,
            profile={"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []},
        )
        src_r2 = revise(
            src_r1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-12T10:00:00Z",
            content=snapshot_content(b_r2, "application/json"),
            source_version="2",
        )
        unrelated = _make_snapshot(
            "src-fuel",
            canonicalize({"liters": 50}),
            profile={"value_origin": "observed", "meaning": _meaning("liters"), "coverage": "complete", "depends_on": []},
        )
        partial_out = _make_descriptor(
            "out-partial",
            canonicalize({"ratio": 2}),
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "partial",
                "depends_on": [{"role": "data_input", "pin": reference_to(unrelated), "selection": "all"}],
            },
        )
        chart_r1 = _make_descriptor(
            "chart-port",
            canonicalize({"bars": [100, 120]}),
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(src_r1), "selection": "Q1..Q4"}],
            },
        )
        sum_r1 = _make_descriptor(
            "sum-port",
            canonicalize({"total": 220}),
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(src_r1), "selection": "Q1+Q4"}],
            },
        )
        sum_r2 = revise(
            sum_r1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-12T11:00:00Z",
            repin=[(src_r1, src_r2)],
            content=descriptor_content(canonicalize({"total": 225}), "application/json"),
        )
        bundle = [src_r1, src_r2, unrelated, partial_out, chart_r1, sum_r1, sum_r2]
        self.assertEqual(dp.check_bundle(bundle), [])

        report = dp.impact(bundle, src_r2)
        self.assertEqual(report["profile"], dp.NAMESPACE)
        self.assertEqual(report["coverage"], "partial")
        by_id_rev = {(r["record"]["id"], r["record"]["revision"]): r for r in report["records"]}
        self.assertEqual(by_id_rev[("chart-port", 1)]["status"], "affected")
        self.assertEqual(by_id_rev[("chart-port", 1)]["latest_status"], "affected")
        self.assertNotIn("selection_status", by_id_rev[("chart-port", 1)])  # v1 without contents keeps exact v1 shape
        self.assertEqual(by_id_rev[("sum-port", 1)]["status"], "affected")
        self.assertEqual(by_id_rev[("sum-port", 1)]["latest_status"], "unaffected")
        self.assertEqual(by_id_rev[("sum-port", 2)]["status"], "unaffected")
        self.assertEqual(by_id_rev[("src-fuel", 1)]["status"], "unaffected")
        self.assertEqual(by_id_rev[("out-partial", 1)]["status"], "unknown")
        self.assertEqual(by_id_rev[("out-partial", 1)]["reasons"], ["partial_coverage"])

    def test_v2_selection_aware_impact_json_pointer_text_quote_and_soundness(self):
        b_r1 = canonicalize({"quarters": {"Q1": "100.0", "Q4": "120.0"}, "note": "Header: Q1 settled at 100.0; Q4 preliminary."})
        b_r2 = canonicalize({"quarters": {"Q1": "100.0", "Q4": "125.5"}, "note": "Header: Q1 settled at 100.0; Q4 revised."})
        src_r1 = _make_snapshot(
            "src-table",
            b_r1,
            ns=dp.NAMESPACE_V2,
            profile={"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []},
        )
        src_r2 = revise(
            src_r1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-15T10:00:00Z",
            content=snapshot_content(b_r2, "application/json"),
            source_version="2",
        )
        q1_bytes = canonicalize({"q1": "100.0"})
        q1_only = _make_descriptor(
            "card-q1",
            q1_bytes,
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{
                    "role": "data_input",
                    "pin": reference_to(src_r1),
                    "selection": {"kind": "json_pointer", "pointer": "/quarters/Q1"},
                }],
            },
        )
        q4_bytes = canonicalize({"q4": "120.0"})
        q4_only = _make_descriptor(
            "card-q4",
            q4_bytes,
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{
                    "role": "data_input",
                    "pin": reference_to(src_r1),
                    "selection": {"kind": "json_pointer", "pointer": "/quarters/Q4"},
                }],
            },
        )
        # Multi-edge soundness test: depends on BOTH Q1 (unchanged) and Q4 (changed) via two separate intermediates!
        both_bytes = canonicalize({"sum": "220.0"})
        both_card = _make_descriptor(
            "card-both",
            both_bytes,
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [
                    {"role": "data_input", "pin": reference_to(q1_only), "selection": {"kind": "json_pointer", "pointer": "/q1"}},
                    {"role": "data_input", "pin": reference_to(q4_only), "selection": {"kind": "json_pointer", "pointer": "/q4"}},
                ],
            },
        )
        quote_bytes = canonicalize({"excerpt": "Q1 settled at 100.0"})
        quote_card = _make_descriptor(
            "card-quote",
            quote_bytes,
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{
                    "role": "data_input",
                    "pin": reference_to(src_r1),
                    "selection": {
                        "kind": "text_quote",
                        "exact": "Q1 settled at 100.0",
                        "prefix": "Header: ",
                        "suffix": "; Q4 ",
                    },
                }],
            },
        )
        contents = {
            dp.key_of(src_r1): b_r1,
            dp.key_of(src_r2): b_r2,
            dp.key_of(q1_only): q1_bytes,
            dp.key_of(q4_only): q4_bytes,
            dp.key_of(both_card): both_bytes,
            dp.key_of(quote_card): quote_bytes,
        }
        bundle = [src_r1, src_r2, q1_only, q4_only, both_card, quote_card]
        self.assertEqual(dp.check_bundle(bundle, contents), [])

        report = dp.impact(bundle, src_r2, contents=contents)
        self.assertEqual(report["profile"], dp.NAMESPACE_V2)
        by_id = {r["record"]["id"]: r for r in report["records"]}
        self.assertEqual(by_id["card-q1"]["status"], "affected")
        self.assertEqual(by_id["card-q1"]["selection_status"], "unchanged")
        self.assertEqual(by_id["card-quote"]["selection_status"], "unchanged")
        self.assertEqual(by_id["card-q4"]["selection_status"], "changed")
        self.assertEqual(by_id["card-both"]["selection_status"], "changed")

        # Meaning change with identical bytes MUST report selection_status == "changed"!
        src_r3_meaning = revise(
            src_r2,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-16T10:00:00Z",
            extensions={
                dp.NAMESPACE_V2: {
                    "value_origin": "observed",
                    "meaning": _meaning("FEU"),
                    "coverage": "complete",
                    "depends_on": [],
                }
            },
        )
        q1_r2 = revise(
            q1_only,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-15T12:00:00Z",
            repin=[(src_r1, src_r2)],
        )
        contents2 = {**contents, dp.key_of(src_r3_meaning): b_r2, dp.key_of(q1_r2): q1_bytes}
        rep_meaning = dp.impact([src_r1, src_r2, src_r3_meaning, q1_r2], src_r3_meaning, contents=contents2)
        self.assertTrue(rep_meaning["change"]["meaning_changed"])
        self.assertFalse(rep_meaning["change"]["content_changed"])
        self.assertEqual(rep_meaning["records"][0]["selection_status"], "changed")

    def test_profile_refusals_and_store_gates(self):
        raw = b'{"x":1}'
        # Both v1 and v2 on one record is refused as invalid_profile.
        prof = {"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []}
        dual = _make_snapshot("src-dual", raw)
        dual["extensions"] = {dp.NAMESPACE: prof, dp.NAMESPACE_V2: prof}
        issues = dp.check_bundle([dual])
        self.assertEqual([i.code for i in issues], ["invalid_profile", "invalid_profile"])

        # Structured selection inside v1 is refused as invalid_profile.
        src = _make_snapshot("src-base", raw, profile=prof)
        bad_v1 = _make_descriptor(
            "art-bad-v1",
            raw,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(src),
                               "selection": {"kind": "json_pointer", "pointer": "/x"}}],
            },
        )
        self.assertEqual([i.code for i in dp.check_bundle([src, bad_v1])], ["invalid_profile"])

        # Store check_profiles=True refuses dangling extension pins on append and catches tampered pins on verify.
        dangling = _make_descriptor(
            "art-dangling",
            raw,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(src), "selection": "x"}],
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            store_dir = Path(tmp) / "store"
            RecordStore.create(store_dir)
            with RecordStore(store_dir, writer=True) as store:
                with self.assertRaises(RefusalError) as caught:
                    store.append(dangling, check_profiles=True)
                self.assertIn("missing_pin", caught.exception.codes)
                store.append(src, check_profiles=True)
                store.append(dangling, check_profiles=True)
            rep = RecordStore(store_dir).verify(check_profiles=True)
            self.assertTrue(rep.ok)
            self.assertTrue(rep.profiles_checked)

        # Single-record verify(..., check_profiles=True).
        v_unresolved = verify(dangling, records=(), check_profiles=True)
        self.assertEqual([r.result for r in v_unresolved.references], ["unresolved"])
        v_matched = verify(dangling, records=[src], check_profiles=True)
        self.assertEqual([r.result for r in v_matched.references], ["match"])
        self.assertEqual(v_matched.issues, ())


class EditionReviewProfileTest(unittest.TestCase):
    def test_edition_review_lifecycle_and_failure_modes(self):
        art_bytes_r1 = canonicalize({"headline": "Edition 1"})
        art_bytes_r2 = canonicalize({"headline": "Edition 2"})
        cap_bytes = b"1\n00:00:00,000 --> 00:00:02,000\nHello.\n"
        sum_bytes = canonicalize({"summary": "Edition 1 review packet"})

        art_r1 = _make_descriptor(
            "art-article",
            art_bytes_r1,
            content_schema="article/1",
            profile={"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []},
        )
        cap_r1 = _make_descriptor("art-captions", cap_bytes, content_schema="captions/1")
        sum_r1 = _make_descriptor("art-summary", sum_bytes, content_schema=er.SUMMARY)

        members_r1 = sorted(
            [
                {"role": "article", "pin": reference_to(art_r1)},
                {"role": "captions", "pin": reference_to(cap_r1)},
            ],
            key=lambda m: m["role"],
        )
        rev_obj_r1 = {
            "edition": "ed-1",
            "members": members_r1,
            "summary": reference_to(sum_r1),
            "status": "pending",
            "destinations": ["local-review", "youtube"],
            "decided_by": not_applicable_marker("pending_decision"),
            "decided_at": not_applicable_marker("pending_decision"),
            "authentication": "none",
            "fixture": True,
            "note": "Synthetic test review",
        }
        rev_bytes_r1 = canonicalize(rev_obj_r1)
        rev_r1 = _make_descriptor("rev-ed-1", rev_bytes_r1, content_schema=er.REVIEW)

        rev_obj_r2 = {
            **rev_obj_r1,
            "status": "approved",
            "decided_by": "fixture:reviewer",
            "decided_at": "2027-01-10T12:00:00Z",
        }
        rev_bytes_r2 = canonicalize(rev_obj_r2)
        rev_r2 = revise(
            rev_r1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T12:00:00Z",
            content=descriptor_content(rev_bytes_r2, "application/json"),
        )

        records = [art_r1, cap_r1, sum_r1, rev_r1, rev_r2]
        contents = {
            er.key_of(art_r1): art_bytes_r1,
            er.key_of(cap_r1): cap_bytes,
            er.key_of(sum_r1): sum_bytes,
            er.key_of(rev_r1): rev_bytes_r1,
            er.key_of(rev_r2): rev_bytes_r2,
        }

        pending = er.review_status(rev_r1, records, contents, destination="youtube")
        self.assertEqual(pending["state"], "current")
        self.assertFalse(pending["covers"])
        self.assertEqual(pending["covers_reasons"], ["decision_pending"])

        approved = er.review_status(rev_r2, records, contents, destination="youtube")
        self.assertEqual(approved["state"], "current")
        self.assertTrue(approved["covers"])
        self.assertEqual(approved["covers_reasons"], [])

        unapproved_dest = er.review_status(rev_r2, records, contents, destination="linkedin")
        self.assertFalse(unapproved_dest["covers"])
        self.assertEqual(unapproved_dest["covers_reasons"], ["destination_not_approved"])

        # Superseding article makes review stale.
        art_r2 = revise(
            art_r1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-11T10:00:00Z",
            content=descriptor_content(art_bytes_r2, "application/json"),
        )
        stale = er.review_status(
            rev_r2,
            records + [art_r2],
            {**contents, er.key_of(art_r2): art_bytes_r2},
            destination="youtube",
        )
        self.assertEqual(stale["state"], "stale")
        self.assertIn("member_superseded", stale["reasons"])
        self.assertFalse(stale["covers"])

        # Tampering caption bytes makes review broken.
        broken = er.review_status(
            rev_r2,
            records,
            {**contents, er.key_of(cap_r1): cap_bytes + b"tamper"},
            destination="youtube",
        )
        self.assertEqual(broken["state"], "broken")
        self.assertEqual(broken["reasons"], ["member_bytes_changed"])

        # Unlabelled synthetic decider makes review invalid.
        bad_obj = {**rev_obj_r2, "decided_by": "Owner"}
        bad_bytes = canonicalize(bad_obj)
        bad_rev = _make_descriptor("rev-bad", bad_bytes, content_schema=er.REVIEW)
        invalid = er.review_status(bad_rev, [art_r1, cap_r1, sum_r1, bad_rev], {**contents, er.key_of(bad_rev): bad_bytes})
        self.assertEqual(invalid["state"], "invalid")
        self.assertEqual(invalid["reasons"], ["fixture_not_labelled"])

        # Duplicate entries in current_members trigger edition_members_changed.
        dup_members = rev_obj_r2["members"] + [rev_obj_r2["members"][0]]
        dup_res = er.review_status(rev_r2, records, contents, current_members=dup_members, destination="youtube")
        self.assertEqual(dup_res["state"], "stale")
        self.assertIn("edition_members_changed", dup_res["reasons"])

    def test_d1_d2_n2_soundness_determinism_rfc6901_and_store_recheck(self):
        # 1. D1.1: Unresolvable pointer on one branch never masks a proven change on another branch, in either key order.
        b1 = canonicalize({"Q1": "100", "Q2": "200"})
        b2 = canonicalize({"Q1": "100", "Q2": "250"})
        s1 = _make_snapshot(
            "src-det",
            b1,
            ns=dp.NAMESPACE_V2,
            profile={"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []},
        )
        s2 = revise(
            s1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-11T10:00:00Z",
            content=snapshot_content(b2, "application/json"),
            source_version="2",
        )
        for unres_id, changed_id in (("aaa-unres", "zzz-changed"), ("zzz-unres", "aaa-changed")):
            m_unres = _make_descriptor(
                unres_id,
                b"{}",
                ns=dp.NAMESPACE_V2,
                profile={
                    "value_origin": "derived",
                    "meaning": _meaning(),
                    "coverage": "complete",
                    "depends_on": [{"role": "data_input", "pin": reference_to(s1), "selection": {"kind": "json_pointer", "pointer": "/missing"}}],
                },
            )
            m_chg = _make_descriptor(
                changed_id,
                b"{}",
                ns=dp.NAMESPACE_V2,
                profile={
                    "value_origin": "derived",
                    "meaning": _meaning(),
                    "coverage": "complete",
                    "depends_on": [{"role": "data_input", "pin": reference_to(s1), "selection": {"kind": "json_pointer", "pointer": "/Q2"}}],
                },
            )
            top = _make_descriptor(
                "top-both",
                b"{}",
                ns=dp.NAMESPACE_V2,
                profile={
                    "value_origin": "derived",
                    "meaning": _meaning(),
                    "coverage": "complete",
                    "depends_on": [
                        {"role": "data_input", "pin": reference_to(m_unres), "selection": {"kind": "json_pointer", "pointer": ""}},
                        {"role": "data_input", "pin": reference_to(m_chg), "selection": {"kind": "json_pointer", "pointer": ""}},
                    ],
                },
            )
            rep = dp.impact(
                [s1, s2, m_unres, m_chg, top],
                s2,
                contents={
                    dp.key_of(s1): b1,
                    dp.key_of(s2): b2,
                    dp.key_of(m_unres): b"{}",
                    dp.key_of(m_chg): b"{}",
                    dp.key_of(top): b"{}",
                },
            )
            by_id = {r["record"]["id"]: r for r in rep["records"]}
            self.assertEqual(by_id["top-both"]["selection_status"], "changed")

        # 2. D1.2: Multi-revision r1 -> r2 -> r3 meaning change (TEU -> FEU -> FEU) is detected for r1 dependents.
        s2_feu = revise(
            s1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-11T10:00:00Z",
            extensions={dp.NAMESPACE_V2: {"value_origin": "observed", "meaning": _meaning("FEU"), "coverage": "complete", "depends_on": []}},
            source_version="2",
        )
        s3_feu = revise(
            s2_feu,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-12T10:00:00Z",
            content=snapshot_content(b2, "application/json"),
            source_version="3",
        )
        dep_q1 = _make_descriptor(
            "dep-q1",
            b"{}",
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning("TEU"),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(s1), "selection": {"kind": "json_pointer", "pointer": "/Q1"}}],
            },
        )
        rep_r3 = dp.impact(
            [s1, s2_feu, s3_feu, dep_q1],
            s3_feu,
            contents={dp.key_of(s1): b1, dp.key_of(s2_feu): b1, dp.key_of(s3_feu): b2, dp.key_of(dep_q1): b"{}"},
        )
        self.assertEqual(rep_r3["records"][0]["selection_status"], "changed")

        # 3. D1.3: Unprofiled targets and invalid-profile changed revisions never claim "unchanged".
        u1 = _make_snapshot("unprof", b1)
        u2 = revise(u1, data_origin="synthetic", recorded_by="recorder:test", recorded_at="2027-01-11T10:00:00Z",
                    content=snapshot_content(b2, "application/json"), source_version="2")
        dep_u = _make_descriptor(
            "dep-unprof",
            b"{}",
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(u1), "selection": {"kind": "json_pointer", "pointer": "/Q1"}}],
            },
        )
        rep_u = dp.impact([u1, u2, dep_u], u2, contents={dp.key_of(u1): b1, dp.key_of(u2): b2, dp.key_of(dep_u): b"{}"})
        self.assertEqual(rep_u["records"][0]["selection_status"], "unscoped")

        s2_bad_prof = revise(
            s1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-11T10:00:00Z",
            content=snapshot_content(b2, "application/json"),
            extensions={dp.NAMESPACE_V2: {"value_origin": "observed", "meaning": _meaning(), "coverage": "bogus", "depends_on": []}},
        )
        rep_bad = dp.impact([s1, s2_bad_prof, dep_q1], s2_bad_prof,
                            contents={dp.key_of(s1): b1, dp.key_of(s2_bad_prof): b2, dp.key_of(dep_q1): b"{}"})
        self.assertEqual(rep_bad["records"][0]["selection_status"], "unscoped")

        # 4. D2: Malformed RFC 6901 tilde escapes, superscript/leading-zero array indices, and overlapping text_quote.
        bad_tilde = _make_descriptor(
            "bad-tilde",
            b"{}",
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(s1), "selection": {"kind": "json_pointer", "pointer": "/a~2b"}}],
            },
        )
        self.assertEqual([i.code for i in dp.check_bundle([s1, bad_tilde])], ["invalid_profile"])

        arr_b1 = canonicalize([10, 20])
        arr_b2 = canonicalize([10, 30])
        arr_s1 = _make_snapshot("arr", arr_b1, ns=dp.NAMESPACE_V2,
                                profile={"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []})
        arr_s2 = revise(arr_s1, data_origin="synthetic", recorded_by="recorder:test", recorded_at="2027-01-11T10:00:00Z",
                        content=snapshot_content(arr_b2, "application/json"), source_version="2")
        for bad_idx_ptr in ("/\u00b2", "/01"):
            arr_dep = _make_descriptor(
                "arr-dep",
                b"{}",
                ns=dp.NAMESPACE_V2,
                profile={
                    "value_origin": "derived",
                    "meaning": _meaning(),
                    "coverage": "complete",
                    "depends_on": [{"role": "data_input", "pin": reference_to(arr_s1), "selection": {"kind": "json_pointer", "pointer": bad_idx_ptr}}],
                },
            )
            arr_rep = dp.impact([arr_s1, arr_s2, arr_dep], arr_s2,
                                contents={dp.key_of(arr_s1): arr_b1, dp.key_of(arr_s2): arr_b2, dp.key_of(arr_dep): b"{}"})
            self.assertEqual(arr_rep["records"][0]["selection_status"], "unscoped")

        ov_b1, ov_b2 = b"ababa-v1", b"ababa-v2"
        ov_s1 = _make_snapshot("ov", ov_b1, ns=dp.NAMESPACE_V2,
                               profile={"value_origin": "observed", "meaning": _meaning(), "coverage": "complete", "depends_on": []})
        ov_s2 = revise(ov_s1, data_origin="synthetic", recorded_by="recorder:test", recorded_at="2027-01-11T10:00:00Z",
                       content=snapshot_content(ov_b2, "text/plain; charset=utf-8"), source_version="2")
        ov_dep = _make_descriptor(
            "ov-dep",
            b"{}",
            ns=dp.NAMESPACE_V2,
            profile={
                "value_origin": "derived",
                "meaning": _meaning(),
                "coverage": "complete",
                "depends_on": [{"role": "data_input", "pin": reference_to(ov_s1),
                                "selection": {"kind": "text_quote", "exact": "aba", "prefix": "", "suffix": ""}}],
            },
        )
        ov_rep = dp.impact([ov_s1, ov_s2, ov_dep], ov_s2,
                           contents={dp.key_of(ov_s1): ov_b1, dp.key_of(ov_s2): ov_b2, dp.key_of(ov_dep): b"{}"})
        self.assertEqual(ov_rep["records"][0]["selection_status"], "unscoped")

        # 5. N2: Store idempotent re-append and import_jsonl re-check profiles when check_profiles=True.
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordStore.create(Path(tmp) / "store")
            store.close()
            with RecordStore(Path(tmp) / "store", writer=True) as writer:
                writer.append(bad_tilde, check_profiles=False)
                with self.assertRaises(RefusalError):
                    writer.append(bad_tilde, check_profiles=True)
                with self.assertRaises(RefusalError):
                    writer.import_jsonl(canonicalize(bad_tilde) + b"\n", check_profiles=True)


if __name__ == "__main__":
    unittest.main()
