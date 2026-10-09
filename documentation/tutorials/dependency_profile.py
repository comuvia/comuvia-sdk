"""Declared dependencies and correction impact: the ``org.comuvia.dependencies/v1`` profile.

An example helper, not part of the ``comuvia`` package. It uses only the public ``comuvia``
0.1.0 API and the Python standard library, and it does no I/O. Tutorial D explains the
profile; ``tutorial_d_dependencies.py`` checks every value stated there.

The profile is one object under ``extensions["org.comuvia.dependencies/v1"]`` of a
``resource_snapshot`` or ``artifact_descriptor``:

- ``value_origin``: ``observed``, ``derived``, ``synthetic`` or ``none``;
- ``meaning``: exactly ``measure``, ``unit``, ``period`` and ``geography``, each a non-empty
  string or a 0.1 ``unknown``/``withheld`` marker;
- ``coverage``: ``complete``, ``partial`` or ``unknown``, the producer's statement about
  whether ``depends_on`` lists every input. Nothing here can check it;
- ``depends_on``: 0 to 64 edges, each exactly ``role`` (``data_input``, ``method`` or
  ``assumption``), ``pin`` (a ``comuvia.reference_to`` value or a marker) and
  ``selection`` (a string or a marker; recorded, never interpreted).

Two functions:

- ``check_bundle(records, contents=None)`` returns sorted ``BundleIssue`` values;
- ``impact(records, changed)`` returns a deterministic report of what a correction affects.
  It raises ``DependencyCycle`` or ``ChangeNotSuccessor`` instead of returning a partial report.

A dependency is a declaration. It does not prove causation, completeness or correctness, and
a digest proves identity, not truth.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import comuvia

NAMESPACE = "org.comuvia.dependencies/v1"
_PROFILE_KEY = re.compile(r"^org\.comuvia\.dependencies/v([0-9]+)\Z")  # \Z: "$" would also match before a final newline
_PROFILE_FIELDS = {"value_origin", "meaning", "coverage", "depends_on"}
_MEANING_FIELDS = {"measure", "unit", "period", "geography"}
_EDGE_FIELDS = {"role", "pin", "selection"}
_REFERENCE_FIELDS = {"record_type", "id", "revision", "digest"}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}\Z")
VALUE_ORIGINS = ("observed", "derived", "synthetic", "none")
COVERAGES = ("complete", "partial", "unknown")
ROLES = ("data_input", "method", "assumption")
PROFILED_TYPES = ("resource_snapshot", "artifact_descriptor")
MAX_RECORDS = 10_000
MAX_EDGES = 64
LIMITATIONS = (
    "A declared dependency does not prove causation, completeness or correctness.",
    "Digests prove byte and record identity, not truth.",
    "No independent time evidence: declared times are as recorded.",
    "Coverage is the producer's statement; omitted inputs cannot be detected.",
)
_POINTER = "/extensions/" + NAMESPACE.replace("~", "~0").replace("/", "~1")


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


def profile_of(body: Mapping):
    """The v1 profile object, or None when the record is not profiled."""
    extensions = body.get("extensions")
    if isinstance(extensions, Mapping):
        return extensions.get(NAMESPACE)
    return None


def _is_text_or_marker(value) -> bool:
    return (isinstance(value, str) and value != "") or comuvia.is_marker(value)


def _is_reference(value) -> bool:
    return (isinstance(value, Mapping) and set(value) == _REFERENCE_FIELDS
            and isinstance(value["record_type"], str) and isinstance(value["id"], str)
            and isinstance(value["revision"], int) and not isinstance(value["revision"], bool)
            and isinstance(value["digest"], str) and _DIGEST.match(value["digest"]) is not None)


def _profile_issues(body: Mapping) -> list[tuple[str, str]]:
    """(pointer, code) problems in the shape of a record's profile."""
    found = []
    extensions = body.get("extensions")
    if isinstance(extensions, Mapping):
        for name in extensions:
            match = _PROFILE_KEY.match(name)
            if match and match.group(1) != "1":
                found.append(("/extensions/" + name.replace("~", "~0").replace("/", "~1"), "unsupported_profile_version"))
    profile = profile_of(body)
    if profile is None:
        return found
    if body.get("record_type") not in PROFILED_TYPES or not isinstance(profile, Mapping) or set(profile) != _PROFILE_FIELDS:
        return found + [(_POINTER, "invalid_profile")]
    if profile["value_origin"] not in VALUE_ORIGINS:
        found.append((_POINTER + "/value_origin", "invalid_profile"))
    meaning = profile["meaning"]
    if not isinstance(meaning, Mapping) or set(meaning) != _MEANING_FIELDS:
        found.append((_POINTER + "/meaning", "invalid_profile"))
    else:
        for name in sorted(_MEANING_FIELDS):
            if not _is_text_or_marker(meaning[name]):
                found.append((f"{_POINTER}/meaning/{name}", "invalid_profile"))
    if profile["coverage"] not in COVERAGES:
        found.append((_POINTER + "/coverage", "invalid_profile"))
    edges = profile["depends_on"]
    if not isinstance(edges, list):
        return found + [(_POINTER + "/depends_on", "invalid_profile")]
    if len(edges) > MAX_EDGES:
        found.append((_POINTER + "/depends_on", "limit_exceeded"))
    seen = set()
    for index, edge in enumerate(edges):
        at = f"{_POINTER}/depends_on/{index}"
        if not isinstance(edge, Mapping) or set(edge) != _EDGE_FIELDS:
            found.append((at, "invalid_profile"))
            continue
        if not isinstance(edge["role"], str):
            found.append((at + "/role", "invalid_profile"))
        elif edge["role"] not in ROLES:
            found.append((at + "/role", "unsupported_role"))
        pin = edge["pin"]
        if _is_reference(pin):
            identity = (pin["record_type"], pin["id"], pin["revision"], pin["digest"])
            if identity in seen:
                found.append((at + "/pin", "duplicate_pin"))
            seen.add(identity)
        elif not comuvia.is_marker(pin):
            found.append((at + "/pin", "invalid_profile"))
        if not _is_text_or_marker(edge["selection"]):
            found.append((at + "/selection", "invalid_profile"))
    data_inputs = sum(1 for e in edges if isinstance(e, Mapping) and e.get("role") == "data_input")
    if profile["value_origin"] == "observed" and data_inputs:
        found.append((_POINTER + "/value_origin", "observed_has_inputs"))
    if profile["value_origin"] == "derived" and not data_inputs:
        found.append((_POINTER + "/value_origin", "derived_without_inputs"))
    if body.get("data_origin") == "observed" and profile["value_origin"] == "synthetic":
        found.append((_POINTER + "/value_origin", "origin_conflict"))
    units = body.get("units")
    if (body.get("record_type") == "artifact_descriptor" and isinstance(units, list) and isinstance(meaning, Mapping)
            and isinstance(meaning.get("unit"), str) and meaning["unit"] not in units):
        found.append((_POINTER + "/meaning/unit", "unit_conflict"))
    return found


