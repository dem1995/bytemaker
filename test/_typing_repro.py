"""Static-typing contract for the Struct field surface.

NOT a pytest module (the name does not match ``test_*`` / ``*_test``, so
pytest skips it, and ``reveal_type`` is a checker-only builtin that would
raise at runtime). It is the durable mypy contract: run

    mypy --follow-imports=silent test/_typing_repro.py

and it must report the two ``reveal_type`` notes below and **no errors**
except the ones marked ``# type: ignore[...]`` (which are the negative
cases -- ``--warn-unused-ignores`` proves the checker really rejects them).

This contract is mypy's. pyright agrees with it, but it diverges on one
thing mypy cannot see: a re-exported ``ClassVar`` stops reading as a
ClassVar to pyright's ``dataclass_transform`` field collection, which
silently turns ``Struct``'s own class attributes into fields. That one is
pinned in ``typing_regression_test.py`` instead.

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
    UInt32,
    UTF8String,
    array,
    field,
    u8,
    u16,
)
from bytemaker.adapters import THUMB_PTR, fixed
from bytemaker.structs import Array


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


# --- fused wire types: adapter @ BitType (adapted-1) ---------------------
# The type parameter is the ADAPTER's user-plane type, not the base's:
# fixed(4) maps an int wire to a float user value.
ThumbPtr = THUMB_PTR @ UInt32
Mult = fixed(4) @ UInt16


class Fused(Struct, endian="little"):
    # A fused codec is a VALUE (an Adapted instance), so -- exactly like
    # `Elem * N` for arrays -- the bare `fn: ThumbPtr` spelling works at
    # runtime but is not a valid *type* to a checker. The two
    # checker-friendly spellings:
    fn: Annotated[int, ThumbPtr]              # int (THUMB_PTR.py_type)
    scale: float = field(Mult)                # float via the adapter


f = Fused(fn=0x0803EBA8, scale=1.5)
reveal_type(f.fn)     # noqa: F821  -> int
reveal_type(f.scale)  # noqa: F821  -> float
f.scale = "x"         # type: ignore  # field is float


class BareFused(Struct, endian="little"):
    # Negative: the runtime-only spelling. Load-bearing ignore --
    # --warn-unused-ignores proves the checker really refuses it, which is
    # why Adapted's docstring points at the two forms above.
    fn: ThumbPtr  # type: ignore[valid-type]


# The ergonomic form for a convention used more than once: bind the
# ANNOTATION to a module-level alias. Terse AND checked -- and the reason
# bytemaker does not offer a `ThumbPtr[int]` subscript, which a checker would
# refuse the same way BareFused.fn is refused above.
FnAddr = Annotated[int, ThumbPtr]
Q4 = Annotated[float, Mult]


class Aliased(Struct, endian="little"):
    update_fn: FnAddr
    next_fn: FnAddr
    scale: Q4


al = Aliased(update_fn=0x0803EBA8, next_fn=0, scale=1.5)
reveal_type(al.update_fn)  # noqa: F821  -> int
reveal_type(al.scale)      # noqa: F821  -> float
al.update_fn = "x"         # type: ignore  # the alias is still int


# A fused element makes a standalone Array report the adapter's type.
mults = Array.of(Mult, 4, endian="little")
reveal_type(mults.parse(b"\x00" * 8))  # noqa: F821  -> list[float]
ptrs = Array.of(ThumbPtr, 2, endian="little")
reveal_type(ptrs.parse(b"\x00" * 8))  # noqa: F821  -> list[int]
# (Array.pack takes an untyped sequence by design -- it accepts plain
# values OR boxes -- so there is no negative case to pin here.)


# --- adapted Array FIELDS: the element list is the USER plane (adapted-2) -
class AdaptedArrays(Struct, endian="little"):
    fns: List[int] = array(ThumbPtr, 2)      # THUMB_PTR.py_type is int
    scales: List[float] = array(Mult, 2)     # fixed(4).py_type is float


aa = AdaptedArrays(fns=[0x0803EBA8, 0], scales=[1.5, 1.0])
reveal_type(aa.fns)     # noqa: F821  -> list[int]
reveal_type(aa.scales)  # noqa: F821  -> list[float]
aa.scales[0] = 2.5      # a live user-plane lvalue
aa.scales[0] = "x"      # type: ignore  # elements are float


# --- pointers: PtrValue is the runtime type; the annotation picks the view -
from bytemaker.rom import Ptr, PtrValue, Space

space = Space(b"\x00" * 8, base=0, endian="little")


class Pointee(Struct, endian="little"):
    v: u16


class HasPtrs(Struct, endian="little"):
    # Loose: reads as int; .deref is runtime-only on this view.
    loose: Annotated[int, Ptr(Pointee)]
    # Precise: reads as PtrValue, so .deref type-checks -- the trade-off is
    # that the generated __init__ then wants a PtrValue for this parameter.
    precise: Annotated[PtrValue, Ptr(Pointee)]


hp = HasPtrs.parse(b"\x00" * 8)
reveal_type(hp.loose)    # noqa: F821  -> int
reveal_type(hp.precise)  # noqa: F821  -> PtrValue
hp.precise.deref(space)  # checker-visible on the precise view
hp.loose.deref(space)    # type: ignore  # int has no .deref to a checker
