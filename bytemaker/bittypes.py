from __future__ import annotations

import inspect
import math
import struct
from abc import ABC, abstractmethod
from typing import Any, Callable

from bytemaker.bits import Bits, BitsConstructorType
from bytemaker.utils import ByteConvertible, classproperty, is_instance_of_union


class BitTypeRegistry:
    """
    Class to track created BitTypes.
    """

    base_types: set = set()
    registered_types: dict[str, type] = dict()

    @staticmethod
    def find_type(type_name: str):
        return BitTypeRegistry.registered_types.get(type_name, None)

    @classmethod
    def register_subtypes(cls, base_cls):
        """
        Class decorator to register all non-abstract subclasses.
        """
        # Preserve the original __init_subclass__ if it exists
        orig_init_subclass = base_cls.__dict__.get("__init_subclass__", None)

        @classmethod
        def __init_subclass__(cls, **kwargs):
            # If there was an original __init_subclass__, call it properly
            if orig_init_subclass:
                orig_init_subclass.__func__(cls, **kwargs)
            # Register the subclass if it's not abstract
            if not inspect.isabstract(cls):
                BitTypeRegistry.registered_types[cls.__name__] = cls

        base_cls.__init_subclass__ = __init_subclass__
        return base_cls


# Abstract Classes
@BitTypeRegistry.register_subtypes
class BitType(ABC):
    """
    Abstract base class for all BitType objects.

    BitType objects are objects that can be converted to and from bits and bytes.

    Class Properties:
    -----------
    num_bits : int
        The number of bits in the BitType object.
    num_bytes : int
        The number of bytes in the BitType object.
    value_type : type
        The type of the value of the BitType object.
    value : Any
        The value of the BitType object.
    bytes : bytes
        The bytes representation of the BitType object.
    bytearray : bytearray
        The bytearray representation of the BitType object.
    bits : Bits
        The bitstring representation of the BitType object.

    Required Abstract Methods:
    -----------------
    get_num_bits() -> int:
        Abstract class method that returns the number of bits in instances of the BitType.

    get_value_type() -> type:
        Abstract class method that returns the type of the values of instances of the BitType.


    to_bits(*args, **kwargs) -> Bits:
        Abstract instance method that converts the BitType object to bitstring.Bits.

    from_bits(the_bits: Bits, *args, **kwargs):
        Abstract class method that converts bitstring.Bits to an instance of the BitType.



    Concrete Methods:
    --------
    get_num_bytes() -> int:
       Class method that returns the number of bytes in instances of the BitType.


    get_value() -> Any:
        Instance method that returns the value (internal) of the BitType object.

    to_bytes(*args, **kwargs) -> bytes:
        Instance method that converts the BitType object to bytes.

    from_bytes(the_bytes, *args, **kwargs):
        Class method that converts bytes to an instance of the BitType class.

    __eq__(other) -> bool:
        Instance method that compares the BitType object with another object.

    __Bits__() -> Bits:
        Instance method that converts the BitType object to bitstring.Bits.
        Useful for Bits(theObject).

    __bytes__() -> bytes:
        Instance method that converts the BitType object to bytes.
        Useful for bytes(theObject).

    __repr__() -> str:
        Instance method that returns the string representation of the object.
        Useful for repr(theObject), or if the class has not overridden __str__, str(thObject)
    """

    def __init_subclass__(cls, **kwargs):
        """
        Registers the subclass in the BitTypeRegistry.
        """
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            BitTypeRegistry.find_type(cls.__name__)

    def __init__(
        self, value: bytes | bytearray | Bits | Any, test_creation=True, *args, **kwargs
    ) -> None:
        """
        Initializes the BitType object.

        Attempts the following:
        - If value is an instance of the valuetype of the BitType subclass, sets the value directly.
        - If value is an instance of BitType and the valuetype of both BitTypes match, \
            sets the value to the value of the BitType subclass.
        - If value is an instance of bitstring.Bits, calls from_bits(Bits(value)) from the BitType subclass.
        - If value is an instance of bytes or bytearray, calls from_bytes(bytes(value)) from the BitType subclass.
        - If value is an instance of BitsConstructorType, calls from_bits(Bits(value)) from the BitType subclass.
        - If value is an instance of ByteConvertible, calls from_bytes(bytes(value)) from the BitType subclass.
        - If value is castable to the valuetype of the BitType subclass, sets the value to the casted value.
        - Otherwise, raises a TypeError.

        Args:
        - value: the value of the object.
        - test_creation: a boolean indicating whether to test the creation of the object.
            If true, calls to_bytes() to test if the object is properly convertible to bytes.
        """
        super().__init__()

        if isinstance(value, self.value_type):
            self._value = value
        elif isinstance(value, BitType) and self.value_type == value.value_type:
            self._value = value.value
        elif isinstance(value, Bits):
            self._value = self.from_bits(value).value
        elif isinstance(value, (bytes, bytearray)):
            self._value = self.from_bytes(value).value
        elif is_instance_of_union(value, BitsConstructorType):
            self._value = self.from_bits(Bits(value)).value
        elif isinstance(value, ByteConvertible):
            self._value = self.from_bytes(bytes(value)).value
        else:
            try:
                newvalue = self.value_type(value)
                self._value = newvalue
            except Exception as e:
                raise TypeError(
                    f"Expecting {self.value_type}, got {type(value)}"
                    f"Exception details: {e}"
                )

        if test_creation:
            self.validate_value(value)

    def validate_value(self, value):
        """
        Validates the value of the object. Called by __init__ if test_creation is True.
            By default, just tries to convert the object to bytes.
        """
        try:
            bytes(self)
        except Exception as e:
            raise type(e)(f"Object {value} is not properly convertible to bytes.")

    # Bits/bytes counting
    @classmethod
    @abstractmethod
    def get_num_bits(cls) -> int:
        """
        Returns the number of bits that represent the values of members of the class.
        """

    @classproperty
    def num_bits(cls) -> int:
        __doc__ = cls.get_num_bits.__doc__
        return cls.get_num_bits()

    @classmethod
    def get_num_bytes(cls) -> int:
        """
        Returns the number of bytes that represent the values of members of the class.
        """
        return cls.get_num_bits() / 8

    @classproperty
    def num_bytes(cls):
        __doc__ = cls.get_num_bytes.__doc__
        return cls.get_num_bytes()

    # Value type info
    @classmethod
    @abstractmethod
    def get_value_type(cls):
        """
        Returns the value type of the subclass.
        """

    @classproperty
    def value_type(cls):
        __doc__ = cls.get_value_type.__doc__
        return cls.get_value_type()

    # Value info
    def get_value(self):
        """
        Returns the value the instance of the BitType represents.
        """
        if hasattr(self, "_value"):
            return self._value
        else:
            raise AttributeError(
                f"Object of type {type(self)} has no attribute '_value'."
                f"All BitType objects should have an attribute '_value' that yields"
                f" the represented value of the object."
            )

    def set_value(self, new_value):
        """
        Sets the value the instance of the BitType represents.
        """
        self._value = new_value

    @property
    def value(self):
        __doc__ = self.get_value.__doc__
        return self.get_value()

    @value.setter
    def value(self, new_value):
        __doc__ = self.set_value.__doc__
        self.set_value(new_value)

    # Conversions to/from bits and bytes
    @abstractmethod
    def to_bits(self, *args, **kwargs) -> Bits:
        """
        Returns the bitstring.Bits representation of the value the object represents
            in the number of bits specified by the class.
        """

    @classmethod
    @abstractmethod
    def from_bits(cls, the_bits: Bits, *args, **kwargs):
        """
        Returns an instance of the subclass representing the object represented by the_bits.
        """

    def __Bits__(self) -> Bits:
        """
        Returns the bitstring.Bits representation of the value the object represents
            Used by Bits(theObject)
        """
        return self.to_bits()

    def to_bytes(self, *args, **kwargs) -> bytes:
        """
        Returns the bytes representation of the value the object represents
            in the number of bytes specified by the class.
        """
        return bytes(self.to_bits(*args, **kwargs))

    @classmethod
    def from_bytes(cls, the_bytes, *args, **kwargs):
        """
        Returns an instance of the subclass representing the object represented by the_bytes.
        """
        return cls.from_bits(Bits(the_bytes), *args, **kwargs)

    def __bytes__(self) -> bytes:
        """
        Returns the bytes representation of the value the object represents
            Used by bytes(theObject)
        """
        return self.to_bytes()

    # Alternative bytes/bytearray/bits representations
    @property
    def bytes(self) -> bytes:
        __doc__ = self.to_bytes.__doc__
        return bytes(self)

    @property
    def bytearray(self) -> bytearray:
        """
        Returns a bytearray representation of the bytes representation of the value represented by the object.
        """
        return bytearray(bytes(self))

    @property
    def bits(self) -> Bits:
        """
        Returns a bitstring.Bits representation of the bytes representation of the value represented by the object.
        """
        return Bits(self)

    # Operators
    def __eq__(self, other) -> bool:
        """
        Returns whether the object is equal to another object.
            Here, this could mean the following, checked in order:
            - This object is a BitType and its value equals the other object
            - Both objects are BitTypes and contain equivalent values.
                In the case of the values being floats, if both are nans, they are still considered equal
            - Both objects are implicitly bit-convertible through __Bits__() and have equivalent bit conversions
            - Both objects are implicitly byte-convertible through __bytes__() and have equivalent byte conversions
            - Both objects are the same object (default behavior of parent class)
        """

        if isinstance(other, self.value_type):
            return self.value == other
        elif isinstance(other, StructPackedBitType):
            if self.value_type == other.value_type:
                both_floats = self.value_type == float and other.value_type == float
                both_nans = (
                    both_floats and math.isnan(self.value) and math.isnan(other.value)
                )
                if not both_nans:
                    return self.value == other.value
        elif is_instance_of_union(other, BitsConstructorType):
            return Bits(self) == other.bits
        elif isinstance(other, ByteConvertible):
            return bytes(self) == bytes(other)

        else:
            return super().__eq__(other)

    # Other conversions
    def __repr__(self) -> str:
        """
        Returns the string representation of the object.

        Returns:
        - the string representation of the object.
        """
        classname = str(self.__class__).split(".")[-1].split("'")[0]
        return f"{classname}, value {str(self.value)}"


