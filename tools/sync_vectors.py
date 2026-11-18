"""Recompute fixture reference digests and regenerate the fixture-derived test vectors.

Standard library plus the in-tree comuvia source; Python 3.11+.

    python -I tools/sync_vectors.py           # rewrite fixtures and generated vectors
    python -I tools/sync_vectors.py --check   # fail if anything is stale

What it writes:

- ``fixtures/synthetic/*/records/*.json``: every reference gains/keeps the record digest
  of its target (targets first). Content digests and all other values are untouched.
- ``fixtures/synthetic/*/expected.json``: references carry the same record digests.
- ``packages/comuvia/tests/vectors/identity.json``, ``records.json``, ``evaluation.json``
  and ``ots.json``: self-contained vectors built from the fixtures and OpenTimestamps
  format rules (when ``packages/foreglass/src/foreglass/verify.py`` is present, ``ots.json``
  is also synced byte-for-byte into ``packages/foreglass/tests/vectors/ots.json``).
- ``packages/comuvia/src/comuvia/types.py``: PEP 561 ``TypedDict`` definitions derived from
  ``packages/comuvia/src/comuvia/schemas/v0_1/*.json``.

Expected reason codes and results in the vectors are written here by hand. Only digest
values are computed by the in-tree encoder, so those values prove stability, not
correctness; RFC 8785 correctness comes from ``canonicalization.json``, whose expected
outputs are copied from the RFC text.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "comuvia" / "src"))

from comuvia import content_digest, record_digest, validate  # noqa: E402

FIXTURES = REPO / "fixtures" / "synthetic"
CORE_FIXTURES = ("narrative-conditional", "structured-binary")
SCHEMAS = REPO / "packages" / "comuvia" / "src" / "comuvia" / "schemas" / "v0_1"
TYPES_PATH = REPO / "packages" / "comuvia" / "src" / "comuvia" / "types.py"
VECTORS = REPO / "packages" / "comuvia" / "tests" / "vectors"
FOREGLASS_VERIFY = REPO / "packages" / "foreglass" / "src" / "foreglass" / "verify.py"
FOREGLASS_VECTORS = REPO / "packages" / "foreglass" / "tests" / "vectors"
LOCATOR_HASH = "sha256:019b10b3b701c573395ff3fa4c5c7382623c2c0be9606178902576ad3e9a3cbf"


def dump(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def key(ref) -> tuple:
    return (ref["record_type"], ref["id"], ref["revision"])


def is_reference(value) -> bool:
    return isinstance(value, dict) and {"record_type", "id", "revision"} <= set(value) <= {
        "record_type", "id", "revision", "digest",
    }


def relink(value, digests: dict, top: bool = True):
    """Return ``value`` with every nested reference carrying its target's digest."""
    if isinstance(value, dict):
        if not top and is_reference(value):
            ref = {k: value[k] for k in ("record_type", "id", "revision")}
            if key(ref) in digests:
                ref["digest"] = digests[key(ref)]
            return ref
        return {k: relink(v, digests, False) if k != "extensions" else v for k, v in value.items()}
    if isinstance(value, list):
        return [relink(v, digests, False) for v in value]
    return value


def load_fixture(directory: Path) -> tuple[dict, dict, dict]:
    records = {}
    for path in sorted((directory / "records").glob("*.json")):
        records[path] = json.loads(path.read_text(encoding="utf-8"))
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    source_dir = directory / "source"
    sources = {p.name: p.read_bytes() for p in sorted(source_dir.iterdir())} if source_dir.is_dir() else {}
    return records, expected, sources


def sync_fixture(directory: Path) -> tuple[dict[Path, bytes], dict[str, dict], dict[str, bytes]]:
    records, expected, sources = load_fixture(directory)
    digests: dict = {}
    for _ in range(len(records) + 1):  # targets settle before the records that reference them
        records = {p: relink(b, digests) for p, b in records.items()}
        updated = {key(b): record_digest(b) for b in records.values()}
        if updated == digests:
            break
        digests = updated
    else:
        raise SystemExit(f"{directory.name}: reference digests did not settle")
    expected = relink(expected, digests)
    for entry in expected["record_identity"]:
        entry["result"] = "match"
    outputs = {p: dump(b) for p, b in records.items()}
    outputs[directory / "expected.json"] = dump(expected)
    for body in records.values():
        issues = validate(body)
        if issues:
            raise SystemExit(f"{directory.name}/{body['id']}: fixture record refused: {issues}")
    by_id = {b["id"]: b for b in records.values()}
    by_digest = {content_digest(data): data for data in sources.values()}
    source_for = {
        b["id"]: by_digest[b["content"]["digest"]]
        for b in records.values()
        if b["record_type"] == "resource_snapshot" and b["content"]["retained"]
    }
    return outputs, by_id, source_for


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def with_value(body: dict, path: list, value) -> dict:
    body = copy.deepcopy(body)
    target = body
    for token in path[:-1]:
        target = target[token]
    target[path[-1]] = value
    return body


def without(body: dict, member: str) -> dict:
    body = copy.deepcopy(body)
    del body[member]
    return body