def _valid_profile(body: Mapping) -> bool:
    """True when the record has a v1 profile without problems (another version's key is not judged here)."""
    return (profile_of(body) is not None
            and not [code for _, code in _profile_issues(body) if code != "unsupported_profile_version"])


def _index(records: Iterable[Mapping]) -> tuple[list[Mapping], dict]:
    bodies = sorted(records, key=lambda b: (str(b.get("record_type")), str(b.get("id")), b.get("revision") or 0))
    return bodies, {key_of(b): b for b in bodies}


def _edges(body: Mapping, index: dict) -> list[dict]:
    """Every declared edge of a validly profiled record, with its resolution state."""
    resolved = []
    for edge in profile_of(body)["depends_on"]:
        pin = edge["pin"]
        if comuvia.is_marker(pin):
            kind = "withheld" if "withheld" in pin else "unknown"
            resolved.append({"role": edge["role"], "target": dict(pin), "state": "marker", "marker": kind})
            continue
        target_key = (pin["record_type"], pin["id"], pin["revision"])
        target = index.get(target_key)
        if target is None:
            state = "missing"
        elif comuvia.record_digest(target) == pin["digest"]:
            state = "match"
        else:
            state = "mismatch"
        resolved.append({"role": edge["role"], "target": _ref(target_key), "state": state, "key": target_key})
    return resolved


