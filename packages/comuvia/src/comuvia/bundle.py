"""Whole-bundle verification, embedded payload reference checks and independent expectations.

Unifies core validation, retained-byte verification, ``source_assertion`` selector checks,
packaged profile validation (``dependencies`` and ``edition_review``), embedded payload pin
audits, and comparison against an independently retained expectation manifest. Performs no
network access and never guesses filesystem paths from locators.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import reasons
from .identity import (
    DIGEST_PATTERN,
    _references,
    canonicalize,
    parse_json,
    record_digest,
    revision_conflicts,
    verify,
)
from .issues import Issue, RefusalError
from .profiles import dependencies as _deps
from .profiles import edition_review as _er
from .selectors import check_selector
from .store import MARKER, RecordStore
from .validation import validate

DIGEST_KEYS = ("sha256", "raw_sha256", "content_sha256")
LOCATOR_KEYS = ("path", "file")
STATES = ("match", "mismatch", "missing", "malformed", "ambiguous", "exempt")
_HEX = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")
_PIN_KEYS = {"record_type", "id", "revision", "digest"}


def _escape(token) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _resolve(expected_hex: str, data) -> str:
    if data is None:
        return "missing"
    return "match" if hashlib.sha256(bytes(data)).hexdigest() == expected_hex else "mismatch"


def check_embedded(
    payload,
    locate: Callable,
    *,
    digest_keys: Iterable[str] = DIGEST_KEYS,
    locator_keys: Iterable[str] = LOCATOR_KEYS,
    exempt: Mapping | None = None,
) -> dict:
    """Check every reference embedded in ``payload``, resolving locators strictly via ``locate``.

    Recognizes ``comuvia.reference_to`` pins (``locate`` receives ``(record_type, id, revision)``
    and returns canonical record bytes) and ``{path|file, sha256|raw_sha256|content_sha256}``
    objects (``locate`` receives the locator string and returns exact bytes). Objects carrying
    multiple locator keys or multiple digest keys are reported as ``ambiguous``.
    """
    d_keys = tuple(digest_keys)
    l_keys = tuple(locator_keys)
    exempt_map = dict(exempt or {})
    references: list[dict] = []

    def visit(value, pointer: str) -> None:
        if isinstance(value, Mapping):
            if set(value) == _PIN_KEYS:
                rt = value.get("record_type")
                rid = value.get("id")
                rev = value.get("revision")
                dig = value.get("digest")
                entry: dict = {
                    "pointer": pointer,
                    "kind": "pin",
                    "locator": [rt, rid, rev],
                    "digest": dig,
                }
                match = _HEX.fullmatch(dig) if isinstance(dig, str) else None
                valid_pin = (
                    isinstance(rt, str)
                    and rt != ""
                    and isinstance(rid, str)
                    and rid != ""
                    and isinstance(rev, int)
                    and not isinstance(rev, bool)
                    and rev >= 1
                    and match is not None
                    and dig.startswith("sha256:")
                )
                if not valid_pin:
                    entry["state"] = "malformed"
                else:
                    assert match is not None
                    entry["state"] = _resolve(match.group(1), locate((rt, rid, rev)))
                references.append(entry)
                return
            present_locators = [k for k in l_keys if k in value]
            present_digests = [k for k in d_keys if k in value]
            if len(present_locators) > 1 or len(present_digests) > 1:
                entry = {
                    "pointer": pointer,
                    "kind": "locator",
                    "locator": [value[k] for k in present_locators],
                    "digest_key": present_digests,
                    "digest": [value[k] for k in present_digests],
                }
                if pointer in exempt_map:
                    entry["state"], entry["reason"] = "exempt", exempt_map[pointer]
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
                entry = {
                    "pointer": pointer,
                    "kind": "locator",
                    "locator": locator,
                    "digest_key": digest_key,
                    "digest": digest,
                }
                match = _HEX.fullmatch(digest) if isinstance(digest, str) else None
                if not isinstance(locator, str) or locator == "" or match is None:
                    entry["state"] = "malformed"
                elif locator in exempt_map:
                    entry["state"], entry["reason"] = "exempt", exempt_map[locator]
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
    return {
        "references": references,
        "counts": counts,
        "ok": bool(references) and counts["match"] + counts["exempt"] == len(references),
    }


def _key(body: Mapping) -> tuple:
    return (body.get("record_type"), body.get("id"), body.get("revision"))


def _valid_record_key_tuple(body) -> tuple[str, str, int] | None:
    if not isinstance(body, Mapping):
        return None
    rt = body.get("record_type")
    rid = body.get("id")
    rev = body.get("revision")
    if (
        isinstance(rt, str)
        and rt != ""
        and isinstance(rid, str)
        and rid != ""
        and isinstance(rev, int)
        and not isinstance(rev, bool)
        and rev >= 1
    ):
        return (rt, rid, rev)
    return None


def _label(key: tuple) -> str:
    return f"{key[0]}/{key[1]}/r{key[2]}"


def expectation(records: Iterable[Mapping]) -> dict:
    """Build an independent expectation manifest of sorted record keys, digests and latest revisions."""
    bodies = list(records)
    entries_raw: list[dict] = []
    for idx, b in enumerate(bodies):
        key = _valid_record_key_tuple(b)
        if key is None:
            raise RefusalError([Issue(f"/{idx}", reasons.INVALID_TYPE, "record must carry valid (record_type, id, int revision >= 1)")])
        entries_raw.append({
            "record_type": key[0],
            "id": key[1],
            "revision": key[2],
            "digest": record_digest(b),
        })
    entries = sorted(entries_raw, key=lambda e: (e["record_type"], e["id"], e["revision"]))
    latest: dict[str, int] = {}
    for entry in entries:
        name = f"{entry['record_type']}/{entry['id']}"
        latest[name] = max(entry["revision"], latest.get(name, entry["revision"]))
    return {"entries": entries, "latest": dict(sorted(latest.items()))}


def preflight(records: Iterable[Mapping], expected: Mapping | None = None) -> dict:
    """Check duplicate/conflicting record keys and strict schema/type validity of ``expected`` before comparing."""
    digests: dict[tuple[str, str, int], list[str]] = {}
    malformed_records: list[str] = []
    for idx, body in enumerate(records):
        key = _valid_record_key_tuple(body)
        if key is None:
            malformed_records.append(f"record:{idx}")
            continue
        try:
            dig = record_digest(body)
        except RefusalError:
            malformed_records.append(f"record:{idx}")
            continue
        digests.setdefault(key, []).append(dig)

    report: dict = {
        "duplicate_keys": sorted(_label(k) for k, d in digests.items() if len(d) > 1 and len(set(d)) == 1),
        "conflicting_keys": sorted(_label(k) for k, d in digests.items() if len(set(d)) > 1),
        "expected_duplicates": [],
        "expected_latest_mismatch": [],
    }
    if malformed_records:
        report["malformed_records"] = malformed_records

    expected_malformed: list[str] = []
    if expected is not None:
        if not isinstance(expected, Mapping) or set(expected) != {"entries", "latest"}:
            expected_malformed.append("/expectation")
        else:
            entries = expected.get("entries")
            latest = expected.get("latest")
            seen: set[tuple[str, str, int]] = set()
            repeated: set[tuple[str, str, int]] = set()
            highest: dict[str, int] = {}
            if not isinstance(entries, list):
                expected_malformed.append("/entries")
            else:
                for idx, entry in enumerate(entries):
                    k = _valid_record_key_tuple(entry) if isinstance(entry, Mapping) and set(entry) == _PIN_KEYS else None
                    dig = entry.get("digest") if isinstance(entry, Mapping) else None
                    if k is None or not isinstance(dig, str) or DIGEST_PATTERN.match(dig) is None:
                        expected_malformed.append(f"/entries/{idx}")
                        continue
                    (repeated if k in seen else seen).add(k)
                    name = f"{k[0]}/{k[1]}"
                    highest[name] = max(k[2], highest.get(name, k[2]))
            report["expected_duplicates"] = sorted(_label(k) for k in repeated)

            if not isinstance(latest, Mapping):
                expected_malformed.append("/latest")
            else:
                valid_latest_keys: set[str] = set()
                for lk, lv in latest.items():
                    if (
                        not isinstance(lk, str)
                        or lk == ""
                        or "/" not in lk
                        or not isinstance(lv, int)
                        or isinstance(lv, bool)
                        or lv < 1
                    ):
                        expected_malformed.append(f"/latest/{_escape(lk)}")
                    else:
                        valid_latest_keys.add(lk)
                report["expected_latest_mismatch"] = sorted(
                    name
                    for name in (valid_latest_keys | set(highest))
                    if not (
                        name in valid_latest_keys
                        and name in highest
                        and type(latest[name]) is int
                        and latest[name] == highest[name]
                    )
                )
    if expected_malformed:
        report["expected_malformed"] = expected_malformed

    report["ok"] = not any(
        report.get(k)
        for k in (
            "malformed_records",
            "duplicate_keys",
            "conflicting_keys",
            "expected_malformed",
            "expected_duplicates",
            "expected_latest_mismatch",
        )
    )
    return report


def check_expectation(records: Iterable[Mapping], expected: Mapping) -> dict:
    """Compare ``records`` against an independently retained ``expected`` manifest."""
    bodies = list(records)
    checked = preflight(bodies, expected)
    if not checked["ok"]:
        return {
            "missing": [],
            "unexpected": [],
            "changed": [],
            "tail_removed": [],
            "preflight": checked,
            "ok": False,
        }
    current = expectation(bodies)
    have = {(e["record_type"], e["id"], e["revision"]): e["digest"] for e in current["entries"]}
    want = {(e["record_type"], e["id"], e["revision"]): e["digest"] for e in expected["entries"]}
    report: dict = {
        "missing": sorted(_label(k) for k in want if k not in have),
        "unexpected": sorted(_label(k) for k in have if k not in want),
        "changed": sorted(_label(k) for k in want if k in have and have[k] != want[k]),
        "tail_removed": sorted(
            name for name, revision in expected["latest"].items() if current["latest"].get(name, 0) < revision
        ),
    }
    report["ok"] = not any(report.values())
    report["preflight"] = checked
    return report


@dataclass(frozen=True)
class BundleReport:
    """Structured result of ``verify_bundle``."""

    records_checked: int
    contents_checked: int
    selectors_checked: int
    profiles_checked: bool
    embedded_checked: int
    expectation_checked: bool
    issues: tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _load_bundle_source(source) -> tuple[list[Mapping], list[Issue]]:
    issues: list[Issue] = []
    if isinstance(source, RecordStore):
        store_report = source.verify()
        issues.extend(store_report.issues)
        return source.records(), issues
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        if path.is_dir() and (path / MARKER).is_file():
            store = RecordStore(path)
            store_report = store.verify()
            issues.extend(store_report.issues)
            return store.records(), issues
        if path.is_file():
            raw = path.read_bytes()
            lines = raw.split(b"\n")
            if lines and lines[-1] == b"":
                lines.pop()
            bodies: list[Mapping] = []
            for idx, line in enumerate(lines):
                if line.endswith(b"\r"):
                    line = line[:-1]
                try:
                    parsed = parse_json(line)
                except RefusalError as error:
                    issues.extend(Issue(f"line:{idx + 1}{i.pointer}", i.code, i.message) for i in error.issues)
                    continue
                if not isinstance(parsed, Mapping):
                    issues.append(Issue(f"line:{idx + 1}", reasons.NOT_AN_OBJECT, "record line must be a JSON object"))
                    continue
                bodies.append(parsed)
            return bodies, issues
        raise RefusalError([Issue("", reasons.NOT_A_STORE, f"{path} is neither a comuvia store nor a JSONL file")])
    return list(source), issues


def _make_content_resolver(contents) -> Callable[[tuple], bytes | None]:
    if contents is None:
        return lambda _key: None
    if callable(contents):
        return contents
    if isinstance(contents, Mapping):
        def _lookup(key: tuple) -> bytes | None:
            if key in contents:
                return contents[key]
            text_key = _label(key)
            if text_key in contents:
                return contents[text_key]
            return None

        return _lookup
    raise TypeError("contents must be a Mapping, a callable, or None")


def verify_bundle(
    source: RecordStore | os.PathLike | str | Iterable[Mapping],
    *,
    contents: Mapping | Callable[[tuple], bytes | None] | None = None,
    require_retained_content: bool = False,
    check_selectors: bool = True,
    check_profiles: bool = True,
    check_embedded_pins: bool = False,
    locate_embedded: Callable | None = None,
    exempt_embedded: Mapping | None = None,
    expectation_manifest: Mapping | None = None,
) -> BundleReport:
    """Verify an evidence bundle offline across records, bytes, selectors, profiles and expectations."""
    bodies, issues_list = _load_bundle_source(source)
    issues: set[Issue] = set(issues_list)
    resolve_content = _make_content_resolver(contents)

    valid_bodies: list[Mapping] = []
    for pos, body in enumerate(bodies):
        if not isinstance(body, Mapping):
            issues.add(Issue(f"/{pos}", reasons.NOT_AN_OBJECT, "record must be a mapping"))
            continue
        rec_name = _label(_key(body))
        val_issues = validate(body)
        for v_issue in val_issues:
            issues.add(Issue(f"{rec_name}:{v_issue.pointer}", v_issue.code, v_issue.message))
        if not val_issues:
            valid_bodies.append(body)

    for conflict in revision_conflicts(valid_bodies):
        issues.add(conflict)

    index: dict[tuple, Mapping] = {_key(b): b for b in valid_bodies}
    verified_contents: dict[tuple, bytes] = {}
    contents_checked = 0

    for body in valid_bodies:
        key = _key(body)
        rec_name = _label(key)
        for pointer, ref in _references(body):
            target = index.get((ref["record_type"], ref["id"], ref["revision"]))
            if target is None:
                issues.add(Issue(f"{rec_name}:{pointer}", reasons.UNRESOLVED_REFERENCE, "referenced record is not in bundle"))
            elif record_digest(target) != ref["digest"]:
                issues.add(Issue(f"{rec_name}:{pointer}", reasons.REFERENCE_DIGEST_MISMATCH, "referenced target digest differs"))

        rtype = body.get("record_type")
        c_desc = body.get("content")
        needs_bytes = (
            rtype == "artifact_descriptor"
            or (rtype == "resource_snapshot" and isinstance(c_desc, Mapping) and c_desc.get("retained") is True)
        )
        if needs_bytes:
            data = resolve_content(key)
            if data is not None:
                contents_checked += 1
                v_res = verify(body, content=data)
                if v_res.content_identity != "match":
                    for c_issue in v_res.issues:
                        issues.add(Issue(f"{rec_name}:{c_issue.pointer}", c_issue.code, c_issue.message))
                else:
                    verified_contents[key] = bytes(data)
            elif require_retained_content:
                issues.add(Issue(f"{rec_name}:/content", reasons.MISSING_CONTENT, "retained bytes not supplied"))

    selectors_checked = 0
    if check_selectors:
        for body in valid_bodies:
            if body.get("record_type") != "source_assertion":
                continue
            rec_name = _label(_key(body))
            res_ref = body["resource"]
            res_key = (res_ref["record_type"], res_ref["id"], res_ref["revision"])
            res_snapshot = index.get(res_key)
            res_bytes = verified_contents.get(res_key)
            if res_bytes is None:
                raw_try = resolve_content(res_key)
                if raw_try is not None:
                    res_bytes = bytes(raw_try)
            if res_snapshot is not None and res_bytes is not None:
                sel_res = check_selector(body, res_bytes, snapshot=res_snapshot)
                if sel_res.result != "unavailable":
                    selectors_checked += 1
                if sel_res.result == "mismatch":
                    for s_issue in sel_res.issues:
                        issues.add(Issue(f"{rec_name}:{s_issue.pointer}", s_issue.code, s_issue.message))

    if check_profiles:
        for body in valid_bodies:
            rec_name = _label(_key(body))
            prof_issues, _ = _deps.verify_record_profile(body, index, require_resolved=True)
            for p_issue in prof_issues:
                issues.add(Issue(f"{rec_name}:{p_issue.pointer}", p_issue.code, p_issue.message))
            if (
                body.get("record_type") == "artifact_descriptor"
                and body.get("content_schema") == _er.REVIEW
                and _key(body) in verified_contents
            ):
                rev_report = _er.review_status(body, valid_bodies, verified_contents)
                if rev_report["state"] in ("invalid", "broken"):
                    for reason_code in rev_report["reasons"]:
                        issues.add(Issue(f"{rec_name}:/content", reasons.INVALID_PROFILE,
                                         f"edition-review/1 {rev_report['state']}: {reason_code}"))

    embedded_checked = 0
    if check_embedded_pins:
        def _lookup_pin(target):
            if isinstance(target, tuple) and len(target) == 3:
                try:
                    rec = index.get(target)
                except TypeError:
                    return None
                return canonicalize(rec) if rec is not None else None
            return None

        def _default_locate(target):
            found_pin = _lookup_pin(target)
            if found_pin is not None:
                return found_pin
            if locate_embedded is not None:
                return locate_embedded(target)
            return None

        def _combined_locate(target):
            if locate_embedded is not None:
                res = locate_embedded(target)
                if res is not None:
                    return res
            return _lookup_pin(target)

        locator_fn = _combined_locate if locate_embedded is not None else _default_locate
        for key, raw_bytes in sorted(verified_contents.items()):
            body = index[key]
            media = str((body.get("content") or {}).get("media_type", "")).lower()
            if "json" not in media and not str(body.get("content_schema", "")).endswith(("/1", "/v1")):
                continue
            try:
                payload = parse_json(raw_bytes)
            except RefusalError:
                continue
            embedded_checked += 1
            rec_name = _label(key)
            emb = check_embedded(payload, locator_fn, exempt=exempt_embedded)
            for ref_entry in emb["references"]:
                if ref_entry["state"] not in ("match", "exempt"):
                    issues.add(Issue(
                        f"{rec_name}:{ref_entry['pointer']}",
                        reasons.EMBEDDED_REFERENCE_FAILED,
                        f"embedded {ref_entry['kind']} reference is {ref_entry['state']}",
                    ))

    expectation_checked = False
    if expectation_manifest is not None:
        expectation_checked = True
        exp = check_expectation(valid_bodies, expectation_manifest)
        if not exp["ok"]:
            pf = exp["preflight"]
            for field_name in (
                "malformed_records",
                "duplicate_keys",
                "conflicting_keys",
                "expected_malformed",
                "expected_duplicates",
                "expected_latest_mismatch",
            ):
                for item in pf.get(field_name, []):
                    issues.add(Issue("expectation", reasons.EXPECTATION_FAILED, f"preflight {field_name}: {item}"))
            for field_name in ("missing", "unexpected", "changed", "tail_removed"):
                for item in exp.get(field_name, []):
                    issues.add(Issue("expectation", reasons.EXPECTATION_FAILED, f"{field_name}: {item}"))

    return BundleReport(
        records_checked=len(valid_bodies),
        contents_checked=contents_checked,
        selectors_checked=selectors_checked,
        profiles_checked=check_profiles,
        embedded_checked=embedded_checked,
        expectation_checked=expectation_checked,
        issues=tuple(sorted(issues)),
    )
