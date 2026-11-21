"""Tests for ``locate_quote``, ``media_time`` selector checks, pin-cascade ``revise``, ``stale_pins`` and ``runtime_identity``."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

import comuvia
from comuvia import (
    RefusalError,
    check_selector,
    descriptor_content,
    is_not_applicable,
    locate_quote,
    new_record,
    not_applicable_marker,
    reference_to,
    revise,
    runtime_identity,
    snapshot_content,
    stale_pins,
    unretained_content,
    validate,
)


class SelectorsAndBuildersTest(unittest.TestCase):
    def test_locate_quote_unique_disambiguated_and_refusals(self):
        doc = (
            "Section 1: Cloud gateway latency stayed at 14 ms during peak traffic.\n"
            "Section 2: Edge cache latency stayed at 14 ms under synthetic replay.\n"
        ).encode("utf-8")
        snap = new_record(
            "resource_snapshot",
            "res-doc",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:00:00Z",
            resource_type="document",
            locator="https://example.org/doc.txt",
            captured_at="2027-01-10T10:00:00Z",
            source_published_at={"date": "2027-01-10", "precision": "day"},
            source_version="1",
            content=snapshot_content(doc, "text/plain; charset=utf-8"),
            language="en",
            captured_assets=["doc_txt"],
            not_captured=[],
        )

        # Unique quote locates cleanly and round-trips through validate + check_selector.
        sel_unique = locate_quote("Cloud gateway latency stayed at 14 ms", doc)
        self.assertTrue(is_not_applicable(sel_unique["media_time"]))
        asr = new_record(
            "source_assertion",
            "asr-1",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:05:00Z",
            resource=reference_to(snap),
            quote={"exact": "Cloud gateway latency stayed at 14 ms", "verbatim": True, "language": "en", "translation": None},
            selector=sel_unique,
            attributed_to={"name": "Synthetic Report", "basis": "document"},
            assertion_kind="factual_claim",
            stated_probability=None,
        )
        self.assertEqual(validate(asr), [])
        chk = check_selector(asr, doc, snapshot=snap)
        self.assertEqual(chk.result, "match")
        self.assertEqual(chk.checked, ("quote", "text_quote", "text_position"))

        # Repeated quote refuses by default, and succeeds with occurrence=1 using widened/anchoring context.
        with self.assertRaises(RefusalError) as caught:
            locate_quote("latency stayed at 14 ms", doc)
        self.assertEqual(caught.exception.codes, frozenset({"ambiguous_quote"}))

        sel_second = locate_quote("latency stayed at 14 ms", doc, context_chars=4, max_context_chars=64, occurrence=1)
        asr2 = new_record(
            "source_assertion",
            "asr-2",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:06:00Z",
            resource=reference_to(snap),
            quote={"exact": "latency stayed at 14 ms", "verbatim": True, "language": "en", "translation": None},
            selector=sel_second,
            attributed_to={"name": "Synthetic Report", "basis": "document"},
            assertion_kind="factual_claim",
            stated_probability=None,
        )
        self.assertEqual(check_selector(asr2, doc, snapshot=snap).result, "match")

        # Missing quote refuses with quote_mismatch.
        with self.assertRaises(RefusalError) as caught:
            locate_quote("nonexistent phrase", doc)
        self.assertEqual(caught.exception.codes, frozenset({"quote_mismatch"}))

    def test_media_time_duration_and_timed_segments_verification(self):
        transcript = b"By definition you cannot simply trust autonomous models without runtime guardrails."
        snap = new_record(
            "resource_snapshot",
            "res-clip-txt",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:00:00Z",
            resource_type="transcript",
            locator="https://example.org/clip.txt",
            captured_at="2027-01-10T10:00:00Z",
            source_published_at={"date": "2027-01-10", "precision": "day"},
            source_version="1",
            content=snapshot_content(transcript, "text/plain; charset=utf-8"),
            language="en",
            captured_assets=["clip_txt"],
            not_captured=["video_frames"],
        )
        quote_text = "cannot simply trust autonomous models"
        sel = locate_quote(quote_text, transcript, media_time={"start_seconds": 12.4, "end_seconds": 16.8})
        asr = new_record(
            "source_assertion",
            "asr-clip",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:05:00Z",
            resource=reference_to(snap),
            quote={"exact": quote_text, "verbatim": True, "language": "en", "translation": None},
            selector=sel,
            attributed_to={"name": "Synthetic Speaker", "basis": "speech_transcript"},
            assertion_kind="factual_claim",
            stated_probability=None,
        )
        segments = [
            {"start": 10.0, "end": 13.0, "text": "By definition you"},
            {"start": 13.0, "end": 16.7, "text": "cannot simply trust\nautonomous models"},
            {"start": 16.7, "end": 19.5, "text": "without runtime guardrails."},
        ]
        ok = check_selector(asr, transcript, snapshot=snap, media_duration=25.0, timed_segments=segments)
        self.assertEqual(ok.result, "match")
        self.assertIn("media_time", ok.checked)

        # Exceeding media_duration fails closed.
        too_short = check_selector(asr, transcript, snapshot=snap, media_duration=15.0, timed_segments=segments)
        self.assertEqual(too_short.result, "mismatch")
        self.assertEqual([i.pointer for i in too_short.issues], ["/selector/media_time"])

        # Wrong speech window fails closed.
        shifted_segments = [{"start": 1.0, "end": 4.0, "text": "Unrelated intro speech only."}]
        wrong_win = check_selector(asr, transcript, snapshot=snap, media_duration=25.0, timed_segments=shifted_segments)
        self.assertEqual(wrong_win.result, "mismatch")

    def test_repin_stale_pins_content_builders_and_runtime_identity(self):
        b1 = b'{"v":1}'
        b2 = b'{"v":2}'
        s1 = new_record(
            "resource_snapshot",
            "src-a",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:00:00Z",
            resource_type="dataset",
            locator="https://example.org/a",
            captured_at="2027-01-10T10:00:00Z",
            source_published_at={"date": "2027-01-10", "precision": "day"},
            source_version="1",
            content=snapshot_content(b1, "application/json"),
            language="en",
            captured_assets=["a_json"],
            not_captured=[],
        )
        unret = unretained_content(
            "video/mp4",
            byte_length=not_applicable_marker("stream_only"),
            digest={"unknown": "bytes_not_retained"},
        )
        self.assertFalse(unret["retained"])

        s2 = revise(
            s1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T11:00:00Z",
            enforce_monotonic_time=True,
            require_change=True,
            content=snapshot_content(b2, "application/json"),
            source_version="2",
        )
        art1 = new_record(
            "artifact_descriptor",
            "art-derived",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:30:00Z",
            content=descriptor_content(b'{"out":1}', "application/json"),
            content_schema="out/1",
            origin={"name": "Test", "locator": "https://example.org"},
            published_at={"date": "2027-01-10", "precision": "day"},
            retrieved_at="2027-01-10T10:30:00Z",
            units=["count"],
            rights_reference={"unknown": "synthetic"},
            access="public",
            locator="https://example.org/out.json",
            extensions={"org.example.pins/v1": {"input": reference_to(s1)}},
        )

        # Stale pins detects s1 is superseded by s2.
        stale = stale_pins([s1, s2, art1])
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].state, "superseded")
        self.assertEqual(stale[0].latest_revision, 2)

        # Repin moves extension pin onto s2 while preserving predecessor.
        art2 = revise(
            art1,
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T11:30:00Z",
            repin=[(s1, s2)],
            require_change=True,
            enforce_monotonic_time=True,
        )
        self.assertEqual(art2["predecessor"], reference_to(art1))
        self.assertEqual(art2["extensions"]["org.example.pins/v1"]["input"], reference_to(s2))
        self.assertEqual(stale_pins([s2, art2]), [stale_pins([s1, s2, art1, art2])[0][:0]] if False else [])

        # Monotonic time & no_change refusals when requested.
        with self.assertRaises(RefusalError) as caught:
            revise(s2, data_origin="synthetic", recorded_by="recorder:test",
                   recorded_at="2027-01-10T09:00:00Z", enforce_monotonic_time=True, source_version="3")
        self.assertIn("recorded_before_predecessor", caught.exception.codes)

        with self.assertRaises(RefusalError) as caught:
            revise(s2, data_origin="synthetic", recorded_by="recorder:test",
                   recorded_at="2027-01-10T12:00:00Z", require_change=True)
        self.assertIn("no_change", caught.exception.codes)

        with self.assertRaises(RefusalError) as caught:
            revise(art2, data_origin="synthetic", recorded_by="recorder:test",
                   recorded_at="2027-01-10T12:00:00Z", repin=[(s2, s1)])
        self.assertIn("not_a_successor", caught.exception.codes)

        # runtime_identity reports version and exposes no drive or directory path.
        ident = runtime_identity()
        self.assertEqual(ident["package"], "comuvia")
        self.assertEqual(ident["version"], comuvia.__version__)
        self.assertIn(ident["source"], ("archive", "directory"))
        if ident["archive_name"] is not None:
            self.assertNotIn("/", ident["archive_name"])
            self.assertNotIn("\\", ident["archive_name"])
            self.assertTrue(ident["archive_sha256"].startswith("sha256:"))

        # Simulate zipimporter archive metadata cleanly.
        with tempfile.TemporaryDirectory() as tmp:
            fake_whl = Path(tmp) / "comuvia-0.1.3-py3-none-any.whl"
            with zipfile.ZipFile(fake_whl, "w") as zf:
                zf.writestr("dummy.txt", b"hello")
            expected_sha = "sha256:" + hashlib.sha256(fake_whl.read_bytes()).hexdigest()
            orig_loader = comuvia.identity.__loader__

            class _FakeZipLoader:
                archive = str(fake_whl)

            try:
                comuvia.identity.__loader__ = _FakeZipLoader()
                zip_ident = runtime_identity()
                self.assertEqual(zip_ident["source"], "archive")
                self.assertEqual(zip_ident["archive_name"], "comuvia-0.1.3-py3-none-any.whl")
                self.assertEqual(zip_ident["archive_sha256"], expected_sha)
                self.assertEqual(zip_ident["archive_bytes"], fake_whl.stat().st_size)
            finally:
                comuvia.identity.__loader__ = orig_loader

    def test_d5_surrogates_media_time_validation_whitespace_and_markers(self):
        doc = b"Instant cue marker and three spaces   in transcript."
        snap = new_record(
            "resource_snapshot",
            "res-cue",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:00:00Z",
            resource_type="transcript",
            locator="https://example.org/cue.txt",
            captured_at="2027-01-10T10:00:00Z",
            source_published_at={"date": "2027-01-10", "precision": "day"},
            source_version="1",
            content=snapshot_content(doc, "text/plain; charset=utf-8"),
            language="en",
            captured_assets=["cue_txt"],
            not_captured=[],
        )

        # Lone surrogates and invalid media_time inputs are refused by locate_quote.
        with self.assertRaises(RefusalError) as caught:
            locate_quote("bad\ud800quote", "bad\ud800quote")
        self.assertIn("lone_surrogate", caught.exception.codes)

        for bad_mt in (
            {"start_seconds": 10.0, "end_seconds": 5.0},
            {"start_seconds": True, "end_seconds": 5.0},
            {"start": 1.0, "end": 2.0},
            {"unknown": "BAD-CODE"},
            "not-a-mapping",
        ):
            with self.assertRaises(RefusalError):
                locate_quote("Instant cue marker", doc, media_time=bad_mt)  # type: ignore[arg-type]

        # Zero-duration cue (start_seconds == end_seconds) is valid in locate_quote, validate and check_selector.
        instant_sel = locate_quote("Instant cue marker", doc, media_time={"start_seconds": 5.0, "end_seconds": 5.0})
        instant_asr = new_record(
            "source_assertion",
            "asr-instant",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:05:00Z",
            resource=reference_to(snap),
            quote={"exact": "Instant cue marker", "verbatim": True, "language": "en", "translation": None},
            selector=instant_sel,
            attributed_to={"name": "Speaker", "basis": "transcript"},
            assertion_kind="factual_claim",
            stated_probability=None,
        )
        self.assertEqual(
            check_selector(
                instant_asr,
                doc,
                snapshot=snap,
                media_duration=10.0,
                timed_segments=[{"start_seconds": 5.0, "end_seconds": 5.0, "text": "Instant cue marker"}],
            ).result,
            "match",
        )

        # Whitespace-only verbatim quote never matches empty or inverted timed_segments.
        ws_sel = locate_quote("   ", doc, media_time={"start_seconds": 1.0, "end_seconds": 2.0})
        ws_asr = new_record(
            "source_assertion",
            "asr-ws",
            data_origin="synthetic",
            recorded_by="recorder:test",
            recorded_at="2027-01-10T10:06:00Z",
            resource=reference_to(snap),
            quote={"exact": "   ", "verbatim": True, "language": "en", "translation": None},
            selector=ws_sel,
            attributed_to={"name": "Speaker", "basis": "transcript"},
            assertion_kind="factual_claim",
            stated_probability=None,
        )
        self.assertEqual(check_selector(ws_asr, doc, snapshot=snap, timed_segments=[]).result, "mismatch")
        self.assertEqual(
            check_selector(
                ws_asr,
                doc,
                snapshot=snap,
                timed_segments=[{"start_seconds": 3.0, "end_seconds": 1.0, "text": "   "}],
            ).result,
            "mismatch",
        )

        # Marker helpers and repin non-sequence guard follow common.json rules strictly.
        with self.assertRaises(RefusalError):
            not_applicable_marker("Not-Applicable")
        self.assertFalse(is_not_applicable({"unknown": "not_applicable", "note": ""}))
        self.assertFalse(is_not_applicable({"unknown": "not_applicable", "note": 123}))
        with self.assertRaises(RefusalError) as caught:
            revise(snap, data_origin="synthetic", recorded_by="recorder:test",
                   recorded_at="2027-01-10T11:00:00Z", repin="not-a-seq")  # type: ignore[arg-type]
        self.assertIn("invalid_type", caught.exception.codes)


if __name__ == "__main__":
    unittest.main()
