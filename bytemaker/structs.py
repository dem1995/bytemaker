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
import typing

from bytemaker.bittypes import BitType, Float, Int, SInt, bytes_to_bittype
from bytemaker.plans import Plan, PlanCompileError, compile_plan
from bytemaker.typing_redirect import (
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

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
    "DEBUG_VALIDATE",
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
    """The structural protocol every schema atom satisfies.

    Scalar BitType classes, Struct classes, and :class:`Array` objects all
    provide ``num_bits`` plus ``parse``/``pack``; composition (arrays,
    nesting, section maps) should demand only this.
    """

    num_bits: int

    def parse(self, data) -> Any: ...

    def pack(self, value) -> bytes: ...


# --------------------------------------------------------------------------
# Field descriptors: narrowing happens here, exactly once, at the store.
# --------------------------------------------------------------------------


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
        self._slot.__set__(obj, operator.index(value) & self._mask)


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
        v = operator.index(value) & self._mask
        if v >= self._sign_bit:
            v -= self._mask + 1
        self._slot.__set__(obj, v)


class _FloatField:
    __slots__ = ("_slot",)

    def __init__(self, slot):
        self._slot = slot

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._slot.__get__(obj, objtype)

    def __set__(self, obj, value):
        self._slot.__set__(obj, float(value))


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
                f"expected a {self._child.__name__} instance, got {value!r}"
            )
        self._slot.__set__(obj, value)


# --------------------------------------------------------------------------
# Annotation resolution
# --------------------------------------------------------------------------


def _resolve_hints(cls) -> Dict[str, Any]:
    try:
        return typing.get_type_hints(cls, include_extras=True)
    except TypeError:  # pragma: no cover - pre-3.9 typing without extras
        return typing.get_type_hints(cls)


def _unwrap_annotation(owner: str, field: str, hint) -> type:
    """``Annotated[int, UInt8]`` -> ``UInt8``; BitType/Struct classes pass
    through; anything else is a compile error."""
    if Annotated is not None and get_origin(hint) is Annotated:
        for meta in get_args(hint)[1:]:
            if isinstance(meta, StructMeta) or (
                isinstance(meta, type) and issubclass(meta, BitType)
            ):
                return meta
        raise PlanCompileError(
            f"{owner}.{field}: Annotated[...] carries no BitType or Struct"
            f" class in its metadata"
        )
    if isinstance(hint, StructMeta) or (
        isinstance(hint, type) and issubclass(hint, BitType)
    ):
        return hint
    raise PlanCompileError(
        f"{owner}.{field}: annotation {hint!r} is not a BitType class, a"
        f" Struct, or an Annotated[...] of one"
    )


# --------------------------------------------------------------------------
# Code generation (once per class): __init__, _from_tuple, _to_tuple
# --------------------------------------------------------------------------


def _generate_methods(cls, field_defs, defaults) -> None:
    names = [n for n, _ in field_defs]
    env: Dict[str, Any] = {"_new": object.__new__, "_cls": cls}
    slot_of = {}
    child_of = {}
    for i, (n, ftype) in enumerate(field_defs):
        slot_of[n] = f"_s{i}"
        env[f"_s{i}"] = cls.__dict__["_bm_" + n]
        if isinstance(ftype, StructMeta):
            child_of[n] = f"_c{i}"
            env[f"_c{i}"] = ftype

    # __init__: assignments run through the narrowing descriptors.
    params = []
    for n in names:
        if n in defaults:
            env[f"_d_{n}"] = defaults[n]
            params.append(f"{n}=_d_{n}")
        else:
            params.append(n)
    body = "".join(f"    self.{n} = {n}\n" for n in names)
    init_src = f"def __init__(self, {', '.join(params)}):\n{body}"

    # _from_tuple: descriptor-bypassing construction from a flat plan tuple.
    lines = ["def _from_tuple(values):", "    obj = _new(_cls)"]
    idx = 0
    for n, ftype in field_defs:
        if n in child_of:
            span = len(ftype.plan.fields)
            lines.append(
                f"    {slot_of[n]}.__set__(obj,"
                f" {child_of[n]}._from_tuple(values[{idx}:{idx + span}]))"
            )
            idx += span
        else:
            lines.append(f"    {slot_of[n]}.__set__(obj, values[{idx}])")
            idx += 1
    lines.append("    return obj")
    from_tuple_src = "\n".join(lines) + "\n"

    # _to_tuple: flat plan tuple from slot reads (descriptors bypassed).
    parts = []
    for n, _ftype in field_defs:
        if n in child_of:
            parts.append(f"*{child_of[n]}._to_tuple({slot_of[n]}.__get__(obj))")
        else:
            parts.append(f"{slot_of[n]}.__get__(obj)")
    to_tuple_src = f"def _to_tuple(obj):\n    return ({', '.join(parts)},)\n"

    namespace: Dict[str, Any] = {}
    exec(init_src + from_tuple_src + to_tuple_src, env, namespace)  # noqa: S102
    cls.__init__ = namespace["__init__"]
    cls._from_tuple = staticmethod(namespace["_from_tuple"])
    cls._to_tuple = namespace["_to_tuple"]


