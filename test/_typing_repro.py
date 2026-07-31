"""Static-typing contract for the Struct field surface.

NOT a pytest module (the name does not match ``test_*`` / ``*_test``, so
pytest skips it, and ``reveal_type`` is a checker-only builtin that would
raise at runtime). It is the durable mypy contract: run

    mypy --follow-imports=silent test/_typing_repro.py

and it must report the two ``reveal_type`` notes below and **no errors**
except the ones marked ``# type: ignore[...]`` (which are the negative
cases -- ``--warn-unused-ignores`` proves the checker really rejects them).

Covers both checker-friendly declaration styles:
- annotation-carried: ``uN``/``sN``/``fN`` for scalars, bare for nested
  Struct, ``Annotated[list[T], Elem * N]`` for arrays;
- field-specifier: ``x: <plain type> = field(...)`` / ``= array(...)`` --
  the annotation is the plain checker type, the wire type rides the RHS
  specifier (which returns ``Any``, so it is assignable to any annotation).
Both produce identical runtime + identical checker types.
"""
from typing import Annotated, List

from bytemaker import (
    Buffer,
    Float32,
    Struct,
    UInt8,
    UInt16,
    UTF8String,
    array,
    field,
    u8,
    u16,
)


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


# --- field-specifier style: annotation is the plain type, RHS is the spec ---
class Spec(Struct, endian="little"):
    hp: int = field(UInt8)
    speed: float = field(Float32)
    name: str = field(UTF8String.of(nbytes=4))
    data: bytes = field(Buffer.of(nbytes=2))
    tags: List[int] = array(UInt16, 3)
    child: RGB = field(RGB)


s = Spec(hp=1, speed=1.5, name="ab", data=b"xy", tags=[1, 2, 3], child=RGB(r=1, g=2))
reveal_type(s.hp)     # noqa: F821  -> int
reveal_type(s.name)   # noqa: F821  -> str
reveal_type(s.data)   # noqa: F821  -> bytes
reveal_type(s.tags)   # noqa: F821  -> list[int]
reveal_type(s.child)  # noqa: F821  -> RGB
s.hp = "x"            # type: ignore  # field is int
s.name = 5            # type: ignore  # field is str
s.tags[0] = "x"       # type: ignore  # list[int]
