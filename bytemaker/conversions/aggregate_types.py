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
from bytemaker.typing_redirect import Iterable, Union
from bytemaker.utils import DataClassType, is_instance_of_union, is_subclass_of_union

UnitType = Union[CType, BitType, PyType]

# CType is a Union of _SimpleCData, Structure, Union, and Array
# YType is a Union of YInt, YFloat, YString, YBytes, YBool, YEnum, YArray, and YStruct
# PyType is a Union of int, float, str, bytes, bool, and Enum


def count_bits_in_unit_type(unit_type: UnitType) -> int:
    """
    Function to count the number of bits in a UnitType-\
        a Python, type, ctype, or BitType (bytemaker type).
    """

    # print("Counting bits in unit type", unit_type)
    if is_subclass_of_union(unit_type, CType):
        return ctypes.sizeof(unit_type) * 8
    elif is_subclass_of_union(unit_type, BitType):
        return unit_type.num_bits
    elif is_subclass_of_union(unit_type, PyType):
        # print(ConversionConfig.get_conversion_info(unit_type).num_bits)
        return ConversionConfig.get_conversion_info(unit_type).num_bits("")
    elif is_subclass_of_union(unit_type, DataClassType):
        size_in_bits = 0
        for field in dataclasses.fields(unit_type):
            field_type = field.type
            if isinstance(field_type, str):
                field_type = eval(field_type)
            size_in_bits += count_bits_in_unit_type(field_type)
        return size_in_bits


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
        for field in dataclasses.fields(aggregate_type):
            field_type = field.type
            if isinstance(field_type, str):
                field_type = eval(field_type)
            size_in_bits += count_bits_in_unit_type(field_type)
        return size_in_bits


def count_bytes_in_unit_type(unit_type: UnitType) -> int:
    """
    Function to count the number of bytes in a UnitType-
        a Python numeric/binary/string type, ctype, or BitType (bytemaker type).
    """
    return (count_bits_in_unit_type(unit_type) + 1) // 8


def to_bits_individual(unit: UnitType) -> BitVector:
    """
    Function to convert a single Python primitive or ctypes object into BitVector.
    """
    if is_instance_of_union(unit, CType):
        return ctype_to_bits(unit)
    elif isinstance(unit, BitType):
        return unit.to_bits()
    elif is_instance_of_union(unit, PyType):
        return pytype_to_bits(unit)
    else:
        raise Exception(
            f"Cannot convert {unit} to bits because"
            f" the unit type is not a CType, YType, or PyType"
        )


