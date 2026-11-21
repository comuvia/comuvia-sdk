"""Envelope, content, marker and pin-cascade builders for ``comuvia/0.1`` records.

``new_record`` and ``revise`` remove only mechanical envelope boilerplate (``schema``,
``revision`` and ``predecessor``). Every provenance-bearing field (``data_origin``,
``recorded_by``, ``recorded_at``) must be stated explicitly by the caller and is never
defaulted or silently inherited. Both return a validated ``dict`` or raise ``RefusalError``.

``revise(..., repin=[(old_record, new_record), ...])`` moves exact ``reference_to(old)``
pins across core fields and ``extensions`` onto a successor revision without touching
``predecessor``. ``stale_pins(records)`` reports ``superseded``, ``mismatch`` and
``missing`` pins across core fields and ``extensions``.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import reasons
from .identity import DIGEST_PATTERN, content_digest, is_marker, record_digest, reference_to
from .issues import Issue, RefusalError, pointer_join
from .validation import SCHEMA_VERSION, as_integer, instant, validate

_PROTECTED_NEW = frozenset({"schema", "revision", "predecessor"})
_PROTECTED_REVISE = frozenset({"schema", "record_type", "id", "revision", "predecessor"})
_SUCCESSOR_ENVELOPE = frozenset({"revision", "predecessor", "recorded_by", "recorded_at"})
_REFERENCE_KEYS = frozenset({"record_type", "id", "revision", "digest"})
_MARKER_CODE = re.compile(r"^[a-z][a-z0-9_]*\Z")


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _plain_copy(value):
    """Deep-copy ``value``, turning ``Mapping`` objects into ``dict`` while leaving tuples untouched."""
    if isinstance(value, Mapping):
        return {k: _plain_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_copy(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_plain_copy(v) for v in value)
    return copy.deepcopy(value)


def snapshot_content(data: bytes | bytearray | memoryview, media_type: str) -> dict:
    """Build a ``resource_snapshot`` ``content`` object for retained bytes."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise RefusalError([Issue("/content", reasons.INVALID_CONTENT_INPUT, "content must be bytes")])
    raw = bytes(data)
    return {
        "media_type": media_type,
        "retained": True,
        "byte_length": len(raw),
        "digest": content_digest(raw),
    }


def unretained_content(media_type: str, *, byte_length, digest) -> dict:
    """Build a ``resource_snapshot`` ``content`` object for unretained bytes (explicit values or markers)."""
    return {
        "media_type": media_type,
        "retained": False,
        "byte_length": _plain_copy(byte_length),
        "digest": _plain_copy(digest),
    }