def check_bundle(records: Iterable[Mapping], contents: Mapping | None = None) -> list[BundleIssue]:
    """Every core and profile problem in a bundle of records, sorted.

    ``contents`` optionally maps ``(record_type, id, revision)`` to retained bytes; each is
    checked with ``comuvia.verify`` and reported as ``content_digest_mismatch`` if it differs.
    """
    bodies, index = _index(records)
    issues: set[BundleIssue] = set()
    if len(bodies) > MAX_RECORDS:
        issues.add(BundleIssue("", "", "limit_exceeded"))
    for body in bodies:
        name = label(key_of(body))
        for issue in comuvia.validate(body):
            issues.add(BundleIssue(name, issue.pointer, issue.code))
        for pointer, code in _profile_issues(body):
            issues.add(BundleIssue(name, pointer, code))
        if profile_of(body) is not None and isinstance(profile_of(body), Mapping) and isinstance(profile_of(body).get("depends_on"), list):
            for position, edge in enumerate(profile_of(body)["depends_on"]):
                if not isinstance(edge, Mapping) or not _is_reference(edge.get("pin")):
                    continue
                pin = edge["pin"]
                target = index.get((pin["record_type"], pin["id"], pin["revision"]))
                at = f"{_POINTER}/depends_on/{position}/pin"
                if target is None:
                    issues.add(BundleIssue(name, at, "missing_pin"))
                elif comuvia.record_digest(target) != pin["digest"]:
                    issues.add(BundleIssue(name, at, "pin_mismatch"))
    for issue in comuvia.revision_conflicts(bodies):
        issues.add(BundleIssue("", issue.pointer, issue.code))
    for key, data in sorted((contents or {}).items()):
        body = index.get(tuple(key))
        if body is not None and comuvia.verify(body, content=data).content_identity == "mismatch":
            issues.add(BundleIssue(label(tuple(key)), "/content/digest", "content_digest_mismatch"))
    return sorted(issues)


def _find_cycle(graph: dict) -> list | None:
    """A cycle in the matched graph, if any (defensive: digests make one infeasible).

    Iterative depth-first search, so a chain as long as the record limit cannot exhaust the stack.
    """
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


_MARKER_REASON = {"withheld": "withheld_pin", "unknown": "unknown_pin"}
_STATE_REASON = {"missing": "missing_pin", "mismatch": "pin_mismatch"}


