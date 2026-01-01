"""Independent checks with test-only libraries (skipped when they are not installed).

- jsonschema: the packaged schema files are valid 2020-12 schemas and agree with every
  record vector (schema-layer refusals invalid; valid and semantic-layer vectors valid).
- rfc8785 (Trail of Bits, Apache-2.0): an independent RFC 8785 encoder used as an oracle
  for the comuvia encoder over the vectors and over seeded random values.

Neither library is a runtime dependency of comuvia.
"""

import json
import random
import struct
import unittest
from pathlib import Path

import comuvia
from comuvia import canonicalize, parse_json

try:
    import jsonschema
    import referencing
    import referencing.jsonschema
except ImportError:  # test-only dependency
    jsonschema = None

try:
    import rfc8785
except ImportError:  # test-only dependency
    rfc8785 = None

VECTORS = Path(__file__).resolve().parent / "vectors"
SCHEMA_PREFIX = "urn:comuvia:schema:0.1:"


def load(name):
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


@unittest.skipUnless(jsonschema, "jsonschema is not installed (test-only dependency)")
class SchemaAgreement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schemas = {}
        for entry in comuvia.schema_files().iterdir():
            if entry.name.endswith(".json"):
                schema = parse_json(entry.read_bytes())
                schemas[schema["$id"]] = schema
        registry = referencing.Registry().with_resources(
            (sid, referencing.Resource.from_contents(s, default_specification=referencing.jsonschema.DRAFT202012))
            for sid, s in schemas.items()
        )
        cls.schemas = schemas
        cls.validators = {
            record_type: jsonschema.Draft202012Validator(schemas[SCHEMA_PREFIX + record_type], registry=registry)
            for record_type in comuvia.RECORD_TYPES
        }

    def accepts(self, body) -> bool:
        validator = self.validators.get(body.get("record_type")) if isinstance(body, dict) else None
        return validator is not None and validator.is_valid(body)

    def test_schemas_are_valid_2020_12(self):
        for sid, schema in self.schemas.items():
            with self.subTest(sid):
                jsonschema.Draft202012Validator.check_schema(schema)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_valid_vectors_accepted(self):
        for case in load("records.json")["valid"]:
            with self.subTest(case["id"]):
                self.assertTrue(self.accepts(case["record"]))

    def test_refusal_layers_agree(self):
        checked = 0
        for case in load("records.json")["refusals"]:
            if case["layer"] == "parse":
                continue
            with self.subTest(case["id"]):
                body = parse_json(case["text"].encode("utf-8"))
                self.assertEqual(self.accepts(body), case["layer"] == "semantic", case["layer"])
                checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_identity_vector_records_accepted(self):
        for record_id, body in load("identity.json")["records"].items():
            with self.subTest(record_id):
                self.assertTrue(self.accepts(body))


def as_binary64(value):
    """Map integers above 2^53 - 1 to the binary64 value they denote.

    rfc8785 refuses such Python ints as an input policy; comuvia accepts them when the
    written integer denotes a binary64 value without change (OSS-1A review R1), and a
    JSON number is that binary64 value.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return float(value)
    if isinstance(value, dict):
        return {k: as_binary64(v) for k, v in value.items()}
    if isinstance(value, list):
        return [as_binary64(v) for v in value]
    return value


@unittest.skipUnless(rfc8785, "rfc8785 is not installed (test-only oracle)")
class EncoderOracle(unittest.TestCase):
    def test_vector_values(self):
        values = []
        for case in load("canonicalization.json")["cases"]:
            expect = case["expect"]
            if "refusal" in expect or "ieee754_hex" in case:
                continue
            values += [parse_json(t) for t in case.get("inputs", [case.get("input_text")]) if t is not None]
        values += list(load("identity.json")["records"].values())
        values += [c["record"] for c in load("records.json")["valid"]]
        self.assertGreaterEqual(len(values), 20)
        for index, value in enumerate(values):
            with self.subTest(index):
                self.assertEqual(canonicalize(value), rfc8785.dumps(as_binary64(value)))

    def test_random_binary64(self):
        rng = random.Random(8785)
        checked = 0
        while checked < 200_000:
            value = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
            if value != value or value in (float("inf"), float("-inf")):
                continue
            self.assertEqual(canonicalize(value), rfc8785.dumps(value), value.hex())
            checked += 1
        for value in (0.1, 0.2, 1 / 3, 1e-7, 1e21, 5e-324, 2.0**53, 123456789012345680000.0):
            self.assertEqual(canonicalize(value), rfc8785.dumps(value), value)

    def test_random_documents(self):
        rng = random.Random(20260924)
        alphabet = [chr(c) for c in (0x1F, 0x22, 0x2F, 0x41, 0x5C, 0x7F, 0xE9, 0x20AC, 0xFB33, 0x1F600, 0x10FFFF)]

        def text():
            return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 6)))

        def value(depth):
            kind = rng.randrange(7 if depth < 3 else 4)
            if kind == 0:
                return rng.choice([None, True, False])
            if kind == 1:
                return rng.randrange(-(2**53) + 1, 2**53)
            if kind == 2:
                return rng.uniform(-1e6, 1e6) * 10 ** rng.randrange(-30, 30)
            if kind == 3:
                return text()
            if kind in (4, 5):
                return {text(): value(depth + 1) for _ in range(rng.randrange(0, 5))}
            return [value(depth + 1) for _ in range(rng.randrange(0, 5))]

        for index in range(3_000):
            document = value(0)
            with self.subTest(index):
                self.assertEqual(canonicalize(document), rfc8785.dumps(document))


if __name__ == "__main__":
    unittest.main()
