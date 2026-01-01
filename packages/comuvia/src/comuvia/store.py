"""Single-writer, append-only record store in a directory the caller chooses.

Layout of a store directory::

    comuvia-store.json    store marker: {"format": "comuvia-store/1", "schema": "comuvia/0.1"}
    index.jsonl           append-only index; one canonical JSON line per stored record:
                          {"digest", "id", "record_type", "revision", "sequence"}
    records/<hex>.json    canonical RFC 8785 bytes of one record body, named by the 64 hex
                          digits of its record digest
    tmp/                  temporary files of in-progress writes
    writer.lock           persistent lock file, created with the store and never deleted;
                          holds the current writer's details while one is open

Records are never rewritten or deleted: there is no update or delete API, and a
correction is a successor revision. Views such as "latest revision per id" are derived at
read time.

Writer lock. ``writer.lock`` is created with the store and never deleted. A writer
(``RecordStore(path, writer=True)``) opens it and takes a non-blocking operating-system
lock on it (``fcntl.flock`` on POSIX; ``msvcrt.locking`` on one byte at a far offset on
Windows), then writes its pid, host and time into a fixed slot at the start of the file.
Only the OS lock decides: a second writer is refused as ``store_locked``, naming the
recorded holder. Closing blanks the details, unlocks and closes; it never deletes. If a
writer dies, the operating system releases its lock and the next writer proceeds; any
crash residue is guarded by the index-tail refusal and reported by ``verify``. Readers
never open the lock for locking: ``verify`` only reports the holder details last
written, and cannot tell whether that holder is alive.

Crash safety. An append writes the canonical body to ``tmp/``, flushes and fsyncs it,
renames it into ``records/`` with ``os.replace`` (and fsyncs the directory on POSIX), then
appends and fsyncs one index line. Guarantees relied on:

- POSIX: ``rename(2)`` atomically replaces the target within one file system; ``fsync``
  of the file and of its directory makes the data and the rename durable.
- Windows: ``os.replace`` uses ``MoveFileExW`` with ``MOVEFILE_REPLACE_EXISTING``, which
  NTFS performs as a single journaled metadata operation on one volume; ``os.fsync`` is
  ``FlushFileBuffers``. Directories cannot be fsynced; the rename's durability rests on
  NTFS metadata journaling.

A crash can therefore leave, at most, a temporary file, an orphan body (renamed but not
indexed) or a torn final index line. ``verify`` reports each by name; appends are
refused while the final index line is torn, until an operator truncates that incomplete
line (``truncate_torn_tail``). ``verify`` running while a writer is appending can report
that in-flight write (a temporary file or a not-yet-indexed body); re-run it after the
writer closes.

Identity, not correctness. ``verify`` checks that stored bytes match their digests and
that references resolve. It does not check that an evaluation's result is correct: a
forged but well-formed evaluation record is valid and stores. Run ``reproduce`` for any
stored evaluation you depend on.

Detection limit. ``verify`` cannot detect removal of complete index lines at the tail,
or replacement of the whole store, without an independently retained checkpoint.
Checkpoints are not part of 0.1.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import reasons
from .history import latest_revisions
from .identity import DIGEST_PATTERN, _references, canonicalize, parse_json, record_digest
from .issues import Issue, RefusalError
from .validation import validate

STORE_FORMAT = "comuvia-store/1"
MARKER = "comuvia-store.json"
INDEX = "index.jsonl"
RECORDS = "records"
TMP = "tmp"
LOCK = "writer.lock"
DETECTION_LIMIT = (
    "Removal of complete index lines at the tail, or replacement of the whole store, "
    "cannot be detected without an independently retained checkpoint; checkpoints are not part of 0.1."
)
_BODY_NAME = re.compile(r"[0-9a-f]{64}\.json\Z")
_ENTRY_KEYS = {"digest", "id", "record_type", "revision", "sequence"}
_LOCK_OFFSET = 1 << 30  # Windows locks a byte far past the holder details so they stay readable.
_HOLDER_SLOT = 1024  # fixed-size, space-padded holder details at the start of writer.lock


@dataclass(frozen=True)
class StoreEntry:
    sequence: int
    record_type: str
    id: str
    revision: int
    digest: str
    appended: bool = True

    def as_index(self) -> dict:
        return {
            "sequence": self.sequence,
            "record_type": self.record_type,
            "id": self.id,
            "revision": self.revision,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class StoreReport:
    """Result of ``RecordStore.verify``; ``ok`` means no issue was found."""

    entries: int
    bodies: int
    lock_holder: str | None  # holder details last written; a reader cannot tell if that holder is alive
    issues: tuple[Issue, ...]
    detection_limit: str = field(default=DETECTION_LIMIT)

    @property
    def ok(self) -> bool:
        return not self.issues


# ------------------------------------------------------------------ file helpers


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_durably(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _refuse(code: str, message: str, pointer: str = "") -> RefusalError:
    return RefusalError([Issue(pointer, code, message)])


# ------------------------------------------------------------------ writer lock


def _host_name() -> str:
    """Host name for lock-holder details, without the socket module (no network facility)."""
    if hasattr(os, "uname"):
        return os.uname().nodename
    return os.environ.get("COMPUTERNAME", "unknown")


def _os_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _os_unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _holder_text(data: bytes) -> str | None:
    try:
        details = json.loads(data.strip() or b"null")
    except ValueError:
        return "unreadable holder details"
    if not isinstance(details, dict):
        return None
    return ", ".join(f"{k}={details[k]}" for k in ("pid", "host", "acquired_at") if k in details) or None


def recorded_holder(lock_path: Path) -> str | None:
    """Holder details last written by a writer, or ``None``. Never takes a lock.

    A reader cannot tell whether that holder is still alive: details can remain after a
    writer process died (the operating system has then released its lock).
    """
    try:
        with open(lock_path, "rb") as handle:
            return _holder_text(handle.read(_HOLDER_SLOT))
    except FileNotFoundError:
        return None


def _write_holder(fd: int, details: dict | None) -> None:
    text = b"" if details is None else json.dumps(details, sort_keys=True).encode("ascii")
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, text[:_HOLDER_SLOT].ljust(_HOLDER_SLOT, b" "))


def _acquire(lock_path: Path) -> int:
    """Open the persistent lock file and take its OS lock, or refuse as ``store_locked``."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
    if not _os_lock(fd):
        os.close(fd)
        holder = recorded_holder(lock_path) or "holder details not yet written"
        raise _refuse(reasons.STORE_LOCKED, f"another writer holds the store ({holder})")
    try:
        _write_holder(fd, {
            "pid": os.getpid(),
            "host": _host_name(),
            "acquired_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "token": uuid.uuid4().hex,
        })
        os.fsync(fd)
    except BaseException:
        _os_unlock(fd)
        os.close(fd)
        raise
    return fd


