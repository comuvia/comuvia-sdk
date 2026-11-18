"""Minimal envelope builders for ``comuvia/0.1`` records (usability fix F4).

``new_record`` and ``revise`` remove only mechanical envelope boilerplate (``schema``,
``revision`` and ``predecessor``). Every provenance-bearing field (``data_origin``,
``recorded_by``, ``recorded_at``) must be stated explicitly by the caller and is never
defaulted or silently inherited. Both return a validated ``dict`` or raise ``RefusalError``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

from . import reasons
from .identity import reference_to
from .issues import Issue, RefusalError, pointer_join
from .validation import SCHEMA_VERSION, as_integer, validate

_PROTECTED_NEW = frozenset({"schema", "revision", "predecessor"})
_PROTECTED_REVISE = frozenset({"schema", "record_type", "id", "revision", "predecessor"})


def _plain_copy(value):
    """Deep-copy ``value``, turning ``Mapping`` objects into ``dict`` while leaving tuples untouched."""
    if isinstance(value, Mapping):
        return {k: _plain_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_copy(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_plain_copy(v) for v in value)
    return copy.deepcopy(value)


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


def revise(
    record: Mapping,
    *,
    data_origin: str,
    recorded_by: str,
    recorded_at: str,
    **changes,
) -> dict:
    """Build and validate the next revision of ``record`` without mutating ``record``.

    Increments ``revision`` and sets ``predecessor = reference_to(record)``. ``data_origin``
    is required explicitly (never silently inherited). Top-level members in ``changes``
    replace the previous values whole (no deep merge). Raises ``RefusalError`` if ``record``
    is invalid, if an immutable envelope member appears in ``changes``, or if ``validate()``
    refuses the resulting successor.
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
    body = dict(previous)
    for key, value in changes.items():
        body[key] = _plain_copy(value)
    revision = as_integer(previous["revision"])
    assert revision is not None
    body["revision"] = revision + 1
    body["predecessor"] = reference_to(previous)
    body["data_origin"] = data_origin
    body["recorded_by"] = recorded_by
    body["recorded_at"] = recorded_at
    issues = validate(body)
    if issues:
        raise RefusalError(issues)
    return body
