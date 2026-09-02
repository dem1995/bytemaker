"""Size and shape questions about a schema, answered in one place.

Every schema object defines ``num_bits``. That covers Struct classes and
instances, Array objects, BitType classes and boxes, and Plans.

The ``uN``/``sN`` aliases are ``Annotated`` forms with no attributes of
their own. A hand-written helper that reads ``plan.num_bytes`` or
``len(bytes(element(0)))`` therefore fails on them. The functions below
accept every one of these forms, and unwrap an alias before reading its
width.

* :func:`bitsizeof` / :func:`sizeof` give the width of any schema object,
  in bits or in whole bytes. Sub-byte widths round up, matching
  ``len(bytes(box))``.
* :func:`fields_of` returns a Struct's top-level layout as
  ``(name, type, bit_offset, bit_width, adapter, endian)`` tuples. The
  offsets and byte order come from the compiled plan.
* :func:`offset_of` / :func:`span_of` say where one named field starts
  and how far it runs, in whole bytes.
* :func:`layout` renders the same layout as text, so the offsets in a
  map's comments do not have to be counted by hand.
"""

from typing import NamedTuple

from bytemaker.structs import Array, StructMeta
from bytemaker.typing_redirect import (
    Annotated,
    Any,
    Optional,
    Tuple,
    get_args,
    get_origin,
)

__all__ = [
    "FieldInfo",
    "FieldSpan",
    "bitsizeof",
    "fields_of",
    "layout",
    "offset_of",
    "sizeof",
    "span_of",
]


def _unwrap(obj: Any) -> Any:
    """Return the BitType inside a ``uN``/``sN`` alias.

    ``Annotated[int, UInt16]``, the ``u16`` alias, gives ``UInt16``. Any
    other object is returned unchanged.
    """
    if get_origin(obj) is Annotated:
        for meta in get_args(obj)[1:]:
            if isinstance(getattr(meta, "num_bits", None), int):
                return meta
    return obj


def bitsizeof(obj: Any) -> int:
    """The bit width of any schema object.

    Accepts a Struct class or instance, a BitType class or box, an
    :class:`~bytemaker.structs.Array`, a :class:`~bytemaker.plans.Plan`, a
    ``uN``/``sN``/``fN`` alias, or a sized field handle.
    """
    num_bits = getattr(_unwrap(obj), "num_bits", None)
    if isinstance(num_bits, int):
        return num_bits
    raise TypeError(
        f"bitsizeof: {obj!r} carries no bit width (expected a Struct class"
        f" or instance, a BitType class or box, an Array, a Plan, or a"
        f" uN/sN/fN field alias)"
    )


def sizeof(obj: Any) -> int:
    """:func:`bitsizeof` in whole bytes.

    Sub-byte widths round up, matching ``len(bytes(box))``.
    """
    return (bitsizeof(obj) + 7) // 8


class FieldInfo(NamedTuple):
    """One top-level Struct field, located in the compiled layout."""

    name: str
    type: Any
    bit_offset: int
    bit_width: int
    #: The field's Adapter, or None. All three declaration forms fill this
    #: in: ``adapt=``, a fused ``adapter @ BitType``, and an adapted Array.
    #: For an adapted Array it is the ELEMENT adapter.
    adapter: Optional[Any]
    #: The field's wire byte order, taken from the compiled plan. A
    #: ``field(T, endian=...)`` override and a nested record's own
    #: declaration both appear here, next to every other layout fact.
    #: The value is None when the field's leaves disagree, which happens
    #: for a nested record of mixed orders, and for an ARRAY whose element
    #: records are mixed.
    endian: Optional[str]


def _record_class(struct: Any, caller: str) -> StructMeta:
    """The concrete Struct class behind a class or an instance.

    Every function here that reads a compiled layout calls this and passes
    its own name. A failure is then reported under the function the caller
    actually called.
    """
    cls = struct if isinstance(struct, type) else type(struct)
    if not (isinstance(cls, StructMeta) and getattr(cls, "_bm_concrete", False)):
        raise TypeError(
            f"{caller}: {struct!r} is not a concrete Struct class or instance"
        )
    return cls


def fields_of(struct: Any) -> Tuple[FieldInfo, ...]:
    """A Struct's top-level fields as :class:`FieldInfo` tuples, in wire order.

    Bit offsets and byte order come from the compiled plan. A nested Struct
    or an array is ONE entry spanning all its leaves. Call
    ``fields_of(info.type)`` to open a nested record up.
    """
    cls = _record_class(struct, "fields_of")
    first_leaf_offset: dict = {}
    leaf_endians: dict = {}
    for leaf in cls.plan.fields:
        top = leaf.name.split(".", 1)[0]
        first_leaf_offset.setdefault(top, leaf.bit_offset)
        leaf_endians.setdefault(top, set()).add(leaf.endian)
    adapters = cls._bm_adapters
    return tuple(
        FieldInfo(
            n,
            cls._bm_field_types[n],
            first_leaf_offset[n],
            bitsizeof(cls._bm_field_types[n]),
            adapters.get(n),
            _sole(leaf_endians[n]),
        )
        for n in cls._bm_fields
    )


