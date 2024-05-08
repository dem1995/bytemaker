# CType Handling
import ctypes
from ctypes import Array, Structure, Union, _SimpleCData

from bytemaker.bits import Bits
from bytemaker.utils import is_instance_of_union, is_subclass_of_union
import bytemaker.typing_redirect as typing_redirect

CType = typing_redirect.Union[_SimpleCData, Structure, Union, Array]


def reverse_bytes_unit(unit: _SimpleCData):
    """Reverse the byte order of the given value."""
    unit_type = type(unit)
    bytes_value = bytearray(unit)
    bytes_value.reverse()
    return unit_type.from_buffer_copy(bytes_value)


def reverse_ctype_endianness(ctype_instance: CType) -> None:
    """Process each field of the structure."""

    if isinstance(ctype_instance, _SimpleCData):
        # Reverse the byte order for single, multi-byte objects
        byte_size = ctypes.sizeof(ctype_instance)
        if byte_size > 1:
            ctype_instance = reverse_bytes_unit(ctype_instance)

    if isinstance(ctype_instance, Array):
        for i in range(len(ctype_instance)):
            ctype_instance[i] = reverse_ctype_endianness(ctype_instance[i])

    if isinstance(ctype_instance, Structure):
        for field_name, field_type in ctype_instance._fields_:
            field_value = getattr(ctype_instance, field_name)
            # print(field_name, field_value, type(field_value))
            reversed_unit = reverse_ctype_endianness(field_type(field_value))
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
    if not is_instance_of_union(ctype_obj, CType):
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f"Union, and Array objects, not {type(ctype_obj)}."
        )

    if reverse_endianness:
        ctype_obj = reverse_ctype_endianness(ctype_obj)

    retbytes = bytes(ctype_obj)

    return retbytes


def ctype_to_bits(ctype_obj: CType, reverse_endianness=True) -> Bits:
    """
    Function to convert ctypes into Bits objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure\
                | ctypes.Union | ctypes.Array):
            The ctypes object to convert to Bits
        reverse_endianness (bool, optional):
            Whether to reverse the endianness of the Bits\
                after converting. Defaults to False.

    Returns:
        Bits: The Bits representation of the ctypes object
    """
    return Bits(ctype_to_bytes(ctype_obj, reverse_endianness=reverse_endianness))


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


def bits_to_ctype(bits_obj: Bits, ctype_type: type, reverse_endianness=True) -> CType:
    """
    Function to convert bits into ctypes objects

    Args:
        bits_obj (Bits): The bits object to convert to a ctypes object
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
