"""Point-forecast error evidence: an example, not a ``comuvia`` scoring rule.

``comuvia`` 0.1 forecasts are binary probabilities and its outcomes are 0 or 1, so a numeric
point forecast cannot be a 0.1 ``forecast`` record without a schema change or without encoding a
number as a probability. Here every input and result is an ``artifact_descriptor`` whose
retained bytes, exactly ``comuvia.canonicalize(object)``, hold the semantics:

- ``point-target/1``: what is being forecast, and which outcome record and edition settle it;
- ``point-error-rule/1``: the frozen ``RULE`` below (its digest is ``RULE_DIGEST``);
- ``point-forecast/1``: one provider's value, as a decimal string, with its times and unit;
- ``point-outcome/1``: the observed value, its edition and publication time;
- ``point-error-result/1``: the signed, absolute and squared error, with exact pins.

Arithmetic is exact ``Decimal``; no float is used. Synthetic results show mechanics, never a
provider's skill. There is no aggregate, no ranking and no probability conversion.

Functions: ``evaluate_point``, ``evaluate_bundle`` and ``reproduce``. Standard library, the
public ``comuvia`` 0.1.0 API, and the example helpers ``record_authoring`` and
``dependency_profile`` only. No I/O.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from decimal import Context, Decimal, Inexact, localcontext

import comuvia
import dependency_profile as dp
import record_authoring as ra

RULE = {
    "rule": "point-error", "version": 1, "status": "example; not a comuvia scoring rule",
    "applies_to": {"output_kind": "point"},
    "signed_error": "forecast - outcome", "absolute_error": "|forecast - outcome|", "squared_error": "(forecast - outcome)^2",
    "arithmetic": "exact decimal; plain decimal strings, no exponent, no trailing zeros, never -0",
    "error_unit": "percentage points if the target unit is percent; otherwise the target unit",
    "squared_unit": "the error unit, squared", "aggregate": "none",
    "eligibility": ["content_digest_mismatch", "malformed_input", "rule_unavailable", "unsupported_output_kind",
                    "conditional_not_scored", "target_mismatch", "measure_mismatch", "unit_mismatch", "missing_unit",
                    "period_mismatch", "missing_cutoff", "impossible_time_order", "post_outcome_forecast", "missing_outcome",
                    "unresolved_outcome", "outcome_edition_mismatch", "malformed_value"],
}
RULE_BYTES = comuvia.canonicalize(RULE)
RULE_DIGEST = comuvia.content_digest(RULE_BYTES)
ELIGIBILITY = tuple(RULE["eligibility"])
NOTE = "Synthetic example arithmetic; not evidence of provider skill."
TARGET, RULE_SCHEMA, FORECAST, OUTCOME, RESULT = (
    "point-target/1", "point-error-rule/1", "point-forecast/1", "point-outcome/1", "point-error-result/1")
_VALUE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?\Z")  # \Z: "$" would also match before a final newline
_REFERENCE_KEYS = {"record_type", "id", "revision", "digest"}
_REPRODUCE_ORDER = ("content_digest_mismatch", "malformed_input", "missing_input", "pin_mismatch", "rule_unavailable")

_TEXT, _TEXT_OR_MARKER, _TIME, _TIME_OR_MARKER, _ANY = "text", "text_or_marker", "time", "time_or_marker", "any"
_SHAPES = {
    TARGET: {"target": _TEXT, "measure": _TEXT, "unit": _TEXT, "period": _TEXT, "geography": _TEXT,
             "outcome_record": _TEXT, "outcome_edition": _TEXT, "resolution": _TEXT},
    FORECAST: {"target": _TEXT, "provider": _TEXT, "output_kind": _TEXT, "measure": _TEXT, "unit": _TEXT_OR_MARKER,
               "period": _TEXT, "value": _ANY, "issued_at": _TIME, "information_cutoff": _TIME_OR_MARKER,
               "upstream_lineage": ("undisclosed", "declared")},
    OUTCOME: {"target": _TEXT, "measure": _TEXT, "unit": _TEXT_OR_MARKER, "period": _TEXT, "value": _ANY,
              "edition": _TEXT, "status": _TEXT, "published_at": _TIME, "source": _TEXT},
}
_RESULT_KEYS = {"rule", "target", "forecast", "outcome", "signed_error", "absolute_error", "squared_error",
                "error_unit", "squared_unit", "note"}


def key_of(body: Mapping) -> tuple:
    return (body.get("record_type"), body.get("id"), body.get("revision"))


def _fits(value, kind) -> bool:
    if kind == _ANY:
        return True
    if isinstance(kind, tuple):
        return value in kind
    if kind in (_TEXT_OR_MARKER, _TIME_OR_MARKER) and comuvia.is_marker(value):
        return True
    if not isinstance(value, str) or value == "":
        return False
    return ra.instant(value) is not None if kind in (_TIME, _TIME_OR_MARKER) else True


def _artifact(body: Mapping | None, contents: Mapping, schema: str):
    """(parsed object, integrity reasons) for one input descriptor."""
    if body is None:
        return None, ["missing_input"]
    data = contents.get(key_of(body))
    if data is None or comuvia.verify(body, content=data).content_identity != "match":
        return None, ["content_digest_mismatch"]
    try:
        obj = comuvia.parse_json(data)
    except (comuvia.RefusalError, ValueError):
        return None, ["malformed_input"]
    if body.get("content_schema") != schema or not isinstance(obj, dict) or comuvia.canonicalize(obj) != data:
        return None, ["malformed_input"]
    if schema == RULE_SCHEMA:
        return (obj, []) if data == RULE_BYTES else (None, ["rule_unavailable"])
    if schema == RESULT:
        ok = set(obj) == _RESULT_KEYS and obj["note"] == NOTE and isinstance(obj["rule"], dict) \
            and all(isinstance(obj[k], dict) and set(obj[k]) == _REFERENCE_KEYS for k in ("target", "forecast", "outcome"))
        return (obj, []) if ok else (None, ["malformed_input"])
    shape = _SHAPES[schema]
    if set(obj) != set(shape) or not all(_fits(obj[k], kind) for k, kind in shape.items()):
        return None, ["malformed_input"]
    return obj, []


def _latest(records: Iterable[Mapping], record_id: str) -> Mapping | None:
    candidates = [b for b in records if b.get("record_type") == "artifact_descriptor" and b.get("id") == record_id]
    return max(candidates, key=lambda b: b["revision"]) if candidates else None


def _plain(value: Decimal) -> str:
    """A normalized plain decimal string: no exponent, no trailing zeros, never -0."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _ordered(reasons: Iterable[str], order=ELIGIBILITY) -> list[str]:
    found = set(reasons)
    return [r for r in order if r in found] + sorted(found - set(order))


