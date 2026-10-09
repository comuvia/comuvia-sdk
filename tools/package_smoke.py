"""Build, inspect and install-check the comuvia and foreglass distributions.

Standard library only; Python 3.11+.

    python -I tools/package_smoke.py build --out DIR [--find-links DIR]
        Build the sdist and wheel of both packages with the release recipe in
        tools/build_release.py (the wheel is built from the sdist), build them a second
        time to compare bytes, and inspect the contents and metadata.

    python -I tools/package_smoke.py check --dist DIR --work DIR
        Using the interpreter that runs this command, create a core-only and a core+client
        virtual environment, install only the local artifacts from --dist (pip --no-index)
        and run the import smoke and the package tests from the extracted sdists.

    python -I tools/package_smoke.py conformance --dist DIR --work DIR
        Install the pinned test-only libraries (TEST_ONLY) from the package index, then
        comuvia from --dist only (pip --no-index), and run every comuvia test from the
        extracted sdist, including the jsonschema agreement and RFC 8785 oracle checks.
        Fails if any test is skipped.

All commands refuse output or work directories inside the source checkout. The check
command does not need the checkout or network access, so it also runs in a container
with the tools directory and the built artifacts mounted.
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PACKAGES = ("comuvia", "foreglass")
# Both distributions are 0.1.0 release candidates: no upload guard, Apache-2.0.
VERSIONS = {"comuvia": "0.1.0", "foreglass": "0.1.0"}
GUARDED = {"comuvia": False, "foreglass": False}
LICENSES = {"comuvia": ("Apache-2.0", ["LICENSE"]), "foreglass": ("Apache-2.0", ["LICENSE"])}
# Unmodified Apache-2.0 text from https://www.apache.org/licenses/LICENSE-2.0.txt (fetched 2026-09-24).
LICENSE_SHA256 = "sha256:cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
REQUIRES_PYTHON = ">=3.11"
UPLOAD_GUARD = "Private :: Do Not Upload"
EXPECTED_REQUIRES = {"comuvia": [], "foreglass": [("comuvia", ["<0.2", ">=0.1.0"])]}
SDIST_TOP_LEVEL = {"pyproject.toml", "PKG-INFO", "README.md", "CHANGELOG.md", "LICENSE", "src", "tests"}
RECORD_TYPES = [
    "resource_snapshot", "source_assertion", "interpretation", "assessment",
    "question", "forecast", "outcome", "evaluation", "artifact_descriptor",
]
SCHEMA_FILES = ["common.json", *(f"{t}.json" for t in RECORD_TYPES)]
# Members each distribution must contain beyond its package module (relative to wheel / sdist root).
REQUIRED_WHEEL = {
    "comuvia": [f"comuvia/schemas/v0_1/{f}" for f in SCHEMA_FILES]
    + ["comuvia/rules/binary-brier-v1/1.json",
       "comuvia/cli.py", "comuvia/store.py", "comuvia/evaluation.py", "comuvia-0.1.0.dist-info/licenses/LICENSE"],
    "foreglass": [f"foreglass/{m}.py" for m in ("client", "intake", "catalog", "normalize", "capabilities", "reasons")]
    + ["foreglass-0.1.0.dist-info/licenses/LICENSE"],
}
REQUIRED_SDIST = {
    "comuvia": [f"tests/vectors/{f}" for f in ("canonicalization.json", "identity.json", "records.json", "evaluation.json")]
    + [f"src/comuvia/schemas/v0_1/{f}" for f in SCHEMA_FILES] + ["LICENSE"],
    "foreglass": [f"tests/vectors/foreglass-ledger/{f}" for f in (
        "expected.json", "source/ledger.json", "source/ledger.json.ots", "source/ledger-archive-index.json",
        "source/fragility-latest.json")]
    + ["LICENSE", "tests/test_transport.py", "tests/tls/test-ca.pem", "tests/tls/test-server.pem", "tests/tls/test-server-key.pem"],
}
# Test-only libraries for the conformance command, pinned; never runtime dependencies.
TEST_ONLY = ["jsonschema==4.26.0", "rfc8785==0.1.4"]
# Project-URL fields as flit_core emits them (sorted by label).
PROJECT_URLS = [
    "Documentation, https://github.com/comuvia/comuvia-sdk/tree/main/documentation/tutorials",
    "Issues, https://github.com/comuvia/comuvia-sdk/issues",
    "Repository, https://github.com/comuvia/comuvia-sdk",
]
DRIVE_PATH = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
FORBIDDEN_MEMBER_PARTS = {".local", "documentation", "fixtures", "__pycache__", ".git", ".env"}

REPO = Path(__file__).resolve().parents[1]


class CheckFailed(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def outside_checkout(path: Path) -> Path:
    path = path.resolve()
    require(not path.is_relative_to(REPO), f"{path} is inside the source checkout")
    return path


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise CheckFailed(f"command failed ({result.returncode}): {cmd}\n{result.stdout}\n{result.stderr}")
    return result


# ---------------------------------------------------------------------------- build


def release_recipe():
    """tools/build_release.py, loaded by path: ``python -I`` does not put this directory on sys.path."""
    spec = importlib.util.spec_from_file_location("build_release", Path(__file__).resolve().with_name("build_release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_into(out: Path, find_links: str | None = None) -> dict[str, Path]:
    """Build with the release recipe (release/0.1.0/BUILD.md) into the empty directory ``out``."""
    try:
        release_recipe().build(out, find_links)
    except (SystemExit, subprocess.CalledProcessError) as error:
        raise CheckFailed(f"release build failed: {error}") from error
    artifacts = {}
    for name in PACKAGES:
        artifacts[f"{name}-wheel"] = out / f"{name}-{VERSIONS[name]}-py3-none-any.whl"
        artifacts[f"{name}-sdist"] = out / f"{name}-{VERSIONS[name]}.tar.gz"
    for path in artifacts.values():
        require(path.is_file(), f"expected artifact missing: {path.name}")
    built = sorted(p.name for p in out.iterdir() if p.suffix in {".whl", ".gz"})
    require(built == sorted(p.name for p in artifacts.values()), f"unexpected artifacts: {built}")
    return artifacts


def private_markers() -> list[bytes]:
    """Absolute paths of this machine that must never appear in an artifact."""
    markers = set()
    for path in (REPO, REPO.parent, Path.home(), Path(tempfile.gettempdir()).resolve()):
        for text in (str(path), path.as_posix()):
            markers.add(text.encode())
            markers.add(text.lower().encode())
    return sorted(markers)


def scan_member(artifact: str, member: str, data: bytes, markers: list[bytes]) -> None:
    parts = set(re.split(r"[\\/]", member))
    require(not parts & FORBIDDEN_MEMBER_PARTS, f"{artifact}: forbidden member {member}")
    require(not member.endswith((".pyc", ".pyo")), f"{artifact}: bytecode member {member}")
    require(DRIVE_PATH.search(data) is None, f"{artifact}: drive-letter path in {member}")
    lowered = data.lower()
    for marker in markers:
        require(marker.lower() not in lowered, f"{artifact}: machine path in {member}")
    require(b".local/" not in data and b".local\\" not in data, f"{artifact}: .local reference in {member}")


def parse_requirement(text: str) -> tuple[str, list[str]]:
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*(.*)", text.strip())
    require(match is not None, f"unparseable requirement {text!r}")
    name, specifiers = match.groups()
    return name.lower(), sorted(s for s in specifiers.replace(" ", "").split(",") if s)


def check_metadata(name: str, artifact: str, raw: bytes) -> dict:
    msg = email.parser.BytesParser().parsebytes(raw)
    require(msg["Name"] == name, f"{artifact}: Name {msg['Name']!r}")
    require(msg["Version"] == VERSIONS[name], f"{artifact}: Version {msg['Version']!r}")
    require(msg["Requires-Python"] == REQUIRES_PYTHON, f"{artifact}: Requires-Python {msg['Requires-Python']!r}")
    classifiers = msg.get_all("Classifier") or []
    if GUARDED[name]:
        require(UPLOAD_GUARD in classifiers, f"{artifact}: missing upload guard classifier")
    else:
        require(UPLOAD_GUARD not in classifiers, f"{artifact}: release candidate still carries the upload guard")
    if LICENSES[name] is None:
        for field in ("License", "License-Expression", "License-File"):
            require(msg[field] is None, f"{artifact}: license metadata {field} present before rights review")
    else:
        expression, files = LICENSES[name]
        require(msg["License-Expression"] == expression, f"{artifact}: License-Expression {msg['License-Expression']!r}")
        require((msg.get_all("License-File") or []) == files, f"{artifact}: License-File {msg.get_all('License-File')}")
        require(msg["License"] is None, f"{artifact}: legacy License field present")
    urls = msg.get_all("Project-URL") or []
    require(urls == PROJECT_URLS, f"{artifact}: Project-URL {urls}")
    requires = [parse_requirement(r) for r in msg.get_all("Requires-Dist") or []]
    require(requires == EXPECTED_REQUIRES[name], f"{artifact}: Requires-Dist {requires}")
    return {"classifiers": classifiers, "requires_dist": msg.get_all("Requires-Dist") or []}


def inspect_wheel(name: str, path: Path, markers: list[bytes]) -> dict:
    with zipfile.ZipFile(path) as zf:
        members = zf.namelist()
        dist_info = f"{name}-{VERSIONS[name]}.dist-info/"
        for member in members:
            require(member.startswith((f"{name}/", dist_info)), f"{path.name}: unexpected member {member}")
            scan_member(path.name, member, zf.read(member), markers)
        require(f"{name}/__init__.py" in members, f"{path.name}: package module missing")
        for member in members:
            if member.endswith("/licenses/LICENSE"):
                require("sha256:" + hashlib.sha256(zf.read(member)).hexdigest() == LICENSE_SHA256, f"{path.name}: LICENSE text changed")
        for required in REQUIRED_WHEEL[name]:
            require(required in members, f"{path.name}: missing {required}")
        metadata = check_metadata(name, path.name, zf.read(dist_info + "METADATA"))
        generator = email.parser.BytesParser().parsebytes(zf.read(dist_info + "WHEEL"))["Generator"]
    return {"members": sorted(members), "generator": generator, **metadata}


def inspect_sdist(name: str, path: Path, markers: list[bytes]) -> dict:
    root = f"{name}-{VERSIONS[name]}/"
    with tarfile.open(path) as tf:
        members = []
        for info in tf.getmembers():
            require(info.name.startswith(root), f"{path.name}: member outside root {info.name}")
            require(info.isfile() or info.isdir(), f"{path.name}: link or special member {info.name}")
            relative = info.name[len(root):]
            require(relative.split("/")[0] in SDIST_TOP_LEVEL, f"{path.name}: unexpected member {info.name}")
            if info.isfile():
                members.append(info.name)
                if relative == "LICENSE":
                    data = tf.extractfile(info).read()
                    require("sha256:" + hashlib.sha256(data).hexdigest() == LICENSE_SHA256, f"{path.name}: LICENSE text changed")
                scan_member(path.name, info.name, tf.extractfile(info).read(), markers)
        pkg_info = tf.extractfile(root + "PKG-INFO").read()
    for required in ("pyproject.toml", "PKG-INFO", "README.md", "CHANGELOG.md", f"src/{name}/__init__.py", *REQUIRED_SDIST[name]):
        require(root + required in members, f"{path.name}: missing {required}")
    require(any(m.startswith(root + "tests/") for m in members), f"{path.name}: package tests missing")
    check_metadata(name, path.name + ":PKG-INFO", pkg_info)
    return {"members": sorted(members)}


def command_build(args: argparse.Namespace) -> dict:
    out = outside_checkout(Path(args.out))
    require(not out.exists() or not any(out.iterdir()), f"output directory {out} is not empty")
    artifacts = build_into(out / "dist", args.find_links)
    markers = private_markers()
    recipe = release_recipe()
    report: dict = {
        "recipe": "tools/build_release.py",
        "source_date_epoch": recipe.SOURCE_DATE_EPOCH,
        "build_constraints_sha256": sha256_file(recipe.CONSTRAINTS),
        "artifacts": {},
    }
    for key, path in artifacts.items():
        name = key.split("-")[0]
        details = inspect_wheel(name, path, markers) if key.endswith("wheel") else inspect_sdist(name, path, markers)
        report["artifacts"][path.name] = {"digest": sha256_file(path), "byte_length": path.stat().st_size, **details}
    if not args.no_rebuild:
        again = build_into(out / "rebuild", args.find_links)
        report["rebuild_identical"] = {
            p.name: sha256_file(p) == report["artifacts"][p.name]["digest"] for p in again.values()
        }
        require(all(report["rebuild_identical"].values()), f"rebuild differs: {report['rebuild_identical']}")
    (out / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


# ---------------------------------------------------------------------------- check

# Runs inside each fresh environment as `python -I -c SMOKE <json>`.
SMOKE = r"""
import json, sys
cfg = json.loads(sys.argv[1])
blocked = []

