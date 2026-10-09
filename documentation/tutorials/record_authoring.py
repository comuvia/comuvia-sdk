"""Authoring and revising ``comuvia/0.1`` records: an example helper.

Not part of the ``comuvia`` package. It uses only the public ``comuvia`` 0.1.0 API and the
standard library, and reads nothing but the packaged schemas (through ``schema_files()``).
Tutorial E explains it; ``tutorial_e_authoring.py`` checks every value stated there.

It removes mechanics, not judgment:

- ``new_record`` adds the envelope (``schema``, ``record_type``, ``id``, ``revision: 1``,
  ``predecessor: null``, ``data_origin``, ``recorded_by``, ``recorded_at``) and nothing else;
- ``revise`` builds the next revision of a record without changing the record it revises;
  ``repin`` moves exact pins onto a corrected target;
- ``snapshot_content``, ``unretained_content`` and ``descriptor_content`` build the two
  ``content`` shapes;
- ``explain`` adds hints to the issues ``comuvia.validate`` reports;
- ``stale_pins`` lists pins whose target has a later revision, a different digest, or is absent.

Field validation is ``comuvia.validate``, unchanged. Every refusal is an ``AuthoringError``
carrying ``AuthoringIssue(pointer, code, message, hint)`` values. Codes are stable; hint text is
explanation only. The helper never fills, normalizes or removes an ``unknown`` or ``withheld``
marker, and never infers a fact.
"""

from __future__ import annotations

import copy
import functools
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import comuvia

ENVELOPE = ("schema", "record_type", "id", "revision", "predecessor", "data_origin", "recorded_by", "recorded_at")
PROVENANCE = ("data_origin", "recorded_by", "recorded_at")
_SUCCESSOR_ENVELOPE = ("revision", "predecessor", "recorded_by", "recorded_at")
_REFERENCE_KEYS = {"record_type", "id", "revision", "digest"}
_TIMESTAMP = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})\Z")  # \Z: "$" would also match before a final newline


@dataclass(frozen=True, order=True)
class AuthoringIssue:
    """One named problem. ``hint`` is explanation, not contract; ``code`` is the contract."""

    pointer: str
    code: str
    message: str = ""
    hint: str = ""


class AuthoringError(ValueError):
    """A refused request. ``issues`` is a sorted tuple of ``AuthoringIssue``."""

    def __init__(self, issues: Iterable[AuthoringIssue]):
        self.issues = tuple(sorted(issues))
        super().__init__("authoring_refused: " + ", ".join(i.code for i in self.issues))

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.issues]


def _escape(token) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _missing(value) -> bool:
    return value is None or value == ""


# ----------------------------------------------------------------------------- hints


def _resolve(node, common: Mapping):
    """Follow a ``$ref`` into common.json's ``$defs``."""
    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str) and "#/$defs/" in node["$ref"]:
        node = common["$defs"][node["$ref"].split("#/$defs/", 1)[1]]
    return node


def _collect_enums(node, path: tuple, common: Mapping, found: dict, depth: int = 0) -> None:
    node = _resolve(node, common)
    if not isinstance(node, Mapping) or depth > 12:
        return
    if isinstance(node.get("enum"), list):
        found.setdefault(path, set()).add(tuple(sorted(node["enum"], key=json.dumps)))
    for alternative in (node.get("anyOf") or []) + (node.get("oneOf") or []):
        _collect_enums(alternative, path, common, found, depth + 1)
    for name, child in (node.get("properties") or {}).items():
        _collect_enums(child, path + (name,), common, found, depth + 1)
    if "items" in node:
        _collect_enums(node["items"], path + ("*",), common, found, depth + 1)


@functools.lru_cache(maxsize=1)
def _enumerations() -> dict:
    """Pointer path (array indices as ``*``) -> allowed values, read from the packaged schemas.

    A path is listed only when every record type that has it allows the same values.
    """
    folder = comuvia.schema_files()
    common = json.loads((folder / "common.json").read_text(encoding="utf-8"))
    found: dict = {}
    for path in folder.iterdir():
        if path.name != "common.json" and path.name.endswith(".json"):
            _collect_enums(json.loads(path.read_text(encoding="utf-8")), (), common, found)
    return {p: values.pop() for p, values in found.items() if len(values) == 1}


def allowed_values(pointer: str) -> tuple | None:
    """The allowed values at ``pointer`` according to the packaged schemas, or None."""
    tokens = [] if pointer == "" else pointer[1:].split("/")
    key = tuple("*" if t.isdigit() else t.replace("~1", "/").replace("~0", "~") for t in tokens)
    return _enumerations().get(key)


