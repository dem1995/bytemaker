"""Mapping a base-mapped address space: :class:`Space`, extents, :class:`Entry`.

A :class:`Struct` says what a record looks like. It says nothing about
*where* records live, how many there are, or how to get at them — so every
project that maps a binary (a GBA ROM, a save file, a firmware image)
reinvents the same three things: subtract the base address, slice, and
decide how the table ends. The reinvention is where the bugs are.

:class:`Space` is that layer, declared once::

    from bytemaker.rom import Space, count, until, span

    rom = Space(open("game.gba", "rb").read(), base=0x08000000,
                endian="little", name="AoS")

    palette = rom.read(0x080E1CD0, UInt8, count(4))     # [7, 6, 8, 9]
    rewards = rom.read(0x08526390, BossRushReward, 3)   # 3 records
    rooms   = rom.read(0x0850E968, ThumbPtr, until(0))  # scan to the 0 entry

Three ideas carry the module:

* **The space owns the byte order.** ``endian`` is a required keyword on
  :class:`Space`, so scalar reads never guess and no declaration repeats it.
  Composite codecs (:class:`~bytemaker.structs.Struct` classes,
  :class:`~bytemaker.structs.Array` objects) always carry their own.
* **Extents are values, not conventions.** ``count(n)``, ``until(sentinel)``,
  ``span(end_addr)`` and ``unknown()`` are the four things anyone actually
  knows about a table's length, so "how long is it" stops being a comment.
* **An :class:`Entry` is a declaration, not a reader.** Entries can be
  written with no buffer at all — a map module stays importable without the
  ROM — and bound to a :class:`Space` later with :meth:`Entry.bind`.

Sub-byte codecs are refused: a byte address has no room for a 4-bit stride.
Wrap those in a Struct (the plan engine packs them properly) and map that.

Two layers build on that base:

* :class:`Patch` / :class:`Edit` — edits as a value. ``space.write(...,
  patch=p)`` records instead of mutating, so the edits can be verified
  against the original bytes, inverted, composed, and exported as IPS.
* :class:`Ptr` and :meth:`Space.coverage` — a typed address (decoding to a
  :class:`PtrValue`, an int that can ``.deref(space)`` itself) plus a report
  of what a map accounts for, what it leaves unaccounted for
  (:meth:`CoverageReport.gaps`, the direction a map grows in), what it
  double-claims, and where its pointers land — verified for record type and
  alignment where a pointer declares its pointee.
"""

import sys
from dataclasses import dataclass
from functools import cached_property, partial
from typing import cast

from bytemaker.adapters import Adapted, Adapter
from bytemaker.introspect import bitsizeof, fields_of, sizeof
from bytemaker.structs import (
    Array,
    Struct,
    StructMeta,
    _field_name_of,
    _structs_named,
)
from bytemaker.typing_redirect import (
    Any,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
)
from bytemaker.utils import validate_endianness

__all__ = [
    "AddressError",
    "CoverageReport",
    "Edit",
    "Entry",
    "Extent",
    "Gap",
    "IPS_EOF_OFFSET",
    "Overlap",
    "Patch",
    "PatchConflict",
    "PatchVerifyError",
    "PointerRef",
    "Ptr",
    "PtrAdapter",
    "PtrValue",
    "Region",
    "Space",
    "count",
    "span",
    "unknown",
    "until",
]

BytesLike = Union[bytes, bytearray, memoryview]


class AddressError(ValueError):
    """An address (or a span) falls outside the space it was read from.

    Its own class because a pointer audit *expects* some addresses to be
    wild and wants to catch exactly that, not every ValueError a decode
    might raise.
    """


# --------------------------------------------------------------------------
# Extents: how far a table runs
# --------------------------------------------------------------------------


class Extent:
    """Base of the four table-length declarations.

    The subclasses are spelled lower-case because they read as values at a
    declaration site (``count(4)``, ``until(0)``), which is what they are.
    """

    __slots__ = ()

    def __repr__(self):
        args = ", ".join(f"{s}={getattr(self, s)!r}" for s in self.__slots__)
        return f"{type(self).__name__}({args})"

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return all(getattr(self, s) == getattr(other, s) for s in self.__slots__)

    def __hash__(self):
        return hash((type(self).__name__,) + tuple(
            getattr(self, s) for s in self.__slots__
        ))


class count(Extent):
    """Exactly ``n`` items."""

    __slots__ = ("n",)

    def __init__(self, n: int):
        if not isinstance(n, int) or n < 0:
            raise ValueError(f"count(n) needs a non-negative int, got {n!r}")
        self.n = n


class until(Extent):
    """Items up to (not including) the first one equal to ``sentinel``.

    The sentinel is matched on the **wire**, before any adapter: an adapter
    must never change what terminates a table. ``max_count`` is the runaway
    guard — a table with no terminator inside it raises rather than reading
    to the end of the space.
    """

    __slots__ = ("sentinel", "max_count")

    def __init__(self, sentinel: Any = 0, max_count: int = 4096):
        if not isinstance(max_count, int) or max_count <= 0:
            raise ValueError(
                f"until(max_count=) needs a positive int, got {max_count!r}"
            )
        self.sentinel = sentinel
        self.max_count = max_count


class span(Extent):
    """Items from the entry's address through ``end`` (an **inclusive** end
    address, the form a disassembly listing gives you).

    The width must divide the region exactly, or the declaration is wrong
    about one of the two.
    """

    __slots__ = ("end",)

    def __init__(self, end: int):
        if not isinstance(end, int):
            raise ValueError(f"span(end) needs an int address, got {end!r}")
        self.end = end

    def __repr__(self):
        # An address in decimal is unreadable, and this one is always an
        # address (unlike count's n, which is a quantity).
        return f"span(end=0x{self.end:08X})"


class unknown(Extent):
    """The length is not known. Reads refuse; the entry still documents the
    address and record shape, and a coverage report still counts one item.
    """

    __slots__ = ("note",)

    def __init__(self, note: str = ""):
        self.note = note


#: Distinguishes "no extent passed" from ``0``/``count(0)``, both of which
#: are legitimate and would be swallowed by a falsiness test.
_INHERIT = object()


def _as_extent(extent) -> Extent:
    """``4`` -> ``count(4)``, ``None`` -> ``count(1)``, Extent -> itself."""
    if extent is None:
        return count(1)
    if isinstance(extent, Extent):
        return extent
    if isinstance(extent, int) and not isinstance(extent, bool):
        return count(extent)
    raise TypeError(
        f"extent must be an int or an Extent (count/until/span/unknown),"
        f" got {extent!r}"
    )


# --------------------------------------------------------------------------
# The space
# --------------------------------------------------------------------------