def build_identity_vectors(records: dict[str, dict], sources: dict[str, bytes]) -> dict:
    snapshot = records["res-harbor-weekly-e42-transcript"]
    assertion = records["asr-harbor-weekly-e42-ilsley-freight"]
    transcript = sources["res-harbor-weekly-e42-transcript"]
    quote_changed = with_value(
        assertion, ["quote", "exact"],
        assertion["quote"]["exact"].replace("Freight", "Freighr"),
    )
    wrong_link = with_value(
        assertion, ["resource", "digest"], record_digest(records["int-ilsley-freight-analyst-1"]),
    )
    metadata_only = with_value(snapshot, ["content"], {
        "media_type": "text/plain; charset=utf-8",
        "retained": False,
        "byte_length": {"unknown": "bytes_not_retained"},
        "digest": {"unknown": "bytes_not_retained"},
    })
    version_known = with_value(snapshot, ["source_version"], "1")
    conflicting = with_value(snapshot, ["language"], "en-GB")
    cases = [
        {
            "id": "fixture-digests",
            "kind": "verify",
            "description": "Every fixture record verifies against its recorded digest; references resolve and match.",
            "records": sorted(records),
            "expect": {"record_identity": "match", "references": "match", "codes": []},
        },
        {
            "id": "I7-quote-character",
            "kind": "verify",
            "record": quote_changed,
            "expected_digest": record_digest(assertion),
            "expect": {"record_identity": "mismatch", "codes": ["record_digest_mismatch"]},
        },
    ]
    for label, mutated in [
        ("I7-source-crlf", transcript.replace(b"\n", b"\r\n")),
        ("I7-source-extra-final-newline", transcript + b"\n"),
        ("I7-source-added-bom", b"\xef\xbb\xbf" + transcript),
    ]:
        cases.append({
            "id": label,
            "kind": "verify",
            "record": snapshot,
            "content_base64": b64(mutated),
            "expect": {"content_identity": "mismatch", "codes": ["content_digest_mismatch"]},
        })
    cases += [
        {
            "id": "I7-source-exact",
            "kind": "verify",
            "record": snapshot,
            "content_base64": b64(transcript),
            "expect": {"content_identity": "match", "codes": []},
        },
        {
            "id": "R3-byte-length-integral-float-match",
            "kind": "verify",
            "record": with_value(snapshot, ["content", "byte_length"], 530.0),
            "content_base64": b64(transcript),
            "expect": {"content_identity": "match", "codes": []},
        },
        {
            "id": "R3-byte-length-integral-float-compared",
            "kind": "verify",
            "record": with_value(snapshot, ["content", "byte_length"], 531.0),
            "content_base64": b64(transcript),
            "expect": {"content_identity": "mismatch", "codes": ["content_digest_mismatch"]},
        },
        {
            "id": "I8-wrong-linkage",
            "kind": "verify",
            "description": "(id, revision) resolves, but the digest belongs to a different body.",
            "record": wrong_link,
            "records": sorted(records),
            "expect": {"references": {"/resource": "mismatch"}, "codes": ["reference_digest_mismatch"]},
        },
        {
            "id": "I9-locator-hash-as-content-digest",
            "kind": "verify",
            "record": with_value(snapshot, ["content", "digest"], LOCATOR_HASH),
            "content_base64": b64(transcript),
            "expect": {"content_identity": "mismatch", "codes": ["content_digest_mismatch"]},
        },
        {
            "id": "I9-metadata-only-snapshot",
            "kind": "verify",
            "record": metadata_only,
            "content_base64": b64(transcript),
            "expect": {"content_identity": "unavailable", "codes": [], "valid": True},
        },
        {
            "id": "I9-identities-distinct",
            "kind": "distinct_identities",
            "record": snapshot,
            "locator_hash": LOCATOR_HASH,
            "description": "Locator hash, content digest and record digest are three different values.",
        },
        {
            "id": "I11-marker-replaced-by-value",
            "kind": "digest_differs",
            "record": snapshot,
            "other": version_known,
        },
        {
            "id": "I11-marker-round-trip",
            "kind": "round_trip",
            "record": snapshot,
            "expect": {"pointer": "/source_version", "value": {"unknown": "source_declares_no_version"}},
        },
        {
            "id": "I12-revision-conflict",
            "kind": "revision_conflicts",
            "records": [snapshot, conflicting],
            "expect": {"codes": ["revision_conflict"]},
        },
        {
            "id": "I12-same-body-twice",
            "kind": "revision_conflicts",
            "records": [snapshot, copy.deepcopy(snapshot)],
            "expect": {"codes": []},
        },
        {
            "id": "day-precision-round-trip",
            "kind": "round_trip",
            "description": "A day-precision value stays a day-precision object; it is never expanded to midnight.",
            "record": snapshot,
            "expect": {
                "pointer": "/source_published_at",
                "value": {"date": "2026-01-14", "precision": "day"},
                "canonical_contains": '"source_published_at":{"date":"2026-01-14","precision":"day"}',
            },
        },
    ]
    return {
        "description": "Identity vectors I7-I9, I11, I12 and day precision (review section 6.6), built from the synthetic fixtures.",
        "generated_by": "tools/sync_vectors.py",
        "records": records,
        "sources_base64": {k: b64(v) for k, v in sorted(sources.items())},
        "cases": cases,
    }


def shape_examples(records: dict[str, dict]) -> list[dict]:
    """Valid examples for the three record types the fixtures do not cover."""
    from comuvia import reference_to
    from comuvia.evaluation import load_rule

    assessment = {
        "schema": "comuvia/0.1",
        "record_type": "assessment",
        "id": "asm-ilsley-freight-checker-1",
        "revision": 1,
        "predecessor": None,
        "data_origin": "synthetic",
        "assertion": reference_to(records["asr-harbor-weekly-e42-ilsley-freight"]),
        "checker": "checker:example-checker-1",
        "evidence": [reference_to(records["res-harbor-weekly-e42-transcript"])],
        "rubric": {"id": "rubric-quote-fidelity", "version": "0.1-synthetic"},
        "verdict": "supported",
        "checker_confidence": 0.9,
        "coverage": {"scope": "full", "items_checked": 1, "items_total": 1},
        "assessed_at": "2026-03-12T09:00:00Z",
        "recorded_by": "checker:example-checker-1",
        "recorded_at": "2026-03-12T09:05:00Z",
    }
    evaluation = {
        "schema": "comuvia/0.1",
        "record_type": "evaluation",
        "id": "eval-lantern-port-calder-teu-2027-01",
        "revision": 1,
        "predecessor": None,
        "data_origin": "synthetic",
        "forecast": reference_to(records["fc-lantern-port-calder-teu-2027-01"]),
        "outcome": reference_to(records["out-port-calder-teu-2027-01"]),
        "scoring_rule": load_rule().reference(),
        "policy": None,
        "result": {"eligible": True, "exclusion_reasons": [], "loss": 0.09000000000000002},
        "evaluated_at": "2027-02-17T00:00:00Z",
        "recorded_by": "evaluator:example-evaluator",
        "recorded_at": "2027-02-17T00:00:00Z",
    }
    descriptor = {
        "schema": "comuvia/0.1",
        "record_type": "artifact_descriptor",
        "id": "art-port-calder-bulletin-2027-01-first",
        "revision": 1,
        "predecessor": None,
        "data_origin": "synthetic",
        "content": {
            "media_type": "text/csv; charset=utf-8",
            "byte_length": 49,
            "digest": "sha256:f9bcfff9fe5b9670049d90519b9e66b9fbdab7734f3a4053e5a4cce18e059c77",
        },
        "content_schema": "month,container_teu,release",
        "origin": {
            "name": "Port Calder Authority monthly statistical bulletin (fictional)",
            "locator": "https://example.org/synthetic/port-calder/bulletins/",
        },
        "published_at": {"date": "2027-02-15", "precision": "day"},
        "retrieved_at": "2027-02-16T09:30:00Z",
        "units": ["TEU"],
        "rights_reference": {"unknown": "rights_not_reviewed"},
        "access": "public",
        "locator": "https://example.org/synthetic/port-calder/bulletins/2027-01.csv",
        "recorded_by": "recorder:example-resolver",
        "recorded_at": "2027-02-16T09:50:00Z",
    }
    return [assessment, evaluation, descriptor]


