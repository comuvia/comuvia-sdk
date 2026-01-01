"""Run the language-neutral vectors in tests/vectors against the installed comuvia package."""

import base64
import json
import math
import random
import struct
import unittest
from pathlib import Path

import comuvia
from comuvia import (
    RefusalError,
    canonicalize,
    content_digest,
    load_record,
    parse_json,
    record_digest,
    revision_conflicts,
    validate,
    verify,
)

VECTORS = Path(__file__).resolve().parent / "vectors"


def load(name):
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


def pointer_get(document, pointer):
    for token in pointer.split("/")[1:]:
        document = document[token.replace("~1", "/").replace("~0", "~")]
    return document


def refusal_codes(data):
    try:
        parse_json(data)
    except RefusalError as error:
        return error.codes
    return frozenset()


class CanonicalizationVectors(unittest.TestCase):
    """I1-I6: RFC 8785 examples, key order, numbers, strings, invariance, parse refusals."""

    def test_cases(self):
        cases = load("canonicalization.json")["cases"]
        self.assertGreaterEqual(len(cases), 50)
        for case in cases:
            with self.subTest(case["id"]):
                expect = case["expect"]
                if "ieee754_hex" in case:
                    value = struct.unpack(">d", bytes.fromhex(case["ieee754_hex"]))[0]
                    if "refusal" in expect:
                        with self.assertRaises(RefusalError) as caught:
                            canonicalize(value)
                        self.assertIn(expect["refusal"], caught.exception.codes)
                    else:
                        self.assertEqual(canonicalize(value).decode("utf-8"), expect["number_text"])
                    continue
                if "inputs" in case:
                    outputs = {canonicalize(parse_json(text)) for text in case["inputs"]}
                    self.assertEqual(outputs, {expect["canonical_text"].encode("utf-8")})
                    digests = {record_digest(parse_json(text)) for text in case["inputs"]}
                    self.assertEqual(len(digests), 1)
                    continue
                if case.get("stage") == "canonicalize":
                    value: list = []
                    for _ in range(case["nested_arrays"] - 1):
                        value = [value]
                    with self.assertRaises(RefusalError) as caught:
                        canonicalize(value)
                    self.assertIn(expect["refusal"], caught.exception.codes)
                    continue
                if "nested_arrays" in case:
                    data = ("[" * case["nested_arrays"] + "]" * case["nested_arrays"]).encode("ascii")
                elif "input_hex" in case:
                    data = bytes.fromhex(case["input_hex"])
                else:
                    data = case["input_text"].encode("utf-8")
                if "refusal" in expect:
                    self.assertIn(expect["refusal"], refusal_codes(data))
                    continue
                canonical = canonicalize(parse_json(data))
                self.assertEqual(canonicalize(parse_json(canonical)), canonical, "not idempotent")
                if "canonical_hex" in expect:
                    self.assertEqual(canonical.hex(), expect["canonical_hex"])
                if "canonical_text" in expect:
                    self.assertEqual(canonical, expect["canonical_text"].encode("utf-8"))
                if "value_order" in expect:
                    self.assertEqual(list(json.loads(canonical).values()), expect["value_order"])


class CanonicalIdempotence(unittest.TestCase):
    """R1: canonical output always parses back to the same canonical bytes (seeded, stdlib only)."""

    def assert_idempotent(self, value):
        canonical = canonicalize(value)
        self.assertEqual(canonicalize(parse_json(canonical)), canonical, canonical[:80])

    def test_random_binary64(self):
        rng = random.Random(8785)
        checked = 0
        while checked < 100_000:
            value = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
            if math.isfinite(value):
                self.assert_idempotent(value)
                checked += 1

    def test_large_integral_doubles(self):
        rng = random.Random(53)
        for exponent in range(53, 1024):
            for _ in range(20):
                value = float(rng.getrandbits(53) | (1 << 52)) * 2.0 ** (exponent - 52)
                self.assert_idempotent(value)
                self.assert_idempotent(-value)
                if value < 1e21:
                    self.assert_idempotent(int(value))

    def test_random_documents(self):
        rng = random.Random(20260924)

        def value(depth):
            kind = rng.randrange(6 if depth < 5 else 3)
            if kind == 0:
                return rng.choice([None, True, False, "", "a" + chr(0) + chr(0xE9) + chr(0x1F600)])
            if kind == 1:
                return rng.choice([rng.randrange(-(2**53) + 1, 2**53), float(rng.getrandbits(60))])
            if kind == 2:
                return rng.uniform(-1e6, 1e6) * 10 ** rng.randrange(-30, 30)
            if kind in (3, 4):
                return {f"k{rng.randrange(99)}": value(depth + 1) for _ in range(rng.randrange(0, 5))}
            return [value(depth + 1) for _ in range(rng.randrange(0, 5))]

        for _ in range(3_000):
            self.assert_idempotent(value(0))


