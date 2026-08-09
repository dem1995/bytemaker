"""
Struct: fixed-layout records with plain-Python field values.

Declaration looks like a dataclass whose annotations are BitType classes (or
``Annotated[int, BitTypeClass]`` aliases such as :data:`u16`, which type
checkers see as plain ``int``), and the runtime values ARE plain ints/floats::

    from bytemaker.bittypes import SInt16, UInt16, UInt32
    from bytemaker.structs import Struct

    class WarpDestination(Struct, endian="little"):
        room_ptr: UInt32
        x:        UInt16
        y:        UInt16
        x_offset: SInt16
        y_offset: SInt16

    d = WarpDestination.parse(data)   # slots-backed instance, plain-int fields
    d.x = 0x10005                     # narrows C-style at the store -> 5
    d.pack()                          # trusts the store-time invariant
    table = (WarpDestination * 3).parse(b36)   # -> list[WarpDestination]

Key semantics (all decided at class-creation time; see bytemaker.plans for
the engine/tier rules):

* Fields hold **plain** ``int``/``float`` values in ``__slots__``; a data
  descriptor per field narrows integer stores C-style (wrap, at any bit
  width) exactly once, at the store -- including ``__init__``. ``parse``
  bypasses the descriptors (decoded values cannot be out of range).
* ``endian`` and ``bit_order`` are per-class, compile-time parameters.
* A Struct class is itself a **codec**: ``num_bits``, ``parse``, ``pack``
  (see :class:`Codec`). It deliberately is NOT a BitType subclass: the
  BitType contract (boxed ``.value``, mutable ``bits`` setter,
  ``__init__(source, value, bits)``) is scalar-shaped and does not fit
  composites.
* Nested Struct fields are flattened into the parent's plan (keeping their
  own endianness); ``T * N`` builds an :class:`Array` codec.
* Bulk escape hatch: ``T.plan.unpack_tuple`` / ``T.plan.iter_tuples`` move
  flat tuples with no per-field materialization (reads on instances go
  through a Python-level descriptor call; the hatch is the answer for
  tuple-hungry hot loops).

Set :data:`DEBUG_VALIDATE` (or the ``BYTEMAKER_DEBUG`` environment variable)
to re-validate every field range at ``pack`` time during migrations.
"""

from __future__ import annotations

import operator
import os
import struct as _pystruct
import typing

from bytemaker.adapters import Adapter
from bytemaker.bitvector import BitVector
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
from bytemaker.plans import Plan, PlanCompileError, _classify_scalar, compile_plan
from bytemaker.typing_redirect import (
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)
from bytemaker.utils import validate_endianness

if typing.TYPE_CHECKING:
    from bytemaker.typing_redirect import Self

    _S = typing.TypeVar("_S", bound="Struct")

#: What the parse paths actually require of their input: len() and slicing.
#: (The abstract Buffer protocol guarantees neither, so the concrete union
#: is the honest annotation.)
BytesLike = typing.Union[bytes, bytearray, memoryview]

try:  # 3.11+
    from typing import dataclass_transform
except ImportError:  # pragma: no cover
    try:
        from typing_extensions import dataclass_transform
    except ImportError:

        def dataclass_transform(**_kwargs):  # type: ignore[misc]
            def decorator(obj):
                return obj

            return decorator


try:  # 3.9+ typing, else typing_extensions, else no Annotated aliases
    from typing import Annotated, get_args, get_origin
