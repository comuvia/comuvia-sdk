"""Produce and scan a fresh-history public export of the repository.

Standard library plus git; Python 3.11+.

    python -I tools/export_public.py --out <new directory outside the checkout> --deny-list <file>

The export contains only the tracked files under PUBLIC_PATHS, taken from the staged tree
(``git write-tree``) or from ``--ref``. Ignored and untracked files are never included.
It becomes a single new commit with a fixed identity and a fixed date, so the same input
gives the same commit id. No remote is created and nothing is pushed.

Every exported file, and the export commit's metadata, is then scanned. The scan fails
on drive-letter or home-directory paths, this machine's checkout, home, temp directory,
user or host name, a path into a ``.local`` directory, and every name in ``--deny-list``,
a local file of private names (one per line, case-insensitive). The deny-list is read
only; it is never exported. The scan also fails on any hexadecimal id (7 to 40 digits) that
names an object in this repository but not in the export, such as a private commit, and on
any relative Markdown link or ``github.com/comuvia/comuvia-sdk/{blob,tree}/main/...`` link
whose target is not in the export.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLIC_PATHS = [
    ".gitattributes",
    ".github/workflows/release.yml",
    ".gitignore",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "documentation/architecture/python-compatibility.md",
    "documentation/architecture/record-store.md",
    "documentation/tutorials",
    "fixtures/synthetic",
    "packages/comuvia",
    "packages/foreglass",
    "release/0.1.0",
    "tools",
]
EXPORT_DATE = "1767225600 +0000"  # 2026-01-01T00:00:00Z, the build's SOURCE_DATE_EPOCH
MESSAGE = "comuvia 0.1.0 release candidate: initial public export\n"
PATTERNS = {
    "drive_letter_path": re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![/\\])"),
    "home_path": re.compile(rb"(/home/[a-z_]|/Users/[A-Za-z]|\\Users\\[A-Za-z])"),
    "dot_local_path": re.compile(rb"\.local[\\/][A-Za-z0-9_]"),
}
HEX_ID = re.compile(rb"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
PUBLIC_URL = re.compile(r"https://github\.com/comuvia/comuvia-sdk/(?:blob|tree)/main/([^)\s`'\"#>]+)")


def git(*args: str, cwd: Path = REPO, env: dict | None = None, data: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=cwd, env=env, input=data, capture_output=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def machine_markers() -> list[str]:
    markers = {str(REPO), REPO.as_posix(), str(Path.home()), Path.home().as_posix(), tempfile.gettempdir()}
    for name in (os.environ.get("USERNAME"), os.environ.get("USER"), os.environ.get("COMPUTERNAME"),
                 os.uname().nodename if hasattr(os, "uname") else None, Path.home().name):
        if name and len(name) >= 4:
            markers.add(name)
    return sorted(markers)


def scan(label: str, data: bytes, deny: list[str], markers: list[str]) -> list[dict]:
    findings = []
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            findings.append({"where": label, "rule": rule, "text": match.group(0).decode("latin-1")})
    lowered = data.lower()
    for name in deny:
        if name.lower().encode() in lowered:
            findings.append({"where": label, "rule": "deny_list", "text": "<deny-list entry>"})
    for marker in markers:
        if marker.lower().encode() in lowered:
            findings.append({"where": label, "rule": "machine_marker", "text": "<machine-specific value>"})
    return findings


def objects_found(repo: Path, names: list[str]) -> set[str]:
    """The names among ``names`` that resolve to an object in ``repo`` (short ids included)."""
    if not names:
        return set()
    data = "".join(f"{n}\n" for n in names).encode()
    lines = git("cat-file", "--batch-check", cwd=repo, data=data).decode().splitlines()
    return {n for n, line in zip(names, lines) if not line.endswith((" missing", " ambiguous"))}


def reference_findings(out: Path, files: list[Path]) -> list[dict]:
    """Private object ids (present here, absent from the export) and links that point nowhere in the export."""
    findings, candidates = [], {}
    exported = {p.relative_to(out).as_posix() for p in files}
    directories = {"/".join(e.split("/")[:i]) for e in exported for i in range(1, e.count("/") + 1)}

    def exists(target: str) -> bool:
        target = target.strip("/")
        return target in exported or target in directories

    for path in files:
        label, data = path.relative_to(out).as_posix(), path.read_bytes()
        for match in HEX_ID.finditer(data):
            candidates.setdefault(match.group(0).decode(), label)
        text = data.decode("utf-8", errors="replace")
        for target in PUBLIC_URL.findall(text):
            if not exists(target):
                findings.append({"where": label, "rule": "dangling_link", "text": target})
        if label.endswith(".md"):
            for target in MARKDOWN_LINK.findall(text):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                resolved = os.path.normpath(os.path.join(os.path.dirname(label), target.split("#")[0])).replace(os.sep, "/")
                if resolved.startswith("..") or not exists(resolved):
                    findings.append({"where": label, "rule": "dangling_link", "text": target})
    private = objects_found(REPO, sorted(candidates)) - objects_found(out, sorted(candidates))
    for name in sorted(private):
        findings.append({"where": candidates[name], "rule": "private_object_id", "text": name})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--deny-list", required=True)
    parser.add_argument("--ref", help="tree or commit to export (default: the staged tree)")
    parser.add_argument("--author", default="Comuvia <info@comuvia.com>")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if out.is_relative_to(REPO):
        raise SystemExit("the export directory must be outside the checkout")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    deny = [line.strip() for line in Path(args.deny_list).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]
    source = args.ref or git("write-tree").decode().strip()

    archive = git("archive", "--format=tar", source, "--", *PUBLIC_PATHS)
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(out, filter="data")
    files = sorted(p for p in out.rglob("*") if p.is_file())

    name, email = re.fullmatch(r"(.+) <(.+)>", args.author).groups()
    env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=name,
               GIT_COMMITTER_EMAIL=email, GIT_AUTHOR_DATE=EXPORT_DATE, GIT_COMMITTER_DATE=EXPORT_DATE)
    empty_template = Path(tempfile.mkdtemp(prefix="export-template-"))
    git("-c", "init.defaultBranch=main", "init", "-q", f"--template={empty_template}", ".", cwd=out)
    git("config", "core.autocrlf", "false", cwd=out)
    git("add", "-A", cwd=out, env=env)
    git("-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-F", "-", cwd=out, env=env, data=MESSAGE.encode())
    commit = git("rev-parse", "HEAD", cwd=out).decode().strip()
    tree = git("rev-parse", "HEAD^{tree}", cwd=out).decode().strip()
    remotes = git("remote", cwd=out).decode().split()

    markers = machine_markers()
    findings = []
    for path in files:
        findings += scan(path.relative_to(out).as_posix(), path.read_bytes(), deny, markers)
    findings += scan("commit metadata", git("cat-file", "-p", "HEAD", cwd=out), deny, markers)
    findings += scan("commit log", git("log", "--format=fuller", cwd=out), deny, markers)
    findings += reference_findings(out, files)
    unexpected = [p.relative_to(out).as_posix() for p in files
                  if not any(p.relative_to(out).as_posix() == q or p.relative_to(out).as_posix().startswith(q + "/") for q in PUBLIC_PATHS)]

    report = {
        "source": source,
        "public_paths": PUBLIC_PATHS,
        "files": len(files),
        "export_commit": commit,
        "export_tree": tree,
        "history": "one commit, no parents",
        "remotes": remotes,
        "deny_list_entries": len(deny),
        "machine_markers": len(markers),
        "unexpected_paths": unexpected,
        "findings": findings,
        "scan": "clean" if not findings and not unexpected and not remotes else "FAILED",
    }
    print(json.dumps(report, indent=2))
    return 0 if report["scan"] == "clean" else 1


if __name__ == "__main__":
    sys.exit(main())
