"""Check the integrity of the synthetic fixtures under fixtures/synthetic.

Standard library plus the in-tree comuvia source; Python 3.11+. It checks:

- each retained source file matches exactly one snapshot's content digest and byte length;
- every ``sha256:`` value in a record or expected.json is a real content digest or the record
  digest of a fixture record (no placeholders);
- JSON files have no duplicate members, no NaN/Infinity and no BOM;
- every record passes ``comuvia.validate``;
- references resolve within the fixture and carry the target's record digest;
- text selectors (quote, prefix, suffix, code-point position) match the decoded source;
- every record is ``comuvia/0.1`` with ``data_origin: "synthetic"``;
- Git stores source files unconverted (``text`` and ``eol`` unset), when run in a Git checkout.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "synthetic"
sys.path.insert(0, str(REPO / "packages" / "comuvia" / "src"))

from comuvia import record_digest, validate  # noqa: E402
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def strict_load(path: Path):
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path}: BOM")

    def no_duplicates(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{path}: duplicate member in {keys}")
        return dict(pairs)

    def no_constant(token):
        raise ValueError(f"{path}: non-finite number {token}")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=no_constant)


def walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, str):
        yield value


def ref_key(ref: dict) -> tuple:
    return (ref["record_type"], ref["id"], ref["revision"])


def check_fixture(directory: Path) -> list[str]:
    errors: list[str] = []
    sources = {
        "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(): p
        for p in sorted((directory / "source").iterdir())
    }
    records = {}
    for path in sorted((directory / "records").glob("*.json")):
        body = strict_load(path)
        if path.stem != body["id"]:
            errors.append(f"{path.name}: file name differs from id {body['id']}")
        if body.get("schema") != "comuvia/0.1" or body.get("data_origin") != "synthetic":
            errors.append(f"{path.name}: schema/data_origin")
        for issue in validate(body):
            errors.append(f"{path.name}: refused: {issue.code} at '{issue.pointer}'")
        records[ref_key(body)] = body
    expected = strict_load(directory / "expected.json")
    record_digests = {record_digest(b): k for k, b in records.items()}

    for owner, value in [*((k[1], v) for k, v in records.items()), ("expected.json", expected)]:
        for text in walk_strings(value):
            if text.startswith("sha256:") and text not in sources and text not in record_digests:
                errors.append(f"{owner}: digest {text} is neither a source content digest nor a fixture record digest")

    snapshots = {}
    for body in records.values():
        content = body.get("content")
        if body["record_type"] == "resource_snapshot" and content and content.get("retained"):
            source = sources.get(content["digest"])
            if source is None or source.stat().st_size != content["byte_length"]:
                errors.append(f"{body['id']}: content digest/length does not match a source file")
            else:
                snapshots[ref_key(body)] = source.read_bytes()
    if len(snapshots) != len(sources):
        errors.append("source files and retained snapshots are not one-to-one")

    for body in records.values():
        for key in ("resource", "assertion", "question", "evidence"):
            if key in body and ref_key(body[key]) not in records:
                errors.append(f"{body['id']}: unresolved reference {key}")
            elif key in body and body[key]["digest"] != record_digest(records[ref_key(body[key])]):
                errors.append(f"{body['id']}: reference {key} digest does not match its target")
        selector = body.get("selector")
        source = snapshots.get(ref_key(body["resource"])) if selector else None
        if source is not None:
            text = source.decode("utf-8")
            quote = selector["text_quote"]
            start, end = selector["text_position"]["start"], selector["text_position"]["end"]
            if text.count(quote["exact"]) != 1:
                errors.append(f"{body['id']}: quote does not occur exactly once")
            if text[start:end] != quote["exact"] or body["quote"]["exact"] != quote["exact"]:
                errors.append(f"{body['id']}: text position does not select the quote")
            if text[start - len(quote["prefix"]):start] != quote["prefix"]:
                errors.append(f"{body['id']}: prefix mismatch")
            if text[end:end + len(quote["suffix"])] != quote["suffix"]:
                errors.append(f"{body['id']}: suffix mismatch")

    for entry in expected["content_identity"]:
        snapshot = records.get(ref_key(entry["record"]))
        if snapshot is None or snapshot["content"]["digest"] != entry["digest"]:
            errors.append(f"expected.json: content identity entry for {entry['record']['id']}")

    if shutil.which("git") and (REPO / ".git").exists():
        paths = [str(p.relative_to(REPO)) for p in sources.values()]
        attrs = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", *paths],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        for line in attrs:
            if not line.endswith(": unset"):
                errors.append(f"git attribute not unset: {line}")
    return errors


def main() -> int:
    failed = False
    # Provider-format fixtures without comuvia records (foreglass-ledger) are checked by
    # tools/make_foreglass_fixture.py --check instead.
    for directory in sorted(p for p in FIXTURES.iterdir() if (p / "records").is_dir()):
        try:
            errors = check_fixture(directory)
        except (ValueError, KeyError, TypeError) as error:
            errors = [f"{type(error).__name__}: {error}"]
        failed |= bool(errors)
        print(f"{'FAIL' if errors else 'PASS'} {directory.name}")
        for error in errors:
            print(f"  {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
