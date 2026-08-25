# CType Handling
import ctypes
import sys
from ctypes import Array, Structure, Union, _SimpleCData

import bytemaker.typing_redirect as typing_redirect
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Literal
from bytemaker.utils import (
    is_instance_of_union,
    is_subclass_of_union,
    validate_endianness,
)

CType = typing_redirect.Union[_SimpleCData, Structure, Union, Array]


def _reversed_ctype_bytes(ctype_type: type, raw: bytes, path: str) -> bytes:
    """
    Computes the byte-order-reversed serialization of a ctypes value from
    its native-order bytes, without touching any ctypes instance.

    Scalars are byte-reversed whole. Arrays are reversed element by element.
    Structures are reversed field by field, and their padding bytes pass
    through unchanged.

    A multi-byte Union raises ``NotImplementedError``. Its active member is
    unknowable, so a byte-order swap would be silently wrong. A single-byte
    Union is its own reverse and passes through.

    Args:
        ctype_type (type): The ctypes type that describes ``raw``.
        raw (bytes): The native-order bytes of the value.
        path (str): Dotted path from the root object, used in error messages.

    Returns:
        bytes: The reversed-endianness bytes.

    Raises:
        NotImplementedError: If a Structure reached by the reversal declares
            bitfields (3-tuple ``_fields_`` entries), or a multi-byte Union
            is reached (its active member is unknowable).
    """
    if issubclass(ctype_type, _SimpleCData):
        return raw[::-1]

    if issubclass(ctype_type, Array):
        elem_type = ctype_type._type_
        elem_size = ctypes.sizeof(elem_type)
        if elem_size == 0:  # array of zero-sized elements: nothing to reverse
            return raw
        return b"".join(
            _reversed_ctype_bytes(
                elem_type,
                raw[offset : offset + elem_size],
                f"{path}[{offset // elem_size}]",
            )
            for offset in range(0, len(raw), elem_size)
        )

    if issubclass(ctype_type, Structure):
        out = bytearray(raw)  # padding bytes pass through unchanged
        for field in ctype_type._fields_:
            field_name, field_type = field[0], field[1]
            field_path = f"{path}.{field_name}" if path else field_name
            if len(field) > 2:
                raise NotImplementedError(
                    f"Cannot reverse the endianness of"
                    f" {ctype_type.__name__!r}: field {field_path!r}"
                    f" is a bitfield (3-tuple entry in _fields_), and"
                    f" ctypes bitfield storage cannot be reversed per-field."
                )
            offset = getattr(ctype_type, field_name).offset
            size = ctypes.sizeof(field_type)
            out[offset : offset + size] = _reversed_ctype_bytes(
                field_type, raw[offset : offset + size], field_path
            )
        return bytes(out)

    if issubclass(ctype_type, Union):
        # DEVIATION (maintainer ruling): a Union's active member is
        # unknowable, so a byte-order swap cannot be applied per member.
        # This helper only runs when a swap is actually required
        # (endianness != sys.byteorder). A single-byte Union is its own
        # reverse (no swap needed); a multi-byte one would be silently
        # wrong, so refuse rather than emit corrupt bytes. (The proposed
        # patch passed Union bytes through unchanged; this raises instead.)
        if ctypes.sizeof(ctype_type) > 1:
            raise NotImplementedError(
                f"Cannot reverse the endianness of {ctype_type.__name__!r}:"
                f" it is a {ctypes.sizeof(ctype_type)}-byte Union whose active"
                f" member is unknowable, so a byte-order swap would be"
                f" silently wrong. Serialize it in native byte order"
                f" (endianness == sys.byteorder)."
            )
        return raw

    return raw  # any other CType: pass through


def reverse_ctype_endianness(ctype_instance: CType) -> CType:
    """
    Returns a copy of a ctypes object with the endianness reversed.

    The input object is never modified. The reversal is computed on the
    object's serialized bytes, then materialized into a fresh instance with
    ``from_buffer_copy``.

    Nested Structures are reversed field by field, and Arrays element by
    element, including arrays of multi-byte scalars. Combinations of the two
    are reversed the same way. A multi-byte Union raises
    ``NotImplementedError`` because the active member is unknowable.

    Args:
        ctype_instance (ctypes._SimpleCData | ctypes.Structure |
                ctypes.Union | ctypes.Array):
            The ctypes object to reverse the endianness of.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            A new ctypes object of the same type with the endianness
            reversed.

    Raises:
        NotImplementedError: If a Structure reached by the reversal declares
            bitfields, or a multi-byte Union is reached.
    """
    ctype_type = type(ctype_instance)
    reversed_raw = _reversed_ctype_bytes(ctype_type, bytes(ctype_instance), "")
    return ctype_type.from_buffer_copy(reversed_raw)


def ctype_to_bytes(
    ctype_obj: CType, endianness: Literal["big", "little"] = "big"
) -> bytes:
    """
    Function to convert ctypes into bytes objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure |
                ctypes.Union | ctypes.Array):
            The ctypes object to convert to bytes
        endianness: The byte order of the output.
            Defaults to "big".

    Returns:
        bytes: The bytes representation of the ctypes object
    """
    validate_endianness(endianness)
    if not is_instance_of_union(ctype_obj, CType):  # type: ignore
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f" Union, and Array objects, not {type(ctype_obj)}."
        )

    if endianness != sys.byteorder:
        return _reversed_ctype_bytes(type(ctype_obj), bytes(ctype_obj), "")

    return bytes(ctype_obj)


def ctype_to_bits(
    ctype_obj: CType, endianness: Literal["big", "little"] = "big"
) -> BitVector:
    """
    Function to convert ctypes into BitVector objects

    Args:
        ctype_obj (ctypes._SimpleCData | ctypes.Structure\
                | ctypes.Union | ctypes.Array):
            The ctypes object to convert to BitVector
        endianness: The byte order to use.
            Defaults to "big".

    Returns:
        BitVector: The BitVector representation of the ctypes object
    """
    return BitVector(ctype_to_bytes(ctype_obj, endianness=endianness))


def bytes_to_ctype(
    bytes_obj: bytes,
    ctype_type: type,
    endianness: Literal["big", "little"] = "big",
) -> CType:
    """
    Function to convert bytes into ctypes objects

    Args:
        bytes_obj (bytes): The bytes object to convert to a ctypes object
        ctype_type (type): The type of the ctypes object to convert to.
            Must be a member of CType
        endianness: The byte order of the input bytes.
            Defaults to "big".

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            The ctypes object representation of the bytes
    """

    validate_endianness(endianness)
    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure,"
            f" Union, and Array types, not {ctype_type}."
        )

    if endianness != sys.byteorder:
        bytes_obj = _reversed_ctype_bytes(ctype_type, bytes(bytes_obj), "")

    return ctype_type.from_buffer_copy(bytes_obj)


def bits_to_ctype(
    bits_obj: BitVector,
    ctype_type: type,
    endianness: Literal["big", "little"] = "big",
) -> CType:
    """
    Function to convert bits into ctypes objects

    Args:
        bits_obj (BitVector): The bits object to convert to a ctypes object
        ctype_type (type): The type of the ctypes object to convert to.
            Must be a member of CType
        endianness: The byte order to use.
            Defaults to "big".

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            The ctypes object representation of the bits
    """
    return bytes_to_ctype(bits_obj.to_bytes(), ctype_type, endianness=endianness)
