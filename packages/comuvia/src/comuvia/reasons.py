"""Reason-code vocabulary shared by parsing, validation, verification, storage and evaluation.

A *refusal* rejects invalid input; the record is never stored. A *verification* result
reports an identity check. An *exclusion* keeps a valid record but leaves it out of an
evaluation.
"""

# Strict JSON parsing (refused before canonicalization).
BYTE_ORDER_MARK = "byte_order_mark"
INVALID_UTF8 = "invalid_utf8"
INVALID_JSON = "invalid_json"
DUPLICATE_MEMBER = "duplicate_member"
LONE_SURROGATE = "lone_surrogate"
NON_FINITE_NUMBER = "non_finite_number"
NUMBER_OUT_OF_RANGE = "number_out_of_range"
INTEGER_OUT_OF_RANGE = "integer_out_of_range"
NESTING_TOO_DEEP = "nesting_too_deep"

# Record validation.
MISSING_REQUIRED_FIELD = "missing_required_field"
UNRECOGNIZED_MEMBER = "unrecognized_member"
UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
UNKNOWN_RECORD_TYPE = "unknown_record_type"
NOT_AN_OBJECT = "not_an_object"
INVALID_TYPE = "invalid_type"
NULL_NOT_ALLOWED = "null_not_allowed"
INVALID_VALUE = "invalid_value"
OUT_OF_RANGE = "out_of_range"
INVALID_MARKER = "invalid_marker"
INVALID_TIMESTAMP = "invalid_timestamp"
INVALID_DATE = "invalid_date"
INVALID_PERIOD = "invalid_period"
INVALID_IDENTIFIER = "invalid_identifier"
INVALID_EXTENSION_KEY = "invalid_extension_key"
MALFORMED_DIGEST = "malformed_digest"
UNSUPPORTED_DIGEST_ALGORITHM = "unsupported_digest_algorithm"
INVALID_PREDECESSOR = "invalid_predecessor"
INVALID_SELECTOR = "invalid_selector"
INVALID_COVERAGE = "invalid_coverage"
INFORMATION_CUTOFF_AFTER_ISSUED_AT = "information_cutoff_after_issued_at"
RESOLUTION_DEADLINE_BEFORE_FORECAST_DEADLINE = "resolution_deadline_before_forecast_deadline"

# Identity verification.
RECORD_DIGEST_MISMATCH = "record_digest_mismatch"
CONTENT_DIGEST_MISMATCH = "content_digest_mismatch"
REFERENCE_DIGEST_MISMATCH = "reference_digest_mismatch"
REVISION_CONFLICT = "revision_conflict"

# Selector check against retained bytes.
QUOTE_MISMATCH = "quote_mismatch"
SELECTOR_MISMATCH = "selector_mismatch"

# Record store: append refusals and writer lock.
NOT_A_STORE = "not_a_store"
STORE_EXISTS = "store_exists"
STORE_LOCKED = "store_locked"
READ_ONLY_STORE = "read_only_store"
UNRESOLVED_REFERENCE = "unresolved_reference"
INDEX_TORN = "index_torn"

# Record store verification.
MISSING_BODY = "missing_body"
BODY_DIGEST_MISMATCH = "body_digest_mismatch"
TORN_INDEX_LINE = "torn_index_line"
ORPHAN_BODY = "orphan_body"
DUPLICATE_INDEX_ENTRY = "duplicate_index_entry"
INDEX_ENTRY_INVALID = "index_entry_invalid"
INDEX_ENTRY_MISMATCH = "index_entry_mismatch"
INDEX_SEQUENCE_GAP = "index_sequence_gap"
UNEXPECTED_FILE = "unexpected_file"
LEFTOVER_TEMP_FILE = "leftover_temp_file"

# Reproduction of a stored evaluation.
EVALUATION_INPUT_NOT_FOUND = "evaluation_input_not_found"
RULE_NOT_FOUND = "rule_not_found"

