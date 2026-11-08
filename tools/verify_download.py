"""Download a published distribution pair as raw bytes and verify it before any install.

Standard library only; Python 3.11+. Nothing is installed, unpacked or built, and no build
backend runs: the files are fetched with urllib, not pip.

    python -I tools/verify_download.py --index testpypi --package comuvia --out <directory>
    python -I tools/verify_download.py --index pypi --package comuvia --version 0.1.1 --out <directory>

``--version`` defaults to 0.1.0, the version the 0.1.0 instructions verify. Steps:
1. read the approved digests from ``release/<version>/SHA256SUMS``; refuse if that file is
   absent, or if it does not list exactly this package's wheel and sdist for that version
   (for example ``foreglass`` 0.1.1, which was never released);
2. fetch the index's JSON for exactly that version (``/pypi/<package>/<version>/json``);
3. require exactly the expected wheel and sdist, neither yanked;
4. download each file from the URL the index lists (https, the index's file host only);
5. require the SHA-256 of the received bytes to equal **both** the digest the index declares
   and the approved digest;
6. only when both files pass, write them into ``--out``. Nothing is written otherwise.

Install only from the verified directory afterwards, for example
``pip install --no-index --no-deps <out>/comuvia-0.1.1-py3-none-any.whl``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.1.0"
VERSION_FORM = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
INDEXES = {
    "pypi": ("https://pypi.org", "files.pythonhosted.org"),
    "testpypi": ("https://test.pypi.org", "test-files.pythonhosted.org"),
}
MAX_BYTES = 16 * 1024 * 1024
TIMEOUT = 60


class Refused(Exception):
    pass


def read_sums(path: Path) -> dict[str, str]:
    sums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(maxsplit=1)
            sums[name.strip().lstrip("*")] = digest.lower()
    return sums


def expected_names(package: str, version: str) -> set[str]:
    return {f"{package}-{version}-py3-none-any.whl", f"{package}-{version}.tar.gz"}


def approved_for(package: str, version: str, repo: Path = REPO) -> dict[str, str]:
    """The approved digests of this package's pair, from release/<version>/SHA256SUMS."""
    if not VERSION_FORM.match(version):
        raise Refused(f"{version!r} is not a release version (expected N.N.N)")
    path = repo / "release" / version / "SHA256SUMS"
    if not path.is_file():
        raise Refused(f"release/{version}/SHA256SUMS is absent: {version} has no approved digests")
    sums = read_sums(path)
    expected = expected_names(package, version)
    missing = sorted(expected - set(sums))
    if missing:
        raise Refused(f"release/{version}/SHA256SUMS does not list {missing}: {package} {version} was not released")
    return {name: sums[name] for name in expected}


def fetch(url: str, version: str = DEFAULT_VERSION) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"comuvia-release-verify/{version}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Refused(f"{url}: larger than {MAX_BYTES} bytes")
    return data


def verify(index: str, package: str, out: Path, approved: dict[str, str], version: str = DEFAULT_VERSION) -> list[dict]:
    base, file_host = INDEXES[index]
    expected = expected_names(package, version)
    listing = json.loads(fetch(f"{base}/pypi/{package}/{version}/json", version))
    files = {entry["filename"]: entry for entry in listing["urls"]}
    if set(files) != expected:
        raise Refused(f"{index} lists {sorted(files)} for {package} {version}; expected {sorted(expected)}")
    results = []
    for name in sorted(expected):
        entry = files[name]
        if entry.get("yanked"):
            raise Refused(f"{name} is yanked on {index}")
        url = urllib.parse.urlsplit(entry["url"])
        if url.scheme != "https" or url.hostname != file_host:
            raise Refused(f"{name}: unexpected download URL {entry['url']}")
        data = fetch(entry["url"], version)
        actual = hashlib.sha256(data).hexdigest()
        declared = entry["digests"]["sha256"].lower()
        if actual != declared:
            raise Refused(f"{name}: received {actual}, index declares {declared}")
        if actual != approved.get(name):
            raise Refused(f"{name}: received {actual}, approved {approved.get(name)}")
        results.append({"file": name, "bytes": len(data), "sha256": actual, "url": entry["url"],
                        "index_digest": "match", "approved_digest": "match", "data": data})
    for result in results:
        if (out / result["file"]).exists():
            raise Refused(f"{out / result['file']} already exists")
    for result in results:
        (out / result["file"]).write_bytes(result.pop("data"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", required=True, choices=sorted(INDEXES))
    parser.add_argument("--package", required=True, choices=["comuvia", "foreglass"])
    parser.add_argument("--version", default=DEFAULT_VERSION, help=f"release version to verify (default {DEFAULT_VERSION})")
    parser.add_argument("--out", required=True, help="directory for verified files (created if absent)")
    args = parser.parse_args()
    try:
        approved = approved_for(args.package, args.version)
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        results = verify(args.index, args.package, out, approved, args.version)
    except (Refused, OSError, KeyError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"index": args.index, "package": args.package, "version": args.version, "verified": results}, indent=2))
    print(f"OK: {len(results)} files match the index and approved digests", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
