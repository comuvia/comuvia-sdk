"""Declared dependencies and correction impact: ``org.comuvia.dependencies/v1`` and ``v2``.

Uses only the ``comuvia/0.1`` schemas and the Python standard library; performs no I/O.

- ``v1`` (``org.comuvia.dependencies/v1``): ``value_origin``, ``meaning``, ``coverage`` and
  ``depends_on`` edges whose ``selection`` is a non-empty string or ``0.1`` marker.
- ``v2`` (``org.comuvia.dependencies/v2``): identical envelope, plus structured ``selection``
  descriptors (``json_pointer``, ``text_quote``, ``byte_range``, ``line_range``) so
  ``impact(..., contents=...)`` can report ``selection_status`` (``"unchanged"``,
  ``"changed"`` or ``"unscoped"``) on affected dependents when a container is revised.

A declared dependency does not prove causation, completeness or correctness, and a digest
proves byte and record identity, not truth.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .. import reasons
from ..identity import (
    DIGEST_PATTERN,
    ReferenceCheck,
    canonicalize,
    is_marker,
    parse_json,
    record_digest,
    revision_conflicts,
    verify,
)
from ..issues import Issue
from ..validation import validate

NAMESPACE = "org.comuvia.dependencies/v1"
NAMESPACE_V2 = "org.comuvia.dependencies/v2"
SUPPORTED_NAMESPACES = (NAMESPACE, NAMESPACE_V2)
_PROFILE_KEY = re.compile(r"^org\.comuvia\.dependencies/v([0-9]+)\Z")
_BAD_TILDE_ESCAPE = re.compile(r"~(?![01])")
_ARRAY_INDEX = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_PROFILE_FIELDS = {"value_origin", "meaning", "coverage", "depends_on"}
_MEANING_FIELDS = {"measure", "unit", "period", "geography"}
_EDGE_FIELDS = {"role", "pin", "selection"}
_REFERENCE_FIELDS = {"record_type", "id", "revision", "digest"}
VALUE_ORIGINS = ("observed", "derived", "synthetic", "none")
COVERAGES = ("complete", "partial", "unknown")
ROLES = ("data_input", "method", "assumption")
PROFILED_TYPES = ("resource_snapshot", "artifact_descriptor")
SELECTION_KINDS = ("json_pointer", "text_quote", "byte_range", "line_range")
MAX_RECORDS = 10_000
MAX_EDGES = 64
LIMITATIONS = (
    "A declared dependency does not prove causation, completeness or correctness.",
    "Digests prove byte and record identity, not truth.",
    "No independent time evidence: declared times are as recorded.",
    "Coverage is the producer's statement; omitted inputs cannot be detected.",
)


def _pointer_for(namespace: str) -> str:
    return "/extensions/" + namespace.replace("~", "~0").replace("/", "~1")


class DependencyRefusal(ValueError):
    """A refused request. ``code`` names the refusal; no partial report is returned."""

    code = "dependency_refusal"

    def __init__(self, message: str):
        super().__init__(f"{self.code}: {message}")


class DependencyCycle(DependencyRefusal):
    code = "dependency_cycle"


class ChangeNotSuccessor(DependencyRefusal):
    code = "change_not_successor"


@dataclass(frozen=True, order=True)
class BundleIssue:
    """One named problem in a bundle: the record (``type/id/rN``), a JSON Pointer within it, a code."""

    record: str
    pointer: str
    code: str


def key_of(body: Mapping) -> tuple:
    return (body.get("record_type"), body.get("id"), body.get("revision"))


def label(key: tuple) -> str:
    return f"{key[0]}/{key[1]}/r{key[2]}"


def _ref(key: tuple) -> dict:
    return {"record_type": key[0], "id": key[1], "revision": key[2]}


def profile_namespace(body: Mapping) -> str | None:
    """Return the active supported namespace on ``body``, or ``None``."""
    extensions = body.get("extensions")
    if not isinstance(extensions, Mapping):
        return None
    present = [ns for ns in SUPPORTED_NAMESPACES if ns in extensions]
    return present[0] if len(present) == 1 else (present[0] if present else None)


def profile_of(body: Mapping):
    """The v1 or v2 profile object, or ``None`` when the record is not profiled."""
    extensions = body.get("extensions")
    if isinstance(extensions, Mapping):
        for ns in SUPPORTED_NAMESPACES:
            if ns in extensions:
                return extensions[ns]
    return None


def _is_text_or_marker(value) -> bool:
    return (isinstance(value, str) and value != "") or is_marker(value)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_reference(value) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _REFERENCE_FIELDS
        and isinstance(value["record_type"], str)
        and isinstance(value["id"], str)
        and _is_int(value["revision"])
        and isinstance(value["digest"], str)
        and DIGEST_PATTERN.match(value["digest"]) is not None
    )


def _is_structured_selection(value) -> bool:
    if not isinstance(value, Mapping) or is_marker(value):
        return False
    kind = value.get("kind")
    if kind == "json_pointer":
        ptr = value.get("pointer")
        return (
            set(value) == {"kind", "pointer"}
            and isinstance(ptr, str)
            and (ptr == "" or ptr.startswith("/"))
            and _BAD_TILDE_ESCAPE.search(ptr) is None
        )
    if kind == "text_quote":
        return (
            set(value) == {"kind", "exact", "prefix", "suffix"}
            and isinstance(value.get("exact"), str)
            and value["exact"] != ""
            and isinstance(value.get("prefix"), str)
            and isinstance(value.get("suffix"), str)
        )
    if kind == "byte_range":
        start, end = value.get("start"), value.get("end")
        return set(value) == {"kind", "start", "end"} and _is_int(start) and _is_int(end) and 0 <= start < end
    if kind == "line_range":
        start, end = value.get("start"), value.get("end")
        return set(value) == {"kind", "start", "end"} and _is_int(start) and _is_int(end) and 1 <= start <= end
    return False


def _valid_selection(value, namespace: str) -> bool:
    if _is_text_or_marker(value):
        return True
    if namespace == NAMESPACE_V2 and _is_structured_selection(value):
        return True
    return False


def _profile_issues(body: Mapping) -> list[tuple[str, str]]:
    """(pointer, code) problems in the shape of a record's dependency profile."""
    found: list[tuple[str, str]] = []
    extensions = body.get("extensions")
    supported_present: list[str] = []
    if isinstance(extensions, Mapping):
        for name in sorted(extensions):
            match = _PROFILE_KEY.match(name)
            if match:
                if name in SUPPORTED_NAMESPACES:
                    supported_present.append(name)
                else:
                    found.append((_pointer_for(name), reasons.UNSUPPORTED_PROFILE_VERSION))
    if len(supported_present) > 1:
        for name in supported_present:
            found.append((_pointer_for(name), reasons.INVALID_PROFILE))
        return found
    if not supported_present:
        return found

    ns = supported_present[0]
    ptr = _pointer_for(ns)
    profile = extensions[ns]
    if body.get("record_type") not in PROFILED_TYPES or not isinstance(profile, Mapping) or set(profile) != _PROFILE_FIELDS:
        return found + [(ptr, reasons.INVALID_PROFILE)]
    if profile["value_origin"] not in VALUE_ORIGINS:
        found.append((ptr + "/value_origin", reasons.INVALID_PROFILE))
    meaning = profile["meaning"]
    if not isinstance(meaning, Mapping) or set(meaning) != _MEANING_FIELDS:
        found.append((ptr + "/meaning", reasons.INVALID_PROFILE))
    else:
        for name in sorted(_MEANING_FIELDS):
            if not _is_text_or_marker(meaning[name]):
                found.append((f"{ptr}/meaning/{name}", reasons.INVALID_PROFILE))
    if profile["coverage"] not in COVERAGES:
        found.append((ptr + "/coverage", reasons.INVALID_PROFILE))
    edges = profile["depends_on"]
    if not isinstance(edges, list):
        return found + [(ptr + "/depends_on", reasons.INVALID_PROFILE)]
    if len(edges) > MAX_EDGES:
        found.append((ptr + "/depends_on", reasons.LIMIT_EXCEEDED))
    seen = set()
    for index, edge in enumerate(edges):
        at = f"{ptr}/depends_on/{index}"
        if not isinstance(edge, Mapping) or set(edge) != _EDGE_FIELDS:
            found.append((at, reasons.INVALID_PROFILE))
            continue
        if not isinstance(edge["role"], str):
            found.append((at + "/role", reasons.INVALID_PROFILE))
        elif edge["role"] not in ROLES:
            found.append((at + "/role", reasons.UNSUPPORTED_ROLE))
        pin = edge["pin"]
        if _is_reference(pin):
            identity = (pin["record_type"], pin["id"], pin["revision"], pin["digest"])
            if identity in seen:
                found.append((at + "/pin", reasons.DUPLICATE_PIN))
            seen.add(identity)
        elif not is_marker(pin):
            found.append((at + "/pin", reasons.INVALID_PROFILE))
        if not _valid_selection(edge["selection"], ns):
            found.append((at + "/selection", reasons.INVALID_PROFILE))
    data_inputs = sum(1 for e in edges if isinstance(e, Mapping) and e.get("role") == "data_input")
    if profile["value_origin"] == "observed" and data_inputs:
        found.append((ptr + "/value_origin", reasons.OBSERVED_HAS_INPUTS))
    if profile["value_origin"] == "derived" and not data_inputs:
        found.append((ptr + "/value_origin", reasons.DERIVED_WITHOUT_INPUTS))
    if body.get("data_origin") == "observed" and profile["value_origin"] == "synthetic":
        found.append((ptr + "/value_origin", reasons.ORIGIN_CONFLICT))
    units = body.get("units")
    if (
        body.get("record_type") == "artifact_descriptor"
        and isinstance(units, list)
        and isinstance(meaning, Mapping)
        and isinstance(meaning.get("unit"), str)
        and meaning["unit"] not in units
    ):
        found.append((ptr + "/meaning/unit", reasons.UNIT_CONFLICT))
    return found


