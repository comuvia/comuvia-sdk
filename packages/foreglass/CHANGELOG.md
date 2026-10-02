# foreglass changelog

## 0.1.0 — 2026-10-01

First release, published on PyPI on 2026-10-01 from tag `v0.1.0`. The copy of this file inside the 0.1.0 source distribution was written before the upload and still calls this version a release candidate. Depends only on `comuvia>=0.1.0,<0.2`. Apache-2.0.

- **`PublicClient`.** Explicit, bounded reads of the documented public ForeGlass artifacts only, with the standard-library `HttpsTransport` (verified TLS; redirects returned, not followed) and an injectable transport:
  - https, host and port allow-lists, and at most 3 re-checked redirects;
  - a streamed size cap, connect and read timeouts, and a total per-artifact deadline;
  - `incomplete_response` for a body that differs from its declared length;
  - at most 2 retries, on network errors, incomplete responses, 429 or 5xx, with `Retry-After` capped.
- **`SnapshotArchive`.** Exact-byte retention. An atomically moved accepted snapshot, re-verified before the pointer moves. Named intake failures. Replays are never accepted as live.
- **`LaneCatalog` and `read_reading`.** A typed, read-only view with declared field meanings. Coverage level is always unknown, truncation is a labelled heuristic, and readings are never probabilities.
- **`normalize`.** Binary lanes with a pinned `qid` become comuvia questions and forecasts, with provider text verbatim, explicit unknowns (including a missing unit) and named not-mapped reasons. `NormalizationError` is raised if the core refuses a record the normalizer built.
- **`capabilities()`.** Custom execution, MCP, submission, outcome normalization, interval/point lanes and proof verification are unsupported, and there is no method for any of them.
- **Outcome keys.** A provisional list is recognized, as `outcome_normalization_unsupported`; any other unknown field is `unrecognized_provider_field`.
