"""mypy regression gate: no NEW type errors in the package.

The package currently carries a known set of mypy errors (the baseline,
``test/mypy_baseline.txt``). This test runs mypy over ``bytemaker/`` and
fails if any error appears that is not in the baseline — so typing fixes
(Self returns, generic Array, ...) cannot silently regress while the old
errors burn down independently.

Regenerate the baseline after intentional changes with::

    python test/typing_regression_test.py --regen

Errors are keyed as ``path :: error-code :: message`` (line numbers are
deliberately excluded so unrelated edits don't churn the file). Message
text can drift between mypy feature releases, so the gate only enforces
when the installed mypy matches the baseline's recorded major.minor —
otherwise it skips and asks for a regen.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "mypy_baseline.txt"
VERSION_PREFIX = "# mypy-version: "


def _mypy_version():
    try:
        from mypy.version import __version__
    except ImportError:
        return None
    return __version__


def _major_minor(version):
    return ".".join(version.split(".")[:2])


def _run_mypy():
    """Run mypy over the package (config from pyproject.toml) and return
    the set of normalized error keys."""
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    keys = set()
    for line in proc.stdout.splitlines():
        # bytemaker\structs.py:123: error: message text  [error-code]
        parts = line.split(":", 2)
        if len(parts) < 3 or " error: " not in line:
            continue
        path = parts[0].strip().replace("\\", "/")
        rest = parts[2].split(" error: ", 1)[-1].strip()
        if rest.endswith("]") and "  [" in rest:
            message, _, code = rest.rpartition("  [")
            code = code[:-1]
        else:
            message, code = rest, "misc"
        keys.add(f"{path} :: {code} :: {message}")
    return keys, proc


def _read_baseline():
    version = None
    keys = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if line.startswith(VERSION_PREFIX):
            version = line[len(VERSION_PREFIX):].strip()
        elif line and not line.startswith("#"):
            keys.add(line.rstrip("\n"))
    return version, keys


def _write_baseline(keys, version):
    lines = [
        "# mypy error baseline for bytemaker/ - see typing_regression_test.py",
        f"{VERSION_PREFIX}{version}",
        *sorted(keys),
    ]
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_no_new_mypy_errors():
    import pytest

    pytest.importorskip("mypy")
    if not BASELINE.exists():
        pytest.skip("no mypy baseline recorded (run --regen to create one)")

    baseline_version, baseline = _read_baseline()
    current_version = _mypy_version()
    if baseline_version is None or current_version is None:
        pytest.skip("baseline or installed mypy has no version recorded")
    if _major_minor(baseline_version) != _major_minor(current_version):
        pytest.skip(
            f"installed mypy {current_version} != baseline mypy"
            f" {baseline_version}; regen the baseline to re-arm the gate"
        )

    current, proc = _run_mypy()
    assert proc.returncode in (0, 1), (
        f"mypy failed to run (rc={proc.returncode}):\n{proc.stderr}"
    )
    new = current - baseline
    assert not new, (
        "New mypy errors (not in test/mypy_baseline.txt):\n  "
        + "\n  ".join(sorted(new))
        + "\nFix them, or if intentional regen the baseline with:"
        "\n  python test/typing_regression_test.py --regen"
    )


if __name__ == "__main__":
    if "--regen" not in sys.argv:
        sys.exit("usage: python test/typing_regression_test.py --regen")
    keys, _ = _run_mypy()
    _write_baseline(keys, _mypy_version() or "unknown")
    print(f"wrote {BASELINE} ({len(keys)} unique error keys)")