def _hint(issue) -> str:
    code, pointer = issue.code, issue.pointer
    if code == "unsupported_schema_version":
        return f"Let new_record set schema; it is always {comuvia.SCHEMA_VERSION!r}."
    if code == "unrecognized_member" and pointer.count("/") == 1:
        return ("Custom data belongs under 'extensions', with a namespaced key such as "
                "'org.example.topic/v1'.")
    if code == "invalid_value":
        values = allowed_values(pointer)
        return ("Allowed values: " + ", ".join(v if isinstance(v, str) else json.dumps(v) for v in values) + ".") if values else ""
    if code == "malformed_digest" and pointer.startswith("/content"):
        return ("Use snapshot_content(data, media_type) or descriptor_content(data, media_type) for bytes "
                "you hold, or unretained_content(...) with an unknown or withheld marker for bytes you did not keep.")
    if code == "invalid_predecessor":
        return "Use revise(previous, ...): it sets revision and predecessor from the record it revises."
    if code == "invalid_timestamp":
        return "RFC 3339 with an explicit offset, for example 2026-10-04T14:00:00Z."
    if code == "missing_required_field":
        return 'Every field is required. State a value you do not know with a marker, for example {"unknown": "<code>"}.'
    return ""


def explain(issues: Iterable) -> list[AuthoringIssue]:
    """``comuvia`` issues as ``AuthoringIssue`` values: pointer, code and message unchanged, plus a hint."""
    return sorted(AuthoringIssue(i.pointer, i.code, i.message, _hint(i)) for i in issues)


def _refuse_core(body: Mapping) -> None:
    issues = comuvia.validate(body)
    if issues:
        raise AuthoringError(explain(issues))


# ----------------------------------------------------------------------------- content


def snapshot_content(data, media_type: str) -> dict:
    """The ``resource_snapshot`` content object for bytes you retain."""
    if not isinstance(data, (bytes, bytearray)):
        raise AuthoringError([AuthoringIssue("/content", "invalid_content_input", "content must be bytes",
                                             "Pass the exact retained bytes, not text or a path.")])
    data = bytes(data)
    return {"media_type": media_type, "retained": True, "byte_length": len(data), "digest": comuvia.content_digest(data)}


def unretained_content(media_type: str, *, byte_length, digest) -> dict:
    """The ``resource_snapshot`` content object for bytes you did not keep. Every value is stated by the caller."""
    return {"media_type": media_type, "retained": False, "byte_length": byte_length, "digest": digest}


def descriptor_content(data, media_type: str) -> dict:
    """The ``artifact_descriptor`` content object: no ``retained`` key."""
    if not isinstance(data, (bytes, bytearray)):
        raise AuthoringError([AuthoringIssue("/content", "invalid_content_input", "content must be bytes",
                                             "Pass the exact bytes of the artifact, not text or a path.")])
    data = bytes(data)
    return {"media_type": media_type, "byte_length": len(data), "digest": comuvia.content_digest(data)}


# ----------------------------------------------------------------------------- records


def _provenance_issues(values: Mapping) -> list[AuthoringIssue]:
    return [AuthoringIssue(f"/{name}", "missing_provenance", f"{name} is required",
                           "State who recorded the record, when, and whether it describes observed or synthetic material.")
            for name, value in values.items() if _missing(value)]


def new_record(record_type, record_id, *, data_origin=None, recorded_by=None, recorded_at=None, fields=None) -> dict:
    """A new revision 1 record: the envelope plus a deep copy of ``fields``, nothing else."""
    fields = {} if fields is None else fields
    issues = _provenance_issues({"data_origin": data_origin, "recorded_by": recorded_by, "recorded_at": recorded_at})
    issues += [AuthoringIssue(f"/{_escape(k)}", "protected_field", f"{k} is set by new_record",
                              "Pass record_type, id and the provenance values as arguments.") for k in fields if k in ENVELOPE]
    if issues:
        raise AuthoringError(issues)
    body = {"schema": comuvia.SCHEMA_VERSION, "record_type": record_type, "id": record_id, "revision": 1,
            "predecessor": None, "data_origin": data_origin, **copy.deepcopy(dict(fields)),
            "recorded_by": recorded_by, "recorded_at": recorded_at}
    _refuse_core(body)
    return body


def _instant(text):
    """(UTC second, fraction) of an RFC 3339 timestamp, exactly; None if it is not one."""
    match = _TIMESTAMP.match(text) if isinstance(text, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    offset = match.group(8)
    delta = timedelta(0) if offset == "Z" else (1 if offset[0] == "+" else -1) * timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6]))
    try:
        moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc) - delta
    except ValueError:
        return None
    return moment, Decimal("0" + (match.group(7) or ""))


instant = _instant  # public alias: (UTC second, exact fraction) of an RFC 3339 timestamp, or None


def _replace_pins(value, old: dict, new: dict, top: bool = True):
    """(copy of value with every exact ``old`` pin replaced by ``new``, number replaced); skips top-level predecessor."""
    if isinstance(value, Mapping):
        if dict(value) == old:
            return copy.deepcopy(new), 1
        result, count = {}, 0
        for key, item in value.items():
            if top and key == "predecessor":
                result[key] = item
                continue
            result[key], found = _replace_pins(item, old, new, False)
            count += found
        return result, count
    if isinstance(value, list):
        pairs = [_replace_pins(item, old, new, False) for item in value]
        return [p[0] for p in pairs], sum(p[1] for p in pairs)
    return value, 0


