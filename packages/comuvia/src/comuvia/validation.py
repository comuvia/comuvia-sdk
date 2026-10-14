"""Validation of single comuvia 0.1 records.

The JSON Schema files under ``comuvia/schemas/v0_1`` are the authority for record
structure. This module interprets exactly the keyword subset those files use (refusing
any other keyword at load time), maps failures to named reason codes, and then applies
the semantic rules JSON Schema cannot express: calendar validity, period order,
predecessor linkage, selector bounds, coverage counts and time order.

Validation never consults other records; cross-record eligibility is evaluated later.
"""

from __future__ import annotations

import datetime as _dt
import functools
import importlib.resources
import math
import re
from collections.abc import Mapping

from . import reasons
from .identity import digest_issue, parse_json
from .issues import Issue, RefusalError, pointer_join

SCHEMA_VERSION = "comuvia/0.1"
SCHEMA_ID_PREFIX = "urn:comuvia:schema:0.1:"
RECORD_TYPES = (
    "resource_snapshot", "source_assertion", "interpretation", "assessment",
    "question", "forecast", "outcome", "evaluation", "artifact_descriptor",
)

_KEYWORDS = frozenset({
    "$schema", "$id", "$ref", "$defs", "title", "description",
    "type", "const", "enum", "properties", "required", "additionalProperties", "propertyNames",
    "items", "minItems", "maxItems", "uniqueItems", "minimum", "maximum", "minLength", "pattern",
    "anyOf", "allOf", "if", "then", "else", "x-comuvia-code", "x-comuvia-semantic",
})
# Codes a schema's ``x-comuvia-code`` may replace with its own, more specific code.
_REMAPPABLE = frozenset({reasons.INVALID_TYPE, reasons.INVALID_VALUE, reasons.OUT_OF_RANGE, reasons.UNRECOGNIZED_MEMBER})
_TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,9}))?(Z|([+-])([0-9]{2}):([0-9]{2}))\Z"
)


def schema_files():
    """The packaged schema resource directory (an ``importlib.resources`` traversable)."""
    return importlib.resources.files("comuvia").joinpath("schemas").joinpath("v0_1")


def _check_keywords(schema, where: str) -> None:
    if isinstance(schema, bool):
        return
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise RuntimeError(f"schema {where} uses unsupported keywords {sorted(unknown)}")
    if "pattern" in schema and not (schema["pattern"].startswith("^") and schema["pattern"].endswith("$")):
        raise RuntimeError(f"schema {where} has an unanchored pattern")
    for key in ("items", "propertyNames", "additionalProperties", "if", "then", "else"):
        if isinstance(schema.get(key), (dict, bool)):
            _check_keywords(schema[key], f"{where}/{key}")
    for key in ("properties", "$defs"):
        for name, sub in schema.get(key, {}).items():
            _check_keywords(sub, f"{where}/{key}/{name}")
    for key in ("anyOf", "allOf"):
        for index, sub in enumerate(schema.get(key, [])):
            _check_keywords(sub, f"{where}/{key}/{index}")