class Space:
    """A buffer viewed as a base-mapped address space.

    Args:
        buf: the bytes. A ``bytearray`` (or writable ``memoryview``) is
            required for in-place :meth:`write`; ``bytes`` is fine for
            reading and for patch-recording writes.
        base: the address the first byte lives at (``0x08000000`` for GBA
            ROM, 0 for a plain file).
        endian: byte order for SCALAR reads/writes — required, because
            guessing it is the single most expensive mistake in this layer.
            Struct and Array codecs carry their own.
        name: shown in error messages and coverage reports.
    """

    __slots__ = ("_buf", "_base", "_endian", "_name")

    def __init__(
        self,
        buf: BytesLike,
        *,
        base: int = 0,
        endian: Literal["big", "little"],
        name: str = "",
    ):
        self._buf = buf
        if not isinstance(base, int) or base < 0:
            raise ValueError(f"Space base must be a non-negative int, got {base!r}")
        self._base = base
        self._endian = validate_endianness(endian, name="Space endian")
        self._name = name

    # -- identity ----------------------------------------------------------
    @property
    def buf(self) -> BytesLike:
        return self._buf

    @property
    def base(self) -> int:
        return self._base

    @property
    def endian(self) -> "Literal['big', 'little']":
        return self._endian

    @property
    def name(self) -> str:
        return self._name

    def __len__(self) -> int:
        buf = self._buf
        return buf.nbytes if isinstance(buf, memoryview) else len(buf)

    @property
    def end(self) -> int:
        """One past the last mapped address."""
        return self._base + len(self)

    def __repr__(self):
        label = f" {self._name!r}" if self._name else ""
        return (
            f"<Space{label} {len(self)} bytes at"
            f" 0x{self._base:08X}-0x{self.end - 1:08X}, {self._endian}-endian>"
        )

    # -- address math ------------------------------------------------------
    def offset(self, addr: int) -> int:
        """Buffer offset of ``addr``, or :class:`AddressError`."""
        if not isinstance(addr, int):
            raise TypeError(f"{self._label()}: address must be an int, got {addr!r}")
        off = addr - self._base
        if off < 0 or off > len(self):
            raise AddressError(
                f"{self._label()}: address 0x{addr:08X} is outside the space"
                f" (0x{self._base:08X}-0x{self.end - 1:08X})"
            )
        return off

    def addr_of(self, offset: int) -> int:
        """The inverse of :meth:`offset`."""
        if not isinstance(offset, int) or offset < 0 or offset > len(self):
            raise AddressError(
                f"{self._label()}: offset {offset!r} is outside the space"
                f" (0..{len(self)})"
            )
        return self._base + offset

    def contains(self, addr: int) -> bool:
        """True if ``addr`` is mapped. The non-raising :meth:`offset`, for
        classifying pointers."""
        return isinstance(addr, int) and self._base <= addr < self.end

    def _label(self) -> str:
        return f"Space {self._name!r}" if self._name else "Space"

    # -- reading -----------------------------------------------------------
    def read(
        self,
        addr: int,
        codec: Any,
        extent: Union[int, Extent, None] = 1,
    ) -> Any:
        """Decode ``extent`` items of ``codec`` at ``addr``.

        ``extent`` is an :class:`Extent` or a plain item count (the two are
        interchangeable; ``4`` means ``count(4)``).

        Shape rule: ``count(1)`` — the default — returns ONE decoded item;
        every other extent returns a list, including a ``span`` or ``until``
        that happens to resolve to one item. So the return shape is a
        property of the *declaration*, never of the data.
        """
        stride = self._stride(codec)
        extent = _as_extent(extent)
        if isinstance(extent, unknown):
            raise ValueError(
                f"{self._label()}: the extent at 0x{addr:08X} is unknown()"
                f" — pass a count at the call site, or declare"
                f" count(n)/until(sentinel)/span(end_addr)"
                + (f" ({extent.note})" if extent.note else "")
            )
        if isinstance(extent, until):
            return self._scan(addr, codec, extent, stride)
        n = self._resolve_count(addr, extent, stride)
        single = isinstance(extent, count) and extent.n == 1
        return self._decode(addr, codec, n, stride, single=single)

    def scan(
        self,
        addr: int,
        codec: Any,
        sentinel: Any = 0,
        max_count: int = 4096,
    ) -> list:
        """Read items at ``addr`` until the first ``sentinel`` — the
        call-site form of ``read(addr, codec, until(sentinel))``."""
        return self._scan(
            addr, codec, until(sentinel, max_count), self._stride(codec)
        )

    def slice(self, addr: int, nbytes: int) -> memoryview:
        """A bounds-checked ``memoryview`` of ``nbytes`` at ``addr`` (no copy)."""
        off = self.offset(addr)
        if nbytes < 0 or off + nbytes > len(self):
            raise AddressError(
                f"{self._label()}: {nbytes} bytes at 0x{addr:08X} run past the"
                f" end of the space (0x{self.end - 1:08X})"
            )
        return memoryview(self._buf)[off : off + nbytes]

    # -- writing -----------------------------------------------------------
    def write(
        self,
        addr: int,
        value: Any,
        codec: Any = None,
        *,
        patch: Any = None,
    ) -> None:
        """Encode ``value`` at ``addr``.

        ``codec`` may be omitted when ``value`` is a Struct instance (or a
        non-empty list of them) — the record's own class is the codec.

        With ``patch=``, nothing is mutated: the old bytes are read and an
        edit is recorded on the patch, so the same call works on a read-only
        ``bytes`` buffer. Without it, the buffer must be writable.
        """
        if codec is None:
            codec = self._infer_codec(value)
        data = self._encode(value, codec)
        off = self.offset(addr)
        if off + len(data) > len(self):
            raise AddressError(
                f"{self._label()}: {len(data)} bytes at 0x{addr:08X} run past"
                f" the end of the space (0x{self.end - 1:08X})"
            )
        if patch is not None:
            old = bytes(memoryview(self._buf)[off : off + len(data)])
            patch.write(off, old, data)
            return
        try:
            self._buf[off : off + len(data)] = data  # type: ignore[index]
        except TypeError:
            raise TypeError(
                f"{self._label()}: the buffer is read-only; build the Space"
                f" over a bytearray for in-place writes, or pass patch= to"
                f" record the edit instead"
            ) from None

    # -- declarations ------------------------------------------------------
    def entry(
        self,
        addr: int,
        codec: Any,
        extent: Union[int, Extent, None] = 1,
        *,
        name: str = "",
        note: str = "",
    ) -> "Entry":
        """An :class:`Entry` at ``addr`` already bound to this space."""
        return Entry(addr, codec, extent, name=name, note=note, space=self)

    def bind(self, entries) -> "List[Entry]":
        """Bind a space-free map (a list of :class:`Entry`) to this space."""
        return [e.bind(self) for e in entries]

    # -- pointers ----------------------------------------------------------
    def deref(
        self,
        record: Any,
        field: Any,
        extent: Union[int, "Extent", None] = 1,
    ) -> Any:
        """Follow a :class:`Ptr` field of ``record``.

        ``field`` is the field's name — as a string, or refactor-safely as
        the CLASS attribute itself (``rom.deref(warp, WarpPoint.room_ptr)``;
        class-level access returns the field descriptor, which knows its
        name). The field must have been declared with a ``Ptr``, so the
        pointee's codec is in the schema, not at the call site. An adapted
        array of pointers dereferences element-wise and returns a list.

        (For a pointer you already read, ``value.deref(space)`` on the
        :class:`PtrValue` itself is the shortest spelling.)
        """
        field_name = field if isinstance(field, str) else _field_name_of(field)
        if field_name is None:
            hint = (
                " — that is the field's VALUE; pass the CLASS attribute"
                " (e.g. WarpPoint.room_ptr) or the name string, or call"
                " value.deref(space) directly"
                if isinstance(field, int)
                else " — pass the field's name or the class attribute"
            )
            raise TypeError(f"{self._label()}: {field!r} is not a field{hint}")
        cls = record if isinstance(record, type) else type(record)
        adapter = getattr(cls, "_bm_adapters", {}).get(field_name)
        ptr = _ptr_adapter_of(adapter)
        if ptr is None:
            known = sorted(
                n
                for n, a in getattr(cls, "_bm_adapters", {}).items()
                if _ptr_adapter_of(a) is not None
            )
            raise TypeError(
                f"{self._label()}: {getattr(cls, '__name__', cls)}.{field_name}"
                f" is not a Ptr field, so there is nothing to follow"
                + (f" (pointer fields here: {', '.join(known)})" if known else "")
            )
        value = getattr(record, field_name)
        if isinstance(value, (list, tuple)):
            return [self.deref_value(v, ptr, extent) for v in value]
        return self.deref_value(value, ptr, extent)

    def deref_value(
        self,
        addr: int,
        ptr: Any,
        extent: Union[int, "Extent", None] = 1,
    ) -> Any:
        """Follow one address through ``ptr`` (a :class:`Ptr` codec or its
        adapter) — the form for elements of a pointer list."""
        adapter = _ptr_adapter_of(ptr)
        if adapter is None:
            raise TypeError(
                f"{self._label()}: {ptr!r} is not a Ptr (or a Ptr's adapter)"
            )
        if adapter.target is None:
            raise TypeError(
                f"{self._label()}: {adapter.name} has no target codec —"
                f" Ptr(None) documents an address whose pointee is not"
                f" modelled; give Ptr a target to follow it"
            )
        return self.read(addr, adapter.target, extent)

    # -- coverage ----------------------------------------------------------
    def coverage(self, entries, *, audit_pointers: bool = True):
        """What a map accounts for: per-entry footprints, double-claims, and
        where every declared pointer lands.

        Returns a :class:`CoverageReport`. ``until`` extents are resolved by
        scanning (the terminator counts as claimed); ``unknown`` extents and
        entries that fail to read are reported unresolved with the reason
        rather than silently skipped.

        The pointer audit covers an entry whose codec is a ``Ptr`` (alone or
        as an array element) and the top-level ``Ptr`` fields of a Struct
        codec. Pointers nested inside a nested Struct are not followed —
        map the inner record as its own entry if you need them.

        Where a pointer declares a record target AND lands in a region
        mapped as records, the audit also verifies it: a hit in a region of
        a different record type reports ``mistargeted``, and a hit off the
        record stride reports ``misaligned``. Unresolvable deferred targets
        verify nothing and never fail the audit.
        """
        bound = [e if e.space is not None else e.bind(self) for e in entries]
        regions = tuple(self._resolve_region(e) for e in bound)
        overlaps = _overlaps(regions)
        pointers: list = []
        if audit_pointers:
            for region in regions:
                pointers.extend(self._audit_pointers(region, regions))
        return CoverageReport(
            space_name=self._name,
            space_size=len(self),
            space_base=self._base,
            regions=regions,
            overlaps=overlaps,
            pointers=tuple(pointers),
        )

    def _resolve_region(self, entry: "Entry"):
        declared = entry.size
        if declared is not None:
            end = entry.addr + declared
            if not (self.contains(entry.addr) and end <= self.end):
                return Region(
                    entry,
                    None,
                    f"0x{entry.addr:08X}+{declared} runs outside the space",
                )
            return Region(entry, declared)
        if isinstance(entry.extent, unknown):
            note = entry.extent.note or "extent not declared"
            return Region(entry, None, f"unknown(): {note}")
        try:
            values = entry.read()
        except (ValueError, TypeError) as exc:
            return Region(entry, None, f"{type(exc).__name__}: {exc}")
        # A scanned table's bytes include its terminator.
        return Region(entry, (len(values) + 1) * entry.stride)

    def _audit_pointers(self, region, regions) -> list:
        entry = region.entry
        codec = entry.codec
        source = region.name
        direct = _ptr_adapter_of(codec)
        out: list = []
        if direct is not None:
            for index, value in _enumerate_values(self._safe_read(entry)):
                verdict, owner = self._classify_address(value, regions, direct)
                out.append(
                    PointerRef(source, None, index, value, verdict, owner)
                )
            return out
        if not isinstance(codec, StructMeta):
            return out
        ptr_fields = [
            (info.name, _ptr_adapter_of(info.adapter))
            for info in fields_of(codec)
            if _ptr_adapter_of(info.adapter) is not None
        ]
        if not ptr_fields:
            return out
        records = self._safe_read(entry)
        if records is None:
            return out
        if not isinstance(records, list):
            records = [records]
        for rec_index, rec in enumerate(records):
            for field_name, ptr_adapter in ptr_fields:
                value = getattr(rec, field_name)
                for sub, one in _enumerate_values(value):
                    index = rec_index if sub is None else (rec_index, sub)
                    verdict, owner = self._classify_address(
                        one, regions, ptr_adapter
                    )
                    out.append(
                        PointerRef(
                            source, field_name, index, one, verdict, owner
                        )
                    )
        return out

    def _safe_read(self, entry: "Entry"):
        try:
            return entry.read()
        except (ValueError, TypeError):
            return None

    def _classify_address(self, addr, regions, adapter=None):
        if not isinstance(addr, int):
            return ("outside", None)
        if addr == 0:
            return ("null", None)
        if not self.contains(addr):
            return ("outside", None)
        for region in regions:
            end = region.end
            if end is not None and region.start <= addr < end:
                return self._verify_target(addr, region, adapter)
        return ("unclaimed", None)

    def _verify_target(self, addr, region, adapter):
        """``claimed`` — unless the pointer DECLARES a record type and the
        claiming region disagrees.

        Checkable only when the region's entry codec is a Struct class and
        the pointer's target is (or resolves to) one: a raw-byte or scalar
        region can legitimately contain records the map has not modelled at
        that granularity, and ``Ptr(None)`` / an unresolvable name declares
        nothing to check. Two defect verdicts come out of this:
        ``mistargeted`` (lands in a region mapped as a DIFFERENT record
        type) and ``misaligned`` (right record type, but not on a record
        boundary — usually an off-by-one in the region's address or an
        interior pointer worth knowing about).
        """
        target = _checkable_target(adapter)
        codec = region.entry.codec
        if target is None or not isinstance(codec, StructMeta):
            return ("claimed", region.name)
        if codec is not target:
            return ("mistargeted", region.name)
        if (addr - region.start) % region.entry.stride:
            return ("misaligned", region.name)
        return ("claimed", region.name)

    # -- internals ---------------------------------------------------------
    def _stride(self, codec) -> int:
        """One item's size in bytes; refuses sub-byte codecs."""
        try:
            bits = bitsizeof(codec)
        except TypeError:
            raise TypeError(
                f"{self._label()}: {codec!r} is not a codec (expected a Struct"
                f" class, an Array, a BitType class, or a fused"
                f" adapter @ BitType)"
            ) from None
        if bits % 8:
            raise ValueError(
                f"{self._label()}: {codec!r} is {bits} bits — a byte address"
                f" has no room for a sub-byte stride; wrap it in a Struct and"
                f" map that"
            )
        return bits // 8

    def _resolve_count(self, addr: int, extent: Extent, stride: int) -> int:
        if isinstance(extent, count):
            return extent.n
        if isinstance(extent, span):
            if extent.end < addr:
                raise ValueError(
                    f"{self._label()}: span end 0x{extent.end:08X} is before"
                    f" the start address 0x{addr:08X}"
                )
            total = extent.end - addr + 1
            if total % stride:
                raise ValueError(
                    f"{self._label()}: span 0x{addr:08X}-0x{extent.end:08X} is"
                    f" {total} bytes, not a whole number of {stride}-byte"
                    f" items — the address, the end, or the record shape is"
                    f" wrong"
                )
            return total // stride
        raise TypeError(f"{self._label()}: unsupported extent {extent!r}")

    def _in_space_endian(self, codec: Array) -> Array:
        """An ``Array`` declared without a byte order, resolved against this
        space's.

        A standalone unset array would otherwise resolve to the historical
        big default and raise the explicit-endian guard, even though the
        space knows the answer — while ``UInt16`` at the same address reads
        fine, because the scalar paths build their array from
        ``self._endian``. An unset array inherits the space's byte order for
        the same reason an unset array FIELD inherits its record's. An
        explicitly declared endian is always honored.
        """
        if codec.declared_endian is not None:
            return codec
        return Array(codec.element, codec.count, self._endian, codec.adapter)

    def _decode(self, addr, codec, n, stride, single):
        off = self.offset(addr)
        if n and off + n * stride > len(self):
            raise AddressError(
                f"{self._label()}: {n} x {stride} bytes at 0x{addr:08X} run"
                f" past the end of the space (0x{self.end - 1:08X})"
            )
        if isinstance(codec, StructMeta):
            records = list(codec.iter_records(self._buf, off, n))
            return records[0] if single else records
        view = memoryview(self._buf)
        if isinstance(codec, Array):
            resolved = self._in_space_endian(codec)
            items = [
                resolved.parse(view[i : i + stride])
                for i in range(off, off + n * stride, stride)
            ]
            return items[0] if single else items
        # Scalar BitType class or fused Adapted: the SPACE supplies the byte
        # order, which also satisfies Array's explicit-endian guard. Built
        # uncached (not Array.of) because n can come from a scan, and the
        # of() cache is unbounded.
        if n == 0:
            return None if single else []
        values = Array(codec, n, self._endian).parse(view[off : off + n * stride])
        return values[0] if single else values

    def _sentinel_wire(self, codec, sentinel, stride: int) -> bytes:
        """The ``stride``-byte wire pattern that ends a table.

        Deliberately the UNADAPTED encoding: a fused THUMB_PTR must not make
        the terminator ``1`` instead of ``0``.
        """
        if isinstance(sentinel, (bytes, bytearray, memoryview)):
            raw = bytes(sentinel)
            if len(raw) != stride:
                raise ValueError(
                    f"{self._label()}: sentinel is {len(raw)} bytes but the"
                    f" item stride is {stride}"
                )
            return raw
        if sentinel == 0:
            return bytes(stride)  # all-zero item: works for any codec
        base = codec.base if isinstance(codec, Adapted) else codec
        if isinstance(base, (StructMeta, Array)):
            raise TypeError(
                f"{self._label()}: a non-zero sentinel for the composite"
                f" codec {codec!r} must be given as {stride} raw bytes"
            )
        return Array(base, 1, self._endian).pack([sentinel])

    def _scan(self, addr, codec, extent: until, stride: int) -> list:
        off = self.offset(addr)
        target = self._sentinel_wire(codec, extent.sentinel, stride)
        view = memoryview(self._buf)
        n = 0
        while n < extent.max_count:
            start = off + n * stride
            if start + stride > len(self):
                raise AddressError(
                    f"{self._label()}: scan from 0x{addr:08X} reached the end"
                    f" of the space after {n} items without finding the"
                    f" sentinel {extent.sentinel!r}"
                )
            if bytes(view[start : start + stride]) == target:
                break
            n += 1
        else:
            raise ValueError(
                f"{self._label()}: scan from 0x{addr:08X} found no sentinel"
                f" {extent.sentinel!r} within max_count={extent.max_count};"
                f" raise the cap if the table really is longer, or the"
                f" address/record shape is wrong"
            )
        if n == 0:
            return []
        return self._decode(addr, codec, n, stride, single=False)

    def _infer_codec(self, value):
        if isinstance(value, Struct):
            return type(value)
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], Struct):
            return type(value[0])
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes  # raw splice; _encode short-circuits on the value
        raise TypeError(
            f"{self._label()}: cannot infer a codec for {value!r}; pass one"
            f" (codec= is optional only for Struct records and raw bytes)"
        )

    def _encode(self, value, codec) -> bytes:
        if isinstance(value, (bytes, bytearray, memoryview)):
            # Bytes go down verbatim, whatever the codec says: an injected
            # blob (hook code, a relocated table) has no shape to encode,
            # and a codec able to encode it would emit these same bytes.
            return bytes(value)
        self._stride(codec)  # reject sub-byte codecs before encoding
        if isinstance(codec, StructMeta):
            if isinstance(value, codec):
                return value.pack()
            if isinstance(value, (list, tuple)):
                bad = [v for v in value if not isinstance(v, codec)]
                if bad:
                    raise TypeError(
                        f"{self._label()}: expected {codec.__name__} records,"
                        f" got {bad[0]!r}"
                    )
                return b"".join(v.pack() for v in value)
            raise TypeError(
                f"{self._label()}: expected a {codec.__name__} record (or a"
                f" list of them), got {value!r}"
            )
        if isinstance(codec, Array):
            resolved = self._in_space_endian(codec)
            if value and isinstance(value[0], (list, tuple)):
                return b"".join(resolved.pack(v) for v in value)
            return resolved.pack(value)
        if isinstance(value, (list, tuple)):
            if not value:
                return b""
            return Array(codec, len(value), self._endian).pack(value)
        return Array(codec, 1, self._endian).pack([value])


