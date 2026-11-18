"""Comuvia: offline, provider-neutral evidence and prediction records.

Implemented: the nine comuvia 0.1 record types as packaged JSON Schemas (with PEP 561
TypedDict definitions in ``comuvia.types``), strict parsing, single-record validation
with named refusal codes, minimal envelope builders (``new_record``, ``revise``),
RFC 8785 canonicalization, content and record digests, identity and selector
verification, detached OpenTimestamps proof parsing (``comuvia.ots``, never verified
against a block chain), a single-writer append-only record store with canonical JSONL
export/import and tamper-evident checkpoints, eligibility and the binary-brier-v1 rule
with named exclusions, reproduction of stored evaluations, and the ``comuvia``
command-line interface. There is no aggregate score, no network access and no runtime
dependency.
"""

__version__ = "0.1.2"

from .builders import new_record, revise
from .identity import (
    ReferenceCheck,
    Verification,
    canonicalize,
    content_digest,
    is_marker,
    parse_json,
    record_digest,
    reference_to,
    revision_conflicts,
    verify,
)
from .evaluation import (
    CandidateResult,
    EvaluationReport,
    Reproduction,
    ScoringRule,
    evaluate,
    evaluation_records,
    load_rule,
    reproduce,
)
from .history import latest_revisions
from .issues import Issue, RefusalError
from .selectors import SelectorCheck, check_selector
from .store import RecordStore, StoreEntry, StoreReport
from .validation import RECORD_TYPES, SCHEMA_VERSION, load_record, schema_dir, schema_files, validate

__all__ = [
    "CandidateResult",
    "EvaluationReport",
    "Issue",
    "RECORD_TYPES",
    "RecordStore",
    "ReferenceCheck",
    "RefusalError",
    "Reproduction",
    "SCHEMA_VERSION",
    "ScoringRule",
    "SelectorCheck",
    "StoreEntry",
    "StoreReport",
    "Verification",
    "canonicalize",
    "check_selector",
    "content_digest",
    "evaluate",
    "evaluation_records",
    "is_marker",
    "latest_revisions",
    "load_record",
    "load_rule",
    "new_record",
    "parse_json",
    "record_digest",
    "reference_to",
    "reproduce",
    "revise",
    "revision_conflicts",
    "schema_dir",
    "schema_files",
    "validate",
    "verify",
]
