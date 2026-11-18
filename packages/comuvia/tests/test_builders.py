"""Usability fixes F1 (artifact_descriptor retained message), F2 (schema_dir) and F4 (new_record, revise)."""

import copy
import json
import unittest
from pathlib import Path
from types import MappingProxyType

import comuvia
from comuvia import RefusalError, canonicalize, new_record, record_digest, reference_to, revise, schema_dir, validate

VECTORS = Path(__file__).resolve().parent / "vectors"
RECORDS = json.loads((VECTORS / "identity.json").read_text(encoding="utf-8"))["records"]
VALID_CASES = {c["id"]: c["record"] for c in json.loads((VECTORS / "records.json").read_text(encoding="utf-8"))["valid"]}
ENVELOPE = {"schema", "record_type", "id", "revision", "predecessor", "data_origin", "recorded_by", "recorded_at"}


class BuildersAndUsabilityTest(unittest.TestCase):
    def test_f1_artifact_descriptor_retained_message_is_specific(self):
        descriptor = copy.deepcopy(VALID_CASES["shape-artifact_descriptor"])
        descriptor["content"]["retained"] = True
        issues = validate(descriptor)
        self.assertEqual([(i.pointer, i.code) for i in issues], [("/content/retained", "unrecognized_member")])
        self.assertEqual(issues[0].message, "artifact_descriptor content always identifies retained bytes; omit 'retained'")

        # Other unrecognized members keep the standard message.
        snapshot = copy.deepcopy(RECORDS["res-harbor-weekly-e42-transcript"])
        snapshot["content"]["extra"] = 1
        snap_issues = validate(snapshot)
        self.assertEqual([(i.pointer, i.code, i.message) for i in snap_issues],
                         [("/content/extra", "unrecognized_member", "not allowed")])

    def test_f2_schema_dir_matches_deprecated_alias(self):
        self.assertEqual(schema_dir(), comuvia.schema_files())
        self.assertIn("artifact_descriptor.json", {p.name for p in schema_dir().iterdir()})

    def test_new_record_rebuilds_all_fixture_records_byte_for_byte(self):
        for body in RECORDS.values():
            fields = {k: v for k, v in body.items() if k not in ENVELOPE}
            rebuilt = new_record(
                body["record_type"],
                body["id"],
                data_origin=body["data_origin"],
                recorded_by=body["recorded_by"],
                recorded_at=body["recorded_at"],
                **fields,
            )
            self.assertEqual(canonicalize(rebuilt), canonicalize(body), body["id"])
            self.assertEqual(record_digest(rebuilt), record_digest(body), body["id"])

    def test_revise_increments_revision_sets_predecessor_and_requires_explicit_data_origin(self):
        out_r1 = RECORDS["out-port-calder-teu-2027-01"]
        proxied = MappingProxyType(copy.deepcopy(out_r1))
        out_r2 = revise(
            proxied,
            data_origin="synthetic",
            recorded_by="recorder:example-resolver",
            recorded_at="2027-02-20T10:00:00Z",
            resolved_value=0,
        )
        self.assertEqual(out_r2["revision"], 2)
        self.assertEqual(out_r2["predecessor"], reference_to(out_r1))
        self.assertEqual(out_r2["resolved_value"], 0)
        self.assertEqual(out_r1["resolved_value"], 1)  # predecessor is never mutated
        self.assertEqual(validate(out_r2), [])

        # Missing required provenance keyword arguments fail at call time (never defaulted or inherited).
        with self.assertRaises(TypeError):
            revise(out_r1, recorded_by="recorder:example-resolver", recorded_at="2027-02-20T10:00:00Z", resolved_value=0)
        with self.assertRaises(TypeError):
            new_record("outcome", "out-1", recorded_by="recorder:x", recorded_at="2027-02-20T10:00:00Z")

    def test_protected_fields_and_invalid_inputs_are_refused(self):
        q = RECORDS["q-port-calder-teu-2027-01"]
        fields = {k: v for k, v in q.items() if k not in ENVELOPE}
        for key, val in (("schema", "comuvia/0.1"), ("revision", 2), ("predecessor", None)):
            with self.assertRaises(RefusalError) as caught:
                new_record("question", "q-1", data_origin="synthetic", recorded_by="recorder:x",
                           recorded_at="2026-09-01T00:00:00Z", **{**fields, key: val})
            self.assertEqual([(i.pointer, i.code) for i in caught.exception.issues], [(f"/{key}", "protected_field")])

        for key in ("schema", "record_type", "id", "revision", "predecessor"):
            with self.assertRaises(RefusalError) as caught:
                revise(q, data_origin="synthetic", recorded_by="recorder:x",
                       recorded_at="2026-09-02T00:00:00Z", **{key: q[key]})
            self.assertEqual([(i.pointer, i.code) for i in caught.exception.issues], [(f"/{key}", "protected_field")])

        # Tuples remain refused where JSON arrays are required (0.1.1 invariant).
        with self.assertRaises(RefusalError) as caught:
            revise(q, data_origin="synthetic", recorded_by="recorder:x",
                   recorded_at="2026-09-02T00:00:00Z", limitations=("text_possibly_truncated",))
        self.assertEqual([(i.pointer, i.code) for i in caught.exception.issues], [("/limitations", "invalid_type")])

        # Invalid predecessor is refused before building a successor.
        bad_prev = copy.deepcopy(q)
        bad_prev["outcome_kind"] = "invalid"
        with self.assertRaises(RefusalError) as caught:
            revise(bad_prev, data_origin="synthetic", recorded_by="recorder:x", recorded_at="2026-09-02T00:00:00Z")
        self.assertEqual(caught.exception.codes, frozenset({"invalid_value"}))


if __name__ == "__main__":
    unittest.main()
