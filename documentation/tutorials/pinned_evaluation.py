"""Checking a consumer's own evaluation: references embedded in payloads, and an independent expectation.

An example helper, not part of the ``comuvia`` package. Standard library, the public ``comuvia``
0.1.0 API, and the example helpers ``record_authoring`` and ``dependency_profile`` only. No I/O:
every byte comes through a callable the caller supplies.

``check_embedded`` walks a JSON payload (for example a consumer's comparison result) and checks
every reference embedded in it:

- a ``comuvia.reference_to`` pin (``record_type``, ``id``, ``revision``, ``digest``);
- an object holding a locator key (``path`` or ``file``) and a digest key (``sha256``,
  ``raw_sha256`` or ``content_sha256``), whose digest is 64 lowercase hex digits, bare or with a
  ``sha256:`` prefix.

Locators are resolved **only** through the explicit ``locate`` callable: no file-name guessing.
For a pin, ``locate`` receives the tuple ``(record_type, id, revision)`` and returns that record's
canonical bytes (``comuvia.canonicalize(body)``), because a record digest is the SHA-256 of those
bytes. For a locator, it receives the locator string and returns the exact bytes. Each reference is
``match``, ``mismatch``, ``missing``, ``malformed``, ``ambiguous`` or ``exempt`` (with the caller's
reason). An object with more than one locator key or more than one digest key is ``ambiguous``,
whatever its values, and is never resolved by key order.

``preflight`` reports duplicate and conflicting record keys, and an inconsistent expected manifest.
``expectation`` and ``check_expectation`` compare a bundle with a list of expected records kept
elsewhere; ``check_expectation`` runs ``preflight`` first and compares nothing if it fails. They report
what is ``missing``, ``unexpected`` or ``changed``, and ids whose correction tail was removed
(``tail_removed``). An expectation detects deletion only if it is retained independently of the
bundle it checks.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping

import comuvia

DIGEST_KEYS = ("sha256", "raw_sha256", "content_sha256")
LOCATOR_KEYS = ("path", "file")
STATES = ("match", "mismatch", "missing", "malformed", "ambiguous", "exempt")
_HEX = re.compile(r"(?:sha256:)?([0-9a-f]{64})")
_PIN_KEYS = {"record_type", "id", "revision", "digest"}


def _escape(token) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _resolve(expected_hex: str, data) -> str:
    if data is None:
        return "missing"
    return "match" if hashlib.sha256(bytes(data)).hexdigest() == expected_hex else "mismatch"


def check_embedded(payload, locate: Callable, *, digest_keys: Iterable[str] = DIGEST_KEYS,
                   locator_keys: Iterable[str] = LOCATOR_KEYS, exempt: Mapping | None = None) -> dict:
    """Every reference embedded in ``payload``, each with a state. ``exempt`` maps a locator to a reason."""
    digest_keys, locator_keys, exempt = tuple(digest_keys), tuple(locator_keys), dict(exempt or {})
    references = []

    def visit(value, pointer):
        if isinstance(value, Mapping):
            if set(value) == _PIN_KEYS:
                entry = {"pointer": pointer, "kind": "pin",
                         "locator": [value.get("record_type"), value.get("id"), value.get("revision")],
                         "digest": value.get("digest")}
                match = _HEX.fullmatch(value["digest"]) if isinstance(value.get("digest"), str) else None
                if match is None or not value["digest"].startswith("sha256:"):
                    entry["state"] = "malformed"
                else:
                    entry["state"] = _resolve(match.group(1), locate((value["record_type"], value["id"], value["revision"])))
                references.append(entry)
                return
            present_locators = [k for k in locator_keys if k in value]
            present_digests = [k for k in digest_keys if k in value]
            if len(present_locators) > 1 or len(present_digests) > 1:
                # Never resolved by key order: the object is reported, whatever its values.
                entry = {"pointer": pointer, "kind": "locator", "locator": [value[k] for k in present_locators],
                         "digest_key": present_digests, "digest": [value[k] for k in present_digests]}
                if pointer in exempt:
                    entry["state"], entry["reason"] = "exempt", exempt[pointer]
                else:
                    entry["state"] = "ambiguous"
                references.append(entry)
                for key, item in value.items():
                    visit(item, f"{pointer}/{_escape(key)}")
                return
            locator_key = present_locators[0] if present_locators else None
            digest_key = present_digests[0] if present_digests else None
            if locator_key is not None and digest_key is not None:
                locator, digest = value[locator_key], value[digest_key]
                entry = {"pointer": pointer, "kind": "locator", "locator": locator, "digest_key": digest_key, "digest": digest}
                match = _HEX.fullmatch(digest) if isinstance(digest, str) else None
                if not isinstance(locator, str) or locator == "" or match is None:
                    entry["state"] = "malformed"
                elif locator in exempt:
                    entry["state"], entry["reason"] = "exempt", exempt[locator]
                else:
                    entry["state"] = _resolve(match.group(1), locate(locator))
                references.append(entry)
            for key, item in value.items():
                visit(item, f"{pointer}/{_escape(key)}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{pointer}/{index}")

    visit(payload, "")
    counts = {state: sum(1 for r in references if r["state"] == state) for state in STATES}
    return {"references": references, "counts": counts,
            "ok": bool(references) and counts["match"] + counts["exempt"] == len(references)}


def _key(body: Mapping) -> tuple:
    return (body.get("record_type"), body.get("id"), body.get("revision"))


def expectation(records: Iterable[Mapping]) -> dict:
    """The sorted record keys and digests, and the latest revision of each id. Retain it elsewhere."""
    entries = sorted(({"record_type": b["record_type"], "id": b["id"], "revision": b["revision"],
                       "digest": comuvia.record_digest(b)} for b in records),
                     key=lambda e: (e["record_type"], e["id"], e["revision"]))
    latest = {}
    for e in entries:
        name = f"{e['record_type']}/{e['id']}"
        latest[name] = max(e["revision"], latest.get(name, e["revision"]))
    return {"entries": entries, "latest": dict(sorted(latest.items()))}


def preflight(records: Iterable[Mapping], expected: Mapping | None = None) -> dict:
    """Duplicate and conflicting record keys, and an inconsistent expected manifest, before any comparison.

    ``duplicate_keys``: a key appears more than once with the same digest; ``conflicting_keys``: the
    same key with different digests. With ``expected``: ``expected_duplicates`` (a key repeated in its
    entries) and ``expected_latest_mismatch`` (``latest`` differs from the highest revision in its own
    entries). Each is a sorted list; ``ok`` when all are empty.
    """
    label = lambda k: f"{k[0]}/{k[1]}/r{k[2]}"  # noqa: E731
    digests: dict = {}
    for body in records:
        digests.setdefault(_key(body), []).append(comuvia.record_digest(body))
    report = {
        "duplicate_keys": sorted(label(k) for k, d in digests.items() if len(d) > 1 and len(set(d)) == 1),
        "conflicting_keys": sorted(label(k) for k, d in digests.items() if len(set(d)) > 1),
        "expected_duplicates": [], "expected_latest_mismatch": [],
    }
    if expected is not None:
        seen, repeated, highest = set(), set(), {}
        for e in expected.get("entries", []):
            k = (e.get("record_type"), e.get("id"), e.get("revision"))
            (repeated if k in seen else seen).add(k)
            name = f"{k[0]}/{k[1]}"
            if isinstance(k[2], int):
                highest[name] = max(k[2], highest.get(name, k[2]))
        report["expected_duplicates"] = sorted(label(k) for k in repeated)
        latest = expected.get("latest", {})
        report["expected_latest_mismatch"] = sorted(name for name in set(latest) | set(highest)
                                                    if latest.get(name) != highest.get(name))
    report["ok"] = not any(report[k] for k in ("duplicate_keys", "conflicting_keys", "expected_duplicates", "expected_latest_mismatch"))
    return report


def check_expectation(records: Iterable[Mapping], expected: Mapping) -> dict:
    """``missing``, ``unexpected``, ``changed`` and ``tail_removed``, each a sorted list; ``ok`` when all are empty.

    ``preflight`` runs first; if it fails, its findings are returned under ``preflight`` with ``ok``
    false, and nothing else is compared.
    """
    records = list(records)
    checked = preflight(records, expected)
    if not checked["ok"]:
        return {"missing": [], "unexpected": [], "changed": [], "tail_removed": [], "preflight": checked, "ok": False}
    current = expectation(records)
    have = {(e["record_type"], e["id"], e["revision"]): e["digest"] for e in current["entries"]}
    want = {(e["record_type"], e["id"], e["revision"]): e["digest"] for e in expected["entries"]}
    label = lambda k: f"{k[0]}/{k[1]}/r{k[2]}"  # noqa: E731
    report = {
        "missing": sorted(label(k) for k in want if k not in have),
        "unexpected": sorted(label(k) for k in have if k not in want),
        "changed": sorted(label(k) for k in want if k in have and have[k] != want[k]),
        "tail_removed": sorted(name for name, revision in expected["latest"].items()
                               if current["latest"].get(name, 0) < revision),
    }
    report["ok"] = not any(report.values())
    report["preflight"] = checked
    return report
