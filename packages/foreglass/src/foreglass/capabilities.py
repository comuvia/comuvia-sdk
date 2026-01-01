"""What foreglass 0.1 implements, and what it deliberately does not."""

from __future__ import annotations


def capabilities() -> dict:
    """A truthful capability statement. Unsupported operations have no method at all."""
    return {
        "implemented": {
            "explicit_read": "PublicClient fetches only the documented public artifacts, bounded, https-only, on request",
            "exact_byte_intake": "SnapshotArchive retains exact bytes and moves the accepted snapshot only after verification",
            "lane_catalog": "LaneCatalog: typed, read-only view of published lane fields with their declared meanings",
            "readings": "read_reading types index readings with caveats; never forecasts or probabilities",
            "normalization": "normalize maps binary lanes with a pinned qid to comuvia question and forecast records",
        },
        "unsupported": {
            "custom_execution": "there is no custom-forecast or model-execution endpoint; the published files are the interface",
            "mcp": "no MCP server exists or is offered",
            "submission": "nothing is uploaded or submitted",
            "outcome_normalization": "outcome fields are recognized but not normalized in 0.1",
            "interval_and_point_lanes": "comuvia 0.1 has no record type for interval or point outputs",
            "proof_verification": "OpenTimestamps proofs are retained as bytes but not verified; timestamp assurance is unavailable",
        },
        "network": "no request on import or construction; each read is an explicit call",
    }
