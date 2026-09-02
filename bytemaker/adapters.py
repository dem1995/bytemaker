"""Per-field value adapters: declarative wire <-> user transforms.

An :class:`Adapter` states an encoding convention once, in the schema,
rather than repeating it at every call site::

    from bytemaker import Struct, UInt8, UInt16, UInt32, field
    from bytemaker.adapters import THUMB_PTR, biased, fixed

    class SkillEntry(Struct, endian="little"):
        anim_fn:    int   = field(UInt32, adapt=THUMB_PTR)   # bit 0 = THUMB
        multiplier: float = field(UInt16, adapt=fixed(4))    # 0x10 == 1.0
        reward_id:  int   = field(UInt8,  adapt=biased(1))   # stored id+1

An adapted field has two planes. The wire value is what the plan engine
stores in the slot, and the user value is what the field reads as.
``load`` maps wire to user on read and parse. ``store`` is its inverse,
applied on assignment before the usual C-style narrowing.

The serialized bytes always hold the wire value. ``parse -> pack`` is
therefore the identity even when a lossy ``store`` would canonicalize the
value.

Both planes stay available on a :class:`~bytemaker.structs.BoundField`
handle. ``.value`` reads and writes the user plane, while ``.bits`` and
``.boxed()`` are the wire plane.

Adapters also apply element-wise to an :class:`Array`, either standalone
(``Array.of(UInt32, n, adapt=THUMB_PTR)``) or as a Struct field
(``array(THUMB_PTR @ UInt32, n)``). Arrays and scalars differ in one way
worth knowing. An array field's slot holds user-plane elements, so its
loads run when the record is built, and its elements re-encode through
``store`` on ``pack``. A wire value the adapter cannot represent exactly
is canonicalized as a result. A scalar adapted field keeps the wire value
in its slot instead, so its load is deferred to the read, and
``parse -> pack`` is byte-exact whether or not ``store`` is lossy. See
:class:`~bytemaker.structs.Array` for the full note.

An adapter can also be fused onto a wire type with ``@``. The result is an
:class:`Adapted` codec, usable anywhere a scalar BitType class is, and it
names the convention once::

    ThumbPtr = THUMB_PTR @ UInt32
    Mult     = fixed(4)  @ UInt16

    class SkillEntry(Struct, endian="little"):
        anim_fn:    Annotated[int, ThumbPtr]    # checker-visible
        multiplier: float = field(Mult)         # checker-visible
        table:      list  = array(ThumbPtr, 8)  # as an Array element

:class:`bytemaker.spaces.Ptr` also fuses an adapter onto a wire integer, and
one rule decides between it and this module: **if the value is an address,
use** ``Ptr``. A ``Ptr`` also records what the address points at, so
``space.deref`` can follow it and ``space.coverage`` can audit it. Use
``adapter @ base`` for value conventions such as fixed-point, bias and
enums. Use ``Ptr(target, adapt=...)`` to put a convention on an address,
such as a THUMB function pointer. An address fused with plain ``@`` still
decodes correctly, but the pointer audit will not see it.

Pass functions rather than lambdas. Schema objects are copied and pickled,
and ``Array.__reduce__`` includes its adapter, so ``load`` and ``store``
should be module-level callables or a ``functools.partial`` of one. The
factories in this module are written that way.
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

    The type parameter is the user-plane value type, so ``fixed(4)`` is an
    ``Adapter[float]``. That is the type a fused :class:`Adapted` and an
    adapted :class:`~bytemaker.structs.Array` report to a type checker.

    Args:
        load: wire value -> user value, applied on read and parse.
        store: user value -> wire value, applied on write and pack,
            before the field's normal wire narrowing.
        py_type: the user-plane type the field reads as. It is used to
            check the plain annotation on a ``field()`` declaration, and
            None skips that check.
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
    once, and is then usable everywhere a scalar BitType class is: as a
    field annotation, inside ``Annotated[...]``, as ``field()``'s wire
    type, as an :class:`~bytemaker.structs.Array` element, and as an
    argument to ``sizeof``/``bitsizeof``::

        ThumbPtr = THUMB_PTR @ UInt32

        class Anim(Struct, endian="little"):
            update_fn: Annotated[int, ThumbPtr]   # the real (even) address
            frames:    list = array(ThumbPtr, 4)

    This is sugar over ``adapt=``. ``field(THUMB_PTR @ UInt32)`` and
    ``field(UInt32, adapt=THUMB_PTR)`` compile to the same layout,
    descriptors and bytes. The engine unwraps an ``Adapted`` at class
    definition time, so the plan layer never receives one.

    **Type-checking a fused field.** A fused codec is a value rather than a
    class. The terse ``update_fn: ThumbPtr`` spelling therefore works at
    runtime but is not a valid type to a checker. Arrays make the same
    trade-off with ``Elem * N``.

    The two checked forms are ``Annotated[<plain type>, ThumbPtr]`` and
    ``field(ThumbPtr)`` with a plain annotation. The plain type is the
    adapter's user-plane type: ``int`` for ``THUMB_PTR``, ``float`` for
    ``fixed(4)``. ``field()`` verifies that annotation.

    For a convention used more than once, bind the annotation to a
    module-level alias. That spelling is both the terse form and the
    checked one::

        ThumbPtr = THUMB_PTR @ UInt32          # the codec
        FnAddr   = Annotated[int, ThumbPtr]    # the field annotation

        class Anim(Struct, endian="little"):
            update_fn: FnAddr                  # reads as int
            next_fn:   FnAddr

    bytemaker deliberately offers no ``ThumbPtr[int]`` subscript. It could
    be made to work at runtime, but a checker never evaluates a variable in
    a type position, so the field would silently go untyped. See
    ``test/_typing_repro.py`` for the mypy contract.

    Equality and hashing are by identity, and an :class:`Adapter` compares
    by identity too, because two ``fixed(4)`` calls build distinct
    transform pairs. Bind a fused codec to a module-level name and reuse
    it, so ``Array.of``'s cache shares one Array object across every
    declaration that uses it.
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
                f" fuse onto a scalar BitType class only; a nested Struct"
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
        """The user-plane value type: the adapter's if it declares one, else the
        base's."""
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
ROMs; for an ARM-code pointer, use the raw field)."""


def _fixed_load(wire, scale):
    return wire / scale


def _fixed_store(user, scale):
    return round(user * scale)


def fixed(frac_bits: int) -> "Adapter[float]":
    """Fixed-point with ``frac_bits`` fractional bits, unsigned or two's
    complement. With ``fixed(4)``, wire ``0x10`` reads as ``1.0``. Stores
    round to the nearest representable step."""
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
    """The wire carries ``user + bias``. Use ``biased(1)`` for a table that
    stores ``global_id + 1`` so that 0 can mean "none"."""
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
        raise ValueError(f"{user!r} is not a multiple of the wire step {step!r}")
    return rounded


def scaled(step) -> "Adapter[Any]":
    """The wire counts in units of ``step``, so user = wire * step. A store
    requires an exact multiple, because raising is better than silently
    landing on a different wire value."""
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
    """Read wire values as members of ``enum_cls``. A store accepts a member,
    or a plain value validated by constructing the member from it."""
    return Adapter(
        enum_cls,  # E(wire) -> member; classes pickle by reference
        partial(_enum_store, enum_cls=enum_cls),
        enum_cls,
        f"enum({enum_cls.__name__})",
    )