class StructPackedBitType(BitType):
    """
    Abstract base class for all BitType objects that involve using struct for packing/unpacking.
    """

    def to_bits(self, *args, endianness="big", **kwargs):
        """
        Returns the bytes representation of the object.

        Args:
        - endianness: the endianness of the bytes representation.

        Returns:
        - the bytes representation of the object.
        """
        packing_format = self.get_packing_format(endianness)
        return Bits(struct.pack(packing_format, self.value, *args))

    @classmethod
    def from_bits(cls, the_bits, *args, endianness="big", **kwargs):
        """
        Returns the StructPackedBitType object from the bytes representation.

        Args:
        - the_bytes: the bytes representation of the object.
        - endianness: the endianness of the bytes representation.

        Returns:
        - the StructPackedBitType object from the bytes representation.
        """
        packing_format = cls.get_packing_format(endianness)
        return cls(struct.unpack(packing_format, bytes(the_bits), *args, **kwargs)[0])

    @abstractmethod
    def get_packing_format_letter(cls):
        """
        Returns the struct-packing format letter for the class.
        """

    @classproperty
    def packing_format_letter(cls):
        __doc__ = cls.get_packing_format_letter.__doc__
        return cls.get_packing_format_letter()

    @classmethod
    def get_packing_format(cls, endianness="big"):
        """
        Returns the packing format for the class.

        Args:
        - endianness: the endianness of the packing format. Defaults to little

        Returns:
        - the struct packing format for the subclass.
        """
        if endianness == "little":
            return f"<{cls.packing_format_letter}"
        elif endianness == "big":
            return f">{cls.packing_format_letter}"
        else:
            raise ValueError(
                f"Endianness must be either 'little' or 'big', not {endianness}"
            )


