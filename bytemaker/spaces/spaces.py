"""The address space itself: :class:`Space`, extents, :class:`Entry`.

:class:`Space` maps a buffer at a base address and supplies the byte order
that scalar reads and writes use. The extents ``count``, ``until``, ``span``
and ``unknown`` say how far a table runs. An :class:`Entry` declares one
mapped thing, and it can be written with no buffer in hand.

See :mod:`bytemaker.spaces` for the layer's overview.
"""

from typing import cast

from bytemaker.adapters import Adapted
from bytemaker.introspect import bitsizeof, fields_of, sizeof
from bytemaker.structs import (
    Array,
    BytesLike,
    Struct,
    StructMeta,
    _field_name_of,
)
from bytemaker.typing_redirect import (
    Any,
    Literal,
    Optional,
    Tuple,
    Union,
)
from bytemaker.utils import unwrap_alias, validate_endianness

from .coverage import (
    CoverageReport,
    PointerRef,
    Region,
    _enumerate_values,
    _overlaps,
)
from .patches import PatchVerifyError, _changed_runs
from .pointers import _checkable_target, _codec_name, _ptr_adapter_of


class AddressError(ValueError):
    """An address or a span falls outside the space it addresses.

    This is a distinct class so that a pointer audit can catch
    out-of-range addresses on their own. The audit expects some of the
    addresses it checks to be out of range, and catching plain
    ``ValueError`` would also catch every decode failure.
    """


# --------------------------------------------------------------------------
# Extents: how far a table runs
# --------------------------------------------------------------------------


class Extent:
    """Base class of the four table-length declarations.

    The subclasses are named in lower case because they are used as values
    at a declaration site, as in ``count(4)`` or ``until(0)``.
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
    """Items up to the first one equal to ``sentinel``, which is excluded.

    The sentinel is matched on the **wire**, before any adapter runs,
    because an adapter must never change what terminates a table.

    ``max_count`` caps the scan. A table with no terminator inside it
    raises rather than reading on to the end of the space.
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
    """Items from the entry's address through ``end``.

    The end address is **inclusive**, because that is the form a disassembly
    listing gives you. The item width must divide the region exactly, so a
    remainder means the address, the end, or the record shape is wrong.
    """

    __slots__ = ("end",)

    def __init__(self, end: int):
        if not isinstance(end, int):
            raise ValueError(f"span(end) needs an int address, got {end!r}")
        self.end = end

    def __repr__(self):
        # The end is always an address, and an address in decimal is
        # unreadable. count's n is a quantity, so it stays decimal.
        return f"span(end=0x{self.end:08X})"


class unknown(Extent):
    """The length is not known, so reads refuse.

    The entry still documents the address and the record shape. A coverage
    report lists it as unresolved and counts it as claiming no bytes,
    giving ``note`` as the reason.
    """

    __slots__ = ("note",)

    def __init__(self, note: str = ""):
        self.note = note


class _Inherit:
    """Marks "no extent passed", distinct from ``0`` or ``count(0)``.

    Both ``0`` and ``count(0)`` are legitimate extents, and a falsiness
    test would read them as absent. This is a named class rather than a
    bare sentinel so that its repr is readable in a signature.
    """

    __slots__ = ()

    def __repr__(self):
        return "<the declared extent>"


_INHERIT = _Inherit()