class IdentityVectors(unittest.TestCase):
    """I7-I9, I11, I12 and day precision."""

    @classmethod
    def setUpClass(cls):
        cls.document = load("identity.json")
        cls.records = cls.document["records"]
        cls.sources = {k: base64.b64decode(v) for k, v in cls.document["sources_base64"].items()}

    def run_verify(self, case):
        expect = case["expect"]
        bodies = [self.records[i] for i in case["records"]] if isinstance(case.get("records"), list) and "record" not in case else [case["record"]]
        targets = list(self.records.values()) if "records" in case else []
        for body in bodies:
            content = base64.b64decode(case["content_base64"]) if "content_base64" in case else self.sources.get(body["id"])
            expected_digest = case.get("expected_digest")
            if case["id"] == "fixture-digests":
                expected_digest = record_digest(self.records[body["id"]])
            result = verify(body, expected_digest=expected_digest, content=content, records=targets)
            self.assertEqual(sorted(i.code for i in result.issues), sorted(expect["codes"]), body["id"])
            self.assertEqual(result.timestamp_assurance, "unavailable")
            self.assertEqual(result.signature, "none")
            self.assertFalse(hasattr(result, "verified"))
            if "record_identity" in expect:
                self.assertEqual(result.record_identity, expect["record_identity"])
            if "content_identity" in expect:
                self.assertEqual(result.content_identity, expect["content_identity"])
            if expect.get("references") == "match":
                self.assertTrue(all(r.result == "match" for r in result.references), result.references)
            elif isinstance(expect.get("references"), dict):
                self.assertEqual({r.pointer: r.result for r in result.references}, expect["references"])
            if expect.get("valid"):
                self.assertEqual(validate(body), [])

    def test_cases(self):
        for case in self.document["cases"]:
            with self.subTest(case["id"]):
                kind = case["kind"]
                if kind == "verify":
                    self.run_verify(case)
                elif kind == "distinct_identities":
                    body = case["record"]
                    content = content_digest(self.sources[body["id"]])
                    self.assertEqual(content, body["content"]["digest"])
                    self.assertEqual(len({case["locator_hash"], content, record_digest(body)}), 3)
                elif kind == "digest_differs":
                    self.assertNotEqual(record_digest(case["record"]), record_digest(case["other"]))
                    self.assertEqual(validate(case["other"]), [])
                elif kind == "round_trip":
                    text = canonicalize(case["record"])
                    again = parse_json(text)
                    self.assertEqual(canonicalize(again), text)
                    self.assertEqual(pointer_get(again, case["expect"]["pointer"]), case["expect"]["value"])
                    if "canonical_contains" in case["expect"]:
                        self.assertIn(case["expect"]["canonical_contains"].encode("utf-8"), text)
                        self.assertNotIn(b"T00:00:00", text)
                elif kind == "revision_conflicts":
                    codes = [i.code for i in revision_conflicts(case["records"])]
                    self.assertEqual(codes, case["expect"]["codes"])
                else:
                    self.fail(f"unknown vector kind {kind}")


class RecordVectors(unittest.TestCase):
    """Valid records are accepted; every refusal vector is refused with its code."""

    @classmethod
    def setUpClass(cls):
        cls.document = load("records.json")

    def test_valid(self):
        types = set()
        for case in self.document["valid"]:
            with self.subTest(case["id"]):
                self.assertEqual(validate(case["record"]), [])
                text = json.dumps(case["record"], ensure_ascii=False).encode("utf-8")
                self.assertEqual(load_record(text), case["record"])
                types.add(case["record"]["record_type"])
        self.assertEqual(types, set(comuvia.RECORD_TYPES))

    def test_refusals(self):
        for case in self.document["refusals"]:
            with self.subTest(case["id"]):
                expect = case["expect"]
                with self.assertRaises(RefusalError) as caught:
                    load_record(case["text"].encode("utf-8"))
                found = {(i.code, i.pointer) for i in caught.exception.issues}
                self.assertIn((expect["code"], expect["pointer"]), found)


