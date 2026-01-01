"""Strict JSON parsing, RFC 8785 canonicalization, digests and identity verification.

Four identities stay distinct:

- the *content digest* is SHA-256 over exact retained bytes, always paired with a byte length;
- the *record digest* is SHA-256 over the RFC 8785 (JCS) canonical form of the whole record body;
- the *logical id + revision* is a stable name, not a digest;
- a *legacy/locator identity* (``{"scheme", "value"}``) is never a digest.

A digest proves byte or record identity only. It says nothing about truth, authorship,
publication or time: timestamp assurance is always ``unavailable`` and there is no signature.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from . import reasons
from .issues import Issue, RefusalError, pointer_join

MAX_SAFE_INTEGER = 2**53 - 1
# Deepest container nesting accepted by parse_json and canonicalize (a top-level object is depth 1).
MAX_DEPTH = 64
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_STRUCTURAL = re.compile(r'[\[\]{}"\\]')
_ALGORITHM_PREFIX = re.compile(r"([A-Za-z0-9][A-Za-z0-9._+-]*):")
_REFERENCE_KEYS = frozenset({"record_type", "id", "revision", "digest"})


class _ParseRefusal(Exception):
    def __init__(self, code: str, message: str):
        self.issue = Issue("", code, message)


# ------------------------------------------------------------------ strict parsing


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise _ParseRefusal(reasons.DUPLICATE_MEMBER, f"duplicate member {key!r}")
        result[key] = value
    return result


def _constant(token: str):
    raise _ParseRefusal(reasons.NON_FINITE_NUMBER, f"{token} is not a JSON number")


def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _ParseRefusal(reasons.NUMBER_OUT_OF_RANGE, f"{text} overflows binary64")
    return value


def _integer_issue(value: int) -> str | None:
    """Why an integer cannot be a JSON number without losing meaning, or ``None``.

    Accepted: magnitudes up to 2^53 - 1; larger integers that binary64 represents exactly;
    and larger integers written exactly as the RFC 8785 text of the binary64 value they
    denote (the canonical form of, for example, 2.0**60 is 1152921504606847000), so that
    canonical output always parses back. Anything else would silently change the number.
    """
    if abs(value) <= MAX_SAFE_INTEGER:
        return None
    try:
        as_float = float(value)
    except OverflowError:
        return "integer overflows binary64"
    if as_float == value or _number(as_float) == str(value):
        return None
    return "integer is not exactly representable in binary64"


def _int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as error:  # exceeds the interpreter's integer-string limit
        raise _ParseRefusal(reasons.INTEGER_OUT_OF_RANGE, "integer too long") from error
    problem = _integer_issue(value)
    if problem:
        raise _ParseRefusal(reasons.INTEGER_OUT_OF_RANGE, f"{text}: {problem}")
    return value


def _nesting_exceeds(text: str, limit: int) -> bool:
    """True if arrays/objects nest deeper than ``limit`` (strings are skipped)."""
    depth, in_string, skip = 0, False, -1
    for match in _STRUCTURAL.finditer(text):
        index = match.start()
        if index < skip:
            continue
        char = text[index]
        if in_string:
            if char == "\\":
                skip = index + 2
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return True
        elif char in "]}":
            depth -= 1
    return False


def _lone_surrogates(value, pointer: str = "") -> list[Issue]:
    found = []
    if isinstance(value, str):
        if any("\ud800" <= ch <= "\udfff" for ch in value):
            found.append(Issue(pointer, reasons.LONE_SURROGATE, "string holds an unpaired surrogate"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if any("\ud800" <= ch <= "\udfff" for ch in key):
                found.append(Issue(pointer, reasons.LONE_SURROGATE, "member name holds an unpaired surrogate"))
            found.extend(_lone_surrogates(item, pointer_join(pointer, key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_lone_surrogates(item, pointer_join(pointer, index)))
    return found


def parse_json(data: bytes | str):
    """Parse JSON text, refusing input that has no single canonical meaning.

    Refused (``RefusalError``): a leading BOM, invalid UTF-8, malformed JSON, duplicate
    member names at any depth, ``NaN``/``Infinity``, numbers that overflow binary64,
    integer literals that binary64 would silently change (see ``_integer_issue``),
    unpaired surrogates, and nesting deeper than ``MAX_DEPTH``. Exact decimals and
    large integers belong in strings.
    """
    if isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data)
        if data.startswith(b"\xef\xbb\xbf"):
            raise RefusalError([Issue("", reasons.BYTE_ORDER_MARK, "leading UTF-8 byte order mark")])
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RefusalError([Issue("", reasons.INVALID_UTF8, str(error))]) from None
    else:
        text = data
        if text.startswith("\ufeff"):
            raise RefusalError([Issue("", reasons.BYTE_ORDER_MARK, "leading byte order mark")])
    if _nesting_exceeds(text, MAX_DEPTH):
        raise RefusalError([Issue("", reasons.NESTING_TOO_DEEP, f"nesting deeper than {MAX_DEPTH}")])
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
            parse_int=_int,
        )
    except _ParseRefusal as refusal:
        raise RefusalError([refusal.issue]) from None
    except json.JSONDecodeError as error:
        raise RefusalError([Issue("", reasons.INVALID_JSON, str(error))]) from None
    surrogates = _lone_surrogates(value)
    if surrogates:
        raise RefusalError(surrogates)
    return value


# ------------------------------------------------------------------ RFC 8785 canonicalization

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
for _code in range(0x20):
    _ESCAPES.setdefault(chr(_code), f"\\u{_code:04x}")
_STRING_TABLE = str.maketrans(_ESCAPES)


def _number(value: float) -> str:
    """ECMAScript Number::toString for a finite binary64 value (RFC 8785 section 3.2.2.3)."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exponent = repr(abs(value)).partition("e")
    integer_part, _, fraction = mantissa.partition(".")
    digits = integer_part + fraction.rstrip("0") if fraction != "0" else integer_part
    leading = len(digits) - len(digits.lstrip("0"))
    n = len(integer_part) + (int(exponent) if exponent else 0) - leading
    s = digits[leading:].rstrip("0")
    k = len(s)
    if k <= n <= 21:
        text = s + "0" * (n - k)
    elif 0 < n <= 21:
        text = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + s
    else:
        e = n - 1
        text = (s if k == 1 else s[0] + "." + s[1:]) + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + text