def offset_of(struct: Any, field: str) -> int:
    """Byte offset of ``field`` within its record.

    This replaces a hand-counted ``+0x0A``. The number comes from the same
    compiled layout the codec uses, so reordering or resizing the fields
    ahead of it updates the offset.

    ``field`` may be dotted, as in ``"header.count"``. A field that does not
    start on a byte boundary raises ``ValueError``, because a byte address
    cannot refer to half a byte.
    """
    cls = _record_class(struct, "offset_of")
    return cls.plan.byte_offset(field)


class FieldSpan(NamedTuple):
    """Where a field sits in its record: byte ``offset`` and byte ``width``.

    A tuple with named members, so ``off, width = span_of(...)`` unpacks
    as before and ``span_of(...).width`` says which number is which.
    """

    offset: int
    width: int


def span_of(struct: Any, field: str) -> FieldSpan:
    """The byte offset and byte width of ``field`` within its record.

    :func:`offset_of` gives the start. This gives the start and the width,
    which together address the field's bytes on their own.

    The second number is a width, not an end offset. A ``UInt16`` after a
    ``UInt32`` spans ``FieldSpan(offset=4, width=2)``, and its end is the
    sum, 6.

    Raises ``ValueError`` unless the field occupies whole bytes.
    """
    cls = _record_class(struct, "span_of")
    return FieldSpan(*cls.plan.byte_span(field))


def _sole(values):
    """The one member of ``values``, or None if it holds more than one.

    A field covers one plan leaf or several, as an array or a nested record
    does. A single byte order describes it only when its leaves agree.
    """
    return next(iter(values)) if len(values) == 1 else None


def _type_name(ftype) -> str:
    """A field type's display name.

    An :class:`~bytemaker.structs.Array` renders as its declaration
    spelling, ``UInt16 * 3``, rather than as its repr.

    The repr also includes the Array's own ``endian`` and ``adapt``, which
    would duplicate the row's notes. It would print ``endian=unset`` for an
    array field that inherits the record's order. Unset applies only to a
    standalone Array: as a field, the plan has already resolved the order,
    and the row's ``endian=`` note reports the resolved value.
    """
    if isinstance(ftype, Array):
        return f"{_type_name(ftype.element)} * {ftype.count}"
    return getattr(ftype, "__name__", None) or repr(ftype)


def _offset_text(bit_offset: int) -> str:
    """``0x0A`` for a byte-aligned offset, ``0x0A.3`` for a sub-byte one."""
    byte, bit = divmod(bit_offset, 8)
    return f"0x{byte:02X}" + (f".{bit}" if bit else "")


def layout(struct: Any) -> str:
    """Return a record's compiled layout as text, for a person to read.

    Takes a Struct class or an instance, and raises :class:`TypeError` for
    anything else. Use :func:`fields_of` to work with the same information
    in code, since this output is meant for reading rather than parsing.

    Given this record::

        class FontPixelEntry(Struct, endian="little"):
            char_number: int = field(UInt16, endian="big")
            pixels: bytes = field(Buffer.of(nbytes=0xC))

    ``layout(FontPixelEntry)`` returns::

        FontPixelEntry  (14 bytes, tier=shiftmask, little-endian, lsb-first)
          +0x00  16b  char_number  UInt16  endian=big
          +0x02  96b  pixels       Bufferx12

    The header line names the record, then gives the facts that belong to
    the record as a whole: its size in bytes, its plan tier, and its two
    compile-time order parameters. ``bit_order`` is one of them because a
    sub-byte offset means nothing without it, as ``+0x04.4`` names a
    different nibble under ``lsb`` than under ``msb``.

    Each row below the header describes one field: byte offset, bit width,
    name, and wire type. An offset gains a ``.bit`` suffix when the field
    does not start on a byte boundary. A nested Struct or an array takes ONE
    row covering all of its leaves, so call ``layout`` again on that field's
    type to expand it.

    Two notes appear only where they apply. ``endian=`` marks a field whose
    byte order differs from the record's, and ``endian=mixed`` marks a
    composite field whose leaves disagree. ``adapt=`` names the field's
    value convention.
    """
    cls = _record_class(struct, "layout")
    infos = fields_of(cls)
    plan = cls.plan
    head = (
        f"{cls.__name__}  ({sizeof(cls)} bytes, tier={plan.tier},"
        f" {plan.endian}-endian, {plan.bit_order}-first)"
    )
    if not infos:
        return head
    offsets = [_offset_text(i.bit_offset) for i in infos]
    offw = max(len(o) for o in offsets)
    bitw = max(len(str(i.bit_width)) for i in infos)
    namew = max(len(i.name) for i in infos)
    rows = [head]
    for info, offset in zip(infos, offsets):
        notes = ""
        if info.endian is None:
            notes += "  endian=mixed"
        elif info.endian != plan.endian:
            notes += f"  endian={info.endian}"
        if info.adapter is not None:
            notes += f"  adapt={getattr(info.adapter, 'name', info.adapter)}"
        rows.append(
            f"  +{offset:<{offw}}  {info.bit_width:>{bitw}}b"
            f"  {info.name:<{namew}}  {_type_name(info.type)}{notes}"
        )
    return "\n".join(rows)