def _evaluate(target_body, rule_body, forecast_body, outcome_body, contents) -> dict:
    """Evaluate one forecast against an explicit outcome descriptor."""
    reasons = []
    target, found = _artifact(target_body, contents, TARGET)
    reasons += found
    _, found = _artifact(rule_body, contents, RULE_SCHEMA)
    reasons += found
    forecast, found = _artifact(forecast_body, contents, FORECAST)
    reasons += found
    outcome = None
    if outcome_body is None:
        if target is not None:
            reasons.append("missing_outcome")
    else:
        outcome, found = _artifact(outcome_body, contents, OUTCOME)
        reasons += found
    reasons = ["malformed_input" if r == "missing_input" else r for r in reasons]

    if forecast is not None:
        if forecast["output_kind"] == "conditional_point":
            reasons.append("conditional_not_scored")
        elif forecast["output_kind"] != "point":
            reasons.append("unsupported_output_kind")
        cutoff, issued = forecast["information_cutoff"], ra.instant(forecast["issued_at"])
        if comuvia.is_marker(cutoff):
            reasons.append("missing_cutoff")
        elif ra.instant(cutoff) > issued:
            reasons.append("impossible_time_order")
    for item in (forecast, outcome):
        if item is None:
            continue
        if not isinstance(item["value"], str) or _VALUE.match(item["value"]) is None:
            reasons.append("malformed_value")
        if comuvia.is_marker(item["unit"]):
            reasons.append("missing_unit")
        elif target is not None and item["unit"] != target["unit"]:
            reasons.append("unit_mismatch")
        if target is not None:
            for field in ("target", "measure", "period"):
                if item[field] != target[field]:
                    reasons.append(f"{field}_mismatch")
    if outcome is not None:
        if outcome["status"] != "resolved":
            reasons.append("unresolved_outcome")
        if target is not None and outcome["edition"] != target["outcome_edition"]:
            reasons.append("outcome_edition_mismatch")
    if forecast is not None and outcome is not None and ra.instant(forecast["issued_at"]) >= ra.instant(outcome["published_at"]):
        reasons.append("post_outcome_forecast")
    if reasons:
        return {"status": "excluded", "reasons": _ordered(reasons)}

    f, o = forecast["value"], outcome["value"]
    digits = len(f.replace("-", "").replace(".", "")) + len(o.replace("-", "").replace(".", ""))
    with localcontext(Context(prec=2 * digits + 8, traps=[Inexact])):
        signed = Decimal(f) - Decimal(o)
        absolute = abs(signed)
        squared = signed * signed
    unit = target["unit"]
    error_unit = "percentage points" if unit == "percent" else unit
    return {"status": "scored", "result": {
        "rule": {"rule": RULE["rule"], "version": RULE["version"], "digest": RULE_DIGEST},
        "target": comuvia.reference_to(target_body), "forecast": comuvia.reference_to(forecast_body),
        "outcome": comuvia.reference_to(outcome_body),
        "signed_error": _plain(signed), "absolute_error": _plain(absolute), "squared_error": _plain(squared),
        "error_unit": error_unit, "squared_unit": f"{error_unit} squared", "note": NOTE}}


