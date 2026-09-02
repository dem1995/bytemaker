"""
Struct: fixed-layout records with plain-Python field values.

Declaration looks like a dataclass whose annotations name each field's wire
type, and the runtime values ARE plain ints/floats::

    from bytemaker import Struct, s16, u16, u32

    class WarpDestination(Struct, endian="little"):
        room_ptr: u32
        x:        u16
        y:        u16
        x_offset: s16
        y_offset: s16

    d = WarpDestination.parse(data)   # slots-backed instance, plain-int fields
    d.x = 0x10005                     # narrows C-style at the store -> 5
    d.pack()                          # trusts the store-time invariant
    table = (WarpDestination * 3).parse(b36)   # -> list[WarpDestination]

The ``uN``/``sN``/``fN`` aliases are ``Annotated[int, BitTypeClass]``, so a
checker reads each field as the plain value the slot holds. Name a nested
Struct directly; give text, bytes and arrays a plain annotation plus
``field(...)`` / ``array(...)``. A bare BitType class (``x: UInt16``) also
works at runtime, but a checker then types the field as the box rather than
the value in the slot, and flags ``d.x = 5``. ``test/_typing_repro.py`` is
the contract.

Key semantics (all decided at class-creation time; see bytemaker.plans for
the engine/tier rules):

* Fields hold **plain** ``int``/``float`` values in ``__slots__``; a data
  descriptor per field narrows integer stores C-style (wrap, at any bit
  width) exactly once, at the store, including ``__init__``. ``parse``
  bypasses the descriptors (decoded values cannot be out of range).
* ``endian`` and ``bit_order`` are per-class, compile-time parameters.
  ``bit_order`` defaults to match ``endian`` ("lsb" under little, "msb"
  under big), the way C compilers allocate bitfields on a target of the
  same endianness. A format that mixes the two states it explicitly.
* A Struct class is itself a **codec**, with ``num_bits``, ``parse`` and
  ``pack`` (see :class:`Codec`). It is deliberately not a BitType subclass,
  because the BitType contract is scalar-shaped: a boxed ``.value``, a
  mutable ``bits`` setter and ``__init__(source, value, bits)`` do not fit
  a composite.
* Nested Struct fields are flattened into the parent's plan (keeping their
  own endianness); ``T * N`` builds an :class:`Array` codec.
* Bulk reads: ``T.plan.unpack_tuple`` and ``T.plan.iter_tuples`` yield
  flat tuples with no per-field materialization. A read on an instance goes
  through a Python-level descriptor call, so these are the faster path for
  a loop that only needs the values.

Set :data:`DEBUG_VALIDATE` (or the ``BYTEMAKER_DEBUG`` environment variable)
to re-validate every field range at ``pack`` time during migrations.
"""

from __future__ import annotations

import operator
import os
import struct as _pystruct
import typing
import weakref

# Straight from typing, not through typing_redirect: pyright's
# dataclass_transform field collection does not follow a re-exported alias of
# ClassVar. Routed through the redirect, Struct's ClassVars below become
# synthesized __init__ parameters, and every field a user declares reports
# "fields without default values cannot appear after fields with default
# values" in their editor. mypy follows the alias correctly, so the mypy gate
# cannot see a regression here; test/typing_regression_test.py pins the import.
from typing import ClassVar

from bytemaker.adapters import Adapted, Adapter
from bytemaker.bittypes import (
    BitType,
    Buffer,
    Int,
    SInt,
    String,
)
from bytemaker.bittypes.bittype import (
    NarrowingConfig,
    NarrowingWarning,
    _warn_narrowing,
)
from bytemaker.bitvector import BitVector
from bytemaker.plans import Plan, PlanCompileError, _classify_scalar, compile_plan
from bytemaker.typing_redirect import (
    Annotated,
    Any,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    dataclass_transform,
    get_args,
    get_origin,
    runtime_checkable,
)
from bytemaker.utils import unwrap_alias, validate_endianness

if typing.TYPE_CHECKING:
    from bytemaker.typing_redirect import Self

    _S = typing.TypeVar("_S", bound="Struct")

#: What the parse paths actually require of their input: len() and slicing.
#: (The abstract Buffer protocol guarantees neither, so the concrete union
#: is the honest annotation.)
BytesLike = typing.Union[bytes, bytearray, memoryview]

