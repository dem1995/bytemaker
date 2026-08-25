"""Checker-friendly Struct field aliases, for any width.

``u8``/``s16``-style names are ``Annotated[int, UInt8]`` (etc.) at runtime,
and ``f16``/``f32``/``f64`` are ``Annotated[float, Float16]`` (etc.). The
annotation tells a type checker that the field holds a plain ``int`` or
``float``, which is what ``Struct`` fields hold, while the metadata carries
the BitType for the plan compiler.

Any integer width works, not just the pre-declared ones. This module
resolves ``uN``/``sN`` lazily through a PEP 562 module ``__getattr__``, so
an import like this one just works::

    from bytemaker.fields import u31, s5

Canonical named classes (``UInt4``, ``SInt5``, ...) are reused when they
exist. Other widths are minted via ``specialize`` and cached, so repeated
lookups agree. ``dir()`` and autocomplete advertise the common widths from
1 to 64 as a sample, but the lazy namespace itself is unbounded. Float
aliases are the fixed IEEE set (``f16`` / ``f32`` / ``f64``), because an
arbitrary float width does not determine an exponent/mantissa split.

The paired ``fields.pyi`` presents these to type checkers as descriptor
types. Reads are ``int``/``float``. Writes accept anything the narrowing
store accepts, including BitType boxes via ``__index__``, and so do the
synthesized ``__init__`` parameters (per dataclass_transform).
"""

import re

import bytemaker.bittypes as _bittypes
from bytemaker.bittypes import SInt, UInt
from bytemaker.typing_redirect import Annotated

__all__ = [
    "u8",
    "u16",
    "u32",
    "u64",
    "s8",
    "s16",
    "s32",
    "s64",
    "f16",
    "f32",
    "f64",
]

from bytemaker.bittypes import (  # noqa: E402
    Float16,
    Float32,
    Float64,
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
)

u8 = Annotated[int, UInt8]
u16 = Annotated[int, UInt16]
u32 = Annotated[int, UInt32]
u64 = Annotated[int, UInt64]
s8 = Annotated[int, SInt8]
s16 = Annotated[int, SInt16]
s32 = Annotated[int, SInt32]
s64 = Annotated[int, SInt64]
f16 = Annotated[float, Float16]
f32 = Annotated[float, Float32]
f64 = Annotated[float, Float64]


_ALIAS_PATTERN = re.compile(r"(u|s)([1-9][0-9]*)")
_alias_cache = {}
_BASE_OF = {"u": UInt, "s": SInt}


def __getattr__(name):
    match = _ALIAS_PATTERN.fullmatch(name)
    if match is None:
        if name[:1] == "f" and name[1:].isdigit():
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}: float aliases"
                f" are the fixed IEEE set f16/f32/f64 (an arbitrary bit width"
                f" does not determine an exponent/mantissa split); for a custom"
                f" split use Float.specialize"
            )
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        return _alias_cache[name]
    except KeyError:
        pass
    base = _BASE_OF[match.group(1)]
    width = int(match.group(2))
    # Reuse the canonical named class when one exists (identity matters for
    # schema introspection); mint-and-cache other widths.
    bittype = getattr(_bittypes, f"{base.__name__}{width}", None)
    if bittype is None:
        bittype = base.specialize(width, name_=f"{base.__name__}{width}")
    alias = Annotated[int, bittype]
    _alias_cache[name] = alias
    return alias


def __dir__():
    # dir() cannot enumerate the unbounded lazy namespace; advertise the
    # common 1..64 widths as a sample (__getattr__ accepts any positive
    # width).
    lazy = [f"{prefix}{n}" for prefix in ("u", "s") for n in range(1, 65)]
    return sorted(set(list(globals()) + __all__ + lazy))
