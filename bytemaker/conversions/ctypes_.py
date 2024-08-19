# CType Handling
import ctypes
from ctypes import Array, Structure, Union, _SimpleCData

import bytemaker.typing_redirect as typing_redirect
from bytemaker.bitvector import BitVector
from bytemaker.utils import is_instance_of_union, is_subclass_of_union

CType = typing_redirect.Union[_SimpleCData, Structure, Union, Array]


def reverse_bytes_unit(unit: _SimpleCData):
    """
    Reverses the byte order of a ctypes object.

    Args:
        unit (_SimpleCData): The ctypes object to reverse the byte order of.

    Returns:
        _SimpleCData: The ctypes object with the byte order reversed.
    """
    unit_type = type(unit)
    bytes_value = bytearray(unit)
    bytes_value.reverse()
    return unit_type.from_buffer_copy(bytes_value)


def reverse_ctype_endianness(ctype_instance: CType) -> CType:
    """
    Reverses the endianness of a ctypes object.

    Args:
        ctype_instance (ctypes._SimpleCData | ctypes.Structure |
                ctypes.Union | ctypes.Array):
            The ctypes object to reverse the endianness of.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            The ctypes object with the endianness reversed.
    """

    if isinstance(ctype_instance, _SimpleCData):
        # Reverse the byte order for single, multi-byte objects
        byte_size = ctypes.sizeof(ctype_instance)
        if byte_size > 1:
            ctype_instance = reverse_bytes_unit(ctype_instance)

    if isinstance(ctype_instance, Array):
        for i in range(len(ctype_instance)):
            ctype_instance[i] = reverse_ctype_endianness(ctype_instance[i])

    if isinstance(ctype_instance, Structure):
        ctype_instance_fields = list(ctype_instance._fields_)
        if len(ctype_instance_fields) > 0 and len(ctype_instance_fields[0]) > 2:
            raise NotImplementedError(
                "ctype structures with _fields_ with more than 2 elements are"
                "not supported."
                f"Ctype instance: {ctype_instance}"
                f"Ctype instance fields: {ctype_instance_fields}"
            )
        for field_name, field_type in ctype_instance_fields:  # type: ignore
            field_value = getattr(ctype_instance, field_name)
            # print(field_name, field_value, type(field_value))
            simple_c_data = field_type(field_value)  # type: ignore[reportCallIssue]
            assert isinstance(simple_c_data, _SimpleCData)
            reversed_unit = reverse_ctype_endianness(simple_c_data)
            setattr(ctype_instance, field_name, reversed_unit)

    return ctype_instance


def ctype_to_bytes(ctype_obj: CType, reverse_endianness=True) -> bytes:
    """
    Function to convert ctypes into bytes objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure |
                ctypes.Union | ctypes.Array):
            The ctypes object to convert to bytes
        reverse_endianness (bool, optional):
            Whether to reverse the endianness of the bytes after
                converting. Defaults to False.

    Returns:
        bytes: The bytes representation of the ctypes object
    """
    if not is_instance_of_union(ctype_obj, CType):  # type: ignore
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f"Union, and Array objects, not {type(ctype_obj)}."
        )

    if reverse_endianness:
        ctype_obj = reverse_ctype_endianness(ctype_obj)

    retbytes = bytes(ctype_obj)

    return retbytes


def ctype_to_bits(ctype_obj: CType, reverse_endianness=True) -> BitVector:
    """
    Function to convert ctypes into BitVector objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure\
                | ctypes.Union | ctypes.Array):
            The ctypes object to convert to BitVector
        reverse_endianness (bool, optional):
            Whether to reverse the endianness of the BitVector\
                after converting. Defaults to False.

    Returns:
        BitVector: The BitVector representation of the ctypes object
    """
    return BitVector(ctype_to_bytes(ctype_obj, reverse_endianness=reverse_endianness))


def bytes_to_ctype(
    bytes_obj: bytes, ctype_type: type, reverse_endianness=True
) -> CType:
    """
    Function to convert bytes into ctypes objects

    Args:
        bytes_obj (bytes): The bytes object to convert to a ctypes object
        ctype_type (type): The type of the ctypes object to convert to.
            Must be a member of CType
        reverse_endianness (bool, optional): Whether to reverse the
            endianness of the bytes before converting. Defaults to False.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union
            | ctypes.Array:
            The ctypes object representation of the bytes
    """

    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure,"
            f"Union, and Array types, not {ctype_type}."
        )

    ctype_obj = ctype_type.from_buffer_copy(bytes_obj)
    if reverse_endianness:
        ctype_obj = reverse_ctype_endianness(ctype_obj)

    return ctype_obj


def bits_to_ctype(
    bits_obj: BitVector, ctype_type: type, reverse_endianness=True
) -> CType:
    """
    Function to convert bits into ctypes objects

    Args:
        bits_obj (BitVector): The bits object to convert to a ctypes object
        ctype_type (type): The type of the ctypes object to convert to.
            Must be a member of CType
        reverse_endianness (bool, optional): Whether to reverse the
            endianness of the bits before converting. Defaults to False.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union
            | ctypes.Array:
            The ctypes object representation of the bits
    """
    return bytes_to_ctype(
        bits_obj.to_bytes(), ctype_type, reverse_endianness=reverse_endianness
    )