def _valid_profile(body: Mapping) -> bool:
    """True when the record has a single supported dependency profile without shape errors."""
    extensions = body.get("extensions")
    if not isinstance(extensions, Mapping):
        return False
    supported = [ns for ns in SUPPORTED_NAMESPACES if ns in extensions]
    if len(supported) != 1:
        return False
    return not [code for _, code in _profile_issues(body) if code != reasons.UNSUPPORTED_PROFILE_VERSION]


def verify_record_profile(
    body: Mapping,
    index: Mapping[tuple, Mapping],
    *,
    require_resolved: bool = False,
) -> tuple[list[Issue], list[ReferenceCheck]]:
    """Check ``body``'s dependency profile shape and pins against ``index``.

    When ``require_resolved`` is ``False`` (single-record ``verify``), unresolved pins are
    reported in ``ReferenceCheck`` with ``result="unresolved"`` without adding ``missing_pin``;
    when ``True`` (store append / store verify), unresolved pins also emit ``missing_pin``.
    """
    issues = [Issue(ptr, code, f"dependency profile error ({code})") for ptr, code in _profile_issues(body)]
    checks: list[ReferenceCheck] = []
    ns = profile_namespace(body)
    prof = profile_of(body)
    if ns is not None and isinstance(prof, Mapping) and isinstance(prof.get("depends_on"), list):
        base = _pointer_for(ns)
        for pos, edge in enumerate(prof["depends_on"]):
            if not isinstance(edge, Mapping) or not _is_reference(edge.get("pin")):
                continue
            pin = edge["pin"]
            at = f"{base}/depends_on/{pos}/pin"
            target = index.get((pin["record_type"], pin["id"], pin["revision"]))
            if target is None:
                result = "unresolved"
                if require_resolved:
                    issues.append(Issue(at, reasons.MISSING_PIN, "pinned target is not in the store"))
            else:
                target_digest = target if isinstance(target, str) else record_digest(target)
                if target_digest == pin["digest"]:
                    result = "match"
                else:
                    result = "mismatch"
                    issues.append(Issue(at, reasons.PIN_MISMATCH, "pinned target has a different digest"))
            checks.append(ReferenceCheck(at, pin["record_type"], pin["id"], pin["revision"], result))
    return issues, checks