class EvaluationVectors(unittest.TestCase):
    """Eligibility, exclusions, counts and exact binary64 losses."""

    def test_cases(self):
        document = load("evaluation.json")
        self.assertEqual(document["scoring_rule"], comuvia.load_rule().reference())
        codes = set()
        for case in document["cases"]:
            with self.subTest(case["id"]):
                for body in case["records"]:
                    self.assertEqual(validate(body), [], body["id"])
                report = comuvia.evaluate(case["records"])
                got = {r.record["id"]: {"status": r.status, "reasons": list(r.reasons), "loss": r.loss} for r in report.results}
                self.assertEqual(got, case["expect"]["results"])
                for name, value in case["expect"].get("counts", {}).items():
                    self.assertEqual(report.counts[name], value, name)
                self.assertIsNone(report.as_json()["aggregate"])
                codes.update(code for r in report.results for code in r.reasons)
        required = {
            "question_mismatch", "unit_mismatch", "issued_after_forecast_deadline", "missing_required_time",
            "conditional_scenario", "unresolved_outcome", "ambiguous_outcome", "annulled_question",
            "no_declared_probability", "no_pinned_question", "not_a_forecast", "unknown_conditions",
        }
        self.assertLessEqual(required, codes)


class RuleVersions(unittest.TestCase):
    """0.1.0 ships one scoring-rule descriptor; pre-release descriptors are not supported."""

    def test_single_released_descriptor(self):
        rule = comuvia.load_rule()
        self.assertEqual((rule.id, rule.version), ("binary-brier-v1", "1"))
        self.assertEqual(rule.digest, "sha256:9a0180cf0678614b3d423ca8e641bff9805e8582ce898438d8586251f96877c1")
        self.assertEqual(comuvia.load_rule("binary-brier-v1", "1"), rule)
        self.assertNotIn("supersedes", rule.descriptor)
        self.assertIn("unit", rule.descriptor["question_completeness"])
        for version in ("2", "3"):
            with self.assertRaises(KeyError):
                comuvia.load_rule("binary-brier-v1", version)

    def test_pre_release_evaluations_are_not_reproduced(self):
        records = load("identity.json")["records"]
        fixture_b = [records[i] for i in (
            "q-port-calder-teu-2027-01", "fc-lantern-port-calder-teu-2027-01",
            "res-port-calder-bulletin-2027-01-first", "out-port-calder-teu-2027-01")]
        stamp = {"evaluated_at": "2027-02-17T00:00:00Z", "recorded_by": "evaluator:test", "recorded_at": "2027-02-17T00:00:00Z"}
        (body,) = comuvia.evaluation_records(comuvia.evaluate(fixture_b), fixture_b, **stamp)
        self.assertEqual(comuvia.reproduce(body, fixture_b).result, "match")
        pre_release = {"id": "binary-brier-v1", "version": "1",
                       "digest": "sha256:5b31e24c62755b3a8271450c9cffab544563ed24f86f13c0f816d61cc7723a41"}
        self.assertEqual(comuvia.reproduce({**body, "scoring_rule": pre_release}, fixture_b).reason, "rule_not_found")


class SchemaResources(unittest.TestCase):
    def test_schema_tree_is_packaged(self):
        names = sorted(e.name for e in comuvia.schema_files().iterdir() if e.name.endswith(".json"))
        self.assertEqual(names, sorted(["common.json", *(f"{t}.json" for t in comuvia.RECORD_TYPES)]))
        for entry in comuvia.schema_files().iterdir():
            if entry.name.endswith(".json"):
                schema = parse_json(entry.read_bytes())
                self.assertTrue(schema["$id"].startswith("urn:comuvia:schema:0.1:"), entry.name)
                self.assertNotIn("http", schema["$id"])


if __name__ == "__main__":
    unittest.main()
