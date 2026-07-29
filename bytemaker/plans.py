"""
Compiled layout plans: the single artifact a record's I/O derives from.

A :class:`Plan` is compiled once per record class (at class-definition time for
:class:`bytemaker.structs.Struct` subclasses; lazily-then-cached for legacy
dataclasses of BitTypes) and is the single source of truth for that record's
layout: total size, per-field offsets/widths, and the execution engine.

Two engines exist, chosen at compile time:

* **aligned tier** (``tier == "struct"``): every leaf field is byte-aligned
  with a standard width (8/16/32/64-bit ints, 16/32/64-bit floats) and a
  uniform byte order, so the whole record rides one cached
  :class:`struct.Struct`.
* **shift/mask tier** (``tier == "shiftmask"``): anything else. The record is
  treated as one big integer (``int.from_bytes`` over the whole record) and
  each field -- byte-aligned or not, byte-straddling or not -- is a
  ``(shift, mask, sign_bit, byteswap)`` bit range of it. Because every field
  is just a bit range, mixed aligned/sub-byte records need no special
  handling.

``BitVector`` is deliberately absent from both engines.

Bit order (shift/mask tier only; the aligned tier is unaffected):

* ``"lsb"`` (default): bit offset 0 is the least-significant bit of byte 0,
  matching little-endian C bitfield allocation (e.g. ARM/GBA).
* ``"msb"``: bit offset 0 is the most-significant bit of byte 0, matching the
  stream order of ``to_bits_aggregate`` (each field's canonical bits
  concatenated in declaration order).

Multi-byte fields whose byte order disagrees with the record's natural
integer orientation are handled with a post-extract byte swap folded into the
plan. Endianness of sub-byte fields is meaningless and ignored.
"""

from __future__ import annotations

import dataclasses
import struct as _struct

from bytemaker.bittypes import BitType, Float, Int, SInt, bytes_to_bittype
from bytemaker.typing_redirect import (
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
)

__all__ = [
    "PlanCompileError",
    "FieldSpec",
    "Plan",
    "LegacyRecordPlan",
    "compile_plan",
    "compile_legacy_record_plan",
]


class PlanCompileError(ValueError):
    """A record layout cannot be compiled; raised at class-definition time."""


_INT_LETTERS = {8: "b", 16: "h", 32: "i", 64: "q"}
_FLOAT_LETTERS = {16: "e", 32: "f", 64: "d"}


def _bswap(value: int, num_bytes: int) -> int:
    """Reverse the byte order of a ``num_bytes``-wide unsigned value (involution)."""
    return int.from_bytes(value.to_bytes(num_bytes, "big"), "little")


class FieldSpec:
    """One leaf field of a compiled record layout.

    ``kind`` is ``"u"`` (unsigned int), ``"s"`` (signed int) or ``"f"``
    (float). Nested Structs are flattened away before FieldSpecs are made;
    ``name`` is dotted (``"child.x"``) for their leaves.
    """

    __slots__ = ("name", "bit_offset", "bit_width", "kind", "letter", "endian")

    def __init__(
        self,
        name: str,
        bit_offset: int,
        bit_width: int,
        kind: str,
        letter: Optional[str],
        endian: Literal["big", "little"],
    ):
        self.name = name
        self.bit_offset = bit_offset
        self.bit_width = bit_width
        self.kind = kind
        self.letter = letter
        self.endian = endian

    def __repr__(self):
        return (
            f"FieldSpec({self.name!r}, bit_offset={self.bit_offset},"
            f" bit_width={self.bit_width}, kind={self.kind!r})"
        )


