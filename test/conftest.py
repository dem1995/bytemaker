import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parents[1]))

# _typing_repro.py is a mypy-only contract (uses reveal_type, a checker-only
# builtin that raises at runtime). pytest's default patterns already skip it;
# this makes an explicit `pytest test/_typing_repro.py` skip it too.
collect_ignore = ["_typing_repro.py"]
