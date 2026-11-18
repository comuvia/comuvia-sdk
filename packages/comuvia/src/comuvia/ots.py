"""Offline, provider-neutral OpenTimestamps detached proof parser.

``parse_proof`` reads an ``.ots`` proof's header, digest, bounded operation tree and
attestations (Bitcoin, Litecoin, Ethereum block-header heights and pending calendar URIs),
computing the commitment message at each attestation leaf.

No block chain, calendar or network endpoint is ever contacted. Parsing a proof checks what
bytes and attestations the file declares; it never establishes independent Bitcoin chain
inclusion or timestamp assurance (``timestamp_assurance`` in ``comuvia`` records remains
``"unavailable"``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import reasons
from .identity import content_digest, digest_issue
from .issues import Issue

OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
OTS_VERSION = 1
_CRYPT_OPS = {0x02: ("sha1", 20), 0x03: ("ripemd160", 20), 0x08: ("sha256", 32), 0x67: ("keccak256", 32)}
_BINARY_OPS = {0xF0: "append", 0xF1: "prepend"}
_UNARY_OPS = {0xF2: "reverse", 0xF3: "hexlify"}
ATTESTATION_TAGS = {
    bytes.fromhex("0588960d73d71901"): "bitcoin",
    bytes.fromhex("83dfe30d2ef90c8e"): "pending",
    bytes.fromhex("06869a0d73d71b45"): "litecoin",
    bytes.fromhex("30fe8087b5c7ead7"): "ethereum",
}
_MAX_MESSAGE = 4096
_MAX_PAYLOAD = 8192
_MAX_URI = 1000
_MAX_DEPTH = 256
_MAX_ATTESTATIONS = 1024


class ProofError(ValueError):
    """The bytes are not a well-formed OpenTimestamps detached proof."""


@dataclass(frozen=True)
class Attestation:
    kind: str                 # bitcoin | litecoin | ethereum | pending | unknown
    tag: str                  # the 8-byte tag, hex
    height: int | None        # block height for block-header attestations
    uri: str | None           # the calendar URI of a pending attestation
    payload: str              # the raw payload, hex (unknown tags)
    result: bytes | None      # the message at the attestation (None if an op was not computable)

    def describe(self) -> str:
        if self.kind in ("bitcoin", "litecoin", "ethereum"):
            text = f"{self.kind} block {self.height}"
            if self.result is not None and len(self.result) == 32:
                text += f" (merkle root {self.result[::-1].hex()}, in the byte order block explorers display)"
            elif self.result is None:
                text += " (commitment not computed: an operation is unavailable here)"
            else:
                text += f" (commitment is {len(self.result)} bytes, not a 32-byte merkle root)"
            return text
        if self.kind == "pending":
            return f"pending at calendar {self.uri}"
        return f"unknown attestation tag {self.tag} ({len(self.payload) // 2} payload bytes)"


@dataclass(frozen=True)
class Proof:
    digest_type: str          # sha256 | sha1 | ripemd160 | keccak256
    digest: str               # hex, the digest the proof commits to
    attestations: tuple[Attestation, ...]
    operations: int


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = bytes(data), 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ProofError("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def byte(self) -> int:
        return self.take(1)[0]

    def varuint(self) -> int:
        value, shift = 0, 0
        for _ in range(10):
            b = self.byte()
            value |= (b & 0x7F) << shift
            if not b & 0x80:
                return value
            shift += 7
        raise ProofError("varuint longer than 10 bytes")

    def varbytes(self, limit: int) -> bytes:
        length = self.varuint()
        if length > limit:
            raise ProofError(f"length {length} exceeds {limit}")
        return self.take(length)

    @property
    def done(self) -> bool:
        return self.pos == len(self.data)


def _digest_function(name: str):
    if name in ("sha1", "sha256"):
        return lambda data: hashlib.new(name, data).digest()
    if name == "ripemd160":
        try:
            hashlib.new("ripemd160", b"")
        except ValueError:
            return None
        return lambda data: hashlib.new("ripemd160", data).digest()
    return None  # keccak256 is not in hashlib


def _apply(tag: int, reader: _Reader, message: bytes | None) -> bytes | None:
    """Read an op's argument (if any) and apply it to ``message``; None once an op is unavailable."""
    if tag in _BINARY_OPS:
        argument = reader.varbytes(_MAX_MESSAGE)
        if message is None:
            return None
        result = message + argument if _BINARY_OPS[tag] == "append" else argument + message
    elif tag in _UNARY_OPS:
        if message is None:
            return None
        if _UNARY_OPS[tag] == "reverse":
            if not message:
                raise ProofError("reverse of an empty message")
            result = message[::-1]
        else:
            result = message.hex().encode("ascii")
    elif tag in _CRYPT_OPS:
        if message is None:
            return None
        function = _digest_function(_CRYPT_OPS[tag][0])
        return None if function is None else function(message)
    else:
        raise ProofError(f"unknown op tag 0x{tag:02x}")
    if len(result) > _MAX_MESSAGE:
        raise ProofError("message longer than 4096 bytes")
    return result


