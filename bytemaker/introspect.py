"""One front door for schema size and shape questions.

Every schema object already answers ``num_bits`` uniformly — Struct
classes and instances, Array objects, BitType classes and boxes, Plans —
but nothing said so, and the ``uN``/``sN`` aliases (being ``Annotated``
forms) answer nothing at all. Users ended up writing their own size
helpers that plan-hopped between ``plan.num_bytes`` and
``len(bytes(element(0)))`` and broke on exactly those aliases.

* :func:`bitsizeof` / :func:`sizeof` — the width of ANY schema object,
  in bits / whole bytes (sub-byte widths round up, matching
  ``len(bytes(box))``).
* :func:`fields_of` — a Struct's top-level layout as
  ``(name, type, bit_offset, bit_width, adapter)`` tuples, offsets from
  the compiled plan.
"""

from typing import NamedTuple

from bytemaker.structs import StructMeta
from bytemaker.typing_redirect import (
    Any,
    Optional,
    Tuple,
    get_args,
    get_origin,
)

try:  # 3.9+ typing, else typing_extensions (a dependency), else no aliases
    from typing import Annotated
except ImportError:  # pragma: no cover - version-dependent
    try:
        from typing_extensions import Annotated
    except ImportError:
        Annotated = None  # type: ignore[assignment]

__all__ = ["FieldInfo", "bitsizeof", "fields_of", "sizeof"]


def _unwrap(obj):
    """``Annotated[int, UInt16]`` (the ``u16`` alias) -> ``UInt16``;
    everything else passes through."""
    if Annotated is not None and get_origin(obj) is Annotated:
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
    adapter: Optional[Any]  # the field's Adapter, if declared with adapt=


def fields_of(struct) -> Tuple[FieldInfo, ...]:
    """A Struct's top-level fields as :class:`FieldInfo` tuples, in wire
    order, with bit offsets from the compiled plan (nested Structs and
    arrays appear as ONE entry spanning all their leaves; recurse with
    ``fields_of(info.type)`` for nested records)."""
    cls = struct if isinstance(struct, type) else type(struct)
    if not (isinstance(cls, StructMeta) and getattr(cls, "_bm_concrete", False)):
        raise TypeError(
            f"fields_of: {struct!r} is not a concrete Struct class or"
            f" instance"
        )
    first_leaf_offset: dict = {}
    for leaf in cls.plan.fields:
        top = leaf.name.split(".", 1)[0]
        first_leaf_offset.setdefault(top, leaf.bit_offset)
    adapters = cls._bm_adapters
    return tuple(
        FieldInfo(
            n,
            cls._bm_field_types[n],
            first_leaf_offset[n],
            bitsizeof(cls._bm_field_types[n]),
            adapters.get(n),
        )
        for n in cls._bm_fields
    )