# --------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------


class Entry:
    """One mapped thing: an address, a codec, and how far it runs.

    An entry is a *declaration*. It can be built with no space at all, so a
    map module is importable without the binary::

        ROM_MAP = [
            Entry(0x080E1CD0, UInt8, count(4), name="soul_palette"),
            Entry(0x08526390, BossRushReward, count(3), name="boss_rush"),
        ]

        rom = Space(data, base=0x08000000, endian="little")
        for e in rom.bind(ROM_MAP):
            print(e.name, e.read())

    Frozen: rebind with :meth:`bind` rather than mutating.
    """

    __slots__ = ("addr", "codec", "extent", "name", "note", "space")

    addr: int
    codec: Any
    extent: Extent
    name: str
    note: str
    space: Optional[Space]

    def __init__(
        self,
        addr: int,
        codec: Any,
        extent: Union[int, Extent, None] = 1,
        *,
        name: str = "",
        note: str = "",
        space: Optional[Space] = None,
    ):
        extent = _as_extent(extent)
        if not isinstance(addr, int) or addr < 0:
            raise ValueError(f"Entry addr must be a non-negative int, got {addr!r}")
        object.__setattr__(self, "addr", addr)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "extent", extent)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "note", note)
        object.__setattr__(self, "space", space)

    def __setattr__(self, key, value):
        raise AttributeError(
            f"Entry is frozen; use e.bind(space) or build a new Entry"
            f" (tried to set {key!r})"
        )

    def bind(self, space: Space) -> "Entry":
        """A copy of this entry bound to ``space``."""
        return Entry(
            self.addr,
            self.codec,
            self.extent,
            name=self.name,
            note=self.note,
            space=space,
        )

    def _space(self) -> Space:
        if self.space is None:
            raise ValueError(
                f"Entry {self.name or hex(self.addr)} is not bound to a Space;"
                f" call e.bind(space) (or space.bind(entries)) first"
            )
        return self.space

    # -- derived -----------------------------------------------------------
    @property
    def stride(self) -> int:
        """One item's size in bytes."""
        return sizeof(self.codec)

    @property
    def item_count(self) -> Optional[int]:
        """Declared item count, or None when the extent needs the buffer
        (``until``) or is not known at all (``unknown``)."""
        extent = self.extent
        if isinstance(extent, count):
            return extent.n
        if isinstance(extent, span):
            total = extent.end - self.addr + 1
            return total // self.stride if total > 0 else None
        return None

    @property
    def size(self) -> Optional[int]:
        """Total bytes claimed, or None when :attr:`item_count` is unknown."""
        n = self.item_count
        return None if n is None else n * self.stride

    @property
    def byte_span(self):
        """``(first_addr, last_addr)`` inclusive, or None when unknown."""
        size = self.size
        if size is None or size == 0:
            return None
        return (self.addr, self.addr + size - 1)

    # -- access ------------------------------------------------------------
    def read(self, extent: Any = _INHERIT) -> Any:
        """Read this entry. ``extent`` overrides the declared one — the way
        an ``unknown()`` entry is read once its length is known. (Passing
        ``0`` or ``count(0)`` means zero items, not "use the declared one".)
        """
        space = self._space()
        if extent is _INHERIT:
            extent = self.extent
        return space.read(self.addr, self.codec, extent)

    def write(self, value: Any, *, patch: Any = None) -> None:
        """Write ``value`` at this entry's address (see :meth:`Space.write`).

        The encoding must fit what this entry declares: a table of
        ``count(3)`` holds three records, and a blob may not outgrow the
        space reserved for it. Writing *fewer* bytes stays legal, so a
        partial table update writes the rows it has. An entry whose extent
        needs the buffer (``until``) or is unknown declares no size, so
        only the space's own bounds apply.
        """
        space = self._space()
        data = space._encode(value, self.codec)
        limit = self.size
        if limit is not None and len(data) > limit:
            raise ValueError(
                f"Entry {self.name or hex(self.addr)}: {len(data)} bytes do"
                f" not fit the {limit} declared by {self.extent!r}; widen the"
                f" extent or write less"
            )
        space.write(self.addr, data, bytes, patch=patch)

    def describe(self) -> str:
        """One line: name, address range, codec and extent."""
        codec_name = getattr(self.codec, "__name__", None) or repr(self.codec)
        pieces = [f"0x{self.addr:08X}"]
        span_ = self.byte_span
        if span_ is not None:
            pieces.append(f"-0x{span_[1]:08X}")
        head = "".join(pieces)
        label = self.name or "(unnamed)"
        out = f"{label:<28} {head:<22} {codec_name} x {self.extent!r}"
        return f"{out}  # {self.note}" if self.note else out

    def __repr__(self):
        codec_name = getattr(self.codec, "__name__", None) or repr(self.codec)
        bound = "" if self.space is None else ", bound"
        return (
            f"Entry({self.name or hex(self.addr)!r}, 0x{self.addr:08X},"
            f" {codec_name}, {self.extent!r}{bound})"
        )

    def __eq__(self, other):
        if not isinstance(other, Entry):
            return NotImplemented
        return (
            self.addr == other.addr
            and self.codec is other.codec
            and self.extent == other.extent
            and self.name == other.name
            and self.space is other.space
        )

    __hash__ = None  # type: ignore[assignment]  # compared, not keyed


