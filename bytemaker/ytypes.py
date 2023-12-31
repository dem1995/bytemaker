
from __future__ import annotations
from abc import ABC, abstractmethod
import math
import struct
from typing import Any, Callable, Optional
from bytemaker.bits import Bits, BitsConstructorType
from bytemaker.utils import classproperty, ByteConvertible, is_instance_of_union


class CustomTypeTracker:
    """
    Class to track custom types created by the user.
    """
    bit_types = {}
    byte_types = {}
    str_types = {}
    uint_types = {}
    sint_types = {}
    float_types = {}


# Abstract Classes
class YType(ABC):
    """
    Abstract base class for all YType objects.

    YType objects are objects that can be converted to and from bits and bytes.

    Class Properties:
    -----------
    num_bits : int
        The number of bits in the YType object.
    num_bytes : int
        The number of bytes in the YType object.
    value_type : type
        The type of the value of the YType object.
    value : Any
        The value of the YType object.
    bytes : bytes
        The bytes representation of the YType object.
    bytearray : bytearray
        The bytearray representation of the YType object.
    bits : Bits
        The bitstring representation of the YType object.

    Required Abstract Methods:
    -----------------
    get_num_bits() -> int:
        Abstract class method that returns the number of bits in instances of the YType.

    get_value_type() -> type:
        Abstract class method that returns the type of the values of instances of the YType.


    to_bits(*args, **kwargs) -> Bits:
        Abstract instance method that converts the YType object to bitstring.Bits.

    from_bits(the_bits: Bits, *args, **kwargs):
        Abstract class method that converts bitstring.Bits to an instance of the YType.



    Concrete Methods:
    --------
    get_num_bytes() -> int:
       Class method that returns the number of bytes in instances of the YType.


    get_value() -> Any:
        Instance method that returns the value (internal) of the YType object.

    to_bytes(*args, **kwargs) -> bytes:
        Instance method that converts the YType object to bytes.

    from_bytes(the_bytes, *args, **kwargs):
        Class method that converts bytes to an instance of the YType class.

    __eq__(other) -> bool:
        Instance method that compares the YType object with another object.

    __Bits__() -> Bits:
        Instance method that converts the YType object to bitstring.Bits.
        Useful for Bits(theObject).

    __bytes__() -> bytes:
        Instance method that converts the YType object to bytes.
        Useful for bytes(theObject).

    __repr__() -> str:
        Instance method that returns the string representation of the object.
        Useful for repr(theObject), or if the class has not overridden __str__, str(thObject)
    """

    def __init__(self, value: bytes | bytearray | Bits | Any, test_creation=True, *args, **kwargs) -> None:
        """
        Initializes the YType object.

        Attempts the following:
        - If value is an instance of the valuetype of the YType subclass, sets the value directly.
        - If value is an instance of YType and the valuetype of both YTypes match, \
            sets the value to the value of the YType subclass.
        - If value is an instance of bitstring.Bits, calls from_bits(Bits(value)) from the YType subclass.
        - If value is an instance of bytes or bytearray, calls from_bytes(bytes(value)) from the YType subclass.
        - If value is an instance of BitsConstructorType, calls from_bits(Bits(value)) from the YType subclass.
        - If value is an instance of ByteConvertible, calls from_bytes(bytes(value)) from the YType subclass.
        - If value is castable to the valuetype of the YType subclass, sets the value to the casted value.
        - Otherwise, raises a TypeError.

        Args:
        - value: the value of the object.
        - test_creation: a boolean indicating whether to test the creation of the object.
            If true, calls to_bytes() to test if the object is properly convertible to bytes.
        """

        super().__init__()

        if self.value is None:
            if isinstance(value, self.value_type):
                self._value = value
            elif isinstance(value, YType) and self.value_type == value.value_type:
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
                    raise TypeError(f"Expecting {self.value_type}, got {type(value)}"
                                    f"Exception details: {e}")

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
        pass

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
        pass

    @classproperty
    def value_type(cls):
        __doc__ = cls.get_value_type.__doc__
        return cls.get_value_type()

    # Value info
    def get_value(self):
        """
        Returns the value the instance of the subclass represents.
        """
        if hasattr(self, '_value'):
            return self._value
        else:
            return None

    @property
    def value(self):
        __doc__ = self.get_value.__doc__
        return self.get_value()

    # Conversions to/from bits and bytes
    @abstractmethod
    def to_bits(self, *args, **kwargs) -> Bits:
        """
        Returns the bitstring.Bits representation of the value the object represents
            in the number of bits specified by the class.
        """
        pass

    @classmethod
    @abstractmethod
    def from_bits(cls, the_bits: Bits, *args, **kwargs):
        """
        Returns an instance of the subclass representing the object represented by the_bits.
        """
        pass

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
        return Bits(bytes(self))

    # Operators
    def __eq__(self, other) -> bool:
        """
        Returns whether the object is equal to another object.
            Here, this could mean the following, checked in order:
            - This object is a ytype and its value equals the other object
            - Both objects are ytypes and contain equivalent values.
                In the case of the values being floats, if both are nans, they are still considered equal
            - Both objects are implicitly bit-convertible through __Bits__() and have equivalent bit conversions
            - Both objects are implicitly byte-convertible through __bytes__() and have equivalent byte conversions
            - Both objects are the same object (default behavior of parent class)
        """

        if isinstance(other, self.value_type):
            return self.value == other
        elif isinstance(other, StructPackedYType):
            if self.value_type == other.value_type:
                both_floats = self.value_type == float and other.value_type == float
                both_nans = both_floats and math.isnan(self.value) and math.isnan(other.value)
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
        classname = str(self.__class__).split('.')[-1].split("'")[0]
        return f"{classname}, value {str(self.value)}"


