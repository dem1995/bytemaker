"""bytemaker — C-style binary records and bit manipulation for Python.

The headline API is :class:`Struct`::

    from bytemaker import Struct, String, u8, u16

    MonName = String.of(nbytes=4, encoding=MON_TABLE, terminator=0x50)

    class Monster(Struct, endian="little"):
        name:    MonName
        species: u8
        hp:      u16

    m = Monster.parse(rom[0x100:0x107])

Fields hold plain Python values: ``int``, ``float``, ``str`` and ``bytes``.
Stores narrow or validate C-style. ``pack()`` and ``parse()`` run a layout
plan compiled once at class definition.

``uN``/``sN`` field aliases exist for any width, so ``from bytemaker import
u31`` just works. :mod:`bytemaker.fields` resolves those names lazily.

Two layers build on the record. Both are exported from here or are one
import away.

* **Encoding conventions** — :mod:`bytemaker.adapters`. An
  :class:`~bytemaker.adapters.Adapter` states a wire↔user transform in the
  schema rather than at every call site. Apply it per field, or fuse it
  onto a wire type with ``@``::

      class SkillEntry(Struct, endian="little"):
          reward_id:  int   = field(UInt8, adapt=biased(1))  # wire = id + 1
          multiplier: float = field(UInt16, adapt=fixed(4))  # 0x10 == 1.0

* **Where records live** — :mod:`bytemaker.rom`, imported separately as
  ``from bytemaker.rom import Space, Ptr``. A :class:`~bytemaker.rom.Space`
  is a base-mapped address space, so reads are by address and the byte
  order is stated once. A :class:`~bytemaker.rom.Ptr` is a typed address
  that can be followed and audited. A :class:`~bytemaker.rom.Patch` turns
  an edit into a value you can verify, invert and export::

      rom  = Space(data, base=0x08000000, endian="little")
      recs = rom.read(0x08526390, BossRushReward, 3)
      print(rom.coverage(ROM_MAP).render())   # claims, overlaps, gaps

:func:`layout`, :func:`fields_of` and :func:`sizeof` answer shape and size
questions for any of it; they live in :mod:`bytemaker.introspect`.

The legacy ``@dataclass`` aggregate API lives in
:mod:`bytemaker.conversions.aggregate_types`.
"""

from bytemaker.adapters import (
    THUMB_PTR,
    Adapted,
    Adapter,
    biased,
    enum_,
    fixed,
    scaled,
)
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
from bytemaker.fields import (
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
from bytemaker.introspect import (
    FieldInfo,
    bitsizeof,
    fields_of,
    layout,
    offset_of,
    sizeof,
    span_of,
)
from bytemaker.plans import PlanCompileError
from bytemaker.structs import (
    Array,
    NarrowingConfig,
    NarrowingWarning,
    Struct,
    array,
    field,
)

__all__ = [
    "Struct",
    "Array",
    "field",
    "array",
    "sizeof",
    "bitsizeof",
    "fields_of",
    "layout",
    "offset_of",
    "span_of",
    "FieldInfo",
    "Adapter",
    "Adapted",
    "THUMB_PTR",
    "biased",
    "enum_",
    "fixed",
    "scaled",
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
    "u8", "u16", "u32", "u64",
    "s8", "s16", "s32", "s64",
    "f16", "f32", "f64",
]

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
