"""Build and check the 0.1.0 release distributions with the fixed recipe in release/0.1.0/BUILD.md.

Standard library only; Python 3.11+. Run from a checkout of the public repository.

    python -I tools/build_release.py build --out dist-release/0.1.0 [--find-links <dir>]
    python -I tools/build_release.py check dist-release/0.1.0
    python -I tools/build_release.py wheel-from-sdist <verified sdist> --out <empty dir> [--find-links <dir>]

``build`` installs the build backend pinned by hash in ``release/0.1.0/build-constraints.txt``
(flit_core 3.12.0) into a fresh virtual environment, then calls its PEP 517 hooks directly:
``build_sdist``, then ``build_wheel`` from the unpacked sdist. ``SOURCE_DATE_EPOCH`` is always
``1767225600``, whatever the environment says; it fixes archive timestamps and is not a
publication date. Each wheel entry records Unix as its creating system on every platform (see
HOOKS). The output directory receives the four distributions, ``SHA256SUMS`` and
``manifest.json``, and nothing else.

``check`` rehashes a staging directory. It fails unless the directory holds exactly the expected
files and every distribution matches both the directory's ``SHA256SUMS`` and the approved
``release/0.1.0/SHA256SUMS``. Run it immediately before any upload.

``wheel-from-sdist`` builds the wheel from a downloaded, already verified sdist with the same
recipe, in an isolated environment, and fails unless it equals the approved wheel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / "release" / "0.1.0"
CONSTRAINTS = RELEASE / "build-constraints.txt"
APPROVED = RELEASE / "SHA256SUMS"
VERSION = "0.1.0"
PACKAGES = ["comuvia", "foreglass"]
SOURCE_DATE_EPOCH = "1767225600"

HOOKS = r"""
import os, sys, tarfile, tempfile, zipfile
# zipfile records the creating system as MS-DOS (0) on Windows and Unix (3) elsewhere, and
# flit_core does not normalize it. Record Unix everywhere so that wheels are identical.
_zipinfo_init = zipfile.ZipInfo.__init__
def _unix_zipinfo_init(self, *args, **kwargs):
    _zipinfo_init(self, *args, **kwargs)
    self.create_system = 3
zipfile.ZipInfo.__init__ = _unix_zipinfo_init
import flit_core.buildapi as backend
source, out = sys.argv[1], sys.argv[2]
if source.endswith(".tar.gz"):
    sdist = source
else:
    os.chdir(source)
    sdist = os.path.join(out, backend.build_sdist(out))
with tempfile.TemporaryDirectory() as unpacked:
    with tarfile.open(sdist) as tf:
        tf.extractall(unpacked, filter="data")
    (root,) = os.listdir(unpacked)
    os.chdir(os.path.join(unpacked, root))
    backend.build_wheel(out)
    os.chdir(out)