except ImportError:  # pragma: no cover
    try:
        from typing_extensions import Annotated, get_args, get_origin
    except ImportError:
        Annotated = None

        def get_origin(_x):  # type: ignore[misc]
            return None

        def get_args(_x):  # type: ignore[misc]
            return ()


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

    A codec maps ``num_bits // 8`` bytes to a value and back: ``parse(data)``
    decodes, ``pack(value)`` encodes what ``parse`` returned. Struct
    *classes* satisfy it -- ``parse`` is a classmethod and the value is the
    instance, so ``S.pack(s)`` is ``s.pack()`` -- and so do :class:`Array`
    objects, whose values are lists. Scalar BitType classes do NOT: they
    carry ``num_bits`` but serialize through the constructor and
    ``bytes()``, so ``isinstance(UInt16, Codec)`` is False (compose scalars
    through a Struct or an Array, which are codecs of them). Note that
    ``runtime_checkable`` checks attribute *presence* only: a Struct
    *instance* also passes ``isinstance``, but its bound ``pack()`` takes
    no value argument -- the codec object for a Struct is the class itself.
    """

    num_bits: int

    def parse(self, data) -> Any: ...

    def pack(self, value) -> bytes: ...


# --------------------------------------------------------------------------
# Field descriptors: narrowing happens here, exactly once, at the store.
# --------------------------------------------------------------------------


def _raise_named(slot, obj, exc):
    """Re-raise a store-time conversion error naming the record class and
    field. Compile-time diagnostics always name their field; runtime value
    errors previously surfaced bare ("'str' object cannot be interpreted
    as an integer"), which on a 20-field record names nothing. The
    original message survives as the suffix and ``__cause__``."""
    field_name = slot.__name__[4:]  # strip the "_bm_" slot prefix
    raise type(exc)(f"{type(obj).__name__}.{field_name}: {exc}") from exc


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
        # serializes (D1) -- a Float32 field must not read back a full-width
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


class _AdaptedField:
    """Wraps a scalar field descriptor with an :class:`Adapter`: reads
    ``load`` the slot's wire value; writes ``store`` the user value and
    then run the inner descriptor's usual wire narrowing. The slot (and
    therefore parse/pack and the generated tuple converters, which bypass
    descriptors) always holds the WIRE value."""

    __slots__ = ("_inner", "_adapter")

    def __init__(self, inner, adapter):
        self._inner = inner
        self._adapter = adapter

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._adapter.load(self._inner.__get__(obj, objtype))

    def __set__(self, obj, value):
        try:
            wire = self._adapter.store(value)
        except (TypeError, ValueError) as exc:
            _raise_named(self._inner._slot, obj, exc)
        self._inner.__set__(obj, wire)


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
    place -- a C lvalue, and a read that never lies about what ``pack()``
    will serialize. Reordering in place (``reverse``/``sort``) is allowed:
    it preserves length and the already-narrowed contents.
    """

    __slots__ = ("_arr",)

    def __init__(self, arr, values):
        # values are pre-coerced (Array._coerce_seq) or trusted (parse).
        super().__init__(values)
        self._arr = arr

    def _violation(self):
        return ValueError(
            f"length is invariant ({len(self)} elements): an array field is"
            f" fixed-count; assign a full-length sequence to replace it"
        )

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            vals = [self._arr._coerce_one(v) for v in value]
            span = len(range(*key.indices(len(self))))
            if len(vals) != span:
                raise self._violation()
            super().__setitem__(key, vals)
        else:
            super().__setitem__(key, self._arr._coerce_one(value))

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
        # coerced, so the constructor stores them as trusted.
        return (NarrowingList, (self._arr, list(self)))


class _ArrayField:
    """Descriptor for an Array field: the slot holds a live
    :class:`NarrowingList`; assignment snapshots into a fresh fixed-length
    list (the caller's *sequence* is never aliased, per R1).

    Scope note: the snapshot copies the list container and narrows numeric
    elements to plain values. Struct *element instances* are stored by
    reference (not deep-copied) -- exactly as a scalar nested-Struct field
    does via :class:`_StructField` -- so explicitly assigning one Struct
    instance into several records (or slots) aliases it, deliberately.
    *Defaults* are the exception: ``__init__`` detach-copies Struct-valued
    defaults, scalar and array-element alike (see ``_generate_methods``),
    so default-constructed instances never share one. Numeric elements are
    immutable, so numeric arrays are fully independent."""

    __slots__ = ("_slot", "_arr")

    def __init__(self, slot, arr):
        self._slot = slot
        self._arr = arr

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        try:
            coerced = self._arr._coerce_seq(value)
        except (TypeError, ValueError) as exc:
            _raise_named(self._slot, obj, exc)
        self._slot.__set__(obj, NarrowingList(self._arr, coerced))


# Annotation-only ClassVars (invisible to hasattr on the base) that the
# metaclass assigns per class; everything else reserved is caught by the
# hasattr-over-bases check (which auto-covers future API) or the _bm_ prefix.
_RESERVED_FIELD_NAMES = frozenset({"plan", "num_bits", "num_bytes"})


# --------------------------------------------------------------------------
# Annotation resolution
# --------------------------------------------------------------------------