def audit(event, args):
    if event.startswith("socket.") or event in cfg["blocked_events"]:
        blocked.append(event)
        raise RuntimeError("blocked during import: " + event)

import importlib, importlib.metadata, pathlib, types
sys.addaudithook(audit)
# Self-test: the hook must block synthetic probe events before any package import.
for probe in cfg["probe_events"]:
    try:
        sys.audit(probe, "probe")
    except RuntimeError:
        pass
    else:
        raise AssertionError("audit hook did not block " + probe)
assert blocked == cfg["probe_events"], blocked
blocked.clear()
prefix = pathlib.Path(sys.prefix).resolve()
allowed = sys.stdlib_module_names | set(cfg["present"])
result = {"python": sys.version.split()[0], "isolated": sys.flags.isolated, "hook_self_test": cfg["probe_events"],
          "present": {}, "absent": {}}
for name in cfg["present"]:
    before = set(sys.modules)
    module = importlib.import_module(name)
    loaded = sorted(set(sys.modules) - before)
    foreign = [m for m in loaded if m.split(".")[0] not in allowed]
    assert not foreign, (name, foreign)
    origin = pathlib.Path(module.__file__).resolve()
    assert origin.is_relative_to(prefix), (name, str(origin))
    assert module.__version__ == importlib.metadata.version(name), name
    submodules = {n for n, v in vars(module).items() if isinstance(v, types.ModuleType)}
    public = sorted(n for n in vars(module) if not n.startswith("_") and n not in submodules)
    assert public == sorted(getattr(module, "__all__", [])), (name, public)
    entry = {"version": module.__version__, "under_env": True, "modules_loaded": loaded, "public": public}
    if name == "comuvia":
        folder = module.schema_files()
        assert pathlib.Path(str(folder)).resolve().is_relative_to(prefix), str(folder)
        schemas = sorted(e.name for e in folder.iterdir() if e.name.endswith(".json"))
        assert schemas == sorted(cfg["schema_files"]), schemas
        ids = sorted(module.parse_json(folder.joinpath(n).read_bytes())["$id"] for n in schemas)
        assert all(i.startswith("urn:comuvia:schema:0.1:") for i in ids), ids
        issues = module.validate({"schema": "comuvia/0.1", "record_type": "forecast"})
        assert issues and all(i.code == "missing_required_field" for i in issues), issues
        entry["schemas"] = schemas
    result["present"][name] = entry