def build_record_vectors(records: dict[str, dict]) -> dict:
    fc = records["fc-lantern-port-calder-teu-2027-01"]
    out = records["out-port-calder-teu-2027-01"]
    snap = records["res-harbor-weekly-e42-transcript"]
    q = records["q-port-calder-teu-2027-01"]
    assessment, _, descriptor = shape_examples(records)
    valid = [{"id": f"fixture-{b['id']}", "record": b} for b in records.values()]
    valid += [{"id": f"shape-{b['record_type']}", "record": b} for b in shape_examples(records)]
    valid += [
        {"id": "extension-namespaced", "record": with_value(fc, ["extensions"], {"org.example.lantern/v1": {"run": 7}})},
        {"id": "outcome-unresolved", "record": {**with_value(out, ["status"], "unresolved"), "resolved_value": None}},
        {"id": "forecast-issued-at-unknown", "record": with_value(fc, ["issued_at"], {"unknown": "provider_did_not_state"})},
        {"id": "probability-withheld", "record": with_value(fc, ["output", "probability"], {"withheld": "licence_terms"})},
        {"id": "forecast-issued-at-day-precision", "record": with_value(fc, ["issued_at"], {"date": "2026-10-01", "precision": "day"})},
        {"id": "cutoff-same-day-as-day-issued-is-indeterminate-not-refused",
         "record": {**with_value(fc, ["issued_at"], {"date": "2026-10-01", "precision": "day"}), "information_cutoff": "2026-10-01T18:00:00Z"}},
        {"id": "forecast-limitations", "record": with_value(fc, ["limitations"], ["outcome_published_before_registration", "provider_fields_withheld"])},
        {"id": "question-unknown-members", "record": {**q, **{
            "target_period": {"unknown": "provider_declares_no_target_period"},
            "forecast_deadline": {"unknown": "provider_declares_no_deadline"},
            "resolution_deadline": {"unknown": "provider_declares_no_deadline"},
            "vintage_policy": {"unknown": "provider_declares_no_vintage"},
            "transformation": {"unknown": "provider_declares_no_transformation"},
            "resolution_source": {"withheld": "provider_terms"},
            "unit": {"unknown": "provider_declares_no_unit"},
            "limitations": ["text_possibly_truncated"],
        }}},
    ]

    def case(case_id, body, layer, code, pointer, text=None):
        return {
            "id": case_id,
            "layer": layer,
            "text": text if text is not None else compact(body),
            "expect": {"code": code, "pointer": pointer},
        }

    nan_text = compact(fc).replace('"probability": 0.7', '"probability": NaN')
    assert "NaN" in nan_text
    refusals = [
        case("probability-1.2", with_value(fc, ["output", "probability"], 1.2), "schema", "out_of_range", "/output/probability"),
        case("probability--0.1", with_value(fc, ["output", "probability"], -0.1), "schema", "out_of_range", "/output/probability"),
        case("probability-true", with_value(fc, ["output", "probability"], True), "schema", "invalid_type", "/output/probability"),
        case("probability-string", with_value(fc, ["output", "probability"], "0.7"), "schema", "invalid_type", "/output/probability"),
        case("probability-raw-nan", None, "parse", "non_finite_number", "", text=nan_text),
        case("resolved-value-0.5", with_value(out, ["resolved_value"], 0.5), "schema", "invalid_value", "/resolved_value"),
        case("resolved-value-true", with_value(out, ["resolved_value"], True), "schema", "invalid_type", "/resolved_value"),
        case("resolved-value-null-when-resolved", with_value(out, ["resolved_value"], None), "schema", "null_not_allowed", "/resolved_value"),
        case("resolved-value-set-when-unresolved", with_value(out, ["status"], "unresolved"), "schema", "invalid_value", "/resolved_value"),
        case("cutoff-after-issued", with_value(fc, ["information_cutoff"], "2026-10-01T12:00:01Z"), "semantic",
             "information_cutoff_after_issued_at", "/information_cutoff"),
        case("I10-schema-0.2", with_value(fc, ["schema"], "comuvia/0.2"), "schema", "unsupported_schema_version", "/schema"),
        case("I10-schema-missing", without(fc, "schema"), "schema", "missing_required_field", "/schema"),
        case("unrecognized-member", {**fc, "confidence": 0.9}, "schema", "unrecognized_member", "/confidence"),
        case("unrecognized-nested-member", with_value(fc, ["output", "note"], "x"), "schema", "unrecognized_member", "/output/note"),
        case("missing-required-member", without(fc, "issued_at"), "schema", "missing_required_field", "/issued_at"),
        case("null-for-unknown", with_value(fc, ["issued_at"], None), "schema", "null_not_allowed", "/issued_at"),
        case("empty-string-for-unknown", with_value(snap, ["source_version"], ""), "schema", "invalid_value", "/source_version"),
        case("marker-without-reason", with_value(snap, ["source_version"], {"unknown": ""}), "schema", "invalid_marker", "/source_version/unknown"),
        case("marker-extra-member", with_value(snap, ["source_version"], {"unknown": "x", "value": "1"}), "schema", "invalid_marker",
             "/source_version/value"),
        case("marker-where-not-allowed", with_value(fc, ["recorded_at"], {"unknown": "not_recorded"}), "schema", "invalid_timestamp",
             "/recorded_at"),
        case("day-value-expanded", with_value(snap, ["source_published_at"], {"date": "2026-01-14T00:00:00Z", "precision": "day"}),
             "schema", "invalid_date", "/source_published_at/date"),
        case("day-value-impossible-date", with_value(snap, ["source_published_at"], {"date": "2026-02-30", "precision": "day"}),
             "semantic", "invalid_date", "/source_published_at/date"),
        case("timestamp-without-offset", with_value(fc, ["issued_at"], "2026-10-01T12:00:00"), "schema", "invalid_timestamp", "/issued_at"),
        case("timestamp-impossible", with_value(fc, ["issued_at"], "2026-10-01T25:00:00Z"), "semantic", "invalid_timestamp", "/issued_at"),
        case("digest-unsupported-algorithm", with_value(fc, ["question", "digest"], "sha512:" + "0" * 128), "schema",
             "unsupported_digest_algorithm", "/question/digest"),
        case("digest-uppercase", with_value(fc, ["question", "digest"], fc["question"]["digest"].upper()), "schema",
             "malformed_digest", "/question/digest"),
        case("reference-without-digest", with_value(fc, ["question"], {k: fc["question"][k] for k in ("record_type", "id", "revision")}),
             "schema", "missing_required_field", "/question/digest"),
        case("reference-wrong-type", with_value(fc, ["question", "record_type"], "outcome"), "schema", "invalid_value",
             "/question/record_type"),
        case("legacy-id-as-content-digest", with_value(snap, ["content", "digest"], {"scheme": "locator", "value": snap["locator"]}),
             "schema", "invalid_type", "/content/digest"),
        case("extension-key-not-namespaced", with_value(fc, ["extensions"], {"lantern": {}}), "schema", "invalid_extension_key",
             "/extensions/lantern"),
        case("unknown-record-type", with_value(fc, ["record_type"], "prediction"), "schema", "unknown_record_type", "/record_type"),
        case("predecessor-on-revision-1", with_value(fc, ["predecessor"], dict(fc["question"])), "semantic", "invalid_predecessor",
             "/predecessor"),
        case("period-reversed", with_value(q, ["target_period", "end"], "2026-12-31"), "semantic", "invalid_period", "/target_period"),
        case("credential-in-locator", with_value(snap, ["locator"], "https://user:secret@example.org/x"), "schema", "invalid_value",
             "/locator"),
        case("extraction-confidence-above-1", with_value(records["int-ilsley-freight-analyst-1"], ["extraction", "confidence"], 1.5),
             "schema", "out_of_range", "/extraction/confidence"),
        # OSS-1A review R3: integral floats are integers in semantic rules too.
        case("R3-coverage-integral-float-above-total",
             with_value(assessment, ["coverage"], {"scope": "sample", "items_checked": 5.0, "items_total": 3}),
             "semantic", "invalid_coverage", "/coverage"),
        case("R3-coverage-full-scope-integral-float",
             with_value(assessment, ["coverage"], {"scope": "full", "items_checked": 2.0, "items_total": 3}),
             "semantic", "invalid_coverage", "/coverage"),
        # OSS-2A part 0: limitations are required; day-precision issued_at is ordered conservatively (U5).
        case("limitations-missing", without(fc, "limitations"), "schema", "missing_required_field", "/limitations"),
        case("limitations-not-a-code", with_value(fc, ["limitations"], ["Text Possibly Truncated"]), "schema", "invalid_value",
             "/limitations/0"),
        case("limitations-repeated", with_value(fc, ["limitations"], ["text_possibly_truncated", "text_possibly_truncated"]),
             "schema", "invalid_value", "/limitations"),
        case("cutoff-definitely-after-day-issued",
             {**with_value(fc, ["issued_at"], {"date": "2026-10-01", "precision": "day"}), "information_cutoff": "2026-10-03T00:00:00Z"},
             "semantic", "information_cutoff_after_issued_at", "/information_cutoff"),
        # OSS-1A review R4: time order is exact at the written precision.
        case("R4-cutoff-100ns-after-issued", with_value(fc, ["information_cutoff"], "2026-10-01T12:00:00.0000001Z"),
             "semantic", "information_cutoff_after_issued_at", "/information_cutoff"),
        # Usability triage F1: artifact_descriptor.content always identifies retained bytes (no 'retained' member).
        case("F1-artifact-descriptor-retained-member", with_value(descriptor, ["content", "retained"], True),
             "schema", "unrecognized_member", "/content/retained"),
    ]
    return {
        "description": "Single-record validation vectors: valid records and named refusals (review sections 5-7).",
        "generated_by": "tools/sync_vectors.py",
        "layers": {
            "parse": "refused by the strict JSON parser before validation",
            "schema": "refused by the packaged JSON Schemas",
            "semantic": "schema-valid; refused by a rule JSON Schema cannot express",
        },
        "valid": valid,
        "refusals": refusals,
    }