def _resolve_hints(cls) -> Dict[str, Any]:
    try:
        return typing.get_type_hints(cls, include_extras=True)
    except TypeError:  # pragma: no cover - pre-3.9 typing without extras
        return typing.get_type_hints(cls)


def _reject_endian_tag_metadata(owner: str, field_name: str, hint) -> None:
    """A byte-order string in Annotated metadata — the spelling a user is
    most likely to guess for per-field endianness — was silently ignored
    and produced record-order bytes. Refuse it with the real spelling."""
    if Annotated is None or get_origin(hint) is not Annotated:
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


def _unwrap_annotation(owner: str, field: str, hint) -> type:
    """``Annotated[int, UInt8]`` -> ``UInt8``; BitType/Struct classes pass
    through; anything else is a compile error."""
    _reject_endian_tag_metadata(owner, field, hint)
    if Annotated is not None and get_origin(hint) is Annotated:
        for meta in get_args(hint)[1:]:
            if isinstance(meta, (StructMeta, Array)) or (
                isinstance(meta, type) and issubclass(meta, BitType)
            ):
                return meta
        raise PlanCompileError(
            f"{owner}.{field}: Annotated[...] carries no BitType, Struct,"
            f" or Array in its metadata"
        )
    if isinstance(hint, (StructMeta, Array)) or (
        isinstance(hint, type) and issubclass(hint, BitType)
    ):
        return hint
    raise PlanCompileError(
        f"{owner}.{field}: annotation {hint!r} is not a BitType class, a"
        f" Struct, an Array, or an Annotated[...] of one"
    )


def _reject_foreign_value_override(owner: str, field_name: str, ftype) -> None:
    """Refuse a BitType subclass whose ``value`` property is (re)defined
    outside bytemaker as a field/element type.

    The plan engine moves plain wire values through slots and generated
    tuple converters; it never constructs the box on the hot path, so a
    user subclass like ``class ThumbPointer(UInt32)`` with a custom
    ``value`` property would be **silently ignored**: parse would store
    the raw wire value, pack would re-emit it untransformed, while the
    standalone box (and ``BoundField.boxed()``) applied the override —
    two answers for one field, and no diagnostic. Failing the class
    definition converts wrong bytes into an error. The sanctioned seam
    for value transforms is ``adapt=`` (:mod:`bytemaker.adapters`);
    String/Buffer codec customization via ``encoding``/``decoding`` or
    ``of(...)`` is engine-honored and unaffected (those hooks define no
    ``value``)."""
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


def _array_carries_adapter(arr) -> bool:
    """True if ``arr`` (or any Array nested in its element chain) has an
    element adapter attached — such arrays are standalone codecs only."""
    while isinstance(arr, Array):
        if arr._adapter is not None:
            return True
        arr = arr.element
    return False


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
    if isinstance(bittype, type) and issubclass(bittype, Buffer):
        return bytes
    if isinstance(bittype, type) and issubclass(bittype, BitType):
        return bittype.py_type
    return None


def _check_spec_annotation(owner, field_name, bittype, annotation, adapter=None):
    """R10 invariant: a ``field()``/``array()`` field's plain annotation is
    the type a checker trusts, so it must match the value type its wire
    ``bittype`` actually reads as — or, for an adapted field, the
    adapter's user-plane ``py_type``. Raises :class:`PlanCompileError` on
    a disagreement (the annotation-carried path enforces the same truth
    via ``_unwrap_annotation``). ``Any`` is allowed as a deliberate
    opt-out."""
    if annotation is None:
        return
    _reject_endian_tag_metadata(owner, field_name, annotation)
    ann = annotation
    if Annotated is not None and get_origin(ann) is Annotated:
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
            elem_expected = _expected_py_type(bittype.element)
            elem_ann = args[0]
            if Annotated is not None and get_origin(elem_ann) is Annotated:
                elem_ann = get_args(elem_ann)[0]
            if (
                elem_expected is not None
                and elem_ann is not Any
                and elem_ann is not elem_expected
            ):
                want = getattr(elem_expected, "__name__", elem_expected)
                _spec_type_error(
                    owner, field_name, annotation, bittype, f"list[{want}]"
                )
        return
    if ann is not expected:
        want = getattr(expected, "__name__", str(expected))
        _spec_type_error(owner, field_name, annotation, bittype, want)


