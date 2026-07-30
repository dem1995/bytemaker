"""bytemaker — C-style binary records and bit manipulation for Python.

The headline API is :class:`Struct`::

    from bytemaker import Struct, String, u8, u16

    MonName = String.of(nbytes=4, encoding=MON_TABLE, terminator=0x50)

    class Monster(Struct, endian="little"):
        name:    MonName
        species: u8
        hp:      u16

    m = Monster.parse(rom[0x100:0x107])

Fields hold plain Python values (``int``/``float``/``str``/``bytes``);
stores narrow or validate C-style; ``pack()``/``parse()`` ride a layout
plan compiled once at class definition. ``uN``/``sN`` field aliases exist
for any width — ``from bytemaker import u31`` just works (resolved lazily
via :mod:`bytemaker.fields`).

The legacy ``@dataclass`` aggregate API lives in
:mod:`bytemaker.conversions.aggregate_types`.
"""

from bytemaker.bittypes import (
    BitType,
    Buffer,
    Float,
    Float16,
    Float32,
    Float64,
    Int,
    SInt,
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    StandardEncodingString,
    String,
    TableString,
    UInt,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    UTF8String,
)
from bytemaker.bitvector import (
    BitsCastable,
    BitsConstructible,
    BitVector,
    FixedLengthBitVector,
)
from bytemaker.plans import Plan, PlanCompileError
from bytemaker.structs import Array, NarrowingConfig, NarrowingWarning, Struct

__all__ = [
    "Struct",
    "Array",
    "Plan",
    "PlanCompileError",
    "NarrowingConfig",
    "NarrowingWarning",
    "BitVector",
    "FixedLengthBitVector",
    "BitsCastable",
    "BitsConstructible",
    "BitType",
    "Int",
    "UInt",
    "SInt",
    "Float",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
    "SInt8",
    "SInt16",
    "SInt32",
    "SInt64",
    "Float16",
    "Float32",
    "Float64",
    "String",
    "StandardEncodingString",
    "TableString",
    "UTF8String",
    "Buffer",
]

try:  # absent on Python 3.8 without typing_extensions (no Annotated)
    from bytemaker.fields import (  # noqa: F401
        f16,
        f32,
        f64,
        s8,
        s16,
        s32,
        s64,
        u8,
        u16,
        u32,
        u64,
    )

    __all__ += [
        "u8", "u16", "u32", "u64",
        "s8", "s16", "s32", "s64",
        "f16", "f32", "f64",
    ]
except ImportError:  # pragma: no cover - version-dependent
    pass

try:
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("bytemaker")
except Exception:  # pragma: no cover - uninstalled source checkout
    __version__ = "0+unknown"


_ALIAS_PATTERN = None  # compiled on first miss


def __getattr__(name: str):
    """Resolve ``u31``/``s5``-style field aliases lazily via
    :mod:`bytemaker.fields` (any width, minted and cached there)."""
    global _ALIAS_PATTERN
    if _ALIAS_PATTERN is None:
        import re

        _ALIAS_PATTERN = re.compile(r"(u|s)([1-9][0-9]*)")
    if _ALIAS_PATTERN.fullmatch(name):
        from bytemaker import fields as _fields

        return getattr(_fields, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