class Plan:
    """The compiled layout of one record class. Immutable once built.

    The flat-tuple methods (:meth:`unpack_tuple`, :meth:`pack_tuple`,
    :meth:`iter_tuples`) are the public bulk escape hatch: they move plain
    Python values with no per-field object materialization at all.
    """

    __slots__ = (
        "num_bits",
        "endian",
        "bit_order",
        "tier",
        "fields",
        "struct_obj",
        "shift_masks",
        "_int_order",
        "_wrap_specs",
    )

    def __init__(
        self,
        fields: Tuple[FieldSpec, ...],
        endian: Literal["big", "little"],
        bit_order: Literal["lsb", "msb"],
    ):
        num_bits = sum(f.bit_width for f in fields)
        self.fields = fields
        self.endian = endian
        self.bit_order = bit_order
        self.num_bits = num_bits

        # (mask, sign_bit) per field for C-style narrowing of int fields;
        # None for float fields.
        self._wrap_specs = tuple(
            (
                (
                    (1 << f.bit_width) - 1,
                    (1 << (f.bit_width - 1)) if f.kind == "s" else 0,
                )
                if f.kind in ("u", "s")
                else None
            )
            for f in fields
        )

        aligned = (
            all(f.letter is not None for f in fields)
            and all(f.bit_offset % 8 == 0 for f in fields)
            and all(f.endian == endian for f in fields)
        )
        if aligned:
            self.tier = "struct"
            prefix = "<" if endian == "little" else ">"
            self.struct_obj = _struct.Struct(
                prefix + "".join(f.letter for f in fields)  # type: ignore[misc]
            )
            self.shift_masks = None
            self._int_order = None
        else:
            for f in fields:
                if f.kind == "f":
                    raise PlanCompileError(
                        f"field {f.name!r}: float fields require byte alignment"
                        f" and a 16/32/64-bit width (record fell back to the"
                        f" shift/mask tier, which is integer-only)"
                    )
            self.tier = "shiftmask"
            self.struct_obj = None
            self._int_order = "little" if bit_order == "lsb" else "big"
            natural = self._int_order
            shift_masks: List[Tuple[int, int, int, int]] = []
            for f in fields:
                if bit_order == "lsb":
                    shift = f.bit_offset
                else:
                    shift = num_bits - f.bit_offset - f.bit_width
                mask = (1 << f.bit_width) - 1
                sign_bit = (1 << (f.bit_width - 1)) if f.kind == "s" else 0
                whole_bytes = f.bit_width % 8 == 0 and f.bit_width > 8
                swap = (
                    f.bit_width // 8
                    if whole_bytes and f.endian != natural
                    else 0
                )
                shift_masks.append((shift, mask, sign_bit, swap))
            self.shift_masks = tuple(shift_masks)

    @property
    def num_bytes(self) -> int:
        return self.num_bits // 8

    # ------------------------------------------------------------------ bulk
    def unpack_tuple(self, data) -> tuple:
        """Decode one record's bytes into a flat tuple of plain values."""
        if self.tier == "struct":
            return self.struct_obj.unpack(data)
        raw = int.from_bytes(bytes(data), self._int_order)
        out = []
        for shift, mask, sign_bit, swap in self.shift_masks:
            v = (raw >> shift) & mask
            if swap:
                v = _bswap(v, swap)
            if sign_bit and v & sign_bit:
                v -= sign_bit << 1
            out.append(v)
        return tuple(out)

    def pack_tuple(self, values: Sequence) -> bytes:
        """Encode a flat sequence of plain values into one record's bytes.

        Out-of-range integers narrow C-style (wrap) rather than raising, at
        every width.
        """
        if self.tier == "struct":
            try:
                return self.struct_obj.pack(*values)
            except (_struct.error, TypeError):
                return self.struct_obj.pack(*self._wrap_values(values))
        acc = 0
        for (shift, mask, sign_bit, swap), v in zip(self.shift_masks, values):
            v &= mask
            if swap:
                v = _bswap(v, swap)
            acc |= v << shift
        return acc.to_bytes(self.num_bits // 8, self._int_order)

    def _wrap_values(self, values: Sequence) -> list:
        wrapped = []
        for spec, v in zip(self._wrap_specs, values):
            if spec is not None and isinstance(v, int):
                mask, sign_bit = spec
                v &= mask
                if sign_bit and v & sign_bit:
                    v -= sign_bit << 1
            wrapped.append(v)
        return wrapped

    def iter_tuples(
        self, buf, offset: int = 0, count: Optional[int] = None
    ) -> Iterator[tuple]:
        """Iterate flat tuples over consecutive records in ``buf``.

        ``count=None`` reads as many whole records as fit from ``offset`` to
        the end of ``buf``.
        """
        size = self.num_bytes
        view = memoryview(buf)
        if count is None:
            count = (len(view) - offset) // size
        end = offset + count * size
        if self.tier == "struct":
            return self.struct_obj.iter_unpack(view[offset:end])
        return (
            self.unpack_tuple(view[start : start + size])
            for start in range(offset, end, size)
        )

    def validate_tuple(self, values: Sequence) -> None:
        """Raise ``ValueError`` naming each value outside its field's range."""
        bad = []
        for f, spec, v in zip(self.fields, self._wrap_specs, values):
            if spec is None:
                continue
            mask, sign_bit = spec
            if sign_bit:
                lo, hi = -sign_bit, sign_bit - 1
            else:
                lo, hi = 0, mask
            if not isinstance(v, int) or not lo <= v <= hi:
                bad.append(f"{f.name}={v!r} outside [{lo}, {hi}]")
        if bad:
            raise ValueError("out-of-range field values: " + "; ".join(bad))

    # ---------------------------------------------------------------- lookup
    def _find(self, name: str) -> FieldSpec:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"no field named {name!r}")

    def bit_offset(self, name: str) -> int:
        """Stream bit offset of a (possibly dotted) field name."""
        return self._find(name).bit_offset

    def byte_offset(self, name: str) -> int:
        """Byte offset of a byte-aligned field; raises ``ValueError`` otherwise."""
        f = self._find(name)
        if f.bit_offset % 8:
            raise ValueError(f"field {name!r} is not byte-aligned (bit {f.bit_offset})")
        return f.bit_offset // 8

    def __repr__(self):
        return (
            f"Plan(num_bits={self.num_bits}, tier={self.tier!r},"
            f" endian={self.endian!r}, fields={[f.name for f in self.fields]})"
        )


