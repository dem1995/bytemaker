"""bytemaker: C-style binary records and bit manipulation for Python.

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
u31`` just works. :mod:`bytemaker.fields` resolves those names lazily. The
sub-byte widths ``u1``..``u7`` and ``s1``..``s7`` are exported here by name,
because a bitfield width has no class spelling the way ``u8``..``u64`` do.
Type checkers read a named alias as an ``int`` field and a lazily resolved
one as ``Any``, so import an unusual width from :mod:`bytemaker.fields` when
its checker type matters.

Two layers build on the record. Both are exported from here or are one
import away.

* **Encoding conventions** live in :mod:`bytemaker.adapters`. An
  :class:`~bytemaker.adapters.Adapter` states a wire<->user transform in the
  schema rather than at every call site. Apply it per field, or fuse it
  onto a wire type with ``@``::

      class SkillEntry(Struct, endian="little"):
          reward_id:  int   = field(UInt8, adapt=biased(1))  # wire = id + 1
          multiplier: float = field(UInt16, adapt=fixed(4))  # 0x10 == 1.0

* **Where records live** is :mod:`bytemaker.spaces`, imported separately as
  ``from bytemaker.spaces import Space, Ptr``. A :class:`~bytemaker.spaces.Space`
  is a base-mapped address space, so reads are by address and the byte
  order is stated once. A :class:`~bytemaker.spaces.Ptr` is a typed address
  that can be followed and audited. A :class:`~bytemaker.spaces.Patch` turns
  an edit into a value you can verify, invert and export::

      rom  = Space(data, base=0x08000000, endian="little")
      recs = rom.read(0x08526390, BossRushReward, 3)
      print(rom.coverage(ROM_MAP).render())   # claims, overlaps, gaps

:func:`layout`, :func:`fields_of` and :func:`sizeof` answer shape and size
questions for any of it; they live in :mod:`bytemaker.introspect`.

The legacy ``@dataclass`` aggregate API lives in
:mod:`bytemaker.conversions.aggregate_types`.
"""

import os
from typing import Any, Optional

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
    s1,
    s2,
    s3,
    s4,
    s5,
    s6,
    s7,
    s8,
    s16,
    s32,
    s64,
    u1,
    u2,
    u3,
    u4,
    u5,
    u6,
    u7,
    u8,
    u16,
    u32,
    u64,
)
from bytemaker.introspect import (
    FieldInfo,
    FieldSpan,
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
    "FieldSpan",
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
    "u1",
    "u2",
    "u3",
    "u4",
    "u5",
    "u6",
    "u7",
    "u8",
    "u16",
    "u32",
    "u64",
    "s1",
    "s2",
    "s3",
    "s4",
    "s5",
    "s6",
    "s7",
    "s8",
    "s16",
    "s32",
    "s64",
    "f16",
    "f32",
    "f64",
]

# The version this package reports about itself. The distribution metadata
# consulted below replaces it only when that metadata describes this very
# directory. test_version_fallback_matches_pyproject keeps the literal in
# step with pyproject.toml.
__version__ = "0.13.0.dev0"


def _installed_version() -> Optional[str]:
    """Return the installed distribution's version when its files are this package.

    ``importlib.metadata`` finds a distribution by name, and the name says
    nothing about which files were imported. A source checkout imported ahead
    of an older release in site-packages is one example: the metadata then
    describes that release, while the code that imported is the checkout.
    The version is therefore used only when the distribution locates its
    ``bytemaker`` package at this file's directory. Otherwise, or when no
    distribution is found, the result is None and the literal above stands.
    """
    try:
        from importlib import metadata

        dist = metadata.distribution("bytemaker")
        located = os.path.realpath(str(dist.locate_file("bytemaker")))
    except Exception:
        return None
    here = os.path.realpath(os.path.dirname(__file__))
    if os.path.normcase(located) != os.path.normcase(here):
        return None
    return dist.version


_installed = _installed_version()
if _installed is not None:
    __version__ = _installed
del _installed


_ALIAS_PATTERN = None  # compiled on first miss


def __getattr__(name: str) -> Any:
    """Resolve ``u31``/``s9``-style field aliases lazily via
    :mod:`bytemaker.fields` (any width, minted and cached there).

    The return type is ``Any`` because a type checker cannot know which
    alias a name will resolve to; the widths exported by name above keep
    their declared types.
    """
    global _ALIAS_PATTERN
    if _ALIAS_PATTERN is None:
        import re

        _ALIAS_PATTERN = re.compile(r"(u|s)([1-9][0-9]*)")
    if _ALIAS_PATTERN.fullmatch(name):
        from bytemaker import fields as _fields

        return getattr(_fields, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
