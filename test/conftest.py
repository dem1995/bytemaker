import sys
import textwrap
from pathlib import Path

sys.path.append(str(Path(__file__).parents[1]))

# _typing_repro.py is a mypy-only contract (uses reveal_type, a checker-only
# builtin that raises at runtime). pytest's default patterns already skip it;
# this makes an explicit `pytest test/_typing_repro.py` skip it too.
collect_ignore = ["_typing_repro.py"]


def docstring_example(doc: str, first_word: str) -> str:
    """The indented example block in ``doc`` that starts with ``first_word``,
    dedented — for tests that execute or compare a docstring's own example
    rather than a hand-typed copy that can drift from it.

    One home (two tests already grew independent copies of this in one
    commit range), with a readable failure when the marker is missing
    instead of a bare StopIteration.
    """
    lines = doc.splitlines()
    starts = [
        i for i, ln in enumerate(lines) if ln.strip().startswith(first_word)
    ]
    assert starts, (
        f"docstring has no example line starting with {first_word!r} —"
        f" the example the test asserts against has been renamed or removed"
    )
    block = []
    for ln in lines[starts[0]:]:
        if not ln.strip():
            break
        block.append(ln)
    return textwrap.dedent("\n".join(block))
