"""The address space itself: :class:`Space`.

A :class:`Space` maps a buffer at a base address and supplies the byte
order that scalar reads and writes use. The extents that say how far a
table runs live in :mod:`~bytemaker.spaces.extents`, and the
:class:`~bytemaker.spaces.entry.Entry` declarations that name mapped
things live in :mod:`~bytemaker.spaces.entry`.

See :mod:`bytemaker.spaces` for the layer's overview.
"""

from typing import cast

from bytemaker.adapters import Adapted
from bytemaker.introspect import bitsizeof
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
    Union,
)
from bytemaker.utils import unwrap_alias, validate_endianness

from .coverage import compute_coverage
from .entry import Entry
from .extents import Extent, _as_extent, count, through, unknown, until
from .patches import PatchVerifyError, _changed_runs
from .pointers import _ptr_adapter_of


class AddressError(ValueError):
    """An address or a span falls outside the space it addresses.

    This is a distinct class so that a pointer audit can catch
    out-of-range addresses on their own. The audit expects some of the
    addresses it checks to be out of range, and catching plain
    ``ValueError`` would also catch every decode failure.
    """


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
    read bytes raises, with a message that says why.

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
        that differs at exactly those bytes, and produces the wrong result
        there without reporting anything.

        A write through a recording space claims **the whole span
        written**, not just the bytes that changed. ``patch=`` writes claim
        only the changed bytes, because those writes leave the buffer
        alone. Without that rule, a later whole-record write would read the
        pristine bytes and record them as the original, undoing an earlier
        edit (see :meth:`write`). A recording write updates the buffer, so
        later reads see it and the rule is unnecessary. Claiming the full
        span is worth more here::

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
                f" over the bytes once you have them; for a live target,"
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
                f"; pass a count at the call site, or declare"
                f" count(n)/until(sentinel)/through(last_addr)"
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
        patch checks it later. Either way the write fails when the target
        does not already hold ``expect``, which is what catches a wrong
        build or a moved table.

        A recorded ``expect`` claims the **full stated span**, and it is
        exempt from the changed-bytes-only rule below. The caller stated a
        guard over that whole value, so ``guards()`` covers the whole value
        too. Writing the expected value back therefore still records a
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
        default. A build that never wants a silent wrap, which is the
        normal stance for randomizer-style writes, escalates the warning
        to an error::

            NarrowingConfig.warn = True
            warnings.filterwarnings("error", category=NarrowingWarning)

        Every value-changing store then raises instead of wrapping, and
        the raise lands before any bytes do, because encoding precedes
        the buffer mutation.

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
        ``|``.

        A ``patch=`` write that finds the buffer already holding the new
        value therefore records nothing. A feature that reads the patch
        back as its own table of writes then sees fewer bytes than it
        wrote. To have every written byte recorded, state ``expect=`` with
        the current value, because a stated guard is recorded whole, or
        build against a geometry-only space, which records every write
        since it has no bytes to compare against. Adjacent writes also come
        back from :attr:`Patch.edits` merged into one contiguous run rather
        than one edit per write.

        The rule is safe here because the buffer is untouched, so reads
        never see pending edits. Without it, a later whole-record write
        would read the pristine bytes and record them as the original,
        undoing an earlier edit. A flow whose later steps must see what the
        earlier ones wrote should write through :meth:`recording` instead,
        which updates the buffer and records the whole span of every write.
        """
        self._write(addr, value, codec, patch=patch, expect=expect)

    def _write(
        self,
        addr: int,
        value: Any,
        codec: Any,
        *,
        patch: Any,
        expect: Any,
        via: str = "",
    ) -> None:
        # The body of write(). ``via`` names the Entry a write came in
        # through, so an expect= mismatch can say which declaration it was.
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
                    f"{self._label()}: nothing to mutate; this space is"
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
            self._check_expectation(off, expected, addr, via)
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
                ": that is the field's VALUE; pass the CLASS attribute"
                " (e.g. WarpPoint.room_ptr) or the name string, or call"
                " value.deref(space) directly"
                if isinstance(field, int)
                else "; pass the field's name or the class attribute"
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
            return [self._deref_value(v, ptr, extent) for v in value]
        return self._deref_value(value, ptr, extent)

    def _deref_value(
        self,
        addr: int,
        ptr: Any,
        extent: Union[int, "Extent", None] = 1,
    ) -> Any:
        """Follow one address through ``ptr``.

        ``ptr`` is a :class:`Ptr` codec or its adapter. The public
        spellings are :meth:`deref` for a record's field and
        :meth:`PtrValue.deref` for an address already read; both come
        through here.
        """
        adapter = _ptr_adapter_of(ptr)
        if adapter is None:
            raise TypeError(
                f"{self._label()}: {ptr!r} is not a Ptr (or a Ptr's adapter)"
            )
        if adapter.target is None:
            raise TypeError(
                f"{self._label()}: {adapter.name} has no target codec;"
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
        return compute_coverage(self, entries, audit_pointers=audit_pointers)

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
                f"{self._label()}: {codec!r} is {bits} bits; a byte address"
                f" has no room for a sub-byte stride; wrap it in a Struct and"
                f" map that"
            )
        return bits // 8

    def _resolve_count(self, addr: int, extent: Extent, stride: int) -> int:
        if isinstance(extent, count):
            return extent.n
        if isinstance(extent, through):
            if extent.last < addr:
                raise ValueError(
                    f"{self._label()}: through(last=0x{extent.last:08X}) is"
                    f" before the start address 0x{addr:08X}"
                )
            total = extent.last - addr + 1
            if total % stride:
                raise ValueError(
                    f"{self._label()}: 0x{addr:08X} through 0x{extent.last:08X}"
                    f" is {total} bytes, not a whole number of {stride}-byte"
                    f" items; the address, the last address, or the record"
                    f" shape is wrong"
                )
            return total // stride
        raise TypeError(f"{self._label()}: unsupported extent {extent!r}")

    def _in_space_endian(self, codec: Array) -> Array:
        """Fill in this space's byte order on an ``Array`` that has none.

        An array that declares its own byte order is returned unchanged,
        because an explicitly declared endian is always honored. An unset
        array inherits the space's byte order for the same reason an unset
        array FIELD inherits its record's.

        Without this step a standalone unset array would raise the
        explicit-endian guard, even though the space's byte order is
        known. A scalar ``UInt16`` at the
        same address is unaffected, because the scalar paths build their
        array from ``self._endian``.
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
        return self._decode_from(self._bytes("read()"), off, codec, n, stride, single)

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
                f" 0x{addr:08X} but the value being written is {nbytes}; the"
                f" two must describe the same bytes"
            )
        return expected

    def _check_expectation(
        self, off: int, expected: bytes, addr: int, via: str = ""
    ) -> None:
        current = bytes(memoryview(self._bytes("expect="))[off : off + len(expected)])
        if current != expected:
            where = f"{self._label()}, {via}" if via else self._label()
            raise PatchVerifyError(
                f"{where}: bytes at 0x{addr:08X} are"
                f" {current.hex()}, but the write expected {expected.hex()}"
                f"; wrong build, moved table, or already applied"
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