def _index(records: Iterable[Mapping]) -> tuple[list[Mapping], dict]:
    bodies = sorted(records, key=lambda b: (str(b.get("record_type")), str(b.get("id")), b.get("revision") or 0))
    return bodies, {key_of(b): b for b in bodies}


def _edges(body: Mapping, index: dict) -> list[dict]:
    """Every declared edge of a validly profiled record, with its resolution state."""
    resolved = []
    for edge in profile_of(body)["depends_on"]:
        pin = edge["pin"]
        if is_marker(pin):
            kind = "withheld" if "withheld" in pin else "unknown"
            resolved.append({
                "role": edge["role"],
                "target": dict(pin),
                "state": "marker",
                "marker": kind,
                "selection": edge["selection"],
            })
            continue
        target_key = (pin["record_type"], pin["id"], pin["revision"])
        target = index.get(target_key)
        if target is None:
            state = "missing"
        elif record_digest(target) == pin["digest"]:
            state = "match"
        else:
            state = "mismatch"
        resolved.append({
            "role": edge["role"],
            "target": _ref(target_key),
            "state": state,
            "key": target_key,
            "selection": edge["selection"],
        })
    return resolved


def check_bundle(records: Iterable[Mapping], contents: Mapping | None = None) -> list[BundleIssue]:
    """Every core and profile problem in a bundle of records, sorted."""
    bodies, index = _index(records)
    issues: set[BundleIssue] = set()
    if len(bodies) > MAX_RECORDS:
        issues.add(BundleIssue("", "", reasons.LIMIT_EXCEEDED))
    for body in bodies:
        name = label(key_of(body))
        for issue in validate(body):
            issues.add(BundleIssue(name, issue.pointer, issue.code))
        for pointer, code in _profile_issues(body):
            issues.add(BundleIssue(name, pointer, code))
        ns = profile_namespace(body)
        prof = profile_of(body)
        if ns is not None and isinstance(prof, Mapping) and isinstance(prof.get("depends_on"), list):
            base = _pointer_for(ns)
            for position, edge in enumerate(prof["depends_on"]):
                if not isinstance(edge, Mapping) or not _is_reference(edge.get("pin")):
                    continue
                pin = edge["pin"]
                target = index.get((pin["record_type"], pin["id"], pin["revision"]))
                at = f"{base}/depends_on/{position}/pin"
                if target is None:
                    issues.add(BundleIssue(name, at, reasons.MISSING_PIN))
                elif record_digest(target) != pin["digest"]:
                    issues.add(BundleIssue(name, at, reasons.PIN_MISMATCH))
    for issue in revision_conflicts(bodies):
        issues.add(BundleIssue("", issue.pointer, issue.code))
    for key, data in sorted((contents or {}).items()):
        body = index.get(tuple(key))
        if body is not None and verify(body, content=data).content_identity == "mismatch":
            issues.add(BundleIssue(label(tuple(key)), "/content/digest", reasons.CONTENT_DIGEST_MISMATCH))
    return sorted(issues)