def build_evaluation_vectors(records: dict[str, dict]) -> dict:
    """Evaluation cases: records in, counts and per-candidate status/reasons/loss out."""
    from comuvia import reference_to
    from comuvia.evaluation import load_rule

    q = records["q-port-calder-teu-2027-01"]
    fc = records["fc-lantern-port-calder-teu-2027-01"]
    res = records["res-port-calder-bulletin-2027-01-first"]
    out = records["out-port-calder-teu-2027-01"]
    narrative = [records[i] for i in (
        "res-harbor-weekly-e42-transcript", "asr-harbor-weekly-e42-ilsley-freight", "int-ilsley-freight-analyst-1")]
    fc_id, out_id = fc["id"], out["id"]

    def loss(p, o):
        d = p - o
        return d * d

    def forecast(body=fc, **changes):
        body = copy.deepcopy(body)
        for path, value in changes.items():
            target = body
            keys = path.split("/")
            for k in keys[:-1]:
                target = target[k]
            target[keys[-1]] = value
        return body

    def outcome(**changes):
        return forecast(out, **changes)

    def scored(value):
        return {"status": "scored", "reasons": [], "loss": value}

    def excluded(*why):
        return {"status": "excluded", "reasons": list(why), "loss": None}

    def unresolved(*why):
        return {"status": "unresolved", "reasons": list(why), "loss": None}

    def case(case_id, bodies, expect_results, counts=None, description=None):
        entry = {"id": case_id}
        if description:
            entry["description"] = description
        entry["records"] = bodies
        entry["expect"] = {"results": expect_results}
        if counts:
            entry["expect"]["counts"] = counts
        return entry

    base = [q, res]
    q2 = {**copy.deepcopy(q), "revision": 2, "predecessor": reference_to(q),
          "recorded_at": "2026-09-20T00:00:00Z"}
    out_on_q2 = outcome(question=reference_to(q2))
    variant = forecast(id="fc-lantern-port-calder-teu-2027-01-variant-b",
                       **{"output/probability": 0.6, "model": {"id": "lantern-demo", "version": "0.0.2-synthetic"}})
    other_family = forecast(id="fc-harbourline-port-calder-teu-2027-01", forecast_family="fam-harbourline-port-calder-teu-2027-01",
                            provider={"id": "harbourline-synthetic", "name": "Harbourline (fictional provider)"},
                            recorded_by="provider:harbourline-synthetic", **{"output/probability": 0.8})
    second_outcome = outcome(id="out-port-calder-teu-2027-01-other-desk", recorded_by="recorder:example-other-desk")
    corrected = outcome(revision=2, predecessor=reference_to(out), resolved_value=0, recorded_at="2027-02-20T10:00:00Z")
    many = forecast(conditions=[{"text": "Meridian Canal stays open", "state": "unresolved"}],
                    issued_at={"unknown": "provider_did_not_state"})

    def with_question(**changes):
        """A changed question plus the Fixture B forecast and outcome relinked to its digest."""
        q_changed = forecast(q, **changes)
        return [q_changed, res, forecast(question=reference_to(q_changed)), outcome(question=reference_to(q_changed))]

    def day(date):
        return {"date": date, "precision": "day"}

    part0 = [
        case("forecast-deadline-unknown", with_question(forecast_deadline={"unknown": "provider_declares_no_deadline"}),
             {fc_id: excluded("missing_required_time")}),
        case("question-target-period-unknown", with_question(target_period={"unknown": "provider_declares_no_target_period"}),
             {fc_id: excluded("incomplete_question")}),
        case("question-resolution-source-withheld", with_question(resolution_source={"withheld": "provider_terms"}),
             {fc_id: excluded("incomplete_question")}),
        case("question-unit-unknown", with_question(unit={"unknown": "provider_declares_no_unit"}),
             {fc_id: excluded("incomplete_question")},
             description="An unknown question unit is incomplete (rule version 3) and never compared with observed.unit."),
        case("issued-day-on-deadline-day", [*base, forecast(issued_at=day("2026-12-31")), out],
             {fc_id: excluded("indeterminate_time_order")},
             description="Day precision is never expanded to midnight (U5); its order against 23:59:59Z that day is indeterminate."),
        case("issued-day-well-before-deadline", [*base, forecast(issued_at=day("2026-10-01")), out],
             {fc_id: scored(0.09000000000000002)}),
        case("issued-day-after-deadline-day", [*base, forecast(issued_at=day("2027-01-02")), out],
             {fc_id: excluded("issued_after_forecast_deadline")}),
        case("limitation-retrospective-registration", [*base, forecast(limitations=["outcome_published_before_registration"]), out],
             {fc_id: excluded("retrospective_registration")}),
        case("limitation-truncated-question-text", with_question(limitations=["text_possibly_truncated"]),
             {fc_id: excluded("resolution_rule_incomplete")}),
        case("limitation-not-excluding", [*base, forecast(limitations=["provider_fields_withheld"]), out],
             {fc_id: scored(0.09000000000000002)},
             description="Limitation codes not named in the rule's limitation_exclusions are reported but do not exclude."),
    ]

    cases = [
        case("fixture-b-eligible", [*base, fc, out], {fc_id: scored(0.09000000000000002)},
             {"candidates": 1, "forecasts": 1, "independent_questions": 1, "forecast_families": 1,
              "eligible": 1, "scored": 1, "unresolved": 0, "excluded": 0}),
        case("fixture-b-counterfactual-outcome-0", [*base, fc, outcome(resolved_value=0)], {fc_id: scored(0.48999999999999994)}),
        case("fixture-a-narrative", narrative, {
            "asr-harbor-weekly-e42-ilsley-freight": excluded("no_declared_probability", "conditional_scenario", "no_pinned_question"),
            "int-ilsley-freight-analyst-1": excluded("not_a_forecast", "conditional_scenario"),
        }, {"candidates": 2, "forecasts": 0, "eligible": 0, "scored": 0, "unresolved": 0, "excluded": 2}),
        case("question-mismatch", [q, q2, res, fc, out_on_q2], {fc_id: excluded("question_mismatch")},
             description="The outcome pins question r2; the forecast pins r1."),
        case("unit-mismatch", [*base, fc, outcome(**{"observed/unit": "tonnes"})], {fc_id: excluded("unit_mismatch")}),
        case("issued-after-deadline", [*base, forecast(issued_at="2027-01-01T00:00:00Z"), out],
             {fc_id: excluded("issued_after_forecast_deadline")}),
        case("issued-after-deadline-by-100ns", [*base, forecast(issued_at="2026-12-31T23:59:59.0000001Z"), out],
             {fc_id: excluded("issued_after_forecast_deadline")}),
        case("issued-exactly-at-deadline", [*base, forecast(issued_at="2026-12-31T23:59:59.000000000Z"), out],
             {fc_id: scored(0.09000000000000002)}),
        case("issued-at-unknown", [*base, forecast(issued_at={"unknown": "provider_did_not_state"}), out],
             {fc_id: excluded("missing_required_time")}),
        case("conditional-forecast", [*base, forecast(conditions=[{"text": "Meridian Canal stays open", "state": "unresolved"}]), out],
             {fc_id: excluded("conditional_scenario")}),
        case("conditions-unknown", [*base, forecast(conditions={"unknown": "provider_did_not_state"}), out],
             {fc_id: excluded("unknown_conditions")}),
        case("probability-withheld", [*base, forecast(**{"output/probability": {"withheld": "licence_terms"}}), out],
             {fc_id: excluded("no_declared_probability")}),
        case("outcome-unresolved", [*base, fc, outcome(status="unresolved", resolved_value=None)],
             {fc_id: unresolved("unresolved_outcome")}, {"unresolved": 1, "scored": 0, "excluded": 0}),
        case("outcome-ambiguous", [*base, fc, outcome(status="ambiguous", resolved_value=None)],
             {fc_id: excluded("ambiguous_outcome")}, {"excluded": 1}),
        case("outcome-annulled", [*base, fc, outcome(status="annulled", resolved_value=None)],
             {fc_id: excluded("annulled_question")}, {"excluded": 1}),
        case("no-outcome-recorded", [*base, fc], {fc_id: unresolved("no_outcome_recorded")}, {"unresolved": 1}),
        case("multiple-outcome-ids", [*base, fc, out, second_outcome], {fc_id: excluded("multiple_outcomes")}),
        case("every-failing-reason", [*base, many, outcome(**{"observed/unit": "tonnes"}, status="ambiguous", resolved_value=None)],
             {fc_id: excluded("conditional_scenario", "missing_required_time", "unit_mismatch", "ambiguous_outcome")},
             description="Every failing check is reported, in rule order, not only the first."),
        case("two-variants-one-family", [*base, fc, variant, out], {
            fc_id: scored(0.09000000000000002),
            variant["id"]: scored(loss(0.6, 1)),
        }, {"forecasts": 2, "independent_questions": 1, "forecast_families": 1, "scored": 2}),
        case("two-families-one-question", [*base, fc, other_family, out], {
            fc_id: scored(0.09000000000000002),
            other_family["id"]: scored(loss(0.8, 1)),
        }, {"forecasts": 2, "independent_questions": 1, "forecast_families": 2}),
        case("corrected-outcome-latest-revision", [*base, fc, out, corrected], {fc_id: scored(0.48999999999999994)},
             description="Outcome r2 corrects r1; evaluation uses the latest revision."),
        *part0,
    ]
    return {
        "description": "Eligibility and binary-brier-v1 vectors: records in; counts and per-candidate status, reasons and loss out.",
        "generated_by": "tools/sync_vectors.py",
        "scoring_rule": load_rule().reference(),
        "conventions": {
            "results": "keyed by candidate record id; every candidate in a case is listed",
            "counts": "only the listed counts are asserted",
            "loss": "exact binary64 value; d = p - o; loss = d * d",
        },
        "cases": cases,
    }


