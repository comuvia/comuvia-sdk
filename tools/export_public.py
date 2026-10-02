"""Produce and scan a public export of the repository.

Standard library plus git; Python 3.11+.

    python -I tools/export_public.py --out <new directory outside the checkout> --deny-list <file>
        [--ref <commit>]
    python -I tools/export_public.py --out <dir> --deny-list <file> --ref <commit>
        --parent-repo <clone of the public repository> --expect-parent <full commit id>
        --date YYYY-MM-DDTHH:MM:SSZ --message-file <file> [--freeze <path> ...]

The export contains only the tracked files under PUBLIC_PATHS, taken from the staged tree
(``git write-tree``) or from ``--ref``. Ignored and untracked files are never included.
No remote is created and nothing is pushed. There are two modes:

- **Initial** (the first form). The export becomes a single parentless commit with a fixed
  identity, the fixed date EXPORT_DATE and the fixed message MESSAGE. This mode made the
  first public commit; it is kept so that commit can be reproduced. Public paths absent
  from the source are skipped and listed under ``absent_public_paths``.
- **Chained** (the second form), for every later public commit. ``--parent-repo`` is a
  local repository whose ``HEAD`` must be exactly ``--expect-parent`` (the current public
  ``main``) with no uncommitted or untracked files. The export becomes one new commit
  whose parent is that commit, dated ``--date`` (UTC, not before the parent and not in the
  future) with the exact bytes of ``--message-file`` as its message. The same inputs give
  the same commit id. Every public path must exist in the source; a tree equal to the
  parent's is refused. Every ``release/<version>/SHA256SUMS`` of the parent, and every
  ``--freeze`` path, must be unchanged, or the scan fails. The report lists the changed
  paths.

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
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
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
    "documentation/guides/working-with-0.1-records.md",
    "documentation/tutorials",
    "fixtures/synthetic",
    "packages/comuvia",
    "packages/foreglass",
    "release/0.1.0",
    "tools",
]
# Initial mode only: the first public commit used this date and message. Chained exports
# take a real, recorded --date and --message-file instead.
EXPORT_DATE = "1767225600 +0000"  # 2026-01-01T00:00:00Z, the build's SOURCE_DATE_EPOCH
MESSAGE = "comuvia 0.1.0 release candidate: initial public export\n"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FUTURE_SLACK_SECONDS = 600
FULL_ID = re.compile(r"[0-9a-f]{40}")
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


def machine_markers(repo: Path = REPO) -> list[str]:
    markers = {str(repo), repo.as_posix(), str(Path.home()), Path.home().as_posix(), tempfile.gettempdir()}
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


def reference_findings(out: Path, files: list[Path], repo: Path = REPO) -> list[dict]:
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
    private = objects_found(repo, sorted(candidates)) - objects_found(out, sorted(candidates))
    for name in sorted(private):
        findings.append({"where": candidates[name], "rule": "private_object_id", "text": name})
    return findings


def object_id(repo: Path, rev: str, path: str) -> str | None:
    """The object id of ``path`` in ``rev``, or None if it does not exist there."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}:{path}"], cwd=repo, capture_output=True)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def present_paths(repo: Path, source: str, public_paths: list[str]) -> tuple[list[str], list[str]]:
    present, absent = [], []
    for path in public_paths:
        (present if git("ls-tree", "--name-only", source, "--", path, cwd=repo).strip() else absent).append(path)
    return present, absent


def parse_date(text: str) -> int:
    try:
        return int(datetime.strptime(text, DATE_FORMAT).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        raise SystemExit(f"--date must be UTC in the form YYYY-MM-DDTHH:MM:SSZ, not {text!r}") from None


def read_message(path: str) -> bytes:
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit("the message file is not UTF-8") from None
    if "\r" in text:
        raise SystemExit("the message file must use LF line endings")
    if not text.endswith("\n") or not text.split("\n", 1)[0].strip():
        raise SystemExit("the message needs a non-empty first line and must end with a newline")
    return data


def extract(repo: Path, source: str, paths: list[str], out: Path) -> list[Path]:
    archive = git("archive", "--format=tar", source, "--", *paths, cwd=repo)
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(out, filter="data")
    return sorted(p for p in out.rglob("*") if p.is_file() and p.relative_to(out).parts[0] != ".git")


def init_repository(out: Path) -> None:
    empty_template = Path(tempfile.mkdtemp(prefix="export-template-"))
    git("-c", "init.defaultBranch=main", "init", "-q", f"--template={empty_template}", ".", cwd=out)
    git("config", "core.autocrlf", "false", cwd=out)


def identity_env(author: str, date: str) -> dict:
    name, email = re.fullmatch(r"(.+) <(.+)>", author).groups()
    return dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=name,
                GIT_COMMITTER_EMAIL=email, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)