def _classify_scalar(bittype: type) -> Tuple[int, str, Optional[str]]:
    """Return (bit_width, kind, struct_letter_or_None) for a scalar BitType class."""
    width = bittype.num_bits
    if issubclass(bittype, Int):
        signed = issubclass(bittype, SInt)
        letter = _INT_LETTERS.get(width)
        if letter is not None and not signed:
            letter = letter.upper()
        return width, ("s" if signed else "u"), letter
    if issubclass(bittype, Float):
        letter = _FLOAT_LETTERS.get(width)
        return width, "f", letter
    raise PlanCompileError(
        f"unsupported field type {bittype.__name__}: Struct fields must be"
        f" Int/UInt/SInt or Float BitType classes, Annotated[...] of one,"
        f" or a nested Struct"
    )


def compile_plan(
    field_defs: Sequence[Tuple[str, type]],
    endian: Literal["big", "little"],
    bit_order: Literal["lsb", "msb"],
    owner_name: str = "<record>",
) -> Plan:
    """Compile ``(name, type)`` field definitions into a :class:`Plan`.

    Types may be scalar BitType classes or Struct classes (flattened, their
    leaves keeping the child's endianness). Raises :class:`PlanCompileError`
    (at import time, when called from Struct creation) for malformed layouts.
    """
    if not field_defs:
        raise PlanCompileError(f"{owner_name} declares no fields")

    flat: List[FieldSpec] = []
    offset = 0

    def add(prefix: str, name: str, ftype: type, field_endian) -> None:
        nonlocal offset
        full = f"{prefix}{name}"
        subplan = getattr(ftype, "plan", None)
        if isinstance(subplan, Plan):  # nested Struct: flatten, keep child endian
            for leaf in subplan.fields:
                flat.append(
                    FieldSpec(
                        f"{full}.{leaf.name}",
                        offset,
                        leaf.bit_width,
                        leaf.kind,
                        leaf.letter,
                        leaf.endian,
                    )
                )
                offset += leaf.bit_width
            return
        if not (isinstance(ftype, type) and issubclass(ftype, BitType)):
            raise PlanCompileError(
                f"{owner_name}.{full}: annotation {ftype!r} is not a BitType"
                f" class or Struct"
            )
        try:
            width, kind, letter = _classify_scalar(ftype)
        except PlanCompileError as exc:
            raise PlanCompileError(f"{owner_name}.{full}: {exc}") from None
        if width <= 0:
            raise PlanCompileError(f"{owner_name}.{full}: zero-width field")
        flat.append(FieldSpec(full, offset, width, kind, letter, field_endian))
        offset += width

    for name, ftype in field_defs:
        add("", name, ftype, endian)

    if offset % 8:
        raise PlanCompileError(
            f"{owner_name}: total size is {offset} bits, not a whole number of"
            f" bytes; pair or pad sub-byte fields until the total is a"
            f" multiple of 8"
        )
    try:
        return Plan(tuple(flat), endian, bit_order)
    except PlanCompileError as exc:
        raise PlanCompileError(f"{owner_name}: {exc}") from None