def _ots_varuint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _ots_varbytes(data: bytes) -> bytes:
    return _ots_varuint(len(data)) + data


def build_ots_vectors() -> dict:
    """Language-neutral OpenTimestamps detached-proof vectors shared by comuvia.ots and foreglass.verify."""
    from comuvia.ots import ATTESTATION_TAGS, OTS_MAGIC, OTS_VERSION

    btc_tag = bytes.fromhex("0588960d73d71901")
    pending_tag = bytes.fromhex("83dfe30d2ef90c8e")
    ltc_tag = bytes.fromhex("06869a0d73d71b45")
    eth_tag = bytes.fromhex("30fe8087b5c7ead7")
    unknown_tag = bytes.fromhex("deadbeefcafebabe")
    assert ATTESTATION_TAGS[btc_tag] == "bitcoin"

    # Case 1: SHA-256 with pending calendars + Bitcoin block-header attestations
    msg1 = hashlib.sha256(b"synthetic comuvia ots vector 1\n").digest()
    nonce1 = b"synthetic-nonce-01"
    inner1 = hashlib.sha256(msg1 + nonce1).digest()
    cals1 = ["https://calendar-a.example.org", "https://calendar-b.example.org"]
    heights1 = [100200, 100205]
    body1 = b""
    for uri in cals1:
        body1 += b"\xff\x00" + pending_tag + _ots_varbytes(_ots_varbytes(uri.encode("utf-8")))
    roots1 = []
    for idx, height in enumerate(heights1):
        prefix = bytes([idx + 1]) * 4
        branch = b"\xf1" + _ots_varbytes(prefix) + b"\x08\x00" + btc_tag + _ots_varbytes(_ots_varuint(height))
        roots1.append(hashlib.sha256(prefix + inner1).digest()[::-1].hex())
        body1 += (b"\xff" if idx < len(heights1) - 1 else b"") + branch
    proof1 = OTS_MAGIC + _ots_varuint(OTS_VERSION) + b"\x08" + msg1 + b"\xf0" + _ots_varbytes(nonce1) + b"\x08" + body1

    # Case 2: reverse (0xF2), hexlify (0xF3), prepend (0xF1), sha256 (0x08), litecoin, ethereum & unknown tags
    msg2 = hashlib.sha256(b"synthetic comuvia ots vector 2\n").digest()
    rev_hex = msg2[::-1].hex().encode("ascii")
    leaf2 = hashlib.sha256(b"pre" + rev_hex).digest()
    root2 = leaf2[::-1].hex()
    att_ltc = b"\x00" + ltc_tag + _ots_varbytes(_ots_varuint(2500000))
    att_eth = b"\x00" + eth_tag + _ots_varbytes(_ots_varuint(19000000))
    att_unk = b"\x00" + unknown_tag + _ots_varbytes(b"\x01\x02\x03")
    proof2 = (
        OTS_MAGIC + _ots_varuint(OTS_VERSION) + b"\x08" + msg2
        + b"\xf2\xf3\xf1" + _ots_varbytes(b"pre") + b"\x08"
        + b"\xff" + att_ltc + b"\xff" + att_eth + att_unk
    )

    # Case 3: keccak256 initial digest (0x67) + keccak256 op (0x67) -> unavailable commitment (None)
    msg3 = bytes(range(32))
    proof3 = OTS_MAGIC + _ots_varuint(OTS_VERSION) + b"\x67" + msg3 + b"\x67\x00" + btc_tag + _ots_varbytes(_ots_varuint(900000))

    valid = [
        {
            "id": "sha256-bitcoin-and-pending",
            "proof_hex": proof1.hex(),
            "expect": {
                "digest_type": "sha256",
                "digest": msg1.hex(),
                "operations": 6,
                "attestations": [
                    {"kind": "pending", "height": None, "uri": cals1[0], "merkle_root_display": None},
                    {"kind": "pending", "height": None, "uri": cals1[1], "merkle_root_display": None},
                    {"kind": "bitcoin", "height": heights1[0], "uri": None, "merkle_root_display": roots1[0]},
                    {"kind": "bitcoin", "height": heights1[1], "uri": None, "merkle_root_display": roots1[1]},
                ],
            },
        },
        {
            "id": "sha256-reverse-hexlify-multichain-and-unknown",
            "proof_hex": proof2.hex(),
            "expect": {
                "digest_type": "sha256",
                "digest": msg2.hex(),
                "operations": 4,
                "attestations": [
                    {"kind": "litecoin", "height": 2500000, "uri": None, "merkle_root_display": root2},
                    {"kind": "ethereum", "height": 19000000, "uri": None, "merkle_root_display": root2},
                    {"kind": "unknown", "height": None, "uri": None, "merkle_root_display": None},
                ],
            },
        },
        {
            "id": "keccak256-unavailable-operation",
            "proof_hex": proof3.hex(),
            "expect": {
                "digest_type": "keccak256",
                "digest": msg3.hex(),
                "operations": 1,
                "attestations": [
                    {"kind": "bitcoin", "height": 900000, "uri": None, "merkle_root_display": None},
                ],
            },
        },
    ]

    header_ok = OTS_MAGIC + _ots_varuint(OTS_VERSION) + b"\x08" + msg1
    refusals = [
        {"id": "bad-magic", "proof_hex": (b"not-ots-magic" + proof1[13:]).hex(), "expect_error": "magic bytes"},
        {"id": "unsupported-version", "proof_hex": (OTS_MAGIC + _ots_varuint(2) + b"\x08" + msg1).hex(), "expect_error": "unsupported proof version 2"},
        {"id": "unknown-digest-type", "proof_hex": (OTS_MAGIC + _ots_varuint(1) + b"\x99" + msg1).hex(), "expect_error": "unknown digest type 0x99"},
        {"id": "truncated-digest", "proof_hex": (OTS_MAGIC + _ots_varuint(1) + b"\x08" + msg1[:10]).hex(), "expect_error": "truncated"},
        {"id": "trailing-bytes", "proof_hex": (proof1 + b"\x00").hex(), "expect_error": "trailing bytes after the proof"},
        {"id": "varuint-too-long", "proof_hex": (OTS_MAGIC + b"\x80" * 11).hex(), "expect_error": "varuint longer than 10 bytes"},
        {"id": "argument-exceeds-limit", "proof_hex": (header_ok + b"\xf0" + _ots_varuint(4097) + b"x").hex(), "expect_error": "length 4097 exceeds 4096"},
        {
            "id": "message-exceeds-4096",
            "proof_hex": (header_ok + b"\xf0" + _ots_varbytes(b"a" * 2100) + b"\xf0" + _ots_varbytes(b"b" * 2100)).hex(),
            "expect_error": "message longer than 4096 bytes",
        },
        {"id": "unknown-op-tag", "proof_hex": (header_ok + b"\xaa").hex(), "expect_error": "unknown op tag 0xaa"},
        {
            "id": "bitcoin-payload-trailing",
            "proof_hex": (header_ok + b"\x00" + btc_tag + _ots_varbytes(_ots_varuint(100) + b"\x00")).hex(),
            "expect_error": "bitcoin attestation payload has trailing bytes",
        },
        {
            "id": "pending-uri-invalid-utf8",
            "proof_hex": (header_ok + b"\x00" + pending_tag + _ots_varbytes(_ots_varbytes(b"\xff\xfe"))).hex(),
            "expect_error": "pending attestation URI is not UTF-8",
        },
        {
            "id": "nesting-too-deep",
            "proof_hex": (header_ok + b"\x08" * 258 + b"\x00" + btc_tag + _ots_varbytes(_ots_varuint(1))).hex(),
            "expect_error": "nesting deeper than 256",
        },
    ]
    return {
        "description": "OpenTimestamps detached-proof vectors shared by comuvia.ots and foreglass.verify (fictional inputs only).",
        "generated_by": "tools/sync_vectors.py",
        "valid": valid,
        "refusals": refusals,
    }