# --------------------------------------------------------------------------
# Patches: edits as a value, not a mutated buffer
# --------------------------------------------------------------------------


class PatchVerifyError(ValueError):
    """A patch was applied to a buffer whose bytes are not what the patch
    recorded as the original. Almost always the wrong ROM build."""


class PatchConflict(ValueError):
    """Two patches being composed disagree about the same byte."""


@dataclass(frozen=True)
class Edit:
    """One contiguous replacement: ``new`` goes where ``old`` was.

    Equal lengths, always — an edit that changed a region's size would shift
    everything after it, which is a different (and much larger) operation
    than patching.
    """

    offset: int
    old: bytes
    new: bytes

    def __post_init__(self):
        if len(self.old) != len(self.new):
            raise ValueError(
                f"Edit at {self.offset}: old is {len(self.old)} bytes and new"
                f" is {len(self.new)} — an edit replaces bytes in place"
            )
        if not self.old:
            raise ValueError(f"Edit at {self.offset} is empty")
        if self.offset < 0:
            raise ValueError(f"Edit offset must be non-negative, got {self.offset}")

    @property
    def size(self) -> int:
        return len(self.old)

    @property
    def end(self) -> int:
        """One past the last byte this edit touches."""
        return self.offset + len(self.old)

    @property
    def is_noop(self) -> bool:
        return self.old == self.new


