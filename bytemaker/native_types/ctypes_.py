# CType Handling
from ctypes import _SimpleCData, Structure, Union, Array
import typing
from bytemaker.utils import is_instance_of_union, is_subclass_of_union
from bytemaker.bits import Bits


CType = typing.Union[_SimpleCData, Structure, Union, Array]


def ctype_to_bytes(ctype_obj: CType, reverse_endianness=False) -> bytes:
    """
    Function to convert ctypes into bytes objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array):
            The ctypes object to convert to bytes
        reverse_endianness (bool, optional):
            Whether to reverse the endianness of the bytes after converting. Defaults to False.

    Returns:
        bytes: The bytes representation of the ctypes object
    """
    if not is_instance_of_union(ctype_obj, CType):
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure, Union, and Array objects, not {type(ctype_obj)}"
        )

    retbytes = bytes(ctype_obj)
    if reverse_endianness:
        retbytes = retbytes[::-1]

    return retbytes


def ctype_to_bits(ctype_obj: CType, reverse_endianness=False) -> Bits:
    """
    Function to convert ctypes into Bits objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array):
            The ctypes object to convert to Bits
        reverse_endianness (bool, optional):
            Whether to reverse the endianness of the Bits after converting. Defaults to False.

    Returns:
        Bits: The Bits representation of the ctypes object
    """
    return Bits(ctype_to_bytes(ctype_obj, reverse_endianness=reverse_endianness))


def bytes_to_ctype(bytes_obj: bytes,
                   ctype_type: type,
                   reverse_endianness=False) -> CType:
    """
    Function to convert bytes into ctypes objects

    Args:
        bytes_obj (bytes): The bytes object to convert to a ctypes object
        ctype_type (type): The type of the ctypes object to convert to.
            Must be a member of CType
        reverse_endianness (bool, optional): Whether to reverse the endianness
            of the bytes before converting. Defaults to False.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            The ctypes object representation of the bytes
    """

    if reverse_endianness:
        bytes_obj = bytes_obj[::-1]

    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure, Union, and Array types, not {ctype_type}"
        )
    return ctype_type.from_buffer_copy(bytes_obj)


def bits_to_ctype(
        bits_obj: Bits,
        ctype_type: type,
        reverse_endianness=False) -> CType:
    """
    Function to convert bits into ctypes objects

    Args:
        bits_obj (Bits): The bits object to convert to a ctypes object
        ctype_type (type): The type of the ctypes object to convert to.
            Must be a member of CType
        reverse_endianness (bool, optional): Whether to reverse the endianness
            of the bits before converting. Defaults to False.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            The ctypes object representation of the bits
    """
    return bytes_to_ctype(bits_obj.to_bytes(), ctype_type, reverse_endianness=reverse_endianness)