def _attestation(reader: _Reader, message: bytes | None) -> Attestation:
    tag = reader.take(8)
    payload = reader.varbytes(_MAX_PAYLOAD)
    kind = ATTESTATION_TAGS.get(tag, "unknown")
    height = uri = None
    if kind in ("bitcoin", "litecoin", "ethereum"):
        inner = _Reader(payload)
        height = inner.varuint()
        if not inner.done:
            raise ProofError(f"{kind} attestation payload has trailing bytes")
    elif kind == "pending":
        inner = _Reader(payload)
        raw = inner.varbytes(_MAX_URI)
        if not inner.done:
            raise ProofError("pending attestation payload has trailing bytes")
        try:
            uri = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProofError("pending attestation URI is not UTF-8") from error
    return Attestation(kind, tag.hex(), height, uri, payload.hex(), message)


def _timestamp(reader: _Reader, message: bytes | None, out: list, counter: list, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise ProofError(f"nesting deeper than {_MAX_DEPTH}")

    def tag_or_attestation(tag: int) -> None:
        if tag == 0x00:
            if len(out) >= _MAX_ATTESTATIONS:
                raise ProofError(f"more than {_MAX_ATTESTATIONS} attestations")
            out.append(_attestation(reader, message))
            return
        counter[0] += 1
        _timestamp(reader, _apply(tag, reader, message), out, counter, depth + 1)

    tag = reader.byte()
    while tag == 0xFF:
        tag_or_attestation(reader.byte())
        tag = reader.byte()
    tag_or_attestation(tag)


def parse_proof(data: bytes) -> Proof:
    """Parse an OpenTimestamps detached proof: header, digest, operations and attestations.

    Every operation is applied to the digest, so each attestation carries the message it
    commits to (for a Bitcoin attestation, the block's merkle root). Nothing is verified
    against any block chain or calendar. ``ProofError`` names any malformation.
    """
    reader = _Reader(data)
    if reader.take(len(OTS_MAGIC)) != OTS_MAGIC:
        raise ProofError("magic bytes are not an OpenTimestamps proof header")
    version = reader.varuint()
    if version != OTS_VERSION:
        raise ProofError(f"unsupported proof version {version}")
    tag = reader.byte()
    if tag not in _CRYPT_OPS:
        raise ProofError(f"unknown digest type 0x{tag:02x}")
    name, length = _CRYPT_OPS[tag]
    digest = reader.take(length)
    attestations: list[Attestation] = []
    counter = [0]
    _timestamp(reader, digest, attestations, counter, 0)
    if not reader.done:
        raise ProofError(f"{len(reader.data) - reader.pos} trailing bytes after the proof")
    return Proof(name, digest.hex(), tuple(attestations), counter[0])


def check_proof_digest(
    proof: Proof,
    *,
    content: bytes | None = None,
    expected_digest: str | None = None,
) -> list[Issue]:
    """Compare ``proof``'s committed SHA-256 digest against ``content`` and/or ``expected_digest``.

    Never verifies block-header or calendar attestations; only checks the initial digest commitment.
    """
    issues: list[Issue] = []
    if proof.digest_type != "sha256":
        issues.append(Issue("/ots", reasons.UNSUPPORTED_DIGEST_ALGORITHM, f"proof commits to {proof.digest_type}, expected sha256"))
        return issues
    committed = f"sha256:{proof.digest}"
    if expected_digest is not None:
        bad = digest_issue(expected_digest, "/expected_digest")
        if bad is not None:
            issues.append(bad)
        elif committed != expected_digest:
            issues.append(Issue("/ots", reasons.PROOF_DIGEST_MISMATCH, f"proof commits to {committed}, expected {expected_digest}"))
    if content is not None:
        actual = content_digest(content)
        if committed != actual:
            issues.append(Issue("/ots", reasons.PROOF_DIGEST_MISMATCH, f"proof commits to {committed}, content digest is {actual}"))
    return sorted(issues)


__all__ = [
    "ATTESTATION_TAGS",
    "Attestation",
    "OTS_MAGIC",
    "OTS_VERSION",
    "Proof",
    "ProofError",
    "check_proof_digest",
    "parse_proof",
]
