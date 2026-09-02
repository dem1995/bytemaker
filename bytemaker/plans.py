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

* ``"lsb"``: bit offset 0 is the least-significant bit of byte 0,
  matching little-endian C bitfield allocation (e.g. ARM/GBA).
* ``"msb"``: bit offset 0 is the most-significant bit of byte 0, matching the
  stream order of ``to_bits_aggregate`` (each field's canonical bits
  concatenated in declaration order).

The default follows the record's endian: "lsb" under ``endian="little"``
and "msb" under ``endian="big"``, which is how C compilers allocate
bitfields on a target of the same endianness. A format that mixes the two
(the GBA's LZ77 token is MSB-first on a little-endian machine) states
``bit_order`` explicitly.

Multi-byte fields whose byte order disagrees with the record's natural
integer orientation are handled with a post-extract byte swap folded into the
plan. Endianness of sub-byte fields is meaningless and ignored.
"""

from __future__ import annotations

import dataclasses
import struct as _struct

from bytemaker.bittypes import (
    BitType,
    Buffer,
    Float,
    Int,
    SInt,
    String,
    bytes_to_bittype,
)
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import (
    Dict,
    Iterator,
    List,
    Literal,
    Mapping,
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

    ``kind`` is ``"u"`` (unsigned int), ``"s"`` (signed int), ``"f"``
    (float), or ``"b"`` (bytes payload: String/Buffer fields, where the tuple
    entry is the field's wire ``bytes``). Nested Structs are flattened away
    before FieldSpecs are made; ``name`` is dotted (``"child.x"``) for
    their leaves.
    """

    __slots__ = (
        "name",
        "bit_offset",
        "bit_width",
        "kind",
        "letter",
        "endian",
        "codec",
    )

    def __init__(
        self,
        name: str,
        bit_offset: int,
        bit_width: int,
        kind: str,
        letter: Optional[str],
        endian: Literal["big", "little"],
        codec: Optional[type] = None,
    ):
        self.name = name
        self.bit_offset = bit_offset
        self.bit_width = bit_width
        self.kind = kind
        self.letter = letter
        self.endian = endian
        # The BitType class for "f" leaves: the shiftmask tier converts
        # float values <-> bit patterns through the type's own codec, so
        # non-IEEE floats (BFloat16/TF19/FP24) and IEEE floats knocked off
        # the struct tier (sub-byte siblings, cross-endian) both work.
        self.codec = codec

    def __repr__(self):
        return (
            f"FieldSpec({self.name!r}, bit_offset={self.bit_offset},"
            f" bit_width={self.bit_width}, kind={self.kind!r})"
        )


def _float_pattern_conv(codec: type, width: int) -> tuple:
    """Return a ``(value -> bit pattern int, bit pattern int -> value)`` pair
    built from the float type's own codec, in natural (unswapped) bit
    order."""

    def to_pattern(value, _c=codec):
        return _c(float(value)).bits.to_int(signed=False)

    def from_pattern(pattern, _c=codec, _w=width):
        # Width-exact unsigned construction (from_int is two's-complement
        # strict, so a pattern with the float's sign bit set would demand
        # an extra bit).
        return _c(bits=BitVector(format(pattern, f"0{_w}b"))).value

    return (to_pattern, from_pattern)


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

        # Endianness only gates the struct tier where byte order is
        # observable: multi-byte u/s ints and floats. Byte-payload ('b')
        # and single-byte fields are byte-order-agnostic, mirroring the
        # shiftmask tier's swap predicate below.
        aligned = (
            all(f.letter is not None for f in fields)
            and all(f.bit_offset % 8 == 0 for f in fields)
            and all(
                f.endian == endian or f.kind == "b" or f.bit_width <= 8 for f in fields
            )
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
            self.tier = "shiftmask"
            self.struct_obj = None
            self._int_order = "little" if bit_order == "lsb" else "big"
            natural = self._int_order
            shift_masks: List[Tuple[int, int, int, int, int, Optional[tuple]]] = []
            for f in fields:
                if bit_order == "lsb":
                    shift = f.bit_offset
                else:
                    shift = num_bits - f.bit_offset - f.bit_width
                mask = (1 << f.bit_width) - 1
                sign_bit = (1 << (f.bit_width - 1)) if f.kind == "s" else 0
                whole_bytes = (
                    f.kind in ("u", "s", "f")
                    and f.bit_width % 8 == 0
                    and f.bit_width > 8
                )
                swap = f.bit_width // 8 if whole_bytes and f.endian != natural else 0
                # nbytes > 0 marks a bytes-payload field: its tuple entry is
                # `bytes`, converted at the int boundary with the tier's own
                # bit ordering (stream order, matching the int fields).
                nbytes = f.bit_width // 8 if f.kind == "b" else 0
                # Float leaves are boxed at the tuple boundary through the
                # type's own codec (value <-> natural-order bit pattern);
                # byte order rides the same swap as multi-byte ints, so
                # non-IEEE, cross-endian, and misaligned floats all carry.
                fconv = None
                if f.kind == "f":
                    if f.codec is None:  # pragma: no cover - compile_plan sets it
                        raise PlanCompileError(
                            f"float field {f.name!r} carries no codec class"
                        )
                    fconv = _float_pattern_conv(f.codec, f.bit_width)
                shift_masks.append((shift, mask, sign_bit, swap, nbytes, fconv))
            self.shift_masks = tuple(shift_masks)

    @property
    def num_bytes(self) -> int:
        """Record size in whole bytes (``num_bits // 8``)."""
        return self.num_bits // 8

    # ------------------------------------------------------------------ bulk
    def unpack_tuple(self, data) -> tuple:
        """Decode one record's bytes into a flat tuple of plain values.

        ``data`` must be exactly :attr:`num_bytes` long. A wrong-length
        buffer raises ``ValueError`` on both tiers, rather than decoding
        from the wrong byte positions.
        """
        size = data.nbytes if isinstance(data, memoryview) else len(data)
        if size * 8 != self.num_bits:
            raise ValueError(
                f"unpack_tuple: expected {self.num_bits // 8} bytes, got {size}"
            )
        if self.tier == "struct":
            return self.struct_obj.unpack(data)
        raw = int.from_bytes(bytes(data), self._int_order)
        out = []
        shift_masks = self.shift_masks
        assert shift_masks is not None  # shiftmask tier
        for shift, mask, sign_bit, swap, nbytes, fconv in shift_masks:
            v = (raw >> shift) & mask
            if nbytes:
                out.append(v.to_bytes(nbytes, self._int_order))
                continue
            if swap:
                v = _bswap(v, swap)
            if fconv is not None:
                out.append(fconv[1](v))  # pattern -> float via the codec
                continue
            if sign_bit and v & sign_bit:
                v -= sign_bit << 1
            out.append(v)
        return tuple(out)

    def pack_tuple(self, values: Sequence) -> bytes:
        """Encode a flat sequence of plain values into one record's bytes.

        ``values`` must hold exactly one entry per leaf field. A wrong
        count raises ``ValueError`` on both tiers, rather than zero-filling
        missing fields or dropping extras. Out-of-range integers wrap
        C-style instead of raising, at every width.
        """
        if len(values) != len(self.fields):
            raise ValueError(
                f"pack_tuple: expected {len(self.fields)} values," f" got {len(values)}"
            )
        if self.tier == "struct":
            try:
                return self.struct_obj.pack(*values)
            except (_struct.error, TypeError):
                return self.struct_obj.pack(*self._wrap_values(values))
        acc = 0
        shift_masks = self.shift_masks
        assert shift_masks is not None  # shiftmask tier
        for (shift, mask, sign_bit, swap, nbytes, fconv), v in zip(shift_masks, values):
            if nbytes:
                v = int.from_bytes(v, self._int_order)
            elif fconv is not None:
                v = fconv[0](v)  # float -> pattern via the codec
            v &= mask
            if swap:
                v = _bswap(v, swap)
            acc |= v << shift
        return acc.to_bytes(self.num_bits // 8, self._int_order)

    def pack_into(self, buf, offset: int, values: Sequence) -> None:
        """Encode a flat value sequence straight into a writable ``buf`` at
        ``offset``.

        This is the in-place counterpart of :meth:`pack_tuple`. The struct
        tier writes through ``struct.pack_into`` with no intermediate bytes
        object, while the shiftmask tier splices. ``buf`` must be writable,
        so pass a ``bytearray`` or a writable ``memoryview``. Bounds are
        checked, so a short buffer raises instead of truncating.
        """
        if len(values) != len(self.fields):
            raise ValueError(
                f"pack_into: expected {len(self.fields)} values," f" got {len(values)}"
            )
        size = self.num_bytes
        avail = buf.nbytes if isinstance(buf, memoryview) else len(buf)
        if offset < 0 or offset + size > avail:
            raise ValueError(
                f"pack_into: a {size}-byte record at offset {offset} does not"
                f" fit in a {avail}-byte buffer"
            )
        if self.tier == "struct":
            try:
                self.struct_obj.pack_into(buf, offset, *values)
            except (_struct.error, TypeError):
                # Same C-narrowing fallback as pack_tuple. A partial write
                # from the failed attempt is fully overwritten by the retry.
                self.struct_obj.pack_into(buf, offset, *self._wrap_values(values))
            return
        buf[offset : offset + size] = self.pack_tuple(values)

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

        ``count=None`` reads as many whole records as fit between
        ``offset`` and the end of ``buf``. An explicit ``count`` larger
        than the number of whole records available raises ``ValueError``,
        on both tiers alike.
        """
        size = self.num_bytes
        view = memoryview(buf)
        # A negative offset would INFLATE avail ((len - -8) // size) and
        # then slice Python-style from the end: silently wrong records on
        # the shiftmask tier, a confusing struct.error on the struct tier.
        # Record offsets are not string indices; reject out-of-buffer.
        if offset < 0 or offset > len(view):
            raise ValueError(
                f"iter_tuples: offset {offset} is outside the buffer"
                f" (0..{len(view)})"
            )
        avail = (len(view) - offset) // size
        if count is None:
            count = avail
        elif count < 0:
            raise ValueError(f"iter_tuples: count must be non-negative, got {count}")
        elif count > avail:
            raise ValueError(
                f"iter_tuples: requested {count} records but only {avail}"
                f" whole records are available from offset {offset}"
            )
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
            if f.kind == "b":
                nbytes = f.bit_width // 8
                if not isinstance(v, (bytes, bytearray)) or len(v) != nbytes:
                    bad.append(f"{f.name}={v!r} is not exactly {nbytes} bytes")
                continue
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
        raise ValueError(
            f"no field named {name!r}; fields are {[f.name for f in self.fields]}"
        )

    def bit_offset(self, name: str) -> int:
        """Stream bit offset of a (possibly dotted) field name."""
        return self._find(name).bit_offset

    def byte_offset(self, name: str) -> int:
        """Byte offset of a byte-aligned field; raises ``ValueError`` otherwise."""
        f = self._find(name)
        if f.bit_offset % 8:
            raise ValueError(f"field {name!r} is not byte-aligned (bit {f.bit_offset})")
        return f.bit_offset // 8

    def byte_span(self, name: str) -> Tuple[int, int]:
        """``(byte offset, byte width)`` of a byte-aligned field.

        Addressing a field's bytes on their own takes both numbers. The
        offset says where the field starts, and the width says how far it
        runs.
        """
        f = self._find(name)
        if f.bit_offset % 8 or f.bit_width % 8:
            raise ValueError(
                f"field {name!r} does not occupy whole bytes"
                f" (bit {f.bit_offset}, {f.bit_width} bits wide)"
            )
        return f.bit_offset // 8, f.bit_width // 8

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
        # A float rides the IEEE struct codec only if it maps to a
        # 16/32/64-bit struct letter AND declares that same letter; the
        # width-keyed letter alone would decode with the wrong codec
        # (BFloat16 -> IEEE half). Every other float -- BFloat16, FP24,
        # even misaligned widths like TF19 -- classifies letter-less and
        # is carried by the shiftmask tier through the type's OWN codec
        # (see FieldSpec.codec), so it is boxed at the tuple boundary
        # instead of rejected at class definition.
        if letter is not None and (
            getattr(bittype, "packing_format_letter", None) != letter
        ):
            letter = None
        return width, "f", letter
    if issubclass(bittype, (String, Buffer)):
        if width % 8:
            raise PlanCompileError(
                f"text/bytes fields need whole-byte widths, got {width} bits"
            )
        # The flat-tuple entry is the field's wire bytes; struct's "Ns"
        # format carries it natively on the aligned tier.
        return width, "b", f"{width // 8}s"
    raise PlanCompileError(
        f"unsupported field type {bittype.__name__}: Struct fields must be"
        f" Int/UInt/SInt, Float, String, or Buffer BitType classes,"
        f" Annotated[...] of one, or a nested Struct"
    )


def compile_plan(
    field_defs: Sequence[Tuple[str, type]],
    endian: Literal["big", "little"],
    bit_order: Literal["lsb", "msb"],
    owner_name: str = "<record>",
    endian_overrides: Optional[Mapping[str, Literal["big", "little"]]] = None,
) -> Plan:
    """Compile ``(name, type)`` field definitions into a :class:`Plan`.

    Types may be scalar BitType classes or Struct classes. A Struct class
    is flattened, and its leaves keep the child's endianness.

    ``endian_overrides`` maps top-level scalar field names to a per-field
    byte order. It carries the ``field(T, endian=...)`` spelling, which the
    caller has already validated.

    A malformed layout raises :class:`PlanCompileError`. Struct creation
    calls this function, so that error surfaces at import time.
    """
    if not field_defs:
        raise PlanCompileError(f"{owner_name} declares no fields")
    endian_overrides = endian_overrides or {}

    flat: List[FieldSpec] = []
    offset = 0

    def check_bit_order(full: str, ftype, subplan: Plan) -> None:
        """Refuse flattening a child compiled under the other bit order.

        endian survives flattening because it lives on each leaf. bit_order
        is one value per Plan, so a mismatched child would be silently
        repacked under the parent's order. The record and its values would
        be unchanged, but its bytes would differ from what it packs
        standalone, and compilation leaves nothing behind that would reveal
        it (findings #29).

        A child whose leaves are all whole bytes is exempt, because
        bit_order is provably a no-op for such a record. The aligned tier
        never reads bit_order at all. The shiftmask tier is the only code
        where bit_order exists, and it serializes its record int in an
        order that tracks bit_order, so byte-aligned layouts come out
        identical either way. That equivalence is differentially pinned on
        the shiftmask tier. Refusing the exemption would make one
        byte-aligned child unusable across parents that disagree about an
        order it does not even express.
        """
        if subplan.bit_order == bit_order:
            return
        if all(f.bit_offset % 8 == 0 and f.bit_width % 8 == 0 for f in subplan.fields):
            return
        raise PlanCompileError(
            f"{owner_name}.{full}: nested {ftype.__name__} is compiled"
            f" with bit_order={subplan.bit_order!r}, but {owner_name}"
            f" packs {bit_order!r}-first -- flattening its sub-byte"
            f" fields would silently repack them, so the same record"
            f" would produce different bytes standalone vs nested."
            f" Declare both classes with the same bit_order"
        )

    def add(prefix: str, name: str, ftype: type, field_endian) -> None:
        nonlocal offset
        full = f"{prefix}{name}"
        if getattr(ftype, "_is_bm_array", False):  # Array field (duck-typed)
            elem = ftype.element
            if getattr(elem, "_is_bm_array", False):
                raise PlanCompileError(
                    f"{owner_name}.{full}: a 2-D array field is not supported"
                    f" yet; declare the inner Array as a Struct element, or"
                    f" flatten to a single Array and index with i*cols + j"
                )
            if isinstance(elem, type) and issubclass(elem, (String, Buffer)):
                raise PlanCompileError(
                    f"{owner_name}.{full}: an Array of {elem.__name__}"
                    f" (text/bytes) is not supported as a field yet; use a"
                    f" single String.of(nbytes=N*K) / Buffer of the full"
                    f" width and split in your own code, or wrap the run in"
                    f" a Struct element"
                )
            # Numeric leaves inherit the record's byte order unless the array
            # was given an explicit endian (C arrays follow the struct's
            # order; the `T * N` sugar leaves it unset). A Struct element
            # keeps its own declared endian via the nested-Struct branch.
            eff_endian = ftype.endian if ftype._endian_set else field_endian
            elem_plan = getattr(elem, "plan", None)
            if isinstance(elem_plan, Plan):
                # Checked here, once, so the error names the FIELD ("rows")
                # rather than the synthetic first element ("rows.0") the
                # per-element recursion would report.
                check_bit_order(full, elem, elem_plan)
            for i in range(ftype.count):
                add(f"{full}.", str(i), elem, eff_endian)
            return
        subplan = getattr(ftype, "plan", None)
        if isinstance(subplan, Plan):  # nested Struct: flatten, keep child endian
            check_bit_order(full, ftype, subplan)
            for leaf in subplan.fields:
                flat.append(
                    FieldSpec(
                        f"{full}.{leaf.name}",
                        offset,
                        leaf.bit_width,
                        leaf.kind,
                        leaf.letter,
                        leaf.endian,
                        leaf.codec,
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
        if kind == "b":
            # Byte strings have no byte order; never force the shiftmask
            # tier on their account.
            field_endian = endian
        flat.append(
            FieldSpec(
                full,
                offset,
                width,
                kind,
                letter,
                field_endian,
                ftype if kind == "f" else None,
            )
        )
        offset += width

    for name, ftype in field_defs:
        add("", name, ftype, endian_overrides.get(name, endian))

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

    The behavior contract is to be byte-identical to
    ``bytemaker.conversions._legacy_aggregate`` for every input either path
    accepts, which the differential suite enforces.

    Parsing boxes each field with ``bytes_to_bittype``, which is
    bits-authoritative and computes no values. Packing reuses each
    instance's canonical bits.
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
        """Box ``data`` back into an instance of the dataclass. Each field is
        one byte slice, decoded with ``bytes_to_bittype``."""
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
        """Serialize ``obj``'s fields to bytes in ``endianness`` order. A
        non-BitType value is coerced C-style through its field's type."""
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
                if letter is not None and (
                    getattr(ftype, "packing_format_letter", None) != letter
                ):
                    # Non-IEEE float (e.g. BFloat16): no struct shortcut;
                    # the boxed coercion path uses the type's own codec.
                    letter = None
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