def _find_cycle(graph: dict) -> list | None:
    """Iterative depth-first cycle check in the matched graph."""
    state = {}
    for root in sorted(graph):
        if root in state:
            continue
        path, frames = [root], [iter(graph.get(root, ()))]
        state[root] = "open"
        while frames:
            nxt = next(frames[-1], None)
            if nxt is None:
                state[path.pop()] = "done"
                frames.pop()
            elif state.get(nxt) == "open":
                return path[path.index(nxt):] + [nxt]
            elif nxt not in state:
                state[nxt] = "open"
                path.append(nxt)
                frames.append(iter(graph.get(nxt, ())))
    return None


def _shortest_path(start, graph: dict, targets: set) -> list | None:
    """The shortest, then lexicographically smallest, path of matched edges to a target."""
    if start in targets:
        return [start]
    seen, frontier = {start}, [[start]]
    while frontier:
        following = []
        for path in frontier:
            for nxt in sorted(graph.get(path[-1], ())):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in targets:
                    return path + [nxt]
                following.append(path + [nxt])
        frontier = sorted(following)
    return None


def _closure(start, graph: dict) -> set:
    seen, todo = {start}, [start]
    while todo:
        for nxt in graph.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def _extract_slice_digest(selection: Mapping, body: Mapping, data: bytes | None) -> str | None:
    """Extract and hash the slice named by a structured v2 ``selection``, or ``None`` if unavailable/invalid."""
    if data is None or verify(body, content=data).content_identity != "match":
        return None
    raw = bytes(data)
    kind = selection.get("kind")
    if kind == "byte_range":
        start, end = selection["start"], selection["end"]
        if end > len(raw):
            return None
        return "sha256:" + hashlib.sha256(raw[start:end]).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if kind == "line_range":
        lines = text.splitlines()
        start, end = selection["start"], selection["end"]
        if end > len(lines):
            return None
        joined = "\n".join(lines[start - 1:end]).encode("utf-8")
        return "sha256:" + hashlib.sha256(joined).hexdigest()
    if kind == "text_quote":
        anchored = selection["prefix"] + selection["exact"] + selection["suffix"]
        first = text.find(anchored)
        if first == -1 or text.find(anchored, first + 1) != -1:
            return None
        return "sha256:" + hashlib.sha256(selection["exact"].encode("utf-8")).hexdigest()
    if kind == "json_pointer":
        try:
            doc = parse_json(raw)
        except Exception:
            return None
        ptr = selection["pointer"]
        cur = doc
        if ptr != "":
            for token in ptr.split("/")[1:]:
                key = token.replace("~1", "/").replace("~0", "~")
                if isinstance(cur, Mapping) and key in cur:
                    cur = cur[key]
                elif isinstance(cur, list) and _ARRAY_INDEX.fullmatch(key) is not None and int(key) < len(cur):
                    cur = cur[int(key)]
                else:
                    return None
        return "sha256:" + hashlib.sha256(canonicalize(cur)).hexdigest()
    return None


