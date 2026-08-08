"""
Aggregate conversions: dataclasses of BitTypes/ctypes/Python primitives
to and from bits/bytes.

Public API is unchanged from bytemaker 0.11/0.12. Internally, the byte-level
functions now route eligible dataclasses (every field a byte-aligned BitType
class) through compiled per-class plans (:mod:`bytemaker.plans`): field types
are resolved and offsets computed once per class instead of per call, and no
whole-record BitVector is built. Everything else -- ctypes fields, PyType
fields, nested dataclasses, sub-byte fields, and all bit-level calls --
delegates to the frozen reference implementation in
:mod:`bytemaker._legacy_aggregate`, which is also the differential-test
oracle the fast paths are validated against.

One deliberate behavior fix vs 0.12: ``from_bytes_aggregate(...,
is_array=True)`` now returns a ``list`` of decoded entries. (Previously it
attempted ``aggregate_type(*entries)`` and ignored ``is_array`` entirely
for scalar types.)
"""

import struct as _struct

from bytemaker import _legacy_aggregate as _legacy

# Re-exported verbatim (bit-level paths and shared helpers keep the reference
# implementation; sub-byte-capable callers go through these).
from bytemaker._legacy_aggregate import (  # noqa: F401
    AggregateTypeByteConvertible,
    UnitType,
    count_bytes_in_unit_type,
    from_bits_aggregate,
    from_bits_individual,
    from_bytes_individual,
    to_bits_aggregate,
    to_bits_individual,
    to_bytes_individual,
    trycast,
)
from bytemaker.bittypes import BitType
from bytemaker.bittypes.bittype import NarrowingConfig
from bytemaker.bittypes.int import SignedConfig
from bytemaker.plans import PlanCompileError, compile_legacy_record_plan
from bytemaker.typing_redirect import Dict, Literal, Union, get_type_hints
from bytemaker.utils import (
    DataClassType,
    is_instance_of_union,
    is_subclass_of_union,
    validate_endianness,
)

__all__ = [
    "UnitType",
    "AggregateTypeByteConvertible",
    "resolve_field_types",
    "count_bits_in_unit_type",
    "count_bits_in_aggregate_type",
    "count_bytes_in_unit_type",
    "to_bits_individual",
    "to_bytes_individual",
    "from_bits_individual",
    "from_bytes_individual",
    "to_bits_aggregate",
    "from_bits_aggregate",
    "to_bytes_aggregate",
    "from_bytes_aggregate",
    "trycast",
]

_HINTS_CACHE: Dict[type, Dict[str, type]] = {}
_UNIT_BITS_CACHE: Dict[type, int] = {}

_orig_count_bits_in_unit_type = _legacy.count_bits_in_unit_type


def resolve_field_types(dataclass_type: type) -> Dict[str, type]:
    """
    Resolve a dataclass's field annotations to concrete types, cached per
    class.

    Field annotations are strings rather than types whenever the defining
    module uses ``from __future__ import annotations`` (PEP 563) or otherwise
    stringizes its annotations. ``typing.get_type_hints`` evaluates those
    strings in the namespace of the module that defined the dataclass, so
    concrete types such as ``SInt16`` resolve correctly. A bare ``eval`` would
    instead resolve them in bytemaker's own namespace and raise ``NameError``.

    ``get_type_hints`` dominated the per-call cost of the 0.11/0.12 aggregate
    functions (~50 us of every call), so its result is cached per class here.
    Mutating a class's annotations after first use is not supported.

    Returns:
        Dict[str, type]: A mapping from field name to its resolved type.
    """
    try:
        return _HINTS_CACHE[dataclass_type]
    except (KeyError, TypeError):
        pass
    hints = get_type_hints(dataclass_type)
    try:
        _HINTS_CACHE[dataclass_type] = hints
    except TypeError:
        pass
    return hints


def count_bits_in_unit_type(unit_type) -> int:
    """
    Function to count the number of bits in a UnitType-\
        a Python, type, ctype, or BitType (bytemaker type).

    Cached per type.
    """
    try:
        return _UNIT_BITS_CACHE[unit_type]
    except (KeyError, TypeError):
        pass
    bits = _orig_count_bits_in_unit_type(unit_type)
    try:
        _UNIT_BITS_CACHE[unit_type] = bits
    except TypeError:
        pass
    return bits


def count_bits_in_aggregate_type(aggregate_type: type) -> int:
    """
    Function to count the number of bits in an aggregate type-\
        a Python, type, ctype, BitType (bytemaker type), or
        a dataclass annotated with those.
    """
    return _legacy.count_bits_in_aggregate_type(aggregate_type)