def scan_export(out: Path, files: list[Path], deny: list[str], repo: Path) -> tuple[list[dict], int]:
    markers = machine_markers(repo)
    findings = []
    for path in files:
        findings += scan(path.relative_to(out).as_posix(), path.read_bytes(), deny, markers)
    findings += scan("commit metadata", git("cat-file", "-p", "HEAD", cwd=out), deny, markers)
    findings += scan("commit log", git("log", "--format=fuller", cwd=out), deny, markers)
    findings += reference_findings(out, files, repo)
    return findings, len(markers)


def unexpected_paths(out: Path, files: list[Path], public_paths: list[str]) -> list[str]:
    return [p.relative_to(out).as_posix() for p in files
            if not any(p.relative_to(out).as_posix() == q or p.relative_to(out).as_posix().startswith(q + "/")
                       for q in public_paths)]


def initial_export(repo: Path, public_paths: list[str], out: Path, deny: list[str], source: str, author: str) -> dict:
    present, absent = present_paths(repo, source, public_paths)
    files = extract(repo, source, present, out)
    env = identity_env(author, EXPORT_DATE)
    init_repository(out)
    git("add", "-A", cwd=out, env=env)
    git("-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-F", "-", cwd=out, env=env, data=MESSAGE.encode())
    commit = git("rev-parse", "HEAD", cwd=out).decode().strip()
    tree = git("rev-parse", "HEAD^{tree}", cwd=out).decode().strip()
    remotes = git("remote", cwd=out).decode().split()
    findings, markers = scan_export(out, files, deny, repo)
    unexpected = unexpected_paths(out, files, public_paths)
    return {
        "mode": "initial",
        "source": source,
        "public_paths": public_paths,
        "absent_public_paths": absent,
        "files": len(files),
        "export_commit": commit,
        "export_tree": tree,
        "history": "one commit, no parents",
        "remotes": remotes,
        "deny_list_entries": len(deny),
        "machine_markers": markers,
        "unexpected_paths": unexpected,
        "findings": findings,
        "scan": "clean" if not findings and not unexpected and not remotes else "FAILED",
    }


