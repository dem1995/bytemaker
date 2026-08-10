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
"""

from bytemaker.adapters import Adapted
from bytemaker.introspect import bitsizeof, sizeof
from bytemaker.structs import Array, Struct, StructMeta
from bytemaker.typing_redirect import Any, List, Literal, Optional, Union
from bytemaker.utils import validate_endianness

__all__ = [
    "AddressError",
    "Entry",
    "Extent",
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
            items = [
                codec.parse(view[i : i + stride])
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
        raise TypeError(
            f"{self._label()}: cannot infer a codec for {value!r}; pass one"
            f" (codec= is optional only for Struct records)"
        )

    def _encode(self, value, codec) -> bytes:
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
            if value and isinstance(value[0], (list, tuple)):
                return b"".join(codec.pack(v) for v in value)
            return codec.pack(value)
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
        """Write ``value`` at this entry's address (see :meth:`Space.write`)."""
        self._space().write(self.addr, value, self.codec, patch=patch)

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