def revise(previous: Mapping, *, recorded_by=None, recorded_at=None, replace=None, repin: Sequence = (), data_origin=None) -> dict:
    """The next revision of ``previous``; ``previous`` itself is never changed.

    ``replace`` substitutes whole top-level values (no merging). ``repin`` is a sequence of
    ``(old, new)`` records: every exact ``reference_to(old)`` in the body, extensions included,
    becomes ``reference_to(new)``. ``predecessor`` is set to ``reference_to(previous)``.
    """
    _refuse_core(previous)
    replace = {} if replace is None else replace
    issues = [AuthoringIssue(f"/{_escape(k)}", "protected_field", f"{k} is set by revise",
                             "Use the data_origin= argument to change data_origin; the other envelope fields follow from previous."
                             if k == "data_origin" else "revise sets this from previous and its own arguments.")
              for k in replace if k in ENVELOPE]
    provenance = {"recorded_by": recorded_by, "recorded_at": recorded_at}
    if data_origin is not None:
        provenance["data_origin"] = data_origin
    issues += _provenance_issues(provenance)
    before, after = _instant(previous["recorded_at"]), _instant(recorded_at)
    if before is not None and after is not None and after < before:
        issues.append(AuthoringIssue("/recorded_at", "recorded_before_predecessor",
                                     "recorded_at is earlier than the revision it succeeds",
                                     "A correction is recorded after the record it corrects; keep the earlier time on the earlier revision."))

    body = copy.deepcopy(dict(previous))
    for key, value in replace.items():
        if key not in ENVELOPE:
            body[key] = copy.deepcopy(value)
    for index, pair in enumerate(repin):
        old, new = pair
        at = f"/repin/{index}"
        if (old.get("record_type"), old.get("id")) != (new.get("record_type"), new.get("id")) \
                or not isinstance(new.get("revision"), int) or not isinstance(old.get("revision"), int) \
                or new["revision"] <= old["revision"]:
            issues.append(AuthoringIssue(at, "not_a_successor", "new is not a later revision of the same record",
                                         "Pair each record with a later revision of itself."))
            continue
        body, count = _replace_pins(body, comuvia.reference_to(old), comuvia.reference_to(new))
        if count == 0:
            issues.append(AuthoringIssue(at, "pin_not_found", "the record does not pin old",
                                         "Only exact reference_to(old) values are moved."))
    if data_origin is not None:
        body["data_origin"] = data_origin
    if not issues and \
            {k: v for k, v in body.items() if k not in _SUCCESSOR_ENVELOPE} == \
            {k: v for k, v in previous.items() if k not in _SUCCESSOR_ENVELOPE}:
        issues.append(AuthoringIssue("", "no_change", "the successor would equal previous",
                                     "A revision records a correction; state what changed through replace, repin or data_origin."))
    if issues:
        raise AuthoringError(issues)
    body["revision"] = previous["revision"] + 1
    body["predecessor"] = comuvia.reference_to(previous)
    body["recorded_by"] = recorded_by
    body["recorded_at"] = recorded_at
    _refuse_core(body)
    return body


# ----------------------------------------------------------------------------- stale pins


def _pins(value, pointer: str = "", top: bool = True):
    if isinstance(value, Mapping):
        if set(value) == _REFERENCE_KEYS:
            yield pointer, value
            return
        for key, item in value.items():
            if top and key == "predecessor":
                continue
            yield from _pins(item, f"{pointer}/{_escape(key)}", False)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _pins(item, f"{pointer}/{index}", False)


def stale_pins(records: Iterable[Mapping]) -> list[dict]:
    """Pins (outside ``predecessor``) that are ``superseded``, ``mismatch`` or ``missing``. Read-only.

    ``superseded``: the pin matches, but the bundle holds a later revision of its target.
    """
    bodies = list(records)
    index = {(b.get("record_type"), b.get("id"), b.get("revision")): b for b in bodies}
    latest = {}
    for (record_type, record_id, revision) in index:
        if isinstance(revision, int):
            latest[(record_type, record_id)] = max(revision, latest.get((record_type, record_id), revision))
    found = []
    for body in bodies:
        holder = {"record_type": body.get("record_type"), "id": body.get("id"), "revision": body.get("revision")}
        for pointer, pin in _pins(body):
            target = index.get((pin["record_type"], pin["id"], pin["revision"]))
            newest = latest.get((pin["record_type"], pin["id"]))
            if target is None:
                state = "missing"
            elif comuvia.record_digest(target) != pin["digest"]:
                state = "mismatch"
            elif newest is not None and newest > pin["revision"]:
                state = "superseded"
            else:
                continue
            found.append({"record": holder, "pointer": pointer, "pin": dict(pin), "state": state,
                          "latest": None if newest is None else {"record_type": pin["record_type"], "id": pin["id"], "revision": newest}})
    return sorted(found, key=lambda e: (str(e["record"]["record_type"]), str(e["record"]["id"]),
                                        e["record"]["revision"] or 0, e["pointer"]))