def _pascal(text: str) -> str:
    return "".join(part.capitalize() for part in text.split("_"))


def build_types_module() -> bytes:
    """Generate packages/comuvia/src/comuvia/types.py deterministically from schemas/v0_1/*.json."""
    common = json.loads((SCHEMAS / "common.json").read_text(encoding="utf-8"))["$defs"]
    record_names = [
        "resource_snapshot", "source_assertion", "interpretation", "assessment",
        "question", "forecast", "outcome", "evaluation", "artifact_descriptor",
    ]
    schemas = {name: json.loads((SCHEMAS / f"{name}.json").read_text(encoding="utf-8")) for name in record_names}

    ref_aliases = {
        "schema_version": 'Literal["comuvia/0.1"]',
        "record_type": "RecordType",
        "identifier": "str",
        "agent": "str",
        "code": "str",
        "text": "str",
        "revision": "int",
        "data_origin": "DataOrigin",
        "timestamp": "str",
        "date": "str",
        "day_value": "DayValue",
        "time_point": "TimePoint",
        "period": "Period",
        "unknown_marker": "UnknownMarker",
        "withheld_marker": "WithheldMarker",
        "digest": "str",
        "reference": "RecordReference",
        "predecessor": "RecordReference | None",
        "probability": "float",
        "unit_interval": "float",
        "count": "int",
        "language": "str",
        "media_type": "str",
        "locator": "str",
        "legacy_id": "LegacyId",
        "legacy_ids": "list[LegacyId]",
        "condition": "Condition",
        "codes": "list[str]",
        "limitations": "list[str]",
        "vintage": "Vintage",
        "extensions": "dict[str, Any]",
    }
    assert set(ref_aliases) == set(common), f"common.json $defs changed: {set(common) ^ set(ref_aliases)}"

    nested_defs: list[str] = []

    def type_expr(node: dict, prefix: str) -> str:
        if "$ref" in node:
            ref_name = node["$ref"].split("#/$defs/", 1)[1]
            return ref_aliases[ref_name]
        if "allOf" in node:
            # Typed record reference (e.g. reference constrained to record_type == "question")
            return "RecordReference"
        if "anyOf" in node:
            parts = [type_expr(sub, prefix) for sub in node["anyOf"]]
            deduped = list(dict.fromkeys(parts))
            return " | ".join(deduped)
        if "const" in node:
            val = node["const"]
            return "None" if val is None else f"Literal[{json.dumps(val)}]"
        if "enum" in node:
            lits = []
            has_none = False
            for opt in node["enum"]:
                if opt is None:
                    has_none = True
                else:
                    lits.append(json.dumps(opt))
            base = f"Literal[{', '.join(lits)}]" if lits else "None"
            return f"{base} | None" if has_none and lits else base
        kind = node.get("type")
        if kind == "null":
            return "None"
        if kind == "boolean":
            return "bool"
        if kind == "string":
            return "str"
        if kind == "integer":
            return "int"
        if kind == "number":
            return "float"
        if kind == "array":
            item_t = type_expr(node["items"], prefix + "Item") if "items" in node else "Any"
            return f"list[{item_t}]"
        if kind == "object":
            props = node.get("properties")
            if not props:
                return "dict[str, Any]"
            req = set(node.get("required", []))
            lines = [f"class {prefix}(TypedDict):"]
            for prop_name, prop_schema in props.items():
                prop_t = type_expr(prop_schema, f"{prefix}{_pascal(prop_name)}")
                if prop_name not in req:
                    prop_t = f"NotRequired[{prop_t}]"
                lines.append(f"    {prop_name}: {prop_t}")
            nested_defs.append("\n".join(lines))
            return prefix
        raise RuntimeError(f"unhandled schema node at {prefix}: {node}")

    record_defs: list[str] = []
    record_classes: list[str] = []
    for name in record_names:
        cls_name = f"{_pascal(name)}Record"
        record_classes.append(cls_name)
        schema = schemas[name]
        req = set(schema["required"])
        lines = [f"class {cls_name}(TypedDict):"]
        for prop_name, prop_schema in schema["properties"].items():
            prop_t = type_expr(prop_schema, f"{_pascal(name)}{_pascal(prop_name)}")
            if prop_name not in req:
                prop_t = f"NotRequired[{prop_t}]"
            lines.append(f"    {prop_name}: {prop_t}")
        record_defs.append("\n".join(lines))

    record_literals = ", ".join(f'"{n}"' for n in record_names)
    exported = [
        "AnyRecord", "Condition", "DataOrigin", "DayValue", "LegacyId", "Marker",
        "Period", "RecordReference", "RecordType", "TimePoint", "UnknownMarker",
        "Vintage", "WithheldMarker", *sorted(record_classes),
    ]
    header = f'''"""Static ``TypedDict`` definitions for ``comuvia/0.1`` records (generated by ``tools/sync_vectors.py``).

Generated deterministically from ``comuvia/schemas/v0_1/*.json``; do not edit by hand.
Import on demand (``from comuvia.types import ForecastRecord, UnknownMarker``). Static
types aid editors and type checkers; runtime validation remains ``comuvia.validate()``.
"""

from typing import Any, Literal, NotRequired, TypedDict

RecordType = Literal[{record_literals}]
DataOrigin = Literal["observed", "synthetic"]
Vintage = Literal["first_release", "latest_release"]


class DayValue(TypedDict):
    date: str
    precision: Literal["day"]


TimePoint = str | DayValue


class Period(TypedDict):
    start: str
    end: str
    inclusive: bool
    precision: Literal["day"]


class UnknownMarker(TypedDict):
    unknown: str
    note: NotRequired[str]


class WithheldMarker(TypedDict):
    withheld: str
    note: NotRequired[str]


Marker = UnknownMarker | WithheldMarker


class RecordReference(TypedDict):
    record_type: RecordType
    id: str
    revision: int
    digest: str


class LegacyId(TypedDict):
    scheme: str
    value: str


class Condition(TypedDict):
    text: str
    state: Literal["unresolved", "occurred", "not_occurred"]
    note: NotRequired[str]
'''
    body = (
        header
        + "\n\n"
        + "\n\n\n".join(nested_defs)
        + "\n\n\n"
        + "\n\n\n".join(record_defs)
        + f"\n\n\nAnyRecord = {' | '.join(record_classes)}\n\n"
        + "__all__ = [\n"
        + "".join(f'    "{item}",\n' for item in exported)
        + "]\n"
    )
    return body.encode("utf-8")