def _mapping_field(prof, name: str):
    return prof.get(name) if isinstance(prof, Mapping) else None


def _selection_status_for(
    start_key: tuple,
    closure_nodes: set[tuple],
    edges_by_key: dict[tuple, list[dict]],
    graph: dict[tuple, list[tuple]],
    profiled: dict[tuple, Mapping],
    index: dict[tuple, Mapping],
    superseded: set[tuple],
    changed_key: tuple,
    meaning_changed: bool,
    contents: Mapping | None,
) -> str:
    """Evaluate ``"unchanged" | "changed" | "unscoped"`` for an affected dependent."""
    if meaning_changed:
        return "changed"

    superseded_edges = [
        e
        for node in sorted(closure_nodes)
        if node not in superseded and node in edges_by_key
        for e in edges_by_key[node]
        if e["state"] == "match" and e.get("key") in superseded
    ]
    if not superseded_edges:
        return "unscoped"

    new_meaning = _mapping_field(profile_of(index[changed_key]), "meaning")
    for edge in superseded_edges:
        old_meaning = _mapping_field(profile_of(index[edge["key"]]), "meaning")
        if old_meaning != new_meaning:
            return "changed"

    if contents is None:
        return "unscoped"

    saw_structured = False
    all_structured_unchanged = True
    for edge in superseded_edges:
        sel = edge["selection"]
        if not _is_structured_selection(sel):
            all_structured_unchanged = False
            continue
        saw_structured = True
        old_key = edge["key"]
        old_body, new_body = index[old_key], index[changed_key]
        old_data = contents.get(old_key)
        new_data = contents.get(changed_key)
        if old_data is None or new_data is None:
            all_structured_unchanged = False
            continue
        if (
            verify(old_body, content=old_data).content_identity != "match"
            or verify(new_body, content=new_data).content_identity != "match"
        ):
            all_structured_unchanged = False
            continue
        old_slice = _extract_slice_digest(sel, old_body, old_data)
        if old_slice is None:
            all_structured_unchanged = False
            continue
        new_slice = _extract_slice_digest(sel, new_body, new_data)
        if new_slice != old_slice:
            return "changed"

    closure_complete = all(
        node in profiled
        and profile_of(index[node])["coverage"] == "complete"
        and all(e["state"] == "match" for e in edges_by_key[node])
        for node in (closure_nodes | _closure(changed_key, graph))
    )
    if saw_structured and all_structured_unchanged and closure_complete:
        return "unchanged"
    return "unscoped"


_MARKER_REASON = {"withheld": "withheld_pin", "unknown": "unknown_pin"}
_STATE_REASON = {"missing": "missing_pin", "mismatch": "pin_mismatch"}


