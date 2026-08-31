from __future__ import annotations

import struct
from dataclasses import dataclass

from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Any, Callable, Literal
from bytemaker.utils import is_subclass_of_union, validate_endianness


class PyTypeMeta(type):
    """
    This is used to create IsByteConvertible, a type to allow checking\
        whether an object or instances of a class can be converted to a\
        bytes object using isinstance or issubclass.
    """

    def __instancecheck__(self, __instance) -> bool:
        return ConversionConfig.has_suitable_conversion(type(__instance))

    def __subclasscheck__(self, __subclass: type) -> bool:
        return ConversionConfig.has_suitable_conversion(__subclass)


class PyType(metaclass=PyTypeMeta):
    pass


# PyType Handling
@dataclass
class ConversionInfo:
    """
    Class to store information about conversions between Python primitives and\
        BitVectors.

    Attributes:
    -----------
    pytype : type
        The Python type to convert to/from BitVectors
    to_bits : Callable[[Any], BitVector]
        Function to convert a Python instance of the type to a BitVector
    from_bits : Callable[[BitVector], Any]
        Function to convert a BitVector to a Python instance of the type
    num_bits : Callable[[Any], int]
        The number of bits in the BitVector representation of the Python instance
    """

    pytype: type
    to_bits: Callable[[Any], BitVector]
    from_bits: Callable[[BitVector], Any]
    num_bits: Callable[[Any], int]


class ConversionConfig:
    """
    Class to configure conversions for Python primitives.
    """

    _implemented_conversions: dict[type, ConversionInfo] = {}
    _known_furthest_descendant_mappings: dict[type, type] = {}
    _has_a_suitable_conversion: dict[type, bool] = {}

    @classmethod
    def set_conversion_info(cls, conversion_info: ConversionInfo):
        # # If the conversion info pytype is an exact match for an
        # # already-mapped type,
        # #   replace any prior mappings to superclasses for that
        # # pytype with the new conversion
        # if conversion_info.pytype in cls._implemented_conversions:
        #     cls._known_furthest_descendant_mappings[conversion_info.pytype] =
        #   conversion_info.pytype

        # If the conversion info pytype is a stricter subclass of an
        #   already-mapped type,
        #   replace the mapping for the superclass with the new conversion
        for key, value in cls._known_furthest_descendant_mappings.items():
            could_map_key_to_conv_pytype_conversion = is_subclass_of_union(
                key, conversion_info.pytype
            )
            conv_pytype_is_stricter_match_than_existing = is_subclass_of_union(
                conversion_info.pytype, value
            )
            if (
                could_map_key_to_conv_pytype_conversion
                and conv_pytype_is_stricter_match_than_existing
            ):
                cls._known_furthest_descendant_mappings[key] = conversion_info.pytype

        # Set the conversion info
        cls._implemented_conversions[conversion_info.pytype] = conversion_info
        cls._known_furthest_descendant_mappings[conversion_info.pytype] = (
            conversion_info.pytype
        )
        cls._has_a_suitable_conversion[conversion_info.pytype] = True

        # Check types previously ascertained to have no suitable conversion
        #  if this new version involves a superclass of that type,
        #   set this new conversion type
        #  as the furthest descendant mapping for that type and flag
        #   that type as a suitable conversion
        types_known_to_not_have_suitable_conversion = [
            pytype
            for pytype, has_suitable_conv in cls._has_a_suitable_conversion.items()
            if not has_suitable_conv
        ]

        for pytype in types_known_to_not_have_suitable_conversion:
            if is_subclass_of_union(conversion_info.pytype, pytype):
                cls._known_furthest_descendant_mappings[pytype] = conversion_info.pytype
                cls._has_a_suitable_conversion[pytype] = True

    @classmethod
    def has_suitable_conversion(cls, pytype: type) -> bool:
        if pytype in cls._has_a_suitable_conversion:
            return cls._has_a_suitable_conversion[pytype]
        else:
            for implemented_pytype in cls._implemented_conversions.keys():
                if is_subclass_of_union(pytype, implemented_pytype):
                    cls._has_a_suitable_conversion[pytype] = True
                    return True
        return False

    @classmethod
    def get_conversion_info(cls, pytype: type) -> ConversionInfo:
        # If the pytype is an exact match for a conversion,
        # return that conversion
        if pytype in cls._implemented_conversions:
            return cls._implemented_conversions[pytype]

        # If the pytype is a known subclass of a conversion,
        # return the conversion for the superclass
        if pytype in cls._known_furthest_descendant_mappings:
            return cls._implemented_conversions[
                cls._known_furthest_descendant_mappings[pytype]
            ]

        # If the pytype is a subclass of a conversion,
        # return the conversion for the superclass
        if cls.has_suitable_conversion(pytype):
            cur_suitable_implemented_pytype = None
            for candidate_implemented_pytype in cls._implemented_conversions.keys():
                pytype_is_subclass_of_candidate = is_subclass_of_union(
                    pytype, candidate_implemented_pytype
                )
                candidate_is_stricter_than_current = (
                    cur_suitable_implemented_pytype is None
                    or is_subclass_of_union(
                        candidate_implemented_pytype, cur_suitable_implemented_pytype
                    )
                )
                if (
                    pytype_is_subclass_of_candidate
                    and candidate_is_stricter_than_current
                ):
                    cur_suitable_implemented_pytype = candidate_implemented_pytype

            if cur_suitable_implemented_pytype is not None:
                cls._known_furthest_descendant_mappings[pytype] = (
                    cur_suitable_implemented_pytype
                )

            return cls._implemented_conversions[
                cls._known_furthest_descendant_mappings[pytype]
            ]
        else:
            raise _no_conversion_error(pytype)