"""


def expected_names(packages: list[str]) -> list[str]:
    return sorted(n for p in packages for n in (f"{p}-{VERSION}-py3-none-any.whl", f"{p}-{VERSION}.tar.gz"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sums(path: Path) -> dict[str, str]:
    sums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(maxsplit=1)
            sums[name.strip().lstrip("*")] = digest.lower()
    return sums


def git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def empty_directory(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    return out


def run_hooks(sources: list[Path], out: Path, find_links: str | None) -> None:
    """Install the pinned backend into a fresh environment and run HOOKS for each source."""
    with tempfile.TemporaryDirectory(prefix="comuvia-release-build-") as tmp:
        venv = Path(tmp) / "backend"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, stdout=sys.stderr)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = [str(python), "-m", "pip", "install", "--quiet", "--no-cache-dir", "--no-deps",
                   "--require-hashes", "--only-binary", ":all:", "-r", str(CONSTRAINTS)]
        if find_links:
            install += ["--no-index", "--find-links", find_links]
        pip_env = dict(os.environ, PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1")
        subprocess.run(install, check=True, env=pip_env, stdout=sys.stderr)
        build_env = dict(os.environ, SOURCE_DATE_EPOCH=SOURCE_DATE_EPOCH)
        for source in sources:
            subprocess.run([str(python), "-I", "-c", HOOKS, str(source), str(out)],
                           check=True, env=build_env, stdout=sys.stderr)


def build(out: Path, find_links: str | None = None) -> list[dict]:
    """Build the four distributions into the empty directory ``out``; return each file's name, size and digest."""
    run_hooks([REPO / "packages" / p for p in PACKAGES], empty_directory(out), find_links)
    built = sorted(p.name for p in out.iterdir())
    if built != expected_names(PACKAGES):
        raise SystemExit(f"unexpected build output: {built}")
    files = [{"name": name, "package": name.split("-")[0], "kind": "wheel" if name.endswith(".whl") else "sdist",
              "size": (out / name).stat().st_size, "sha256": sha256(out / name)} for name in built]
    (out / "SHA256SUMS").write_text("".join(f"{f['sha256']}  {f['name']}\n" for f in files),
                                    encoding="utf-8", newline="\n")
    dirty = git("status", "--porcelain", "--", "packages")
    manifest = {
        "release": VERSION,
        "files": files,
        "recipe": {"source_date_epoch": int(SOURCE_DATE_EPOCH),
                   "constraints": CONSTRAINTS.relative_to(REPO).as_posix(),
                   "constraints_sha256": sha256(CONSTRAINTS)},
        "source": {"commit": git("rev-parse", "HEAD"),
                   "trees": {f"packages/{p}": git("rev-parse", f"HEAD:packages/{p}") for p in PACKAGES},
                   "packages_clean": None if dirty is None else dirty == ""},
        "built_with": {"python": platform.python_version(), "platform": f"{platform.system()} {platform.machine()}"},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return files


def wheel_from_sdist(sdist: Path, out: Path, find_links: str | None = None) -> int:
    """Build the wheel from a (verified) sdist with the same recipe and compare it with the approved wheel."""
    run_hooks([sdist], empty_directory(out), find_links)
    (wheel,) = [p for p in out.iterdir() if p.suffix == ".whl"]
    actual, approved = sha256(wheel), read_sums(APPROVED).get(wheel.name)
    print(f"{actual}  {wheel.name}")
    if actual != approved:
        print(f"FAIL {wheel.name}: rebuilt {actual}, approved {approved}", file=sys.stderr)
        return 1
    print(f"OK: the wheel rebuilt from {sdist.name} equals the approved wheel", file=sys.stderr)
    return 0


def check(stage: Path) -> int:
    problems = []
    names = expected_names(PACKAGES)
    present = sorted(p.name for p in stage.iterdir())
    if present != sorted(names + ["SHA256SUMS", "manifest.json"]):
        problems.append(f"{stage} must hold exactly {names} plus SHA256SUMS and manifest.json; found {present}")
    staged = read_sums(stage / "SHA256SUMS") if (stage / "SHA256SUMS").is_file() else {}
    approved = read_sums(APPROVED)
    manifest = ({f["name"]: f["sha256"] for f in json.loads((stage / "manifest.json").read_text(encoding="utf-8"))["files"]}
                if (stage / "manifest.json").is_file() else {})
    if sorted(staged) != names:
        problems.append(f"staged SHA256SUMS names {sorted(staged)}, expected {names}")
    for name in names:
        path = stage / name
        actual = sha256(path) if path.is_file() else None
        for label, table in (("staged SHA256SUMS", staged), ("manifest.json", manifest), ("approved SHA256SUMS", approved)):
            if table.get(name) != actual:
                problems.append(f"{name}: actual {actual}, {label} {table.get(name)}")
        if actual is not None:
            print(f"{actual}  {name}")
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if not problems:
        print(f"OK: {len(names)} files match the staged and approved digests", file=sys.stderr)
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the four distributions into an empty directory")
    b.add_argument("--out", required=True)
    b.add_argument("--find-links", help="install the pinned backend from this directory instead of the index")
    c = sub.add_parser("check", help="rehash a staging directory against the approved digests")
    c.add_argument("stage")
    w = sub.add_parser("wheel-from-sdist", help="rebuild the wheel from a verified sdist and compare it")
    w.add_argument("sdist")
    w.add_argument("--out", required=True)
    w.add_argument("--find-links", help="install the pinned backend from this directory instead of the index")
    args = parser.parse_args()
    if args.command == "build":
        for f in build(Path(args.out).resolve(), args.find_links):
            print(f"{f['sha256']}  {f['name']}")
        return 0
    if args.command == "wheel-from-sdist":
        return wheel_from_sdist(Path(args.sdist).resolve(), Path(args.out).resolve(), args.find_links)
    return check(Path(args.stage).resolve())


if __name__ == "__main__":
    sys.exit(main())
