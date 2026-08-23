"""mypy regression gate: no NEW type errors in the package.

The package currently carries a known set of mypy errors (the baseline,
``test/mypy_baseline.txt``). This test runs mypy over ``bytemaker/`` and
fails if any error appears that is not in the baseline — so typing fixes
(Self returns, generic Array, ...) cannot silently regress while the old
errors burn down independently.

Regenerate the baseline after intentional changes with::

    python test/typing_regression_test.py --regen

Errors are keyed as ``path :: error-code :: message`` (line numbers are
deliberately excluded so unrelated edits don't churn the file — including
the ones mypy writes INSIDE a message, see :func:`_normalize`). Message
text can drift between mypy feature releases, so the gate only enforces
when the installed mypy matches the baseline's recorded major.minor —
otherwise it skips and asks for a regen.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "mypy_baseline.txt"
VERSION_PREFIX = "# mypy-version: "


#: mypy writes a line number into the message of some errors ("Name "x"
#: already defined on line 280"). The key drops the error's OWN line number,
#: so leaving these in made any edit that shifts lines look like a batch of
#: new errors — nine baseline entries carried one, and adding four lines to a
#: file five modules away was enough to fire the gate. A false alarm is worse
#: than no alarm here: it teaches a reflexive --regen, which is precisely how
#: a real regression gets waved through.
_LINE_IN_MESSAGE = re.compile(r"\bon line \d+")


def _normalize(message: str) -> str:
    """A message with its incidental details removed.

    Two kinds: line numbers written into the text (above), and mypy's
    did-you-mean suffixes — adding an attribute elsewhere can append
    ``; maybe "x"?`` to an unrelated pre-existing error, which must not read
    as a NEW one.
    """
    message = message.split("; maybe ")[0]
    return _LINE_IN_MESSAGE.sub("on line N", message)


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
        keys.add(f"{path} :: {code} :: {_normalize(message)}")
    return keys, proc


def _read_baseline():
    version = None
    keys = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if line.startswith(VERSION_PREFIX):
            version = line[len(VERSION_PREFIX):].strip()
        elif line and not line.startswith("#"):
            # Normalized on READ as well as on run: a baseline entry added
            # by hand from raw mypy output (literal "on line 280", an
            # unstripped did-you-mean) would otherwise never match its
            # normalized twin and report as a permanent false new error.
            # _normalize is idempotent, so a --regen-written file is
            # untouched; only raw pastes are repaired.
            keys.add(_normalize(line.rstrip("\n")))
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


def test_both_sides_of_the_gate_normalize_identically():
    """The set difference only means something if run output and baseline
    pass through the same normalizer. _normalize must be idempotent (so a
    regen-written baseline is untouched on read) and must repair a raw
    hand-pasted mypy line into the key the run side produces."""
    raw = 'bytemaker/x.py :: no-redef :: Name "y" already defined on line 280'
    fixed = 'bytemaker/x.py :: no-redef :: Name "y" already defined on line N'
    assert _normalize(raw) == fixed
    assert _normalize(fixed) == fixed  # idempotent
    assert _normalize('m :: attr-defined :: no attr; maybe "x"?') == (
        "m :: attr-defined :: no attr"
    )
    # ... and the real baseline is already in normal form, so read-side
    # normalization is a no-op on a healthy file
    _, keys = _read_baseline()
    assert all(_normalize(k) == k for k in keys)


if __name__ == "__main__":
    if "--regen" not in sys.argv:
        sys.exit("usage: python test/typing_regression_test.py --regen")
    keys, _ = _run_mypy()
    _write_baseline(keys, _mypy_version() or "unknown")
    print(f"wrote {BASELINE} ({len(keys)} unique error keys)")