class StructPackedYType(YType):
    """
    Abstract base class for all YType objects that involve using struct for packing/unpacking.
    """

    def to_bits(self, *args, endianness='big', **kwargs):
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
    def from_bits(cls, the_bits, *args, endianness='big', **kwargs):
        """
        Returns the StructPackedYType object from the bytes representation.

        Args:
        - the_bytes: the bytes representation of the object.
        - endianness: the endianness of the bytes representation.

        Returns:
        - the StructPackedYType object from the bytes representation.
        """
        packing_format = cls.get_packing_format(endianness)
        return cls(struct.unpack(packing_format, bytes(the_bits), *args, **kwargs)[0])

    @abstractmethod
    def get_packing_format_letter(cls):
        """
        Returns the struct-packing format letter for the class.
        """
        pass

    @classproperty
    def packing_format_letter(cls):
        __doc__ = cls.get_packing_format_letter.__doc__
        return cls.get_packing_format_letter()

    @classmethod
    def get_packing_format(cls, endianness='big'):
        """
        Returns the packing format for the class.

        Args:
        - endianness: the endianness of the packing format. Defaults to little

        Returns:
        - the struct packing format for the subclass.
        """
        if endianness == 'little':
            return f"<{cls.packing_format_letter}"
        elif endianness == 'big':
            return f">{cls.packing_format_letter}"
        else:
            raise ValueError(f"Endianness must be either 'little' or 'big', not {endianness}")


