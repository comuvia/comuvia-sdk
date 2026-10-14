"""Invalid input is refused by evaluate, evaluation_records and reproduce; validate refuses non-finite numbers.

Uses the synthetic structured-binary records from the identity vectors (no new values).
"""

import copy
import json
import math
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import comuvia
from comuvia import RefusalError, canonicalize, evaluate, evaluation_records, reproduce

VECTORS = Path(__file__).resolve().parent / "vectors"
RECORDS = json.loads((VECTORS / "identity.json").read_text(encoding="utf-8"))["records"]
NAMES = ["q-port-calder-teu-2027-01", "fc-lantern-port-calder-teu-2027-01",
         "res-port-calder-bulletin-2027-01-first", "out-port-calder-teu-2027-01"]
QUESTION, FORECAST, OUTCOME = 0, 1, 3  # positions in bundle()
EVALUATED = {"evaluated_at": "2027-02-17T00:00:00Z", "recorded_by": "evaluator:example-evaluator", "recorded_at": "2027-02-17T00:00:00Z"}

BAD_PROBABILITIES = [
    (1.2, "out_of_range"), (-0.1, "out_of_range"), (1.0000000000000002, "out_of_range"),
    (math.nan, "non_finite_number"), (math.inf, "non_finite_number"), (-math.inf, "non_finite_number"),
    (True, "invalid_type"), ("0.5", "invalid_type"),
]
BAD_OUTCOMES = [(2, "invalid_value"), (0.5, "invalid_value"), ("1", "invalid_type"), (True, "invalid_type"),
                (math.nan, "non_finite_number")]


def bundle(probability=None, resolved_value=None, question=None):
    records = [copy.deepcopy(RECORDS[n]) for n in NAMES]
    if probability is not None:
        records[FORECAST]["output"]["probability"] = probability
    if resolved_value is not None:
        records[OUTCOME]["resolved_value"] = resolved_value
    if question is not None:
        records[QUESTION].update(question)
    return records