def impact(records: Iterable[Mapping], changed: Mapping) -> dict:
    """What a correction affects, for every validly profiled record.

    ``changed`` is a record at revision 2 or later, present in the bundle, whose
    ``predecessor`` resolves there with a matching digest. Its lower revisions in the bundle
    are the superseded editions. Each other profiled record is ``affected`` (a path of
    matched pins leads to a superseded edition), ``unaffected`` (no such path, and its whole
    matched closure is complete and fully matched) or ``unknown`` (with reasons).

    A record whose v1 profile is invalid is ``unknown`` with reason ``invalid_profile``, no path,
    no edges and ``synthetic_in_closure`` null; it is never followed, so a ``match`` pin to it
    gives its dependents ``unprofiled_input`` (a pin to a record without a valid v1 profile).
    """
    bodies, index = _index(records)
    changed_key = key_of(changed)
    if not isinstance(changed_key[2], int) or changed_key[2] < 2:
        raise ChangeNotSuccessor(f"{label(changed_key)} is not a correction (revision 2 or later)")
    if changed_key not in index or comuvia.record_digest(index[changed_key]) != comuvia.record_digest(changed):
        raise ChangeNotSuccessor(f"{label(changed_key)} is not this record in the bundle")
    predecessor = changed.get("predecessor")
    previous = index.get((predecessor["record_type"], predecessor["id"], predecessor["revision"])) if isinstance(predecessor, Mapping) else None
    if previous is None or comuvia.record_digest(previous) != predecessor.get("digest"):
        raise ChangeNotSuccessor(f"the predecessor of {label(changed_key)} does not resolve as match")

    same = (changed_key[0], changed_key[1])
    superseded = {k for k in index if (k[0], k[1]) == same and k[2] < changed_key[2]}
    profiled = {k: b for k, b in index.items() if _valid_profile(b)}
    edges = {k: _edges(b, index) for k, b in profiled.items()}
    graph = {k: sorted({e["key"] for e in es if e["state"] == "match"}) for k, es in edges.items()}
    cycle = _find_cycle(graph)
    if cycle:
        raise DependencyCycle(" -> ".join(label(k) for k in cycle))

    statuses, entries = {}, {}
    for key in sorted(k for k, b in index.items() if profile_of(b) is not None and k not in profiled):
        if (key[0], key[1]) == same:
            continue
        # An invalid v1 profile is not followed: no path, and its dependents see an unprofiled input.
        entries[key] = {"record": _ref(key), "digest": comuvia.record_digest(index[key]), "edges": [],
                        "synthetic_in_closure": None, "status": "unknown", "reasons": ["invalid_profile"]}
        statuses[key] = "unknown"
    for key in sorted(profiled):
        if (key[0], key[1]) == same:
            continue
        synthetic = any(profile_of(index[n])["value_origin"] == "synthetic"
                        for n in _closure(key, graph) if n in profiled)
        entry = {"record": _ref(key), "digest": comuvia.record_digest(index[key]),
                 "edges": [{k: v for k, v in e.items() if k != "key"} for e in edges[key]],
                 "synthetic_in_closure": synthetic}
        path = _shortest_path(key, graph, superseded)
        if path is not None:
            entry["status"] = "affected"
            entry["path"] = [_ref(k) for k in path]
        else:
            reasons = set()
            for node in _closure(key, graph):
                if node not in profiled:
                    reasons.add("unprofiled_input")
                    continue
                coverage = profile_of(index[node])["coverage"]
                if coverage != "complete":
                    reasons.add(f"{coverage}_coverage")
                for e in edges[node]:
                    if e["state"] == "marker":
                        reasons.add(_MARKER_REASON[e["marker"]])
                    elif e["state"] != "match":
                        reasons.add(_STATE_REASON[e["state"]])
            entry["status"] = "unknown" if reasons else "unaffected"
            if reasons:
                entry["reasons"] = sorted(reasons)
        statuses[key] = entry["status"]
        entries[key] = entry
    for key, entry in entries.items():
        if entry["status"] == "affected":
            latest = max(k for k in index if (k[0], k[1]) == (key[0], key[1]))
            entry["latest"] = _ref(latest)
            entry["latest_status"] = statuses.get(latest, "not_profiled")

    old_profile, new_profile = profile_of(previous), profile_of(changed)
    change = {
        "content_changed": (previous.get("content") or {}).get("digest") != (changed.get("content") or {}).get("digest"),
        "meaning_changed": (old_profile or {}).get("meaning") != (new_profile or {}).get("meaning"),
        "dependencies_changed": (old_profile or {}).get("depends_on") != (new_profile or {}).get("depends_on"),
        "changed_fields": sorted(k for k in set(previous) | set(changed)
                                 if k not in ("revision", "predecessor") and previous.get(k) != changed.get(k)),
    }
    return {
        "profile": NAMESPACE,
        "changed": {**_ref(changed_key), "digest": comuvia.record_digest(changed)},
        "superseded": [_ref(k) for k in sorted(superseded)],
        "change": change,
        "records": [entries[k] for k in sorted(entries)],
        "coverage": "partial" if any(s == "unknown" for s in statuses.values()) else "complete",
        "limitations": list(LIMITATIONS),
    }