def _as_extent(extent) -> Extent:
    """Normalize an extent argument.

    ``4`` becomes ``count(4)``, ``None`` becomes ``count(1)``, and an
    :class:`Extent` is already one.
    """
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

    The space turns addresses into buffer offsets, and it supplies the byte
    order that scalar reads and writes use.

    Args:
        buf: the bytes. In-place :meth:`write` needs a ``bytearray`` or a
            writable ``memoryview``. Read-only ``bytes`` is enough for
            reading and for patch-recording writes. Pass ``None`` together
            with ``size=`` to build a **geometry-only** space (see below).
        size: how many bytes the space spans. It is required when ``buf``
            is ``None`` and rejected otherwise, because a buffer already
            knows its own length.
        base: the address the first byte lives at. GBA ROM is mapped at
            ``0x08000000``, and a plain file at 0.
        endian: byte order for SCALAR reads and writes. It is required,
            because guessing the byte order is the single most expensive
            mistake in this layer. Struct and Array codecs carry their own.
        name: shown in error messages and coverage reports.

    A **geometry-only** space is the same address plane with no bytes
    behind it::

        gba = Space(None, size=0x800000, base=0x08000000, endian="little")

    Address math, entries, declaration-level :meth:`coverage` and
    patch-recording writes all work on such a space. Anything that would
    read bytes refuses and says why.

    Two situations call for it, and neither has an image to hand. The first
    is building writes *before* the target file exists. The second is
    describing a live machine's memory, where the bytes arrive from a
    transport one fetch at a time.
    """

    __slots__ = ("_buf", "_size", "_base", "_endian", "_name", "_record")

    def __init__(
        self,
        buf: Optional[BytesLike],
        *,
        size: Optional[int] = None,
        base: int = 0,
        endian: Literal["big", "little"],
        name: str = "",
    ):
        if buf is None:
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ValueError(
                    "Space(None, ...) is geometry only and needs size= (how"
                    " many bytes the address plane spans); pass the bytes"
                    " instead if you have them"
                )
        else:
            if not isinstance(buf, (bytes, bytearray, memoryview)):
                raise TypeError(
                    f"Space buf must be bytes-like or None, got"
                    f" {type(buf).__name__}"
                )
            if size is not None:
                raise ValueError(
                    "Space size= describes a geometry-only space; a buffer"
                    " already knows its own length"
                )
        self._buf = buf
        self._size = size
        if not isinstance(base, int) or base < 0:
            raise ValueError(f"Space base must be a non-negative int, got {base!r}")
        self._base = base
        self._endian = validate_endianness(endian, name="Space endian")
        self._name = name
        self._record = None  # set only by recording(); see its docstring

    # -- identity ----------------------------------------------------------
    @property
    def buf(self) -> Optional[BytesLike]:
        """The bytes, or None for a geometry-only space."""
        return self._buf

    @property
    def backed(self) -> bool:
        """True when this space has bytes behind it."""
        return self._buf is not None

    def _as_endian(self, endian: Optional[str]) -> "Space":
        """Return this space, or a view of the same bytes in another order.

        A record can declare a byte order for one field, such as
        ``field(UInt16, endian="big")`` inside a little-endian image. A
        scalar read takes its byte order from the space, so reading that
        field needs a space whose byte order matches the field.
        """
        if endian is None or endian == self._endian:
            return self
        out = Space(
            self._buf,
            size=self._size,
            base=self._base,
            endian=cast('Literal["big", "little"]', endian),
            name=self._name,
        )
        out._record = self._record  # a field write must still be recorded
        return out

    def recording(self, patch: Any) -> "Space":
        """Return a view whose writes land in the buffer and are recorded.

        Each write through the returned space mutates the buffer and
        records an edit on ``patch``.

        The two other write modes each give up something a build pipeline
        needs. A plain write mutates the buffer and records nothing. A
        ``patch=`` write records the edit but leaves the buffer alone, so a
        later step cannot read what an earlier one did.

        Rebuilding the record afterwards with :meth:`Patch.diff` is the
        weaker alternative. It costs a scan of the whole image, and it
        *drops every byte written back to the value it already held*. For a
        table relocated into zero-filled free space, that can be most of
        the table. The resulting patch then applies cleanly to an image
        that differs exactly there, and it silently produces the wrong
        bytes.

        A write through a recording space claims **the whole span
        written**, not just the bytes that changed. The changed-bytes-only
        rule exists for ``patch=`` writes because those leave the buffer
        alone: a later whole-record write would otherwise stamp an earlier
        edit back to the value it read (see :meth:`write`). A recording
        write updates the buffer and later reads see it, so that reason
        does not apply and full fidelity is worth more::

            work = Space(bytearray(rom), base=0x08000000, endian="little")
            p = Patch(name="all features")
            rec = work.recording(p)
            for feature in features:
                feature(rec)          # reads see what earlier features did
            assert p.apply(rom) == work.buf   # and p is pristine-relative

        The patch remains a transition from the *pristine* image even
        though each write records the intermediate bytes it replaced,
        because :meth:`Patch.write` keeps the earliest known original for
        each byte.
        """
        if self._buf is None:
            raise ValueError(
                f"{self._label()}: a geometry-only space has nothing to"
                f" mutate, so there is no recording to do alongside it;"
                f" pass patch= to Space.write to collect blind edits"
            )
        if patch is None:
            raise ValueError(f"{self._label()}: recording() needs a Patch")
        out = Space(
            self._buf,
            base=self._base,
            endian=self._endian,
            name=self._name,
        )
        out._record = patch
        return out

    def _bytes(self, what: str) -> BytesLike:
        """Return the buffer, or raise naming the operation that needed it."""
        if self._buf is None:
            raise ValueError(
                f"{self._label()}: {what} needs bytes, but this space is"
                f" geometry only (built with size=, no buffer). Build a Space"
                f" over the bytes once you have them — for a live target,"
                f" fetch the bytes yourself and decode them."
            )
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
        if buf is None:
            return cast(int, self._size)
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
        """Return the buffer offset of ``addr``, or raise :class:`AddressError`."""
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
        """Return the address at ``offset``, the inverse of :meth:`offset`."""
        if not isinstance(offset, int) or offset < 0 or offset > len(self):
            raise AddressError(
                f"{self._label()}: offset {offset!r} is outside the space"
                f" (0..{len(self)})"
            )
        return self._base + offset

    def contains(self, addr: int) -> bool:
        """True when ``addr`` is mapped.

        This is the non-raising counterpart to :meth:`offset`, and it is
        what classifies a pointer as inside or outside the space.
        """
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

        ``extent`` is an :class:`Extent` or a plain item count, and the two
        are interchangeable, so ``4`` means ``count(4)``.

        The return shape follows the *declaration*, never the data. The
        default ``count(1)`` returns ONE decoded item. Every other extent
        returns a list, including a ``span`` or ``until`` that happens to
        resolve to a single item.
        """
        codec = unwrap_alias(codec)
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

    def slice(self, addr: int, nbytes: int) -> memoryview:
        """Return a ``memoryview`` of ``nbytes`` at ``addr``, without copying.

        The address and the length are both bounds-checked.
        """
        off = self.offset(addr)
        if nbytes < 0 or off + nbytes > len(self):
            raise AddressError(
                f"{self._label()}: {nbytes} bytes at 0x{addr:08X} run past the"
                f" end of the space (0x{self.end - 1:08X})"
            )
        return memoryview(self._bytes("slice()"))[off : off + nbytes]

    # -- writing -----------------------------------------------------------
    def write(
        self,
        addr: int,
        value: Any,
        codec: Any = None,
        *,
        patch: Any = None,
        expect: Any = None,
    ) -> None:
        """Encode ``value`` at ``addr``.

        ``codec`` may be omitted for a Struct instance, or for a non-empty
        list of them, because the record's own class is the codec. It may
        also be omitted for raw bytes, which go down verbatim.

        ``expect`` is what the target must currently hold. State it as a
        *value* in the same codec rather than as bytes, so
        ``write(addr, 5, expect=32)`` says "this was 32, make it 5".
        Against bytes in hand the guard is checked immediately. Against a
        patch it becomes the edit's recorded original, so applying the
        patch checks it later. Either way the write refuses to land
        somewhere it does not recognise, which is what catches a wrong
        build or a moved table.

        A recorded ``expect`` claims the **full stated span**, and it is
        exempt from the changed-bytes-only rule below. The guard the caller
        states is the guard the caller gets: ``guards()`` covers the whole
        value, and writing the expected value back still records a
        verifying no-op edit rather than nothing.

        A value too large for its codec **wraps**, silently, because that
        is what C does. Converting to an unsigned type is defined as
        reduction modulo its width, so ``uint8_t x = 256`` is 0 and
        ``write(addr, 256, UInt8)`` writes a zero byte. C still warns while
        doing it, and so can this. Set ``NarrowingConfig.warn = True``, or
        the ``BYTEMAKER_WARN_NARROWING`` environment variable, to turn
        every value-changing store into a
        :class:`~bytemaker.NarrowingWarning` naming what became what. It is
        off by default for the same reason ``-Wconversion`` is not on by
        default.

        That knob reports a *type* overflowing its width. It says nothing
        about a limit the target imposes, such as an opcode whose immediate
        field only encodes 0..255, or a table whose consumer rejects an
        index past its length. No codec knows those limits, so state them
        where you do know them, the way ``expect=`` states what the bytes
        must already be.

        With ``patch=`` nothing is mutated. The old bytes are read and an
        edit is recorded on the patch, so the same call works on a
        read-only ``bytes`` buffer. Without ``patch=`` the buffer must be
        writable.

        When there are bytes to compare against, a ``patch=`` write claims
        only what it actually *changes*: writing a whole record to tweak
        one field claims that field, not the record. That is what lets two
        patches touching different fields of one record compose under
        ``|``. The buffer is untouched by definition, so reads never see
        pending edits. That is exactly why only the changed bytes are
        claimed: a later whole-record write can then no longer stamp an
        earlier edit back to the value it read. A flow whose later steps
        must see what the earlier ones wrote should write through
        :meth:`recording` instead, which updates the buffer and records the
        whole span of every write.
        """
        codec = unwrap_alias(codec) if codec is not None else self._infer_codec(value)
        data = self._encode(value, codec)
        off = self.offset(addr)
        if off + len(data) > len(self):
            raise AddressError(
                f"{self._label()}: {len(data)} bytes at 0x{addr:08X} run past"
                f" the end of the space (0x{self.end - 1:08X})"
            )
        expected = self._expected_bytes(expect, codec, len(data), addr)
        if self._buf is None:
            if patch is None:
                raise ValueError(
                    f"{self._label()}: nothing to mutate — this space is"
                    f" geometry only, so a write has to be recorded; pass"
                    f" patch= to collect the edit"
                )
            if expected is None:
                patch.write(off, data)
            else:
                # The caller stated a guard, so the guard they stated is
                # the edit: the FULL span, old=expected, with no
                # changed-bytes trimming. Trimming would shrink a
                # compare-and-swap to the bytes that differ. When
                # new == expected it would record nothing, silently turning
                # "verify it is still X and write X" into no check at all.
                patch.write(off, data, expected)
            return
        if expected is not None:
            self._check_expectation(off, expected, addr)
        if self._record is not None:
            if patch is not None:
                raise ValueError(
                    f"{self._label()}: this space already records into"
                    f" {self._record!r}; drop patch= here, or write through"
                    f" the plain space to record somewhere else"
                )
            old = bytes(memoryview(self._buf)[off : off + len(data)])
            self._buf[off : off + len(data)] = data  # type: ignore[index]
            # The whole span, deliberately: see recording().
            self._record.write(off, data, old)
            return
        if patch is not None:
            if expected is not None:
                # Same rule as the unbacked branch. An explicit guard is
                # recorded whole, and expected == current here because it
                # was just verified. Apply-time verify and guards() then
                # re-check what the caller actually stated, rather than a
                # trimmed remnant of it.
                patch.write(off, data, expected)
                return
            old = bytes(memoryview(self._buf)[off : off + len(data)])
            for i, was, now in _changed_runs(old, data):
                patch.write(off + i, now, was)
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
        reserve: Optional[int] = None,
    ) -> "Entry":
        """An :class:`Entry` at ``addr`` already bound to this space."""
        return Entry(
            addr,
            codec,
            extent,
            name=name,
            note=note,
            space=self,
            reserve=reserve,
        )

    # -- pointers ----------------------------------------------------------
    def deref(
        self,
        record: Any,
        field: Any,
        extent: Union[int, "Extent", None] = 1,
    ) -> Any:
        """Follow a :class:`Ptr` field of ``record``.

        ``field`` is the field's name as a string, or the CLASS attribute
        itself. ``rom.deref(warp, WarpPoint.room_ptr)`` works because
        class-level access returns the field descriptor, which carries the
        field's name, and passing the attribute survives a rename.

        The field must have been declared with a ``Ptr``, so the pointee's
        codec comes from the schema rather than from the call site. An
        adapted array of pointers is dereferenced element-wise and returns
        a list.

        For a pointer that has already been read, ``value.deref(space)`` on
        the :class:`PtrValue` itself is the shortest spelling.
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
        """Follow one address through ``ptr``.

        ``ptr`` is a :class:`Ptr` codec or its adapter. This is the form for
        elements of a pointer list.
        """
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
        """Report what a map accounts for, as a :class:`CoverageReport`.

        The report gives each entry's footprint, the regions two entries
        both claim, and where every declared pointer lands.

        ``until`` extents are resolved by scanning, and the terminator
        counts as claimed. ``unknown`` extents and entries that fail to
        read are reported unresolved with the reason, rather than silently
        skipped.

        The pointer audit covers two things: an entry whose codec is a
        ``Ptr``, alone or as an array element, and the top-level ``Ptr``
        fields of a Struct codec. Pointers inside a nested Struct are not
        followed, so map the inner record as its own entry when you need
        them.

        The audit also verifies a pointer that declares a record target AND
        lands in a region mapped as records. A hit in a region of a
        different record type reports ``mistargeted``. A hit off the record
        stride reports ``misaligned``. A deferred target that cannot be
        resolved verifies nothing and never fails the audit.
        """
        bound = [e if e.space is not None else e.bind(self) for e in entries]
        regions = tuple(self._resolve_region(e) for e in bound)
        overlaps = _overlaps(regions)
        # Following a pointer means reading the address it holds, so a
        # geometry-only space cannot audit pointers. It still resolves the
        # declarations, and pointers_audited reports how far it got.
        audited = audit_pointers and self._buf is not None
        pointers: list = []
        if audited:
            for region in regions:
                pointers.extend(self._audit_pointers(region, regions))
        return CoverageReport(
            space_name=self._name,
            space_size=len(self),
            space_base=self._base,
            regions=regions,
            overlaps=overlaps,
            pointers=tuple(pointers),
            pointers_audited=audited,
        )

    def _resolve_region(self, entry: "Entry"):
        # Capacity, not size. A reservation claims its whole extent even
        # when what currently lives there is shorter or not yet known.
        declared = entry.capacity
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
        """Classify an address that landed inside ``region``.

        The verdict is ``claimed`` unless the pointer DECLARES a record
        type that the claiming region disagrees with.

        That check only runs when the region's entry codec is a Struct
        class and the pointer's target is a Struct class, or resolves to
        one. A raw-byte or scalar region can legitimately contain records
        the map has not modelled at that granularity, and ``Ptr(None)`` or
        an unresolvable name declares nothing to check.

        Two defect verdicts can come out of the check. ``mistargeted``
        means the address lands in a region mapped as a DIFFERENT record
        type. ``misaligned`` means the record type is right but the address
        is not on a record boundary, which is usually an off-by-one in the
        region's address or an interior pointer worth knowing about.
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
        """Return one item's size in bytes, refusing sub-byte codecs."""
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
        """Fill in this space's byte order on an ``Array`` that has none.

        An array that declares its own byte order is returned unchanged,
        because an explicitly declared endian is always honored. An unset
        array inherits the space's byte order for the same reason an unset
        array FIELD inherits its record's.

        Without this step a standalone unset array would resolve to the
        historical big default and raise the explicit-endian guard, even
        though the space knows the answer. ``UInt16`` at the same address
        reads fine, because the scalar paths build their array from
        ``self._endian``.
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
        return self._decode_from(
            self._bytes("read()"), off, codec, n, stride, single
        )

    def _decode_from(self, data, off, codec, n, stride, single):
        """Decode from bytes already in hand.

        This space supplies only the byte order, so a caller that fetched
        the bytes itself can still decode them through the same declaration.
        """
        if isinstance(codec, StructMeta):
            records = list(codec.iter_records(data, off, n))
            return records[0] if single else records
        view = memoryview(data)
        if isinstance(codec, Array):
            resolved = self._in_space_endian(codec)
            items = [
                resolved.parse(view[i : i + stride])
                for i in range(off, off + n * stride, stride)
            ]
            return items[0] if single else items
        # Scalar BitType class or fused Adapted. The SPACE supplies the
        # byte order, which also satisfies Array's explicit-endian guard.
        # The Array is built uncached rather than through Array.of, because
        # n can come from a scan and the of() cache is unbounded.
        if n == 0:
            return None if single else []
        values = Array(codec, n, self._endian).parse(view[off : off + n * stride])
        return values[0] if single else values

    def _sentinel_wire(self, codec, sentinel, stride: int) -> bytes:
        """Return the ``stride``-byte wire pattern that ends a table.

        The encoding is deliberately UNADAPTED, so a fused THUMB_PTR does
        not turn the terminator into ``1`` instead of ``0``.
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
        view = memoryview(self._bytes("read()"))
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

    def _expected_bytes(self, expect, codec, nbytes: int, addr: int):
        """``expect`` encoded through ``codec``, or None when not given."""
        if expect is None:
            return None
        expected = self._encode(expect, codec)
        if len(expected) != nbytes:
            raise ValueError(
                f"{self._label()}: expect= encodes to {len(expected)} bytes at"
                f" 0x{addr:08X} but the value being written is {nbytes} — the"
                f" two must describe the same bytes"
            )
        return expected

    def _check_expectation(self, off: int, expected: bytes, addr: int) -> None:
        current = bytes(memoryview(self._bytes("expect="))[off : off + len(expected)])
        if current != expected:
            raise PatchVerifyError(
                f"{self._label()}: bytes at 0x{addr:08X} are"
                f" {current.hex()}, but the write expected {expected.hex()}"
                f" — wrong build, moved table, or already applied"
            )

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


