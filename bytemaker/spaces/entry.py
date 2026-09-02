"""One mapped thing: :class:`Entry` ties an address to a codec and an extent.

An entry is a declaration rather than a reader: a map module full of them
imports with no binary in hand. :meth:`Entry.bind` attaches a declaration
to a :class:`~bytemaker.spaces.spaces.Space` when there are bytes, or a
live target, to work against.

See :mod:`bytemaker.spaces` for the layer's overview.
"""

from typing import TYPE_CHECKING, NamedTuple

from bytemaker.adapters import Adapted
from bytemaker.introspect import fields_of, sizeof
from bytemaker.structs import Array, BytesLike, StructMeta
from bytemaker.typing_redirect import Any, Optional, Union
from bytemaker.utils import unwrap_alias

from .extents import _INHERIT, Extent, _as_extent, count, through, unknown, until
from .pointers import _codec_name

if TYPE_CHECKING:
    from .spaces import Space


class FetchRequest(NamedTuple):
    """What a transport is asked for: byte ``offset`` and ``nbytes``.

    A tuple with named members, so ``off, size = entry.request()`` unpacks
    as before and ``entry.request().nbytes`` says which number is which.
    """

    offset: int
    nbytes: int


def _field_info(codec: StructMeta, name: str, where: str):
    """Return the named top-level field of ``codec``.

    When there is no such field, the error lists the ones there are.
    """
    for info in fields_of(codec):
        if info.name == name:
            return info
    known = ", ".join(i.name for i in fields_of(codec))
    raise ValueError(f"{where}: {codec.__name__} has no field {name!r}; it has {known}")


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
        "addr",
        "codec",
        "extent",
        "name",
        "note",
        "space",
        "reserve",
        "endian",
    )

    addr: int
    codec: Any
    extent: Extent
    name: str
    note: str
    space: Optional["Space"]
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
        space: Optional["Space"] = None,
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
        n = self.item_count
        declared = None if n is None else n * self.stride
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

    def bind(self, space: "Space") -> "Entry":
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

    def _space(self) -> "Space":
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
        if isinstance(extent, through):
            total = extent.last - self.addr + 1
            return total // self.stride if total > 0 else None
        return None

    @property
    def size(self) -> Optional[int]:
        """Bytes this entry occupies: its :attr:`reserve` when it declares
        one, otherwise the bytes its extent describes. None when neither
        is known.

        This is what a write may not outgrow, and what coverage counts as
        claimed. The extent's own byte count, ignoring a reservation, is
        ``item_count * stride``.
        """
        if self.reserve is not None:
            return self.reserve
        n = self.item_count
        return None if n is None else n * self.stride

    @property
    def end(self) -> Optional[int]:
        """One past the last byte this entry may occupy, or None when that
        is unknown.

        Two entries abut exactly when ``a.end == b.addr``, which is the
        adjacency a table-cluster check needs to state.
        """
        size = self.size
        return None if size is None else self.addr + size

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
            addr=self.addr + index * self.stride,
            extent=count(1),
            reserve=None,
            name=f"{self.name}[{index}]" if self.name else "",
        )

    def field(self, name: str) -> "Entry":
        """One field of this entry's record, as an entry of its own.

        The address comes from the compiled layout rather than from a
        hand-kept offset constant, so it cannot go stale. The codec
        carries the field's own adapter and byte order.

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

        ``pickup.set(p, kind=4, subtype=2)`` writes those fields' bytes and
        leaves the rest of the record alone. Two features can therefore
        edit one record and still compose. The write also works on an
        image this code has never read, because only the named fields'
        bytes are touched.

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
        as in ``entry.bind(space).read()``. The same applies to every
        other method here that touches bytes.
        """
        space = self._space()
        if extent is _INHERIT:
            extent = self.extent
        return space.read(self.addr, self.codec, extent)

    # -- bytes in hand -----------------------------------------------------
    def request(self) -> FetchRequest:
        """The :class:`FetchRequest` a transport is asked for.

        The ``offset`` is relative to the space's base, which is what a
        memory-domain read wants. ``nbytes`` comes from the declaration
        rather than from a hand-kept constant.
        """
        size = self.size
        if size is None:
            raise ValueError(
                f"{self._name()}: how many bytes to fetch is not known"
                f" ({self.extent!r}); declare count(n)/through(last) or reserve="
            )
        return FetchRequest(self._space().offset(self.addr), size)

    def parse(self, data: BytesLike) -> Any:
        """Decode this entry out of ``data``, which someone else fetched.

        The bytes do not have to be sitting in a buffer at the right
        address. Fetch them with :meth:`request`, then decode them here.
        Nothing about the transport reaches the library, whether it is
        async, batched or guarded, so the same declaration serves a file
        and a live machine.

        Every live-target consumer ends up wanting the same three-line
        helper, so write it once against your transport rather than per
        call site::

            async def fetch(entry):
                off, size = entry.request()
                (data,) = await conn.read_many([(off, size, DOMAIN)])
                return entry.parse(data)
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
            raise ValueError(f"{self._name()}: needs {need} bytes, got {len(data)}")
        single = isinstance(extent, count) and extent.n == 1
        return space._decode_from(data, 0, self.codec, n, stride, single)

    def pack(self, value: Any) -> bytes:
        """Encode ``value`` as this entry's bytes, ready for a transport.

        This is the mirror of :meth:`parse`. A guarded write needs it for
        both its new bytes and its expected ones.
        """
        space = self._space()
        data = space._encode(value, self.codec)
        limit = self.size
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
        limit = self.size
        if limit is not None and len(data) > limit:
            declared = (
                f"reserve={self.reserve}"
                if self.reserve is not None
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
        space._write(
            self.addr, data, bytes, patch=patch, expect=expected, via=self._name()
        )

    def describe(self) -> str:
        """One line: name, address range, codec and extent."""
        codec_name = getattr(self.codec, "__name__", None) or repr(self.codec)
        pieces = [f"0x{self.addr:08X}"]
        size = self.size
        if size:
            pieces.append(f"-0x{self.addr + size - 1:08X}")
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