def _no_conversion_error(pytype) -> TypeError:
    """Build a TypeError naming the unconvertible type and every registered
    pytype."""
    registered = ", ".join(
        sorted(t.__name__ for t in ConversionConfig._implemented_conversions)
    )
    return TypeError(
        f"No conversion registered for {pytype}." f" Registered pytypes: {registered}"
    )


# _string_conversion_info = ConversionInfo(
#     pytype=str,
#     to_bits=lambda string: BitVector(string.encode('utf-8')),
#     from_bits=lambda bits: bits.to_bytes().decode('utf-8'),
#     num_bits=lambda string: len(string.encode('utf-8')) * 8
# )
# ConversionConfig.set_conversion_info(_string_conversion_info)


def _char_to_bits(string: str) -> BitVector:
    """
    Convert a single one-byte character into its 8-bit BitVector.

    The registered str conversion is a fixed-width char, so num_bits reports
    8. The encoding is latin-1, the canonical byte-to-character bijection,
    which lets all 256 byte values round-trip.

    This encoder refuses any string whose latin-1 encoding is not exactly one
    byte, rather than silently emitting a width that disagrees with num_bits.
    Multi-byte and variable-width text belongs in the String bittypes
    instead. Use ``String.of(encoding=...)`` for that.

    Args:
        string (str): The character to convert. Must be a single
            U+0000-U+00FF character (exactly one latin-1 byte).

    Returns:
        BitVector: The 8-bit representation of the character

    Raises:
        ValueError: If the string does not encode to exactly one latin-1 byte.
    """
    try:
        encoded = string.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"The registered str conversion is a fixed-width latin-1 char"
            f" (8 bits), but {string!r} is not representable in latin-1"
            f" (use a String bittype for other encodings)."
        ) from exc
    if len(encoded) != 1:
        raise ValueError(
            f"The registered str conversion is a fixed-width char (8 bits),"
            f" but {string!r} encodes to {len(encoded)} latin-1 bytes."
            f" Serialize longer strings character-by-character or use a"
            f" String bittype for other encodings."
        )
    return BitVector(encoded)