def to_bytes_individual(unit: UnitType, reverse_endianness: bool = False) -> bytes:
    """
    Function to convert a single Python primitive or ctypes object into bytes.
    """

    if is_instance_of_union(unit, CType):
        return ctype_to_bytes(unit, reverse_endianness=reverse_endianness)
    elif isinstance(unit, BitType):
        return unit.to_bytes(reverse_endianness=reverse_endianness)
    elif is_instance_of_union(unit, PyType):
        return pytype_to_bytes(unit, reverse_endianness=reverse_endianness)
    else:
        raise Exception(
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
        raise Exception(
            f"Cannot convert {unitbits} to {unittype}"
            f" because the number of bits in the bits object ({unitbits.num_bits})"
            f" does not match the number of bits in the unit type ({size_in_bits})"
        )
    if is_subclass_of_union(unittype, CType):
        return bits_to_ctype(unitbits, unittype)
    elif is_subclass_of_union(unittype, BitType):
        return unittype.from_bits(unitbits)
    elif is_subclass_of_union(unittype, PyType):
        return bits_to_pytype(unitbits, unittype)
    else:
        raise Exception(
            f"Cannot convert {unitbits} to {unittype}"
            f" because the unit type is not a CType, YType, or PyType"
        )


def from_bytes_individual(
    unitbytes: bytes, unittype: type, reverse_endianness: bool = False
) -> PyType:
    """
    Function to convert bytes into a single UnitType-
        a Python numeric/binary/string type, ctype, or YType (bytemaker type).

    Args:
        unitbytes (bytes): The bytes object to convert to a UnitType
        unittype (type): The type of the UnitType to convert to.
            Must be a member of UnitType
        reverse_endianness (bool, optional): Whether to reverse the endianness of
            the bytes before converting. Defaults to False.
    """

    size_in_bits = count_bits_in_unit_type(unittype)
    if len(unitbytes) * 8 != size_in_bits:
        raise Exception(
            f"Cannot convert {unitbytes} to {unittype}"
            f" because the number of bits in the bytes object ({len(unitbytes) * 8})"
            f" does not match the number of bits in the unit type ({size_in_bits})"
        )
    if is_subclass_of_union(unittype, CType):
        return bytes_to_ctype(
            unitbytes, unittype, reverse_endianness=reverse_endianness
        )
    elif is_subclass_of_union(unittype, BitType):
        return bytes_to_bittype(
            unitbytes, unittype, reverse_endianness=reverse_endianness
        )
    elif is_subclass_of_union(unittype, PyType):
        return bytes_to_pytype(
            unitbytes, unittype, reverse_endianness=reverse_endianness
        )
    else:
        raise Exception(
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
        field_values = [getattr(convertible_object, field.name) for field in fields]
        field_types = [
            field.type if not isinstance(field.type, str) else eval(field.type)
            for field in fields
        ]
        # print("types", field_types)
        # print("type_is_dataclass", [isinstance(field_type, DataClassType)
        # for field_type in field_types])
        field_values = [
            trycast(field_value, field_type)
            for field_type, field_value in zip(field_types, field_values)
        ]
        field_value_bits = []
        for field_value in field_values:
            bitsified = to_bits_aggregate(field_value)
            field_value_bits.append(bitsified)
        # field_value_bits = [to_bits_aggregate(field_value)
        # for field_value in field_values]
        ret_bits = BitVector().join(field_value_bits)
    elif isinstance(convertible_object, Iterable):
        for unit in convertible_object:
            ret_bits.extend(to_bits_aggregate(unit))
    else:
        raise Exception(
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
            raise Exception(
                f"Cannot convert {unitbits} to {aggregate_type}"
                f" because the number of bits in the bits object ({unitbits.num_bits})"
                f" does not match the number of bits in the unit type ({size_in_bits})"
            )

        read_fields = list()
        for field in dataclasses.fields(aggregate_type):
            field_type = field.type
            if isinstance(field.type, str):
                field_type = eval(field.type)

            field_size_in_bits = count_bits_in_unit_type(field_type)
            field_bits = unitbits[:field_size_in_bits]
            field_value = from_bits_aggregate(field_bits, field_type)
            read_fields.append(field_value)
            unitbits = unitbits[field_size_in_bits:]
        retval = aggregate_type(*read_fields)

    return retval


def to_bytes_aggregate(
    units: AggregateTypeByteConvertible, reverse_endianness: bool = False
) -> bytes:
    """
    Function to convert a collection of Python primitives or ctypes objects into bytes.

    Essentially a bitfield serializer.

    Args:
        units [Iterable | DataClassType]): The objects to convert to bytes

    Returns:
        bytes: The bytes representation of the objects
    """
    ret_bytes = bytearray()

    if is_instance_of_union(units, UnitType):
        # print("Is unit", type(units))
        ret_bytes = to_bytes_individual(units, reverse_endianness=reverse_endianness)

    elif isinstance(units, DataClassType):
        # print("Is dataclass", type(units))

        for field in dataclasses.fields(units):
            field_type = field.type
            if isinstance(field.type, str):
                field_type = eval(field_type)
            field_value = getattr(units, field.name)
            # print(field_type)
            field_value = field_type(field_value)
            # print("-----")
            try:
                field_value = field_type(field_value)
            except TypeError:
                # print("Couldn't get field value")
                pass
            # print(field)
            # print(field_value)
            # print(field_type)
            # print(type(field_value))
            # print("-----")
            field_value_bytes = to_bytes_aggregate(
                field_value, reverse_endianness=reverse_endianness
            )
            # print(field_value_bytes)

            ret_bytes.extend(field_value_bytes)

    elif isinstance(units, Iterable):
        # print("Is iterable")
        # print("Units:", units)
        for unit in units:
            # print(unit)
            ret_bytes.extend(
                to_bytes_aggregate(unit, reverse_endianness=reverse_endianness)
            )

    return bytes(ret_bytes)


def from_bytes_aggregate(
    bytes_obj: bytes,
    aggregate_type: type,
    is_array=False,
    reverse_endianness: bool = False,
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
        is_array (bool, optional): Whether the object is an array of the aggregate type.
            Defaults to False.
        reverse_endianness (bool, optional): Whether to reverse the endianness of the
            bytes before converting. Defaults to False.

    Returns:
        Union[UnitType, AggregateTypeByteConvertible]: The object(s) represented by
            the bytes.
    """
    if reverse_endianness:
        bytes_obj = bytes_obj[::-1]

    if is_subclass_of_union(aggregate_type, UnitType):
        return from_bytes_individual(
            bytes_obj, aggregate_type, reverse_endianness=reverse_endianness
        )
    else:
        size_in_bits = count_bits_in_unit_type(aggregate_type)

        if not is_array:
            if len(bytes_obj) * 8 != size_in_bits:
                raise Exception(
                    f"Cannot convert {bytes_obj} to {aggregate_type}"
                    f" because the # of bits in the bytes object ({len(bytes_obj) * 8})"
                    f" does not match the # of bits in the unit type ({size_in_bits})"
                )

            read_fields = list()
            for field in dataclasses.fields(aggregate_type):
                if isinstance(field.type, str):
                    field_type = eval(field.type)
                field_size_in_bits = count_bits_in_unit_type(field_type)
                field_bytes = bytes_obj[:field_size_in_bits]
                field_value = from_bytes_aggregate(
                    field_bytes, field_type, reverse_endianness=reverse_endianness
                )
                read_fields.append(field_value)
                bytes_obj = bytes_obj[field_size_in_bits:]
            retval = aggregate_type(*read_fields)

        else:
            arr_entry_list = list()
            for i in range(0, len(bytes_obj), size_in_bits):
                endindex = (
                    i + size_in_bits
                    if i + size_in_bits < len(bytes_obj)
                    else len(bytes_obj)
                )
                arr_entry_list.append(
                    from_bytes_aggregate(
                        bytes_obj[i:endindex],
                        aggregate_type,
                        reverse_endianness=reverse_endianness,
                    )
                )
            retval = aggregate_type(*arr_entry_list)

    return retval