def _field_info(codec: StructMeta, name: str, where: str):
    """Return the named top-level field of ``codec``.

    When there is no such field, the error lists the ones there are.
    """
    for info in fields_of(codec):
        if info.name == name:
            return info
    known = ", ".join(i.name for i in fields_of(codec))
    raise ValueError(
        f"{where}: {codec.__name__} has no field {name!r}; it has {known}"
    )


class Entry:
    """One mapped thing: an address, a codec, and how far it runs.

    An entry is a *declaration* rather than a reader. It can be built with
    no space at all, so a map module stays importable without the binary.

    :meth:`bind` attaches a declaration to bytes, one entry at a time.
    Binding a whole map is a comprehension, which lands in the shape a
    caller wants anyway rather than a list they must re-key::

        ROM_MAP = [
            Entry(0x080E1CD0, UInt8, count(4), name="soul_palette"),
            Entry(0x08526390, BossRushReward, count(3), name="boss_rush"),
        ]

        rom = Space(data, base=0x08000000, endian="little")
        by_name = {e.name: e.bind(rom) for e in ROM_MAP}
        by_name["boss_rush"].read()

    An entry is frozen, so rebind with :meth:`bind` rather than mutating it.
    """

    __slots__ = (
        "addr", "codec", "extent", "name", "note", "space", "reserve", "endian",
    )

    addr: int
    codec: Any
    extent: Extent
    name: str
    note: str
    space: Optional[Space]
    #: Bytes set aside here, for when that differs from what the extent
    #: describes. It bounds writes, and it is what coverage counts as
    #: claimed. A pure blob reservation is usually better spelled with a
    #: byte-payload codec, such as ``Entry(addr, Buffer.of(nbytes=0x200))``,
    #: which reads back as ``bytes`` and bounds writes by its own size. Use
    #: ``reserve=`` when the CONTENT has a real shape, such as a growable
    #: table of records, and the room set aside is bigger than the rows
    #: currently in it.
    reserve: Optional[int]
    #: Byte order for this entry's codec, overriding the space's. Normally
    #: None; :meth:`field` sets it when a record declares an order its space
    #: does not share.
    endian: Optional[str]

    def __init__(
        self,
        addr: int,
        codec: Any,
        extent: Union[int, Extent, None] = 1,
        *,
        name: str = "",
        note: str = "",
        space: Optional[Space] = None,
        reserve: Optional[int] = None,
        endian: Optional[str] = None,
    ):
        extent = _as_extent(extent)
        codec = unwrap_alias(codec)  # u16 and UInt16 both mean the scalar
        if not isinstance(addr, int) or addr < 0:
            raise ValueError(f"Entry addr must be a non-negative int, got {addr!r}")
        if reserve is not None and (not isinstance(reserve, int) or reserve < 0):
            raise ValueError(
                f"Entry reserve must be a non-negative int, got {reserve!r}"
            )
        object.__setattr__(self, "addr", addr)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "extent", extent)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "note", note)
        object.__setattr__(self, "space", space)
        object.__setattr__(self, "reserve", reserve)
        object.__setattr__(self, "endian", endian)
        declared = self.size
        if reserve is not None and declared is not None and reserve < declared:
            raise ValueError(
                f"Entry {name or hex(addr)}: reserve={reserve} is smaller than"
                f" the {declared} bytes {extent!r} already declares"
            )

    def __setattr__(self, key, value):
        raise AttributeError(
            f"Entry is frozen; use e.bind(space) or build a new Entry"
            f" (tried to set {key!r})"
        )

    def bind(self, space: Space) -> "Entry":
        """A copy of this entry bound to ``space``."""
        return self._derive(space=space)

    def _derive(self, **changes) -> "Entry":
        """Return a copy with some fields replaced.

        This is the one place that knows the full slot list, so a rebind
        cannot forget a slot added later.
        """
        kw = dict(
            addr=self.addr,
            codec=self.codec,
            extent=self.extent,
            name=self.name,
            note=self.note,
            space=self.space,
            reserve=self.reserve,
            endian=self.endian,
        )
        kw.update(changes)
        addr, codec, extent = kw.pop("addr"), kw.pop("codec"), kw.pop("extent")
        return Entry(addr, codec, extent, **kw)

    def _name(self) -> str:
        return f"Entry {self.name or hex(self.addr)}"

    def _space(self) -> Space:
        if self.space is None:
            raise ValueError(
                f"{self._name()} is not bound to a Space;"
                f" call e.bind(space) (or space.bind(entries)) first"
            )
        # A field's record may declare a byte order its space does not
        # share. The entry carries that order and reads through a view of
        # the space that matches it.
        return self.space._as_endian(self.endian)

    # -- derived -----------------------------------------------------------
    @property
    def stride(self) -> int:
        """One item's size in bytes."""
        return sizeof(self.codec)

    @property
    def item_count(self) -> Optional[int]:
        """Declared item count, or None when the extent does not give one.

        An ``until`` extent needs the buffer to find its terminator, and an
        ``unknown`` extent has no length at all, so both give None.
        """
        extent = self.extent
        if isinstance(extent, count):
            return extent.n
        if isinstance(extent, span):
            total = extent.end - self.addr + 1
            return total // self.stride if total > 0 else None
        return None

    @property
    def size(self) -> Optional[int]:
        """Total bytes the extent describes, or None when
        :attr:`item_count` is unknown."""
        n = self.item_count
        return None if n is None else n * self.stride

    @property
    def capacity(self) -> Optional[int]:
        """Bytes this entry may occupy: its :attr:`reserve` when it
        declares one, otherwise what its extent describes.

        This is what a write may not outgrow, and what coverage counts as
        claimed.
        """
        return self.reserve if self.reserve is not None else self.size

    @property
    def end(self) -> Optional[int]:
        """One past the last byte this entry may occupy, or None when that
        is unknown.

        Two entries abut exactly when ``a.end == b.addr``, which is the
        adjacency a table-cluster check needs to state.
        """
        size = self.capacity
        return None if size is None else self.addr + size

    @property
    def byte_span(self):
        """``(first_addr, last_addr)`` inclusive, or None when unknown."""
        size = self.capacity
        if size is None or size == 0:
            return None
        return (self.addr, self.addr + size - 1)

    # -- derived addresses -------------------------------------------------
    def item(self, index: int) -> "Entry":
        """Item ``index`` of this table, as an entry of its own.

        ``rewards.item(3)`` is the record at ``addr + 3 * stride``. Every
        caller of a table would otherwise write that arithmetic out by
        hand, and get it subtly wrong the day the record grows a field.
        """
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError(f"{self._name()}: item index must be an int")
        n = self.item_count
        if index < 0 or (n is not None and index >= n):
            where = f"0..{n - 1}" if n is not None else "unknown length"
            raise IndexError(
                f"{self._name()}: item {index} is outside this entry ({where})"
            )
        return self._derive(
            addr=self.addr + index * self.stride, extent=count(1), reserve=None,
            name=f"{self.name}[{index}]" if self.name else "",
        )

    def field(self, name: str) -> "Entry":
        """One field of this entry's record, as an entry of its own.

        The address comes from the compiled layout, so ``+0x0A`` stops
        being a constant somebody has to maintain. The codec carries the
        field's own adapter and byte order.

        This entry must hold ONE record. A 113-row table has no single
        field that a name could refer to, so pick the row first, as in
        ``enemies.item(54).field("soul_rate")``.

        Only top-level fields are reachable. Map a nested record as its own
        entry to reach its fields, which is the same boundary the pointer
        audit draws.
        """
        n = self.item_count
        if n is not None and n != 1:
            raise ValueError(
                f"{self._name()}: field({name!r}) needs one record, but this"
                f" entry holds {n}; pick the row first, e.g."
                f" .item(0).field({name!r})"
            )
        base = self
        codec = self.codec
        if not isinstance(codec, StructMeta):
            raise TypeError(
                f"{self._name()}: field() needs a Struct codec to look a name"
                f" up in, but this entry holds {_codec_name(codec)}"
            )
        info = _field_info(codec, name, self._name())
        # byte_span rather than byte_offset, because byte_span also
        # refuses a field that does not occupy whole bytes. Such a field
        # has no address of its own.
        offset, _ = codec.plan.byte_span(name)
        field_codec = info.type
        if info.adapter is not None and not isinstance(
            field_codec, (Array, StructMeta)
        ):
            field_codec = Adapted(field_codec, info.adapter)
        return Entry(
            base.addr + offset,
            field_codec,
            count(1),
            name=f"{base.name}.{name}" if base.name else name,
            space=base.space,
            # The record decides the field's byte order. The space decides
            # it only for codecs that never declared one.
            endian=info.endian,
        )

    def set(self, patch: Any = None, /, **fields: Any) -> None:
        """Write named fields of this entry's record, and nothing else.

        ``pickup.set(p, kind=4, subtype=2)`` claims those fields' bytes and
        leaves the rest of the record alone. That is what lets two features
        edit one record and still compose, and what lets a write land on an
        image this code has never read.

        ``patch`` is positional so that a field may be named ``patch``.
        Without a patch, the fields are written in place.
        """
        if not fields:
            raise TypeError(f"{self._name()}: set() needs at least one field=value")
        for name, value in fields.items():
            self.field(name).write(value, patch=patch)

    # -- access ------------------------------------------------------------
    def read(self, extent: Any = _INHERIT) -> Any:
        """Read this entry.

        ``extent`` overrides the declared extent, which is how an
        ``unknown()`` entry is read once its length turns out to be known.
        Passing ``0`` or ``count(0)`` means zero items rather than "use the
        declared extent".

        To read this declaration against some other bytes, bind it first,
        as in ``entry.bind(space).read()``. :meth:`bind` is the one verb for
        that, and it serves every method here rather than only this one.
        """
        space = self._space()
        if extent is _INHERIT:
            extent = self.extent
        return space.read(self.addr, self.codec, extent)

    # -- bytes in hand -----------------------------------------------------
    def request(self) -> "Tuple[int, int]":
        """Return ``(offset, nbytes)``, which is what a transport is asked for.

        The offset is relative to the space's base, which is what a
        memory-domain read wants. The size comes from the declaration
        rather than from a hand-kept constant.
        """
        size = self.capacity
        if size is None:
            raise ValueError(
                f"{self._name()}: how many bytes to fetch is not known"
                f" ({self.extent!r}); declare count(n)/span(end) or reserve="
            )
        return self._space().offset(self.addr), size

    def parse(self, data: BytesLike) -> Any:
        """Decode this entry out of ``data``, which someone else fetched.

        The bytes do not have to be sitting in a buffer at the right
        address. Fetch them with :meth:`request`, then decode them here.
        Nothing about the transport reaches the library, whether it is
        async, batched or guarded, so the same declaration serves a file
        and a live machine.
        """
        space = self._space()
        stride = space._stride(self.codec)
        extent = self.extent
        if isinstance(extent, (unknown, until)):
            raise ValueError(
                f"{self._name()}: parse() needs a length known up front,"
                f" not {extent!r}; scan a buffer for that"
            )
        n = space._resolve_count(self.addr, extent, stride)
        need = n * stride
        if len(data) < need:
            raise ValueError(
                f"{self._name()}: needs {need} bytes, got {len(data)}"
            )
        single = isinstance(extent, count) and extent.n == 1
        return space._decode_from(data, 0, self.codec, n, stride, single)

    def pack(self, value: Any) -> bytes:
        """Encode ``value`` as this entry's bytes, ready for a transport.

        This is the mirror of :meth:`parse`. A guarded write needs it for
        both its new bytes and its expected ones.
        """
        space = self._space()
        data = space._encode(value, self.codec)
        limit = self.capacity
        if limit is not None and len(data) > limit:
            raise ValueError(
                f"{self._name()}: {len(data)} bytes do not fit the {limit}"
                f" this entry declares"
            )
        return data

    def write(self, value: Any, *, patch: Any = None, expect: Any = None) -> None:
        """Write ``value`` at this entry's address (see :meth:`Space.write`).

        ``expect`` is what this entry must currently hold, stated as a value
        in the entry's own codec. It is the guard for "change the drop rate
        from 32 to 5, and say so if it was not 32".

        A value too wide for the codec wraps rather than raising, as it does
        in C. :meth:`Space.write` explains the rule and the
        ``NarrowingConfig.warn`` knob that reports it.

        The encoding must fit what this entry declares. A table of
        ``count(3)`` holds three records, and a blob may not outgrow the
        space reserved for it. Writing *fewer* bytes stays legal, so a
        partial table update writes the rows it has. An ``until`` extent
        needs the buffer and an ``unknown`` extent has no length, so
        neither declares a size and only the space's own bounds apply.
        """
        space = self._space()
        data = space._encode(value, self.codec)
        limit = self.capacity
        if limit is not None and len(data) > limit:
            declared = (
                f"reserve={self.reserve}" if self.reserve is not None
                else repr(self.extent)
            )
            raise ValueError(
                f"{self._name()}: {len(data)} bytes do not fit the {limit}"
                f" from {declared}; reserve more room or write less"
            )
        # expect is encoded through the ENTRY's codec, so the guard is
        # stated in the same terms as the value. From here down both are
        # already bytes.
        expected = None if expect is None else space._encode(expect, self.codec)
        space.write(self.addr, data, bytes, patch=patch, expect=expected)

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
