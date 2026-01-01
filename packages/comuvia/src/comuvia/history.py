"""Read-time views over record revisions. Nothing here mutates records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def latest_revisions(records: Iterable[Mapping]) -> dict[tuple[str, str], Mapping]:
    """The highest revision of each (record type, id), derived at read time."""
    latest: dict[tuple[str, str], Mapping] = {}
    for body in records:
        key = (body["record_type"], body["id"])
        if key not in latest or body["revision"] > latest[key]["revision"]:
            latest[key] = body
    return latest
