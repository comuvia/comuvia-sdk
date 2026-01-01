"""Normalize a retained ForeGlass snapshot into comuvia records, honestly.

Only semantics the public artifact declares are mapped. Everything it lacks becomes an
explicit unknown marker; every lane that cannot be mapped is named with a reason.

Derivation rules (documented and stable):

- ``encode_identifier(text)`` keeps ``A-Z a-z 0-9 . : -`` and writes every other byte of
  the UTF-8 text, including ``_``, as ``_`` plus two lowercase hex digits. Because ``_``
  itself is always escaped, the encoding is injective and reversible.
- Question id: ``fg:`` + ``encode_identifier(qid)``; the original ``qid`` is preserved in
  the ``ai.foreglass/v1`` extension.
- Forecast id: ``fg:lane:`` + ``encode_identifier(lane id)`` + ``:`` + the first 16 hex
  digits of the lane's ``core_sha256`` (the provider's sealed commitment), so a changed
  sealed core is a different forecast.
- Forecast family: ``fg:family:`` + the first 40 hex digits of SHA-256 over ``gkey``;
  provider variants (arms) share a ``gkey`` and therefore one family.
- Model id: ``fg:model:`` + ``encode_identifier(model)``.
- Resource snapshot id: ``fg:snapshot:`` + ``encode_identifier(role)`` + ``:`` + the 64
  hex digits of the artifact's SHA-256.

An absent or empty provider unit becomes ``{"unknown": "provider_declares_no_unit"}``.
``malformed_lane`` means provider data that violates the provider's own lane shape; if the
comuvia core refuses a record the normalizer built, ``NormalizationError`` is raised.

Question text is the lane ``statement`` and the resolution rule is the lane ``criteria``,
verbatim, from the first lane (ledger order) of that ``qid`` carrying both; the source
lane and field are recorded. No wording is generated.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import comuvia
from comuvia import parse_json, reference_to
from comuvia import reasons as core_reasons
from comuvia.validation import instant

from . import reasons
from .catalog import Lane
from .client import Artifact
from .intake import Finding, Snapshot, drift_findings

EXTENSION = "ai.foreglass/v1"
PROVIDER = {"id": "foreglass", "name": "ForeGlass"}
DEFAULT_AGENT = "normalizer:foreglass-python"
_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.:-")
_RESOURCE_TYPES = {
    "ledger": "foreglass_verification_ledger",
    "ledger_ots": "opentimestamps_proof_file",
    "archive_index": "foreglass_ledger_archive_index",
    "fragility_latest": "foreglass_index_reading",
    "fragility_countries": "foreglass_index_reading",
}
MODEL_CONDITIONAL = "crisis-hazard-model-conditional"
PUBLISHED_BEFORE_SEAL = "outcome-published-before-seal"


def encode_identifier(text: str) -> str:
    """Injective encoding into comuvia identifier characters (see the module docstring)."""
    out = []
    for char in text:
        if char in _SAFE:
            out.append(char)
        else:
            out.extend(f"_{byte:02x}" for byte in char.encode("utf-8"))
    return "".join(out)


def question_id(qid: str) -> str:
    return "fg:" + encode_identifier(qid)


def forecast_id(lane: Lane) -> str:
    return f"fg:lane:{encode_identifier(lane.id)}:{str(lane.raw.get('core_sha256', ''))[:16]}"


def family_id(gkey: str) -> str:
    return "fg:family:" + hashlib.sha256(gkey.encode("utf-8")).hexdigest()[:40]


def _resource_type(role: str) -> str:
    if role.startswith("archive_file:"):
        return "foreglass_verification_ledger_archive_copy"
    if role.startswith("archive_ots:"):
        return "opentimestamps_proof_file"
    return _RESOURCE_TYPES.get(role, "foreglass_artifact")


class NormalizationError(RuntimeError):
    """The normalizer built a record the comuvia core refuses: a defect here, never a lane property."""


@dataclass(frozen=True)
class NotMapped:
    lane_id: str | None
    kind: str | None
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class NormalizationResult:
    records: tuple[dict, ...] = field(repr=False)
    not_mapped: tuple[NotMapped, ...]
    findings: tuple[Finding, ...]
    report: Mapping


def _snapshot_record(role: str, artifact: Artifact, origin: str, ledger: Mapping | None, recorded_by: str, recorded_at: str) -> dict:
    extension = {"role": role, "request_url": artifact.request_url, "final_url": artifact.final_url, "status": artifact.status}
    if role == "ledger" and ledger is not None:
        extension.update({
            "schema": ledger.get("_schema"), "tier": ledger.get("tier"), "built": ledger.get("built"),
            "registry_schema": ledger.get("registry_schema"), "counts": ledger.get("counts"),
        })
    captured = artifact.fetched_at if artifact.fetched_at and _is_timestamp(artifact.fetched_at) else None
    return {
        "schema": "comuvia/0.1",
        "record_type": "resource_snapshot",
        "id": f"fg:snapshot:{encode_identifier(role)}:{artifact.sha256.removeprefix('sha256:')}",
        "revision": 1,
        "predecessor": None,
        "data_origin": origin,
        "resource_type": _resource_type(role),
        "locator": artifact.final_url or artifact.request_url or {"unknown": "replayed_from_fixture_bytes"},
        "language": {"unknown": "source_declares_no_language"},
        "source_version": {"unknown": "source_declares_no_version"},
        "source_published_at": {"unknown": "source_declares_build_date_only"},
        "captured_at": captured or {"unknown": "capture_time_not_recorded"},
        "captured_assets": ["response_body"],
        "not_captured": ["response_headers"],
        "content": {
            "media_type": artifact.content_type or {"unknown": "content_type_not_recorded"},
            "retained": True,
            "byte_length": artifact.byte_length,
            "digest": artifact.sha256,
        },
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
        "extensions": {EXTENSION: extension},
    }


def _is_timestamp(text: str) -> bool:
    return instant(text) is not None


def _limitations(lanes: list[Lane], *, include_caveat: bool) -> list[str]:
    truncated = any(lane.possibly_truncated["statement"] or lane.possibly_truncated["criteria"] for lane in lanes)
    retrospective = include_caveat and any(lane.caveat_id == PUBLISHED_BEFORE_SEAL for lane in lanes)
    withheld = any(lane.withheld_fields for lane in lanes)
    return [code for code, present in (
        (core_reasons.TEXT_POSSIBLY_TRUNCATED, truncated),
        (core_reasons.OUTCOME_PUBLISHED_BEFORE_REGISTRATION, retrospective),
        (core_reasons.PROVIDER_FIELDS_WITHHELD, withheld),
    ) if present]


def _question(qid: str, source_lane: Lane, lanes: list[Lane], origin: str, recorded_by: str, recorded_at: str) -> dict:
    if source_lane.source:
        resolution_source = {"name": source_lane.source, "locator": {"unknown": "provider_declares_no_locator"}}
    elif "source" in source_lane.withheld_fields:
        resolution_source = {"withheld": "provider_withheld_source"}
    else:
        resolution_source = {"unknown": "provider_declares_no_source"}
    return {
        "schema": "comuvia/0.1",
        "record_type": "question",
        "id": question_id(qid),
        "revision": 1,
        "predecessor": None,
        "data_origin": origin,
        "text": source_lane.statement,
        "outcome_kind": "binary",
        "unit": source_lane.full_unit or source_lane.unit or {"unknown": "provider_declares_no_unit"},
        "transformation": {"unknown": "provider_declares_no_transformation"},
        "observable": source_lane.metric,
        "target_period": {"unknown": "provider_declares_no_target_period"},
        "resolution_rule": source_lane.criteria,
        "resolution_source": resolution_source,
        "vintage_policy": {"unknown": "provider_declares_no_vintage_policy"},
        "forecast_deadline": {"unknown": "provider_declares_no_forecast_deadline"},
        "resolution_deadline": {"unknown": "provider_declares_grading_date_only"},
        "limitations": _limitations([source_lane], include_caveat=False),
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
        "extensions": {EXTENSION: {
            "qid": qid,
            "metric": source_lane.metric,
            "due": source_lane.due,
            "due_meaning": "the provider's grading date, not a target period or a deadline",
            "text_source": {"lane_id": source_lane.id, "field": "statement"},
            "rule_source": {"lane_id": source_lane.id, "field": "criteria"},
            "unit_source": "gkey segment 3" if source_lane.full_unit else ("unit" if source_lane.unit else "none published"),
            "unit_display": source_lane.unit,
            "lanes": [lane.id for lane in lanes],
            "text_varies_across_lanes": len({(l.statement, l.criteria) for l in lanes}) > 1,
        }},
    }


def _forecast(lane: Lane, question: dict, ledger_ref: dict | None, origin: str, recorded_by: str, recorded_at: str) -> dict:
    conditional = lane.caveat_id == MODEL_CONDITIONAL or lane.validation_status == "model-conditional"
    conditions = []
    if conditional:
        conditions.append({
            "text": lane.caveat or f"provider validation_status {lane.validation_status}",
            "state": "unresolved",
            "note": f"provider caveat_id {lane.caveat_id}" if lane.caveat_id else "provider validation_status",
        })
    raw = lane.raw
    extension = {
        "lane_id": lane.id, "sha": raw.get("sha"), "core_sha256": raw.get("core_sha256"), "arm": lane.arm,
        "arm_label": raw.get("arm_label"), "gkey": lane.gkey, "qid": lane.qid, "due": lane.due,
        "sealed_at": lane.sealed_at, "scope": lane.scope, "unit_display": lane.unit, "model": lane.model,
        "lo": lane.lo, "hi": lane.hi,
        "lo_hi_meaning": "an interval on the probability with no declared coverage level; not a probability",
        "naive_value": raw.get("naive_value"), "pred_short": raw.get("predShort"), "pred_full": raw.get("predFull"),
        "validation_status": lane.validation_status, "caveat_id": lane.caveat_id, "caveat": lane.caveat,
        "prompt_version": raw.get("prompt_version"), "withheld_fields": list(lane.withheld_fields),
        "ledger_snapshot": ledger_ref,
    }
    return {
        "schema": "comuvia/0.1",
        "record_type": "forecast",
        "id": forecast_id(lane),
        "revision": 1,
        "predecessor": None,
        "data_origin": origin,
        "question": reference_to(question),
        "provider": dict(PROVIDER),
        "model": {
            "id": "fg:model:" + encode_identifier(lane.model) if lane.model else "fg:model:unknown",
            "version": {"unknown": "provider_declares_no_model_version"},
        },
        "forecast_family": family_id(lane.gkey),
        "issued_at": {"date": lane.sealed_at, "precision": "day"},
        "information_cutoff": {"unknown": "provider_declares_no_information_cutoff"},
        "output": {"kind": "binary_probability", "event": "resolves_1", "probability": lane.val},
        "conditions": conditions,
        "limitations": _limitations([lane], include_caveat=True),
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
        "extensions": {EXTENSION: extension},
    }


def normalize(
    snapshot: Snapshot | Mapping[str, Artifact],
    *,
    recorded_at: str,
    recorded_by: str = DEFAULT_AGENT,
) -> NormalizationResult:
    """Map a verified snapshot to comuvia records and report everything not mapped."""
    artifacts = dict(snapshot.artifacts if isinstance(snapshot, Snapshot) else snapshot)
    origins = {a.data_origin for a in artifacts.values()}
    origin = "observed" if origins == {"observed"} else "synthetic"
    ledger = parse_json(artifacts["ledger"].data)

    records: list[dict] = []
    ledger_record = None
    for role in sorted(artifacts, key=lambda r: (r != "ledger", r)):
        record = _snapshot_record(role, artifacts[role], origin, ledger if role == "ledger" else None, recorded_by, recorded_at)
        records.append(record)
        if role == "ledger":
            ledger_record = record
    ledger_ref = reference_to(ledger_record) if ledger_record else None

    not_mapped: list[NotMapped] = []
    by_qid: dict[str, list[Lane]] = {}
    kinds: dict[str, int] = {}
    for raw in ledger.get("lanes", []):
        kind = raw.get("kind") if isinstance(raw, Mapping) else None
        kinds[str(kind)] = kinds.get(str(kind), 0) + 1
        try:
            lane = Lane.from_json(raw)
        except (KeyError, TypeError, AttributeError) as error:
            not_mapped.append(NotMapped(raw.get("id") if isinstance(raw, Mapping) else None, kind, reasons.MALFORMED_LANE,
                                        f"missing or invalid field {error}"))
            continue
        if lane.kind != "binary":
            not_mapped.append(NotMapped(lane.id, lane.kind, reasons.UNSUPPORTED_OUTPUT_KIND,
                                        "comuvia 0.1 has no record type for interval or point outputs"))
        elif not lane.qid:
            not_mapped.append(NotMapped(lane.id, lane.kind, reasons.NO_PINNED_QUESTION, "blank qid; no identity is fabricated"))
        elif (not isinstance(lane.val, (int, float)) or isinstance(lane.val, bool) or not math.isfinite(lane.val)
              or not 0 <= lane.val <= 1):
            not_mapped.append(NotMapped(lane.id, lane.kind, reasons.MALFORMED_LANE, "val is not a probability in [0, 1]"))
        else:
            by_qid.setdefault(lane.qid, []).append(lane)

    questions, forecasts = [], []
    for qid, lanes in by_qid.items():
        source_lane = next((lane for lane in lanes if lane.statement and lane.criteria), None)
        if source_lane is None:
            not_mapped.extend(NotMapped(l.id, l.kind, reasons.RESOLUTION_RULE_WITHHELD, "no lane of this qid publishes criteria")
                              for l in lanes)
            continue
        question = _question(qid, source_lane, lanes, origin, recorded_by, recorded_at)
        questions.append(question)
        forecasts.extend(_forecast(lane, question, ledger_ref, origin, recorded_by, recorded_at) for lane in lanes)
    records += questions + forecasts
    for record in records:
        issues = comuvia.validate(record)
        if issues:
            # Provider-shape problems are caught above as malformed_lane; a refusal here means
            # the normalizer built an invalid record, which must never be passed off as lane data.
            raise NormalizationError(f"normalizer built an invalid record {record['id']}: "
                                     + ", ".join(f"{i.code} at {i.pointer}" for i in issues))

    evaluation = comuvia.evaluate(records)
    findings = drift_findings(ledger)
    by_reason: dict[str, list[str]] = {}
    for item in not_mapped:
        by_reason.setdefault(item.reason, []).append(item.lane_id)
    report = {
        "data_origin": origin,
        "ledger": {"built": ledger.get("built"), "built_meaning": "build date, not a publication time",
                   "sha256": artifacts["ledger"].sha256, "byte_length": artifacts["ledger"].byte_length},
        "lanes": {"total": sum(kinds.values()), "by_kind": dict(sorted(kinds.items()))},
        "mapped": {"questions": len(questions), "forecasts": len(forecasts),
                   "lanes": [f["extensions"][EXTENSION]["lane_id"] for f in forecasts]},
        "not_mapped": {reason: ids for reason, ids in sorted(by_reason.items())},
        "findings": [{"code": f.code, "where": f.where, "field": f.field} for f in findings],
        "evaluation": {
            "scoring_rule": evaluation.scoring_rule,
            "counts": evaluation.counts,
            "results": [{"forecast": r.record["id"], "status": r.status, "reasons": list(r.reasons)} for r in evaluation.results],
        },
        "timestamp_assurance": "unavailable",
    }
    return NormalizationResult(tuple(records), tuple(not_mapped), tuple(findings), report)
