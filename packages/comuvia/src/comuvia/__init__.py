"""Comuvia: offline, provider-neutral evidence and prediction records.

Implemented: the nine comuvia 0.1 record types as packaged JSON Schemas (with PEP 561
TypedDict definitions in ``comuvia.types``), strict parsing, single-record validation
with named refusal codes, envelope/content/marker and pin-cascade builders
(``new_record``, ``revise`` with ``repin``, ``stale_pins``), RFC 8785 canonicalization,
content and record digests, runtime wheel identity (``runtime_identity``), identity and
selector verification plus deterministic quote locating and audiovisual ``media_time``
checks (``locate_quote``, ``check_selector``), detached OpenTimestamps proof parsing
(``comuvia.ots``, never verified against a block chain), validated application profiles
(``comuvia.profiles.dependencies`` v1/v2 with selection-aware impact and
``comuvia.profiles.edition_review``), whole-bundle verification and independent
expectations (``verify_bundle``, ``check_embedded``, ``expectation``,
``check_expectation``), a single-writer append-only record store with canonical JSONL
export/import, tamper-evident checkpoints and optional profile enforcement, eligibility
and the binary-brier-v1 rule with named exclusions, reproduction of stored evaluations,
and the ``comuvia`` command-line interface. There is no aggregate score, no network
access and no runtime dependency.
"""

__version__ = "0.1.3"

from .builders import (
    StalePin,
    descriptor_content,
    is_not_applicable,
    new_record,
    not_applicable_marker,
    revise,
    snapshot_content,
    stale_pins,
    unretained_content,
)
from .bundle import (
    BundleReport,
    check_embedded,
    check_expectation,
    expectation,
    preflight,
    verify_bundle,
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
    runtime_identity,
    verify,
)
from .issues import Issue, RefusalError
from .selectors import SelectorCheck, check_selector, locate_quote
from .store import RecordStore, StoreEntry, StoreReport
from .validation import RECORD_TYPES, SCHEMA_VERSION, load_record, schema_dir, schema_files, validate

__all__ = [
    "BundleReport",
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
    "StalePin",
    "StoreEntry",
    "StoreReport",
    "Verification",
    "canonicalize",
    "check_embedded",
    "check_expectation",
    "check_selector",
    "content_digest",
    "descriptor_content",
    "evaluate",
    "evaluation_records",
    "expectation",
    "is_marker",
    "is_not_applicable",
    "latest_revisions",
    "load_record",
    "load_rule",
    "locate_quote",
    "new_record",
    "not_applicable_marker",
    "parse_json",
    "preflight",
    "record_digest",
    "reference_to",
    "reproduce",
    "revise",
    "revision_conflicts",
    "runtime_identity",
    "schema_dir",
    "schema_files",
    "snapshot_content",
    "stale_pins",
    "unretained_content",
    "validate",
    "verify",
    "verify_bundle",
]