#: IPS record offsets are 24-bit, and an offset of exactly 0x454F46 encodes
#: as the ASCII bytes "EOF" — the same marker that terminates the file.
IPS_EOF_OFFSET = 0x454F46
IPS_MAX_OFFSET = 0xFFFFFF
IPS_MAX_RECORD = 0xFFFF


class Patch:
    """A set of byte edits, as a value you can verify, invert and compose.

    The alternative — mutating a buffer in place — throws away everything
    you need afterwards: what the bytes used to be, whether you are even
    editing the right build, and how to undo it. A patch keeps all three::

        p = Patch(name="boss rush reward")
        rom.write(0x08526390, rec, patch=p)   # records, does not mutate
        patched = p.apply(rom.buf)            # verifies old bytes first
        assert p.invert().apply(patched) == rom.buf
        open("fix.ips", "wb").write(p.to_ips())

    Internally a patch is a sparse byte map, not a list of edits, which is
    what makes the algebra total: overlapping writes have no ambiguity.

    * :meth:`write` is an imperative edit — **later writes win**, and the
      patch keeps the EARLIEST ``old`` for each byte, so verify and
      :meth:`invert` still refer to the pristine buffer. This is the natural
      read-modify-write flow (tweak a field, then tweak it again).
    * ``a | b`` composes two INDEPENDENT patches and raises
      :class:`PatchConflict` when they disagree about a byte, because with no
      ordering between them a disagreement is a mistake, not an update.

    :attr:`edits` coalesces the byte map back into maximal contiguous runs,
    so the export format and :meth:`summary` see whole edits.
    """

    __slots__ = ("_old", "_new", "name")

    def __init__(self, edits=(), *, name: str = ""):
        self._old: dict = {}
        self._new: dict = {}
        self.name = name
        for e in edits:
            self.write(e.offset, e.old, e.new)

    # -- building ----------------------------------------------------------
    def write(self, offset: int, old: BytesLike, new: BytesLike) -> None:
        """Record that the bytes ``old`` at ``offset`` become ``new``.

        Later writes win per byte; the earliest ``old`` is kept, so the patch
        always describes a transition from the pristine buffer.
        """
        old_b, new_b = bytes(old), bytes(new)
        if len(old_b) != len(new_b):
            raise ValueError(
                f"Patch.write at {offset}: old is {len(old_b)} bytes and new"
                f" is {len(new_b)} — an edit replaces bytes in place"
            )
        if offset < 0:
            raise ValueError(
                f"Patch.write offset must be non-negative, got {offset}"
            )
        for i, (o, n) in enumerate(zip(old_b, new_b)):
            at = offset + i
            self._old.setdefault(at, o)  # earliest original wins
            self._new[at] = n  # latest edit wins

    @property
    def edits(self) -> tuple:
        """The byte map as maximal contiguous :class:`Edit` runs, in offset
        order."""
        runs: List[List[int]] = []  # [first, last] byte offsets, inclusive
        for at in sorted(self._new):
            if runs and at == runs[-1][1] + 1:
                runs[-1][1] = at
            else:
                runs.append([at, at])
        return tuple(self._edit(first, last) for first, last in runs)

    def _edit(self, start: int, last: int) -> Edit:
        rng = range(start, last + 1)
        return Edit(
            start,
            bytes(self._old[i] for i in rng),
            bytes(self._new[i] for i in rng),
        )

    def __len__(self) -> int:
        """The number of coalesced edits."""
        return len(self.edits)

    def __bool__(self) -> bool:
        return bool(self._new)

    @property
    def byte_count(self) -> int:
        """How many bytes the patch claims (no-ops included)."""
        return len(self._new)

    @property
    def changed_byte_count(self) -> int:
        """How many bytes the patch actually changes."""
        return sum(1 for at, n in self._new.items() if self._old[at] != n)

    def touches(self, offset: int) -> bool:
        """True if ``offset`` is claimed by this patch."""
        return offset in self._new

    # -- algebra -----------------------------------------------------------
    def invert(self) -> "Patch":
        """The patch that undoes this one."""
        out = Patch(name=f"undo({self.name})" if self.name else "")
        out._old = dict(self._new)
        out._new = dict(self._old)
        return out

    def __or__(self, other: "Patch") -> "Patch":
        """Compose two independent patches; disagreement is a
        :class:`PatchConflict`."""
        if not isinstance(other, Patch):
            return NotImplemented
        clash = sorted(
            at
            for at, n in other._new.items()
            if at in self._new and self._new[at] != n
        )
        if clash:
            at = clash[0]
            extra = f" ({len(clash)} bytes conflict)" if len(clash) > 1 else ""
            raise PatchConflict(
                f"patches disagree at offset {at} (0x{at:X}):"
                f" {self._new[at]:#04x} vs {other._new[at]:#04x}{extra}"
            )
        names = [n for n in (self.name, other.name) if n]
        out = Patch(name=" | ".join(names))
        out._old = {**other._old, **self._old}  # earliest original wins
        out._new = {**self._new, **other._new}
        return out

    # -- applying ----------------------------------------------------------
    def _check_range(self, at: int, size: int) -> None:
        if at >= size:
            raise PatchVerifyError(
                f"{self._label()}: offset {at} (0x{at:X}) is past the end of a"
                f" {size}-byte buffer"
            )

    def _verify(self, view: memoryview) -> None:
        size = view.nbytes
        for at in sorted(self._new):
            self._check_range(at, size)
            want, got = self._old[at], view[at]
            if got != want:
                raise PatchVerifyError(
                    f"{self._label()}: buffer byte at offset {at} (0x{at:X})"
                    f" is {got:#04x}, but the patch was built against"
                    f" {want:#04x} — wrong build, or already applied"
                )

    def apply(self, buf: BytesLike, *, verify: bool = True) -> bytes:
        """The patched bytes. ``verify`` checks the original bytes first —
        leave it on; it is the whole point."""
        out = bytearray(buf)
        self.apply_into(out, verify=verify)
        return bytes(out)

    def apply_into(self, buf, *, verify: bool = True) -> None:
        """Apply in place to a ``bytearray`` (or writable ``memoryview``)."""
        view = memoryview(buf)
        if view.readonly:
            raise TypeError(
                f"{self._label()}: apply_into needs a writable buffer; use"
                f" apply() to get patched bytes back instead"
            )
        if verify:
            self._verify(view)
        size = view.nbytes
        for at, n in self._new.items():
            self._check_range(at, size)
            view[at] = n

    # -- export ------------------------------------------------------------
    def to_ips(self, buf: Optional[BytesLike] = None) -> bytes:
        """This patch as an IPS file.

        IPS records carry no original bytes, so the export is
        **verification-lossy**: keep the :class:`Patch` (or its edits) as the
        source artifact and treat the ``.ips`` as a distribution format.

        ``buf`` is only needed for one quirk: an IPS record whose 24-bit
        offset is exactly ``0x454F46`` encodes as the ASCII bytes ``EOF``,
        which naive readers treat as end-of-file. Given the buffer, such a
        record is extended one byte backwards (carrying the unchanged byte
        along) so its offset lands elsewhere; without it, this raises.
        A long edit whose *split boundary* lands there needs no buffer: the
        preceding byte is part of that same edit, so the record simply
        starts one byte earlier.
        """
        parts = [b"PATCH"]
        for edit in self.edits:
            offset, data = edit.offset, edit.new
            if offset == IPS_EOF_OFFSET:
                if buf is None:
                    raise ValueError(
                        f"{self._label()}: an IPS record at offset"
                        f" 0x{IPS_EOF_OFFSET:06X} encodes as the ASCII bytes"
                        f" 'EOF' and would truncate the patch for naive"
                        f" readers; pass to_ips(buf=<the original bytes>) so"
                        f" the record can start one byte earlier"
                    )
                offset -= 1
                data = bytes(memoryview(buf)[offset : offset + 1]) + data
            start = 0
            while start < len(data):
                at = offset + start
                if at == IPS_EOF_OFFSET:
                    # A split boundary landed on the quirk offset. Only a
                    # record after the first can (the edit's own offset was
                    # handled above), so the preceding byte belongs to this
                    # same edit: starting one byte earlier re-emits an
                    # identical value and needs no buffer.
                    start -= 1
                    at -= 1
                chunk = data[start : start + IPS_MAX_RECORD]
                if at > IPS_MAX_OFFSET:
                    raise ValueError(
                        f"{self._label()}: IPS offsets are 24-bit; offset"
                        f" 0x{at:X} exceeds 0x{IPS_MAX_OFFSET:06X} (16 MiB)"
                    )
                parts.append(at.to_bytes(3, "big"))
                parts.append(len(chunk).to_bytes(2, "big"))
                parts.append(chunk)
                start += len(chunk)
        parts.append(b"EOF")
        return b"".join(parts)

    def save_ips(self, path, buf: Optional[BytesLike] = None) -> int:
        """Write :meth:`to_ips` to ``path``; returns the byte count."""
        data = self.to_ips(buf)
        with open(path, "wb") as fh:
            fh.write(data)
        return len(data)

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        """A header line plus one line per coalesced edit."""
        edits = self.edits
        if not edits:
            return f"{self._label()}: empty"
        lines = [
            f"{self._label()}: {len(edits)} edit(s),"
            f" {self.changed_byte_count}/{self.byte_count} bytes changed"
        ]
        for e in edits:
            mark = "  (no-op)" if e.is_noop else ""
            lines.append(
                f"  0x{e.offset:06X}+{e.size:<4} {e.old.hex()} ->"
                f" {e.new.hex()}{mark}"
            )
        return "\n".join(lines)

    def _label(self) -> str:
        return f"Patch {self.name!r}" if self.name else "Patch"

    def __repr__(self):
        label = f" {self.name!r}" if self.name else ""
        return f"<Patch{label} {len(self.edits)} edits, {self.byte_count} bytes>"

    def __eq__(self, other):
        if not isinstance(other, Patch):
            return NotImplemented
        return self._old == other._old and self._new == other._new

    __hash__ = None  # type: ignore[assignment]  # mutable, like a bytearray