_char_conversion_info = ConversionInfo(
    pytype=str,
    to_bits=_char_to_bits,
    from_bits=lambda bits: bits.to_bytes().decode("latin-1"),
    num_bits=lambda _: 8,
)
ConversionConfig.set_conversion_info(_char_conversion_info)

bool_conversion_info = ConversionInfo(
    pytype=bool,
    to_bits=lambda boo: BitVector([int(boo)]),
    from_bits=lambda bits: bool(bits.to_int()),
    num_bits=lambda _: 1,
)
ConversionConfig.set_conversion_info(bool_conversion_info)


# def _int_to_bits(num: int) -> BitVector:
#     if issubclass(type(num), bool):
#         to_convert = int(num)
#     return BitVector(to_convert,
#       to_convert.to_bytes(
#           twos_complement_bit_length(num),
#           byteorder='little', signed=num >= 0))


int_conversion_info = ConversionInfo(
    pytype=int,
    to_bits=lambda num: BitVector.from_int(num, size=32),
    from_bits=lambda bits: bits.to_int(),
    num_bits=lambda _: 32,
)
ConversionConfig.set_conversion_info(int_conversion_info)


float_conversion_info = ConversionInfo(
    pytype=float,
    to_bits=lambda fl: BitVector(struct.pack(">f", fl)),
    from_bits=lambda bits: struct.unpack(">f", bits.to_bytes())[0],
    num_bits=lambda _: 32,
)
ConversionConfig.set_conversion_info(float_conversion_info)


def pytype_to_bits(py_prim) -> BitVector:
    """
    Function to convert Python instances into a default number of BitVector.
        Uses the conversions in ConversionConfig.

    Args:
        py_prim: The python instance to convert to BitVector

    Returns:
        BitVector: The BitVector representation of the python instance
    """
    py_prim_type = type(py_prim)

    conversion = ConversionConfig.get_conversion_info(py_prim_type)

    if conversion is None:  # unreachable: get_conversion_info raises first
        raise _no_conversion_error(py_prim_type)

    return conversion.to_bits(py_prim)


def pytype_to_bytes(py_prim, endianness: Literal["big", "little"] = "big") -> bytes:
    """
    Function to convert Python instances into a default number of bytes.
        Uses the conversions in ConversionConfig.

    Args:
        py_prim: The python instance to convert to bytes
        endianness: The byte order of the output.
            Defaults to "big".

    Returns:
        bytes: The bytes representation of the python instance
    """
    retval = pytype_to_bits(py_prim).to_bytes()
    if validate_endianness(endianness) == "little":
        retval = retval[::-1]
    return retval


def bits_to_pytype(bits_obj: BitVector, pytype: type):
    """
    Convert bits into an instance of a Python type.

    Args:
        bits_obj (BitVector): The bits to convert to a Python primitive.
        pytype (type): The type of the Python primitive to convert to. It
            must have a suitable conversion registered in ConversionConfig.

    Returns:
        pytype: The instance of the provided Python type that the bits
            represent.
    """

    conversion = ConversionConfig.get_conversion_info(pytype)

    if conversion is None:  # unreachable: get_conversion_info raises first
        raise _no_conversion_error(pytype)

    return conversion.from_bits(bits_obj)


def bytes_to_pytype(
    bytes_obj: bytes, pytype: type, endianness: Literal["big", "little"] = "big"
):
    """
    Convert bytes into an instance of a Python type.

    Args:
        bytes_obj (bytes): The bytes to convert to a Python primitive.
        pytype (type): The type of the Python primitive to convert to. It
            must have a suitable conversion registered in ConversionConfig.
        endianness: The byte order of the input bytes. Defaults to "big".

    Returns:
        pytype: The instance of the provided Python type that the bytes
            represent.
    """
    if validate_endianness(endianness) == "little":
        bytes_obj = bytes_obj[::-1]
    return bits_to_pytype(BitVector(bytes_obj), pytype)