@functools.lru_cache(maxsize=1)
def load_schemas() -> dict[str, dict]:
    """Load every packaged schema, keyed by ``$id``."""
    registry = {}
    for entry in sorted(schema_files().iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            schema = parse_json(entry.read_bytes())
            _check_keywords(schema, entry.name)
            registry[schema["$id"]] = schema
    missing = [t for t in RECORD_TYPES if SCHEMA_ID_PREFIX + t not in registry]
    if missing or SCHEMA_ID_PREFIX + "common" not in registry:
        raise RuntimeError(f"packaged schemas incomplete: missing {missing}")
    return registry


@functools.lru_cache(maxsize=None)
def _compile(pattern: str) -> re.Pattern:
    # ECMA-262 '$' without the multiline flag matches only at the end of input.
    return re.compile(pattern[:-1] + r"\Z")


def _type_ok(value, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if isinstance(value, bool):
        return False
    if name == "number":
        return isinstance(value, (int, float))
    if name == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    raise RuntimeError(f"unknown schema type {name}")


def _non_finite(value) -> bool:
    """A float that is NaN, +inf or -inf: never a JSON number."""
    return isinstance(value, float) and not math.isfinite(value)


def _json_equal(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


class _Interpreter:
    def __init__(self, registry: dict[str, dict]):
        self.registry = registry

    def resolve(self, reference: str, base: str) -> tuple[dict, str]:
        document, _, fragment = reference.partition("#")
        document = document or base
        schema = self.registry[document]
        for token in [t for t in fragment.split("/") if t]:
            schema = schema[token.replace("~1", "/").replace("~0", "~")]
        return schema, document

    def admits(self, schema, value, base: str) -> bool:
        """Whether a subschema's declared type (following $ref) admits the value."""
        while "$ref" in schema and "type" not in schema:
            schema, base = self.resolve(schema["$ref"], base)
        if "allOf" in schema and "type" not in schema:
            return all(self.admits(s, value, base) for s in schema["allOf"])
        if "anyOf" in schema and "type" not in schema:
            return any(self.admits(s, value, base) for s in schema["anyOf"])
        declared = schema.get("type")
        if declared is None:
            return True
        return any(_type_ok(value, t) for t in ([declared] if isinstance(declared, str) else declared))

    def is_marker_schema(self, schema, base: str) -> bool:
        while "$ref" in schema:
            schema, base = self.resolve(schema["$ref"], base)
        return schema.get("x-comuvia-code") == reasons.INVALID_MARKER

    def check(self, value, schema, pointer: str, base: str, notes: list) -> list[Issue]:
        if schema is True:
            return []
        if schema is False:
            return [Issue(pointer, reasons.UNRECOGNIZED_MEMBER, "not allowed")]
        if _non_finite(value):
            # NaN fails every comparison, so range checks would pass it; refuse it here with the
            # code strict parsing uses, at any schema-checked position.
            return [Issue(pointer, reasons.NON_FINITE_NUMBER, "non-finite number")]
        issues: list[Issue] = []
        local: list = []
        if "$ref" in schema:
            target, target_base = self.resolve(schema["$ref"], base)
            issues += self.check(value, target, pointer, target_base, local)
        if "type" in schema:
            declared = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
            if not any(_type_ok(value, t) for t in declared):
                code = reasons.NULL_NOT_ALLOWED if value is None else reasons.INVALID_TYPE
                return self._finish(schema, [Issue(pointer, code, f"expected {'/'.join(declared)}")], notes, [], pointer, value)
        if "const" in schema and not _json_equal(value, schema["const"]):
            issues.append(Issue(pointer, reasons.INVALID_VALUE, f"expected {schema['const']!r}"))
        if "enum" in schema and not any(_json_equal(value, option) for option in schema["enum"]):
            issues.append(Issue(pointer, reasons.INVALID_VALUE, "not one of the allowed values"))
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                issues.append(Issue(pointer, reasons.INVALID_VALUE, "too short"))
            if "pattern" in schema and not _compile(schema["pattern"]).search(value):
                issues.append(Issue(pointer, reasons.INVALID_VALUE, "does not match the required form"))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                issues.append(Issue(pointer, reasons.OUT_OF_RANGE, f"below {schema['minimum']}"))
            if "maximum" in schema and value > schema["maximum"]:
                issues.append(Issue(pointer, reasons.OUT_OF_RANGE, f"above {schema['maximum']}"))
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                issues.append(Issue(pointer, reasons.INVALID_VALUE, f"fewer than {schema['minItems']} items"))
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                issues.append(Issue(pointer, reasons.INVALID_VALUE, f"more than {schema['maxItems']} items"))
            if schema.get("uniqueItems") and any(
                _json_equal(value[i], value[j]) for i in range(len(value)) for j in range(i)
            ):
                issues.append(Issue(pointer, reasons.INVALID_VALUE, "items repeat"))
            if "items" in schema:
                for index, item in enumerate(value):
                    issues += self.check(item, schema["items"], pointer_join(pointer, index), base, local)
        if isinstance(value, dict):
            properties = schema.get("properties", {})
            for name in schema.get("required", []):
                if name not in value:
                    issues.append(Issue(pointer_join(pointer, name), reasons.MISSING_REQUIRED_FIELD, "required member is absent"))
            if "propertyNames" in schema:
                for name in value:
                    issues += self.check(name, schema["propertyNames"], pointer_join(pointer, name), base, [])
            for name, item in value.items():
                if name in properties:
                    issues += self.check(item, properties[name], pointer_join(pointer, name), base, local)
                elif "additionalProperties" in schema:
                    issues += self.check(item, schema["additionalProperties"], pointer_join(pointer, name), base, local)
        for sub in schema.get("allOf", []):
            issues += self.check(value, sub, pointer, base, local)
        if "anyOf" in schema:
            issues += self._any_of(value, schema["anyOf"], pointer, base, local)
        if "if" in schema:
            branch = "then" if not self.check(value, schema["if"], pointer, base, []) else "else"
            if branch in schema:
                issues += self.check(value, schema[branch], pointer, base, local)
        return self._finish(schema, issues, notes, local, pointer, value)

    def _any_of(self, value, branches, pointer: str, base: str, notes: list) -> list[Issue]:
        if _non_finite(value):
            return [Issue(pointer, reasons.NON_FINITE_NUMBER, "non-finite number")]
        attempts = []
        for branch in branches:
            branch_notes: list = []
            found = self.check(value, branch, pointer, base, branch_notes)
            if not found:
                notes.extend(branch_notes)
                return []
            attempts.append((branch, found))
        marker_shaped = isinstance(value, dict) and ("unknown" in value or "withheld" in value)
        if marker_shaped:
            for branch, found in attempts:
                if self.is_marker_schema(branch, base) and ("unknown" in value) == self._marker_key(branch, base):
                    return found
        for branch, found in attempts:
            if self.admits(branch, value, base) and not self.is_marker_schema(branch, base):
                return found
        code = reasons.NULL_NOT_ALLOWED if value is None else reasons.INVALID_TYPE
        return [Issue(pointer, code, "no allowed form matches")]

    def _marker_key(self, schema, base: str) -> bool:
        while "$ref" in schema:
            schema, base = self.resolve(schema["$ref"], base)
        return "unknown" in schema.get("properties", {})

    @staticmethod
    def _finish(schema, issues, notes, local, pointer, value) -> list[Issue]:
        code = schema.get("x-comuvia-code")
        if code and issues:
            issues = [Issue(i.pointer, code, i.message) if i.code in _REMAPPABLE else i for i in issues]
        if not issues:
            notes.extend(local)
            if "x-comuvia-semantic" in schema:
                notes.append((schema["x-comuvia-semantic"], pointer, value))
        return issues


# ------------------------------------------------------------------ semantic rules


_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def instant(text: str) -> tuple[int, int] | None:
    """Exact UTC instant of an RFC 3339 timestamp as (seconds since 1970, nanoseconds).

    Comparison is exact at the written precision (up to the 9 fractional digits the
    schema allows); nothing is truncated. ``None`` if the text is not a valid timestamp.
    Leap seconds (``:60``) are not valid.
    """
    match = _TIMESTAMP.match(text) if isinstance(text, str) else None
    if not match:
        return None
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    nanoseconds = int((match.group(7) or "0").ljust(9, "0"))
    try:
        if match.group(8) == "Z":
            offset = _dt.timedelta(0)
        else:
            hours, minutes = int(match.group(10)), int(match.group(11))
            if hours > 23 or minutes > 59:
                return None
            offset = _dt.timedelta(hours=hours, minutes=minutes) * (1 if match.group(9) == "+" else -1)
        moment = _dt.datetime(year, month, day, hour, minute, second, tzinfo=_dt.timezone(offset))
    except ValueError:
        return None
    return (moment - _EPOCH) // _dt.timedelta(seconds=1), nanoseconds


_NS = 1_000_000_000
_EARLIEST_OFFSET_NS = 14 * 3600 * _NS  # UTC+14:00
_LATEST_OFFSET_NS = 12 * 3600 * _NS  # UTC-12:00


def time_bounds(value) -> tuple[int, int] | None:
    """Inclusive (earliest, latest) instant in UTC nanoseconds for a time value.

    A timestamp is one instant. A day-precision value ``{"date", "precision": "day"}``
    is never expanded to a single instant: it may be any instant of that calendar date at
    any UTC offset from -12:00 to +14:00. ``None`` for markers or invalid values.
    """
    if isinstance(value, str):
        moment = instant(value)
        if moment is None:
            return None
        point = moment[0] * _NS + moment[1]
        return point, point
    if isinstance(value, Mapping) and value.get("precision") == "day" and isinstance(value.get("date"), str):
        day = _date(value["date"])
        if day is None:
            return None
        start = (_dt.datetime(day.year, day.month, day.day, tzinfo=_dt.timezone.utc) - _EPOCH) // _dt.timedelta(seconds=1)
        return start * _NS - _EARLIEST_OFFSET_NS, (start + 86400) * _NS + _LATEST_OFFSET_NS - 1
    return None


def compare_times(a, b) -> int | None:
    """-1, 0 or 1 when the order of two time values is determinate; ``None`` when it is not (U5)."""
    first, second = time_bounds(a), time_bounds(b)
    if first is None or second is None:
        return None
    if first[1] < second[0]:
        return -1
    if first[0] > second[1]:
        return 1
    if first[0] == first[1] == second[0] == second[1]:
        return 0
    return None


def as_integer(value) -> int | None:
    """An integer-typed member as ``int`` (integral floats such as 5.0 included), else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _date(text: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


def _semantic_notes(notes) -> list[Issue]:
    issues = []
    for kind, pointer, value in notes:
        if kind == "timestamp" and instant(value) is None:
            issues.append(Issue(pointer, reasons.INVALID_TIMESTAMP, "not a valid RFC 3339 date-time"))
        elif kind == "date" and _date(value) is None:
            issues.append(Issue(pointer, reasons.INVALID_DATE, "not a valid calendar date"))
        elif kind == "period":
            start, end = _date(value["start"]), _date(value["end"])
            if start and end and (start > end or (start == end and not value["inclusive"])):
                issues.append(Issue(pointer, reasons.INVALID_PERIOD, "period ends before it starts"))
    return issues


def _record_rules(body: Mapping) -> list[Issue]:
    issues = []
    predecessor, revision = body["predecessor"], body["revision"]
    if revision == 1 and predecessor is not None:
        issues.append(Issue("/predecessor", reasons.INVALID_PREDECESSOR, "revision 1 has no predecessor"))
    elif revision > 1 and (
        predecessor is None
        or predecessor["record_type"] != body["record_type"]
        or predecessor["id"] != body["id"]
        or predecessor["revision"] != revision - 1
    ):
        issues.append(Issue("/predecessor", reasons.INVALID_PREDECESSOR, "must reference the same record at revision - 1"))

    kind = body["record_type"]
    if kind == "source_assertion":
        selector = body["selector"]
        position, quote = selector["text_position"], selector["text_quote"]
        if "start" in position and position["start"] >= position["end"]:
            issues.append(Issue("/selector/text_position", reasons.INVALID_SELECTOR, "start must precede end"))
        if "exact" in quote and quote["exact"] != body["quote"]["exact"]:
            issues.append(Issue("/selector/text_quote/exact", reasons.INVALID_SELECTOR, "differs from quote.exact"))
        media = selector["media_time"]
        if "start_seconds" in media and media["start_seconds"] > media["end_seconds"]:
            issues.append(Issue("/selector/media_time", reasons.INVALID_SELECTOR, "start after end"))
    elif kind == "forecast":
        cutoff, issued = body["information_cutoff"], body["issued_at"]
        if compare_times(cutoff, issued) == 1:  # refused only when definitely later (U5)
            issues.append(Issue("/information_cutoff", reasons.INFORMATION_CUTOFF_AFTER_ISSUED_AT, "cutoff is after issuance"))
    elif kind == "question":
        if compare_times(body["resolution_deadline"], body["forecast_deadline"]) == -1:
            issues.append(Issue(
                "/resolution_deadline", reasons.RESOLUTION_DEADLINE_BEFORE_FORECAST_DEADLINE,
                "resolution deadline precedes forecast deadline",
            ))
    elif kind == "assessment":
        coverage = body["coverage"]
        checked, total = as_integer(coverage["items_checked"]), as_integer(coverage["items_total"])
        if checked is not None and total is not None:
            if checked > total or (coverage["scope"] == "full" and checked != total):
                issues.append(Issue("/coverage", reasons.INVALID_COVERAGE, "checked items inconsistent with scope/total"))
    return issues


def _refine_digests(body, issues: list[Issue]) -> list[Issue]:
    refined = []
    for issue in issues:
        if issue.code == reasons.MALFORMED_DIGEST:
            value = body
            for token in issue.pointer.split("/")[1:]:
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if isinstance(value, list) else value.get(token) if isinstance(value, dict) else None
            better = digest_issue(value, issue.pointer)
            issue = better if better is not None else issue
        refined.append(issue)
    return refined


def _unique(issues) -> list[Issue]:
    """One issue per (pointer, code), in pointer order."""
    first: dict = {}
    for issue in issues:
        first.setdefault((issue.pointer, issue.code), issue)
    return sorted(first.values())


def validate(body) -> list[Issue]:
    """Return every issue that refuses ``body`` as a comuvia 0.1 record (empty if valid)."""
    if not isinstance(body, dict):
        return [Issue("", reasons.NOT_AN_OBJECT, "a record body is a JSON object")]
    if "schema" not in body:
        return [Issue("/schema", reasons.MISSING_REQUIRED_FIELD, "required member is absent")]
    if body["schema"] != SCHEMA_VERSION:
        return [Issue("/schema", reasons.UNSUPPORTED_SCHEMA_VERSION, f"only {SCHEMA_VERSION} is supported")]
    if "record_type" not in body:
        return [Issue("/record_type", reasons.MISSING_REQUIRED_FIELD, "required member is absent")]
    if body["record_type"] not in RECORD_TYPES:
        return [Issue("/record_type", reasons.UNKNOWN_RECORD_TYPE, "not a comuvia 0.1 record type")]
    registry = load_schemas()
    schema_id = SCHEMA_ID_PREFIX + body["record_type"]
    notes: list = []
    issues = _Interpreter(registry).check(body, registry[schema_id], "", schema_id, notes)
    if issues:
        return _unique(_refine_digests(body, issues))
    issues = _semantic_notes(notes)
    if issues:
        return _unique(issues)
    return _unique(_record_rules(body))


def load_record(data: bytes | str) -> dict:
    """Parse and validate one record, raising ``RefusalError`` if it is refused."""
    body = parse_json(data)
    issues = validate(body)
    if issues:
        raise RefusalError(issues)
    return body