# --------------------------------------------------------------------------
# Typed pointers
# --------------------------------------------------------------------------


def _identity(value):
    return value


class PtrAdapter(Adapter):
    """The :class:`Adapter` half of a :class:`Ptr`: it carries the pointee's
    codec so a record can be dereferenced without a lookup table.

    Living on the adapter (rather than on the wire type) is what makes this
    work: :class:`Adapted` codecs are split into base + adapter at class
    definition time, so the adapter is the half that survives into
    ``_bm_adapters`` and :func:`~bytemaker.introspect.fields_of`.
    """

    __slots__ = ("_target", "inner", "module")

    #: The target as GIVEN: a codec, a name/callable awaiting resolution, or
    #: None. Read it through :attr:`target`, which resolves and memoizes.
    _target: Any
    inner: Optional[Adapter]
    module: Optional[str]

    def __init__(self, target=None, inner=None, name=None, module=None):
        if inner is not None and not isinstance(inner, Adapter):
            raise TypeError(f"Ptr adapt= must be an Adapter, got {inner!r}")
        if not (target is None or _is_codec(target) or isinstance(target, str)
                or callable(target)):
            raise TypeError(
                f"Ptr target must be a codec (Struct class, BitType class,"
                f" Array, fused adapter@BitType), a name to resolve later, a"
                f" zero-argument callable returning one, or None — got"
                f" {target!r}"
            )
        inner_load = inner.load if inner is not None else _identity
        store = inner.store if inner is not None else _identity
        label = name or _default_ptr_name(target)
        # Every read path — record fields, array elements, Space.read of a
        # bare Ptr — goes through this load, so wrapping HERE is what makes
        # value.deref(space) available everywhere with one seam.
        load = partial(_ptr_value_load, adapter=self, inner_load=inner_load)
        super().__init__(load, store, PtrValue, label)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "inner", inner)
        object.__setattr__(self, "module", module)

    @property
    def target(self):
        """The pointee's codec, resolving a deferred target on first use.

        A string or zero-argument callable is resolved once and memoized, so
        a pointer can name a record that does not exist yet — the shape a
        linked list, a tree node, or any pair of mutually-referencing tables
        forces.
        """
        target = self._target
        if target is None or _is_codec(target):
            return target
        resolved = self._resolve(target)
        if not _is_codec(resolved):
            raise TypeError(
                f"{self.name}: deferred target {target!r} resolved to"
                f" {resolved!r}, which is not a codec"
            )
        object.__setattr__(self, "_target", resolved)  # memoize
        return resolved

    def _resolve(self, target):
        if callable(target) and not isinstance(target, str):
            return target()
        namespace = getattr(sys.modules.get(self.module or ""), "__dict__", {})
        if target in namespace:
            return namespace[target]
        # Cross-module fallback: every concrete Struct registers itself by
        # name, so a map split over several files can say Ptr("RoomHeader")
        # without importing the class into the declaring module. Only an
        # UNAMBIGUOUS match resolves — two live same-named records is a
        # question only the author can answer (module=).
        candidates = _structs_named(target)
        # Prefer classes their own module still binds: filters out stale
        # redefinitions (REPL / reload) without guessing between real
        # duplicates.
        current = tuple(
            c for c in candidates
            if getattr(sys.modules.get(c.__module__ or ""), target, None) is c
        )
        pool = current or candidates
        if len(pool) == 1:
            return pool[0]
        if len(pool) > 1:
            mods = ", ".join(sorted(c.__module__ or "?" for c in pool))
            raise TypeError(
                f"{self.name}: deferred target {target!r} is ambiguous — a"
                f" concrete Struct by that name is alive in each of: {mods}."
                f" Pass Ptr(..., module=...) to pick one"
            )
        raise TypeError(
            f"{self.name}: cannot resolve the deferred target {target!r} —"
            f" not in module {self.module!r}, and no concrete Struct class"
            f" by that name is alive anywhere. Deferred targets resolve"
            f" against the module the Ptr was built in, then against all"
            f" Struct classes by name; pass module= or a callable"
            f" (Ptr(lambda: {target})) to be explicit"
        )

    @property
    def deferred(self) -> bool:
        """True while the target is still an unresolved name/callable."""
        return not (self._target is None or _is_codec(self._target))

    def __reduce__(self):
        # Pickle the RAW target: a deferred one stays deferred (and picklable,
        # since it is just a string) instead of forcing resolution here.
        return (PtrAdapter, (self._target, self.inner, self.name, self.module))


def _ptr_value_load(wire, adapter, inner_load):
    return PtrValue(inner_load(wire), adapter)


