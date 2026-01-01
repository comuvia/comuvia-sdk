# Record store

Status: IMPLEMENTED in OSS-1B (`comuvia.RecordStore`, `comuvia store …`). Format `comuvia-store/1`.
Last updated: 2026-09-24, US Eastern time

The store keeps `comuvia/0.1` records offline, in a directory the caller chooses, never inside package resources. It has one writer at a time, only ever appends, and makes every problem visible by name. Records are never rewritten or deleted. A correction is a successor revision whose `predecessor` references the corrected revision by digest.

## Layout

| Path | Content |
|---|---|
| `comuvia-store.json` | Store marker, in canonical JSON: `{"format": "comuvia-store/1", "schema": "comuvia/0.1"}` |
| `index.jsonl` | Append-only index with one canonical JSON line per stored record: `{"digest", "id", "record_type", "revision", "sequence"}`. Sequence numbers start at 1 and have no gaps |
| `records/<hex>.json` | The RFC 8785 canonical bytes of one record body, named by the 64 hex digits of its record digest, so the file's SHA-256 is its name |
| `tmp/` | Temporary files of in-progress writes; empty when no write is interrupted |
| `writer.lock` | Persistent lock file, created with the store and never deleted. While a writer is open, a fixed 1024-byte slot at its start holds that writer's pid, host and acquisition time; the slot is blanked when the writer closes |

Reads are derived views and mutate nothing:

- `records()`: every revision, in sequence order;
- `latest()`: the highest revision per record type and id;
- `get(type, id, revision)`;
- `get_by_digest(digest)`.

A read refuses a body whose bytes do not match its digest.

## One writer

`RecordStore(path, writer=True)` opens the persistent `writer.lock` and takes a non-blocking operating-system lock on it: `fcntl.flock` on POSIX, and `msvcrt.locking` on one byte at a far offset on Windows. It holds that lock for as long as the writer stays open. Only the OS lock decides who writes; the file's existence and its text do not. This design was adopted in OSS-1B correction C1.

- **A live holder:** a second writer, in any process, is refused as `store_locked`. The refusal names the holder details that writer recorded.
- **Closing** blanks the holder details, unlocks and closes the file. It never deletes the file, so closing cannot fail because another process has the file open.
- **A writer that dies:** the operating system releases its lock, and the next writer proceeds. There is no stale-lock state and no break-lock operation. The index-tail refusal (`index_torn`) and `verify` guard any residue of an interrupted append.
- **Readers** never lock, block or modify `writer.lock`. `verify` only reads the holder details last written, and a reader cannot tell whether that holder is still alive.
- **Tested** with a reader thread and a separate reader process running `comuvia store verify` in a loop, each concurrent with 300 writer open/close cycles, on Windows and Linux. There were no close errors, no writer refusals and no residue.

## Append

`append(body)` refuses, with named codes:

- any validation refusal;
- a reference or predecessor that is not in the store (`unresolved_reference`), or whose stored target has a different digest (`reference_digest_mismatch`);
- a (record type, id, revision) already stored with a different digest (`revision_conflict`).

Re-appending an identical body is idempotent: it returns the existing entry and writes nothing.

Write order:

1. Write the canonical body to `tmp/`, then flush and fsync it.
2. `os.replace` it into `records/`. On POSIX, also fsync the directory.
3. Append one index line, then flush and fsync it.

These steps rely on the following:

- **POSIX:** `rename(2)` atomically replaces its target within one file system. `fsync` of the file and of its directory makes the data and the rename durable.
- **Windows:** `os.replace` is `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`, which NTFS performs as one journaled metadata operation on a single volume. `os.fsync` is `FlushFileBuffers`. Directories cannot be fsynced, so the rename's durability rests on NTFS metadata journaling.

A crash can therefore leave, at most:

- a temporary file;
- an orphan body (renamed, not indexed);
- an incomplete final index line.

Appends are refused as `index_torn` while the final index line is incomplete. `truncate_torn_tail` (CLI: `comuvia store repair DIR --truncate-torn-tail --confirm`) removes only the bytes after the last newline; complete lines are never touched. Re-appending the record then re-indexes an orphan body.

## Verification

`verify()` (CLI: `comuvia store verify DIR`) modifies nothing. It reports each problem by name:

| Code | Meaning |
|---|---|
| `torn_index_line` | The final index line is incomplete |
| `index_entry_invalid` | A complete index line is not a canonical entry |
| `index_sequence_gap` | Sequence numbers skip or repeat, for example after a line was removed from the middle |
| `duplicate_index_entry` | A (type, id, revision) or a digest is indexed twice |
| `missing_body` | An index entry has no body file |
| `body_digest_mismatch` | A body's bytes do not hash to its digest: the body was tampered with |
| `index_entry_mismatch` | An entry names a different record than its body holds |
| `orphan_body` | A body file has no index entry |
| `unresolved_reference`, `reference_digest_mismatch` | A stored body's reference does not resolve to the indexed target |
| `unexpected_file`, `leftover_temp_file` | Other files in `records/` or `tmp/` |

It also reports the writer details last recorded in `writer.lock`, if any.

**Identity, not correctness.** `verify` checks that stored bytes match their digests and that references resolve. It does not check whether a stored evaluation's result is correct: a forged but well-formed evaluation record is valid and stores. Run `comuvia reproduce` (or `comuvia.reproduce`) for any stored evaluation you depend on; it re-derives the result from the pinned inputs and reports `mismatch`.

**While a writer appends.** `verify` running during an append can report that in-flight write as a temporary file or a not-yet-indexed body. Run it again after the writer closes.

**Detection limit.** Removal of complete index lines at the tail, or replacement of the whole store, cannot be detected without an independently retained checkpoint. Checkpoints are not part of 0.1. `verify` states this limit in every report.
