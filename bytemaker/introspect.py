"""One front door for schema size and shape questions.

Every schema object already answers ``num_bits`` uniformly: Struct
classes and instances, Array objects, BitType classes and boxes, and Plans.
Nothing said so, though, and the ``uN``/``sN`` aliases are ``Annotated``
forms, so they answer nothing at all. Users ended up writing their own size
helpers that hopped between ``plan.num_bytes`` and
``len(bytes(element(0)))``, and those helpers broke on exactly those
aliases.

* :func:`bitsizeof` / :func:`sizeof` — the width of ANY schema object,
  in bits / whole bytes. Sub-byte widths round up, matching
  ``len(bytes(box))``.
* :func:`fields_of` — a Struct's top-level layout as
  ``(name, type, bit_offset, bit_width, adapter, endian)`` tuples, with
  offsets and byte order taken from the compiled plan.
* :func:`offset_of` / :func:`span_of` — where one named field starts, and
  how far it runs, in whole bytes.
* :func:`layout` — the same layout rendered for a human to read, so the
  offsets in a map's comments stop being counted by hand.
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
    "bitsizeof",
    "fields_of",
    "layout",
    "offset_of",
    "sizeof",
    "span_of",
]


def _unwrap(obj):
    """``Annotated[int, UInt16]`` (the ``u16`` alias) -> ``UInt16``;
    everything else passes through."""
    if get_origin(obj) is Annotated:
        for meta in get_args(obj)[1:]:
            if isinstance(getattr(meta, "num_bits", None), int):
                return meta
    return obj


def bitsizeof(obj) -> int:
    """The bit width of any schema object: a Struct class or instance, a
    BitType class or box, an :class:`~bytemaker.structs.Array`, a
    :class:`~bytemaker.plans.Plan`, a ``uN``/``sN``/``fN`` alias, or a
    sized field handle."""
    num_bits = getattr(_unwrap(obj), "num_bits", None)
    if isinstance(num_bits, int):
        return num_bits
    raise TypeError(
        f"bitsizeof: {obj!r} carries no bit width (expected a Struct class"
        f" or instance, a BitType class or box, an Array, a Plan, or a"
        f" uN/sN/fN field alias)"
    )


def sizeof(obj) -> int:
    """:func:`bitsizeof` in whole bytes; sub-byte widths round up, matching
    ``len(bytes(box))``."""
    return (bitsizeof(obj) + 7) // 8


class FieldInfo(NamedTuple):
    """One top-level Struct field, located in the compiled layout."""

    name: str
    type: Any
    bit_offset: int
    bit_width: int
    #: The field's Adapter, or None. Present for every adapted field however
    #: it was declared -- ``adapt=``, a fused ``adapter @ BitType``, or an
    #: adapted Array, whose entry is the ELEMENT adapter.
    adapter: Optional[Any]
    #: The field's wire byte order, from the compiled plan -- so a
    #: ``field(T, endian=...)`` override, or a nested record's own
    #: declaration, is visible where every other layout fact is. None
    #: whenever the field's leaves disagree, which a field spanning several
    #: leaves can do in more than one way: a nested record of mixed orders,
    #: or an ARRAY whose element records are internally mixed.
    endian: Optional[str]


def _record_class(struct, caller: str) -> StructMeta:
    """The concrete Struct class behind a class or an instance.

    Shared by every function here that reads a compiled layout, so each
    reports the failure under ITS own name rather than the name of whatever
    it delegated to.
    """
    cls = struct if isinstance(struct, type) else type(struct)
    if not (isinstance(cls, StructMeta) and getattr(cls, "_bm_concrete", False)):
        raise TypeError(
            f"{caller}: {struct!r} is not a concrete Struct class or instance"
        )
    return cls


def fields_of(struct) -> Tuple[FieldInfo, ...]:
    """A Struct's top-level fields as :class:`FieldInfo` tuples, in wire
    order, with bit offsets and byte order from the compiled plan (nested
    Structs and arrays appear as ONE entry spanning all their leaves;
    recurse with ``fields_of(info.type)`` for nested records)."""
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


def offset_of(struct, field: str) -> int:
    """Byte offset of ``field`` within its record.

    This is the typed replacement for a hand-counted ``+0x0A``. The number
    comes from the same compiled layout the codec uses, so reordering or
    resizing the fields ahead of it moves the offset automatically.

    ``field`` may be dotted, as in ``"header.count"``. A field that does not
    start on a byte boundary raises ``ValueError``, because a byte address
    cannot name half a byte.
    """
    cls = _record_class(struct, "offset_of")
    return cls.plan.byte_offset(field)


def span_of(struct, field: str) -> Tuple[int, int]:
    """``(byte offset, byte width)`` of ``field`` within its record.

    :func:`offset_of` says where the field starts, while this also says how
    far it runs. Both numbers together are what it takes to address the
    field's bytes on their own. Raises ``ValueError`` unless the field
    occupies whole bytes.
    """
    cls = _record_class(struct, "span_of")
    return cls.plan.byte_span(field)


def _sole(values):
    """The one member of ``values``, or None if it holds more than one. A
    field spans one plan leaf or many (an array, a nested record); a single
    byte order describes it only when its leaves agree."""
    return next(iter(values)) if len(values) == 1 else None


def _type_name(ftype) -> str:
    """A field type's display name.

    An :class:`~bytemaker.structs.Array` renders as its declaration
    spelling, ``UInt16 * 3``, rather than its repr: the repr also carries
    the Array's own ``endian`` and ``adapt``, which in a layout row would
    duplicate the row's notes — and would print ``endian=unset`` for an
    array field that inherits the record's order perfectly well (unset is
    a STANDALONE Array's concern; as a field the plan has already resolved
    it, and the row's ``endian=`` note reports the resolved value).
    """
    if isinstance(ftype, Array):
        return f"{_type_name(ftype.element)} * {ftype.count}"
    return getattr(ftype, "__name__", None) or repr(ftype)


def _offset_text(bit_offset: int) -> str:
    """``0x0A`` for a byte-aligned offset, ``0x0A.3`` for a sub-byte one."""
    byte, bit = divmod(bit_offset, 8)
    return f"0x{byte:02X}" + (f".{bit}" if bit else "")


def layout(struct) -> str:
    """A record's layout as text — the whole compiled shape in one look::

        FontPixelEntry  (14 bytes, tier=shiftmask, little-endian, lsb-first)
          +0x00  16b  char_number  UInt16  endian=big
          +0x02  96b  pixels       Bufferx12

    That example is this docstring's own output, asserted by
    ``test_layout_docstring_example_is_real_output`` — a rendering example
    that drifts from the renderer is worse than none.

    The header carries the record-level facts: size, plan tier, and BOTH
    compile-time order parameters. ``bit_order`` is there because it is what
    gives a sub-byte offset its meaning — ``+0x04.4`` names a different
    nibble under ``lsb`` than under ``msb`` — so the ``.bit`` suffix below
    would be ambiguous without it. It is a property of the record, not of a
    field, which is why :class:`FieldInfo` has no such member.

    Then one row per :func:`fields_of` entry (so a nested Struct or an array
    is ONE row spanning its leaves; call ``layout(info.type)`` to open it
    up): byte offset — with a ``.bit`` suffix where a field is not
    byte-aligned — bit width, name, wire type, and two notes only when they
    are worth reading. ``endian=`` appears when a field's byte order differs
    from the record's own (or ``endian=mixed`` when its leaves disagree),
    and ``adapt=`` names the field's value convention.

    Accepts a Struct class or an instance; :class:`TypeError` otherwise.
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