class PtrValue(int):
    """A decoded pointer: an ``int`` that knows what it points at.

    Every read through a :class:`Ptr` mints one, so the address a record
    field (or a pointer-table element) hands you can follow itself::

        room = warp.room_ptr.deref(rom)
        while node.next:                     # PtrValue(0) is falsy, like 0
            node = node.next.deref(rom)

    It behaves exactly like the address it is — equality, hashing,
    formatting, truthiness all match ``int`` — with two additions: it reprs
    in hex (this is a ROM library), and it carries the :class:`PtrAdapter`
    that ``deref``/``space.coverage`` consult. Still no proxy and no
    laziness: nothing is read until ``deref`` is called, and the Space stays
    an explicit argument because records are detached from their buffer.

    Arithmetic collapses to a plain ``int`` on purpose: ``ptr + 4`` is an
    offset address, and no longer carries the original claim about what
    lives there.
    """

    _adapter: PtrAdapter

    def __new__(cls, value, adapter):
        if not isinstance(adapter, PtrAdapter):
            raise TypeError(
                f"PtrValue needs the pointer's PtrAdapter, got {adapter!r}"
            )
        self = super().__new__(cls, value)
        self._adapter = adapter
        return self

    @property
    def adapter(self) -> PtrAdapter:
        return self._adapter

    @property
    def target(self):
        """The pointee's codec (resolving a deferred name), or None."""
        return self._adapter.target

    def deref(self, space: "Space", extent: Any = 1) -> Any:
        """Follow this address in ``space`` — sugar for
        ``space.deref_value(self, ...)``, with the target from the schema."""
        return space.deref_value(self, self._adapter, extent)

    def __repr__(self):
        return hex(self)

    def __reduce__(self):
        return (PtrValue, (int(self), self._adapter))


class Ptr(Adapted):
    """A typed address: a wire integer that points at ``target``.

    The decoded value is a :class:`PtrValue` — an ``int`` subclass that
    carries its adapter, so it can follow itself. Still no proxy and not a
    lazy record: nothing is read until you ask, and the Space stays an
    explicit argument::

        class WarpPoint(Struct, endian="little"):
            sector: UInt8
            room_ptr: Annotated[int, Ptr(RoomHeader)]

        w = rom.read(0x08525FBC, WarpPoint)
        w.room_ptr                         # 0x08520B08 -- just an int
        rom.deref(w, "room_ptr")           # the RoomHeader it points at

    A pointer is an :class:`~bytemaker.adapters.Adapted` codec, so it works
    everywhere a scalar wire type does (annotation, ``field()``, array
    element, ``space.read``) with no extra plumbing.

    ``adapt=`` composes a value convention on top — ``Ptr(Anim,
    adapt=THUMB_PTR)`` is a function pointer whose bit 0 selects the THUMB
    instruction set, so the decoded address is the real (even) one.

    ``Ptr(None)`` means "this is an address, but the pointee is not modelled
    yet": :meth:`Space.coverage` still audits it, and :meth:`Space.deref`
    refuses it by name.

    **Deferred targets.** Pass the class itself whenever it is bound at the
    declaration — that is the normal form: a typo fails at import time, the
    IDE can follow it, and nothing resolves at runtime. A *string* (or a
    zero-argument callable) exists for the declarations evaluation order
    forbids — a self-referential node, mutually-referencing records, a
    cross-module cycle — and is resolved on first deref::

        NextNode = Annotated[int, Ptr("Node")]   # resolved later, by name

        class Node(Struct, endian="little"):
            value: u16
            _pad:  u16
            next:  NextNode                      # points at its own type

        n = rom.read(addr, Node)
        while n.next:
            n = rom.deref(n, "next")             # walk the list

    A bare forward name cannot work — ``Ptr(Node)`` inside ``Node``'s own body
    is evaluated before the class exists, even under
    ``from __future__ import annotations``, because the metaclass resolves
    hints during class creation. The string defers past that point.

    Resolution looks in two places, in order: the module the ``Ptr`` was
    built in, then — if the name is not bound there — the set of all live
    concrete Struct classes, when exactly ONE bears that name. So a map
    split across several files can say ``Ptr("RoomHeader")`` without
    importing the class into the declaring module; two live records with
    the same name refuse with the modules listed. Use ``module=__name__``
    (or a callable) to be explicit when it matters.
    """

    __slots__ = ()

    def __init__(self, target=None, *, base=None, adapt=None, name=None,
                 module=None):
        if base is None:
            from bytemaker.bittypes import UInt32

            base = UInt32
        if module is None and isinstance(target, str):
            # A deferred name resolves against the module this Ptr was built
            # in, which is the one the reader expects it to mean. Captured
            # here (not at resolution time) because by then the frame is gone.
            frame = sys._getframe(1)
            module = frame.f_globals.get("__name__")
        super().__init__(base, PtrAdapter(target, adapt, name, module))

    @property
    def _ptr_adapter(self) -> PtrAdapter:
        """The adapter, narrowed. Every Ptr constructor installs a PtrAdapter
        (``__init__`` and ``_rebuild_ptr`` are the only two), so this states
        an invariant for the checker rather than hiding a doubt."""
        return cast(PtrAdapter, self.adapter)

    @property
    def target(self):
        """The codec this address points at, or None when unmodelled.

        Resolves a deferred target (a name or callable) on first access.
        """
        return self._ptr_adapter.target

    @property
    def deferred(self) -> bool:
        """True while the target is still an unresolved name/callable."""
        return self._ptr_adapter.deferred

    def __repr__(self):
        # The RAW target throughout: a repr must never trigger resolution, nor
        # fail because a deferred name is not importable yet.
        raw = self._ptr_adapter._target
        head = f"Ptr({_codec_name(raw)}->{self.base.__name__}"
        # Show a composed value convention: two pointer tables that differ
        # only in whether bit 0 is an instruction-set selector must not read
        # identically in a map listing.
        if (
            self.adapter.inner is not None
            or self.adapter.name != _default_ptr_name(raw)
        ):
            head += f", {self.adapter.name}"
        return head + ")"

    def __reduce__(self):
        return (_rebuild_ptr, (self.base, self.adapter))


def _rebuild_ptr(base, adapter) -> Ptr:
    """Unpickle a Ptr without re-running __init__ (which would rebuild the
    adapter and lose its identity)."""
    ptr = object.__new__(Ptr)
    object.__setattr__(ptr, "base", base)
    object.__setattr__(ptr, "adapter", adapter)
    return ptr


def _is_codec(obj) -> bool:
    """True for anything that can decode bytes at an address. The duck test
    (``num_bits``) is the same one :mod:`bytemaker.introspect` uses, and it
    is what distinguishes a real codec from a deferred name or callable."""
    return isinstance(getattr(obj, "num_bits", None), int)


def _default_ptr_name(target) -> str:
    return f"ptr({_codec_name(target)})"


def _codec_name(codec) -> str:
    if codec is None:
        return "?"
    if isinstance(codec, str):
        return codec  # a deferred target names itself
    return getattr(codec, "__name__", None) or repr(codec)


def _checkable_target(adapter) -> Optional[StructMeta]:
    """The adapter's declared record type, when there is one to check: a
    PtrAdapter whose target is (or resolves to) a concrete Struct class.
    Resolution failure is NOT an audit failure — an unresolvable name just
    means unverifiable, and the address classification stands on its own."""
    if not isinstance(adapter, PtrAdapter):
        return None
    try:
        target = adapter.target
    except TypeError:
        return None
    return target if isinstance(target, StructMeta) else None


def _ptr_adapter_of(obj) -> Optional[PtrAdapter]:
    """The :class:`PtrAdapter` behind a Ptr codec, an adapter, or an Array of
    pointers — else None."""
    if isinstance(obj, PtrAdapter):
        return obj
    if isinstance(obj, Adapted):
        return obj.adapter if isinstance(obj.adapter, PtrAdapter) else None
    if isinstance(obj, Array):
        return obj._adapter if isinstance(obj._adapter, PtrAdapter) else None
    return None


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    """One entry's resolved footprint in a coverage report."""

    entry: "Entry"
    size: Optional[int]
    error: Optional[str] = None

    @property
    def name(self) -> str:
        return self.entry.name or f"0x{self.entry.addr:08X}"

    @property
    def start(self) -> int:
        return self.entry.addr

    @property
    def end(self) -> Optional[int]:
        """One past the last claimed address, or None when unresolved."""
        return None if self.size is None else self.entry.addr + self.size

    @property
    def resolved(self) -> bool:
        return self.size is not None


@dataclass(frozen=True)
class Overlap:
    """Two entries claiming the same bytes — usually a wrong count."""

    a: str
    b: str
    start: int
    size: int