# --------------------------------------------------------------------------
# Legacy dataclasses of BitTypes (the aggregate-API fast path)
# --------------------------------------------------------------------------


class LegacyRecordPlan:
    """Byte-slicing fast path for a dataclass whose fields are all
    byte-aligned BitType classes.

    Behavior contract: byte-identical to ``bytemaker._legacy_aggregate`` for
    every input either path accepts (enforced by the differential suite).
    Parsing boxes each field with ``bytes_to_bittype`` (bits-authoritative, no
    value computation); packing reuses each instance's canonical bits.
    """

    __slots__ = ("cls", "names", "types", "offsets", "sizes", "total", "fmt_letters")

    def __init__(self, cls, names, types, offsets, sizes, fmt_letters):
        self.cls = cls
        self.names = names
        self.types = types
        self.offsets = offsets
        self.sizes = sizes
        self.total = sum(sizes)
        self.fmt_letters = fmt_letters  # per-field letter or None

    def parse(self, data: bytes, endianness: Literal["big", "little"]):
        if len(data) * 8 != self.total * 8:
            raise ValueError(
                f"Cannot convert {data!r} to {self.cls}"
                f" because the number of bits in the bytes object"
                f" ({len(data) * 8}) does not match the number of bits in the"
                f" unit type ({self.total * 8})"
            )
        return self.cls(
            *(
                bytes_to_bittype(bytes(data[o : o + s]), t, endianness=endianness)
                for o, s, t in zip(self.offsets, self.sizes, self.types)
            )
        )

    def pack(self, obj, endianness: Literal["big", "little"]) -> bytes:
        parts = []
        for name, ftype in zip(self.names, self.types):
            v = getattr(obj, name)
            if not isinstance(v, ftype):
                v = ftype(v)  # trycast semantics, incl. C-narrowing/int_format
            b = bytes(v)  # instance-endianness aware, like to_bytes_individual
            parts.append(b[::-1] if endianness == "little" else b)
        return b"".join(parts)


_LEGACY_PLAN_CACHE: Dict[type, Optional[LegacyRecordPlan]] = {}


def compile_legacy_record_plan(
    dataclass_type: type, resolved_hints: Dict[str, type]
) -> Optional[LegacyRecordPlan]:
    """Compile (and cache) a fast-path plan for a legacy dataclass, or return
    ``None`` (also cached) if any field disqualifies it -- ctypes/PyType
    fields, nested dataclasses, or sub-byte fields all fall back to the
    reference implementation."""
    try:
        return _LEGACY_PLAN_CACHE[dataclass_type]
    except KeyError:
        pass

    plan: Optional[LegacyRecordPlan] = None
    if isinstance(dataclass_type, type) and dataclasses.is_dataclass(dataclass_type):
        names: List[str] = []
        types: List[type] = []
        offsets: List[int] = []
        sizes: List[int] = []
        letters: List[Optional[str]] = []
        offset = 0
        ok = True
        for field in dataclasses.fields(dataclass_type):
            ftype = resolved_hints.get(field.name)
            if not (
                isinstance(ftype, type)
                and issubclass(ftype, BitType)
                and isinstance(getattr(ftype, "num_bits", None), int)
                and ftype.num_bits > 0
                and ftype.num_bits % 8 == 0
            ):
                ok = False
                break
            names.append(field.name)
            types.append(ftype)
            offsets.append(offset)
            size = ftype.num_bits // 8
            sizes.append(size)
            offset += size
            if issubclass(ftype, Int):
                letter = _INT_LETTERS.get(ftype.num_bits)
                if letter is not None and not issubclass(ftype, SInt):
                    letter = letter.upper()
            elif issubclass(ftype, Float):
                letter = _FLOAT_LETTERS.get(ftype.num_bits)
            else:
                letter = None
            letters.append(letter)
        if ok and names:
            plan = LegacyRecordPlan(
                dataclass_type,
                tuple(names),
                tuple(types),
                tuple(offsets),
                tuple(sizes),
                tuple(letters),
            )

    _LEGACY_PLAN_CACHE[dataclass_type] = plan
    return plan
