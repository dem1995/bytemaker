"""Static-typing contract for the Struct field surface.

NOT a pytest module (the name does not match ``test_*`` / ``*_test``, so
pytest skips it, and ``reveal_type`` is a checker-only builtin that would
raise at runtime). It is the durable mypy contract: run

    mypy --follow-imports=silent test/_typing_repro.py

and it must report the two ``reveal_type`` notes below and **no errors**
except the ones marked ``# type: ignore[...]`` (which are the negative
cases -- ``--warn-unused-ignores`` proves the checker really rejects them).

Covers the checker-friendly spellings:
- scalar fields via the ``uN``/``sN``/``fN`` aliases (``Annotated[int, UIntN]``);
- array fields via ``Annotated[list[T], Elem * N]`` -- the array analog of
  the ``uN`` pattern (the terse runtime sugar ``Elem * N`` is not a valid
  type to a checker, so the checker-friendly form carries the element/count
  in the ``Annotated`` metadata while the first arg is the plain list type).
"""
from typing import Annotated, List

from bytemaker import Struct, UInt16, Float32, u8, u16


class RGB(Struct, endian="little"):
    r: u8
    g: u8


# Reusable module-level alias (the recommended ergonomic form).
Colors8 = Annotated[List[int], UInt16 * 8]


class Palette(Struct, endian="little"):
    colors: Colors8                              # list[int]
    coeffs: Annotated[List[float], Float32 * 4]  # list[float]
    tiles: Annotated[List[RGB], RGB * 3]         # list[RGB]
    count: u16


p = Palette(
    colors=[1, 2, 3, 4, 5, 6, 7, 8],
    coeffs=[0.5, 1.5, 2.5, 3.5],
    tiles=[RGB(r=1, g=2), RGB(r=3, g=4), RGB(r=5, g=6)],
    count=3,
)

reveal_type(p.colors)  # noqa: F821  -> list[int]
reveal_type(p.tiles)  # noqa: F821  -> list[RGB]

# Positive: the list surface type-checks
p.colors[0] = 99           # list[int] is mutable and int-valued
n: int = p.colors[3]
p.tiles[0].r = 7           # element is a real RGB with typed fields
c: float = p.coeffs[1]

# Negative: the checker rejects wrong element / field types. Bare ignores
# (version-robust across error codes); each is load-bearing --
# --warn-unused-ignores fails if the checker does NOT error on that line.
p.colors[0] = "x"          # type: ignore
p.colors = "not a list"    # type: ignore
p.tiles[0] = 5             # type: ignore
bad = Palette(colors="x", coeffs=[], tiles=[], count=0)  # type: ignore