__all__ = [
    "Codec",
    "Struct",
    "StructMeta",
    "Array",
    "field",
    "array",
    "DEBUG_VALIDATE",
    "NarrowingConfig",
    "NarrowingWarning",
    "BoundField",
    "BoundBits",
    "NarrowingList",
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

DEBUG_VALIDATE = bool(os.environ.get("BYTEMAKER_DEBUG"))
"""When true, ``Struct.pack`` re-validates every field's range first."""


@runtime_checkable
class Codec(Protocol):
    """The structural protocol the composite schema objects satisfy.

    A codec maps ``num_bits // 8`` bytes to a value and back. ``parse(data)``
    decodes, and ``pack(value)`` encodes what ``parse`` returned.

    Struct classes satisfy it. ``parse`` is a classmethod and the value is
    the instance, so ``S.pack(s)`` is ``s.pack()``. :class:`Array` objects
    satisfy it too, and their values are lists.

    Scalar BitType classes do not. They define ``num_bits``, but they
    serialize through the constructor and ``bytes()``, so
    ``isinstance(UInt16, Codec)`` is False. Wrap a scalar in a Struct or an
    Array, both of which are codecs.

    ``runtime_checkable`` checks attribute presence only, so a Struct
    instance also passes ``isinstance``. Its bound ``pack()`` takes no
    value argument, though: the codec object for a Struct is the class
    itself.
    """

    num_bits: int

    def parse(self, data) -> Any: ...

    def pack(self, value) -> bytes: ...


# --------------------------------------------------------------------------
# Field descriptors: narrowing happens here, exactly once, at the store.
# --------------------------------------------------------------------------


#: Builtin exception families an attributed wrapper preserves, most-derived
#: first. A caller who wrote ``except KeyError`` around a table adapter must
#: still catch after attribution, because losing the family is losing
#: the caller's error handling. ValueError is the default for anything unlisted.
_EXC_FAMILIES = (
    TypeError,
    KeyError,
    IndexError,
    LookupError,
    AttributeError,
    ArithmeticError,
    OSError,
    RuntimeError,
)


def _attributed(exc, label: str):
    """``exc`` re-expressed with ``label`` prefixed to its message.

    The raised object is a wrapper carrying the attributed message. The
    caller always chains the intact original as ``__cause__``, and that
    chain is where the precise type and attributes live, not the wrapper.

    Two rules decide the wrapper's class:

    * The exact class, when it is a builtin constructed from one argument.
      The family and the message rebuild faithfully, and those are what the
      ``except`` clause and the error text depend on. Not every attribute
      survives: an ``AttributeError`` minted by the interpreter carries
      ``.name`` and ``.obj`` outside ``args``, so the wrapper's are None.
      The original's are intact on ``__cause__``, which is the fidelity
      channel throughout. Rebuilding any wider class of exception is
      unsafe. A multi-arg builtin makes the constructor fail, because
      ``UnicodeEncodeError`` takes five arguments. A user subclass that
      captures constructor args as attributes gets them silently replaced
      by the message string.
    * Otherwise the nearest builtin family (:data:`_EXC_FAMILIES`), so
      ``except KeyError`` around a ``TABLE.__getitem__`` adapter still
      catches whatever KeyError subclass the table raised. ValueError is
      the default, because it is what "this wire value is wrong" means.
    """
    msg = f"{label}: {exc}"
    cls = type(exc)
    if cls.__module__ == "builtins" and len(exc.args) == 1:
        try:
            return cls(msg)
        except Exception:  # noqa: BLE001 - a builtin ctor may still refuse
            pass
    for base in _EXC_FAMILIES:
        if isinstance(exc, base):
            return base(msg)
    return ValueError(msg)


def _unreadable(exc, prefix: str) -> str:
    """The ``<unreadable: why>`` marker for a field whose read raised.

    A repr must never raise, but reading a field can. An adapter's ``load``
    runs over whatever the bytes say, so one value the schema does not
    describe, such as ``enum_(E)`` over an undocumented wire byte, would
    otherwise break the repr of the whole record, and with it
    ``print(records)``, the first thing anyone does with a table they are
    still figuring out. The readable fields still render, and the
    unreadable one becomes this marker, which names the reason.

    This runs from the ``except`` path only, so its work costs nothing when
    every field reads. That includes stripping ``prefix``, the
    "Record.field: " that :func:`_raise_named` prepends, which is noise
    beside the field's own name in a repr. :meth:`Struct._bm_repr_of` and
    :meth:`BoundField.__repr__` share this function, because they read the
    same plane and so can fail the same way.

    The reason comes from ``args[0]`` when that is the message, rather than
    from ``str(exc)``. For a KeyError, ``str()`` is ``repr(args[0])``,
    which would quote the message and defeat the prefix strip. The
    type-name fallback runs after the strip, so a message-less exception,
    whose "R.v: " strips to nothing, still names its type instead of
    rendering blank.
    """
    args = exc.args
    if len(args) == 1 and isinstance(args[0], str):
        reason = args[0]
    else:
        reason = str(exc)
    if reason.startswith(prefix):
        reason = reason[len(prefix) :]
    return f"<unreadable: {reason or type(exc).__name__}>"


def _raise_named(slot, obj, exc):
    """Re-raise a field conversion error naming the record class and field.

    Both directions use it: a store-time narrowing or validation failure,
    and an adapter ``load`` failure on data the schema does not describe,
    which arrives via :class:`_AdaptedField`.

    Compile-time diagnostics always name their field. Runtime value errors
    previously surfaced bare, as in "'str' object cannot be interpreted as
    an integer", which names nothing on a 20-field record. The original
    message survives as the suffix and on ``__cause__``.
    """
    field_name = slot.__name__[4:]  # strip the "_bm_" slot prefix
    raise _attributed(exc, f"{type(obj).__name__}.{field_name}") from exc


class _UIntField:
    __slots__ = ("_slot", "_mask")

    def __init__(self, slot, mask):
        self._slot = slot
        self._mask = mask

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        try:
            iv = operator.index(value)
        except TypeError as exc:
            _raise_named(self._slot, obj, exc)
        v = iv & self._mask
        if NarrowingConfig.warn and v != iv:
            _warn_narrowing(iv, v, f"field {self._slot.__name__[4:]!r}")
        self._slot.__set__(obj, v)


class _SIntField:
    __slots__ = ("_slot", "_mask", "_sign_bit")

    def __init__(self, slot, mask, sign_bit):
        self._slot = slot
        self._mask = mask
        self._sign_bit = sign_bit

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        try:
            iv = operator.index(value)
        except TypeError as exc:
            _raise_named(self._slot, obj, exc)
        v = iv & self._mask
        if v >= self._sign_bit:
            v -= self._mask + 1
        if NarrowingConfig.warn and v != iv:
            _warn_narrowing(iv, v, f"field {self._slot.__name__[4:]!r}")
        self._slot.__set__(obj, v)


class _FloatField:
    __slots__ = ("_slot", "_ftype")

    def __init__(self, slot, ftype):
        self._slot = slot
        self._ftype = ftype

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        # Narrow through the codec so the stored value is exactly what pack()
        # serializes (D1): a Float32 field must not read back a full-width
        # double. Float64 narrowing is a no-op (native width).
        try:
            v = self._ftype(float(value)).value
        except (TypeError, ValueError) as exc:
            _raise_named(self._slot, obj, exc)
        self._slot.__set__(obj, v)


class _StrField:
    __slots__ = ("_slot", "_ftype")

    def __init__(self, slot, ftype):
        self._slot = slot
        self._ftype = ftype

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        # Encode-validates through the box (raising on overflow, per the
        # field type's truncate/pad policy) and canonicalizes: the slot
        # holds the post-round-trip str; pack() re-encodes trusting it.
        try:
            v = self._ftype(value).value
        except (TypeError, ValueError) as exc:
            _raise_named(self._slot, obj, exc)
        self._slot.__set__(obj, v)


class _BytesField:
    __slots__ = ("_slot", "_nbytes")

    def __init__(self, slot, nbytes):
        self._slot = slot
        self._nbytes = nbytes

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        try:
            v = bytes(value)
        except (TypeError, ValueError) as exc:
            _raise_named(self._slot, obj, exc)
        if len(v) != self._nbytes:
            raise ValueError(
                f"{type(obj).__name__}.{self._slot.__name__[4:]}: expected"
                f" exactly {self._nbytes} bytes, got {len(v)}"
            )
        self._slot.__set__(obj, v)


def _field_name_of(descriptor) -> Optional[str]:
    """The field name a Struct field descriptor was installed under, or
    None for anything that is not one.

    Class-level attribute access returns the descriptor, as in
    ``WarpPoint.room_ptr``. This function is what lets an API accept that
    attribute as a refactor-safe alternative to the name string. The name
    comes from the slot the descriptor wraps (``_bm_<field>``), the same
    derivation the narrowing warning uses.
    """
    inner = getattr(descriptor, "_inner", descriptor)  # _AdaptedField wraps
    slot = getattr(inner, "_slot", None)
    name = getattr(slot, "__name__", "")
    return name[4:] if name.startswith("_bm_") else None


class _AdaptedField:
    """Wraps a scalar field descriptor with an :class:`Adapter`.

    A read applies ``load`` to the slot's wire value. A write applies
    ``store`` to the user value and then runs the inner descriptor's usual
    wire narrowing. The slot always holds the wire value, and so do
    parse/pack and the generated tuple converters, which bypass
    descriptors.

    Both directions attribute their failures. A ``load`` can fail on data
    the schema does not describe; the canonical example is ``enum_(E)`` over
    a wire byte that is not a member. That failure surfaces on a plain
    attribute read, arbitrarily far from the ``parse`` that accepted the
    bytes, because parse fills slots wire-plane and never calls ``load``.
    An unattributed message would name neither the record nor the field.

    An adapter is user code, so both handlers catch ``Exception`` rather
    than a shortlist. A table adapter spelled ``Adapter(TABLE.__getitem__,
    ...)`` is the obvious way to decode a game's character table, and the
    most likely adapter after ``enum_``. It raises ``KeyError`` on
    precisely the undocumented byte this attribution exists for.

    Nothing is swallowed. :func:`_attributed` re-raises, keeping the
    exception's exact class for one-arg builtins and its builtin family
    otherwise, and it always chains the intact original as ``__cause__``.
    See that function's docstring for why subclasses are never rebuilt.
    """

    __slots__ = ("_inner", "_adapter")

    def __init__(self, inner, adapter):
        self._inner = inner
        self._adapter = adapter

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        wire = self._inner.__get__(obj, objtype)
        try:
            return self._adapter.load(wire)
        except Exception as exc:  # noqa: BLE001 - see the class docstring
            _raise_named(self._inner._slot, obj, exc)

    def __set__(self, obj, value):
        try:
            wire = self._adapter.store(value)
        except Exception as exc:  # noqa: BLE001 - see the class docstring
            _raise_named(self._inner._slot, obj, exc)
        self._inner.__set__(obj, wire)


def _elem_loader(load, label: str):
    """A whole-field element loader for an adapted Array field.

    An adapted array's slot holds user-plane values, so its elements are
    loaded in the generated ``_bm_from_tuple``. That function has no field
    context of its own, so a strict ``load`` over undocumented data would
    fail inside parse with a message naming nothing. Binding the
    ``"Record.field"`` label here keeps the attribution that
    :class:`_AdaptedField` gives a scalar, at one call per field per record
    rather than one per element.
    """

    def load_elems(values):
        try:
            return [load(v) for v in values]
        except Exception as exc:  # noqa: BLE001 - as _AdaptedField.__get__
            raise _attributed(exc, label) from exc

    return load_elems


def _elem_storer(store, label: str):
    """The pack-direction counterpart of :func:`_elem_loader`.

    An adapted array's slot is user-plane, so ``pack()`` re-encodes every
    element through ``store`` inside the generated ``_bm_to_tuple``. A
    mutable user value can have drifted since it was last stored into a
    state ``store`` refuses, so pack is one of the five places an element
    store can fail. Without this wrapper the failure would name neither
    the record nor the field.
    """

    def store_elems(values):
        try:
            return [store(v) for v in values]
        except Exception as exc:  # noqa: BLE001 - store is user code
            raise _attributed(exc, label) from exc

    return store_elems


class _StructField:
    __slots__ = ("_slot", "_child")

    def __init__(self, slot, child):
        self._slot = slot
        self._child = child

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        if not isinstance(value, self._child):
            raise TypeError(
                f"{type(obj).__name__}.{self._slot.__name__[4:]}: expected"
                f" a {self._child.__name__} instance, got {value!r}"
            )
        self._slot.__set__(obj, value)


class NarrowingList(list):
    """A fixed-length list that narrows every element at the store (D1) and
    refuses length change (R1 / :class:`FixedLengthBitVector`, list edition).

    Backs an :class:`Array` *field*. Item and length-preserving slice writes
    C-narrow each element through the element type and pass through;
    ``append``/``extend``/``insert``/``pop``/``remove``/``clear``/``del``/
    ``+=``/``*=`` and length-changing slice assignment raise. The field hands
    out this live object, so ``s.colors[0] = 70000`` narrows to ``4464`` in
    place, like a C lvalue, and a read never returns a value ``pack()``
    would not serialize. Reordering in place (``reverse``/``sort``) is allowed:
    it preserves length and the already-narrowed contents.
    """

    __slots__ = ("_arr", "_label")

    def __init__(self, arr, values, label: str = ""):
        # values are pre-coerced (Array._coerce_seq) or trusted (parse).
        super().__init__(values)
        self._arr = arr
        #: "Record.field", for attributing a failed element store. An Array
        #: is standalone-capable and so has no name of its own; the list a
        #: FIELD hands out is told the one it belongs to.
        self._label = label

    def _violation(self):
        # Attributed like a coercion error: on a 20-field record, "length is
        # invariant" without a field name is as anonymous as the element
        # errors used to be.
        where = f"{self._label}: " if self._label else ""
        return ValueError(
            f"{where}length is invariant ({len(self)} elements): an array"
            f" field is fixed-count; assign a full-length sequence to"
            f" replace it"
        )

    def _coerce(self, value):
        """``Array._coerce_one``, attributed to the owning record and field.

        A value crosses an array field's element type in five ways, and all
        five are attributed. Whole-list assignment and ``__init__`` go
        through :class:`_ArrayField`. Parse-time loads go through
        :func:`_elem_loader`, and pack-time stores through
        :func:`_elem_storer`. The element store lands here. Without the
        attribution, ``s.fns[0] = 99`` reports "99 is not a valid Terrain"
        and nothing more.
        """
        try:
            return self._arr._coerce_one(value)
        except Exception as exc:  # noqa: BLE001 - re-raised, attributed
            if not self._label:
                raise
            raise _attributed(exc, self._label) from exc

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            vals = [self._coerce(v) for v in value]
            span = len(range(*key.indices(len(self))))
            if len(vals) != span:
                raise self._violation()
            super().__setitem__(key, vals)
        else:
            super().__setitem__(key, self._coerce(value))

    def __delitem__(self, key):
        raise self._violation()

    def append(self, value):
        raise self._violation()

    def extend(self, values):
        raise self._violation()

    def insert(self, index, value):
        raise self._violation()

    def pop(self, index=-1):
        raise self._violation()

    def remove(self, value):
        raise self._violation()

    def clear(self):
        raise self._violation()

    def __iadd__(self, other):
        raise self._violation()

    def __imul__(self, count):
        raise self._violation()

    def __reduce__(self):
        # copy/deepcopy/pickle: rebuild via the constructor, never list's
        # default reduce (which repopulates an empty instance through the
        # guarded append/extend and would raise). Contents are already
        # coerced, so the constructor stores them as trusted. The label
        # rides along: a copied record's element stores must stay as
        # attributed as the original's.
        return (NarrowingList, (self._arr, list(self), self._label))


class _ArrayField:
    """Descriptor for an Array field.

    The slot holds a live :class:`NarrowingList`. Assignment snapshots the
    values into a fresh fixed-length list, so the caller's sequence is
    never aliased (per R1).

    The snapshot copies the list container and narrows numeric elements to
    plain values. Struct element instances are stored by reference rather
    than deep-copied, exactly as a scalar nested-Struct field does via
    :class:`_StructField`. Explicitly assigning one Struct instance into
    several records or slots therefore aliases it, deliberately.

    Defaults are the exception. ``__init__`` detach-copies Struct-valued
    defaults, scalar and array-element alike (see ``_generate_methods``),
    so default-constructed instances never share one. Numeric elements are
    immutable, so numeric arrays are fully independent."""

    __slots__ = ("_slot", "_arr", "_label")

    def __init__(self, slot, arr, label: str = ""):
        self._slot = slot
        self._arr = arr
        #: "Record.field", derived ONCE, at the descriptor's construction in
        #: StructMeta. Every other consumer (the generated from_tuple
        #: and to_tuple env, _elem_loader/_elem_storer, and every
        #: NarrowingList this field hands out) reads it from here.
        self._label = label

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        try:
            coerced = self._arr._coerce_seq(value)
        except Exception as exc:  # noqa: BLE001 - store may be user code
            # Exception, not a shortlist: _coerce_one runs the element
            # adapter's store, and a table adapter raises KeyError on the
            # value this attribution exists for. The reach matches
            # _AdaptedField's, since whole-list assignment and __init__ are
            # just the bulk spellings of the same store.
            _raise_named(self._slot, obj, exc)
        self._slot.__set__(obj, NarrowingList(self._arr, coerced, self._label))


# Annotation-only ClassVars (invisible to hasattr on the base) that the
# metaclass assigns per class; everything else reserved is caught by the
# hasattr-over-bases check (which auto-covers future API) or the _bm_ prefix.
_RESERVED_FIELD_NAMES = frozenset({"plan", "num_bits", "num_bytes"})

#: Every concrete Struct class, by class NAME, weakly, so REPL/test classes
#: vanish with their last reference. This is what :mod:`bytemaker.spaces`'s
#: deferred ``Ptr("Name")`` targets fall back on when the name is not bound
#: in the Ptr's own module: the cross-module case a map split over several
#: files hits constantly.
_STRUCT_REGISTRY: Dict[str, Any] = {}


def _structs_named(name: str) -> tuple:
    """All live concrete Struct classes named ``name``, sorted by module. The
    stable order matters only for error messages."""
    registered = _STRUCT_REGISTRY.get(name)
    if not registered:
        return ()
    return tuple(sorted(registered, key=lambda c: (getattr(c, "__module__", "") or "")))


# --------------------------------------------------------------------------
# Annotation resolution
# --------------------------------------------------------------------------


def _resolve_hints(cls) -> Dict[str, Any]:
    try:
        return typing.get_type_hints(cls, include_extras=True)
    except TypeError:  # pragma: no cover - pre-3.9 typing without extras
        return typing.get_type_hints(cls)


def _reject_endian_tag_metadata(owner: str, field_name: str, hint) -> None:
    """Refuse a byte-order string in Annotated metadata, and name the real
    spelling. It is the spelling a user is most likely to guess for
    per-field endianness, and it used to be ignored silently, producing
    record-order bytes."""
    if get_origin(hint) is not Annotated:
        return
    for meta in get_args(hint)[1:]:
        if isinstance(meta, str) and meta.lower() in ("big", "little", "be", "le"):
            raise PlanCompileError(
                f"{owner}.{field_name}: Annotated metadata {meta!r} looks"
                f" like a byte order and would be silently ignored;"
                f" per-field endianness is spelled"
                f" field(T, endian='big'/'little') (or array(T, n,"
                f" endian=...) for arrays)"
            )


def _is_wire_type(obj) -> bool:
    """True for anything the field machinery accepts as a wire type: a
    BitType class, an :class:`Adapted` codec, a Struct class, or an
    Array."""
    return isinstance(obj, (StructMeta, Array, Adapted)) or (
        isinstance(obj, type) and issubclass(obj, BitType)
    )


def _unwrap_annotation(owner: str, field: str, hint) -> Any:
    """``Annotated[int, UInt8]`` unwraps to ``UInt8``. A BitType, Adapted,
    Struct or Array passes through. Anything else is a compile error."""
    _reject_endian_tag_metadata(owner, field, hint)
    if get_origin(hint) is Annotated:
        for meta in get_args(hint)[1:]:
            if _is_wire_type(meta):
                return meta
        raise PlanCompileError(
            f"{owner}.{field}: Annotated[...] carries no BitType, Struct,"
            f" or Array in its metadata"
        )
    if _is_wire_type(hint):
        return hint
    raise PlanCompileError(
        f"{owner}.{field}: annotation {hint!r} is not a BitType class, a"
        f" Struct, an Array, or an Annotated[...] of one"
    )


def _reject_foreign_value_override(owner: str, field_name: str, ftype) -> None:
    """Refuse a BitType subclass as a field or element type when its
    ``value`` property is defined or redefined outside bytemaker.

    The plan engine moves plain wire values through slots and generated
    tuple converters, and it never constructs the box on the hot path. A
    user subclass such as ``class ThumbPointer(UInt32)`` with a custom
    ``value`` property would therefore be silently ignored. Parse would
    store the raw wire value and pack would re-emit it untransformed, while
    the standalone box and ``BoundField.boxed()`` applied the override.
    That is two answers for one field, with no diagnostic. Failing the
    class definition turns wrong bytes into an error instead.

    The sanctioned seam for value transforms is ``adapt=``, in
    :mod:`bytemaker.adapters`. String and Buffer codec customization
    through ``encoding``/``decoding`` or ``of(...)`` is engine-honored and
    unaffected, because those hooks define no ``value``.
    """
    if not (isinstance(ftype, type) and issubclass(ftype, BitType)):
        return
    for klass in type.mro(ftype):
        if "value" in vars(klass):
            module = getattr(klass, "__module__", "") or ""
            if not (module == "bytemaker" or module.startswith("bytemaker.")):
                raise PlanCompileError(
                    f"{owner}.{field_name}: {ftype.__name__} (re)defines"
                    f" 'value' in {module}, which the plan engine would"
                    f" silently ignore (fields hold plain wire values; the"
                    f" box is never consulted on parse/pack). Use a plain"
                    f" engine type and attach the transform with adapt="
                    f" (see bytemaker.adapters), or compute it at the call"
                    f" site."
                )
            return  # first definer wins; engine-owned -> fine


def _expected_py_type(bittype):
    """The plain Python value type a field of ``bittype`` reads as: ``int``
    for Int, ``float`` for Float, ``str`` for String, ``bytes`` for Buffer
    (its box value is a BitVector, but a *field* holds plain bytes),
    ``list`` for an Array, and the class itself for a nested Struct. Used to
    check a ``field()``/``array()`` field's plain annotation against its wire
    type. Returns ``None`` for anything unrecognized (check skipped)."""
    if isinstance(bittype, Array):
        return list
    if isinstance(bittype, StructMeta):
        return bittype
    if isinstance(bittype, Adapted):
        return bittype.py_type
    if isinstance(bittype, type) and issubclass(bittype, Buffer):
        return bytes
    if isinstance(bittype, type) and issubclass(bittype, BitType):
        return bittype.py_type
    return None


def _check_spec_annotation(owner, field_name, bittype, annotation, adapter=None):
    """Enforce the R10 invariant on a ``field()`` or ``array()`` field.

    The plain annotation is the type a checker trusts, so it must match the
    value type its wire ``bittype`` actually reads as. For an adapted field
    it must match the adapter's user-plane ``py_type`` instead. A
    disagreement raises :class:`PlanCompileError`. The
    annotation-carried path enforces the same truth via
    ``_unwrap_annotation``. ``Any`` is allowed as a deliberate opt-out.
    """
    if annotation is None:
        return
    _reject_endian_tag_metadata(owner, field_name, annotation)
    ann = annotation
    if get_origin(ann) is Annotated:
        ann = get_args(ann)[0]
    if ann is Any:
        return  # explicit "untype this" escape hatch
    if adapter is not None:
        expected = adapter.py_type
    else:
        expected = _expected_py_type(bittype)
    if expected is None:
        return
    if expected is list:  # Array field: want list[<elem>] or bare list
        if not (ann is list or get_origin(ann) is list):
            _spec_type_error(owner, field_name, annotation, bittype, "list[...]")
        args = get_args(ann)
        if args:  # parameterized -> the element type must match too
            # An adapted array reads USER-plane elements, so the element
            # annotation is checked against the adapter's py_type (None =
            # deliberately unchecked, as for a scalar adapted field).
            if bittype._adapter is not None:
                elem_expected = bittype._adapter.py_type
            else:
                elem_expected = _expected_py_type(bittype.element)
            elem_ann = args[0]
            if get_origin(elem_ann) is Annotated:
                elem_ann = get_args(elem_ann)[0]
            if (
                elem_expected is not None
                and elem_ann is not Any
                and not _annotation_accepts(elem_ann, elem_expected)
            ):
                want = getattr(elem_expected, "__name__", elem_expected)
                _spec_type_error(
                    owner, field_name, annotation, bittype, f"list[{want}]"
                )
        return
    if not _annotation_accepts(ann, expected):
        want = getattr(expected, "__name__", str(expected))
        _spec_type_error(owner, field_name, annotation, bittype, want)


def _annotation_accepts(ann, expected) -> bool:
    """True when ``ann`` truthfully describes a field whose values are of
    type ``expected``, meaning ``ann`` is that exact type or a superclass
    of it. A field may be annotated looser than what it returns, such as
    ``int`` for a field that reads as a PtrValue. It may never be
    annotated tighter: ``bool`` for an int field stays refused, because the
    values would not satisfy the annotation."""
    if ann is expected:
        return True
    return (
        isinstance(ann, type)
        and isinstance(expected, type)
        and issubclass(expected, ann)
    )


def _spec_type_error(owner, field_name, annotation, bittype, want):
    raise PlanCompileError(
        f"{owner}.{field_name}: annotation {annotation!r} disagrees with the"
        f" field()/array() wire type {bittype!r}; a checker would trust the"
        f" annotation while the field really holds {want}. Annotate it as"
        f" {want} (or fix the field()/array() type)."
    )


# --------------------------------------------------------------------------
# Code generation (once per class): __init__, _from_tuple, _to_tuple
# --------------------------------------------------------------------------


_MISSING = object()
"""Sentinel: a defaulted __init__ parameter the caller left unpassed. A
Struct-valued default is detach-copied only when its parameter is still
_MISSING, so explicitly passing even the exact default object keeps a live
reference (closes the object-identity corner)."""


def _generate_methods(cls, field_defs, defaults) -> None:
    names = [n for n, _ in field_defs]
    env: Dict[str, Any] = {"_new": object.__new__, "_cls": cls, "_MISSING": _MISSING}
    slot_of = {}
    child_of = {}
    str_of = {}  # String fields: slot holds str; the tuple carries wire bytes
    array_of = {}  # Array fields: (arr_var, elem_struct_var_or_None)
    adapted_array_of = {}  # Adapted Array fields: (load_var, store_var)
    for i, (n, ftype) in enumerate(field_defs):
        slot_of[n] = f"_s{i}"
        env[f"_s{i}"] = cls.__dict__["_bm_" + n]
        if isinstance(ftype, StructMeta):
            child_of[n] = f"_c{i}"
            env[f"_c{i}"] = ftype
        elif isinstance(ftype, Array):  # before issubclass (instance!)
            env[f"_a{i}"] = ftype
            elem_var = None
            if isinstance(ftype.element, StructMeta):
                elem_var = f"_ae{i}"
                env[elem_var] = ftype.element
            array_of[n] = (f"_a{i}", elem_var)
            if ftype._adapter is not None:
                # An adapted array field stores USER-plane values, so the
                # tuple boundary is where the element adapter runs (scalar
                # elements only; an adapted Struct-element array is
                # refused at Array construction).
                adapted_array_of[n] = (f"_ald{i}", f"_ast{i}")
                # The label is READ off the field's descriptor (installed
                # before codegen runs), never re-derived: one home, one
                # spelling, nothing to drift.
                field_label = cls.__dict__[n]._label
                env[f"_ald{i}"] = _elem_loader(ftype._adapter.load, field_label)
                env[f"_ast{i}"] = _elem_storer(ftype._adapter.store, field_label)
        elif isinstance(ftype, type) and issubclass(ftype, String):
            str_of[n] = (f"_enc{i}", f"_dec{i}")
            env[f"_enc{i}"] = ftype._encode_padded
            env[f"_dec{i}"] = ftype._decode_wire

    # __init__: assignments run through the narrowing descriptors.
    ftype_of = dict(field_defs)
    params = []
    stores = {}  # per-field RHS expression; absent means the plain name
    for n in names:
        if n in defaults:
            dflt = defaults[n]
            if n in array_of and not isinstance(dflt, (list, tuple)):
                # A one-shot iterable default (generator/map/zip) lives once
                # in __init__.__defaults__ and would be consumed by the
                # first instance, leaving every later one empty. Materialize
                # to a tuple so each instance gets an independent snapshot
                # (the per-instance list() copy in _coerce_seq handles the
                # rest, exactly as for a list/tuple default).
                dflt = tuple(dflt)
            env[f"_d_{n}"] = dflt
            # A Struct-valued default is one shared mutable instance living
            # in __init__.__defaults__; storing it by reference would alias
            # every default-constructed record to it (the classic mutable-
            # default footgun: mutate one, corrupt all). Detach-copy at bind
            # time, but only when the parameter was actually left at its
            # default, which the _MISSING sentinel detects exactly, so
            # explicitly passing even the default object keeps a live
            # reference. Same for Struct *elements* of an array default
            # (numeric elements are immutable and _coerce_seq already
            # snapshots the container). An ill-typed default keeps the plain
            # store and fails in the descriptor with the usual TypeError.
            if n in child_of and isinstance(dflt, ftype_of[n]):
                stores[n] = f"_d_{n}.detach_copy() if {n} is _MISSING else {n}"
                params.append(f"{n}=_MISSING")
            elif (
                n in array_of
                and array_of[n][1] is not None
                and all(isinstance(e, ftype_of[n].element) for e in dflt)
            ):
                stores[n] = (
                    f"[_bm_e.detach_copy() for _bm_e in _d_{n}]"
                    f" if {n} is _MISSING else {n}"
                )
                params.append(f"{n}=_MISSING")
            else:
                params.append(f"{n}=_d_{n}")
        else:
            params.append(n)
    body = "".join(f"    self.{n} = {stores.get(n, n)}\n" for n in names)
    init_src = f"def __init__(self, {', '.join(params)}):\n{body}"

    # _bm_from_tuple: descriptor-bypassing construction from a flat plan
    # tuple. (The _bm_ prefix keeps generated internals out of the user's
    # field namespace, which the metaclass guard reserves by prefix.)
    lines = ["def _bm_from_tuple(values):", "    obj = _new(_cls)"]
    idx = 0
    for n, ftype in field_defs:
        if n in child_of:
            span = len(ftype.plan.fields)
            lines.append(
                f"    {slot_of[n]}.__set__(obj,"
                f" {child_of[n]}._bm_from_tuple(values[{idx}:{idx + span}]))"
            )
            idx += span
        elif n in array_of:
            arr_var, elem_var = array_of[n]
            count = ftype.count
            # The live list is told which field it belongs to, so an element
            # store through it can name the record and field (the Array
            # itself is standalone-capable and has no name). Read off the
            # descriptor, like the loader/storer labels above.
            label_var = f"_alab_{n}"
            env[label_var] = cls.__dict__[n]._label
            if elem_var is not None:  # Struct-element array: rebuild each
                span = len(ftype.element.plan.fields)
                lines.append(
                    f"    {slot_of[n]}.__set__(obj, {arr_var}.field_list(["
                    f"{elem_var}._bm_from_tuple("
                    f"values[{idx}+k*{span}:{idx}+(k+1)*{span}])"
                    f" for k in range({count})], {label_var}))"
                )
                idx += count * span
            elif n in adapted_array_of:  # load each wire element
                load_var = adapted_array_of[n][0]
                lines.append(
                    f"    {slot_of[n]}.__set__(obj, {arr_var}.field_list("
                    f"{load_var}(values[{idx}:{idx + count}]), {label_var}))"
                )
                idx += count
            else:  # numeric array: the count flat entries are the values
                lines.append(
                    f"    {slot_of[n]}.__set__(obj, {arr_var}.field_list("
                    f"values[{idx}:{idx + count}], {label_var}))"
                )
                idx += count
        elif n in str_of:
            lines.append(
                f"    {slot_of[n]}.__set__(obj, {str_of[n][1]}(values[{idx}]))"
            )
            idx += 1
        else:
            lines.append(f"    {slot_of[n]}.__set__(obj, values[{idx}])")
            idx += 1
    lines.append("    return obj")
    from_tuple_src = "\n".join(lines) + "\n"

    # _bm_to_tuple: flat plan tuple from slot reads (descriptors bypassed).
    parts = []
    for n, _ftype in field_defs:
        if n in child_of:
            parts.append(f"*{child_of[n]}._bm_to_tuple({slot_of[n]}.__get__(obj))")
        elif n in array_of:
            arr_var, elem_var = array_of[n]
            if elem_var is not None:  # splat each element struct's leaves
                parts.append(
                    f"*[x for e in {slot_of[n]}.__get__(obj)"
                    f" for x in {elem_var}._bm_to_tuple(e)]"
                )
            elif n in adapted_array_of:  # store each user-plane element
                store_var = adapted_array_of[n][1]
                parts.append(f"*{store_var}({slot_of[n]}.__get__(obj))")
            else:  # splat the numeric list straight in
                parts.append(f"*{slot_of[n]}.__get__(obj)")
        elif n in str_of:
            parts.append(f"{str_of[n][0]}({slot_of[n]}.__get__(obj))")
        else:
            parts.append(f"{slot_of[n]}.__get__(obj)")
    to_tuple_src = f"def _bm_to_tuple(obj):\n    return ({', '.join(parts)},)\n"

    namespace: Dict[str, Any] = {}
    exec(init_src + from_tuple_src + to_tuple_src, env, namespace)  # noqa: S102
    cls.__init__ = namespace["__init__"]
    cls._bm_from_tuple = staticmethod(namespace["_bm_from_tuple"])
    cls._bm_to_tuple = namespace["_bm_to_tuple"]


# --------------------------------------------------------------------------
# The metaclass and base class
# --------------------------------------------------------------------------


_MISSING = object()


class _FieldSpec:
    """Runtime marker produced by :func:`field` and :func:`array`.

    It carries the field's bytemaker type, which is a BitType class, a
    Struct class or an :class:`Array`, plus an optional default and an
    optional value :class:`Adapter`. The metaclass reads the type from here
    when a field is spelled ``name: <plain type> = field(...)``, so the
    annotation stays the plain checker type."""

    __slots__ = ("bittype", "default", "adapter", "endian")

    def __init__(self, bittype, default=_MISSING, adapter=None, endian=None):
        self.bittype = bittype
        self.default = default
        self.adapter = adapter
        self.endian = endian


def field(
    bittype: Any,
    *,
    default: Any = _MISSING,
    adapt: Any = None,
    endian: Any = None,
) -> Any:
    """Declare a Struct field whose checker type is the annotation and
    whose wire type is ``bittype``.

    ``bittype`` may be a scalar BitType class, a ``String`` or ``Buffer``
    type such as one from ``String.of(...)``, a nested ``Struct`` class, or
    an ``Array``. The ``uN`` and ``Annotated[...]`` spellings instead put
    the wire type in the annotation, and ``field()`` is the checker-friendly
    counterpart to those::

        hp:   int = field(UInt8)
        name: str = field(String.of(nbytes=4, encoding=MON_TABLE))

    To a type checker this returns ``Any``, so it is assignable to any
    field annotation. The field's real type comes from the annotation, via
    dataclass_transform, and its wire type comes from ``bittype`` at
    runtime.

    ``adapt`` attaches a :class:`bytemaker.adapters.Adapter`, which puts an
    encoding convention into the schema: a THUMB bit, a fixed-point scale,
    a +1 bias, or an enum. Reads apply ``load`` to the wire value. Writes
    apply ``store`` to the user value before the usual wire narrowing. The
    annotation is checked against the adapter's ``py_type``::

        anim_fn:    int   = field(UInt32, adapt=THUMB_PTR)
        multiplier: float = field(UInt16, adapt=fixed(4))

    ``adapt`` takes scalar wire types only. An adapted :class:`Array` is a
    standalone codec, and a nested Struct adapts its own fields.

    ``endian`` overrides the record's byte order for this one multi-byte
    numeric field. It covers the rare mixed-endian record, such as a ROM
    table with a single big-endian column::

        char_number: int = field(UInt16, endian="big")   # in an LE record

    Every other use of ``endian`` raises here, with a message naming the
    right spelling. Text and bytes fields have no byte order. A nested
    Struct declares its own at its class definition. An array spells it
    ``array(T, n, endian=...)``.

    A Struct-valued ``default``, scalar or array element alike, is
    detach-copied per instance at ``__init__`` time, so default-constructed
    records never share one mutable instance. Immutable defaults are bound
    as-is. Defaults are user-plane values, so they store through the
    adapter.
    """
    if adapt is not None and not isinstance(adapt, Adapter):
        raise TypeError(f"adapt= must be a bytemaker.adapters.Adapter, got {adapt!r}")
    if endian is not None:
        validate_endianness(endian, name="field endian", exc=PlanCompileError)
    return _FieldSpec(bittype, default, adapt, endian)


def array(
    element: Any,
    count: int,
    *,
    endian: Any = None,
    default: Any = _MISSING,
) -> Any:
    """Declare a fixed-count array field: ``colors: list[int] = array(UInt16, 8)``.
    Sugar for ``field(element * count)`` with a plain-list checker type."""
    return _FieldSpec(Array.of(element, count, endian), default)


@dataclass_transform(eq_default=True, field_specifiers=(field, array))
class StructMeta(type):
    """Metaclass of :class:`Struct`: turns annotated class bodies into
    compiled, slots-backed record classes, and provides ``T * N`` sugar."""

    # Compiled-class attributes, declared here so assignments in __new__
    # (and attribute access on StructMeta-typed class objects) typecheck;
    # runtime storage is on each concrete class.
    plan: Plan
    num_bits: int
    num_bytes: int
    _bm_adapters: Dict[str, Adapter]
    _bm_fields: Tuple[str, ...]
    _bm_field_types: Dict[str, type]

    def __new__(
        mcs,
        name,
        bases,
        ns,
        endian: Optional[Literal["big", "little"]] = None,
        bit_order: Optional[Literal["lsb", "msb"]] = None,
        **kwargs,
    ):
        is_concrete = any(isinstance(b, StructMeta) for b in bases)
        if not is_concrete:
            ns.setdefault("__slots__", ())
            return super().__new__(mcs, name, bases, ns, **kwargs)

        for b in bases:
            if isinstance(b, StructMeta) and getattr(b, "_bm_concrete", False):
                raise PlanCompileError(
                    f"{name}: subclassing the concrete Struct"
                    f" {b.__name__} is not supported; compose (nest) instead"
                )

        ann = ns.get("__annotations__", {})
        field_names = [n for n in ann if not _is_classvar(ann[n])]
        if not field_names:
            raise PlanCompileError(f"{name} declares no fields")

        defaults: Dict[str, Any] = {}
        # Fields spelled `name: <plain type> = field(...)` / `= array(...)`
        # carry their wire type in the RHS _FieldSpec (the annotation is the
        # plain checker type). Collect those here; the rest resolve their
        # type from the annotation via _unwrap_annotation, as before.
        specs: Dict[str, Any] = {}
        seen_default = False
        for n in field_names:
            # Reserved-name guard: field descriptors are installed with plain
            # setattr, so a colliding name would silently shadow the Struct
            # API (or, for the _bm_ slot prefix, cross-wire field storage).
            # The invariant this buys: if the class compiles, documented
            # attributes mean what the docs say, for everyone.
            # A field's storage slot is "_bm_<name>", so a field can collide
            # with the Struct API from TWO directions: its own name, and its
            # slot's. Both fail here at class definition, naming the slot,
            # which is the only place the collision is explainable. The slot
            # direction is the quiet one: left to run, a field named
            # "repr_of" would put an int where Struct._bm_repr_of expects a
            # method, so the record would parse, pack and read correctly
            # and only repr() would break.
            slot_taken = any(hasattr(b, "_bm_" + n) for b in bases)
            if (
                n.startswith("_bm_")
                or n in _RESERVED_FIELD_NAMES
                or slot_taken
                or any(hasattr(b, n) for b in bases)
            ):
                why = (
                    f"its storage slot {'_bm_' + n!r} is a Struct internal"
                    if slot_taken
                    else f"{n!r} is reserved"
                )
                raise PlanCompileError(
                    f"{name}.{n}: field name collides with the Struct API"
                    f" ({why}); rename the field"
                    f" (e.g. {n + '_'!r}; layout is positional, so field"
                    f" names never affect the wire format)"
                )
            has_default = False
            if n in ns:
                val = ns.pop(n)
                if isinstance(val, _FieldSpec):
                    specs[n] = val  # wire type (and adapter) from the RHS
                    if val.default is not _MISSING:
                        defaults[n] = val.default
                        has_default = True
                else:
                    defaults[n] = val  # a plain default value
                    has_default = True
            # A required field (no default) may not follow a defaulted one,
            # since the generated __init__ would put a non-default param after a
            # defaulted one. A spec-without-default is required even though it
            # has a class-body assignment, so key this off has_default.
            if has_default:
                seen_default = True
            elif seen_default:
                raise PlanCompileError(
                    f"{name}.{n}: field without a default follows fields"
                    f" with defaults"
                )
        ns["__slots__"] = tuple("_bm_" + n for n in field_names)

        cls = super().__new__(mcs, name, bases, ns, **kwargs)

        hints = _resolve_hints(cls)
        field_defs: List[Tuple[str, Any]] = [
            (
                n,
                (
                    specs[n].bittype
                    if n in specs
                    else _unwrap_annotation(name, n, hints[n])
                ),
            )
            for n in field_names
        ]
        # Adapter placement is checked FIRST (the conceptual error), then
        # the annotation/wire-type agreement.
        adapters: Dict[str, Adapter] = {
            n: spec.adapter for n, spec in specs.items() if spec.adapter
        }
        # An Adapted wire type (adapter @ BitType) is pure sugar for adapt=:
        # split it into its base type + adapter HERE, before anything else
        # looks at the field types, so the plan layer, the descriptors and
        # every diagnostic below see exactly what the adapt= spelling
        # produces. `field(THUMB_PTR @ UInt32)` and
        # `field(UInt32, adapt=THUMB_PTR)` are the same class from here on.
        for i, (n, ftype) in enumerate(field_defs):
            if not isinstance(ftype, Adapted):
                continue
            if n in adapters:
                raise PlanCompileError(
                    f"{name}.{n}: {ftype!r} already carries an adapter;"
                    f" drop adapt= (or fuse the composed transform instead)"
                )
            adapters[n] = ftype.adapter
            field_defs[i] = (n, ftype.base)
        ftype_by_name = dict(field_defs)
        for n in adapters:
            if isinstance(ftype_by_name[n], (StructMeta, Array)):
                raise PlanCompileError(
                    f"{name}.{n}: adapt= supports scalar field types only;"
                    f" an Array adapts its ELEMENTS (spell it"
                    f" array(adapter @ element, n), or Array.of(element, n,"
                    f" adapt=...)), and a nested Struct adapts its own fields"
                )
        # Per-field byte-order overrides (field(T, endian=...)): only
        # multi-byte numeric scalars have one to override.
        endian_overrides: Dict[str, Literal["big", "little"]] = {}
        for n, spec in specs.items():
            if spec.endian is None:
                continue
            ftype = ftype_by_name[n]
            if isinstance(ftype, StructMeta):
                raise PlanCompileError(
                    f"{name}.{n}: a nested Struct declares its own byte"
                    f" order at ITS class definition (endian= there)"
                )
            if isinstance(ftype, Array):
                raise PlanCompileError(
                    f"{name}.{n}: array fields spell their byte order as"
                    f" array(element, count, endian=...)"
                )
            if issubclass(ftype, (String, Buffer)):
                raise PlanCompileError(
                    f"{name}.{n}: text/bytes fields are byte-order-agnostic"
                    f" (stream order, like C char[]); drop endian="
                )
            endian_overrides[n] = spec.endian
        # field()/array() fields carry the wire type on the RHS and the plain
        # checker type in the annotation; verify they agree, so the static
        # type a checker trusts matches what the field actually holds.
        for n in specs:
            # adapters.get(n), not specs[n].adapter: a fused Adapted wire
            # type checks its annotation against the adapter's py_type too.
            _check_spec_annotation(
                name, n, specs[n].bittype, hints.get(n), adapters.get(n)
            )

        if endian is None:
            endian = "big"
        validate_endianness(endian, name=f"{name}: endian", exc=PlanCompileError)
        if bit_order is None:
            bit_order = "msb" if endian == "big" else "lsb"
        if bit_order not in ("lsb", "msb"):
            raise PlanCompileError(f"{name}: bit_order must be 'lsb' or 'msb'")

        plan = compile_plan(
            field_defs,
            endian,
            bit_order,
            owner_name=name,
            endian_overrides=endian_overrides,
        )
        cls.plan = plan
        cls.num_bits = plan.num_bits
        cls.num_bytes = plan.num_bytes
        cls._bm_concrete = True
        cls._bm_fields = tuple(field_names)
        cls._bm_field_types = dict(field_defs)
        cls._bm_endian = endian

        for n, ftype in field_defs:
            slot = cls.__dict__["_bm_" + n]
            _reject_foreign_value_override(name, n, ftype)
            descriptor: Any
            if isinstance(ftype, StructMeta):
                descriptor = _StructField(slot, ftype)
            elif isinstance(ftype, Array):  # before issubclass (instance!)
                descriptor = _ArrayField(slot, ftype, f"{name}.{n}")
            elif issubclass(ftype, Int):
                mask = (1 << ftype.num_bits) - 1
                if issubclass(ftype, SInt):
                    descriptor = _SIntField(slot, mask, 1 << (ftype.num_bits - 1))
                else:
                    descriptor = _UIntField(slot, mask)
            elif issubclass(ftype, String):
                descriptor = _StrField(slot, ftype)
            elif issubclass(ftype, Buffer):
                descriptor = _BytesField(slot, ftype.num_bits // 8)
            else:  # Float; compile_plan already rejected everything else
                descriptor = _FloatField(slot, ftype)
            if n in adapters:
                # The wrap keeps the slot in the WIRE plane: reads load,
                # writes store-then-narrow. parse/pack and the generated
                # tuple converters bypass descriptors and stay wire-only.
                descriptor = _AdaptedField(descriptor, adapters[n])
            setattr(cls, n, descriptor)

        # _bm_adapters reports EVERY adapted field, which is not the same set
        # the descriptor loop above needed: an adapted array field carries its
        # adapter on the Array (its codegen converts at the tuple boundary and
        # it must NOT be wrapped in _AdaptedField), so it is added only now.
        # Introspection cares that the field is adapted, not where the engine
        # keeps the transform. fields_of() would otherwise report None for an
        # adapted array and callers reading the schema would miss it.
        cls._bm_adapters = {
            **adapters,
            **{
                n: ftype._adapter
                for n, ftype in field_defs
                if isinstance(ftype, Array) and ftype._adapter is not None
            },
        }
        _generate_methods(cls, field_defs, defaults)
        _STRUCT_REGISTRY.setdefault(name, weakref.WeakSet()).add(cls)
        return cls

    def __mul__(cls, count: int) -> Array:
        return Array.of(cls, count)

    def __rmul__(cls, count: int) -> Array:
        return Array.of(cls, count)


def _is_classvar(hint) -> bool:
    if isinstance(hint, str):
        return hint.replace(" ", "").startswith(("ClassVar[", "typing.ClassVar["))
    return getattr(hint, "__origin__", None) is ClassVar or hint is ClassVar


class Struct(metaclass=StructMeta):
    """Base class for fixed-layout records; see the module docstring.

    Subclasses declare fields as annotations and may pass ``endian`` /
    ``bit_order`` as class keywords; ``bit_order`` defaults to match
    ``endian`` (LSB-first under little, MSB-first under big)::

        class Header(Struct, endian="little"):
            magic:   u32
            version: u16 = 1
    """

    __slots__ = ()

    plan: ClassVar[Plan]
    num_bits: ClassVar[int]
    num_bytes: ClassVar[int]
    _bm_concrete: ClassVar[bool] = False
    _bm_fields: ClassVar[Tuple[str, ...]] = ()
    _bm_field_types: ClassVar[Dict[str, type]] = {}
    _bm_endian: ClassVar[str] = "big"
    _bm_adapters: ClassVar[Dict[str, Adapter]] = {}

    @classmethod
    def parse(cls, data: BytesLike) -> Self:
        """Decode ``num_bits // 8`` bytes into a new detached instance."""
        n = cls.plan.num_bytes
        if len(data) != n:
            raise ValueError(
                f"{cls.__name__}.parse: expected {n} bytes, got {len(data)}"
            )
        return cls._bm_from_tuple(cls.plan.unpack_tuple(data))

    @classmethod
    def from_tuple(cls, values: Sequence[Any]) -> Self:
        """Build a record from one flat wire-plane tuple.

        This is the inverse of :meth:`to_tuple` and the record half of
        :meth:`Plan.unpack_tuple <bytemaker.plans.Plan.unpack_tuple>`. The
        values are in the plan's flat field order, with nested Structs and
        array elements flattened in place, exactly as ``plan.unpack_tuple``
        yields them.

        The values are trusted, as in :meth:`parse`. The narrowing
        descriptors are bypassed, so they must already be in range.

        An adapted field takes its wire value here. Reads through the
        attribute apply the adapter as usual.
        """
        want = len(cls.plan.fields)
        if len(values) != want:
            raise ValueError(
                f"{cls.__name__}.from_tuple: expected {want} values,"
                f" got {len(values)}"
            )
        return cls._bm_from_tuple(values)

    def to_tuple(self) -> tuple:
        """This record's flat wire-plane tuple, with adapters not applied.

        It round-trips through :meth:`from_tuple`, and it is what
        :meth:`Plan.pack_tuple <bytemaker.plans.Plan.pack_tuple>` consumes.
        """
        return self._bm_to_tuple()

    @classmethod
    def iter_records(
        cls, data: BytesLike, offset: int = 0, count: Optional[int] = None
    ) -> Iterator[Self]:
        """Lazily decode consecutive records starting at ``offset``.

        This is the record-plane counterpart of
        :meth:`Plan.iter_tuples <bytemaker.plans.Plan.iter_tuples>`. It
        needs no slicing at the call site and makes no intermediate copies,
        and nothing is decoded until the iterator is consumed.
        ``count=None`` reads as many whole records as fit between
        ``offset`` and the end of ``data``.

        For a table scan that never materializes records at all, use
        ``cls.plan.iter_tuples(...)`` directly. Those tuples are the same
        wire-plane values :meth:`from_tuple` accepts.
        """
        return map(cls._bm_from_tuple, cls.plan.iter_tuples(data, offset, count))

    @classmethod
    def parse_at(cls, data: BytesLike, offset: int = 0) -> Self:
        """Decode one record at a byte ``offset``. This is :meth:`parse`
        without the call-site slice, and its bounds error names the
        record."""
        return cls._bm_from_tuple(next(iter(cls.plan.iter_tuples(data, offset, 1))))

    def pack(self) -> bytes:
        """Encode this instance; trusts the store-time narrowing invariant."""
        values = self._bm_to_tuple()
        if DEBUG_VALIDATE:
            self.plan.validate_tuple(values)
        return self.plan.pack_tuple(values)

    def pack_into(self, buf, offset: int = 0) -> None:
        """Encode this instance in place into a writable ``buf`` at
        ``offset``. It is the read-modify-write counterpart of
        :meth:`parse_at`."""
        values = self._bm_to_tuple()
        if DEBUG_VALIDATE:
            self.plan.validate_tuple(values)
        self.plan.pack_into(buf, offset, values)

    def detach_copy(self) -> Self:
        """A new instance with the same field values."""
        return self._bm_from_tuple(self._bm_to_tuple())

    @property
    def sizedview(self) -> _SizedView:
        """A live, width-carrying view of this record's fields.

        ``t.sizedview.<field>`` returns a :class:`BoundField`, a live
        handle with C lvalue semantics: reading it promotes to the plain
        value, and assigning to it narrows through the field descriptor.
        Its ``.bits`` channel writes through to the record, but width is
        invariant, so a mutation that would change it raises. ``.boxed()``
        detaches a snapshot.
        """
        return _SizedView(self)

    def __eq__(self, other):
        if other.__class__ is self.__class__:
            return self._bm_to_tuple() == other._bm_to_tuple()
        return NotImplemented

    __hash__ = None  # mutable record semantics, like an eq dataclass

    def __repr__(self):
        args = ", ".join(f"{n}={self._bm_repr_of(n)}" for n in self._bm_fields)
        return f"{type(self).__name__}({args})"

    def _bm_repr_of(self, name: str) -> str:
        """One field's repr text, or a marker when reading it raises (see
        :func:`_unreadable`). The happy path is one getattr and one repr,
        and the marker work is paid only on a field that cannot load."""
        try:
            return repr(getattr(self, name))
        except Exception as exc:  # noqa: BLE001 - a repr must not raise
            return _unreadable(exc, f"{type(self).__name__}.{name}: ")


# --------------------------------------------------------------------------
# The sized view: live, width-carrying field handles
# --------------------------------------------------------------------------


def _unwrap_bound(value):
    return value.value if isinstance(value, BoundField) else value


#: The field's plain value type (int/float/str/bytes), for checker use:
#: annotate a handle as ``BoundField[int]`` and ``.value`` reads/writes
#: type as ``int`` while ``.boxed()`` returns ``BitType[int]``. Handles
#: minted by ``sizedview`` attribute access type as ``Any`` (the view is
#: dynamic); the parameter exists for explicitly-annotated code.
V = typing.TypeVar("V")


class BoundField(typing.Generic[V]):
    """A live handle to one scalar field of a Struct instance.

    A handle holds only the owning record, the field name, and the field's
    BitType. The value stays in the struct's slot, so a handle reads and
    writes through to the record and never goes stale.

    Handles follow C lvalue semantics. Reading one promotes to the plain
    value. Assigning to it narrows through the field descriptor. Compound
    assignment reads the promoted value, computes at full width, and narrows
    again on the way back into the slot.

    ``__index__`` and the bitwise operators (``& | ^ << >> ~``) are
    deliberately absent. A handle has both a value plane and a bit plane, so
    each of those operators would have two defensible meanings. Name the
    plane instead::

        f.value & mask      # value plane
        f.bits & bv         # bit plane
        f"{f:#x}"           # formatting reads the value

    Handles are unhashable, because the value behind one can change. Key on
    ``f.value``, or on the detached box ``f.boxed()`` returns.
    """

    __slots__ = ("_owner", "_name", "_ftype")

    def __init__(self, owner, name: str, ftype: type[BitType[V]]):
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_ftype", ftype)

    # -- the two channels ---------------------------------------------------

    @property
    def value(self) -> V:
        return getattr(self._owner, self._name)

    @value.setter
    def value(self, new) -> None:
        setattr(self._owner, self._name, _unwrap_bound(new))

    @property
    def bits(self) -> BoundBits:
        return BoundBits(self)

    @bits.setter
    def bits(self, new) -> None:
        if isinstance(new, BoundBits):
            new = new._snapshot()
        # Any other BitsConstructible goes straight through: the box's
        # bits setter snapshots and length-validates whatever it gets.
        self._wire_store(self._ftype(bits=new).value)

    # -- the wire plane: descriptor-bypassing slot access ---------------------
    # For a plain field the slot holds exactly what ``.value`` reads, so
    # these are equivalent to getattr/setattr; for an adapted field they
    # are the WIRE value (bits/boxed() serialize; ``.value`` is the user
    # plane through the adapter).

    def _wire_value(self):
        return type(self._owner).__dict__["_bm_" + self._name].__get__(self._owner)

    def _wire_store(self, wire) -> None:
        descriptor = type(self._owner).__dict__[self._name]
        inner = getattr(descriptor, "_inner", descriptor)
        inner.__set__(self._owner, wire)

    @property
    def num_bits(self) -> int:
        return self._ftype.num_bits

    def boxed(self) -> BitType[V]:
        """Return a detached BitType snapshot of this field, in its wire
        byte order. The snapshot survives later mutation of the struct.

        The box is wire-plane. For an adapted field it holds the slot's
        wire value, because the box is a serialization object. The
        user-plane number is ``.value``.

        The byte order comes from the field's plan leaf rather than the
        record, because the box is the documented way to inspect the wire:
        a ``field(T, endian=...)`` override must serialize from the box
        exactly as ``pack()`` writes it.

        Byte-payload fields, meaning String and Buffer with plan kind
        ``"b"``, have no byte order. ``pack()`` writes them in stream order
        whatever the record declares, and their leaf endian exists only for
        tier selection. Their box is therefore minted big-endian, whose
        serialization is stream order. A record-endian box would
        byte-reverse a String field of a little-endian record on
        ``bytes()``, putting the wire backwards.
        """
        leaf = type(self._owner).plan._find(self._name)
        endianness = "big" if leaf.kind == "b" else leaf.endian
        return self._ftype(self._wire_value(), endianness=endianness)

    def __setattr__(self, name, value):
        # Only the two channels are assignable; everything else is a likely
        # typo that would otherwise vanish into an instance attribute.
        if name in ("value", "bits"):
            type(self).__dict__[name].__set__(self, value)
        else:
            raise AttributeError(
                f"cannot set {name!r} on a bound field; assign .value or .bits"
            )

    # -- bit access: [] has no value-plane rival on a number -----------------

    def __getitem__(self, index):
        return self._ftype(self._wire_value()).bits[index]

    def __setitem__(self, index, bit):
        b = self._ftype(self._wire_value()).bits
        b[index] = bit
        self._wire_store(self._ftype(bits=b).value)

    # -- promotion: rvalue use yields plain results ---------------------------

    def __eq__(self, other):
        return self.value == _unwrap_bound(other)

    __hash__ = None

    def __lt__(self, other):
        return self.value < _unwrap_bound(other)

    def __le__(self, other):
        return self.value <= _unwrap_bound(other)

    def __gt__(self, other):
        return self.value > _unwrap_bound(other)

    def __ge__(self, other):
        return self.value >= _unwrap_bound(other)

    def __add__(self, other):
        return self.value + _unwrap_bound(other)

    def __radd__(self, other):
        return _unwrap_bound(other) + self.value

    def __sub__(self, other):
        return self.value - _unwrap_bound(other)

    def __rsub__(self, other):
        return _unwrap_bound(other) - self.value

    def __mul__(self, other):
        return self.value * _unwrap_bound(other)

    def __rmul__(self, other):
        return _unwrap_bound(other) * self.value

    def __truediv__(self, other):
        return self.value / _unwrap_bound(other)

    def __rtruediv__(self, other):
        return _unwrap_bound(other) / self.value

    def __floordiv__(self, other):
        return self.value // _unwrap_bound(other)

    def __rfloordiv__(self, other):
        return _unwrap_bound(other) // self.value

    def __mod__(self, other):
        return self.value % _unwrap_bound(other)

    def __rmod__(self, other):
        return _unwrap_bound(other) % self.value

    def __pow__(self, other):
        return self.value ** _unwrap_bound(other)

    def __rpow__(self, other):
        return _unwrap_bound(other) ** self.value

    def __neg__(self):
        return -self.value

    def __pos__(self):
        return +self.value

    def __abs__(self):
        return abs(self.value)

    def __int__(self):
        return int(self.value)

    def __float__(self):
        return float(self.value)

    def __bool__(self):
        return bool(self.value)

    # -- compound assignment: RMW through the narrowing store ----------------

    def __iadd__(self, other):
        self.value = self.value + _unwrap_bound(other)
        return self

    def __isub__(self, other):
        self.value = self.value - _unwrap_bound(other)
        return self

    def __imul__(self, other):
        self.value = self.value * _unwrap_bound(other)
        return self

    def __itruediv__(self, other):
        self.value = self.value / _unwrap_bound(other)
        return self

    def __ifloordiv__(self, other):
        self.value = self.value // _unwrap_bound(other)
        return self

    def __imod__(self, other):
        self.value = self.value % _unwrap_bound(other)
        return self

    def __ipow__(self, other):
        self.value = self.value ** _unwrap_bound(other)
        return self

    # -- display --------------------------------------------------------------

    def __format__(self, format_spec):
        # No spec: displaying the handle (sized form, agrees with print).
        # Any spec: formatting the number (plain value).
        if format_spec == "":
            return str(self)
        return format(self.value, format_spec)

    def __str__(self):
        return str(self.boxed())

    def __repr__(self):
        owner = type(self._owner).__name__
        # Same plane as Struct.__repr__, so the same failure is possible: the
        # session that just got a degraded record repr and reached for the
        # handle to inspect the offending field must not be met with a raise.
        try:
            value = repr(self.value)
        except Exception as exc:  # noqa: BLE001 - a repr must not raise
            value = _unreadable(exc, f"{owner}.{self._name}: ")
        return f"<bound {self._ftype.__name__} {self._name}={value} of {owner}>"


class BoundBits:
    """Live bits of a bound field: a view of a view.

    Holds only the :class:`BoundField`; every operation re-derives the
    current bits from the struct's slot at call time, so held handles never
    go stale. Width-preserving mutation writes through; width-changing
    mutation raises at write-back (the field's width is invariant).
    Unhashable, like BitVector.
    """

    __slots__ = ("_field",)

    def __init__(self, field):
        object.__setattr__(self, "_field", field)

    def _cur(self):
        f = self._field
        return f._ftype(f._wire_value()).bits

    def _write(self, bits):
        f = self._field
        f._wire_store(f._ftype(bits=bits).value)

    def _snapshot(self):
        return self._cur()

    # -- readers (dunders bypass __getattr__, so these are explicit) ---------

    def __len__(self):
        return len(self._cur())

    def __iter__(self):
        return iter(self._cur())

    def __getitem__(self, index):
        return self._cur()[index]

    def __eq__(self, other):
        if isinstance(other, BoundBits):
            other = other._cur()
        return self._cur() == other

    __hash__ = None

    def __str__(self):
        return str(self._cur())

    def __repr__(self):
        f = self._field
        return f"<bound bits {self._cur().to01()} of {f._name!r}>"

    def __getattr__(self, name):
        # Reader methods (to01, hex, to_bytes, count, ...) delegate to a
        # fresh derivation and pass straight through. Anything else the
        # backend provides that mutates in place (bitarray's setall /
        # invert / sort / bytereverse, ...) must not land on a throwaway
        # the caller can never see, so every delegated call re-derives at
        # call time, diffs the derivation around the call, and writes a
        # changed result back through the same width-validating store the
        # explicit mutators below use (width-changing growth, e.g.
        # bitarray's fill, raises there; the struct stays untouched).
        attr = getattr(self._cur(), name)  # missing names raise eagerly
        if not callable(attr):
            return attr

        def delegated(*args, **kwargs):
            b = self._cur()
            before = b.copy()
            result = getattr(b, name)(*args, **kwargs)
            if b != before:
                self._write(b)
            return result

        return delegated

    # -- mutators: read-modify-write through the store ------------------------

    def __setitem__(self, index, value):
        b = self._cur()
        b[index] = value
        self._write(b)

    def __delitem__(self, index):
        b = self._cur()
        del b[index]
        self._write(b)  # width-changing: raises; struct untouched

    def __iadd__(self, other):
        b = self._cur()
        b += other
        self._write(b)  # concatenation grows: raises unless other is empty
        return self

    def append(self, value):
        b = self._cur()
        b.append(value)
        self._write(b)

    def extend(self, values):
        b = self._cur()
        b.extend(values)
        self._write(b)

    def insert(self, index, value):
        b = self._cur()
        b.insert(index, value)
        self._write(b)

    def pop(self, index=None, default=_MISSING):
        # Mirrors the BitVector contract (None = last bit; negative
        # indices count from the end, as in list.pop). Forward the default
        # only when the caller gave one, so an omitted default still raises
        # IndexError (a passed default=None returns None), and the backend's
        # own _MISSING sentinel governs the raise.
        b = self._cur()
        value = b.pop(index) if default is _MISSING else b.pop(index, default)
        self._write(b)
        return value

    def remove(self, value):
        b = self._cur()
        b.remove(value)
        self._write(b)

    def clear(self):
        b = self._cur()
        b.clear()
        self._write(b)

    def reverse(self):
        b = self._cur()
        b.reverse()
        self._write(b)  # width-preserving: writes through


class _SizedView:
    """Lazy attribute proxy: each field access mints a fresh live handle
    (nested-Struct fields return the child's own sizedview)."""

    __slots__ = ("_owner",)

    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        owner = self._owner
        try:
            ftype = type(owner)._bm_field_types[name]
        except KeyError:
            raise AttributeError(
                f"{type(owner).__name__} has no field {name!r}"
            ) from None
        if isinstance(ftype, StructMeta):
            return getattr(owner, name).sizedview
        if isinstance(ftype, Array):
            # No scalar sized-handle for a list field (a whole-array handle
            # is a possible future addition); read/write the live list.
            raise AttributeError(
                f"array field {name!r} has no scalar sized-view; access its"
                f" live list via the field itself ({name})"
            )
        return BoundField(owner, name, ftype)

    def __setattr__(self, name, value):
        setattr(self._owner, name, _unwrap_bound(value))

    def __dir__(self):
        return list(type(self._owner)._bm_fields)

    def __repr__(self):
        return f"<sizedview of {self._owner!r}>"


# --------------------------------------------------------------------------
# Array
# --------------------------------------------------------------------------


class Array(typing.Generic[V]):
    """A fixed-count codec of a uniform element codec.

    Build one with ``element * count`` (Struct classes and scalar BitType
    classes both support ``*``) or with :meth:`Array.of`. ``parse`` returns
    a ``list``, and ``pack`` accepts any sequence of the right length.

    The type parameter is the decoded element value type. The ``Array.of``
    overloads infer it, so ``Array.of(UInt16, 4).parse(b)`` reads as
    ``list[int]`` and ``Array.of(RGB, 3).parse(b)`` reads as ``list[RGB]``.

    **Decoded scalars are plain Python values.** That is the same
    decoded-scalar rule Struct fields follow: ``int`` or ``float`` for
    numeric elements, ``str`` for String elements, and ``bytes`` for Buffer
    elements. A String element decodes through the element's terminator and
    pad policy. Width lives in the schema, on ``self.element``, and the
    constructor cast ``arr.element(v)`` re-attaches it on demand.

    ``pack`` accepts plain values or boxes. A plain value is coerced
    through the element type, which means C-narrowing for ints and
    encode-validation for text. ``endian`` governs the byte order of
    numeric elements. Text and bytes elements have no byte order and stay
    in stream order, as they do in the plan engine and in C ``char[]``.

    **Type-checking an array field.** The terse ``field: Elem * N``
    spelling works at runtime but is not a valid type to a checker, because
    ``Elem * N`` is an expression rather than a type. For checker
    visibility use the ``Annotated`` form, the array analog of the ``uN``
    scalar aliases::

        colors: Annotated[list[int], UInt16 * 8]   # reads as list[int]
        tiles:  Annotated[list[RGB], RGB * 3]       # reads as list[RGB]

    The first argument is the plain type the field reads and writes as,
    such as ``list[int]``, ``list[float]`` or ``list[YourStruct]``. The
    ``Elem * N`` metadata is the runtime :class:`Array`, which the field
    machinery unwraps. Bind it to a module-level alias to reuse it. See
    ``test/_typing_repro.py`` for the mypy contract.

    **Adapted elements** transform each element between the wire plane and
    the user plane. Spell them ``array(THUMB_PTR @ UInt32, 8)`` or
    ``Array.of(UInt32, 8, adapt=THUMB_PTR)``. An adapted array's live
    element list holds user-plane values, which it has to do so that
    ``s.fns[0] = addr`` and ``s.fns == [...]`` operate on the values the
    field reads as.

    The consequence is that an adapted array field canonicalizes its bytes
    on repack. Every element round-trips through ``load`` and then
    ``store``, so a wire value the adapter cannot represent comes back
    normalized: a THUMB table entry parsed with bit 0 clear repacks with it
    set. ``parse -> pack`` is therefore the identity only for canonical wire
    values, in the same way that a ``String`` field canonicalizes its
    terminator and pad. Read the table unadapted when exact byte
    preservation of malformed data matters. A scalar adapted field keeps
    its slot in the wire plane instead, so it round-trips exactly in every
    case.
    """

    # Immutable value object: the byte order is compiled into the scalar
    # codec and the size into num_bits at construction, so the identity
    # attributes are read-only (and instances are shared via Array.of).
    # Mutating one would desync the cached codec from a live read; build
    # a new Array to change any of them.
    __slots__ = (
        "_element",
        "_count",
        "_endian",
        "_endian_set",
        "_num_bits",
        "_scalar_codec",
        "_adapter",
    )
    _cache: ClassVar[Dict[tuple, Array]] = {}

    def __init__(
        self,
        element,
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
        adapt: Optional[Adapter] = None,
    ):
        if not isinstance(count, int) or count <= 0:
            raise PlanCompileError(f"Array count must be a positive int, got {count!r}")
        # A fused element codec (adapter @ BitType) is the same thing as
        # adapt= on the array: split it here so nothing downstream (the
        # scalar classification, the plan, the parse/pack paths) ever sees
        # an Adapted. Array.of's cache still keys on the Adapted object, so
        # a module-level fused alias shares one Array as usual.
        # u16 and UInt16 both mean the scalar: the field aliases read like C
        # in a record body, so they arrive here too, and failing three layers
        # down with an Annotated compile error taught nobody anything.
        element = unwrap_alias(element)
        if isinstance(element, Adapted):
            if adapt is not None:
                raise PlanCompileError(
                    f"Array element {element!r} already carries an adapter;"
                    f" drop adapt="
                )
            adapt = element.adapter
            element = element.base
        if adapt is not None and not isinstance(adapt, Adapter):
            raise PlanCompileError(
                f"Array adapt= must be a bytemaker.adapters.Adapter," f" got {adapt!r}"
            )
        self._adapter = adapt
        # ``endian=None`` means "unset": standalone parse/pack resolve it to
        # big (the historical default), but as a Struct FIELD an unset array
        # inherits the record's byte order (like a C array; see
        # compile_plan). An explicit endian is honored either way.
        self._endian_set = endian is not None
        resolved = (
            validate_endianness(endian, name="Array endian", exc=PlanCompileError)
            if endian is not None
            else "big"
        )
        self._scalar_codec = None
        if isinstance(element, (StructMeta, Array)):
            elem_bits = element.num_bits
        elif isinstance(element, type) and issubclass(element, BitType):
            _reject_foreign_value_override("Array", "element", element)
            elem_bits = element.num_bits
            # Sub-byte scalar elements are fine as a Struct FIELD (the plan
            # flattens each element into an ordinary sub-byte leaf on the
            # shiftmask tier); only the STANDALONE byte-slicing parse/pack
            # paths need whole-byte elements, and they guard themselves.
            # Classify through the plan compiler so Array cannot drift from
            # the Struct decode rules (also rejects e.g. non-IEEE floats).
            try:
                _width, kind, letter = _classify_scalar(element)
            except PlanCompileError as exc:
                raise PlanCompileError(f"Array of {element.__name__}: {exc}") from None
            struct_obj = None
            if kind in ("u", "s", "f") and letter is not None and elem_bits % 8 == 0:
                prefix = "<" if resolved == "little" else ">"
                struct_obj = _pystruct.Struct(f"{prefix}{count}{letter}")
            self._scalar_codec = (kind, struct_obj)
        else:
            raise PlanCompileError(
                f"Array element must be a Struct class, a BitType class, or"
                f" an Array, got {element!r}"
            )
        # An adapter transforms one scalar VALUE. On a Struct- or
        # Array-element array parse/pack would hand it a record (or a list),
        # and the store-time _coerce_one path ignores it entirely: two
        # answers for one array, no diagnostic. Refuse it at construction.
        if adapt is not None and self._scalar_codec is None:
            raise PlanCompileError(
                f"Array adapt= transforms scalar element values; {element!r}"
                f" elements carry their own layout (a nested Struct adapts"
                f" its own fields; a nested Array adapts its elements)"
            )
        self._element = element
        self._count = count
        self._endian = resolved
        self._num_bits = elem_bits * count

    @property
    def element(self):
        return self._element

    @property
    def count(self) -> int:
        return self._count

    @property
    def endian(self) -> Literal["big", "little"]:
        return self._endian

    @property
    def adapter(self) -> Optional[Adapter]:
        """The element adapter, or None. It is the fourth declarative field,
        alongside element, count and declared_endian. Those four together
        are what ``__reduce__`` rebuilds an equivalent Array from."""
        return self._adapter

    @property
    def declared_endian(self) -> Optional[Literal["big", "little"]]:
        """The byte order this Array was declared with, or None when it was
        left unset.

        One Array object means two things. Standalone, an unset array
        resolves to big, the historical default, now guarded (see
        parse/pack). As a Struct field it inherits the record's byte order,
        like a C array. ``endian`` always answers with the resolved
        standalone value, so this property is the only way to tell
        "explicitly big" from "unset"."""
        return self._endian if self._endian_set else None

    @property
    def num_bits(self) -> int:
        return self._num_bits

    # Overloads map the element CLASS to the decoded VALUE type: a Struct
    # class parses to instances of itself, a BitType class to its py_type
    # (UInt* -> int, Float* -> float, String -> str, Buffer -> bytes), and
    # a nested Array to lists of its own value type.
    @typing.overload
    @classmethod
    def of(
        cls,
        element: type[_S],
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> Array[_S]: ...

    @typing.overload
    @classmethod
    def of(
        cls,
        element: type[BitType[V]],
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> Array[V]: ...

    @typing.overload
    @classmethod
    def of(
        cls,
        element: Array[V],
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> Array[List[V]]: ...

    # A fused element codec reports the ADAPTER's user-plane type, not the
    # base's: Array.of(fixed(4) @ UInt16, 8).parse(b) reads as list[float].
    @typing.overload
    @classmethod
    def of(
        cls,
        element: Adapted[V],
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> Array[V]: ...

    @classmethod
    def of(
        cls,
        element,
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
        adapt: Optional[Adapter] = None,
    ) -> Array:
        try:
            key = (element, count, endian, adapt)
            return cls._cache[key]
        except KeyError:
            arr = cls(element, count, endian, adapt)
            cls._cache[key] = arr
            return arr
        except TypeError:  # unhashable element
            return cls(element, count, endian, adapt)

    def __reduce__(self):
        # copy/deepcopy/pickle: rebuild from the declarative fields.
        # _scalar_codec caches a _pystruct.Struct (unpicklable); __init__
        # regenerates it. Pass endian back as None when unset so the
        # reconstructed array keeps inheriting the record's byte order.
        endian = self._endian if self._endian_set else None
        return (Array, (self._element, self._count, endian, self._adapter))

    # -- field support (R8): store-time narrowing helpers --------------------
    #: Duck-type marker so ``compile_plan`` (which cannot import Array without
    #: a structs<->plans cycle) recognizes an array field via getattr.
    _is_bm_array: ClassVar[bool] = True

    def field_list(self, values, label: str = "") -> NarrowingList:
        """Wrap already-decoded, in-range values into a live
        :class:`NarrowingList` for the parse path, without re-narrowing.

        ``label`` is the owning ``"Record.field"``. The generated
        ``_bm_from_tuple`` knows it and the Array does not, so passing it
        here lets a later element store through the live list name where it
        happened.
        """
        return NarrowingList(self, list(values), label)

    def _coerce_seq(self, values) -> list:
        """Validate length and narrow/canonicalize each element C-style, the
        store-time narrowing an array *field* applies (D1). Returns a plain
        list; the descriptor wraps it in a live :class:`NarrowingList`."""
        seq = list(values)
        if len(seq) != self._count:
            raise ValueError(
                f"array field expects exactly {self._count} elements,"
                f" got {len(seq)}"
            )
        return [self._coerce_one(v) for v in seq]

    def _coerce_one(self, value):
        """Coerce one element to its plain stored form, exactly as the scalar
        field descriptors do.

        An Int or SInt element goes through ``operator.index`` and a C
        mask, which rejects float and str and emits the opt-in
        NarrowingWarning. A Float element is narrowed through the codec
        (D1). A Struct element is type-checked and stored by reference,
        like ``_StructField``.

        For an adapted array the stored plane is the user plane, so the
        value round-trips through the wire as ``store``, narrow, then
        ``load``. The live list can therefore never show something
        ``pack()`` would not reproduce."""
        element = self._element
        if isinstance(element, StructMeta):
            if not isinstance(value, element):
                raise TypeError(
                    f"array element must be a {element.__name__} instance,"
                    f" got {value!r}"
                )
            return value  # by reference, like _StructField (see _ArrayField)
        if self._adapter is None:
            return self._narrow_wire(value)
        return self._adapter.load(self._narrow_wire(self._adapter.store(value)))

    def _narrow_wire(self, value):
        """Narrow one wire-plane numeric element value, with no adapter
        involved. This is the store-time narrowing the scalar field
        descriptors apply."""
        element = self._element
        if issubclass(element, Int):  # mirrors _UIntField / _SIntField
            iv = operator.index(value)
            mask = (1 << element.num_bits) - 1
            v = iv & mask
            if issubclass(element, SInt) and v >= (1 << (element.num_bits - 1)):
                v -= mask + 1
            if NarrowingConfig.warn and v != iv:
                _warn_narrowing(iv, v, f"array element ({element.__name__})")
            return v
        # Float element: narrow through the codec, matching _FloatField.
        return element(float(value)).value

    @property
    def num_bytes(self) -> int:
        return self.num_bits // 8

    def _require_whole_byte_elements(self, op: str) -> None:
        """The standalone parse and pack paths slice per-element bytes, so a
        sub-byte element only works as a Struct field. There ``compile_plan``
        flattens each element into an ordinary sub-byte leaf."""
        elem_bits = self._element.num_bits
        if elem_bits % 8:
            raise ValueError(
                f"{self!r}.{op}: standalone {op} needs whole-byte elements"
                f" (element is {elem_bits} bits); as a Struct FIELD this"
                f" array is supported; the plan flattens its elements"
            )
        # Multi-byte NUMERIC elements have a byte order, and an unset one
        # would be a coin flip: big by the standalone default, but
        # inherit-from-record as a field, and the wrong guess byte-reverses
        # a GBA pointer table. Standalone use therefore requires saying
        # which. (Text/bytes and single-byte elements are
        # byte-order-agnostic; Struct and Array elements carry their own.)
        if (
            not self._endian_set
            and self._scalar_codec is not None
            and self._scalar_codec[0] in ("u", "s", "f")
            and elem_bits > 8
        ):
            raise ValueError(
                f"{self!r}.{op}: no byte order declared; standalone"
                f" {op} of multi-byte numeric elements needs an explicit"
                f" endian= (as a Struct field, an unset array inherits"
                f" the record's byte order)"
            )

    def parse(self, data: BytesLike) -> List[V]:
        self._require_whole_byte_elements("parse")
        if len(data) != self.num_bytes:
            raise ValueError(
                f"{self!r}.parse: expected {self.num_bytes} bytes, got {len(data)}"
            )
        values = self._parse_wire(data)
        if self._adapter is not None:
            load = self._adapter.load
            return [load(v) for v in values]
        return values

    def _parse_wire(self, data) -> list:
        element = self.element
        if isinstance(element, StructMeta):
            from_tuple = element._bm_from_tuple
            return [
                from_tuple(t) for t in element.plan.iter_tuples(data, 0, self.count)
            ]
        size = element.num_bits // 8
        if isinstance(element, Array):
            return [
                element.parse(data[i : i + size])
                for i in range(0, self.num_bytes, size)
            ]
        # Scalar elements decode to PLAIN values. Reference semantics:
        # exactly what element(bits=<endian-normalized chunk>).value yields;
        # the fast paths below are gated to configurations where they are
        # provably identical to that reference.
        kind, struct_obj = self._scalar_codec
        if kind == "b":
            # Text/bytes elements are in stream order (no byte order to
            # apply, matching the plan engine's "b" fields and C
            # char[]; endian governs numeric elements only).
            chunks = [bytes(data[i : i + size]) for i in range(0, self.num_bytes, size)]
            if issubclass(element, String):
                return [element._decode_wire(c) for c in chunks]
            return chunks
        # Numeric elements decode two's-complement / IEEE, config-INDEPENDENT:
        # the new Struct/Plan/Array system does not consult SignedConfig
        # (that legacy global governs only the aggregate/BitType layer). This
        # makes a standalone Array and the same schema used as a Struct field
        # agree byte-for-byte; see R9 / tracker 13 #17.
        if struct_obj is not None:
            return list(struct_obj.unpack(data))  # one C-level call
        if kind == "f":
            # Letter-less floats (BFloat16 & co.): decode each chunk through
            # the element's own codec, byte order applied like the ints'.
            # (Unsigned width-exact bits: from_int is two's-complement
            # strict and would reject sign-bit-set patterns.)
            elem_bits = element.num_bits
            return [
                element(
                    bits=BitVector(
                        format(
                            int.from_bytes(bytes(data[i : i + size]), self.endian),
                            f"0{elem_bits}b",
                        )
                    )
                ).value
                for i in range(0, self.num_bytes, size)
            ]
        signed = kind == "s"
        return [
            int.from_bytes(bytes(data[i : i + size]), self.endian, signed=signed)
            for i in range(0, self.num_bytes, size)
        ]

    def pack(self, values) -> bytes:
        self._require_whole_byte_elements("pack")
        if len(values) != self.count:
            raise ValueError(
                f"{self!r}.pack: expected {self.count} elements, got {len(values)}"
            )
        if self._adapter is not None:
            store = self._adapter.store
            values = [store(v) for v in values]
        element = self.element
        if isinstance(element, StructMeta):
            return b"".join(v.pack() for v in values)
        if isinstance(element, Array):
            return b"".join(element.pack(v) for v in values)
        kind, struct_obj = self._scalar_codec
        if kind == "b":
            # Text/bytes elements: stream order, via the box's wire bytes
            # (no byte order to apply; not affected by SignedConfig).
            parts = []
            for v in values:
                if not isinstance(v, element):
                    v = element(v)  # encode-validation via the box
                parts.append(bytes(v.bits))
            return b"".join(parts)
        # Numeric elements: two's-complement / IEEE, config-INDEPENDENT and
        # narrowed at the boundary exactly as parse decodes (R9 / 13 #17).
        # struct_obj already carries the byte order, so no manual swap.
        # _narrow_wire, not _coerce_one: `values` is already the wire plane
        # (the adapter's store ran above), so re-adapting would double-apply.
        coerced = [self._narrow_wire(v) for v in values]
        if struct_obj is not None:
            return struct_obj.pack(*coerced)
        size = element.num_bits // 8  # letter-less whole-byte (e.g. UInt24)
        if kind == "f":
            return b"".join(
                element(float(v)).bits.to_int(signed=False).to_bytes(size, self.endian)
                for v in coerced
            )
        return b"".join(
            v.to_bytes(size, self.endian, signed=(kind == "s")) for v in coerced
        )

    def __mul__(self, count: int) -> Array:
        return Array.of(self, count)

    __rmul__ = __mul__

    def __repr__(self):
        name = getattr(self.element, "__name__", None) or repr(self.element)
        adapted = f", adapt={self._adapter.name}" if self._adapter else ""
        # An unset byte order must not read as an explicit one.
        endian = f"endian={self._endian!r}" if self._endian_set else "endian=unset"
        return f"Array({name} * {self.count}, {endian}{adapted})"


# --------------------------------------------------------------------------
# Checker-friendly field aliases live in bytemaker.fields (which also
# resolves arbitrary uN/sN widths lazily, e.g. ``from bytemaker.fields
# import u31``); the common names are re-exported here for compatibility.
# --------------------------------------------------------------------------

from bytemaker.fields import (  # noqa: E402,F401
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