def _encode(value, out: list[str], pointer: str, depth: int = 0) -> None:
    if isinstance(value, (list, tuple, Mapping)):
        depth += 1
        if depth > MAX_DEPTH:
            raise RefusalError([Issue(pointer, reasons.NESTING_TOO_DEEP, f"nesting deeper than {MAX_DEPTH}")])
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        problem = _integer_issue(value)
        if problem:
            raise RefusalError([Issue(pointer, reasons.INTEGER_OUT_OF_RANGE, problem)])
        # Above 2^53 - 1 the binary64 Number form applies (10**21 -> "1e+21").
        out.append(str(value) if abs(value) <= MAX_SAFE_INTEGER else _number(float(value)))
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise RefusalError([Issue(pointer, reasons.NON_FINITE_NUMBER, "non-finite number")])
        out.append(_number(value))
    elif isinstance(value, str):
        if any("\ud800" <= ch <= "\udfff" for ch in value):
            raise RefusalError([Issue(pointer, reasons.LONE_SURROGATE, "unpaired surrogate")])
        out.append('"' + value.translate(_STRING_TABLE) + '"')
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _encode(item, out, pointer_join(pointer, index), depth)
        out.append("]")
    elif isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"member name {key!r} at '{pointer}' is not a string")
        out.append("{")
        for index, key in enumerate(sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))):
            if index:
                out.append(",")
            _encode(key, out, pointer)
            out.append(":")
            _encode(value[key], out, pointer_join(pointer, key), depth)
        out.append("}")
    else:
        raise TypeError(f"{type(value).__name__} at '{pointer}' is not a JSON value")


def canonicalize(value) -> bytes:
    """Return the RFC 8785 (JCS) canonical UTF-8 bytes of a JSON value."""
    out: list[str] = []
    _encode(value, out, "")
    return "".join(out).encode("utf-8")


# ------------------------------------------------------------------ digests


def content_digest(data: bytes) -> str:
    """SHA-256 of exact bytes, with no decoding or normalization."""
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


def record_digest(body: Mapping) -> str:
    """SHA-256 of the canonical record body. No member is excluded."""
    if not isinstance(body, Mapping):
        raise TypeError("a record body is a JSON object")
    return "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()


def digest_issue(value, pointer: str = "") -> Issue | None:
    """Return an issue if ``value`` is not a supported digest text, else ``None``."""
    if isinstance(value, str) and DIGEST_PATTERN.match(value):
        return None
    if isinstance(value, str):
        prefix = _ALGORITHM_PREFIX.match(value)
        if prefix and prefix.group(1).lower() != "sha256":
            return Issue(pointer, reasons.UNSUPPORTED_DIGEST_ALGORITHM, f"algorithm {prefix.group(1)!r} is not supported")
    return Issue(pointer, reasons.MALFORMED_DIGEST, "expected 'sha256:' and 64 lowercase hex digits")