def _spec_type_error(owner, field_name, annotation, bittype, want):
    raise PlanCompileError(
        f"{owner}.{field_name}: annotation {annotation!r} disagrees with the"
        f" field()/array() wire type {bittype!r} — a checker would trust the"
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
            # time -- but only when the parameter was actually left at its
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
            if elem_var is not None:  # Struct-element array: rebuild each
                span = len(ftype.element.plan.fields)
                lines.append(
                    f"    {slot_of[n]}.__set__(obj, {arr_var}.field_list(["
                    f"{elem_var}._bm_from_tuple("
                    f"values[{idx}+k*{span}:{idx}+(k+1)*{span}])"
                    f" for k in range({count})]))"
                )
                idx += count * span
            else:  # numeric array: the count flat entries are the values
                lines.append(
                    f"    {slot_of[n]}.__set__(obj, {arr_var}.field_list("
                    f"values[{idx}:{idx + count}]))"
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
    """Runtime marker produced by :func:`field`/:func:`array`. Carries the
    field's bytemaker type (a BitType class, a Struct class, or an
    :class:`Array`), an optional default, and an optional value
    :class:`Adapter`. The metaclass reads the type from here when a field
    is spelled ``name: <plain type> = field(...)``, so the annotation
    stays the plain checker type."""

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
    """Declare a Struct field whose *checker* type is the annotation and
    whose *wire* type is ``bittype`` — a scalar BitType class, a
    ``String``/``Buffer`` type (e.g. from ``String.of(...)``), a nested
    ``Struct`` class, or an ``Array``. The checker-friendly counterpart to
    the annotation-carries-the-type spellings (``uN``, ``Annotated[...]``)::

        hp:   int = field(UInt8)
        name: str = field(String.of(nbytes=4, encoding=MON_TABLE))

    Returns ``Any`` to type checkers so it is assignable to any field
    annotation; the field's real type comes from the annotation (via
    dataclass_transform), the wire type from ``bittype`` at runtime.

    ``adapt`` attaches a :class:`bytemaker.adapters.Adapter` so an encoding
    convention (THUMB bit, fixed-point scale, +1 bias, enums) lives in the
    schema: reads ``load`` the wire value, writes ``store`` the user value
    before the usual wire narrowing, and the annotation is checked against
    the adapter's ``py_type``::

        anim_fn:    int   = field(UInt32, adapt=THUMB_PTR)
        multiplier: float = field(UInt16, adapt=fixed(4))

    Scalar wire types only (an adapted :class:`Array` is a standalone
    codec; nested Structs adapt their own fields).

    ``endian`` overrides the record's byte order for THIS multi-byte
    numeric field (the C-struct rarity a mixed-endian ROM table needs)::

        char_number: int = field(UInt16, endian="big")   # in an LE record

    Text/bytes fields have no byte order, nested Structs declare their
    own at their class definition, and arrays spell it ``array(T, n,
    endian=...)`` — each of those is refused here with directions.

    A Struct-valued ``default`` (scalar or array element) is detach-copied
    per instance at ``__init__`` time, so default-constructed records never
    share one mutable instance; immutable defaults are bound as-is.
    Defaults are user-plane values (they store through the adapter).
    """
    if adapt is not None and not isinstance(adapt, Adapter):
        raise TypeError(
            f"adapt= must be a bytemaker.adapters.Adapter, got {adapt!r}"
        )
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
            # attributes mean what the docs say — for everyone.
            if (
                n.startswith("_bm_")
                or n in _RESERVED_FIELD_NAMES
                or any(hasattr(b, n) for b in bases)
            ):
                raise PlanCompileError(
                    f"{name}.{n}: field name collides with the Struct API"
                    f" ({n!r} is reserved); rename the field"
                    f" (e.g. {n + '_'!r} — layout is positional, so field"
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
            # A required field (no default) may not follow a defaulted one —
            # the generated __init__ would put a non-default param after a
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
        field_defs: List[Tuple[str, type]] = [
            (
                n,
                specs[n].bittype
                if n in specs
                else _unwrap_annotation(name, n, hints[n]),
            )
            for n in field_names
        ]
        # Adapter placement is checked FIRST (the conceptual error), then
        # the annotation/wire-type agreement.
        adapters: Dict[str, Adapter] = {
            n: spec.adapter for n, spec in specs.items() if spec.adapter
        }
        ftype_by_name = dict(field_defs)
        for n in adapters:
            if isinstance(ftype_by_name[n], (StructMeta, Array)):
                raise PlanCompileError(
                    f"{name}.{n}: adapt= supports scalar field types only;"
                    f" an adapted Array is a standalone codec (its live"
                    f" fixed-length field list does not thread adapters"
                    f" yet), and a nested Struct adapts its own fields"
                )
        # An adapted Array smuggled in as a field type (via the annotation
        # or field(Array.of(..., adapt=...))) would silently bypass its
        # adapter in the live-list read path — refuse it.
        for n, ftype in field_defs:
            if isinstance(ftype, Array) and _array_carries_adapter(ftype):
                raise PlanCompileError(
                    f"{name}.{n}: an Array carrying an adapter is a"
                    f" standalone codec and is not supported as a Struct"
                    f" field yet; parse/pack it explicitly"
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
            _check_spec_annotation(
                name, n, specs[n].bittype, hints.get(n), specs[n].adapter
            )

        if endian is None:
            endian = "big"
        validate_endianness(endian, name=f"{name}: endian", exc=PlanCompileError)
        if bit_order is None:
            bit_order = "lsb"
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
                descriptor = _ArrayField(slot, ftype)
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

        cls._bm_adapters = adapters
        _generate_methods(cls, field_defs, defaults)
        return cls

    def __mul__(cls, count: int) -> "Array":
        return Array.of(cls, count)

    def __rmul__(cls, count: int) -> "Array":
        return Array.of(cls, count)


def _is_classvar(hint) -> bool:
    if isinstance(hint, str):
        return hint.replace(" ", "").startswith(("ClassVar[", "typing.ClassVar["))
    return getattr(hint, "__origin__", None) is ClassVar or hint is ClassVar


class Struct(metaclass=StructMeta):
    """Base class for fixed-layout records; see the module docstring.

    Subclasses declare fields as annotations and may pass ``endian`` /
    ``bit_order`` as class keywords::

        class Header(Struct, endian="little"):
            magic:   UInt32
            version: UInt16 = 1
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

    def pack(self) -> bytes:
        """Encode this instance; trusts the store-time narrowing invariant."""
        values = self._bm_to_tuple()
        if DEBUG_VALIDATE:
            self.plan.validate_tuple(values)
        return self.plan.pack_tuple(values)

    def detach_copy(self) -> Self:
        """A new instance with the same field values."""
        return self._bm_from_tuple(self._bm_to_tuple())

    @property
    def sizedview(self) -> _SizedView:
        """Width-carrying live view of this record's fields.

        ``t.sizedview.<field>`` returns a :class:`BoundField` — a live lvalue
        handle. The handle and its ``.bits`` are live; width is invariant;
        reads promote to plain values, stores narrow, width-breaking
        mutations raise; ``.boxed()`` detaches a snapshot.
        """
        return _SizedView(self)

    def __eq__(self, other):
        if other.__class__ is self.__class__:
            return self._bm_to_tuple() == other._bm_to_tuple()
        return NotImplemented

    __hash__ = None  # mutable record semantics, like an eq dataclass

    def __repr__(self):
        args = ", ".join(f"{n}={getattr(self, n)!r}" for n in self._bm_fields)
        return f"{type(self).__name__}({args})"


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
    """Live lvalue handle to one Struct field (any scalar kind).

    Stores no data — only ``(owner, field name, field's BitType)``; the only
    storage is the struct's slot, so handles are live in both directions and
    never go stale. Semantics are a C lvalue's: rvalue use promotes to the
    plain value; stores narrow through the field descriptor; compound
    assignment is read-promote / full-width compute / narrowing store.

    Operators exist only where the design leaves one lawful meaning.
    ``__index__`` and the bitwise family (``& | ^ << >> ~``) are deliberately
    absent: on a value/bits seam each has two lawful meanings, so the code
    names the plane instead — ``f.value & m`` (value plane), ``f.bits & bv``
    (bit plane), ``f"{f:#x}"`` / ``f.value`` where an int is required.
    Handles are unhashable (their value mutates under them); key with
    ``f.value`` or ``f.boxed()``.
    """

    __slots__ = ("_owner", "_name", "_ftype")

    def __init__(self, owner, name: str, ftype: "type[BitType[V]]"):
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
    def bits(self) -> "BoundBits":
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

    def boxed(self) -> "BitType[V]":
        """A detached BitType snapshot (record's endianness); survives
        later struct mutation. Wire-plane: for an adapted field the box
        holds the slot's WIRE value (the box is a serialization object) —
        the user-plane number is ``.value``."""
        return self._ftype(
            self._wire_value(), endianness=type(self._owner)._bm_endian
        )

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
        return (
            f"<bound {self._ftype.__name__} {self._name}={self.value!r}"
            f" of {type(self._owner).__name__}>"
        )


class BoundBits:
    """Live bits of a bound field — a view of a view.

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
        # IndexError (a passed default=None returns None) — and the backend's
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

    Built via ``element * count`` (Struct classes and scalar BitType classes
    both support ``*``) or :meth:`Array.of`. ``parse`` returns a ``list``;
    ``pack`` accepts any sequence of the right length.

    The type parameter is the decoded ELEMENT VALUE type — ``Array.of``
    overloads infer it, so ``Array.of(UInt16, 4).parse(b)`` reads as
    ``list[int]`` and ``Array.of(RGB, 3).parse(b)`` as ``list[RGB]``.

    **Decoded scalars are plain Python values** — the one decoded-scalar
    rule, same as Struct fields: ``int``/``float`` for numeric elements,
    ``str`` for String elements (decoded through the element's
    terminator/pad policy), ``bytes`` for Buffer elements. Width lives in
    the schema (``self.element``); re-attach it on demand with the
    constructor cast, ``arr.element(v)``. ``pack`` accepts plain values
    (coerced through the element type — C-narrowing for ints,
    encode-validation for text) or boxes. ``endian`` governs numeric
    elements' byte order; text/bytes elements have no byte order and stay
    in stream order (as in the plan engine and C ``char[]``).

    **Type-checking an array field.** The terse ``field: Elem * N`` spelling
    works at runtime but is not a valid *type* to a checker (``Elem * N`` is
    an expression, not a type). For checker visibility use the ``Annotated``
    form — the array analog of the ``uN`` scalar aliases::

        colors: Annotated[list[int], UInt16 * 8]   # reads as list[int]
        tiles:  Annotated[list[RGB], RGB * 3]       # reads as list[RGB]

    The first argument is the plain type the field reads/writes as
    (``list[int]`` / ``list[float]`` / ``list[YourStruct]``); the ``Elem * N``
    metadata is the runtime :class:`Array` (unwrapped by the field
    machinery). Bind it to a module-level alias to reuse it. See
    ``test/_typing_repro.py`` for the mypy contract.
    """

    # Immutable value object: the byte order is compiled into the scalar
    # codec and the size into num_bits at construction, so the identity
    # attributes are read-only (and instances are shared via Array.of).
    # Mutating one would desync the cached codec from a live read -- build
    # a new Array to change any of them.
    __slots__ = (
        "_element", "_count", "_endian", "_endian_set", "_num_bits",
        "_scalar_codec", "_adapter",
    )
    _cache: ClassVar[Dict[tuple, "Array"]] = {}

    def __init__(
        self,
        element,
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
        adapt: Optional[Adapter] = None,
    ):
        if not isinstance(count, int) or count <= 0:
            raise PlanCompileError(f"Array count must be a positive int, got {count!r}")
        if adapt is not None and not isinstance(adapt, Adapter):
            raise PlanCompileError(
                f"Array adapt= must be a bytemaker.adapters.Adapter,"
                f" got {adapt!r}"
            )
        self._adapter = adapt
        # ``endian=None`` means "unset": standalone parse/pack resolve it to
        # big (the historical default), but as a Struct FIELD an unset array
        # inherits the record's byte order (like a C array -- see
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
            # paths need whole-byte elements — they guard themselves.
            # Classify through the plan compiler so Array cannot drift from
            # the Struct decode rules (also rejects e.g. non-IEEE floats).
            try:
                _width, kind, letter = _classify_scalar(element)
            except PlanCompileError as exc:
                raise PlanCompileError(
                    f"Array of {element.__name__}: {exc}"
                ) from None
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
    def declared_endian(self) -> Optional[Literal["big", "little"]]:
        """The byte order this Array was DECLARED with, or None when unset.

        One Array object means two things: standalone, an unset array
        resolves to big (the historical default, now guarded — see
        parse/pack); as a Struct field it inherits the record's byte
        order like a C array. ``endian`` always answers with the resolved
        standalone value, so this is the only way to tell "explicitly
        big" from "unset"."""
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
        element: "type[_S]",
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> "Array[_S]": ...

    @typing.overload
    @classmethod
    def of(
        cls,
        element: "type[BitType[V]]",
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> "Array[V]": ...

    @typing.overload
    @classmethod
    def of(
        cls,
        element: "Array[V]",
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
    ) -> "Array[List[V]]": ...

    @classmethod
    def of(
        cls,
        element,
        count: int,
        endian: Optional[Literal["big", "little"]] = None,
        adapt: Optional[Adapter] = None,
    ) -> "Array":
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

    def field_list(self, values) -> "NarrowingList":
        """Wrap already-decoded, in-range values into a live
        :class:`NarrowingList` for the parse path (no re-narrow)."""
        return NarrowingList(self, list(values))

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
        """Narrow/validate one element to its plain stored form, *exactly*
        as the scalar field descriptors do: Int/SInt via ``operator.index``
        + C mask (rejects float/str, emits the opt-in NarrowingWarning);
        Float narrowed through the codec (D1); Struct type-checked (stored
        by reference, like ``_StructField``)."""
        element = self._element
        if isinstance(element, StructMeta):
            if not isinstance(value, element):
                raise TypeError(
                    f"array element must be a {element.__name__} instance,"
                    f" got {value!r}"
                )
            return value  # by reference, like _StructField (see _ArrayField)
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
        """The standalone parse/pack paths slice per-element BYTES; a
        sub-byte element only works as a Struct field (compile_plan
        flattens each element into an ordinary sub-byte leaf)."""
        elem_bits = self._element.num_bits
        if elem_bits % 8:
            raise ValueError(
                f"{self!r}.{op}: standalone {op} needs whole-byte elements"
                f" (element is {elem_bits} bits); as a Struct FIELD this"
                f" array is supported — the plan flattens its elements"
            )
        # Multi-byte NUMERIC elements have a byte order, and an unset one
        # silently meant big here while meaning inherit-from-record as a
        # field — the exact coin flip that byte-reversed a GBA pointer
        # table. Standalone use now requires saying which. (Text/bytes
        # and single-byte elements are byte-order-agnostic; Struct and
        # Array elements carry their own.)
        if (
            not self._endian_set
            and self._scalar_codec is not None
            and self._scalar_codec[0] in ("u", "s", "f")
            and elem_bits > 8
        ):
            raise ValueError(
                f"{self!r}.{op}: no byte order declared — standalone"
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
            # apply — same rule as the plan engine's "b" fields and C
            # char[]; endian governs numeric elements only).
            chunks = [
                bytes(data[i : i + size])
                for i in range(0, self.num_bytes, size)
            ]
            if issubclass(element, String):
                return [element._decode_wire(c) for c in chunks]
            return chunks
        # Numeric elements decode two's-complement / IEEE, config-INDEPENDENT:
        # the new Struct/Plan/Array system does not consult SignedConfig
        # (that legacy global governs only the aggregate/BitType layer). This
        # makes a standalone Array and the same schema used as a Struct field
        # agree byte-for-byte -- see R9 / tracker 13 #17.
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
        coerced = self._coerce_seq(values)
        if struct_obj is not None:
            return struct_obj.pack(*coerced)
        size = element.num_bits // 8  # letter-less whole-byte (e.g. UInt24)
        if kind == "f":
            return b"".join(
                element(float(v))
                .bits.to_int(signed=False)
                .to_bytes(size, self.endian)
                for v in coerced
            )
        return b"".join(
            v.to_bytes(size, self.endian, signed=(kind == "s")) for v in coerced
        )

    def __mul__(self, count: int) -> "Array":
        return Array.of(self, count)

    __rmul__ = __mul__

    def __repr__(self):
        name = getattr(self.element, "__name__", None) or repr(self.element)
        adapted = f", adapt={self._adapter.name}" if self._adapter else ""
        # An unset byte order must not read as an explicit one.
        endian = f"endian={self._endian!r}" if self._endian_set else "endian=unset"
        return f"Array({name} * {self.count}, {endian}{adapted})"


# --------------------------------------------------------------------------
# Checker-friendly field aliases now live in bytemaker.fields (which also
# resolves arbitrary uN/sN widths lazily — e.g. ``from bytemaker.fields
# import u31``); the common names are re-exported here for compatibility.
# --------------------------------------------------------------------------

if Annotated is not None:
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
