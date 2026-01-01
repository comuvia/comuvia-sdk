"""Typed, read-only view of the published ForeGlass lanes and readings.

Every lane field keeps the meaning the provider's artifact declares (see
``FIELD_MEANINGS``); nothing is upgraded into a stronger claim. In particular:
``lo``/``hi`` carry no declared coverage level; ``due`` is a grading date, not a target
period; ``sealed_at`` is a registration date without a time of day; ``built`` is a build
date, not a publication time; readings are index readings, never forecasts or
probabilities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from comuvia import parse_json

KNOWN_TOP_LEVEL_FIELDS = frozenset({"_schema", "tier", "built", "registry_schema", "seal", "counts", "lanes", "commitments"})
KNOWN_LANE_FIELDS = frozenset({
    "id", "metric", "due", "predShort", "predFull", "kind", "arm", "status", "naive_value", "scope", "sha",
    "statement", "source", "criteria", "qid", "sealed_at", "prompt_version", "val", "lo", "hi", "model", "unit",
    "gkey", "obsKey", "marker", "arm_label", "validation_status", "core_sha256", "validation_card_url", "caveat",
    "caveat_id", "withheld_fields",
})
# Keys expected once grading begins; recognized, but normalizing outcomes is unsupported in 0.1.
OUTCOME_FIELD_NAMES = frozenset({
    "outcome", "outcomes", "observed", "actual", "resolved", "resolved_value", "resolution", "graded", "graded_at",
    "grade", "score", "brier", "hit", "result",
})
STATEMENT_LIMIT, CRITERIA_LIMIT = 320, 220

FIELD_MEANINGS = MappingProxyType({
    "val": "binary lanes: the declared probability of the lane's event; interval lanes: the centre; point lanes: the value",
    "lo": "interval lower bound with no declared coverage level; on a binary lane, a CI on the probability",
    "hi": "interval upper bound with no declared coverage level; engine intervals can be scenario spans (val == hi)",
    "due": "the provider's grading date, not a target period",
    "sealed_at": "the registration date, with no time of day",
    "built": "a build date of the ledger, not a publication time",
    "scope": "a provider label, not a verified geography code",
    "unit": "a shortened display unit; the full unit is the third gkey segment",
    "qid": "q:<metric>@<due>; may be blank",
    "gkey": "<qid>||<kind>||<full unit>; provider variants (arms) of one question share it",
    "statement": "provider text, cut without an ellipsis at 320 characters",
    "criteria": "provider text, cut without an ellipsis at 220 characters",
    "caveat_id": "provider caveat code, e.g. crisis-hazard-model-conditional or outcome-published-before-seal",
    "withheld_fields": "fields the provider withheld from the public lane",
    "naive_value": "a provider baseline value; never a probability",
})


def _optional(lane: Mapping, key: str):
    return lane.get(key)


@dataclass(frozen=True)
class Lane:
    """One published lane. ``raw`` holds every field as published, including unknown ones."""

    id: str
    kind: str
    metric: str
    due: str
    qid: str
    gkey: str
    arm: str
    status: str
    validation_status: str
    scope: str
    unit: str
    val: float
    lo: float | None
    hi: float | None
    sealed_at: str
    statement: str | None
    criteria: str | None
    source: str | None
    model: str | None
    caveat: str | None
    caveat_id: str | None
    withheld_fields: tuple[str, ...]
    raw: Mapping = field(repr=False)

    @classmethod
    def from_json(cls, lane: Mapping) -> Lane:
        return cls(
            id=lane["id"], kind=lane["kind"], metric=lane["metric"], due=lane["due"], qid=lane["qid"],
            gkey=lane["gkey"], arm=lane["arm"], status=lane["status"], validation_status=lane["validation_status"],
            scope=lane["scope"], unit=lane["unit"], val=lane["val"], lo=lane["lo"], hi=lane["hi"],
            sealed_at=lane["sealed_at"], statement=_optional(lane, "statement"), criteria=_optional(lane, "criteria"),
            source=_optional(lane, "source"), model=_optional(lane, "model"), caveat=_optional(lane, "caveat"),
            caveat_id=_optional(lane, "caveat_id"), withheld_fields=tuple(lane.get("withheld_fields") or ()),
            raw=MappingProxyType(dict(lane)),
        )

    @property
    def unknown_fields(self) -> Mapping:
        return MappingProxyType({k: v for k, v in self.raw.items() if k not in KNOWN_LANE_FIELDS})

    @property
    def coverage_level(self) -> dict:
        """Always unknown: the published file declares no interval coverage level."""
        return {"unknown": "provider_declares_no_coverage_level"}

    @property
    def full_unit(self) -> str | None:
        """The third ``gkey`` segment, where the full unit appears."""
        parts = self.gkey.split("||")
        return parts[2] if len(parts) >= 3 and parts[2] else None

    @property
    def possibly_truncated(self) -> dict[str, bool]:
        """Length heuristic, labelled as such: text exactly at the provider's cut length may be truncated."""
        return {
            "statement": self.statement is not None and len(self.statement) == STATEMENT_LIMIT,
            "criteria": self.criteria is not None and len(self.criteria) == CRITERIA_LIMIT,
        }

    @property
    def declared_probability(self) -> float | None:
        """``val`` of a binary lane; ``None`` for every other kind. ``lo``/``hi`` are never probabilities."""
        return self.val if self.kind == "binary" else None