# Evaluation exclusions (emitted by comuvia.evaluation).
NO_DECLARED_PROBABILITY = "no_declared_probability"
CONDITIONAL_SCENARIO = "conditional_scenario"
NO_PINNED_QUESTION = "no_pinned_question"
NOT_A_FORECAST = "not_a_forecast"
QUESTION_MISMATCH = "question_mismatch"
UNIT_MISMATCH = "unit_mismatch"
ISSUED_AFTER_FORECAST_DEADLINE = "issued_after_forecast_deadline"
UNRESOLVED_OUTCOME = "unresolved_outcome"
AMBIGUOUS_OUTCOME = "ambiguous_outcome"
MISSING_REQUIRED_TIME = "missing_required_time"
INDETERMINATE_TIME_ORDER = "indeterminate_time_order"
ANNULLED_QUESTION = "annulled_question"
UNKNOWN_CONDITIONS = "unknown_conditions"
QUESTION_NOT_FOUND = "question_not_found"
NO_OUTCOME_RECORDED = "no_outcome_recorded"
MULTIPLE_OUTCOMES = "multiple_outcomes"
INCOMPLETE_QUESTION = "incomplete_question"
RETROSPECTIVE_REGISTRATION = "retrospective_registration"
RESOLUTION_RULE_INCOMPLETE = "resolution_rule_incomplete"

# Limitation codes recorded in question/forecast `limitations` (a record's own known limits).
# The scoring-rule descriptor states which of them exclude a forecast.
OUTCOME_PUBLISHED_BEFORE_REGISTRATION = "outcome_published_before_registration"
TEXT_POSSIBLY_TRUNCATED = "text_possibly_truncated"
PROVIDER_FIELDS_WITHHELD = "provider_fields_withheld"

PARSE_CODES = frozenset({
    BYTE_ORDER_MARK, INVALID_UTF8, INVALID_JSON, DUPLICATE_MEMBER, LONE_SURROGATE,
    NON_FINITE_NUMBER, NUMBER_OUT_OF_RANGE, INTEGER_OUT_OF_RANGE, NESTING_TOO_DEEP,
})
VALIDATION_CODES = frozenset({
    MISSING_REQUIRED_FIELD, UNRECOGNIZED_MEMBER, UNSUPPORTED_SCHEMA_VERSION, UNKNOWN_RECORD_TYPE,
    NOT_AN_OBJECT, INVALID_TYPE, NULL_NOT_ALLOWED, INVALID_VALUE, OUT_OF_RANGE, INVALID_MARKER,
    INVALID_TIMESTAMP, INVALID_DATE, INVALID_PERIOD, INVALID_IDENTIFIER, INVALID_EXTENSION_KEY,
    MALFORMED_DIGEST, UNSUPPORTED_DIGEST_ALGORITHM, INVALID_PREDECESSOR, INVALID_SELECTOR,
    INVALID_COVERAGE, INFORMATION_CUTOFF_AFTER_ISSUED_AT, RESOLUTION_DEADLINE_BEFORE_FORECAST_DEADLINE,
})
VERIFICATION_CODES = frozenset({
    RECORD_DIGEST_MISMATCH, CONTENT_DIGEST_MISMATCH, REFERENCE_DIGEST_MISMATCH, REVISION_CONFLICT,
})
EXCLUSION_CODES = frozenset({
    NO_DECLARED_PROBABILITY, CONDITIONAL_SCENARIO, NO_PINNED_QUESTION, NOT_A_FORECAST,
    QUESTION_MISMATCH, UNIT_MISMATCH, ISSUED_AFTER_FORECAST_DEADLINE, UNRESOLVED_OUTCOME,
    AMBIGUOUS_OUTCOME, MISSING_REQUIRED_TIME, INDETERMINATE_TIME_ORDER, ANNULLED_QUESTION,
    UNKNOWN_CONDITIONS, QUESTION_NOT_FOUND, NO_OUTCOME_RECORDED, MULTIPLE_OUTCOMES, INCOMPLETE_QUESTION,
    RETROSPECTIVE_REGISTRATION, RESOLUTION_RULE_INCOMPLETE,
})
LIMITATION_CODES = frozenset({OUTCOME_PUBLISHED_BEFORE_REGISTRATION, TEXT_POSSIBLY_TRUNCATED, PROVIDER_FIELDS_WITHHELD})
STORE_CODES = frozenset({
    NOT_A_STORE, STORE_EXISTS, STORE_LOCKED, READ_ONLY_STORE, UNRESOLVED_REFERENCE, INDEX_TORN,
    MISSING_BODY, BODY_DIGEST_MISMATCH, TORN_INDEX_LINE, ORPHAN_BODY, DUPLICATE_INDEX_ENTRY, INDEX_ENTRY_INVALID,
    INDEX_ENTRY_MISMATCH, INDEX_SEQUENCE_GAP, UNEXPECTED_FILE, LEFTOVER_TEMP_FILE,
})
SELECTOR_CODES = frozenset({QUOTE_MISMATCH, SELECTOR_MISMATCH})
REPRODUCTION_CODES = frozenset({EVALUATION_INPUT_NOT_FOUND, RULE_NOT_FOUND})
