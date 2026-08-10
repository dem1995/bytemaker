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

An adapter can also be **fused onto** a wire type with ``@``, producing an
:class:`Adapted` codec that is usable anywhere a scalar BitType class is —
so the convention gets a name and is declared once::

    ThumbPtr = THUMB_PTR @ UInt32
    Mult     = fixed(4)  @ UInt16

    class SkillEntry(Struct, endian="little"):
        anim_fn:    Annotated[int, ThumbPtr]    # checker-visible
        multiplier: float = field(Mult)         # checker-visible
        table:      list  = array(ThumbPtr, 8)  # as an Array element

Ship functions, not lambdas: schema objects travel through
copy/pickle (``Array.__reduce__`` carries its adapter), so ``load``/
``store`` should be module-level callables or ``functools.partial`` of
one, as the factories here do.
"""

import typing
from functools import partial
from typing import Any, Callable, Generic, Optional, TypeVar

if typing.TYPE_CHECKING:  # annotation-only; adapters stays a runtime leaf
    from bytemaker.structs import Array

#: The USER-plane value type an adapter reads as. It is the adapter's, not
#: the wire type's: ``fixed(4)`` maps an int wire to a ``float`` user value,
#: so ``Array.of(fixed(4) @ UInt16, 8).parse(b)`` reads as ``list[float]``.
U = TypeVar("U")

#: The enum class :func:`enum_` reads members of.
_E = TypeVar("_E")

__all__ = [
    "Adapted",
    "Adapter",
    "THUMB_PTR",
    "biased",
    "enum_",
    "fixed",
    "scaled",
]


class Adapter(Generic[U]):
    """A frozen pair of inverse value transforms.

    The type parameter is the USER-plane value type (``Adapter[float]`` for
    ``fixed(4)``), which is what a fused :class:`Adapted` and an adapted
    :class:`~bytemaker.structs.Array` report to a type checker.

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
    load: Callable[[Any], U]
    store: Callable[[U], Any]
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

    def __matmul__(self, base) -> "Adapted[U]":
        """``THUMB_PTR @ UInt32`` -> an :class:`Adapted` codec."""
        return Adapted(base, self)