# Concrete classes
# Bit Types
class BitYType(YType):
    """
    Abstract base class for all YType objects that represent bit values.
    """
    def to_bits(self, *args, **kwargs) -> Bits:
        default_bits = Bits(self, size=self.num_bits, *args, **kwargs)
        diff = self.num_bits - len(default_bits)
        if diff > 0:
            return default_bits + Bits([0] * diff)
        elif diff < 0:
            raise ValueError(
                f"Cannot convert {self} to Bits"
                f"because the number of bits in the object ({self.num_bits})"
                f"is greater than the number of bits in the object ({len(default_bits)})")
        else:
            return default_bits

    @classmethod
    def from_bits(cls, the_bits: Bits, *args, **kwargs):
        return cls(the_bits, *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return Bits


def BitsTypeFactory(size_in_bits: int):
    """
    Factory function for creating BitYType subclasses with the given number of bits.
        In the event there is an existing BitYType with the specified number of bits,
        retrieves it instead.
    Args:
    - size_in_bits: the number of bits the subclass represents.

    """
    init_type_name = f"Bit{size_in_bits}"
    cur_type_name = init_type_name
    cur_type_count = 0
    # Grab an existing type if this matches one. Ends with the "next" bit type name for bits with the given # of bits
    while cur_type_name in CustomTypeTracker.bit_types:
        if cur_type_name in CustomTypeTracker.bit_types[cur_type_name]:
            return CustomTypeTracker.bit_types[cur_type_name]
        cur_type_count += 1
        cur_type_name = f"{init_type_name}{cur_type_count}"

    class NewBitYType(Bits, BitYType):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

    NewBitYType.__name__ = cur_type_name
    CustomTypeTracker.bit_types[cur_type_name] = NewBitYType
    return NewBitYType


class Bit1(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 1
    pass


class Bit2(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 2
    pass


class Bit3(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 3
    pass


class Bit4(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 4
    pass


class Bit5(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 5
    pass


class Bit6(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 6
    pass


class Bit7(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 7
    pass


class Bit8(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 8
    pass


class Bit16(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 16
    pass


class Bit24(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 24
    pass


class Bit32(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 32
    pass


class Bit64(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 64
    pass


class Bit128(Bits, BitYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 128
    pass


# Byte Types
class ByteYType(YType, bytearray):
    """
    Abstract base class for all YType objects that represent raw byte values.
    """

    def to_bits(self, *args, **kwargs) -> Bits:
        default_bytes = self.value
        diff = math.ceil(self.num_bytes) - len(default_bytes)
        if diff > 0:
            return default_bytes + bytes(b'\x00' * diff)
        elif diff < 0:
            raise ValueError(
                f"Cannot convert {self} to Bits."
                f" The number of bits in the self.num_bits, ({self.num_bits})"
                f" is greater than the number of bits in the object ({len(default_bytes)})")
        else:
            return Bits(default_bytes)

    @classmethod
    def from_bits(cls, the_bits: Bits, *args, **kwargs):
        return cls(bytes(the_bits), *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return bytes


def BytesTypeFactory(size_in_bits: int):
    init_type_name = f"Byte{size_in_bits}"
    cur_type_name = init_type_name
    cur_type_count = 0
    # Grab an existing type if this matches one. Ends with the "next" byte type name for bytes with the given # of bits
    while cur_type_name in CustomTypeTracker.byte_types:
        if cur_type_name in CustomTypeTracker.byte_types:
            return CustomTypeTracker.byte_types[cur_type_name]
        cur_type_count += 1
        cur_type_name = f"{init_type_name}{cur_type_count}"

    class NewByteYType(ByteYType, bytearray):
        @classmethod
        def get_num_bits(cls) -> int:
            return size_in_bits

    NewByteYType.__name__ = cur_type_name
    CustomTypeTracker.byte_types[cur_type_name] = NewByteYType
    return NewByteYType


class Byte8(ByteYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 8
    pass


class Byte16(ByteYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 16
    pass


class Byte24(ByteYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 24
    pass


class Byte32(ByteYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 32
    pass


class Byte64(ByteYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 64
    pass


class Byte128(ByteYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 128
    pass


# Integer Types
class IntYType(YType):
    def __init__(self, value: int | bytes | bytearray | IntYType, *args, **kwargs):
        super().__init__(value, *args, **kwargs)

    @abstractmethod
    def get_is_signed(self):
        """
        Returns whether the subclass represents a signed (vs unsigned) integer.
        """
        pass

    @classproperty
    def is_signed(self):
        __doc__ = self.get_is_signed.__doc__
        pass

    @classmethod
    def get_value_type(cls):
        return int

    def __int__(self):
        return self.value


# UInts
class UInt(IntYType):
    @classmethod
    def get_is_signed(cls):
        return False


class UInt8(UInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 8

    @classmethod
    def get_packing_format_letter(cls):
        return 'B'


class UInt16(UInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 16

    @classmethod
    def get_packing_format_letter(cls):
        return 'H'


class UInt24(UInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 24

    @classmethod
    def get_packing_format_letter(cls):
        return 'I'


class UInt32(UInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 32

    @classmethod
    def get_packing_format_letter(cls):
        return 'I'


class UInt64(UInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 64

    @classmethod
    def get_packing_format_letter(cls):
        return 'Q'


# Signed ints
class SInt(IntYType):
    @classmethod
    def get_is_signed(cls):
        return True


class SInt8(SInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 8

    @classmethod
    def get_packing_format_letter(cls):
        return 'b'


class SInt16(SInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 16

    @classmethod
    def get_packing_format_letter(cls):
        return 'h'


class SInt24(SInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 24

    @classmethod
    def get_packing_format_letter(cls):
        return 'i'


class SInt32(SInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 32

    @classmethod
    def get_packing_format_letter(cls):
        return 'i'


class SInt64(SInt, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 64

    @classmethod
    def get_packing_format_letter(cls):
        return 'q'


# Floats
class FloatYType(YType):
    def __init__(self, value: float | bytes | bytearray | FloatYType, *args, **kwargs):
        super().__init__(value, *args, **kwargs)

    @classmethod
    def get_value_type(cls):
        return float

    def __float__(self):
        return self.value


class Float16(FloatYType, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 16

    @classmethod
    def get_packing_format_letter(cls):
        return 'e'


class Float32(FloatYType, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 32

    @classmethod
    def get_packing_format_letter(cls):
        return 'f'


class Float64(FloatYType, StructPackedYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 64

    @classmethod
    def get_packing_format_letter(cls):
        return 'd'


class StrYType(YType):
    def __init__(self, value: str | bytes | bytearray | StrYType, *args, **kwargs):
        super().__init__(value, *args, **kwargs)

    @property
    def value(self):
        return self._value

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
        decode_method: Callable[[Bits], str] = DefaultCodings.str_dec):
    init_type_name = f"Str{size_in_bits}"
    cur_type_name = init_type_name
    cur_type_count = 0
    # Grab an existing type if this matches one in name/encoding/decoding.
    # Ends with the "next" string type name for strings with the given number of bits
    while cur_type_name in CustomTypeTracker.str_types:
        if (
            CustomTypeTracker.str_types[cur_type_name].encode_method == encode_method and
            CustomTypeTracker.str_types[cur_type_name].decode_method == decode_method
        ):
            return CustomTypeTracker.str_types[cur_type_name]
        cur_type_count += 1
        cur_type_name = f"{init_type_name}Coding{cur_type_count}"

    class NewStrYType(StrYType):
        def __init__(self, value: str | Bits | bytes | bytearray | StrYType, *args, **kwargs):
            if isinstance(value, str):
                self._value = value
            elif isinstance(value, bytes) or isinstance(value, bytearray) or isinstance(value, Bits):
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

    NewStrYType.__name__ = cur_type_name
    NewStrYType.encode_method = encode_method
    NewStrYType.decode_method = decode_method
    CustomTypeTracker.str_types[cur_type_name] = NewStrYType
    return NewStrYType


class Str8(StrTypeFactory(8), StrYType):
    @classmethod
    def get_num_bits(cls) -> int:
        return 8


CustomTypeTracker.str_types = {}
CustomTypeTracker.bit_types = {
    Bit1.__name__: Bit1,
    Bit2.__name__: Bit2,
    Bit3.__name__: Bit3,
    Bit4.__name__: Bit4,
    Bit5.__name__: Bit5,
    Bit6.__name__: Bit6,
    Bit7.__name__: Bit7,
    Bit8.__name__: Bit8,
    Bit16.__name__: Bit16,
    Bit24.__name__: Bit24,
    Bit32.__name__: Bit32,
    Bit64.__name__: Bit64,
    Bit128.__name__: Bit128
}
CustomTypeTracker.byte_types = {
    Byte8.__name__: Byte8,
    Byte16.__name__: Byte16,
    Byte24.__name__: Byte24,
    Byte32.__name__: Byte32,
    Byte64.__name__: Byte64,
    Byte128.__name__: Byte128
}
CustomTypeTracker.uint_types = {
    UInt8.__name__: UInt8,
    UInt16.__name__: UInt16,
    UInt24.__name__: UInt24,
    UInt32.__name__: UInt32,
    UInt64.__name__: UInt64
}
CustomTypeTracker.sint_types = {
    SInt8.__name__: SInt8,
    SInt16.__name__: SInt16,
    SInt24.__name__: SInt24,
    SInt32.__name__: SInt32,
    SInt64.__name__: SInt64
}
CustomTypeTracker.float_types = {
    Float16.__name__: Float16,
    Float32.__name__: Float32,
    Float64.__name__: Float64
}


def ytype_to_bytes(unit: YType, num_bytes: Optional[int] = None, reverse_endianness: bool = False) -> bytes:
    if isinstance(unit, YType):
        return unit.to_bytes(num_bytes=num_bytes, reverse_endianness=reverse_endianness)
    else:
        raise TypeError(f"Expecting YType, got {type(unit)}")


def bytes_to_ytype(unitbytes: bytes, unittype: YType, reverse_endianness: bool = False) -> YType:
    if reverse_endianness:
        unitbytes = unitbytes[::-1]

    if issubclass(unittype, YType):
        unit = unittype.from_bytes(unitbytes)
    else:
        raise TypeError(f"Expecting YType, got {unittype}")

    return unit


if __name__ == "__main__":
    the_bytes = Bits(StrTypeFactory(10 * 8)("fish"))
    print(the_bytes)
    print(bytes_to_ytype(the_bytes, StrTypeFactory(20), reverse_endianness=False))

    print(Str8("f"))