class InvalidInputRefused(unittest.TestCase):
    def assertRefused(self, call, pointer, code):
        with self.assertRaises(RefusalError) as caught:
            call()
        self.assertIn((pointer, code), [(i.pointer, i.code) for i in caught.exception.issues])
        return caught.exception

    def test_probability_refused_by_validate_and_evaluate(self):
        for value, code in BAD_PROBABILITIES:
            with self.subTest(probability=value):
                records = bundle(probability=value)
                self.assertEqual([(i.pointer, i.code) for i in comuvia.validate(records[FORECAST])], [("/output/probability", code)])
                self.assertRefused(lambda: evaluate(records), f"/{FORECAST}/output/probability", code)

    def test_resolved_value_refused_by_validate_and_evaluate(self):
        for value, code in BAD_OUTCOMES:
            with self.subTest(resolved_value=value):
                records = bundle(resolved_value=value)
                self.assertEqual([(i.pointer, i.code) for i in comuvia.validate(records[OUTCOME])], [("/resolved_value", code)])
                self.assertRefused(lambda: evaluate(records), f"/{OUTCOME}/resolved_value", code)

    def test_invalid_question_refused(self):
        records = bundle(question={"outcome_kind": "ternary"})
        self.assertRefused(lambda: evaluate(records), f"/{QUESTION}/outcome_kind", "invalid_value")

    def test_no_partial_report(self):
        records = bundle(probability=1.2)
        with self.assertRaises(RefusalError) as caught:
            evaluate(records)
        self.assertEqual(caught.exception.codes, frozenset({"out_of_range"}))

    def test_fail_closed_on_an_unrelated_invalid_record(self):
        records = bundle()
        stray = copy.deepcopy(RECORDS["q-port-calder-teu-2027-01"])
        stray.update(id="q-unrelated-example", outcome_kind="ternary")
        self.assertRefused(lambda: evaluate(records + [stray]), "/4/outcome_kind", "invalid_value")

    def test_every_issue_is_reported_with_its_index(self):
        records = bundle(probability=math.nan, resolved_value=2)
        error = self.assertRefused(lambda: evaluate(records), f"/{FORECAST}/output/probability", "non_finite_number")
        self.assertIn((f"/{OUTCOME}/resolved_value", "invalid_value"), [(i.pointer, i.code) for i in error.issues])

    def test_evaluation_records_refuses_the_same_way(self):
        valid = bundle()
        report = evaluate(valid)
        for value, code in BAD_PROBABILITIES:
            with self.subTest(probability=value):
                self.assertRefused(lambda: evaluation_records(report, bundle(probability=value), **EVALUATED),
                                   f"/{FORECAST}/output/probability", code)

    def test_reproduce_refuses_invalid_records_and_an_invalid_evaluation(self):
        valid = bundle()
        (stored,) = evaluation_records(evaluate(valid), valid, **EVALUATED)
        self.assertEqual(reproduce(stored, valid).result, "match")
        for value, code in BAD_OUTCOMES:
            with self.subTest(resolved_value=value):
                self.assertRefused(lambda: reproduce(stored, bundle(resolved_value=value)), f"/{OUTCOME}/resolved_value", code)
        broken = copy.deepcopy(stored)
        broken["result"]["loss"] = math.inf
        self.assertRefused(lambda: reproduce(broken, valid), "/evaluation/result/loss", "non_finite_number")

    def test_validate_skips_range_checks_for_non_finite(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                codes = [i.code for i in comuvia.validate(bundle(probability=value)[FORECAST])]
                self.assertEqual(codes, ["non_finite_number"])


class UserMapping(Mapping):
    """A user-defined, read-only Mapping."""

    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


def proxied(value):
    """MappingProxyType at every nesting level (lists stay lists)."""
    if isinstance(value, dict):
        return MappingProxyType({k: proxied(v) for k, v in value.items()})
    if isinstance(value, list):
        return [proxied(v) for v in value]
    return value


class MappingInputAccepted(unittest.TestCase):
    """0.1.0 evaluated any Mapping; 0.1.1 still does, with identical results and record bytes."""

    def assertSameAsDict(self, wrapped):
        plain = bundle()
        (a,), (b,) = evaluate(plain).results, evaluate(wrapped).results
        self.assertEqual((b.status, json.dumps(b.loss)), ("scored", "0.09000000000000002"))
        self.assertEqual((a.status, a.loss, a.reasons), (b.status, b.loss, b.reasons))
        ea = evaluation_records(evaluate(plain), plain, **EVALUATED)
        eb = evaluation_records(evaluate(wrapped), wrapped, **EVALUATED)
        self.assertEqual([canonicalize(x) for x in ea], [canonicalize(x) for x in eb])
        self.assertEqual(reproduce(eb[0], wrapped).result, "match")

    def test_mapping_proxy_records(self):
        self.assertSameAsDict([MappingProxyType(r) for r in bundle()])

    def test_user_defined_mapping_records(self):
        self.assertSameAsDict([UserMapping(r) for r in bundle()])

    def test_mapping_proxy_at_every_level(self):
        self.assertSameAsDict([proxied(r) for r in bundle()])

    def test_invalid_value_inside_a_mapping_proxy_is_refused(self):
        records = [proxied(r) for r in bundle(probability=1.2)]
        with self.assertRaises(RefusalError) as caught:
            evaluate(records)
        self.assertEqual([(i.pointer, i.code) for i in caught.exception.issues], [(f"/{FORECAST}/output/probability", "out_of_range")])


class ValidInputUnchanged(unittest.TestCase):
    def test_boundary_probabilities_are_scored(self):
        for value, loss in ((0, 1.0), (1, 0.0), (0.5, 0.25), (-0.0, 1.0)):
            with self.subTest(probability=value):
                (result,) = evaluate(bundle(probability=value)).results
                self.assertEqual((result.status, result.loss), ("scored", loss))

    def test_negative_zero_gives_identical_evaluation_bytes(self):
        zero, negative = bundle(probability=0.0), bundle(probability=-0.0)
        a = evaluation_records(evaluate(zero), zero, **EVALUATED)
        b = evaluation_records(evaluate(negative), negative, **EVALUATED)
        self.assertEqual([canonicalize(x) for x in a], [canonicalize(x) for x in b])

    def test_the_fixture_loss_is_unchanged(self):
        (result,) = evaluate(bundle()).results
        self.assertEqual((result.status, json.dumps(result.loss)), ("scored", "0.09000000000000002"))
        corrected = bundle()
        correction = copy.deepcopy(corrected[OUTCOME])
        correction.update(revision=2, predecessor=comuvia.reference_to(corrected[OUTCOME]), resolved_value=0,
                          recorded_at="2027-02-20T10:00:00Z")
        (result,) = evaluate(corrected + [correction]).results
        self.assertEqual(json.dumps(result.loss), "0.48999999999999994")


if __name__ == "__main__":
    unittest.main()