def evaluate_point(records: Iterable[Mapping], contents: Mapping, *, target: Mapping, rule: Mapping, forecast: Mapping) -> dict:
    """Evaluate ``forecast`` against the latest revision of the outcome its target names.

    Returns ``{"status": "scored", "result": ...}`` or ``{"status": "excluded", "reasons": [...]}``,
    reasons in the rule's eligibility order. ``contents`` maps ``(record_type, id, revision)`` to bytes.
    """
    bodies = list(records)
    target_obj, _ = _artifact(target, contents, TARGET)
    outcome = _latest(bodies, target_obj["outcome_record"]) if target_obj is not None else None
    return _evaluate(target, rule, forecast, outcome, contents)


def _of_schema(bodies, schema):
    latest = {}
    for b in bodies:
        if b.get("record_type") == "artifact_descriptor" and b.get("content_schema") == schema:
            if b["id"] not in latest or b["revision"] > latest[b["id"]]["revision"]:
                latest[b["id"]] = b
    return [latest[k] for k in sorted(latest)]


def evaluate_bundle(records: Iterable[Mapping], contents: Mapping) -> dict:
    """Every latest ``point-forecast/1`` descriptor, each against the target it names. Counts only; no aggregate."""
    bodies = list(records)
    targets = _of_schema(bodies, TARGET)
    rules = _of_schema(bodies, RULE_SCHEMA)
    named = {}
    for t in targets:
        obj, _ = _artifact(t, contents, TARGET)
        if obj is not None:
            named.setdefault(obj["target"], t)
    results = []
    for forecast in _of_schema(bodies, FORECAST):
        obj, _ = _artifact(forecast, contents, FORECAST)
        target = named.get(obj["target"]) if obj is not None else None
        target = target or (targets[0] if targets else None)
        rule = rules[0] if rules else None
        if target is None or rule is None:
            outcome = {"status": "excluded", "reasons": ["malformed_input" if target is None else "rule_unavailable"]}
        else:
            outcome = evaluate_point(bodies, contents, target=target, rule=rule, forecast=forecast)
        results.append({"forecast": comuvia.reference_to(forecast), **outcome})
    scored = sum(1 for r in results if r["status"] == "scored")
    return {"candidates": len(results), "scored": scored, "excluded": len(results) - scored, "results": results}


def reproduce(result_record: Mapping, records: Iterable[Mapping], contents: Mapping) -> dict:
    """Recompute a stored result from its own pins: ``match``, ``mismatch`` or ``unavailable`` (with reasons)."""
    bodies = list(records)
    index = {key_of(b): b for b in bodies}
    result, reasons = _artifact(result_record, contents, RESULT)
    if result is None:
        return {"status": "unavailable", "reasons": reasons}
    profile = dp.profile_of(result_record) or {}
    edges = profile.get("depends_on", []) if isinstance(profile, Mapping) else []
    by_role = {}
    for edge in edges:
        by_role.setdefault(edge.get("role"), []).append(edge.get("pin"))
    pins = {"target": result["target"], "forecast": result["forecast"], "outcome": result["outcome"]}
    if (by_role.get("assumption") != [pins["target"]] or len(by_role.get("method", [])) != 1
            or sorted(json.dumps(p, sort_keys=True) for p in by_role.get("data_input", []))
            != sorted(json.dumps(p, sort_keys=True) for p in (pins["forecast"], pins["outcome"]))
            or result["rule"] != {"rule": RULE["rule"], "version": RULE["version"], "digest": RULE_DIGEST}):
        return {"status": "unavailable", "reasons": ["malformed_input"]}

    schemas = {"target": TARGET, "forecast": FORECAST, "outcome": OUTCOME, "rule": RULE_SCHEMA}
    resolved = {}
    for name, pin in [*pins.items(), ("rule", by_role["method"][0])]:
        body = index.get((pin.get("record_type"), pin.get("id"), pin.get("revision")))
        if body is None:
            reasons.append("missing_input")
            continue
        if comuvia.record_digest(body) != pin.get("digest"):
            reasons.append("pin_mismatch")
        reasons += _artifact(body, contents, schemas[name])[1]  # integrity of what the bundle holds now
        resolved[name] = body
    if reasons:
        return {"status": "unavailable", "reasons": _ordered(reasons, _REPRODUCE_ORDER)}
    recomputed = _evaluate(resolved["target"], resolved["rule"], resolved["forecast"], resolved["outcome"], contents)
    if recomputed["status"] != "scored":
        return {"status": "unavailable", "reasons": _ordered(recomputed["reasons"], _REPRODUCE_ORDER + ELIGIBILITY)}
    same = comuvia.canonicalize(recomputed["result"]) == contents[key_of(result_record)]
    return {"status": "match" if same else "mismatch", "reasons": []}
