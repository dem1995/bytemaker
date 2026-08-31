"""
The pre-plan-compiler (0.12) aggregate-conversion reference implementation.

This module has two roles.

1. **Fallback**: ``bytemaker.conversions.aggregate_types`` routes eligible
   dataclasses through compiled ``bytemaker.plans`` fast paths. It delegates
   everything else here unchanged: ctypes fields, PyType fields, nested
   dataclasses, sub-byte-field dataclasses, and all bit-level calls.
2. **Differential-test oracle**: the fast paths are required to be
   byte-identical to this implementation, and
   ``test/plan_fastpath_test.py`` enforces that over randomized layouts.

Those roles imply a coordination procedure, not a veto on change. A
deliberate behavior change lands in this module and in the fast paths as one
change, and the parity suite is re-run afterwards. It never lands in one
path alone.
"""

import ctypes
import dataclasses

from bytemaker.bittypes import BitType, bytes_to_bittype
from bytemaker.bitvector import BitVector
from bytemaker.conversions.ctypes_ import (
    CType,
    bits_to_ctype,
    bytes_to_ctype,
    ctype_to_bits,
    ctype_to_bytes,
)
from bytemaker.conversions.pytypes import (
    ConversionConfig,
    PyType,
    bits_to_pytype,
    bytes_to_pytype,
    pytype_to_bits,
    pytype_to_bytes,
)
from bytemaker.typing_redirect import Dict, Iterable, Literal, Union, get_type_hints
from bytemaker.utils import (
    DataClassType,
    is_instance_of_union,
    is_subclass_of_union,
    validate_endianness,
)

UnitType = Union[CType, BitType, PyType]

# CType is a Union of _SimpleCData, Structure, Union, and Array
# YType is a Union of YInt, YFloat, YString, YBytes, YBool, YEnum, YArray, and YStruct
# PyType is a Union of int, float, str, bytes, bool, and Enum


_HINTS_CACHE: Dict[type, Dict[str, type]] = {}
_UNIT_BITS_CACHE: Dict = {}  # key: UnitType member (wider than plain `type`)