@dataclass(frozen=True)
class Gap:
    """A run of bytes no resolved entry claims.

    The complement of a coverage report, and the question a mapping session
    actually runs on: not "how much have I got" but "what is left, and where
    is the big one".
    """

    start: int
    size: int

    @property
    def end(self) -> int:
        """One past the last unclaimed address."""
        return self.start + self.size

    def describe(self) -> str:
        return f"0x{self.start:08X}-0x{self.end - 1:08X} ({self.size} bytes)"


def _enumerate_values(value):
    """``(index, one)`` pairs for a scalar, a list, or None: normalizes the
    three shapes a Ptr-carrying read can produce."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(enumerate(value))
    return ((None, value),)


def _overlaps(regions) -> tuple:
    """Pairs of resolved regions that claim the same bytes.

    Sweeps in start order, so an entry overlapping three others reports
    three pairs rather than one vague complaint.
    """
    live = sorted(
        (r for r in regions if r.resolved and r.size),
        key=lambda r: (r.start, r.end),
    )
    out = []
    for i, a in enumerate(live):
        for b in live[i + 1 :]:
            if b.start >= a.end:
                break  # sorted by start: nothing later can overlap a either
            shared = min(a.end, b.end) - b.start
            if shared > 0:
                out.append(Overlap(a.name, b.name, b.start, shared))
    return tuple(out)


@dataclass(frozen=True)
class PointerRef:
    """One decoded pointer, classified against the map."""

    source: str  #: the entry's name
    field: Optional[str]  #: record field, or None for a bare pointer table
    #: Position: None for a lone pointer, an int for a flat table, and
    #: ``(record, element)`` for a pointer array field inside a record.
    index: Any
    value: int
    #: "claimed" | "unclaimed" | "outside" | "null" — plus, when the pointer
    #: declares a record target, the two verified-defect verdicts
    #: "mistargeted" (lands in a region mapped as a different record type)
    #: and "misaligned" (right type, off a record boundary).
    verdict: str
    claimed_by: Optional[str] = None

    @property
    def is_dangling(self) -> bool:
        """Points outside the space entirely — the one that is always a bug
        (or a pointer into RAM, which a ROM map should say so about)."""
        return self.verdict == "outside"

    def describe(self) -> str:
        where = self.source
        if self.field:
            where += f".{self.field}"
        if isinstance(self.index, tuple):
            where += "".join(f"[{i}]" for i in self.index)
        elif self.index is not None:
            where += f"[{self.index}]"
        tail = f" -> {self.claimed_by}" if self.claimed_by else ""
        return f"{where} = 0x{self.value:08X}  {self.verdict}{tail}"


@dataclass(frozen=True)
class CoverageReport:
    """What a map accounts for, what it leaves unaccounted for, what it
    double-claims, and where its pointers land.

    :attr:`claimed_bytes` and :meth:`gaps` are the two halves of one
    partition of the space; :attr:`overlaps` and :attr:`pointers` report the
    two ways a map can be wrong about bytes it does claim.
    """

    space_name: str
    space_size: int
    space_base: int
    regions: tuple
    overlaps: tuple
    pointers: tuple

    @cached_property
    def _merged_spans(self) -> "Tuple[tuple, ...]":
        """Resolved footprints merged into maximal disjoint ``(start, end)``
        runs, in address order, clipped to the space.

        What the map claims and what it does not are both read off this one
        list, which is what makes them two views of a single partition:
        ``claimed_bytes + unclaimed_bytes == space_size``, always. The
        clipping only bites for a report assembled by hand —
        :meth:`Space.coverage` never resolves a region outside its own
        bounds — but without it a stray region would inflate the claim and
        stretch a gap past the end of the space it describes.

        Cached: the report is frozen and one ``render()`` reads this several
        times over what can be thousands of regions.
        """
        low = self.space_base
        high = low + self.space_size
        merged: "List[List[int]]" = []
        for start, end in sorted(
            (max(low, r.start), min(high, r.end))
            for r in self.regions
            if r.resolved and r.size
        ):
            if end <= start:
                continue  # lies entirely outside the space
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return tuple((start, end) for start, end in merged)

    @property
    def claimed_bytes(self) -> int:
        """Distinct bytes claimed by at least one resolved entry (overlaps
        counted once)."""
        return sum(end - start for start, end in self._merged_spans)

    def gaps(self, min_size: int = 1) -> tuple:
        """Runs of at least ``min_size`` bytes that no resolved entry
        claims, as :class:`Gap` values in address order.

        The complement of :attr:`claimed_bytes`, and the direction a map
        actually grows in: percentages say how far along you are, gaps say
        where to look next — especially paired with the ``unclaimed``
        pointer verdicts, which name addresses something already points at.

        An UNRESOLVED region claims nothing, so its bytes read as gap. That
        is deliberate (the entry may be right about the address and wrong
        about the length, and a report must not credit a length it could not
        resolve); :attr:`unresolved` names those entries and why.
        """
        gaps = []
        cursor = self.space_base
        limit = self.space_base + self.space_size
        for start, end in self._merged_spans:
            if start > cursor:
                gaps.append(Gap(cursor, start - cursor))
            cursor = max(cursor, end)
        if cursor < limit:
            gaps.append(Gap(cursor, limit - cursor))
        return tuple(g for g in gaps if g.size >= min_size)

    @property
    def unclaimed_bytes(self) -> int:
        """``space_size - claimed_bytes``, which is also the total bytes in
        :meth:`gaps` — the two agree because both sides are read off
        :attr:`_merged_spans`, whose spans are clipped to the space. The
        equality is pinned by a test against the gap sum, so this can stay
        the cheap arithmetic form (the sum allocates a Gap per run just to
        add its sizes)."""
        return self.space_size - self.claimed_bytes

    @property
    def percent(self) -> float:
        if not self.space_size:
            return 0.0
        return 100.0 * self.claimed_bytes / self.space_size

    @property
    def unresolved(self) -> tuple:
        return tuple(r for r in self.regions if not r.resolved)

    @property
    def dangling(self) -> tuple:
        return tuple(p for p in self.pointers if p.is_dangling)

    def render(self, max_pointers: int = 20, max_gaps: int = 10) -> str:
        """A text report. Truncates the pointer and gap listings, and says by
        how much — a silent cap would read as "all clear"."""
        label = self.space_name or "space"
        lines = [
            f"coverage of {label}: {self.claimed_bytes}/{self.space_size} bytes"
            f" ({self.percent:.2f}%) in {len(self.regions)} entries"
        ]
        if self.unresolved:
            lines.append(f"  unresolved ({len(self.unresolved)}):")
            for r in self.unresolved:
                lines.append(f"    {r.name}: {r.error}")
        if self.overlaps:
            lines.append(f"  overlaps ({len(self.overlaps)}):")
            for o in self.overlaps:
                lines.append(
                    f"    {o.a} and {o.b} share {o.size} bytes at"
                    f" 0x{o.start:08X}"
                )
        gaps = self.gaps()
        if gaps:
            # Listed LARGEST first, unlike gaps() itself: on a real map the
            # first gaps by address are the least interesting (a ROM starts
            # with code), and the question being asked is where the big
            # unmapped region is.
            lines.append(
                f"  gaps ({len(gaps)}): {self.unclaimed_bytes} bytes"
                f" unclaimed, largest first"
            )
            by_size = sorted(gaps, key=lambda g: (-g.size, g.start))
            for g in by_size[:max_gaps]:
                lines.append(f"    {g.describe()}")
            if len(by_size) > max_gaps:
                lines.append(
                    f"    ... and {len(by_size) - max_gaps} more gaps"
                    f" (raise max_gaps to see them)"
                )
        if self.pointers:
            counts: dict = {}
            for p in self.pointers:
                counts[p.verdict] = counts.get(p.verdict, 0) + 1
            tally = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
            lines.append(f"  pointers ({len(self.pointers)}): {tally}")
            interesting = [p for p in self.pointers if p.verdict != "claimed"]
            for p in interesting[:max_pointers]:
                lines.append(f"    {p.describe()}")
            if len(interesting) > max_pointers:
                lines.append(
                    f"    ... and {len(interesting) - max_pointers} more"
                    f" non-claimed pointers (raise max_pointers to see them)"
                )
        return "\n".join(lines)