def chained_export(repo: Path, public_paths: list[str], out: Path, deny: list[str], source: str, author: str,
                   parent_repo: Path, expect_parent: str, date: str, message_file: str, freeze: list[str]) -> dict:
    if not FULL_ID.fullmatch(expect_parent):
        raise SystemExit("--expect-parent must be a full 40-digit lowercase commit id")
    if out.is_relative_to(parent_repo):
        raise SystemExit("the export directory must be outside the parent repository")
    head = git("rev-parse", "HEAD", cwd=parent_repo).decode().strip()
    if head != expect_parent:
        raise SystemExit(f"the parent repository's HEAD is {head}, not --expect-parent {expect_parent}")
    if git("status", "--porcelain", "--untracked-files=all", cwd=parent_repo).strip():
        raise SystemExit("the parent repository has uncommitted or untracked files")
    epoch = parse_date(date)
    message = read_message(message_file)
    present, absent = present_paths(repo, source, public_paths)
    if absent:
        raise SystemExit(f"public paths missing from {source}: {absent}")
    for path in freeze:
        if object_id(parent_repo, expect_parent, path) is None:
            raise SystemExit(f"--freeze {path} does not exist in the parent")
    if epoch < int(git("log", "-1", "--format=%ct", expect_parent, cwd=parent_repo).decode()):
        raise SystemExit("--date is earlier than the parent commit's date")
    if epoch > time.time() + FUTURE_SLACK_SECONDS:
        raise SystemExit("--date is in the future")

    files = extract(repo, source, present, out)
    init_repository(out)
    git("fetch", "-q", "--no-tags", str(parent_repo), "HEAD", cwd=out)
    if git("rev-parse", "FETCH_HEAD", cwd=out).decode().strip() != expect_parent:
        raise SystemExit("the fetched parent differs from --expect-parent")
    (out / ".git" / "FETCH_HEAD").unlink()  # it names the local parent path
    env = identity_env(author, f"{epoch} +0000")
    git("add", "-A", cwd=out, env=env)
    tree = git("write-tree", cwd=out).decode().strip()
    if tree == git("rev-parse", f"{expect_parent}^{{tree}}", cwd=out).decode().strip():
        raise SystemExit("nothing to export: the tree equals the parent's")
    commit = git("-c", "commit.gpgsign=false", "commit-tree", tree, "-p", expect_parent, "-F", "-",
                 cwd=out, env=env, data=message).decode().strip()
    git("update-ref", "refs/heads/main", commit, cwd=out)

    versions = git("ls-tree", "-d", "--name-only", expect_parent, "release/", cwd=out).decode().splitlines()
    frozen_paths = sorted(set(freeze) | {f"{v}/SHA256SUMS" for v in versions
                                         if object_id(out, expect_parent, f"{v}/SHA256SUMS")})
    frozen = []
    for path in frozen_paths:
        before, after = object_id(out, expect_parent, path), object_id(out, commit, path)
        frozen.append({"path": path, "parent": before, "export": after, "unchanged": before == after})
    changed = [dict(zip(("status", "path"), line.split("\t", 1)))
               for line in git("diff-tree", "-r", "--no-renames", "--name-status", expect_parent, commit,
                               cwd=out).decode().splitlines()]

    findings, markers = scan_export(out, files, deny, repo)
    findings += [{"where": f["path"], "rule": "frozen_path_changed", "text": f["path"]}
                 for f in frozen if not f["unchanged"]]
    remotes = git("remote", cwd=out).decode().split()
    clean = not git("status", "--porcelain", "--untracked-files=all", cwd=out).strip()
    unexpected = unexpected_paths(out, files, public_paths)
    count = int(git("rev-list", "--count", "HEAD", cwd=out).decode())
    return {
        "mode": "chained",
        "source": source,
        "public_paths": public_paths,
        "files": len(files),
        "parent": expect_parent,
        "export_commit": commit,
        "export_tree": tree,
        "date": date,
        "message_sha256": hashlib.sha256(message).hexdigest(),
        "history": f"{count} commits; parent {expect_parent}",
        "changed": changed,
        "frozen": frozen,
        "remotes": remotes,
        "clean_tree": clean,
        "deny_list_entries": len(deny),
        "machine_markers": markers,
        "unexpected_paths": unexpected,
        "findings": findings,
        "scan": "clean" if not findings and not unexpected and not remotes and clean else "FAILED",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--deny-list", required=True)
    parser.add_argument("--ref", help="tree or commit to export (default: the staged tree)")
    parser.add_argument("--author", default="Comuvia <info@comuvia.com>")
    chained = parser.add_argument_group("chained mode (every public commit after the first)")
    chained.add_argument("--parent-repo", help="local repository whose HEAD is the current public main")
    chained.add_argument("--expect-parent", help="full commit id that HEAD of --parent-repo must equal")
    chained.add_argument("--date", help="commit date, UTC: YYYY-MM-DDTHH:MM:SSZ")
    chained.add_argument("--message-file", help="UTF-8 file with LF line endings: the exact commit message")
    chained.add_argument("--freeze", action="append", default=[],
                         help="a path that must be unchanged from the parent (repeatable)")
    return parser


def export(args: argparse.Namespace, repo: Path = REPO, public_paths: list[str] = PUBLIC_PATHS) -> dict:
    out = Path(args.out).resolve()
    if out.is_relative_to(repo):
        raise SystemExit("the export directory must be outside the checkout")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    deny = [line.strip() for line in Path(args.deny_list).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]
    source = args.ref or git("write-tree", cwd=repo).decode().strip()
    chained = (args.parent_repo, args.expect_parent, args.date, args.message_file)
    if any(value is not None for value in chained):
        if any(value is None for value in chained):
            raise SystemExit("chained mode needs --parent-repo, --expect-parent, --date and --message-file together")
        return chained_export(repo, public_paths, out, deny, source, args.author, Path(args.parent_repo).resolve(),
                              args.expect_parent, args.date, args.message_file, args.freeze)
    if args.freeze:
        raise SystemExit("--freeze applies only to chained mode")
    return initial_export(repo, public_paths, out, deny, source, args.author)


def main(argv: list[str] | None = None) -> int:
    report = export(build_parser().parse_args(argv))
    print(json.dumps(report, indent=2))
    return 0 if report["scan"] == "clean" else 1


if __name__ == "__main__":
    sys.exit(main())