def descriptor_content(data: bytes | bytearray | memoryview, media_type: str) -> dict:
    """Build an ``artifact_descriptor`` ``content`` object (no ``retained`` member)."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise RefusalError([Issue("/content", reasons.INVALID_CONTENT_INPUT, "content must be bytes")])
    raw = bytes(data)
    return {
        "media_type": media_type,
        "byte_length": len(raw),
        "digest": content_digest(raw),
    }


def not_applicable_marker(code: str = "not_applicable", *, note: str | None = None) -> dict:
    """Return the documented ``0.1`` marker convention for a field that does not apply."""
    if not isinstance(code, str) or _MARKER_CODE.match(code) is None:
        raise RefusalError([Issue("/unknown", reasons.INVALID_MARKER, "marker code must match ^[a-z][a-z0-9_]*$")])
    marker: dict = {"unknown": code}
    if note is not None:
        if not isinstance(note, str) or note == "":
            raise RefusalError([Issue("/note", reasons.INVALID_MARKER, "marker note must be a non-empty string")])
        if _has_surrogate(note):
            raise RefusalError([Issue("/note", reasons.LONE_SURROGATE, "marker note contains an unpaired surrogate")])
        marker["note"] = note
    return marker


def is_not_applicable(value) -> bool:
    """True when ``value`` is a schema-valid ``0.1`` marker stating ``not_applicable``."""
    if not isinstance(value, Mapping) or "unknown" not in value:
        return False
    if not set(value) <= {"unknown", "note"} or value.get("unknown") != "not_applicable":
        return False
    if "note" in value:
        note = value["note"]
        if not isinstance(note, str) or note == "" or _has_surrogate(note):
            return False
    return True


def new_record(
    record_type: str,
    id: str,
    *,
    data_origin: str,
    recorded_by: str,
    recorded_at: str,
    **fields,
) -> dict:
    """Build and validate a revision-1 ``comuvia/0.1`` record.

    Sets ``schema="comuvia/0.1"``, ``revision=1`` and ``predecessor=None`` only. Never
    defaults ``data_origin``, ``recorded_by`` or ``recorded_at``. Raises ``RefusalError``
    if a protected envelope field is passed in ``fields`` or if ``validate()`` refuses it.
    """
    protected = [
        Issue(pointer_join("", key), reasons.PROTECTED_FIELD, f"{key} is set by new_record")
        for key in sorted(fields)
        if key in _PROTECTED_NEW
    ]
    if protected:
        raise RefusalError(protected)
    body = {
        "schema": SCHEMA_VERSION,
        "record_type": record_type,
        "id": id,
        "revision": 1,
        "predecessor": None,
        "data_origin": data_origin,
        **{k: _plain_copy(v) for k, v in fields.items()},
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
    }
    issues = validate(body)
    if issues:
        raise RefusalError(issues)
    return body


def _replace_pins(value, old_ref: dict, new_ref: dict, top: bool = True) -> tuple[object, int]:
    """Replace every exact ``old_ref`` pin with ``new_ref``, skipping top-level ``predecessor``."""
    if isinstance(value, Mapping):
        if dict(value) == old_ref:
            return dict(new_ref), 1
        result, count = {}, 0
        for key, item in value.items():
            if top and key == "predecessor":
                result[key] = item
                continue
            result[key], found = _replace_pins(item, old_ref, new_ref, False)
            count += found
        return result, count
    if isinstance(value, list):
        replaced_items = [_replace_pins(item, old_ref, new_ref, False) for item in value]
        return [p[0] for p in replaced_items], sum(p[1] for p in replaced_items)
    return value, 0


def revise(
    record: Mapping,
    *,
    data_origin: str,
    recorded_by: str,
    recorded_at: str,
    repin: Sequence[tuple[Mapping, Mapping]] = (),
    require_change: bool = False,
    enforce_monotonic_time: bool = False,
    **changes,
) -> dict:
    """Build and validate the next revision of ``record`` without mutating ``record``.

    Increments ``revision`` and sets ``predecessor = reference_to(record)``. ``data_origin``
    is required explicitly (never silently inherited). Top-level members in ``changes``
    replace the previous values whole (no deep merge). ``repin`` is an optional sequence of
    ``(old_record, new_record)`` pairs: every exact ``reference_to(old_record)`` across core
    fields and ``extensions`` (excluding ``predecessor``) becomes ``reference_to(new_record)``.
    """
    if not isinstance(record, Mapping):
        raise RefusalError([Issue("", reasons.NOT_AN_OBJECT, "a record body is a JSON object")])
    previous = _plain_copy(record)
    prior_issues = validate(previous)
    if prior_issues:
        raise RefusalError(prior_issues)
    protected = [
        Issue(pointer_join("", key), reasons.PROTECTED_FIELD, f"{key} is set by revise")
        for key in sorted(changes)
        if key in _PROTECTED_REVISE
    ]
    if protected:
        raise RefusalError(protected)

    pre_issues: list[Issue] = []
    if enforce_monotonic_time:
        before = instant(previous["recorded_at"])
        after = instant(recorded_at)
        if before is not None and after is not None and after < before:
            pre_issues.append(
                Issue("/recorded_at", reasons.RECORDED_BEFORE_PREDECESSOR,
                      "recorded_at is earlier than the revision it succeeds")
            )

    body = dict(previous)
    for key, value in changes.items():
        body[key] = _plain_copy(value)
    body["data_origin"] = data_origin

    if isinstance(repin, (str, bytes, bytearray, memoryview, Mapping)) or not isinstance(repin, Iterable):
        raise RefusalError([Issue("/repin", reasons.INVALID_TYPE, "repin must be a sequence of (old, new) record pairs")])
    for index, pair in enumerate(repin):
        at = f"/repin/{index}"
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            pre_issues.append(Issue(at, reasons.INVALID_TYPE, "each repin item must be an (old, new) record pair"))
            continue
        old_rec, new_rec = pair
        if not isinstance(old_rec, Mapping) or not isinstance(new_rec, Mapping):
            pre_issues.append(Issue(at, reasons.NOT_AN_OBJECT, "repin targets must be record mappings"))
            continue
        old_plain, new_plain = _plain_copy(old_rec), _plain_copy(new_rec)
        if validate(old_plain) or validate(new_plain):
            pre_issues.append(Issue(at, reasons.NOT_A_SUCCESSOR, "repin targets must be valid comuvia records"))
            continue
        old_rev, new_rev = as_integer(old_plain["revision"]), as_integer(new_plain["revision"])
        if (
            (old_plain.get("record_type"), old_plain.get("id")) != (new_plain.get("record_type"), new_plain.get("id"))
            or old_rev is None or new_rev is None or new_rev <= old_rev
        ):
            pre_issues.append(Issue(at, reasons.NOT_A_SUCCESSOR, "new is not a later revision of the same record"))
            continue
        replaced_body, count = _replace_pins(body, reference_to(old_plain), reference_to(new_plain))
        body = replaced_body  # type: ignore[assignment]
        if count == 0:
            pre_issues.append(Issue(at, reasons.PIN_NOT_FOUND, "the record does not pin old"))

    if require_change and not pre_issues:
        comparable_new = {k: v for k, v in body.items() if k not in _SUCCESSOR_ENVELOPE}
        comparable_old = {k: v for k, v in previous.items() if k not in _SUCCESSOR_ENVELOPE}
        if comparable_new == comparable_old:
            pre_issues.append(Issue("", reasons.NO_CHANGE, "the successor would equal previous"))

    if pre_issues:
        raise RefusalError(pre_issues)

    revision = as_integer(previous["revision"])
    assert revision is not None
    body["revision"] = revision + 1
    body["predecessor"] = reference_to(previous)
    body["recorded_by"] = recorded_by
    body["recorded_at"] = recorded_at
    issues = validate(body)
    if issues:
        raise RefusalError(issues)
    return body


@dataclass(frozen=True, order=True)
class StalePin:
    """A pin (outside ``predecessor``) that is ``superseded``, ``mismatch`` or ``missing``."""

    record_type: str
    id: str
    revision: int
    pointer: str
    state: str  # "superseded" | "mismatch" | "missing"
    pin: dict
    latest_revision: int | None = None

    def as_dict(self) -> dict:
        return {
            "record": {"record_type": self.record_type, "id": self.id, "revision": self.revision},
            "pointer": self.pointer,
            "pin": dict(self.pin),
            "state": self.state,
            "latest": (
                None if self.latest_revision is None
                else {"record_type": self.pin["record_type"], "id": self.pin["id"], "revision": self.latest_revision}
            ),
        }


def _iter_all_pins(value, pointer: str = "", top: bool = True):
    if isinstance(value, Mapping):
        if (
            set(value) == _REFERENCE_KEYS
            and isinstance(value.get("record_type"), str)
            and isinstance(value.get("id"), str)
            and isinstance(value.get("revision"), int)
            and not isinstance(value.get("revision"), bool)
            and isinstance(value.get("digest"), str)
            and DIGEST_PATTERN.match(value["digest"]) is not None
        ):
            yield pointer, value
            return
        for key, item in value.items():
            if top and key == "predecessor":
                continue
            yield from _iter_all_pins(item, pointer_join(pointer, key), False)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_all_pins(item, pointer_join(pointer, index), False)


def stale_pins(records: Iterable[Mapping]) -> list[StalePin]:
    """Return sorted ``StalePin`` entries across core fields and ``extensions`` (excluding ``predecessor``)."""
    bodies = list(records)
    index = {(b.get("record_type"), b.get("id"), b.get("revision")): b for b in bodies}
    latest: dict[tuple, int] = {}
    for record_type, record_id, revision in index:
        if isinstance(revision, int) and not isinstance(revision, bool):
            latest[(record_type, record_id)] = max(revision, latest.get((record_type, record_id), revision))
    found: list[StalePin] = []
    for body in bodies:
        rt = str(body.get("record_type", ""))
        rid = str(body.get("id", ""))
        rev = body.get("revision") if isinstance(body.get("revision"), int) and not isinstance(body.get("revision"), bool) else 0
        for pointer, pin in _iter_all_pins(body):
            target = index.get((pin["record_type"], pin["id"], pin["revision"]))
            newest = latest.get((pin["record_type"], pin["id"]))
            if target is None:
                state = "missing"
            elif record_digest(target) != pin["digest"]:
                state = "mismatch"
            elif newest is not None and newest > pin["revision"]:
                state = "superseded"
            else:
                continue
            found.append(StalePin(rt, rid, rev, pointer, state, dict(pin), newest))
    return sorted(found, key=lambda s: (s.record_type, s.id, s.revision, s.pointer))
