"""Per-field value adapters: declarative wire <-> user transforms.

An :class:`Adapter` attaches an encoding convention to a schema instead of
leaking it into every call site::

    from bytemaker import Struct, UInt8, UInt16, UInt32, field
    from bytemaker.adapters import THUMB_PTR, biased, fixed

    class SkillEntry(Struct, endian="little"):
        anim_fn:    int   = field(UInt32, adapt=THUMB_PTR)   # bit 0 = THUMB
        multiplier: float = field(UInt16, adapt=fixed(4))    # 0x10 == 1.0
        reward_id:  int   = field(UInt8,  adapt=biased(1))   # stored id+1

``load`` maps the wire value (what the plan engine stores in the slot) to
the user value the field reads as; ``store`` is its inverse, applied on
assignment BEFORE the usual C-style narrowing of the wire value. The
serialized bytes always carry the wire value, so ``parse -> pack`` stays
the identity even for values a lossy ``store`` would canonicalize.

The two planes remain visible on a :class:`~bytemaker.structs.BoundField`
handle: ``.value`` reads/writes the user plane; ``.bits`` and ``.boxed()``
are the wire plane (the box is a serialization object).

Adapters also apply element-wise to a STANDALONE :class:`Array`
(``Array.of(UInt32, n, adapt=THUMB_PTR)``); an adapted Array as a Struct
*field* is rejected at class definition (the live fixed-length list a
field hands out does not thread adapters yet).

Ship functions, not lambdas: schema objects travel through
copy/pickle (``Array.__reduce__`` carries its adapter), so ``load``/
``store`` should be module-level callables or ``functools.partial`` of
one, as the factories here do.
"""

from functools import partial
from typing import Any, Callable, Optional

__all__ = [
    "Adapter",
    "THUMB_PTR",
    "biased",
    "enum_",
    "fixed",
    "scaled",
]


class Adapter:
    """A frozen pair of inverse value transforms.

    Args:
        load: wire value -> user value (applied on read/parse).
        store: user value -> wire value (applied on write/pack, before
            the field's normal wire narrowing).
        py_type: the user-plane type the field reads as, used to check a
            ``field()`` declaration's plain annotation (None skips it).
        name: display name for reprs.
    """

    __slots__ = ("load", "store", "py_type", "name")

    # (assigned via object.__setattr__ in __init__; the class is frozen)
    load: Callable[[Any], Any]
    store: Callable[[Any], Any]
    py_type: Optional[type]
    name: str

    def __init__(self, load, store, py_type=None, name=None):
        if not callable(load) or not callable(store):
            raise TypeError("Adapter load and store must both be callable")
        object.__setattr__(self, "load", load)
        object.__setattr__(self, "store", store)
        object.__setattr__(self, "py_type", py_type)
        object.__setattr__(self, "name", name or "adapter")

    def __setattr__(self, name, value):
        raise AttributeError(
            "Adapter is frozen (schema objects are shared); build a new one"
        )

    def __repr__(self):
        return f"<Adapter {self.name}>"

    def __reduce__(self):
        return (Adapter, (self.load, self.store, self.py_type, self.name))


# ------------------------------------------------------------------ shipped
def _thumb_load(wire):
    return wire & ~1


def _thumb_store(user):
    return user | 1


THUMB_PTR = Adapter(_thumb_load, _thumb_store, int, "THUMB_PTR")
"""ARM/THUMB function pointer: bit 0 on the wire selects the THUMB
instruction set; the user value is the real (even) code address. Reading
masks bit 0 off; writing sets it (THUMB code, the common case in GBA
ROMs — for an ARM-code pointer, use the raw field)."""


def _fixed_load(wire, scale):
    return wire / scale


def _fixed_store(user, scale):
    return round(user * scale)


def fixed(frac_bits: int) -> Adapter:
    """Unsigned/two's-complement fixed-point with ``frac_bits`` fractional
    bits: wire ``0x10`` with ``fixed(4)`` reads as ``1.0``. Stores round
    to the nearest representable step."""
    if not isinstance(frac_bits, int) or frac_bits < 1:
        raise ValueError(f"frac_bits must be a positive int, got {frac_bits!r}")
    scale = 1 << frac_bits
    return Adapter(
        partial(_fixed_load, scale=scale),
        partial(_fixed_store, scale=scale),
        float,
        f"fixed(q{frac_bits})",
    )


def _biased_load(wire, bias):
    return wire - bias


def _biased_store(user, bias):
    return user + bias


def biased(bias: int) -> Adapter:
    """The wire carries ``user + bias`` (e.g. ``biased(1)`` for tables
    that store ``global_id + 1`` so 0 can mean "none")."""
    return Adapter(
        partial(_biased_load, bias=bias),
        partial(_biased_store, bias=bias),
        int,
        f"biased({bias:+d})",
    )


def _scaled_load(wire, step):
    return wire * step


def _scaled_store(user, step):
    wire = user / step
    rounded = round(wire)
    if rounded * step != user:
        raise ValueError(
            f"{user!r} is not a multiple of the wire step {step!r}"
        )
    return rounded


def scaled(step) -> Adapter:
    """The wire counts in units of ``step``: user = wire * step. Stores
    require an exact multiple (raising beats silently landing on a
    different wire value)."""
    if step == 0:
        raise ValueError("step must be nonzero")
    return Adapter(
        partial(_scaled_load, step=step),
        partial(_scaled_store, step=step),
        None,  # int step -> int user, fractional step -> float; unchecked
        f"scaled({step!r})",
    )


def _enum_store(value, enum_cls):
    if isinstance(value, enum_cls):
        return value.value
    return enum_cls(value).value  # validates plain ints against the enum


def enum_(enum_cls) -> Adapter:
    """Read wire values as members of ``enum_cls``; store members (or
    valid plain values, validated through the enum)."""
    return Adapter(
        enum_cls,  # E(wire) -> member; classes pickle by reference
        partial(_enum_store, enum_cls=enum_cls),
        enum_cls,
        f"enum({enum_cls.__name__})",
    )