for name in cfg["absent"]:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as error:
        assert error.name == name, error
        result["absent"][name] = "ModuleNotFoundError"
    else:
        raise AssertionError(name + " imported in an environment without it")
assert not blocked, blocked
assert sys.flags.isolated == 1
print(json.dumps(result))
"""

BLOCKED_EVENTS = [
    "urllib.Request",
    "http.client.connect",
    "http.client.send",
    "ftplib.connect",
    "smtplib.connect",
    "subprocess.Popen",
    "os.system",
]
# Synthetic events raised with sys.audit to prove the hook blocks before imports run.
PROBE_EVENTS = ["socket.connect", "urllib.Request", "http.client.connect"]


def venv_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_script(env: Path, name: str) -> Path:
    return env / ("Scripts" if os.name == "nt" else "bin") / (f"{name}.exe" if os.name == "nt" else name)


# Runs the installed CLI in-process under the same audit hook as SMOKE: python -I -c CLI_UNDER_HOOK <json cfg> <args...>
CLI_UNDER_HOOK = r"""
import json, sys
cfg = json.loads(sys.argv[1])
blocked = []
def audit(event, args):
    if event.startswith("socket.") or event in cfg["blocked_events"]:
        blocked.append(event)
        raise RuntimeError("blocked: " + event)
