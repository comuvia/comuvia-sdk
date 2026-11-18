"""Keep test subprocesses on the same package copy as the parent, under -I.

Installed runs use normal isolated imports. Source runs add only the imported
package's absolute root, never the caller's working directory or PYTHONPATH.
This helper belongs to the tests, not the public package API.
"""

import importlib.metadata
import sys
from pathlib import Path

import comuvia


def imported_from_distribution():
    try:
        distribution = importlib.metadata.distribution("comuvia")
    except importlib.metadata.PackageNotFoundError:
        return False
    installed = Path(distribution.locate_file("comuvia/__init__.py")).resolve()
    return installed == Path(comuvia.__file__).resolve()


INSTALLED = imported_from_distribution()


def python_code(code, *args):
    if not INSTALLED:
        root = str(Path(comuvia.__file__).resolve().parents[1])
        code = f"import sys\nsys.path.insert(0, {root!r})\n" + code
    return [sys.executable, "-I", "-B", "-c", code, *args]


def python_cli(*args):
    if INSTALLED:
        return [sys.executable, "-I", "-B", "-m", "comuvia", *args]
    return python_code(
        "import runpy\nrunpy.run_module('comuvia', run_name='__main__', alter_sys=True)\n",
        *args,
    )