def resolve_field_types(dataclass_type: type) -> Dict[str, type]:
    """
    Resolve a dataclass's field annotations to concrete types, cached per
    class.

    Field annotations are strings rather than types whenever the defining
    module uses ``from __future__ import annotations`` (PEP 563) or
    otherwise stringizes its annotations. ``typing.get_type_hints``
    evaluates those strings in the namespace of the module that defined the
    dataclass, so concrete types such as ``SInt16`` resolve correctly. A
    bare ``eval`` would instead resolve them in bytemaker's own namespace
    and raise ``NameError``.

    For non-stringized annotations the field types are already real objects
    and are returned unchanged, so this is safe to use unconditionally.

    ``get_type_hints`` dominated the per-call cost of the 0.11/0.12
    aggregate functions, at roughly 50 us of every call. Its result is
    therefore cached per class here, in the reference implementation itself.
    The cache used to live in a wrapper in ``aggregate_types`` that
    monkeypatched this module's globals on import, which made this module's
    behavior depend on import order.

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


def count_bits_in_unit_type(unit_type: UnitType) -> int:
    """Count the number of bits in a UnitType.

    A UnitType is a Python type, a ctype, or a BitType (a bytemaker type).

    The result is cached per type, here in the reference implementation. The
    cache used to be a wrapper in ``aggregate_types`` that monkeypatched
    this module's global, which made behavior depend on import order.

    Returns:
        int: The number of bits the unit type occupies.
    """
    try:
        return _UNIT_BITS_CACHE[unit_type]
    except (KeyError, TypeError):
        pass
    if is_subclass_of_union(unit_type, CType):
        bits = ctypes.sizeof(unit_type) * 8
    elif is_subclass_of_union(unit_type, BitType):
        bits = unit_type.num_bits
    elif is_subclass_of_union(unit_type, PyType):
        bits = ConversionConfig.get_conversion_info(unit_type).num_bits("")
    elif is_subclass_of_union(unit_type, DataClassType):
        bits = 0
        field_types = resolve_field_types(unit_type)
        for field in dataclasses.fields(unit_type):
            bits += count_bits_in_unit_type(field_types[field.name])
    else:
        raise TypeError(
            f"Cannot count bits in {unit_type} because the unit type"
            f" is not a CType, YType, PyType, or dataclass"
        )
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
    if is_subclass_of_union(aggregate_type, UnitType):
        return count_bits_in_unit_type(aggregate_type)
    else:
        size_in_bits = 0
        field_types = resolve_field_types(aggregate_type)
        for field in dataclasses.fields(aggregate_type):
            size_in_bits += count_bits_in_unit_type(field_types[field.name])
        return size_in_bits


def count_bytes_in_unit_type(unit_type: UnitType) -> int:
    """
    Function to count the number of bytes in a UnitType-
        a Python numeric/binary/string type, ctype, or BitType (bytemaker type).
    """
    return (count_bits_in_unit_type(unit_type) + 7) // 8


def to_bits_individual(unit: UnitType) -> BitVector:
    """
    Function to convert a single Python primitive or ctypes object into BitVector.
    """
    if is_instance_of_union(unit, CType):
        return ctype_to_bits(unit)
    elif isinstance(unit, BitType):
        return unit.bits
    elif is_instance_of_union(unit, PyType):
        return pytype_to_bits(unit)
    else:
        raise TypeError(
            f"Cannot convert {unit} to bits because"
            f" the unit type is not a CType, YType, or PyType"
        )


def to_bytes_individual(
    unit: UnitType, endianness: Literal["big", "little"] = "big"
) -> bytes:
    """
    Function to convert a single Python primitive or ctypes object into bytes.
    """
    validate_endianness(endianness)

    if is_instance_of_union(unit, CType):
        return ctype_to_bytes(unit, endianness=endianness)
    elif isinstance(unit, BitType):
        unit_bytes = bytes(unit)
        if endianness == "little":
            unit_bytes = unit_bytes[::-1]
        return unit_bytes
    elif is_instance_of_union(unit, PyType):
        return pytype_to_bytes(unit, endianness=endianness)
    else:
        raise TypeError(
            f"Cannot convert {unit} to bytes because"
            f" the unit type is not a CType, YType, or PyType"
        )


def from_bits_individual(unitbits: BitVector, unittype: type) -> PyType:
    """
    Function to convert BitVector into a single UnitType-
        a Python numeric/binary/string type, ctype, or YType (bytemaker type).

    Args:
        unitbits (BitVector): The BitVector object to convert to a UnitType
        unittype (type): The type of the UnitType to convert to.
            Must be a member of UnitType
    """

    size_in_bits = count_bits_in_unit_type(unittype)

    if len(unitbits) != size_in_bits:
        raise ValueError(
            f"Cannot convert {unitbits} to {unittype}"
            f" because the number of bits in the bits object ({len(unitbits)})"
            f" does not match the number of bits in the unit type ({size_in_bits})"
        )
    if is_subclass_of_union(unittype, CType):
        return bits_to_ctype(unitbits, unittype)
    elif is_subclass_of_union(unittype, BitType):
        return unittype(bits=unitbits)
    elif is_subclass_of_union(unittype, PyType):
        return bits_to_pytype(unitbits, unittype)
    else:
        raise TypeError(
            f"Cannot convert {unitbits} to {unittype}"
            f" because the unit type is not a CType, YType, or PyType"
        )


def from_bytes_individual(
    unitbytes: bytes,
    unittype: type,
    endianness: Literal["big", "little"] = "big",
) -> PyType:
    """
    Function to convert bytes into a single UnitType-
        a Python numeric/binary/string type, ctype, or YType (bytemaker type).

    Args:
        unitbytes (bytes): The bytes object to convert to a UnitType
        unittype (type): The type of the UnitType to convert to.
            Must be a member of UnitType
        endianness: The byte order of the input bytes.
            Defaults to "big".
    """
    validate_endianness(endianness)

    size_in_bits = count_bits_in_unit_type(unittype)
    if len(unitbytes) * 8 != size_in_bits:
        raise ValueError(
            f"Cannot convert {unitbytes} to {unittype}"
            f" because the number of bits in the bytes object ({len(unitbytes) * 8})"
            f" does not match the number of bits in the unit type ({size_in_bits})"
        )
    if is_subclass_of_union(unittype, CType):
        return bytes_to_ctype(unitbytes, unittype, endianness=endianness)
    elif is_subclass_of_union(unittype, BitType):
        return bytes_to_bittype(unitbytes, unittype, endianness=endianness)
    elif is_subclass_of_union(unittype, PyType):
        return bytes_to_pytype(unitbytes, unittype, endianness=endianness)
    else:
        raise TypeError(
            f"Cannot convert {unitbytes} to {unittype}"
            f" because the unit type is not a CType, YType, or PyType"
        )


AggregateTypeByteConvertible = Union[DataClassType, BitType, CType, PyType, Iterable]


def trycast(obj, type_):
    if not isinstance(obj, type_):
        obj = type_(obj)
    return obj


def to_bits_aggregate(convertible_object: AggregateTypeByteConvertible) -> BitVector:
    """
    Function to convert a BitType, Python primitive, ctypes object, or dataclass\
        of those types into a BitVector.

    Essentially a bitfield serializer.

    Args:
        units (DataClassType | YType | CType | PyType | Iterable):\
            The object to convert to BitVector

    Returns:
        BitVector: The BitVector representation of the object
    """

    ret_bits = BitVector()

    # print("to_bits_aggregate", convertible_object)
    # print("type(units)", type(convertible_object))
    # print("isinstance(units, DataClassType)",
    # isinstance(convertible_object, DataClassType))

    # try:
    if is_instance_of_union(convertible_object, UnitType) and not (
        isinstance(convertible_object, str) and len(convertible_object) > 1
    ):
        ret_bits = to_bits_individual(convertible_object)
    elif isinstance(convertible_object, DataClassType):
        fields = dataclasses.fields(convertible_object)
        resolved_types = resolve_field_types(type(convertible_object))
        field_values = [getattr(convertible_object, field.name) for field in fields]
        field_types = [resolved_types[field.name] for field in fields]
        # print("types", field_types)
        # print("type_is_dataclass", [isinstance(field_type, DataClassType)
        # for field_type in field_types])
        field_values = [
            trycast(field_value, field_type)
            for field_type, field_value in zip(field_types, field_values)
        ]
        field_value_bits = []
        for field_value, field_type in zip(field_values, field_types):
            bitsified = to_bits_aggregate(field_value)
            if isinstance(field_type, type) and issubclass(field_type, str):
                # Option (c): the registered str codec is one fixed-width
                # char (num_bits=8). A multi-char value overflows the
                # declared field width and would fail far from cause on
                # decode, so refuse it at serialize time. Subclass-aware so
                # it matches the layout side (count_bits_in_unit_type maps a
                # str subclass to the same 8-bit codec).
                declared_bits = count_bits_in_unit_type(str)
                if len(bitsified) != declared_bits:
                    raise ValueError(
                        f"Cannot serialize {field_value!r} into a str field:"
                        f" it occupies {len(bitsified)} bits but a str field"
                        f" is one fixed-width character ({declared_bits} bits)."
                    )
            field_value_bits.append(bitsified)
        ret_bits = BitVector().join(field_value_bits)
    elif isinstance(convertible_object, Iterable):
        for unit in convertible_object:
            ret_bits.extend(to_bits_aggregate(unit))
    else:
        raise TypeError(
            f"Cannot convert {convertible_object} to bits because the unit type"
            f" is not a CType, YType, or PyType"
        )
    # except Exception as e:
    #     raise Exception(f"Cannot convert {convertible_object} to bits.\n
    #                     f"Next-level error: {e}") from e

    return ret_bits


def from_bits_aggregate(
    unitbits: BitVector, aggregate_type: type
) -> Union[UnitType, AggregateTypeByteConvertible]:
    """
    Function to convert a collection of BitVector objects into Python primitives,\
        ctypes objects, BitTypes, or a dataclass of those types.

    Essentially a bitfield deserializer.

    Args:
        unitbits (BitVector): The BitVector object to convert to a Python primitive,\
            ctypes object, BitType, or dataclass.
        aggregate_type (type): The type(s) of the object to convert to.
            Must be a member of UnitType or a dataclass annotated with UnitType members.

    Returns:
        Union[UnitType, AggregateTypeByteConvertible]: The object(s)
            represented by the bits.
    """
    if is_subclass_of_union(aggregate_type, UnitType):
        return from_bits_individual(unitbits, aggregate_type)
    else:
        size_in_bits = count_bits_in_aggregate_type(aggregate_type)
        # print("unitbits type", type(unitbits))
        # print(unitbits)
        if len(unitbits) != size_in_bits:
            raise ValueError(
                f"Cannot convert {unitbits} to {aggregate_type}"
                f" because the number of bits in the bits object ({len(unitbits)})"
                f" does not match the number of bits in the unit type ({size_in_bits})"
            )

        read_fields = list()
        field_types = resolve_field_types(aggregate_type)
        for field in dataclasses.fields(aggregate_type):
            field_type = field_types[field.name]

            field_size_in_bits = count_bits_in_unit_type(field_type)
            field_bits = unitbits[:field_size_in_bits]
            field_value = from_bits_aggregate(field_bits, field_type)
            read_fields.append(field_value)
            unitbits = unitbits[field_size_in_bits:]
        retval = aggregate_type(*read_fields)

    return retval


def to_bytes_aggregate(
    units: AggregateTypeByteConvertible,
    endianness: Literal["big", "little"] = "big",
) -> bytes:
    """
    Function to convert a collection of Python primitives or ctypes objects into bytes.

    Essentially a bitfield serializer.

    Args:
        units [Iterable | DataClassType]): The objects to convert to bytes
        endianness: The byte order of the output.
            Defaults to "big".

    Returns:
        bytes: The bytes representation of the objects
    """
    validate_endianness(endianness)
    ret_bytes = bytearray()

    if is_instance_of_union(units, UnitType) and not (
        isinstance(units, str) and len(units) > 1
    ):
        ret_bytes = to_bytes_individual(units, endianness=endianness)

    elif isinstance(units, DataClassType):
        field_types = resolve_field_types(type(units))
        for field in dataclasses.fields(units):
            field_type = field_types[field.name]
            field_value = getattr(units, field.name)
            field_value = trycast(field_value, field_type)
            field_value_bytes = to_bytes_aggregate(field_value, endianness=endianness)
            if isinstance(field_type, type) and issubclass(field_type, str):
                # Option (c): a str field is one fixed-width char (8 bits);
                # a multi-char value overflows the declared width, so refuse
                # it at serialize time (matches the bits path, subclass-aware).
                declared_bits = count_bits_in_unit_type(str)
                if len(field_value_bytes) * 8 != declared_bits:
                    raise ValueError(
                        f"Cannot serialize {field_value!r} into a str field:"
                        f" it occupies {len(field_value_bytes) * 8} bits but a"
                        f" str field is one fixed-width character"
                        f" ({declared_bits} bits)."
                    )
            ret_bytes.extend(field_value_bytes)

    elif isinstance(units, Iterable):
        for unit in units:
            ret_bytes.extend(to_bytes_aggregate(unit, endianness=endianness))

    else:
        raise TypeError(
            f"Cannot convert {units} to bytes because the unit type"
            f" is not a CType, YType, or PyType"
        )

    return bytes(ret_bytes)


def from_bytes_aggregate(
    bytes_obj: bytes,
    aggregate_type: type,
    is_array=False,
    endianness: Literal["big", "little"] = "big",
) -> Union[UnitType, AggregateTypeByteConvertible]:
    """
    Convert a collection of bytes into Python primitives, ctypes objects,
    BitTypes, or a dataclass of those types.

    This is essentially a bitfield deserializer.

    Args:
        bytes_obj (bytes): The bytes object to convert to a Python primitive,
            ctypes object, BitType, or dataclass.
        aggregate_type (type): The type(s) of the object to convert to. It
            must be a member of UnitType, or a dataclass annotated with
            UnitType members.
        is_array (bool, optional): Whether ``bytes_obj`` holds consecutive
            entries of ``aggregate_type``. If it does, a ``list`` of decoded
            entries is returned. Defaults to False.
        endianness: The byte order of the input bytes. Defaults to "big".

    Returns:
        Union[UnitType, AggregateTypeByteConvertible]: The object(s) represented by
            the bytes.
    """
    validate_endianness(endianness)
    if is_array:
        size_in_bits = count_bits_in_aggregate_type(aggregate_type)
        size_in_bytes = (size_in_bits + 7) // 8
        arr_entry_list = list()
        for i in range(0, len(bytes_obj), size_in_bytes):
            arr_entry_list.append(
                from_bytes_aggregate(
                    bytes_obj[i : i + size_in_bytes],
                    aggregate_type,
                    endianness=endianness,
                )
            )
        return arr_entry_list

    if is_subclass_of_union(aggregate_type, UnitType):
        return from_bytes_individual(bytes_obj, aggregate_type, endianness=endianness)
    else:
        size_in_bits = count_bits_in_unit_type(aggregate_type)

        if len(bytes_obj) * 8 != size_in_bits:
            raise ValueError(
                f"Cannot convert {bytes_obj} to {aggregate_type}"
                f" because the # of bits in the bytes object ({len(bytes_obj) * 8})"
                f" does not match the # of bits in the unit type ({size_in_bits})"
            )

        read_fields = list()
        field_types = resolve_field_types(aggregate_type)
        for field in dataclasses.fields(aggregate_type):
            field_type = field_types[field.name]
            field_size_in_bytes = (count_bits_in_unit_type(field_type) + 7) // 8
            field_bytes = bytes_obj[:field_size_in_bytes]
            field_value = from_bytes_aggregate(
                field_bytes, field_type, endianness=endianness
            )
            read_fields.append(field_value)
            bytes_obj = bytes_obj[field_size_in_bytes:]
        retval = aggregate_type(*read_fields)

    return retval