class LaneCatalog:
    """Read-only catalog of the lanes of one ledger."""

    def __init__(self, ledger: Mapping):
        self.ledger = MappingProxyType(dict(ledger))
        self.lanes: tuple[Lane, ...] = tuple(Lane.from_json(lane) for lane in ledger["lanes"])

    @classmethod
    def from_bytes(cls, data: bytes) -> LaneCatalog:
        return cls(parse_json(data))

    @property
    def built(self) -> str | None:
        """The ledger build date. It is not a publication time."""
        return self.ledger.get("built")

    def select(
        self,
        *,
        kind: str | None = None,
        metric: str | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        status: str | None = None,
        validation_status: str | None = None,
        caveat_id: str | None = None,
        arm: str | None = None,
        scope: str | None = None,
    ) -> tuple[Lane, ...]:
        """Lanes matching every given filter (``due`` range inclusive, ISO dates)."""
        def keep(lane: Lane) -> bool:
            return all((
                kind is None or lane.kind == kind,
                metric is None or lane.metric == metric,
                due_from is None or lane.due >= due_from,
                due_to is None or lane.due <= due_to,
                status is None or lane.status == status,
                validation_status is None or lane.validation_status == validation_status,
                caveat_id is None or lane.caveat_id == caveat_id,
                arm is None or lane.arm == arm,
                scope is None or lane.scope == scope,
            ))
        return tuple(lane for lane in self.lanes if keep(lane))

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for lane in self.lanes:
            counts[lane.kind] = counts.get(lane.kind, 0) + 1
        return dict(sorted(counts.items()))


@dataclass(frozen=True)
class Reading:
    """An index reading (e.g. fragility ``latest.json``). Never a forecast or a probability."""

    kind: str
    date: str | None
    reading: float | None
    caveats: tuple[str, ...]
    raw: Mapping = field(repr=False)
    is_forecast: bool = False
    probability: None = None


def _caveats(value, found: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "caveat" and isinstance(item, str):
                if item not in found:
                    found.append(item)
            else:
                _caveats(item, found)
    elif isinstance(value, list):
        for item in value:
            _caveats(item, found)


def read_reading(data: bytes, *, kind: str = "fragility_index_reading") -> Reading:
    """Type a reading artifact, keeping every caveat verbatim."""
    document = parse_json(data)
    caveats: list[str] = []
    _caveats(document, caveats)
    reading = document.get("reading") if isinstance(document, Mapping) else None
    return Reading(
        kind=kind,
        date=document.get("date") if isinstance(document, Mapping) else None,
        reading=reading if isinstance(reading, (int, float)) and not isinstance(reading, bool) else None,
        caveats=tuple(caveats),
        raw=MappingProxyType(dict(document)) if isinstance(document, Mapping) else MappingProxyType({}),
    )