def reference_to(body: Mapping) -> dict:
    """A reference to ``body``: record type, logical id, revision and record digest."""
    return {
        "record_type": body["record_type"],
        "id": body["id"],
        "revision": body["revision"],
        "digest": record_digest(body),
    }


def is_marker(value) -> bool:
    """True for an ``{"unknown": ...}`` or ``{"withheld": ...}`` state marker."""
    return isinstance(value, Mapping) and ("unknown" in value) != ("withheld" in value) and set(value) <= {
        "unknown", "withheld", "note",
    }


# ------------------------------------------------------------------ verification


@dataclass(frozen=True)
class ReferenceCheck:
    pointer: str
    record_type: str
    id: str
    revision: int
    result: str  # "match" | "mismatch" | "unresolved"


@dataclass(frozen=True)
class Verification:
    """Separate identity results; there is deliberately no overall "verified" flag."""

    record_digest: str
    record_identity: str  # "match" | "mismatch" | "not_checked"
    content_identity: str  # "match" | "mismatch" | "unavailable" | "not_applicable"
    references: tuple[ReferenceCheck, ...]
    issues: tuple[Issue, ...]
    timestamp_assurance: str = "unavailable"
    signature: str = "none"


def _references(value, pointer: str = ""):
    if isinstance(value, Mapping):
        if set(value) == _REFERENCE_KEYS:
            yield pointer, value
            return
        for key, item in value.items():
            if pointer == "" and key == "extensions":
                continue
            yield from _references(item, pointer_join(pointer, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _references(item, pointer_join(pointer, index))


def _is_number(value) -> bool:
    """A JSON number (integral floats such as 530.0 included), never a boolean."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _content_identity(body: Mapping, content: bytes | None) -> tuple[str, list[Issue]]:
    descriptor = body.get("content")
    if body.get("record_type") not in ("resource_snapshot", "artifact_descriptor") or not isinstance(descriptor, Mapping):
        return "not_applicable", []
    digest, length = descriptor.get("digest"), descriptor.get("byte_length")
    if descriptor.get("retained") is False or not isinstance(digest, str) or content is None:
        return "unavailable", []
    if digest_issue(digest) is not None:
        return "mismatch", [digest_issue(digest, "/content/digest")]
    if content_digest(content) != digest or (_is_number(length) and length != len(content)):
        return "mismatch", [Issue("/content/digest", reasons.CONTENT_DIGEST_MISMATCH, "retained bytes differ")]
    return "match", []


def verify(
    body: Mapping,
    *,
    expected_digest: str | None = None,
    content: bytes | None = None,
    records: Iterable[Mapping] = (),
) -> Verification:
    """Check a record's identities.

    ``expected_digest`` is the record digest it should have; ``content`` holds the retained
    bytes for a snapshot or artifact descriptor; ``records`` are candidate targets for
    the body's references. Nothing is fetched: a locator is never dereferenced.
    """
    issues: list[Issue] = []
    digest = record_digest(body)
    if expected_digest is None:
        record_identity = "not_checked"
    elif expected_digest == digest:
        record_identity = "match"
    else:
        record_identity = "mismatch"
        issues.append(Issue("", reasons.RECORD_DIGEST_MISMATCH, "canonical body digest differs"))

    content_identity, content_issues = _content_identity(body, content)
    issues.extend(content_issues)

    index = {(r.get("record_type"), r.get("id"), r.get("revision")): r for r in records}
    checks = []
    for pointer, ref in _references(body):
        target = index.get((ref["record_type"], ref["id"], ref["revision"]))
        if target is None:
            result = "unresolved"
        elif record_digest(target) == ref["digest"]:
            result = "match"
        else:
            result = "mismatch"
            issues.append(Issue(pointer, reasons.REFERENCE_DIGEST_MISMATCH, "referenced body has a different digest"))
        checks.append(ReferenceCheck(pointer, ref["record_type"], ref["id"], ref["revision"], result))
    return Verification(digest, record_identity, content_identity, tuple(checks), tuple(sorted(issues)))


def revision_conflicts(bodies: Iterable[Mapping]) -> list[Issue]:
    """Report every (record type, id, revision) that names more than one distinct body."""
    seen: dict[tuple, set[str]] = {}
    for body in bodies:
        key = (body.get("record_type"), body.get("id"), body.get("revision"))
        seen.setdefault(key, set()).add(record_digest(body))
    return [
        Issue("", reasons.REVISION_CONFLICT, f"{key[0]} {key[1]!r} revision {key[2]} has {len(digests)} bodies")
        for key, digests in sorted(seen.items(), key=lambda item: str(item[0]))
        if len(digests) > 1
    ]