# --------------------------------------------------------------------------
# The metaclass and base class
# --------------------------------------------------------------------------


@dataclass_transform(eq_default=True)
class StructMeta(type):
    """Metaclass of :class:`Struct`: turns annotated class bodies into
    compiled, slots-backed record classes, and provides ``T * N`` sugar."""

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
        for n in field_names:
            if n in ns:
                defaults[n] = ns.pop(n)
            elif defaults:
                raise PlanCompileError(
                    f"{name}.{n}: field without a default follows fields"
                    f" with defaults"
                )
        ns["__slots__"] = tuple("_bm_" + n for n in field_names)

        cls = super().__new__(mcs, name, bases, ns, **kwargs)

        hints = _resolve_hints(cls)
        field_defs: List[Tuple[str, type]] = [
            (n, _unwrap_annotation(name, n, hints[n])) for n in field_names
        ]

        if endian is None:
            endian = "big"
        if endian not in ("big", "little"):
            raise PlanCompileError(f"{name}: endian must be 'big' or 'little'")
        if bit_order is None:
            bit_order = "lsb"
        if bit_order not in ("lsb", "msb"):
            raise PlanCompileError(f"{name}: bit_order must be 'lsb' or 'msb'")

        plan = compile_plan(field_defs, endian, bit_order, owner_name=name)
        cls.plan = plan
        cls.num_bits = plan.num_bits
        cls._bm_concrete = True
        cls._bm_fields = tuple(field_names)

        for n, ftype in field_defs:
            slot = cls.__dict__["_bm_" + n]
            if isinstance(ftype, StructMeta):
                descriptor = _StructField(slot, ftype)
            elif issubclass(ftype, Int):
                mask = (1 << ftype.num_bits) - 1
                if issubclass(ftype, SInt):
                    descriptor = _SIntField(slot, mask, 1 << (ftype.num_bits - 1))
                else:
                    descriptor = _UIntField(slot, mask)
            else:  # Float; compile_plan already rejected everything else
                descriptor = _FloatField(slot)
            setattr(cls, n, descriptor)

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
    _bm_concrete: ClassVar[bool] = False
    _bm_fields: ClassVar[Tuple[str, ...]] = ()

    @classmethod
    def parse(cls, data) -> "Struct":
        """Decode ``num_bits // 8`` bytes into a new detached instance."""
        n = cls.plan.num_bytes
        if len(data) != n:
            raise ValueError(
                f"{cls.__name__}.parse: expected {n} bytes, got {len(data)}"
            )
        return cls._from_tuple(cls.plan.unpack_tuple(data))

    def pack(self) -> bytes:
        """Encode this instance; trusts the store-time narrowing invariant."""
        values = self._to_tuple()
        if DEBUG_VALIDATE:
            self.plan.validate_tuple(values)
        return self.plan.pack_tuple(values)

    def detach_copy(self) -> "Struct":
        """A new instance with the same field values."""
        return self._from_tuple(self._to_tuple())

    def __eq__(self, other):
        if other.__class__ is self.__class__:
            return self._to_tuple() == other._to_tuple()
        return NotImplemented

    __hash__ = None  # mutable record semantics, like an eq dataclass

    def __repr__(self):
        args = ", ".join(f"{n}={getattr(self, n)!r}" for n in self._bm_fields)
        return f"{type(self).__name__}({args})"


