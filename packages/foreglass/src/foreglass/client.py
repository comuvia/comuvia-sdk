"""Explicit, bounded reader for the published ForeGlass artifacts.

Nothing is fetched on import or construction. Only the documented artifacts can be
fetched; there is no arbitrary-URL fetch, and a locator stored in a record is never
dereferenced. Transport rules: https only; hosts limited to an explicit allow-list; at
most ``max_redirects`` redirects, each hop re-checked; a streamed size cap; connect and
read timeouts and a total per-artifact deadline; a body shorter than its declared length is
an incomplete response; at most ``max_retries`` retries, only on network errors, incomplete
responses, 429 or 5xx, with bounded backoff and ``Retry-After`` honoured up to a cap; no cookies, credentials or
telemetry; ``Accept-Encoding: identity`` so the retained bytes are the bytes served.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import email.utils
import hashlib
import re
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from comuvia import Issue, RefusalError

from . import __version__, reasons

DEFAULT_ORIGIN = "https://foreglass.ai"
DEFAULT_ALLOWED_HOSTS = ("foreglass.ai", "www.foreglass.ai")
ARTIFACTS = {
    "ledger": "/verification-explorer/ledger.json",
    "ledger_ots": "/verification-explorer/ledger.json.ots",
    "archive_index": "/verification-explorer/ledger-archive/index.json",
    "fragility_latest": "/readings/fragility/latest.json",
    "fragility_countries": "/readings/fragility/countries.json",
}
ARCHIVE_DIRECTORY = "/verification-explorer/ledger-archive/"
_ARCHIVE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REDIRECTS = {301, 302, 303, 307, 308}
USER_AGENT = f"foreglass-python/{__version__} (comuvia SDK; explicit reads only)"


class Response(Protocol):
    status: int
    headers: Mapping[str, str]  # lower-case names

    def read(self, size: int) -> bytes: ...

    def close(self) -> None: ...


class Transport(Protocol):
    def request(self, url: str, *, headers: Mapping[str, str], connect_timeout: float, read_timeout: float) -> Response: ...


class _HttpResponse:
    def __init__(self, connection, response):
        self._connection, self._response = connection, response
        self.status = response.status
        self.headers = {k.lower(): v for k, v in response.getheaders()}

    def read(self, size: int) -> bytes:
        # read1 returns what one socket read delivers (at most one read timeout), so the
        # client's total deadline is checked between reads; read(size) would block until
        # ``size`` bytes or the declared length arrive, however slowly they drip.
        return self._response.read1(size)

    def close(self) -> None:
        self._response.close()
        self._connection.close()


class HttpsTransport:
    """Default transport: one standard-library HTTPS request per call, no redirects followed.

    ``context`` defaults to ``ssl.create_default_context()`` (certificate and host-name
    verification on). Passing another context exists for tests against a local server.
    """

    def __init__(self, context=None):
        self._context = context

    def request(self, url: str, *, headers: Mapping[str, str], connect_timeout: float, read_timeout: float) -> Response:
        import http.client
        import ssl

        parts = urllib.parse.urlsplit(url)
        connection = http.client.HTTPSConnection(
            parts.hostname, parts.port or 443, timeout=connect_timeout, context=self._context or ssl.create_default_context()
        )
        try:
            connection.connect()
            connection.sock.settimeout(read_timeout)
            target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            connection.request("GET", target, headers=dict(headers))
            return _HttpResponse(connection, connection.getresponse())
        except BaseException:
            connection.close()
            raise


@dataclass(frozen=True)
class Artifact:
    """One retained artifact: exact bytes plus where and when they came from."""

    role: str
    data: bytes = field(repr=False)
    request_url: str | None
    final_url: str | None
    status: int | None
    fetched_at: str | None
    content_type: str | None
    data_origin: str = "observed"  # "observed" for live reads, "synthetic" for replays
    declared_sha256: str | None = None  # a digest the bytes must match (e.g. from the archive index)

    @property
    def byte_length(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.data).hexdigest()


class _Retryable(Exception):
    def __init__(self, issue: Issue, retry_after: float | None = None):
        self.issue, self.retry_after = issue, retry_after


def _refuse(code: str, message: str, pointer: str = "") -> RefusalError:
    return RefusalError([Issue(pointer, code, message)])


def _retry_after_seconds(value: str | None, now: float) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, moment.timestamp() - now)


class PublicClient:
    """Reads the documented public ForeGlass artifacts, explicitly and within bounds."""

    def __init__(
        self,
        *,
        origin: str = DEFAULT_ORIGIN,
        allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS,
        allowed_ports: Iterable[int] = (443,),
        transport: Transport | None = None,
        max_bytes: int = 4 * 1024 * 1024,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        total_timeout: float = 120.0,
        max_redirects: int = 3,
        max_retries: int = 2,
        backoff_base: float = 1.0,
        backoff_max: float = 8.0,
        retry_after_cap: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self.allowed_ports = frozenset(allowed_ports)
        self.origin = origin.rstrip("/")
        self._check_url(self.origin, reasons.INSECURE_URL, reasons.HOST_NOT_ALLOWED)
        self.transport = transport if transport is not None else HttpsTransport()
        self.max_bytes, self.max_redirects, self.max_retries = max_bytes, max_redirects, max_retries
        self.connect_timeout, self.read_timeout = connect_timeout, read_timeout
        self.backoff_base, self.backoff_max, self.retry_after_cap = backoff_base, backoff_max, retry_after_cap
        self.total_timeout = total_timeout
        self._sleep, self._clock, self._monotonic = sleep, clock, monotonic

    # ---- public reads

    def url_for(self, role: str) -> str:
        if role not in ARTIFACTS:
            raise _refuse(reasons.UNKNOWN_ARTIFACT, f"{role!r} is not a documented artifact; choose from {sorted(ARTIFACTS)}")
        return self.origin + ARTIFACTS[role]

    def fetch(self, role: str) -> Artifact:
        """Fetch one documented artifact by role (see ``ARTIFACTS``)."""
        return self._get(role, self.url_for(role))

    def fetch_bundle(self, roles: Iterable[str] = ("ledger",)) -> dict[str, Artifact]:
        return {role: self.fetch(role) for role in roles}

    def fetch_archive_file(self, entry: Mapping, *, proof: bool = False) -> Artifact:
        """Fetch a dated archive file named in the archive index (or its ``.ots`` proof).

        The archive file must match the ``bytes`` and ``sha256`` its index entry declares.
        """
        name = entry.get("ots") if proof else entry.get("file")
        if not isinstance(name, str) or not _ARCHIVE_NAME.match(name):
            raise _refuse(reasons.INVALID_ARCHIVE_ENTRY, "archive entry does not name a plain file in the archive directory")
        role = f"archive_{'ots' if proof else 'file'}:{name}"
        artifact = self._get(role, self.origin + ARCHIVE_DIRECTORY + name)
        if not proof and isinstance(entry.get("sha256"), str):
            artifact = dataclasses.replace(artifact, declared_sha256="sha256:" + entry["sha256"])
        if not proof:
            if entry.get("bytes") != artifact.byte_length or entry.get("sha256") != artifact.sha256.removeprefix("sha256:"):
                raise _refuse(reasons.DIGEST_MISMATCH, f"{name} does not match the size and sha256 declared in the archive index")
        return artifact

    # ---- transport rules

    def _check_url(self, url: str, scheme_code: str, host_code: str) -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            raise _refuse(scheme_code, f"only https is allowed: {url}")
        if parts.username or parts.password or (parts.hostname or "").lower() not in self.allowed_hosts:
            raise _refuse(host_code, f"host is not on the allow-list: {parts.hostname}")
        if (parts.port or 443) not in self.allowed_ports:
            raise _refuse(host_code, f"port {parts.port} is not on the allow-list")

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}

    def _get(self, role: str, url: str) -> Artifact:
        deadline = self._monotonic() + self.total_timeout
        attempts = 0
        while True:
            attempts += 1
            if self._monotonic() > deadline:
                raise _refuse(reasons.DEADLINE_EXCEEDED, f"no complete response within {self.total_timeout} s")
            try:
                return self._follow(role, url, deadline)
            except _Retryable as retry:
                if attempts > self.max_retries:
                    raise RefusalError([retry.issue]) from None
                delay = min(self.backoff_base * 2 ** (attempts - 1), self.backoff_max)
                if retry.retry_after is not None:
                    delay = min(retry.retry_after, self.retry_after_cap)
                self._sleep(delay)

    def _follow(self, role: str, url: str, deadline: float) -> Artifact:
        current, hops = url, 0
        while True:
            self._check_url(current, reasons.INSECURE_URL, reasons.HOST_NOT_ALLOWED)
            try:
                response = self.transport.request(
                    current, headers=self._headers(), connect_timeout=self.connect_timeout, read_timeout=self.read_timeout
                )
            except (OSError, TimeoutError) as error:
                raise _Retryable(Issue("", reasons.NETWORK_ERROR, f"{type(error).__name__}: {error}")) from None
            except Exception as error:  # http.client.HTTPException and similar protocol failures
                if type(error).__module__.startswith("http"):
                    raise _Retryable(Issue("", reasons.NETWORK_ERROR, f"{type(error).__name__}: {error}")) from None
                raise
            try:
                status = response.status
                if status in _REDIRECTS:
                    location = response.headers.get("location")
                    hops += 1
                    if not location:
                        raise _refuse(reasons.HTTP_STATUS, f"redirect {status} without a location")
                    if hops > self.max_redirects:
                        raise _refuse(reasons.TOO_MANY_REDIRECTS, f"more than {self.max_redirects} redirects")
                    target = urllib.parse.urljoin(current, location)
                    self._check_url(target, reasons.INSECURE_REDIRECT, reasons.REDIRECT_OFF_ORIGIN)
                    current = target
                    continue
                if status == 429 or 500 <= status <= 599:
                    retry_after = _retry_after_seconds(response.headers.get("retry-after"), self._clock())
                    raise _Retryable(Issue("", reasons.HTTP_STATUS, f"status {status}"), retry_after)
                if status != 200:
                    raise _refuse(reasons.HTTP_STATUS, f"status {status} for {current}")
                encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if encoding not in ("", "identity"):
                    raise _refuse(reasons.UNSUPPORTED_CONTENT_ENCODING, f"content-encoding {encoding} is not accepted")
                declared_text = (response.headers.get("content-length") or "").strip()
                declared = int(declared_text) if declared_text.isdigit() else None
                if declared is not None and declared > self.max_bytes:
                    raise _refuse(reasons.RESPONSE_TOO_LARGE, f"declared {declared} bytes exceeds {self.max_bytes}")
                data = self._read_capped(response, declared, deadline)
                fetched_at = _dt.datetime.fromtimestamp(self._clock(), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                return Artifact(role, data, url, current, status, fetched_at, response.headers.get("content-type"))
            finally:
                response.close()

    def _read_capped(self, response: Response, declared: int | None, deadline: float) -> bytes:
        """Read the whole body within the size cap and the deadline.

        A body shorter or longer than its declared ``Content-Length`` is an incomplete
        response, retried like a network error: ``http.client`` returns ``b""`` on a
        premature close instead of raising.
        """
        chunks, total = [], 0
        while True:
            try:
                chunk = response.read(65536)
            except (OSError, TimeoutError) as error:
                raise _Retryable(Issue("", reasons.NETWORK_ERROR, f"{type(error).__name__}: {error}")) from None
            except Exception as error:  # http.client.IncompleteRead and other protocol errors mid-body
                if type(error).__module__.startswith("http"):
                    raise _Retryable(Issue("", reasons.NETWORK_ERROR, f"{type(error).__name__}: {error}")) from None
                raise
            if not chunk:
                if declared is not None and total != declared:
                    raise _Retryable(Issue("", reasons.INCOMPLETE_RESPONSE,
                                           f"received {total} bytes, Content-Length declared {declared}"))
                return b"".join(chunks)
            total += len(chunk)
            if total > self.max_bytes:
                raise _refuse(reasons.RESPONSE_TOO_LARGE, f"more than {self.max_bytes} bytes streamed")
            if self._monotonic() > deadline:
                raise _refuse(reasons.DEADLINE_EXCEEDED, f"body not complete within {self.total_timeout} s")
            chunks.append(chunk)