sys.addaudithook(audit)
from comuvia.cli import main
code = main(sys.argv[2:])
assert not blocked, blocked
sys.exit(code)
"""

EVALUATED_AT = "2027-02-17T00:00:00Z"


def cli_scenario(env: Path, sdist: Path, work: Path) -> dict:
    """Fixture B through the installed console script: store, evaluate, append, reproduce, verify."""
    records = json.loads((sdist / "tests" / "vectors" / "identity.json").read_text(encoding="utf-8"))["records"]
    names = ["q-port-calder-teu-2027-01", "fc-lantern-port-calder-teu-2027-01",
             "res-port-calder-bulletin-2027-01-first", "out-port-calder-teu-2027-01"]
    folder = work / "cli-fixture-b"
    folder.mkdir()
    files = []
    for name in names:
        path = folder / f"{name}.json"
        path.write_text(json.dumps(records[name]), encoding="utf-8")
        files.append(str(path))
    store = str(folder / "store")
    script = str(venv_script(env, "comuvia"))
    require(Path(script).exists(), f"console script missing: {script}")

    def console(*args):
        result = subprocess.run([script, "--json", *args], capture_output=True, text=True, cwd=work)
        return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None

    def hooked(*args):
        cfg = json.dumps({"blocked_events": BLOCKED_EVENTS})
        result = subprocess.run([str(venv_python(env)), "-I", "-c", CLI_UNDER_HOOK, cfg, "--json", *args],
                                capture_output=True, text=True, cwd=work)
        return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None

    require(console("store", "init", store)[0] == 0, "cli: store init failed")
    code, appended = console("store", "append", store, *files)
    require(code == 0 and len(appended["entries"]) == 4, f"cli: append failed ({code})")
    code, report = hooked("evaluate", "--store", store, "--append", "--evaluated-at", EVALUATED_AT,
                          "--recorded-by", "evaluator:package-smoke", "--recorded-at", EVALUATED_AT)
    require(code == 0, f"cli: evaluate failed ({code})")
    (result,) = report["results"]
    loss_text = json.dumps(result["loss"])
    require(result["status"] == "scored" and loss_text == "0.09000000000000002", f"cli: unexpected result {result}")
    require(report["aggregate"] is None, "cli: aggregate score present")
    code, reproduced = hooked("reproduce", "--store", store)
    require(code == 0 and [r["result"] for r in reproduced["results"]] == ["match"], f"cli: reproduce {reproduced}")
    code, verified = hooked("store", "verify", store)
    require(code == 0 and verified["ok"] and verified["entries"] == 5, f"cli: store verify {verified}")
    code, _ = console("evaluate", "--store", store, "--append")
    require(code == 2, f"cli: usage error exit code {code}")
    return {
        "console_script": Path(script).name,
        "fixture_b_loss": loss_text,
        "reproduce": reproduced["results"][0]["result"],
        "store_verify": {"ok": verified["ok"], "entries": verified["entries"], "lock_holder": verified["lock_holder"]},
        "network_events": 0,
    }


def install_env(env: Path, dist: Path, requirement: str) -> Path:
    run([sys.executable, "-m", "venv", str(env)])
    python = venv_python(env)
    pip_env = dict(os.environ, PIP_CONFIG_FILE=os.devnull, PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    run(
        [str(python), "-I", "-m", "pip", "install", "--no-index", "--find-links", str(dist),
         "--only-binary", ":all:", "--no-cache-dir", requirement],
        env=pip_env,
    )
    return python


def command_check(args: argparse.Namespace) -> dict:
    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    if REPO.joinpath("packages").is_dir():
        outside_checkout(work)
    require(not work.exists() or not any(work.iterdir()), f"work directory {work} is not empty")
    work.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "interpreter": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
        },
        "artifacts": {p.name: sha256_file(p) for p in sorted(dist.iterdir()) if p.suffix in {".whl", ".gz"}},
        "environments": {},
    }
    sdists = {}
    for name in PACKAGES:
        target = work / "sdist"
        with tarfile.open(dist / f"{name}-{VERSIONS[name]}.tar.gz") as tf:
            tf.extractall(target, filter="data")
        sdists[name] = target / f"{name}-{VERSIONS[name]}"

    scenarios = {
        "core-only": ("comuvia", ["comuvia"], ["foreglass"]),
        "core+client": ("foreglass", ["comuvia", "foreglass"], []),
    }
    for label, (requirement, present, absent) in scenarios.items():
        env = work / f"env-{label.replace('+', '-')}"
        python = install_env(env, dist, requirement)
        cfg = {
            "present": present,
            "absent": absent,
            "blocked_events": BLOCKED_EVENTS,
            "probe_events": PROBE_EVENTS,
            "schema_files": SCHEMA_FILES,
        }
        smoke = json.loads(run([str(python), "-I", "-c", SMOKE, json.dumps(cfg)], cwd=work).stdout)
        tests = {}
        for name in present:
            result = run(
                [str(python), "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "tests", "-v"],
                cwd=sdists[name],
            )
            lines = result.stderr.strip().splitlines()
            tests[name] = "; ".join(line for line in lines if line.startswith("Ran ")) + "; " + lines[-1]
        report["environments"][label] = {"smoke": smoke, "package_tests": tests}
        if label == "core-only":
            report["environments"][label]["cli"] = cli_scenario(env, sdists["comuvia"], work)
        if args.tutorials:
            names = ["tutorial_a_narrative.py", "tutorial_b_forecast.py", "tutorial_d_dependencies.py", "tutorial_e_authoring.py", "tutorial_f_point_error.py", "tutorial_g_edition_review.py", "tutorial_h_pinned_evaluation.py"]
            if "foreglass" in present:
                names.append("tutorial_c_foreglass.py")
            report["environments"][label]["tutorials"] = run_tutorials(
                env, Path(args.tutorials).resolve(), Path(args.fixtures).resolve(), work / f"tutorials-{env.name}", names)
    return report


def run_tutorials(env: Path, tutorials: Path, fixtures: Path, work: Path, names: list[str]) -> dict:
    """Run the named tutorial scripts with the environment's interpreter; each asserts its stated values."""
    results = {}
    work.mkdir(parents=True, exist_ok=True)
    for script in (tutorials / name for name in names):
        result = subprocess.run(
            [str(venv_python(env)), "-I", str(script), "--fixtures", str(fixtures), "--work", str(work / script.stem), "--json"],
            capture_output=True, text=True, cwd=work,
        )
        require(result.returncode == 0, f"{script.name} failed: {result.stdout[-500:]} {result.stderr[-500:]}")
        summary = json.loads(result.stdout)
        results[script.name] = {"passed": True, "evaluation": summary.get("evaluation"), "cli": summary.get("cli")}
    require(sorted(results) == sorted(names), f"expected tutorials {names}, ran {sorted(results)}")
    return results