def main() -> int:
    check = "--check" in sys.argv[1:]
    outputs: dict[Path, bytes] = {}
    records: dict[str, dict] = {}
    sources: dict[str, bytes] = {}
    for name in CORE_FIXTURES:
        directory = FIXTURES / name
        fixture_outputs, by_id, source_for = sync_fixture(directory)
        outputs.update(fixture_outputs)
        records.update(by_id)
        sources.update(source_for)
    outputs[VECTORS / "identity.json"] = dump(build_identity_vectors(records, sources))
    outputs[VECTORS / "records.json"] = dump(build_record_vectors(records))
    outputs[VECTORS / "evaluation.json"] = dump(build_evaluation_vectors(records))
    ots_bytes = dump(build_ots_vectors())
    outputs[VECTORS / "ots.json"] = ots_bytes
    if FOREGLASS_VERIFY.is_file():
        outputs[FOREGLASS_VECTORS / "ots.json"] = ots_bytes
    outputs[TYPES_PATH] = build_types_module()
    stale = [p for p, data in outputs.items() if not p.exists() or p.read_bytes() != data]
    if check:
        for path in stale:
            print(f"STALE {path.relative_to(REPO).as_posix()}")
        print("PASS" if not stale else "FAIL")
        return 1 if stale else 0
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(outputs[path])
        print(f"wrote {path.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
