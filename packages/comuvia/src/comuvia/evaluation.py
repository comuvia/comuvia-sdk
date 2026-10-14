"""Eligibility and the ``binary-brier-v1`` scoring rule.

The rule is a packaged, canonical JSON descriptor (``comuvia/rules/binary-brier-v1/<version>.json``)
pinned by id, version and digest. Every failing eligibility check is reported by name;
there is no aggregate mean, skill or relative score. Narrative records are reported as
candidates with their exclusion reasons and are never converted into forecasts.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.resources
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from . import reasons
from .history import latest_revisions
from .identity import canonicalize, content_digest, is_marker, parse_json, record_digest, reference_to
from .issues import Issue, RefusalError
from .validation import compare_times, validate

_UNRESOLVED = frozenset({reasons.UNRESOLVED_OUTCOME, reasons.NO_OUTCOME_RECORDED})
_STATUS_EXCLUSIONS = {
    "unresolved": reasons.UNRESOLVED_OUTCOME,
    "ambiguous": reasons.AMBIGUOUS_OUTCOME,
    "annulled": reasons.ANNULLED_QUESTION,
}


@dataclass(frozen=True)
class ScoringRule:
    id: str
    version: str
    digest: str
    descriptor: Mapping

    def reference(self) -> dict:
        return {"id": self.id, "version": self.version, "digest": self.digest}


def _rule_versions(rule_id: str) -> dict[str, object]:
    folder = importlib.resources.files("comuvia").joinpath("rules").joinpath(rule_id)
    try:
        entries = list(folder.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return {}
    return {e.name[:-5]: e for e in entries if e.name.endswith(".json") and e.name[:-5].isdigit()}


@functools.lru_cache(maxsize=None)
def load_rule(rule_id: str = "binary-brier-v1", version: str | None = None) -> ScoringRule:
    """Load a packaged scoring-rule descriptor (the latest version if ``version`` is ``None``).

    Descriptors live at ``comuvia/rules/<id>/<version>.json`` in canonical form; a changed
    descriptor is a new version and earlier versions stay byte-identical, so evaluations
    pinned to them still reproduce. The digest is SHA-256 of the canonical bytes.
    """
    versions = _rule_versions(rule_id)
    if not versions:
        raise KeyError(f"no packaged scoring rule {rule_id!r}")
    chosen = version if version is not None else max(versions, key=int)
    if chosen not in versions:
        raise KeyError(f"no packaged version {chosen!r} of scoring rule {rule_id!r}")
    data = versions[chosen].read_bytes()
    descriptor = parse_json(data)
    if canonicalize(descriptor) != data:
        raise RuntimeError(f"packaged rule {rule_id} version {chosen} is not stored in canonical form")
    if descriptor["id"] != rule_id or descriptor["version"] != chosen:
        raise RuntimeError(f"packaged rule file {rule_id}/{chosen}.json names a different rule")
    return ScoringRule(descriptor["id"], descriptor["version"], content_digest(data), descriptor)


@dataclass(frozen=True)
class CandidateResult:
    record: dict  # reference to the candidate record
    kind: str  # "forecast" | "narrative"
    status: str  # "scored" | "unresolved" | "excluded"
    reasons: tuple[str, ...]
    outcome: dict | None = None
    loss: float | None = None

    def as_json(self) -> dict:
        return {
            "record": self.record,
            "kind": self.kind,
            "status": self.status,
            "reasons": list(self.reasons),
            "outcome": self.outcome,
            "loss": self.loss,
        }


@dataclass(frozen=True)
class EvaluationReport:
    scoring_rule: dict
    counts: dict
    results: tuple[CandidateResult, ...]

    def as_json(self) -> dict:
        """Report as JSON data. Deliberately no aggregate score."""
        return {
            "scoring_rule": self.scoring_rule,
            "counts": self.counts,
            "results": [r.as_json() for r in self.results],
            "aggregate": None,
        }




def _rule_codes(rule: ScoringRule) -> frozenset[str]:
    return frozenset(e["exclusion"] for e in rule.descriptor["eligibility"] if "exclusion" in e)


def _pair(
    forecast: Mapping, outcome: Mapping | None, question: Mapping | None, rule: ScoringRule
) -> tuple[list[str], float | None]:
    """Eligibility reasons (every failing check, in the rule's order) and the loss if eligible.

    Checks introduced by later descriptor versions apply only when the pinned descriptor
    names them, so an evaluation reproduces under the version it pinned.
    """
    codes = _rule_codes(rule)
    limitation_exclusions = rule.descriptor.get("limitation_exclusions", {})
    found = []
    if outcome is not None and outcome["question"] != forecast["question"]:
        found.append(reasons.QUESTION_MISMATCH)
    if question is None:
        found.append(reasons.QUESTION_NOT_FOUND)
    elif reasons.INCOMPLETE_QUESTION in codes and any(
        is_marker(question.get(m)) for m in rule.descriptor.get("question_completeness", ())
    ):
        found.append(reasons.INCOMPLETE_QUESTION)
    probability = forecast["output"]["probability"]
    if is_marker(probability):
        found.append(reasons.NO_DECLARED_PROBABILITY)
    conditions = forecast["conditions"]
    if is_marker(conditions):
        found.append(reasons.UNKNOWN_CONDITIONS)
    elif conditions:
        found.append(reasons.CONDITIONAL_SCENARIO)
    issued, cutoff = forecast["issued_at"], forecast["information_cutoff"]
    deadline = question.get("forecast_deadline") if question is not None else None
    if is_marker(issued) or is_marker(cutoff) or is_marker(deadline):
        found.append(reasons.MISSING_REQUIRED_TIME)
    elif question is not None:
        order = compare_times(issued, deadline)
        if order == 1:
            found.append(reasons.ISSUED_AFTER_FORECAST_DEADLINE)
        elif order is None and reasons.INDETERMINATE_TIME_ORDER in codes:
            found.append(reasons.INDETERMINATE_TIME_ORDER)
    limitations = list(forecast.get("limitations", []))
    if question is not None:
        limitations += [code for code in question.get("limitations", []) if code not in limitations]
    for code in limitations:
        exclusion = limitation_exclusions.get(code)
        if exclusion and exclusion not in found:
            found.append(exclusion)
    if outcome is None:
        found.append(reasons.NO_OUTCOME_RECORDED)
    else:
        observed = outcome["observed"]
        if (question is not None and not is_marker(observed) and not is_marker(question["unit"])
                and observed["unit"] != question["unit"]):
            found.append(reasons.UNIT_MISMATCH)
        if outcome["status"] in _STATUS_EXCLUSIONS:
            found.append(_STATUS_EXCLUSIONS[outcome["status"]])
    if found:
        return found, None
    d = float(probability) - float(outcome["resolved_value"])
    return found, d * d


def _status(found: list[str]) -> str:
    if not found:
        return "scored"
    return "unresolved" if set(found) <= _UNRESOLVED else "excluded"


def _narrative_reasons(body: Mapping) -> list[str]:
    if body["record_type"] == "source_assertion":
        found = []
        if not isinstance(body["stated_probability"], (int, float)) or isinstance(body["stated_probability"], bool):
            found.append(reasons.NO_DECLARED_PROBABILITY)
        if body["assertion_kind"] == "conditional_scenario":
            found.append(reasons.CONDITIONAL_SCENARIO)
        found.append(reasons.NO_PINNED_QUESTION)
        return found
    found = [reasons.NOT_A_FORECAST]
    if body.get("condition") is not None:
        found.append(reasons.CONDITIONAL_SCENARIO)
    return found


class _Index:
    def __init__(self, records: Iterable[Mapping]):
        self.all = list(records)
        self.by_digest = {record_digest(b): b for b in self.all}

    def resolve(self, ref: Mapping) -> Mapping | None:
        body = self.by_digest.get(ref["digest"])
        if body is None or (body["record_type"], body["id"], body["revision"]) != (ref["record_type"], ref["id"], ref["revision"]):
            return None
        return body


def _plain(value):
    """A plain-JSON view for validation: every Mapping, at any depth, as a dict; lists stay lists."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _validated(records: Iterable[Mapping], extra: Mapping | None = None) -> list[Mapping]:
    """Materialize ``records`` and refuse them all if any record is invalid.

    Records may be any ``Mapping`` (as in 0.1.0); each is validated through a plain-JSON view,
    and the original objects are returned. Each issue's pointer is prefixed with ``/<index>``,
    the record's zero-based position in the input; issues in ``extra`` (the evaluation passed to
    ``reproduce``) are prefixed with ``/evaluation``. Invalid input is refused, never excluded:
    exclusion is for valid records.
    """
    bodies = list(records)
    issues = [Issue(f"/{position}{issue.pointer}", issue.code, issue.message)
              for position, body in enumerate(bodies) for issue in validate(_plain(body))]
    if extra is not None:
        issues += [Issue(f"/evaluation{issue.pointer}", issue.code, issue.message) for issue in validate(_plain(extra))]
    if issues:
        raise RefusalError(issues)
    return bodies


def evaluate(records: Iterable[Mapping], *, rule: ScoringRule | None = None) -> EvaluationReport:
    """Evaluate every candidate among ``records`` (all revisions may be passed).

    Candidates are the latest revision of each forecast, source assertion and
    interpretation. Pinned references (questions) resolve by digest among all records.

    Every record is validated first. If any record is invalid, even one that pairs with
    nothing, the whole call raises ``RefusalError`` with every issue (pointers prefixed with
    ``/<index>``) and no partial report: fail-closed.
    """
    rule = rule or load_rule()
    index = _Index(_validated(records))
    latest = latest_revisions(index.all)
    outcomes: dict[str, list[Mapping]] = {}
    for (record_type, _), body in latest.items():
        if record_type == "outcome":
            outcomes.setdefault(body["question"]["id"], []).append(body)

    results = []
    forecasts = []
    for (record_type, _), body in sorted(latest.items()):
        if record_type == "forecast":
            forecasts.append(body)
            candidates = outcomes.get(body["question"]["id"], [])
            question = index.resolve(body["question"])
            if len(candidates) > 1:
                found, outcome, loss = [reasons.MULTIPLE_OUTCOMES], None, None
            else:
                outcome = candidates[0] if candidates else None
                found, loss = _pair(body, outcome, question, rule)
            results.append(CandidateResult(
                reference_to(body), "forecast", _status(found) if found != [reasons.MULTIPLE_OUTCOMES] else "excluded",
                tuple(found), reference_to(outcome) if outcome is not None else None, loss,
            ))
        elif record_type in ("source_assertion", "interpretation"):
            results.append(CandidateResult(reference_to(body), "narrative", "excluded", tuple(_narrative_reasons(body))))

    scored = sum(r.status == "scored" for r in results)
    unresolved = sum(r.status == "unresolved" for r in results)
    counts = {
        "candidates": len(results),
        "forecasts": len(forecasts),
        "independent_questions": len({f["question"]["id"] for f in forecasts}),
        "forecast_families": len({f["forecast_family"] for f in forecasts}),
        "eligible": scored,
        "scored": scored,
        "unresolved": unresolved,
        "excluded": len(results) - scored - unresolved,
    }
    return EvaluationReport(rule.reference(), counts, tuple(results))


def _evaluation_id(forecast_ref: Mapping, outcome_ref: Mapping) -> str:
    readable = f"eval:{forecast_ref['id']}:r{forecast_ref['revision']}:{outcome_ref['id']}:r{outcome_ref['revision']}"
    if len(readable) <= 200:
        return readable
    return "eval:" + hashlib.sha256(readable.encode("utf-8")).hexdigest()


def evaluation_records(
    report: EvaluationReport,
    records: Iterable[Mapping],
    *,
    evaluated_at: str,
    recorded_by: str,
    recorded_at: str,
) -> list[dict]:
    """Evaluation record bodies for every forecast paired with an outcome in ``report``.

    Refuses invalid ``records`` exactly as ``evaluate`` does.
    """
    index = _Index(_validated(records))
    bodies = []
    for result in report.results:
        if result.kind != "forecast" or result.outcome is None:
            continue
        inputs = [index.resolve(result.record), index.resolve(result.outcome)]
        synthetic = any(b is not None and b["data_origin"] == "synthetic" for b in inputs)
        bodies.append({
            "schema": "comuvia/0.1",
            "record_type": "evaluation",
            "id": _evaluation_id(result.record, result.outcome),
            "revision": 1,
            "predecessor": None,
            "data_origin": "synthetic" if synthetic else "observed",
            "forecast": result.record,
            "outcome": result.outcome,
            "scoring_rule": report.scoring_rule,
            "policy": None,
            "result": {
                "eligible": result.status == "scored",
                "exclusion_reasons": [] if result.status == "scored" else list(result.reasons),
                "loss": result.loss,
            },
            "evaluated_at": evaluated_at,
            "recorded_by": recorded_by,
            "recorded_at": recorded_at,
        })
    return bodies


@dataclass(frozen=True)
class Reproduction:
    result: str  # "match" | "mismatch" | "unavailable"
    stored: dict
    recomputed: dict | None
    reason: str | None = None


def reproduce(evaluation: Mapping, records: Iterable[Mapping]) -> Reproduction:
    """Re-derive a stored evaluation from the inputs it pins, found by digest. Never overwrites.

    Refuses invalid ``records`` exactly as ``evaluate`` does, and an invalid ``evaluation``
    (its issues prefixed with ``/evaluation``).
    """
    records = _validated(records, evaluation)
    stored = dict(evaluation["result"])
    try:
        rule = load_rule(evaluation["scoring_rule"]["id"], evaluation["scoring_rule"]["version"])
    except KeyError:
        return Reproduction("unavailable", stored, None, reasons.RULE_NOT_FOUND)
    if rule.reference() != evaluation["scoring_rule"]:
        return Reproduction("unavailable", stored, None, reasons.RULE_NOT_FOUND)
    index = _Index(records)  # already validated above
    forecast, outcome = index.resolve(evaluation["forecast"]), index.resolve(evaluation["outcome"])
    if forecast is None or outcome is None:
        return Reproduction("unavailable", stored, None, reasons.EVALUATION_INPUT_NOT_FOUND)
    found, loss = _pair(forecast, outcome, index.resolve(forecast["question"]), rule)
    scored = _status(found) == "scored"
    recomputed = {"eligible": scored, "exclusion_reasons": [] if scored else found, "loss": loss}
    return Reproduction("match" if canonicalize(recomputed) == canonicalize(stored) else "mismatch", stored, recomputed)