class Adapted(Generic[U]):
    """A scalar wire type with an :class:`Adapter` fused on.

    Built with ``adapter @ BitTypeClass``. The result names the convention
    once and is then usable everywhere a scalar BitType class is — as a
    field annotation, inside ``Annotated[...]``, as ``field()``'s wire type,
    as an :class:`~bytemaker.structs.Array` element, and as an argument to
    ``sizeof``/``bitsizeof``::

        ThumbPtr = THUMB_PTR @ UInt32

        class Anim(Struct, endian="little"):
            update_fn: Annotated[int, ThumbPtr]   # the real (even) address
            frames:    list = array(ThumbPtr, 4)

    This is pure sugar over ``adapt=``: ``field(THUMB_PTR @ UInt32)`` and
    ``field(UInt32, adapt=THUMB_PTR)`` compile to the identical layout,
    descriptors and bytes. The engine unwraps an ``Adapted`` at class
    definition time, so the plan layer never sees one.

    **Type-checking a fused field.** A fused codec is a *value*, not a
    class, so the terse ``update_fn: ThumbPtr`` spelling works at runtime
    but is not a valid *type* to a checker — the same trade-off as
    ``Elem * N`` for arrays. (Nor would a subscript hook help:
    ``ThumbPtr[int]`` could be made to work at runtime, but a checker never
    evaluates a variable in a type position, so the field would silently go
    untyped. bytemaker deliberately does not offer that spelling.) The two
    checked forms are ``Annotated[<plain type>, ThumbPtr]`` and
    ``field(ThumbPtr)`` with the plain annotation; the plain type is the
    ADAPTER's user-plane type (``int`` for ``THUMB_PTR``, ``float`` for
    ``fixed(4)``), which ``field()`` also verifies.

    For a convention used more than once, bind the ANNOTATION to a
    module-level alias — the array analog of ``Colors8``. This is both the
    terse form and the checked one::

        ThumbPtr = THUMB_PTR @ UInt32          # the codec
        FnAddr   = Annotated[int, ThumbPtr]    # the field annotation

        class Anim(Struct, endian="little"):
            update_fn: FnAddr                  # reads as int
            next_fn:   FnAddr

    See ``test/_typing_repro.py`` for the mypy contract.

    Equality and hashing are by IDENTITY (an :class:`Adapter` is too, since
    two ``fixed(4)`` calls build distinct transform pairs). Bind the fused
    codec to a module-level name and reuse it: ``Array.of``'s cache then
    shares one Array object across every declaration that uses it.
    """

    __slots__ = ("base", "adapter")

    base: Any
    adapter: Adapter[U]

    def __init__(self, base, adapter):
        from bytemaker.bittypes.bittype import BitType  # keep this a leaf module

        if isinstance(base, Adapted):
            raise TypeError(
                f"cannot adapt an already-adapted codec ({base!r}); compose"
                f" the two transforms into one Adapter explicitly"
            )
        if not (isinstance(base, type) and issubclass(base, BitType)):
            raise TypeError(
                f"{getattr(adapter, 'name', adapter)!r} @ {base!r}: adapters"
                f" fuse onto a scalar BitType class only — a nested Struct"
                f" adapts its own fields, and an Array adapts its ELEMENTS"
                f" (adapter @ element, then Array.of(...))"
            )
        if not isinstance(adapter, Adapter):
            raise TypeError(f"expected an Adapter, got {adapter!r}")
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "adapter", adapter)

    def __setattr__(self, name, value):
        raise AttributeError(
            "Adapted is frozen (schema objects are shared); build a new one"
        )

    @property
    def num_bits(self) -> int:
        return self.base.num_bits

    @property
    def num_bytes(self) -> int:
        return (self.base.num_bits + 7) // 8

    @property
    def py_type(self):
        """The user-plane value type: the adapter's, else the base's."""
        return self.adapter.py_type or getattr(self.base, "py_type", None)

    def __repr__(self):
        return f"{self.adapter.name}@{self.base.__name__}"

    def __reduce__(self):
        return (Adapted, (self.base, self.adapter))

    def __mul__(self, count: int) -> "Array[U]":
        """``ThumbPtr * 4`` -> ``Array.of(ThumbPtr, 4)``, as for a BitType."""
        from bytemaker.structs import Array  # keep this a leaf module

        return Array.of(self, count)

    __rmul__ = __mul__


# ------------------------------------------------------------------ shipped
def _thumb_load(wire):
    return wire & ~1


def _thumb_store(user):
    return user | 1


THUMB_PTR: "Adapter[int]" = Adapter(_thumb_load, _thumb_store, int, "THUMB_PTR")
"""ARM/THUMB function pointer: bit 0 on the wire selects the THUMB
instruction set; the user value is the real (even) code address. Reading
masks bit 0 off; writing sets it (THUMB code, the common case in GBA
ROMs — for an ARM-code pointer, use the raw field)."""


def _fixed_load(wire, scale):
    return wire / scale


def _fixed_store(user, scale):
    return round(user * scale)


def fixed(frac_bits: int) -> "Adapter[float]":
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


def biased(bias: int) -> "Adapter[int]":
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


def scaled(step) -> "Adapter[Any]":
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


def enum_(enum_cls: "type[_E]") -> "Adapter[_E]":
    """Read wire values as members of ``enum_cls``; store members (or
    valid plain values, validated through the enum)."""
    return Adapter(
        enum_cls,  # E(wire) -> member; classes pickle by reference
        partial(_enum_store, enum_cls=enum_cls),
        enum_cls,
        f"enum({enum_cls.__name__})",
    )
