"""Reason codes used by foreglass (reading, intake, catalog and normalization)."""

# Explicit reader (refusals).
UNKNOWN_ARTIFACT = "unknown_artifact"
INSECURE_URL = "insecure_url"
HOST_NOT_ALLOWED = "host_not_allowed"
REDIRECT_OFF_ORIGIN = "redirect_off_origin"
INSECURE_REDIRECT = "insecure_redirect"
TOO_MANY_REDIRECTS = "too_many_redirects"
RESPONSE_TOO_LARGE = "response_too_large"
HTTP_STATUS = "http_status"
NETWORK_ERROR = "network_error"
INCOMPLETE_RESPONSE = "incomplete_response"
DEADLINE_EXCEEDED = "deadline_exceeded"
UNSUPPORTED_CONTENT_ENCODING = "unsupported_content_encoding"
INVALID_ARCHIVE_ENTRY = "invalid_archive_entry"

# Intake of a snapshot bundle.
INCOMPLETE_INTAKE = "incomplete_intake"
DIGEST_MISMATCH = "digest_mismatch"
PARSE_REFUSED = "parse_refused"
SCHEMA_MISMATCH = "schema_mismatch"
COUNTS_MISMATCH = "counts_mismatch"
ARCHIVE_INDEX_MISMATCH = "archive_index_mismatch"
NOT_A_SNAPSHOT_ARCHIVE = "not_a_snapshot_archive"
REPLAY_NOT_ACCEPTED = "replay_not_accepted"

# Drift findings (reported, not fatal).
UNRECOGNIZED_PROVIDER_FIELD = "unrecognized_provider_field"
OUTCOME_NORMALIZATION_UNSUPPORTED = "outcome_normalization_unsupported"

# Normalization: lanes not mapped to comuvia records.
UNSUPPORTED_OUTPUT_KIND = "unsupported_output_kind"
NO_PINNED_QUESTION = "no_pinned_question"
MALFORMED_LANE = "malformed_lane"
RESOLUTION_RULE_WITHHELD = "resolution_rule_withheld"
QUESTION_TEXT_VARIES = "question_text_varies"