def _release(fd: int) -> None:
    """Blank the holder details, unlock and close. The lock file itself stays."""
    try:
        _write_holder(fd, None)
    except OSError:
        pass  # stale details are harmless: the OS lock, not the text, decides
    try:
        _os_unlock(fd)
    finally:
        os.close(fd)


# ------------------------------------------------------------------ store


class RecordStore:
    """An append-only store of comuvia records. Open with ``writer=True`` to append."""

    def __init__(self, path: str | os.PathLike, *, writer: bool = False):
        self.path = Path(path)
        marker = self.path / MARKER
        try:
            info = parse_json(marker.read_bytes())
        except (OSError, RefusalError):
            raise _refuse(reasons.NOT_A_STORE, f"{self.path} is not a comuvia store") from None
        if not isinstance(info, dict) or info.get("format") != STORE_FORMAT:
            raise _refuse(reasons.NOT_A_STORE, f"{self.path} has an unsupported store format")
        self._lock_fd: int | None = None
        self._entries: list[StoreEntry] | None = None
        if writer:
            self._lock_fd = _acquire(self.path / LOCK)
            try:
                self._entries = list(self._read_index()[0])
            except BaseException:
                self.close()
                raise

    # ---- lifecycle

    @classmethod
    def create(cls, path: str | os.PathLike) -> RecordStore:
        """Create an empty store at ``path`` (a new or empty directory)."""
        root = Path(path)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise _refuse(reasons.STORE_EXISTS, f"{root} exists and is not an empty directory")
        root.mkdir(parents=True, exist_ok=True)
        (root / RECORDS).mkdir()
        (root / TMP).mkdir()
        _write_durably(root / INDEX, b"")
        _write_durably(root / LOCK, b"")
        _write_durably(root / MARKER, canonicalize({"format": STORE_FORMAT, "schema": "comuvia/0.1"}))
        _fsync_directory(root)
        return cls(root)

    def close(self) -> None:
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            _release(fd)

    def __enter__(self) -> RecordStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_writer(self) -> bool:
        return self._lock_fd is not None

    # ---- index

    def _read_index(self) -> tuple[list[StoreEntry], bytes, list[Issue]]:
        """Complete entries, the torn tail (b"" if none) and issues with complete lines."""
        data = (self.path / INDEX).read_bytes()
        complete, _, tail = data.rpartition(b"\n")
        if not complete and not data.endswith(b"\n"):
            complete, tail = b"", data
        entries, problems = [], []
        for number, line in enumerate(complete.split(b"\n") if complete else [], start=1):
            try:
                raw = parse_json(line)
                if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS or canonicalize(raw) != line:
                    raise ValueError("not a canonical index entry")
                if not isinstance(raw["digest"], str) or not DIGEST_PATTERN.match(raw["digest"]):
                    raise ValueError("index entry digest is not 'sha256:' and 64 lowercase hex digits")
                entries.append(StoreEntry(raw["sequence"], raw["record_type"], raw["id"], raw["revision"], raw["digest"]))
            except (RefusalError, ValueError) as error:
                problems.append(Issue(f"{INDEX}:{number}", reasons.INDEX_ENTRY_INVALID, str(error)))
        return entries, tail, problems

    def entries(self) -> tuple[StoreEntry, ...]:
        """Index entries in sequence order (a torn final line is not an entry)."""
        return tuple(self._entries if self._entries is not None else self._read_index()[0])

    # ---- reads

    def _body_path(self, digest: str) -> Path:
        if not isinstance(digest, str) or not DIGEST_PATTERN.match(digest):
            raise _refuse(reasons.MALFORMED_DIGEST, "expected 'sha256:' and 64 lowercase hex digits")
        return self.path / RECORDS / f"{digest.removeprefix('sha256:')}.json"

    def get_by_digest(self, digest: str) -> dict | None:
        """The stored body with this record digest, or ``None``. A tampered body is refused.

        The digest text is validated before any path is built, so it cannot name a file
        outside ``records/``.
        """
        path = self._body_path(digest)  # refuses malformed digest text before any file access
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
            raise _refuse(reasons.BODY_DIGEST_MISMATCH, f"stored body for {digest} does not match its digest")
        return parse_json(data)

    def get(self, record_type: str, record_id: str, revision: int | None = None) -> dict | None:
        """One revision of a record; the latest if ``revision`` is ``None``."""
        matches = [e for e in self.entries() if e.record_type == record_type and e.id == record_id]
        if revision is not None:
            matches = [e for e in matches if e.revision == revision]
        if not matches:
            return None
        return self.get_by_digest(max(matches, key=lambda e: e.revision).digest)

    def records(self) -> list[dict]:
        """Every stored body, all revisions, in sequence order."""
        seen, bodies = set(), []
        for entry in self.entries():
            if entry.digest not in seen:
                seen.add(entry.digest)
                body = self.get_by_digest(entry.digest)
                if body is not None:
                    bodies.append(body)
        return bodies

    def latest(self) -> dict[tuple[str, str], dict]:
        """The latest revision per (record type, id), derived at read time."""
        return dict(latest_revisions(self.records()))

    # ---- append

    def append(self, body: Mapping) -> StoreEntry:
        """Append one record body. Re-appending an identical body is a no-op."""
        if self._lock_fd is None or self._entries is None:
            raise _refuse(reasons.READ_ONLY_STORE, "open the store with writer=True to append")
        if self._read_index()[1]:
            raise _refuse(reasons.INDEX_TORN, "the final index line is incomplete; an operator must run truncate_torn_tail")
        issues = validate(body)
        if issues:
            raise RefusalError(issues)
        digest = record_digest(body)
        key = (body["record_type"], body["id"], body["revision"])
        by_key = {(e.record_type, e.id, e.revision): e for e in self._entries}
        existing = by_key.get(key)
        if existing is not None:
            if existing.digest == digest:
                return StoreEntry(existing.sequence, *key, digest, appended=False)
            raise _refuse(reasons.REVISION_CONFLICT, f"{key[0]} {key[1]!r} revision {key[2]} is stored with a different digest")
        problems = []
        for pointer, ref in _references(body):
            target = by_key.get((ref["record_type"], ref["id"], ref["revision"]))
            if target is None:
                problems.append(Issue(pointer, reasons.UNRESOLVED_REFERENCE, "referenced record is not in the store"))
            elif target.digest != ref["digest"]:
                problems.append(Issue(pointer, reasons.REFERENCE_DIGEST_MISMATCH, "stored target has a different digest"))
        if problems:
            raise RefusalError(problems)

        data = canonicalize(body)
        final = self._body_path(digest)
        temporary = self.path / TMP / f"{final.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        _write_durably(temporary, data)
        os.replace(temporary, final)
        _fsync_directory(final.parent)

        entry = StoreEntry((self._entries[-1].sequence if self._entries else 0) + 1, *key, digest)
        with open(self.path / INDEX, "ab") as index:
            index.write(canonicalize(entry.as_index()) + b"\n")
            index.flush()
            os.fsync(index.fileno())
        self._entries.append(entry)
        return entry

    def truncate_torn_tail(self) -> int:
        """Operator action: remove an incomplete final index line. Returns bytes removed.

        Only bytes after the last newline are removed; complete index lines are never touched.
        """
        if self._lock_fd is None:
            raise _refuse(reasons.READ_ONLY_STORE, "open the store with writer=True to repair it")
        tail = self._read_index()[1]
        if tail:
            index = self.path / INDEX
            with open(index, "r+b") as handle:
                handle.truncate(index.stat().st_size - len(tail))
                handle.flush()
                os.fsync(handle.fileno())
        return len(tail)

    # ---- verification

    def verify(self) -> StoreReport:
        """Check the index and bodies; every problem is reported by name. Nothing is modified."""
        listed = sorted((self.path / RECORDS).iterdir())  # listed before the index is read
        entries, tail, issues = self._read_index()
        if tail:
            issues.append(Issue(INDEX, reasons.TORN_INDEX_LINE, f"final index line is incomplete ({len(tail)} bytes)"))
        seen_keys: dict[tuple, int] = {}
        seen_digests: dict[str, int] = {}
        expected_sequence = 1
        stored: dict[tuple, str] = {}
        for entry in entries:
            where = f"{INDEX}:seq={entry.sequence}"
            if entry.sequence != expected_sequence:
                issues.append(Issue(where, reasons.INDEX_SEQUENCE_GAP, f"expected sequence {expected_sequence}"))
            expected_sequence = entry.sequence + 1
            key = (entry.record_type, entry.id, entry.revision)
            if key in seen_keys or entry.digest in seen_digests:
                issues.append(Issue(where, reasons.DUPLICATE_INDEX_ENTRY, f"{key} or its digest is already indexed"))
            seen_keys.setdefault(key, entry.sequence)
            seen_digests.setdefault(entry.digest, entry.sequence)
            stored[key] = entry.digest
            path = self._body_path(entry.digest)
            if not path.exists():
                issues.append(Issue(where, reasons.MISSING_BODY, f"no body file for {entry.digest}"))
                continue
            data = path.read_bytes()
            if "sha256:" + hashlib.sha256(data).hexdigest() != entry.digest:
                issues.append(Issue(f"{RECORDS}/{path.name}", reasons.BODY_DIGEST_MISMATCH, "body bytes do not match their digest (tampered)"))
                continue
            body = parse_json(data)
            if (body.get("record_type"), body.get("id"), body.get("revision")) != key:
                issues.append(Issue(where, reasons.INDEX_ENTRY_MISMATCH, "index entry names a different record"))
        for entry in entries:
            path = self._body_path(entry.digest)
            if not path.exists():
                continue
            data = path.read_bytes()
            if "sha256:" + hashlib.sha256(data).hexdigest() != entry.digest:
                continue
            for pointer, ref in _references(parse_json(data)):
                target = stored.get((ref["record_type"], ref["id"], ref["revision"]))
                where = f"{RECORDS}/{path.name}#{pointer}"
                if target is None:
                    issues.append(Issue(where, reasons.UNRESOLVED_REFERENCE, "referenced record is not indexed"))
                elif target != ref["digest"]:
                    issues.append(Issue(where, reasons.REFERENCE_DIGEST_MISMATCH, "indexed target has a different digest"))
        bodies = 0
        for path in listed:
            if not _BODY_NAME.match(path.name):
                issues.append(Issue(f"{RECORDS}/{path.name}", reasons.UNEXPECTED_FILE, "not a record body file"))
                continue
            bodies += 1
            if "sha256:" + path.stem not in seen_digests:
                issues.append(Issue(f"{RECORDS}/{path.name}", reasons.ORPHAN_BODY, "body file has no index entry"))
        for path in sorted((self.path / TMP).iterdir()):
            issues.append(Issue(f"{TMP}/{path.name}", reasons.LEFTOVER_TEMP_FILE, "left by an interrupted write"))
        return StoreReport(len(entries), bodies, recorded_holder(self.path / LOCK), tuple(sorted(issues)))
