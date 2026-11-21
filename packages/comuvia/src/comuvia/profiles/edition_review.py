"""A review bound to an exact edition: ``edition-review/1``, ``review-summary/1``, ``contribution/1``.

Pins every member of an edition (for example an article, its captions, its claim map and a
video render) and the exact summary shown to the reviewer. ``review_status`` reports
whether that review is ``current``, ``stale``, ``broken`` or ``invalid`` for the records in
a bundle, and whether it ``covers`` a named destination.

What it is not:
- Not authentication (``decided_by`` is caller-supplied text; ``authentication`` is ``"none"``).
- Not a publication gate (an application calls ``review_status`` and enforces its own policy).
- Not a materiality judgment (any change to a pinned member makes the review ``stale``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from ..identity import DIGEST_PATTERN, canonicalize, is_marker, parse_json, record_digest, verify
from ..issues import RefusalError
from ..validation import instant
from . import dependencies as dp

REVIEW = "edition-review/1"
SUMMARY = "review-summary/1"
CONTRIBUTION = "contribution/1"
STATUSES = ("pending", "approved", "changes_requested", "internal_only")
INVALID_REASONS = (
    "content_digest_mismatch",
    "malformed_review",
    "pending_has_decision",
    "decision_incomplete",
    "unsupported_authentication",
    "fixture_flag_conflict",
    "fixture_not_labelled",
)
BROKEN_REASONS = (
    "member_missing",
    "member_mismatch",
    "member_bytes_changed",
    "summary_missing",
    "summary_mismatch",
    "summary_bytes_changed",
)
STALE_REASONS = (
    "member_superseded",
    "summary_superseded",
    "edition_members_changed",
    "member_affected",
)
COVERS_REASONS = (
    "not_current",
    "decision_pending",
    "not_approved",
    "no_destination",
    "destination_not_approved",
)
MEMBER_STATES = ("match", "superseded", "affected", "mismatch", "missing", "bytes_changed")
_REVIEW_KEYS = {
    "edition",
    "members",
    "summary",
    "status",
    "destinations",
    "decided_by",
    "decided_at",
    "authentication",
    "fixture",
    "note",
}
_REFERENCE_KEYS = {"record_type", "id", "revision", "digest"}


def key_of(body: Mapping) -> tuple:
    return (body.get("record_type"), body.get("id"), body.get("revision"))


def _is_text(value) -> bool:
    return isinstance(value, str) and value != ""


def _is_reference(value) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _REFERENCE_KEYS
        and _is_text(value["record_type"])
        and _is_text(value["id"])
        and isinstance(value["revision"], int)
        and not isinstance(value["revision"], bool)
        and isinstance(value["digest"], str)
        and DIGEST_PATTERN.match(value["digest"]) is not None
    )


def _shape_ok(obj) -> bool:
    if not isinstance(obj, dict) or set(obj) != _REVIEW_KEYS:
        return False
    members = obj["members"]
    if not isinstance(members, list) or not members:
        return False
    if not all(
        isinstance(m, dict)
        and set(m) == {"role", "pin"}
        and _is_text(m["role"])
        and _is_reference(m["pin"])
        for m in members
    ):
        return False
    roles = [m["role"] for m in members]
    if roles != sorted(roles) or len(set(roles)) != len(roles):
        return False
    destinations = obj["destinations"]
    if (
        not isinstance(destinations, list)
        or not all(_is_text(d) for d in destinations)
        or destinations != sorted(set(destinations))
    ):
        return False
    return (
        _is_text(obj["edition"])
        and _is_reference(obj["summary"])
        and obj["status"] in STATUSES
        and (_is_text(obj["decided_by"]) or is_marker(obj["decided_by"]))
        and (is_marker(obj["decided_at"]) or instant(obj["decided_at"]) is not None)
        and _is_text(obj["authentication"])
        and isinstance(obj["fixture"], bool)
        and _is_text(obj["note"])
    )


def _ordered(found_reasons: Iterable[str], order: tuple[str, ...]) -> list[str]:
    found = set(found_reasons)
    return [r for r in order if r in found]


def _review_object(review: Mapping, contents: Mapping) -> tuple[dict | None, list[str]]:
    data = contents.get(key_of(review))
    if data is None or verify(review, content=data).content_identity != "match":
        return None, ["content_digest_mismatch"]
    try:
        obj = parse_json(data)
    except (RefusalError, ValueError):
        return None, ["malformed_review"]
    if review.get("content_schema") != REVIEW or canonicalize(obj) != bytes(data) or not _shape_ok(obj):
        return None, ["malformed_review"]
    invalid: list[str] = []
    decided = _is_text(obj["decided_by"]) or not is_marker(obj["decided_at"])
    if obj["status"] == "pending":
        if decided:
            invalid.append("pending_has_decision")
    elif not (_is_text(obj["decided_by"]) and not is_marker(obj["decided_at"])):
        invalid.append("decision_incomplete")
    if obj["authentication"] != "none":
        invalid.append("unsupported_authentication")
    if obj["fixture"] != (review.get("data_origin") == "synthetic"):
        invalid.append("fixture_flag_conflict")
    if (
        obj["fixture"]
        and obj["status"] != "pending"
        and _is_text(obj["decided_by"])
        and not obj["decided_by"].startswith("fixture:")
    ):
        invalid.append("fixture_not_labelled")
    return obj, invalid


def _pin_state(pin: Mapping, index: dict, contents: Mapping) -> str:
    body = index.get((pin["record_type"], pin["id"], pin["revision"]))
    if body is None:
        return "missing"
    if record_digest(body) != pin["digest"]:
        return "mismatch"
    data = contents.get(key_of(body))
    if data is None or verify(body, content=data).content_identity != "match":
        return "bytes_changed"
    return "match"


def _covers_reasons(state: str, status: str | None, destinations: list[str], destination: str | None) -> list[str]:
    found: list[str] = []
    if state != "current":
        found.append("not_current")
    if status == "pending":
        found.append("decision_pending")
    elif status != "approved":
        found.append("not_approved")
    if destination is None:
        found.append("no_destination")
    elif destination not in destinations:
        found.append("destination_not_approved")
    return found


def review_status(
    review: Mapping,
    records: Iterable[Mapping],
    contents: Mapping,
    *,
    current_members=None,
    changed: Mapping | None = None,
    destination: str | None = None,
) -> dict:
    """Report whether ``review`` is current for ``records``/``contents`` and covers ``destination``."""
    bodies = list(records)
    index = {key_of(b): b for b in bodies}
    latest: dict[tuple, int] = {}
    for record_type, record_id, revision in index:
        if isinstance(revision, int) and not isinstance(revision, bool):
            latest[(record_type, record_id)] = max(revision, latest.get((record_type, record_id), revision))
    obj, invalid = _review_object(review, contents)
    if invalid:
        return {
            "state": "invalid",
            "status": obj["status"] if obj else None,
            "covers": False,
            "reasons": _ordered(invalid, INVALID_REASONS),
            "covers_reasons": _covers_reasons(
                "invalid",
                obj["status"] if obj else None,
                obj["destinations"] if obj else [],
                destination,
            ),
            "members": [],
        }

    assert obj is not None
    affected = set()
    if changed is not None:
        affected = {
            (e["record"]["record_type"], e["record"]["id"], e["record"]["revision"])
            for e in dp.impact(bodies, changed, contents=contents)["records"]
            if e["status"] == "affected"
        }
    broken: list[str] = []
    stale: list[str] = []
    members: list[dict] = []
    for member in obj["members"]:
        pin = member["pin"]
        state = _pin_state(pin, index, contents)
        if state != "match":
            broken.append(
                {"missing": "member_missing", "mismatch": "member_mismatch", "bytes_changed": "member_bytes_changed"}[state]
            )
        else:
            pin_key = (pin["record_type"], pin["id"], pin["revision"])
            if latest.get((pin["record_type"], pin["id"]), pin["revision"]) > pin["revision"]:
                state = "superseded"
                stale.append("member_superseded")
            if pin_key in affected:
                stale.append("member_affected")
                state = "superseded" if state == "superseded" else "affected"
        members.append({"role": member["role"], "pin": dict(pin), "state": state})

    summary = obj["summary"]
    summary_state = _pin_state(summary, index, contents)
    if summary_state != "match":
        broken.append(
            {"missing": "summary_missing", "mismatch": "summary_mismatch", "bytes_changed": "summary_bytes_changed"}[summary_state]
        )
    elif latest.get((summary["record_type"], summary["id"]), summary["revision"]) > summary["revision"]:
        stale.append("summary_superseded")

    if current_members is not None:
        current_list = list(current_members)
        given = {(m["role"], json.dumps(m["pin"], sort_keys=True)) for m in current_list}
        mine = {(m["role"], json.dumps(m["pin"], sort_keys=True)) for m in obj["members"]}
        if len(current_list) != len(obj["members"]) or given != mine:
            stale.append("edition_members_changed")

    if broken:
        overall_state, overall_reasons = "broken", _ordered(broken, BROKEN_REASONS)
    elif stale:
        overall_state, overall_reasons = "stale", _ordered(stale, STALE_REASONS)
    else:
        overall_state, overall_reasons = "current", []

    covers_reasons = _covers_reasons(overall_state, obj["status"], obj["destinations"], destination)
    return {
        "state": overall_state,
        "status": obj["status"],
        "covers": not covers_reasons,
        "reasons": overall_reasons,
        "covers_reasons": covers_reasons,
        "members": members,
    }
