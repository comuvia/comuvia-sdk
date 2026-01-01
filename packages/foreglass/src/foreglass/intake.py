"""Exact-byte intake and the accepted snapshot.

Layout of a snapshot archive directory::

    foreglass-snapshots.json          marker {"format": "foreglass-snapshots/1"}
    snapshots/<snapshot_id>/manifest.json   canonical JSON: roles, URLs, status, fetched_at,
                                            byte length, sha256, content type, data origin
    snapshots/<snapshot_id>/<n>.bin         exact bytes of each role, never re-serialized
    accepted.json                     pointer to the accepted live snapshot, replaced atomically
    tmp/                              in-progress intake

A bundle is written to ``tmp/``, re-read and re-hashed, verified, and only then moved
into ``snapshots/``. The accepted pointer moves (temporary file, fsync, ``os.replace``)
only when every check passes and the bundle is a live read. Any failure leaves the
previously accepted snapshot untouched and is named. Replays of fixture bytes are
``data_origin: "synthetic"`` and are never accepted as the live snapshot.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from comuvia import Issue, RefusalError, canonicalize, parse_json

from . import reasons
from .catalog import KNOWN_LANE_FIELDS, KNOWN_TOP_LEVEL_FIELDS, OUTCOME_FIELD_NAMES
from .client import Artifact

ARCHIVE_FORMAT = "foreglass-snapshots/1"
LEDGER_SCHEMA = "foreglass.verification-ledger/v1"
MARKER = "foreglass-snapshots.json"
ACCEPTED = "accepted.json"


@dataclass(frozen=True)
class Finding:
    """A non-fatal drift observation (``unrecognized_provider_field`` and similar)."""

    code: str
    where: str
    field: str


@dataclass(frozen=True)
class IntakeResult:
    verified: bool
    accepted: bool
    snapshot_id: str | None
    issues: tuple[Issue, ...] = ()
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    manifest: Mapping
    artifacts: Mapping[str, Artifact] = field(repr=False)

    @property
    def data_origin(self) -> str:
        return self.manifest["data_origin"]


def replay_bundle(files: Mapping[str, bytes], *, fetched_at: str | None = None) -> dict[str, Artifact]:
    """Artifacts from fixture bytes. Always ``data_origin: "synthetic"``; no URL is claimed."""
    return {
        role: Artifact(role, bytes(data), None, None, None, fetched_at, None, data_origin="synthetic")
        for role, data in files.items()
    }


def _fsync_write(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def drift_findings(ledger: Mapping) -> list[Finding]:
    """Unknown top-level or lane fields (not fatal), and outcome keys (unsupported in 0.1)."""
    findings = [Finding(reasons.UNRECOGNIZED_PROVIDER_FIELD, "ledger", k) for k in ledger if k not in KNOWN_TOP_LEVEL_FIELDS]
    for lane in ledger.get("lanes", []) if isinstance(ledger.get("lanes"), list) else []:
        if not isinstance(lane, Mapping):
            continue
        where = f"lane:{lane.get('id')}"
        for key in lane:
            if key in OUTCOME_FIELD_NAMES:
                findings.append(Finding(reasons.OUTCOME_NORMALIZATION_UNSUPPORTED, where, key))
            elif key not in KNOWN_LANE_FIELDS:
                findings.append(Finding(reasons.UNRECOGNIZED_PROVIDER_FIELD, where, key))
    return findings


class SnapshotArchive:
    """Retained provider snapshots and the accepted live snapshot."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        try:
            info = parse_json((self.path / MARKER).read_bytes())
        except (OSError, RefusalError):
            raise RefusalError([Issue("", reasons.NOT_A_SNAPSHOT_ARCHIVE, f"{self.path} is not a snapshot archive")]) from None
        if not isinstance(info, dict) or info.get("format") != ARCHIVE_FORMAT:
            raise RefusalError([Issue("", reasons.NOT_A_SNAPSHOT_ARCHIVE, f"{self.path} has an unsupported format")])

    @classmethod
    def create(cls, path: str | os.PathLike) -> SnapshotArchive:
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise RefusalError([Issue("", reasons.NOT_A_SNAPSHOT_ARCHIVE, f"{root} is not empty")])
        (root / "snapshots").mkdir()
        (root / "tmp").mkdir()
        _fsync_write(root / MARKER, canonicalize({"format": ARCHIVE_FORMAT}))
        return cls(root)

    # ---- reads

    def accepted(self) -> Snapshot | None:
        """The accepted live snapshot, re-verified on read, or ``None``."""
        try:
            pointer = parse_json((self.path / ACCEPTED).read_bytes())
        except FileNotFoundError:
            return None
        snapshot = self.load(pointer["snapshot_id"])
        if "sha256:" + hashlib.sha256(canonicalize(snapshot.manifest)).hexdigest() != pointer["manifest_sha256"]:
            raise RefusalError([Issue("", reasons.DIGEST_MISMATCH, "accepted manifest does not match its pointer")])
        return snapshot

    def load(self, snapshot_id: str) -> Snapshot:
        folder = self.path / "snapshots" / snapshot_id
        manifest = parse_json((folder / "manifest.json").read_bytes())
        artifacts = {}
        for role, entry in manifest["roles"].items():
            data = (folder / entry["file"]).read_bytes()
            if "sha256:" + hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["byte_length"]:
                raise RefusalError([Issue(f"/roles/{role}", reasons.DIGEST_MISMATCH, "retained bytes changed")])
            artifacts[role] = Artifact(role, data, entry["request_url"], entry["final_url"], entry["status"],
                                       entry["fetched_at"], entry["content_type"], manifest["data_origin"])
        return Snapshot(snapshot_id, manifest, artifacts)

    # ---- intake

    def intake(self, bundle: Mapping[str, Artifact], *, declared_roles: Iterable[str] = ("ledger",)) -> IntakeResult:
        """Retain and verify a bundle; accept it only if it is a complete, verified live read."""
        declared = list(dict.fromkeys(["ledger", *declared_roles]))
        missing = [role for role in declared if role not in bundle]
        if missing:
            return IntakeResult(False, False, None, (Issue("", reasons.INCOMPLETE_INTAKE, f"missing declared roles {missing}"),))
        origins = {bundle[r].data_origin for r in declared}
        if len(origins) != 1 or not origins <= {"observed", "synthetic"}:
            return IntakeResult(False, False, None, (Issue("", reasons.INCOMPLETE_INTAKE, "roles mix live and replayed data"),))
        data_origin = origins.pop()

        work = self.path / "tmp" / uuid.uuid4().hex
        work.mkdir()
        try:
            roles = {}
            for number, role in enumerate(declared):
                artifact = bundle[role]
                name = f"{number}.bin"
                _fsync_write(work / name, artifact.data)
                reread = (work / name).read_bytes()
                digest = "sha256:" + hashlib.sha256(reread).hexdigest()
                if reread != artifact.data or digest != artifact.sha256:
                    return IntakeResult(False, False, None, (Issue(f"/roles/{role}", reasons.DIGEST_MISMATCH, "re-read bytes differ"),))
                if artifact.declared_sha256 is not None and digest != artifact.declared_sha256:
                    return IntakeResult(False, False, None, (
                        Issue(f"/roles/{role}", reasons.DIGEST_MISMATCH, f"bytes hash to {digest}, declared {artifact.declared_sha256}"),))
                roles[role] = {
                    "file": name, "request_url": artifact.request_url, "final_url": artifact.final_url,
                    "status": artifact.status, "fetched_at": artifact.fetched_at, "content_type": artifact.content_type,
                    "byte_length": len(reread), "sha256": "sha256:" + hashlib.sha256(reread).hexdigest(),
                }
            issues, findings = self._verify(bundle, declared)
            if issues:
                return IntakeResult(False, False, None, tuple(issues), tuple(findings))
            manifest = {"format": ARCHIVE_FORMAT, "data_origin": data_origin, "roles": roles}
            manifest_bytes = canonicalize(manifest)
            snapshot_id = "snap-" + hashlib.sha256(manifest_bytes).hexdigest()[:32]
            _fsync_write(work / "manifest.json", manifest_bytes)
            final = self.path / "snapshots" / snapshot_id
            if final.exists():
                # Same content already retained: re-verify it before anything points at it.
                try:
                    existing_manifest = (final / "manifest.json").read_bytes()
                    self.load(snapshot_id)
                except (OSError, RefusalError, KeyError):
                    existing_manifest = None
                if existing_manifest != manifest_bytes:
                    return IntakeResult(False, False, None, (Issue(
                        "/snapshots", reasons.DIGEST_MISMATCH, f"retained snapshot {snapshot_id} no longer verifies"),))
                shutil.rmtree(work)
            else:
                os.replace(work, final)
            if data_origin != "observed":
                return IntakeResult(True, False, snapshot_id,
                                    (Issue("", reasons.REPLAY_NOT_ACCEPTED, "replayed bytes are never the accepted live snapshot"),),
                                    tuple(findings))
            pointer = canonicalize({"snapshot_id": snapshot_id, "manifest_sha256": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()})
            temporary = self.path / "tmp" / f"accepted.{uuid.uuid4().hex}.tmp"
            _fsync_write(temporary, pointer)
            os.replace(temporary, self.path / ACCEPTED)
            return IntakeResult(True, True, snapshot_id, (), tuple(findings))
        finally:
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _verify(bundle: Mapping[str, Artifact], declared: list[str]) -> tuple[list[Issue], list[Finding]]:
        ledger_artifact = bundle["ledger"]
        try:
            ledger = parse_json(ledger_artifact.data)
        except RefusalError as error:
            codes = ", ".join(sorted(error.codes))
            return [Issue("/roles/ledger", reasons.PARSE_REFUSED, f"strict parser refused the ledger ({codes})")], []
        if not isinstance(ledger, dict) or ledger.get("_schema") != LEDGER_SCHEMA:
            found = ledger.get("_schema") if isinstance(ledger, dict) else None
            return [Issue("/roles/ledger/_schema", reasons.SCHEMA_MISMATCH, f"expected {LEDGER_SCHEMA}, found {found!r}")], []
        lanes, counts = ledger.get("lanes"), ledger.get("counts")
        if not isinstance(lanes, list) or not isinstance(counts, dict) or counts.get("included") != len(lanes):
            included = counts.get("included") if isinstance(counts, dict) else None
            return [Issue("/roles/ledger/counts/included", reasons.COUNTS_MISMATCH,
                          f"counts.included {included!r} but {len(lanes) if isinstance(lanes, list) else 'no'} lanes")], []
        if "archive_index" in declared:
            try:
                index = parse_json(bundle["archive_index"].data)
                listed = {entry.get("sha256") for entry in index.get("files", []) if isinstance(entry, dict)}
            except (RefusalError, AttributeError):
                listed = set()
            if ledger_artifact.sha256.removeprefix("sha256:") not in listed:
                return [Issue("/roles/archive_index", reasons.ARCHIVE_INDEX_MISMATCH, "archive index does not list the ledger's sha256")], []
        return [], drift_findings(ledger)