def command_conformance(args: argparse.Namespace) -> dict:
    """Install pinned test-only libraries, then comuvia from local artifacts only, and run every test."""
    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    if REPO.joinpath("packages").is_dir():
        outside_checkout(work)
    require(not work.exists() or not any(work.iterdir()), f"work directory {work} is not empty")
    work.mkdir(parents=True, exist_ok=True)
    env = work / "env-conformance"
    run([sys.executable, "-m", "venv", str(env)])
    python = str(venv_python(env))
    pip_env = dict(os.environ, PIP_CONFIG_FILE=os.devnull, PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    wheels = work / "test-only-wheels"
    run([python, "-I", "-m", "pip", "download", "--no-cache-dir", "--only-binary", ":all:", "--dest", str(wheels), *TEST_ONLY],
        env=pip_env)
    test_only_hashes = {w.name: sha256_file(w) for w in sorted(wheels.iterdir())}
    run([python, "-I", "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "--only-binary", ":all:",
         "--no-cache-dir", *TEST_ONLY], env=pip_env)
    run([python, "-I", "-m", "pip", "install", "--no-index", "--find-links", str(dist), "--only-binary", ":all:",
         "--no-cache-dir", "comuvia"], env=pip_env)
    with tarfile.open(dist / f"comuvia-{VERSIONS['comuvia']}.tar.gz") as tf:
        tf.extractall(work / "sdist", filter="data")
    result = run([python, "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "tests", "-v"],
                 cwd=work / "sdist" / f"comuvia-{VERSIONS['comuvia']}")
    lines = result.stderr.strip().splitlines()
    require(lines[-1] == "OK", f"conformance run skipped or failed: {lines[-1]}")
    freeze = run([python, "-I", "-m", "pip", "freeze", "--all"], env=pip_env).stdout.split()
    return {
        "interpreter": platform.python_version(),
        "test_only": TEST_ONLY,
        "test_only_wheels": test_only_hashes,
        "installed": freeze,
        "comuvia_wheel": sha256_file(dist / f"comuvia-{VERSIONS['comuvia']}-py3-none-any.whl"),
        "tests": "; ".join(line for line in lines if line.startswith("Ran ")) + "; " + lines[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--out", required=True)
    build.add_argument("--no-rebuild", action="store_true", help="skip the second build and byte comparison")
    build.add_argument("--find-links", help="install the pinned build backend from this directory, not the index")
    for command in ("check", "conformance"):
        parsed = sub.add_parser(command)
        parsed.add_argument("--dist", required=True)
        parsed.add_argument("--work", required=True)
        if command == "check":
            parsed.add_argument("--tutorials", help="directory holding tutorial_*.py (runs them in the core-only environment)")
            parsed.add_argument("--fixtures", help="fixtures/synthetic directory used by the tutorials")
    args = parser.parse_args()
    commands = {"build": command_build, "check": command_check, "conformance": command_conformance}
    try:
        report = commands[args.command](args)
    except (CheckFailed, AssertionError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    print("PASS", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