# Concrete classes
# Bit Types
class BitBitType(BitType):
    """
    Abstract base class for all BitType objects that represent bit values.
    """

    def to_bits(self, *args, **kwargs) -> Bits:
        return self.value
        # default_bits = Bits.from_int(self.value, size=self.num_bits, *args, **kwargs)
        # diff = self.num_bits - len(default_bits)
        # if diff > 0:
        #     return default_bits + Bits([0] * diff)
        # elif diff < 0:
        #     raise ValueError(
        #         f"Cannot convert {self} to Bits"
        #         f"because the number of bits in the object ({self.num_bits})"
        #         f"is greater than the number of bits in the object ({len(default_bits)})")
        # else:
        #     return default_bits

    @classmethod
    def from_bits(cls, the_bits: Bits, *args, **kwargs):
        return cls(the_bits, *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return Bits


def BitsTypeFactory(size_in_bits: int) -> type[BitBitType]:
    """
    Factory function for creating BitBitType subclasses with the given number of bits.
        In the event there is an existing BitBitType with the specified number of bits,
        retrieves it instead.
    Args:
    - size_in_bits: the number of bits the subclass represents.

    """
    init_type_name = f"Bit{size_in_bits}"

    # Grab an existing type if this matches one.
    existing_type = BitTypeRegistry.find_type(init_type_name)
    if existing_type is not None:
        return existing_type

    class NewBitBitType(BitBitType):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

    NewBitBitType.__name__ = init_type_name
    BitTypeRegistry.registered_types[init_type_name] = NewBitBitType
    return NewBitBitType


class Bit1(BitsTypeFactory(1)):
    pass


class Bit2(BitsTypeFactory(2)):
    pass


class Bit3(BitsTypeFactory(3)):
    pass


class Bit4(BitsTypeFactory(4)):
    pass


class Bit5(BitsTypeFactory(5)):
    pass


class Bit6(BitsTypeFactory(6)):
    pass


class Bit7(BitsTypeFactory(7)):
    pass


class Bit8(BitsTypeFactory(8)):
    pass


class Bit16(BitsTypeFactory(16)):
    pass


class Bit24(BitsTypeFactory(24)):
    pass


class Bit32(BitsTypeFactory(32)):
    pass


class Bit64(BitsTypeFactory(64)):
    pass


class Bit128(BitsTypeFactory(128)):
    pass


# Byte Types
class ByteBitType(BitType, bytearray):
    """
    Abstract base class for all BitType objects that represent raw byte values.
    """

    def to_bits(self, *args, **kwargs) -> Bits:
        default_bytes = self.value
        diff = math.ceil(self.num_bytes) - len(default_bytes)
        if diff > 0:
            return default_bytes + bytes(b"\x00" * diff)
        elif diff < 0:
            raise ValueError(
                f"Cannot convert {self} to Bits."
                f" The number of bits in the self.num_bits, ({self.num_bits})"
                f" is greater than the number of bits in the object ({len(default_bytes)})"
            )
        else:
            return Bits(default_bytes)

    @classmethod
    def from_bits(cls, the_bits: Bits, *args, **kwargs):
        return cls(bytes(the_bits), *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return bytes


def BytesTypeFactory(size_in_bits: int) -> type[ByteBitType]:
    init_type_name = f"Byte{size_in_bits}"

    # Grab an existing type if this matches one.
    existing_type = BitTypeRegistry.find_type(init_type_name)
    if existing_type is not None:
        return existing_type

    class NewByteBitType(ByteBitType, bytearray):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

    NewByteBitType.__name__ = init_type_name
    return NewByteBitType


class Byte8(BytesTypeFactory(8)):
    pass


class Byte16(BytesTypeFactory(16)):
    pass


class Byte24(BytesTypeFactory(24)):
    pass


class Byte32(BytesTypeFactory(32)):
    pass


class Byte64(BytesTypeFactory(64)):
    pass


class Byte128(BytesTypeFactory(128)):
    pass


# Integer Types
class IntBitType(BitType):
    def __init__(self, value: int | bytes | bytearray | IntBitType, *args, **kwargs):
        super().__init__(value, *args, **kwargs)

    @abstractmethod
    def get_is_signed(self):
        """
        Returns whether the subclass represents a signed (vs unsigned) integer.
        """

    @classproperty
    def is_signed(self):
        __doc__ = self.get_is_signed.__doc__

    @classmethod
    def get_value_type(cls):
        return int

    def __int__(self):
        return self.value


# UInts
class UInt(IntBitType):
    @classmethod
    def get_is_signed(cls):
        return False


def _UIntStructPackedTypeFactory(
    size_in_bits: int, packing_format_letter: str
) -> type[UInt]:
    init_type_name = f"UInt{size_in_bits}"
    existing_type = BitTypeRegistry.find_type(init_type_name)
    if existing_type is not None:
        return existing_type

    class NewUIntBitType(UInt, StructPackedBitType):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

        @classmethod
        def get_packing_format_letter(cls):
            return packing_format_letter

    return NewUIntBitType


class UInt8(_UIntStructPackedTypeFactory(8, "B")):
    pass


class UInt16(_UIntStructPackedTypeFactory(16, "H")):
    pass


class UInt24(_UIntStructPackedTypeFactory(24, "I")):
    pass


class UInt32(_UIntStructPackedTypeFactory(32, "I")):
    pass


class UInt64(_UIntStructPackedTypeFactory(64, "Q")):
    pass


# Signed ints
class SInt(IntBitType):
    @classmethod
    def get_is_signed(cls):
        return True


def _SIntStructPackedTypeFactory(size_in_bits: int, packing_format_letter: str) -> SInt:
    class NewSIntBitType(SInt, StructPackedBitType):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

        @classmethod
        def get_packing_format_letter(cls):
            return packing_format_letter

    return NewSIntBitType


class SInt8(_SIntStructPackedTypeFactory(8, "b")):
    pass


class SInt16(_SIntStructPackedTypeFactory(16, "h")):
    pass


class SInt24(_SIntStructPackedTypeFactory(24, "i")):
    pass


class SInt32(_SIntStructPackedTypeFactory(32, "i")):
    pass


class SInt64(_SIntStructPackedTypeFactory(64, "q")):
    pass


# Floats


class FloatBitType(BitType):
    def __init__(
        self, value: float | bytes | bytearray | FloatBitType, *args, **kwargs
    ):
        super().__init__(value, *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return float

    def __float__(self):
        return self.value


def _FloatStructPackedTypeFactory(
    size_in_bits: int, packing_format_letter: str
) -> type[FloatBitType]:
    class NewFloatBitType(FloatBitType, StructPackedBitType):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

        @classmethod
        def get_packing_format_letter(cls):
            return packing_format_letter

    return NewFloatBitType


class Float16(_FloatStructPackedTypeFactory(16, "e")):
    pass


class Float32(_FloatStructPackedTypeFactory(32, "f")):
    pass


class Float64(_FloatStructPackedTypeFactory(64, "d")):
    pass


# Strings


class StrBitType(BitType):
    def __init__(self, value: str | bytes | bytearray | StrBitType, *args, **kwargs):
        super().__init__(value, *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return str

    @classproperty
    def encoding_method(cls):
        return cls.get_encoding_method()

    @classproperty
    def decoding_method(cls):
        return cls.get_decoding_method()

    @classmethod
    @abstractmethod
    def get_encoding_method(cls):
        pass

    @classmethod
    @abstractmethod
    def get_decoding_method(cls):
        pass

    @classmethod
    def pack_string_same_size(cls, size_in_bits: int):
        packed_string = cls(size_in_bits)
        return packed_string

    def __str__(self):
        return self.value


class DefaultCodings:
    str_dec = lambda the_bits: bytes(the_bits).decode(encoding="UTF-8")
    str_enc = lambda the_str: Bits(the_str.encode(encoding="UTF-8"))


def StrTypeFactory(
    size_in_bits: int,
    encode_method: Callable[[str], Bits] = DefaultCodings.str_enc,
    decode_method: Callable[[Bits], str] = DefaultCodings.str_dec,
    custom_type_name=None,
) -> type[StrBitType]:
    if custom_type_name is None:
        init_type_name = f"Str{size_in_bits}"
    else:
        init_type_name = custom_type_name
    cur_type_name = init_type_name

    # Grab an existing type if this matches one in name/encoding/decoding.
    existing_type = BitTypeRegistry.find_type(cur_type_name)
    counter = 0
    while existing_type is not None:
        if (
            existing_type.encode_method == encode_method
            and existing_type.decode_method == decode_method
        ):
            return existing_type
        else:
            cur_type_name = f"Str{size_in_bits}_{counter}"
            existing_type = BitTypeRegistry.find_type(cur_type_name)

    class NewStrBitType(StrBitType):
        def __init__(
            self, value: str | Bits | bytes | bytearray | StrBitType, *args, **kwargs
        ):
            if isinstance(value, str):
                self._value = value
            elif (
                isinstance(value, bytes)
                or isinstance(value, bytearray)
                or isinstance(value, Bits)
            ):
                self._value = decode_method(value, *args, **kwargs)

            super().__init__(value, *args, **kwargs)

        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

        def to_bits(self, *args, **kwargs) -> Bits:
            str_len = len(encode_method(self.value))
            diff = self.num_bits - str_len
            default_bits = Bits(encode_method(self.value), *args, **kwargs)

            # print("before", len(default_bits))
            if diff > 0:
                default_bits = default_bits + [0] * diff
            # print(len(default_bits))
            return default_bits

        def get_encoding_method(cls):
            return encode_method

        def get_decoding_method(cls):
            return decode_method

        @classmethod
        def from_bits(cls, the_bits, *args, **kwargs):
            return cls(decode_method(the_bits, *args, **kwargs))

        def __repr__(self):
            str_len = len(encode_method(self.value))
            diff = self.num_bits - str_len
            addendum_bytes = ""
            addendum_bits = ""

            if diff > 0:
                initial_counter = str_len
                addendum_bytes = "\\x"
                while initial_counter < self.num_bits:
                    if initial_counter % 32 == 0:
                        addendum_bytes += "_"
                    addendum_bytes += "0"
                    initial_counter += 4

                if initial_counter > self.num_bits:
                    initial_counter -= 4
                    addendum_bits = "\\b"
                    while initial_counter < self.num_bits:
                        if initial_counter % 8 == 0:
                            addendum_bits += "_"
                        addendum_bits += "0"
                        initial_counter += 1

                return self.value + addendum_bytes + addendum_bits
            else:
                return self.value

        def __str__(self):
            return self.value

    NewStrBitType.__name__ = cur_type_name
    NewStrBitType.encode_method = encode_method
    NewStrBitType.decode_method = decode_method
    BitTypeRegistry.registered_types[cur_type_name] = NewStrBitType
    print(BitTypeRegistry.find_type(cur_type_name))
    return NewStrBitType


class Str8(StrTypeFactory(8)):
    pass


# BitTypeRegistry.str_types = {
#     Str8.__name__: Str8
# }
# BitTypeRegistry.bit_types = {
#     Bit1.__name__: Bit1,
#     Bit2.__name__: Bit2,
#     Bit3.__name__: Bit3,
#     Bit4.__name__: Bit4,
#     Bit5.__name__: Bit5,
#     Bit6.__name__: Bit6,
#     Bit7.__name__: Bit7,
#     Bit8.__name__: Bit8,
#     Bit16.__name__: Bit16,
#     Bit24.__name__: Bit24,
#     Bit32.__name__: Bit32,
#     Bit64.__name__: Bit64,
#     Bit128.__name__: Bit128
# }
# BitTypeRegistry.byte_types = {
#     Byte8.__name__: Byte8,
#     Byte16.__name__: Byte16,
#     Byte24.__name__: Byte24,
#     Byte32.__name__: Byte32,
#     Byte64.__name__: Byte64,
#     Byte128.__name__: Byte128
# }
# BitTypeRegistry.uint_types = {
#     UInt8.__name__: UInt8,
#     UInt16.__name__: UInt16,
#     UInt24.__name__: UInt24,
#     UInt32.__name__: UInt32,
#     UInt64.__name__: UInt64
# }
# BitTypeRegistry.sint_types = {
#     SInt8.__name__: SInt8,
#     SInt16.__name__: SInt16,
#     SInt24.__name__: SInt24,
#     SInt32.__name__: SInt32,
#     SInt64.__name__: SInt64
# }
# BitTypeRegistry.float_types = {
#     Float16.__name__: Float16,
#     Float32.__name__: Float32,
#     Float64.__name__: Float64
# }


def get_bittype(
    typing_representation: str | BitType | type, num_bits: int = None
) -> BitType:
    matched_type = BitTypeRegistry.find_type(typing_representation)
    if matched_type is not None:
        return matched_type

    BitType_to_str = {
        UInt: "uint",
        SInt: "sint",
        FloatBitType: "float",
        BitBitType: "bit",
        ByteBitType: "byte",
        StrBitType: "str",
    }

    type_name_matching = {
        "chr": "Str8",
        "char": "Str8",
        "int": "sint",
        "bytes": "byte",
    }

    type_name_re_matching = {
        "sint": "SInt",
        "uint": "UInt",
        "float": "Float",
        "str": "Str",
        "bit": "Bit",
        "byte": "Byte",
    }

    if isinstance(typing_representation, BitType):
        typing_representation = BitType_to_str[type(typing_representation)]

    elif isinstance(typing_representation, type):
        typing_representation = typing_representation.__qualname__

    # Typing representation should be string by this point
    assert isinstance(typing_representation, str)
    if not num_bits:
        number_in_string = [s for s in list(typing_representation) if s.isdigit()]
        number_in_string = "".join(number_in_string)
        if number_in_string:
            num_bits = int(number_in_string)

    # Get only alphabetic characters
    typing_representation = "".join([i for i in typing_representation if i.isalpha()])

    typing_representation = typing_representation.lower()
    if typing_representation == "int":
        typing_representation = "sint"
    elif typing_representation == "char" or typing_representation == "chr":
        num_bits = 8
        typing_representation = "str"

    # Process the typing representation
    if typing_representation in type_name_matching:
        typing_representation = type_name_matching[typing_representation]

    if typing_representation in type_name_re_matching:
        typing_representation = type_name_re_matching[typing_representation]

    typing_representation = typing_representation + str(num_bits)

    matched_type = BitTypeRegistry.find_type(typing_representation)
    if matched_type is not None:
        return matched_type
    else:
        return None


def bittype_to_bytes(
    unit: BitType, num_bytes: int | None = None, reverse_endianness: bool = False
) -> bytes:
    if isinstance(unit, BitType):
        return unit.to_bytes(num_bytes=num_bytes, reverse_endianness=reverse_endianness)
    else:
        raise TypeError(f"Expecting BitType, got {type(unit)}")


def bytes_to_bittype(
    unitbytes: bytes, unittype: BitType, reverse_endianness: bool = False
) -> BitType:
    if reverse_endianness:
        unitbytes = unitbytes[::-1]

    if issubclass(unittype, BitType):
        unit = unittype.from_bytes(unitbytes)
    else:
        raise TypeError(f"Expecting BitType, got {unittype}")

    return unit


if __name__ == "__main__":
    the_bytes = Bits(StrTypeFactory(10 * 8)("fish"))
    print(the_bytes)
    print(bytes_to_bittype(the_bytes, StrTypeFactory(20), reverse_endianness=False))

    print(Str8("f"))