# Point the reference implementation's module globals at the cached versions,
# so fallback calls (and its internal recursion) share the per-class caches.
# Caching is behavior-transparent; the oracle's semantics are unchanged.
_legacy.resolve_field_types = resolve_field_types
_legacy.count_bits_in_unit_type = count_bits_in_unit_type


def _get_record_plan(aggregate_type):
    """Fast-path plan for a dataclass, or None (cached either way)."""
    try:
        return compile_legacy_record_plan(
            aggregate_type, resolve_field_types(aggregate_type)
        )
    except PlanCompileError:
        return None


def _pack_all_plain_numbers(plan, units, endianness):
    """One-call struct.pack when every field value is a plain number and every
    field has a struct letter. Signed ints require the global two's-complement
    format (otherwise the boxed coercion path is authoritative). Returns None
    when ineligible."""
    letters = plan.fmt_letters
    if None in letters:
        return None
    if SignedConfig.signed_int_format != "twos_complement":
        return None
    if NarrowingConfig.warn:
        # Checked-store mode: the boxed coercion path is authoritative (it
        # emits the opt-in NarrowingWarning); the one-call fast path would
        # wrap silently.
        return None
    values = []
    for name, ftype, letter in zip(plan.names, plan.types, letters):
        v = getattr(units, name)
        if isinstance(v, int) and not isinstance(v, BitType):
            if letter in "bhiq":  # signed: C-style wrap into range
                n = ftype.num_bits
                v = ((v + (1 << (n - 1))) % (1 << n)) - (1 << (n - 1))
            elif letter in "BHIQ":
                v &= (1 << ftype.num_bits) - 1
            else:
                return None  # int into a float field: defer to boxed path
        elif isinstance(v, float) and letter in "efd":
            pass
        else:
            return None
        values.append(v)
    prefix = "<" if endianness == "little" else ">"
    return _struct.pack(prefix + "".join(letters), *values)


def to_bytes_aggregate(
    units: AggregateTypeByteConvertible,
    endianness: Literal["big", "little"] = "big",
) -> bytes:
    """
    Function to convert a collection of Python primitives or ctypes objects into bytes.

    Essentially a bitfield serializer.

    Args:
        units (AggregateTypeByteConvertible): The objects to convert to bytes
        endianness: The byte order of the output.
            Defaults to "big".

    Returns:
        bytes: The bytes representation of the objects
    """
    validate_endianness(endianness)
    if isinstance(units, DataClassType) and not is_instance_of_union(units, UnitType):
        plan = _get_record_plan(type(units))
        if plan is not None:
            fast = _pack_all_plain_numbers(plan, units, endianness)
            if fast is not None:
                return fast
            return plan.pack(units, endianness)
    return _legacy.to_bytes_aggregate(units, endianness=endianness)


def from_bytes_aggregate(
    bytes_obj: bytes,
    aggregate_type: type,
    is_array=False,
    endianness: Literal["big", "little"] = "big",
) -> Union[UnitType, AggregateTypeByteConvertible]:
    """
    Function to convert a collection of bytes into Python primitives, ctypes objects,\
        BitTypes, or a dataclass of those types.

    Essentially a bitfield deserializer.

    Args:
        bytes_obj (bytes): The bytes object to convert to a Python primitive,
            ctypes object, BitType, or dataclass.
        aggregate_type (type): The type(s) of the object to convert to.
            Must be a member of UnitType or a dataclass annotated with UnitType members.
        is_array (bool, optional): Whether ``bytes_obj`` holds consecutive
            entries of ``aggregate_type``; if so a ``list`` of decoded entries
            is returned. Defaults to False.
        endianness: The byte order of the input bytes.
            Defaults to "big".

    Returns:
        Union[UnitType, AggregateTypeByteConvertible]: The object(s) represented by
            the bytes.
    """
    validate_endianness(endianness)
    if is_array:
        entry_bits = count_bits_in_aggregate_type(aggregate_type)
        entry_bytes = (entry_bits + 7) // 8
        return [
            from_bytes_aggregate(
                bytes_obj[i : i + entry_bytes], aggregate_type, endianness=endianness
            )
            for i in range(0, len(bytes_obj), entry_bytes)
        ]

    if not is_subclass_of_union(aggregate_type, UnitType):
        plan = _get_record_plan(aggregate_type)
        if plan is not None:
            return plan.parse(bytes_obj, endianness)
    return _legacy.from_bytes_aggregate(
        bytes_obj, aggregate_type, is_array=False, endianness=endianness
    )