# --------------------------------------------------------------------------
# Array
# --------------------------------------------------------------------------


class Array:
    """A fixed-count codec of a uniform element codec.

    Built via ``element * count`` (Struct classes and scalar BitType classes
    both support ``*``) or :meth:`Array.of`. ``parse`` returns a ``list``;
    ``pack`` accepts any sequence of the right length. Scalar elements are
    boxed BitType instances (canonical bits; the array's ``endian`` governs
    their byte order in the stream); plain values are accepted by ``pack``
    and coerced through the element type (C-narrowing applies).
    """

    __slots__ = ("element", "count", "endian", "num_bits")
    _cache: ClassVar[Dict[tuple, "Array"]] = {}

    def __init__(self, element, count: int, endian: Literal["big", "little"] = "big"):
        if not isinstance(count, int) or count <= 0:
            raise PlanCompileError(f"Array count must be a positive int, got {count!r}")
        if isinstance(element, (StructMeta, Array)):
            elem_bits = element.num_bits
        elif isinstance(element, type) and issubclass(element, BitType):
            elem_bits = element.num_bits
            if elem_bits % 8:
                raise PlanCompileError(
                    f"Array of {element.__name__}: sub-byte scalar arrays are"
                    f" not supported (element is {elem_bits} bits); wrap the"
                    f" elements in a Struct instead"
                )
        else:
            raise PlanCompileError(
                f"Array element must be a Struct class, a BitType class, or"
                f" an Array, got {element!r}"
            )
        self.element = element
        self.count = count
        self.endian = endian
        self.num_bits = elem_bits * count

    @classmethod
    def of(
        cls, element, count: int, endian: Literal["big", "little"] = "big"
    ) -> "Array":
        try:
            key = (element, count, endian)
            return cls._cache[key]
        except KeyError:
            arr = cls(element, count, endian)
            cls._cache[key] = arr
            return arr
        except TypeError:  # unhashable element
            return cls(element, count, endian)

    @property
    def num_bytes(self) -> int:
        return self.num_bits // 8

    def parse(self, data) -> list:
        if len(data) != self.num_bytes:
            raise ValueError(
                f"{self!r}.parse: expected {self.num_bytes} bytes, got {len(data)}"
            )
        element = self.element
        if isinstance(element, StructMeta):
            from_tuple = element._from_tuple
            return [
                from_tuple(t) for t in element.plan.iter_tuples(data, 0, self.count)
            ]
        size = element.num_bits // 8
        if isinstance(element, Array):
            return [
                element.parse(data[i : i + size])
                for i in range(0, self.num_bytes, size)
            ]
        return [
            bytes_to_bittype(bytes(data[i : i + size]), element, endianness=self.endian)
            for i in range(0, self.num_bytes, size)
        ]

    def pack(self, values) -> bytes:
        if len(values) != self.count:
            raise ValueError(
                f"{self!r}.pack: expected {self.count} elements, got {len(values)}"
            )
        element = self.element
        if isinstance(element, StructMeta):
            return b"".join(v.pack() for v in values)
        if isinstance(element, Array):
            return b"".join(element.pack(v) for v in values)
        parts = []
        for v in values:
            if not isinstance(v, element):
                v = element(v)  # C-narrowing via the scalar's value setter
            b = bytes(v.bits)  # canonical big-endian bits, instance-agnostic
            parts.append(b[::-1] if self.endian == "little" else b)
        return b"".join(parts)

    def __mul__(self, count: int) -> "Array":
        return Array.of(self, count)

    __rmul__ = __mul__

    def __repr__(self):
        name = getattr(self.element, "__name__", None) or repr(self.element)
        return f"Array({name} * {self.count}, endian={self.endian!r})"


# --------------------------------------------------------------------------
# Checker-friendly field aliases: annotation says plain int/float, metadata
# carries the BitType. (Absent only on 3.8 without typing_extensions.)
# --------------------------------------------------------------------------

if Annotated is not None:
    from bytemaker.bittypes import (
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