def impact(records: Iterable[Mapping], changed: Mapping, *, contents: Mapping | None = None) -> dict:
    """What a correction affects, for every validly profiled record.

    For pure ``v1`` bundles called without ``contents``, the returned dictionary matches
    Tutorial D's ``org.comuvia.dependencies/v1`` report byte-for-byte. When ``contents`` is
    provided or any record uses ``org.comuvia.dependencies/v2``, each ``affected`` entry
    also carries ``selection_status`` (``"unchanged"``, ``"changed"`` or ``"unscoped"``).
    """
    bodies, index = _index(records)
    changed_key = key_of(changed)
    if not _is_int(changed_key[2]) or changed_key[2] < 2:
        raise ChangeNotSuccessor(f"{label(changed_key)} is not a correction (revision 2 or later)")
    if changed_key not in index or record_digest(index[changed_key]) != record_digest(changed):
        raise ChangeNotSuccessor(f"{label(changed_key)} is not this record in the bundle")
    predecessor = changed.get("predecessor")
    previous = (
        index.get((predecessor["record_type"], predecessor["id"], predecessor["revision"]))
        if isinstance(predecessor, Mapping)
        else None
    )
    if previous is None or record_digest(previous) != predecessor.get("digest"):
        raise ChangeNotSuccessor(f"the predecessor of {label(changed_key)} does not resolve as match")

    uses_v2 = any(
        isinstance(b.get("extensions"), Mapping) and NAMESPACE_V2 in b["extensions"]
        for b in bodies
    )
    emit_selection_status = uses_v2 or contents is not None

    same = (changed_key[0], changed_key[1])
    superseded = {k for k in index if (k[0], k[1]) == same and k[2] < changed_key[2]}
    profiled = {k: b for k, b in index.items() if _valid_profile(b)}
    edges = {k: _edges(b, index) for k, b in profiled.items()}
    graph = {k: sorted({e["key"] for e in es if e["state"] == "match"}) for k, es in edges.items()}
    cycle = _find_cycle(graph)
    if cycle:
        raise DependencyCycle(" -> ".join(label(k) for k in cycle))

    old_profile, new_profile = profile_of(previous), profile_of(changed)
    meaning_changed = _mapping_field(old_profile, "meaning") != _mapping_field(new_profile, "meaning")

    statuses, entries = {}, {}
    for key in sorted(
        k for k, b in index.items()
        if (profile_of(b) is not None or any(c == reasons.INVALID_PROFILE for _, c in _profile_issues(b)))
        and k not in profiled
    ):
        if (key[0], key[1]) == same:
            continue
        entries[key] = {
            "record": _ref(key),
            "digest": record_digest(index[key]),
            "edges": [],
            "synthetic_in_closure": None,
            "status": "unknown",
            "reasons": ["invalid_profile"],
        }
        statuses[key] = "unknown"

    for key in sorted(profiled):
        if (key[0], key[1]) == same:
            continue
        closure_nodes = _closure(key, graph)
        synthetic = any(
            profile_of(index[n])["value_origin"] == "synthetic"
            for n in closure_nodes
            if n in profiled
        )
        entry = {
            "record": _ref(key),
            "digest": record_digest(index[key]),
            "edges": [{k: v for k, v in e.items() if k not in ("key", "selection")} for e in edges[key]],
            "synthetic_in_closure": synthetic,
        }
        path = _shortest_path(key, graph, superseded)
        if path is not None:
            entry["status"] = "affected"
            entry["path"] = [_ref(k) for k in path]
            if emit_selection_status:
                entry["selection_status"] = _selection_status_for(
                    key, closure_nodes, edges, graph, profiled, index, superseded, changed_key, meaning_changed, contents
                )
        else:
            found_reasons = set()
            for node in closure_nodes:
                if node not in profiled:
                    found_reasons.add("unprofiled_input")
                    continue
                coverage = profile_of(index[node])["coverage"]
                if coverage != "complete":
                    found_reasons.add(f"{coverage}_coverage")
                for e in edges[node]:
                    if e["state"] == "marker":
                        found_reasons.add(_MARKER_REASON[e["marker"]])
                    elif e["state"] != "match":
                        found_reasons.add(_STATE_REASON[e["state"]])
            entry["status"] = "unknown" if found_reasons else "unaffected"
            if found_reasons:
                entry["reasons"] = sorted(found_reasons)
        statuses[key] = entry["status"]
        entries[key] = entry

    for key, entry in entries.items():
        if entry["status"] == "affected":
            latest = max(k for k in index if (k[0], k[1]) == (key[0], key[1]))
            entry["latest"] = _ref(latest)
            entry["latest_status"] = statuses.get(latest, "not_profiled")

    change = {
        "content_changed": _mapping_field(previous.get("content"), "digest") != _mapping_field(changed.get("content"), "digest"),
        "meaning_changed": meaning_changed,
        "dependencies_changed": _mapping_field(old_profile, "depends_on") != _mapping_field(new_profile, "depends_on"),
        "changed_fields": sorted(
            k for k in set(previous) | set(changed)
            if k not in ("revision", "predecessor") and previous.get(k) != changed.get(k)
        ),
    }
    return {
        "profile": NAMESPACE_V2 if uses_v2 else NAMESPACE,
        "changed": {**_ref(changed_key), "digest": record_digest(changed)},
        "superseded": [_ref(k) for k in sorted(superseded)],
        "change": change,
        "records": [entries[k] for k in sorted(entries)],
        "coverage": "partial" if any(s == "unknown" for s in statuses.values()) else "complete",
        "limitations": list(LIMITATIONS),
    }
