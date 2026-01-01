# foreglass

An explicit, bounded reader for the **existing public ForeGlass artifacts**. It retains their exact bytes and turns into `comuvia` records only what those artifacts declare.

Version 0.1.0 · Apache-2.0 · Python 3.11–3.13 · depends only on `comuvia>=0.1.0,<0.2` · no network request on import or construction.

There is no ForeGlass API server, MCP server or custom-forecast endpoint: the published files *are* the interface.

## Install

```sh
pip install foreglass
```

This also installs its only dependency, `comuvia`. Importing or constructing anything makes no network request.

## First steps, offline

Read a synthetic ForeGlass-format ledger from the [source repository](https://github.com/comuvia/comuvia-sdk), from its root:

```sh
git clone https://github.com/comuvia/comuvia-sdk
cd comuvia-sdk
```

```python
import pathlib
import foreglass

source = pathlib.Path("fixtures/synthetic/foreglass-ledger/source")
files = {
    "ledger": (source / "ledger.json").read_bytes(),
    "archive_index": (source / "ledger-archive-index.json").read_bytes(),
}
archive = foreglass.SnapshotArchive.create("./foreglass-snapshots")
result = archive.intake(foreglass.replay_bundle(files), declared_roles=list(files))
print(result.verified, result.accepted)     # True False: a replay is never accepted as live
report = foreglass.normalize(archive.load(result.snapshot_id), recorded_at="2026-09-25T00:00:00Z").report
print(report["mapped"]["questions"], report["mapped"]["forecasts"], report["evaluation"]["counts"]["eligible"])  # 7 8 0
```

[Tutorial C](https://github.com/comuvia/comuvia-sdk/blob/main/documentation/tutorials/C-reading-foreglass-honestly.md) walks through the same fixture and checks every value it states: `python documentation/tutorials/tutorial_c_foreglass.py --fixtures fixtures/synthetic --work ./tutorial-c`.

## Capabilities

| Capability | What it does | API |
|---|---|---|
| Explicit reads | Fetches only the documented artifacts: the verification ledger and its `.ots` proof, the ledger archive index and archive files named in it, and the fragility readings (`latest.json`, `countries.json`). https only; host and port allow-lists; at most 3 re-checked redirects; a 4 MiB streamed cap; connect/read timeouts and a total per-artifact deadline; a body shorter than its declared length is an incomplete response; at most 2 retries on network errors, 429 or 5xx, with `Retry-After` capped; no cookies, credentials or telemetry | `PublicClient`, `ARTIFACTS` |
| Exact-byte intake | Retains each artifact's exact bytes with URLs, status, fetch time, length and SHA-256. The accepted snapshot moves atomically only after verification. Every failure is named and leaves the accepted snapshot untouched. Replays are `synthetic` and never accepted as live | `SnapshotArchive`, `replay_bundle` |
| Lane catalog | A typed, read-only view with declared field meanings: `lo`/`hi` have no coverage level, `due` is a grading date, `sealed_at` has no time of day, and `built` is not a publication time. Truncation is flagged by a labelled length heuristic. Readings are never forecasts or probabilities | `LaneCatalog`, `Lane`, `FIELD_MEANINGS`, `read_reading` |
| Honest normalization | Binary lanes with a pinned `qid` become one `question` per `qid` and one `forecast` per lane. Provider text is used verbatim. The information cutoff, target period, deadlines, vintage, model version and any missing unit are explicit unknowns; `issued_at` has day precision; caveats and units are preserved. Interval, point and blank-`qid` lanes are not mapped, each with a named reason | `normalize` |
| Statement of scope | What is implemented and what is not | `capabilities()` |

**Not supported**, with no method for any of them: custom execution, MCP, submission or upload, outcome normalization, interval or point lanes, and OpenTimestamps proof verification.

## What to expect from the live artifacts

For the current public ledger shape, **0 forecasts are eligible** for scoring. The published file declares no information cutoff, target period or forecast deadline, so every mapped forecast is excluded by name (`missing_required_time`, `incomplete_question`, and others). This describes the published metadata, not forecast quality. A replay of the 2026-09-24 public ledger maps 78 forecasts in 11 questions: 299 interval and point lanes are not mapped, and 4 lanes have a blank `qid`.

```python
import datetime, foreglass

client = foreglass.PublicClient()                       # no request yet
bundle = client.fetch_bundle(["ledger", "archive_index"])   # explicit network reads
archive = foreglass.SnapshotArchive.create("./foreglass-snapshots")
result = archive.intake(bundle, declared_roles=["ledger", "archive_index"])
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
report = foreglass.normalize(archive.accepted(), recorded_at=now).report
print(report["mapped"], report["not_mapped"].keys(), report["evaluation"]["counts"])
```

## Provider fields and outcome keys

The publisher has not documented outcome field names; they were checked on 2026-09-24. Until it does:

- 0.1.0 recognizes a **provisional** list of likely outcome key names (`outcome`, `graded_at`, `resolved_value` and similar). It reports them as `outcome_normalization_unsupported` and never interprets them.
- Every other unknown lane or top-level field is reported as `unrecognized_provider_field` and kept verbatim in the lane's raw mapping.

Neither kind of finding is fatal, and nothing is inferred from either.

## Limitations

- **What is not verified.** Proofs (`.ots`) are retained as bytes and not verified, so timestamp assurance is `unavailable`. A digest proves byte identity only.
- **Question text.** It comes from the first lane of a `qid` that publishes both statement and criteria. If lanes differ, `text_varies_across_lanes` is recorded; nothing is merged.
- **Family ids** use a SHA-256 prefix of the provider's `gkey`. Question ids are an injective encoding of `qid`.
- **Timeout overshoot.** Reads are bounded by per-read timeouts and a total deadline. A single socket read can overshoot the deadline by at most the read timeout.

## Tests

The `tests/` directory in the source distribution runs offline against an installed pair of wheels, with `python -m unittest discover -s tests`. It uses a fake transport, a local TLS test server with a throwaway test CA (`tests/tls/`, test only), and a synthetic ForeGlass-format fixture.

## Source, issues and security

- Source, release checksums and build recipe: [github.com/comuvia/comuvia-sdk](https://github.com/comuvia/comuvia-sdk) ([`release/0.1.0`](https://github.com/comuvia/comuvia-sdk/tree/main/release/0.1.0))
- Issues: [github.com/comuvia/comuvia-sdk/issues](https://github.com/comuvia/comuvia-sdk/issues)
- Reporting a vulnerability: [SECURITY.md](https://github.com/comuvia/comuvia-sdk/blob/main/SECURITY.md)
