"""Run current source tests offline in separate isolated package processes.

Usage: python -I tools/check_source.py [--package comuvia|foreglass]
No installation, build or private fixture is required. Installed-distribution
metadata and optional conformance/private-fixture skips are reported explicitly;
this command does not replace package_smoke.py's installed-wheel checks.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


CHILD = r'''
import importlib, io, json, sys, unittest
from pathlib import Path
root, package = Path(sys.argv[1]), sys.argv[2]
names = ['comuvia'] if package == 'comuvia' else ['comuvia', 'foreglass']
sys.path[:0] = [str(root / 'packages' / name / 'src') for name in names]
modules = {}
for name in names:
    module = importlib.import_module(name)
    expected = (root / 'packages' / name / 'src' / name / '__init__.py').resolve()
    if Path(module.__file__).resolve() != expected:
        raise RuntimeError('test imported the wrong package: ' + name)
    modules[name] = {'version': module.__version__, 'path': str(expected)}
folder = root / 'packages' / package / 'tests'
suite = unittest.defaultTestLoader.discover(str(folder), top_level_dir=str(folder))
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
ok = result.wasSuccessful() and result.testsRun > len(result.skipped)
report = {'package': package, 'modules': modules, 'tests': result.testsRun,
          'failures': len(result.failures), 'errors': len(result.errors),
          'skipped': [{'test': test.id(), 'reason': reason} for test, reason in result.skipped],
          'ok': ok}
if not ok:
    print(stream.getvalue(), file=sys.stderr)
print(json.dumps(report))
sys.exit(0 if ok else 1)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", choices=("comuvia", "foreglass"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    reports = []
    for name in ([args.package] if args.package else ["comuvia", "foreglass"]):
        result = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, str(root), name],
                                cwd=root, capture_output=True, text=True, timeout=300)
        try:
            report = json.loads(result.stdout)
        except (ValueError, TypeError):
            report = {"package": name, "ok": False, "error": "source test process did not return a report"}
        if result.returncode != 0:
            report["ok"] = False
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        reports.append(report)
    print(json.dumps({"kind": "source-check", "results": reports}, indent=2))
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
