from __future__ import annotations

import re
import struct
from abc import ABC, abstractmethod
from math import ceil, log2
from typing import TYPE_CHECKING

from bytemaker.bitvector import BitsConstructible, BitVector
from bytemaker.typing_redirect import (
    Final,
    Generic,
    Literal,
    Optional,
    Tuple,
    Type,
    TypeVar,
)
from bytemaker.utils import (
    FrozenDict,
    HashableMapping,
    classproperty,
    is_instance_of_union,
)


class Config:
    signed_int_format: Literal[
        "signed_magnitude", "ones_complement", "twos_complement"
    ] = "twos_complement"


# region BitType declaration
T = TypeVar("T")


class BitType(ABC, Generic[T]):
    """A type representable by a sequence of bits.
    Allows for editing the value of the type pythonically through the `value` property
       or through the underlying sequence of bits through the `bits` property.

    Also allows treating the BitType as the underlying (Pythonic) value
        for regular operations.

    Class Attributes:
    ---------------
    num_bits : int
       The number of bits in the BitType.
    base_bit_type : Type[BitType]
       The base BitType this class derives from (e.g. UInt for UInt8)
    py_type : Type[T]
       The Pythonic type that this BitType can be converted to/from

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this BitType object.
    value : py_type
       The (Pythonic) value of this BitType object.
    endianness : Literal["big", "little"]
       The endianness of this BitType object.
    """

    _num_bits: Final[int]
    base_bit_type: Final[Type[BitType]]
    py_type: Final[Type[T]]  # type: ignore[reportGeneralTypeIssue]

    _bits: BitVector
    _endianness: Literal["big", "little"]

    def __init__(
        self,
        source: Optional[(T | BitVector | BitType)] = None,
        value: Optional[T] = None,
        bits: Optional[BitVector] = None,
        endianness: Literal["big", "little", "source_else_big"] = "source_else_big",
    ):
        if source is not None:
            if isinstance(source, BitType):
                try:
                    value = self.py_type(source.value)  # type: ignore[reportCallIssue]
                    assert isinstance(value, self.py_type)
                except Exception as e:
                    raise ValueError(
                        f"Could not convert source value to (Pythonic) value"
                        f" due to error: {e}"
                    )
                if endianness == "source_else_big":
                    endianness = source.endianness

            elif isinstance(source, BitVector):
                bits = source
            else:
                try:
                    value = self.py_type(source)  # type: ignore[reportCallIssue]
                except Exception as e:
                    raise ValueError(
                        f"Could not convert source value to (Pythonic) value"
                        f" due to error: {e}"
                    )

        if endianness == "source_else_big":
            endianness = "big"
        endianness: Literal["big", "little"]
        self._endianness = endianness

        if value is None and bits is None:
            raise ValueError("Either value or bits must be provided")
        elif value is not None and bits is not None:
            raise ValueError("Only one of value or bits should be provided")
        if value is not None:
            self.value = value
        elif bits is not None:
            self.bits = bits

    @property
    def endianness(self) -> Literal["big", "little"]:
        return self._endianness

    @classproperty
    @classmethod
    def num_bits(cls) -> int:
        return cls._num_bits

    @property
    @abstractmethod
    def value(self) -> T:
        """
        The (readonly) getter for the (Pythonic) value of the BitType.

        To set the value directly, use the `value` setter.
        To directly adjust the value more complicatedly,
            use operations available directly on BitType object
            rather than on the value returned by this property.

        Returns:
            T: The (Pythonic) value of the BitType.
        """

    @value.setter
    @abstractmethod
    def value(self, value: T):
        """
        The setter for the (Pythonic) value of the BitType.

        Args:
            value (T): The new value for the BitType.
        """

    @property
    def bits(self) -> BitVector:
        """
        The (readonly) getter for the underlying sequence of bits of the BitType.

        To set the bits directly, use the `bits` setter.

        Returns:
            BitVector: _description_
        """
        return self._bits

    @bits.setter
    def bits(self, bits: BitVector):
        if len(bits) != self.num_bits:
            raise ValueError(f"Expected {self.num_bits} bits, got {len(bits)}")

        # if self._endianness != bits.endianness:
        #     raise ValueError(
        #         f"Endianness mismatch:"
        #         f" expected {self._endianness}, got {bits.endianness}")

        self._bits = bits

    def __str__(self):
        if len(self.bits) < 17:
            bitstring = self.bits.to01(sep=" ")
        else:
            bitstring = self.bits[:8].to01() + "..." + self.bits[-8:].to01()

        return (
            f"{self.__class__.__name__}[{self.endianness}]"
            f"({self.value} = {bitstring})"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}({self.value})"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.value == other.value
        return self.value == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __bytes__(self):
        temp_bytes = bytes(self.bits)
        if self.endianness == "big":
            return temp_bytes
        else:
            return temp_bytes[::-1]

    def __hash__(self):
        return hash(frozenset([self.__class__, self.value]))

    # Temporary methods
    # TODO remove
    def to_bits(self):
        return self.bits

    @classmethod
    def from_bits(cls, bits: BitVector):
        return cls(bits=bits)


class StructPackedBitType(BitType[T]):
    """
    Abstract base class for all BitType objects that use struct for packing/unpacking.
    """

    packing_format_letter: Final[str]

    @property
    def skip_struct_packing(self) -> bool:
        """
        If true, the struct packing/unpacking will be skipped and the value will be
            be calculated using parent methods.

        Most of the time this will be false
        """
        return False

    @property
    def packing_format(self) -> str:
        """
        Returns the packing format for the class.

        Args:
            endianness (str): the endianness of the packing format. Defaults to little

        Returns:
            str: the struct packing format for the subclass.
        """
        cls = self.__class__
        if self.endianness == "little":
            return f"<{cls.packing_format_letter}"
        elif self.endianness == "big":
            return f">{cls.packing_format_letter}"
        else:
            raise ValueError(
                f"Endianness must be either 'little' or 'big', not {self.endianness}"
            )

    @property
    def value(self) -> T:
        if not self.skip_struct_packing:
            the_bits = self.bits
            if not len(the_bits) % 8 == 0:
                the_bits = BitVector(8 - len(the_bits) % 8) + the_bits
            return struct.unpack(self.packing_format, bytes(self.bits))[0]
        else:
            return super().value

    @value.setter
    def value(self, value: T):
        if not self.skip_struct_packing:
            self._bits = BitVector(struct.pack(self.packing_format, value))
        else:
            super().value = value


# endregion BitType declaration
# region Buffer declaration
if TYPE_CHECKING:
    BufferSelf = TypeVar("BufferSelf", bound="Buffer")
else:
    try:
        from typing_redirect import Self as BufferSelf
    except ImportError:
        BufferSelf = TypeVar("BufferSelf", bound="Buffer")

NumBits = TypeVar("NumBits", bound=int)


class Buffer(BitType[BitVector]):
    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.
    """

    py_type = BitVector

    @property
    def value(self):
        return self.bits

    @value.setter
    def value(self, value):
        self._bits = BitVector(value)

    @classmethod
    def specialize(cls: Type[BufferSelf], num_bits_: int, name_: Optional[str] = None):
        """
        Returns a subclass of Buffer with the specified number of bits.
        """

        class _Buffer(cls):
            _num_bits = num_bits_

        if name_:
            _Buffer.__name__ = name_
        else:
            _Buffer.__name__ = f"Buffer{num_bits_}"

        # _Buffer_Genericized: Type[BufferSelf] = _Buffer[
        #     Literal[num_bits_]]  # type: ignore[reportUndefinedVariable]

        return _Buffer


Buffer.base_bit_type = Buffer


# endregion Buffer declaration
# region Buffer concrete subclasses
class Buffer1(Buffer):
    _num_bits = 1


class Buffer2(Buffer):
    _num_bits = 2


class Buffer3(Buffer):
    _num_bits = 3


class Buffer4(Buffer):
    _num_bits = 4


class Buffer5(Buffer):
    _num_bits = 5


class Buffer6(Buffer):
    _num_bits = 6


class Buffer7(Buffer):
    _num_bits = 7


class Buffer8(Buffer):
    _num_bits = 8


class Buffer9(Buffer):
    _num_bits = 9


class Buffer10(Buffer):
    _num_bits = 10


class Buffer11(Buffer):
    _num_bits = 11


class Buffer12(Buffer):
    _num_bits = 12


class Buffer13(Buffer):
    _num_bits = 13


class Buffer14(Buffer):
    _num_bits = 14


class Buffer15(Buffer):
    _num_bits = 15


class Buffer16(Buffer):
    _num_bits = 16


class Buffer17(Buffer):
    _num_bits = 17


class Buffer18(Buffer):
    _num_bits = 18


class Buffer19(Buffer):
    _num_bits = 19


class Buffer20(Buffer):
    _num_bits = 20


class Buffer21(Buffer):
    _num_bits = 21


class Buffer22(Buffer):
    _num_bits = 22


class Buffer23(Buffer):
    _num_bits = 23


class Buffer24(Buffer):
    _num_bits = 24


class Buffer25(Buffer):
    _num_bits = 25


class Buffer26(Buffer):
    _num_bits = 26


class Buffer27(Buffer):
    _num_bits = 27


class Buffer28(Buffer):
    _num_bits = 28


class Buffer29(Buffer):
    _num_bits = 29


class Buffer30(Buffer):
    _num_bits = 30


class Buffer31(Buffer):
    _num_bits = 31


class Buffer32(Buffer):
    _num_bits = 32


class Buffer50(Buffer):
    _num_bits = 50


class Buffer64(Buffer):
    _num_bits = 64


class Buffer100(Buffer):
    _num_bits = 100


class Buffer128(Buffer):
    _num_bits = 128


class Buffer200(Buffer):
    _num_bits = 200


class Buffer250(Buffer):
    _num_bits = 250


class Buffer256(Buffer):
    _num_bits = 256


class Buffer500(Buffer):
    _num_bits = 500


class Buffer512(Buffer):
    _num_bits = 512


class Buffer1000(Buffer):
    _num_bits = 1000


class Buffer1024(Buffer):
    _num_bits = 1024


# endregion Buffer concrete subclasses
# region Float declaration

if TYPE_CHECKING:
    FloatSelf = TypeVar("FloatSelf", bound="Float")
else:
    try:
        from typing_redirect import Self as FloatSelf
    except ImportError:
        FloatSelf = TypeVar("FloatSelf", bound="Float")

float_descriptor_type = int
FloatDescriptor = TypeVar("FloatDescriptor", bound=int)
FloatDescriptorInner = TypeVar("FloatDescriptorInner", bound=int)


class Float(BitType[float], ABC):
    """
    A BitType that represents a floating-point number.

    Use the `specialize` method to create a subclass with the desired number of
        exponent and mantissa bits
        or use one of the pre-defined subclasses.
    """

    py_type = float
    num_exponent_bits: Final[int]
    num_mantissa_bits: Final[int]

    @classproperty
    @classmethod
    def num_bits(cls) -> int:
        return 1 + cls.num_exponent_bits + cls.num_mantissa_bits

    def __float__(self):
        return self.value

    @property
    def value(self) -> float:
        # the first bit is the sign bit
        # "0" means positive, "1" means negative
        sign: int = -1 if self.bits[0] else 1
        # The exponent is not stored as a two's-
        # complement signed integer, but is still
        # signed. This is achieved by biasing the
        # stored unsigned binary integer with
        # an eventual offset. The biased exponent
        # is then just the unsigned int
        exponent: int = sum(
            2 ** (self.num_exponent_bits - i - 1) * self.bits[1 + i]
            for i in range(self.num_exponent_bits)
        )

        # The bias is 2^(num_exponent_bits_ - 1) - 1
        # To ensure that about half of the values
        # are negative and half are positive
        unbiased_exponent: int = exponent - (2 ** (self.num_exponent_bits - 1) - 1)

        mantissa: int = sum(
            (self.bits[1 + self.num_exponent_bits + i] * 2 ** -(i + 1))
            for i in range(self.num_mantissa_bits)
        )

        magnitude: float = 2**unbiased_exponent * (1 + mantissa)

        result = sign * magnitude

        return result

    @value.setter
    def value(self, value):
        if not isinstance(value, float):
            raise ValueError(f"Expected a float, got {type(value)}")
        self.bits = BitVector(
            self.__class__.to_binstring(
                value, self.num_exponent_bits, self.num_mantissa_bits
            )
        )

    def to_binstring(
        self: Float | float, num_exponent_bits=8, num_mantissa_bits=23
    ) -> str:
        if isinstance(self, Float):
            num = self.value
        else:
            num = self

        if num == 0:
            return "0" + "0" * (num_exponent_bits + num_mantissa_bits)
        if num == float("inf"):
            return "0" + "1" * (num_exponent_bits) + "0" * num_mantissa_bits
        if num == -float("inf"):
            return "1" + "1" * (num_exponent_bits) + "0" * num_mantissa_bits
        if num == float("NaN"):
            return "0" + "1" * (num_exponent_bits + 1) + "0" * (num_mantissa_bits - 1)

        def get_sign_bit(value) -> int:
            return 0 if value >= 0 else 1

        def int_to_bin(integer) -> str:
            return bin(integer)[2:]

        def frac_to_bin(fraction, bits) -> str:
            result = []
            while fraction and len(result) < bits:
                fraction *= 2
                bit = int(fraction)
                result.append(bit)
                fraction -= bit
            return "".join(map(str, result))

        def normalize(binary_int: str, binary_frac: str) -> Tuple[str, int]:
            combined = binary_int + binary_frac
            first_one = combined.index("1")
            normalized = "1." + combined[first_one + 1 :]
            exponent = len(binary_int) - first_one - 1
            return normalized, exponent

        def get_exponent_bias(num_exponent_bits: int) -> int:
            return (2 ** (num_exponent_bits - 1)) - 1

        def int_to_binary(integer: int, bits: int) -> str:
            binary = bin(integer).replace("0b", "")
            return binary.zfill(bits)

        def assemble_bits(
            sign, biased_exponent, mantissa, num_exponent_bits, num_mantissa_bits
        ) -> str:
            return (
                f"{sign}"
                f"{int_to_binary(biased_exponent, num_exponent_bits)}"
                f"{mantissa[:num_mantissa_bits].ljust(num_mantissa_bits, '0')}"
            )

        sign_bit = get_sign_bit(num)
        abs_num = abs(num)

        integral_part = int(abs_num)
        fractional_part = abs_num - integral_part

        integral_bin = int_to_bin(integral_part)
        fractional_bin = frac_to_bin(fractional_part, num_mantissa_bits + 1)

        normalized, exponent = normalize(integral_bin, fractional_bin)

        exponent_bias = get_exponent_bias(num_exponent_bits)
        biased_exponent = exponent + exponent_bias

        mantissa_bits = normalized.split(".")[1]

        final_binary = assemble_bits(
            sign_bit,
            biased_exponent,
            mantissa_bits,
            num_exponent_bits,
            num_mantissa_bits,
        )
        return final_binary

    @classmethod
    def specialize(
        cls,
        num_exponent_bits_,
        num_mantissa_bits_,
        packing_format_letter_: Optional[str] = None,
        name_: Optional[str] = None,
    ):
        if packing_format_letter_ is not None:

            class _Float(cls, StructPackedBitType[float]):
                num_exponent_bits = num_exponent_bits_
                num_mantissa_bits = num_mantissa_bits_
                packing_format_letter = packing_format_letter_

        else:

            class _Float(cls):
                num_exponent_bits = num_exponent_bits_
                num_mantissa_bits = num_mantissa_bits_

        if name_:
            _Float.__name__ = name_

        # _Float_Genericized: Type[FloatSelf] = _Float[
        #     Literal[num_bits_]]  # type: ignore[reportUndefinedVariable]

        # _Float_Genericized = _Float[
        #     Literal[num_bits_]]  # type: ignore[reportUndefinedVariable]

        return _Float


Float.base_bit_type = Float


# endregion Float declaration
# region concrete Float subclasses
class Float16(StructPackedBitType, Float):
    num_exponent_bits = 5
    num_mantissa_bits = 10
    packing_format_letter = "e"


class Float32(StructPackedBitType, Float):
    num_exponent_bits = 8
    num_mantissa_bits = 23
    packing_format_letter = "f"


class Float64(StructPackedBitType, Float):
    num_exponent_bits = 11
    num_mantissa_bits = 52
    packing_format_letter = "d"


class BFloat16(Float):
    num_exponent_bits = 8
    num_mantissa_bits = 7


class TF19(Float):
    num_exponent_bits = 8
    num_mantissa_bits = 10


class FP24(Float):
    num_exponent_bits = 7
    num_mantissa_bits = 16


# endregion concrete Float subclasses
# region int declaration
if TYPE_CHECKING:
    IntSelf = TypeVar("IntSelf", bound="Int")
else:
    try:
        from typing_redirect import Self as IntSelf
    except ImportError:
        IntSelf = TypeVar("IntSelf", bound="Int")


class Int(BitType[int]):
    py_type = int
    is_signed: Final[bool]

    def __int__(self):
        return self.value

    def to_pyint(
        self: BitType | BitsConstructible,
        signed: Optional[bool] = None,
        bin_format: Literal[
            "twos_complement", "signed_magnitude", "ones_complement"
        ] = "twos_complement",
    ):
        """
        Convert a bitstring to an integer.

        Parameters:
        - bitstring (str): The bitstring to convert.
        - signed (bool?): Whether the bitstring represents a signed integer.
            Default is cls.signed or True
        - bin_format (str?): The format for signed integers.
            Can be "twos_complement", "signed_magnitude", or "ones_complement".
            Default is "twos_complement".

        Returns:
        - int: The integer representation of the bitstring.
        """

        if signed is None:
            bin_format_default = getattr(self, "is_signed", True)
            assert isinstance(bin_format_default, bool)
            signed = bin_format_default

        if isinstance(self, BitType):
            self = self.bits.to01()
        elif isinstance(self, BitVector):
            self = self.to01()
        elif is_instance_of_union(self, BitsConstructible):
            self = BitVector(self).to01()
        else:
            raise TypeError(f"Unsupported type: {type(self)}")

        bitstring: str = self

        if not bitstring:
            raise ValueError("bitstring cannot be empty")

        bit_length = len(bitstring)

        if not signed:
            # Unsigned integer
            return int(bitstring, 2)

        # Signed integer handling
        if bin_format == "twos_complement":
            # Handle two's complement for signed integers
            if bitstring[0] == "1":  # Negative number
                int_value = -(2**bit_length) + int(bitstring, 2)
            else:  # Positive number
                int_value = int(bitstring, 2)

        elif bin_format == "signed_magnitude" or bin_format == "sign_magnitude":
            # Handle sign-magnitude for signed integers
            if bitstring[0] == "1":  # Negative number
                int_value = -int(bitstring[1:], 2)
            else:  # Positive number
                int_value = int(bitstring[1:], 2)

        elif bin_format == "ones_complement":
            # Handle one's complement for signed integers
            if bitstring[0] == "1":  # Negative number
                int_value = -((2 ** (bit_length - 1)) - int(bitstring[1:], 2) - 1)
            else:  # Positive number
                int_value = int(bitstring, 2)
        else:
            raise ValueError(f"Unsupported format: {bin_format}")

        return int_value

    @staticmethod
    def min_bit_length(
        value: int,
        signed: bool = False,
        bin_format: Optional[
            Literal["twos_complement", "signed_magnitude", "ones_complement"]
        ] = None,
    ) -> int:
        n = value

        if not signed:
            if n == 0:
                return 1
            return ceil(log2(n + 1))
        else:
            if bin_format is None:
                bin_format = "twos_complement"

            if bin_format == "twos_complement":
                if n == 0:
                    return 1  # Technically can represent 0 with 0 bits in
                    # two's complement, but this is not useful

                is_greq_than_zero = n >= 0
                abs_val = abs(n)
                is_power_of_two = (abs_val & (abs_val - 1)) == 0

                if is_greq_than_zero or not is_power_of_two:
                    return ceil(log2(abs_val + 1)) + 1  # Account for extra
                    # at negative extreme
                else:
                    return int(log2(abs_val)) + 1
            elif bin_format == "signed_magnitude" or bin_format == "sign_magnitude":
                if n == 0:
                    return 1
                return ceil(log2(abs(n) + 1)) + 1
            elif bin_format == "ones_complement":
                if n == 0:
                    return 1  # Technically can represent 0 with 0 bits in
                    # one's complement, but this is not useful
                return ceil(log2(abs(n) + 1)) + 1

    def to_bitstring(
        self: Int | int,
        signed: bool = False,
        bit_length: Optional[int] = None,
        rep_format: Optional[
            Literal["twos_complement", "signed_magnitude", "ones_complement"]
        ] = None,
    ) -> str:
        """
        Convert an integer to a bitstring.

        Parameters:
        - integer (int): The integer to convert.
        - signed (bool): Whether the integer should be treated as signed.
        - bit_length (int): The length of the bitstring.
        - rep_format (str): The format for signed integers.
            Can be "twos_complement", "signed_magnitude", or "ones_complement".
            Default is "twos_complement".

        Returns:
        - str: The bitstring representation of the integer.
        """

        def unsigned_int_to_bitstring(n: int, bit_length: int):
            if n < 0 or n >= 2**bit_length:
                raise ValueError("Value out of range for the specified bit_length")
            return bin(n)[2:].zfill(bit_length)

        def int_to_twos_complement(n: int, bit_length: int):
            """
            Convert a signed integer to its two's complement binary string
                representation.

            Args:
            z (int): The signed integer to convert.
            bit_length (int): The bit length of the two's complement representation.

            Returns:
            str: The two's complement binary string representation of the integer.
            """

            if n < -(2 ** (bit_length - 1)) or n >= 2 ** (bit_length - 1):
                raise ValueError(
                    "Value out of range for the specified bit_length"
                    " for two's-complement notation."
                )

            if n < 0:
                # Calculate two's complement for negative numbers
                n = 2**bit_length + n
            return format(n, f"0{bit_length}b")

        def int_to_ones_complement(n: int, bit_length: int):
            if abs(n) > 2 ** (bit_length - 1) - 1:
                raise ValueError(
                    "Value out of range for the specified bit_length"
                    " for one's-complement notation."
                )

            magnitude_string = unsigned_int_to_bitstring(abs(n), bit_length)
            if n >= 0:
                return magnitude_string
            else:
                return "".join(
                    "0" if digit == "1" else "1" for digit in magnitude_string
                )

        def int_to_signed_magnitude(n: int, bit_length: int):
            if abs(n) > 2 ** (bit_length - 1) - 1:
                raise ValueError(
                    "Value out of range for the specified bit_length"
                    " for sign-magnitude notation."
                )

            if n >= 0:
                return "0" + unsigned_int_to_bitstring(n, bit_length - 1)
            else:
                return "1" + unsigned_int_to_bitstring(-n, bit_length - 1)

        if isinstance(self, Int):
            value = self.value
        elif isinstance(self, int):
            value = int(self)

        if signed and rep_format is None:
            rep_format = "twos_complement"

        if bit_length is None:
            bit_length = Int.min_bit_length(value, signed=signed, bin_format=rep_format)

        if bit_length <= 0:
            raise ValueError("bit_length must be a positive integer")

        if not signed:
            return unsigned_int_to_bitstring(value, bit_length)

        if signed:
            if rep_format == "twos_complement":
                return int_to_twos_complement(value, bit_length)
            elif rep_format == "signed_magnitude" or rep_format == "sign_magnitude":
                return int_to_signed_magnitude(value, bit_length)
            elif rep_format == "ones_complement":
                return int_to_ones_complement(value, bit_length)
            else:
                raise ValueError(f"Unsupported format: {rep_format}")


# endregion int declaration
# region concrete SInt declaration
class SInt(Int):
    """
    A BitType that represents a signed integer.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.

    To change the default signed integer format, use the Config class
        (or set the int_format parameter in the constructor).
        The default signed integer format is two's complement.

    Class Attributes:
        base_bit_type (Type[SInt]): The base class for the SInt class.
        num_bits (int): The number of bits in the integer.
        is_signed (bool): Whether the integer is signed.

    Instance Attributes:
        int_format (Optional[str]): The format for signed integers.
            Can be "twos_complement", "signed_magnitude", or "ones_complement".
            If this is left as "None", the format will be taken from the Config class.
            Default is "twos_complement.

    Properties:
        value (int): The integer value of the bits.
        bits (BitVector): The bits representing the integer value.
    """

    is_signed = True

    def __init__(
        self,
        source: Optional[(int | BitVector | BitType)] = None,
        value: Optional[int] = None,
        bits: Optional[BitVector] = None,
        endianness: Literal["big", "little", "source_else_big"] = "source_else_big",
        int_format: Optional[
            Literal["twos_complement", "signed_magnitude", "ones_complement"]
        ] = None,
    ):
        if int_format is None:
            int_format = Config.signed_int_format

        self.int_format: Literal[
            "twos_complement", "signed_magnitude", "ones_complement"
        ] = int_format
        super().__init__(source=source, value=value, bits=bits, endianness=endianness)

    # @classproperty
    # @classmethod
    # def int_format(cls) -> str:
    #     return Config.signed_int_format

    @property
    def value(self):
        return Int.to_pyint(self.bits.to01(), signed=True, bin_format=self.int_format)

    @value.setter
    def value(self, value):
        str_bits = Int.to_bitstring(
            value, signed=True, bit_length=self.num_bits, rep_format=self.int_format
        )

        self.bits = BitVector(str_bits)

    @classmethod
    def specialize(
        cls,
        num_bits_: int,
        packing_format_letter_: Optional[str] = None,
        name_: Optional[str] = None,
    ):
        if packing_format_letter_ is not None:

            class _SInt(StructPackedBitType[int], cls):
                _num_bits = num_bits_
                packing_format_letter = packing_format_letter_

                @property
                def skip_struct_packing(self):
                    return self.int_format != "twos_complement"

        else:

            class _SInt(cls):
                _num_bits = num_bits_

        if name_ is not None:
            _SInt.__name__ = name_

        return _SInt


SInt.base_bit_type = SInt


# endregion SInt declaration
# region concrete SInt subclasses
class SInt1(SInt):
    _num_bits = 1


class SInt2(SInt):
    _num_bits = 2


class SInt3(SInt):
    _num_bits = 3


class SInt4(SInt):
    _num_bits = 4


class SInt5(SInt):
    _num_bits = 5


class SInt6(SInt):
    _num_bits = 6


class SInt7(SInt):
    _num_bits = 7


class SInt8(StructPackedBitType, SInt):
    _num_bits = 8
    packing_format_letter = "b"

    @property
    def skip_struct_packing(self):
        return Config.signed_int_format != "twos_complement"


class SInt9(SInt):
    _num_bits = 9


class SInt10(SInt):
    _num_bits = 10


class SInt11(SInt):
    _num_bits = 11


class SInt12(SInt):
    _num_bits = 12


class SInt13(SInt):
    _num_bits = 13


class SInt14(SInt):
    _num_bits = 14


class SInt15(SInt):
    _num_bits = 15


class SInt16(StructPackedBitType, SInt):
    _num_bits = 16
    packing_format_letter = "h"

    @property
    def skip_struct_packing(self):
        return Config.signed_int_format != "twos_complement"


class SInt32(StructPackedBitType, SInt):
    _num_bits = 32
    packing_format_letter = "i"

    @property
    def skip_struct_packing(self):
        return Config.signed_int_format != "twos_complement"


class SInt64(StructPackedBitType, SInt):
    _num_bits = 64
    packing_format_letter = "q"

    @property
    def skip_struct_packing(self):
        return Config.signed_int_format != "twos_complement"


class SInt128(SInt):
    _num_bits = 128


class SInt256(SInt):
    _num_bits = 256


# endregion concrete SInt subclasses
# region UInt declaration
class UInt(Int):
    is_signed = False

    @property
    def value(self):
        return int(self.bits.to01(), 2)

    @value.setter
    def value(self, value):
        self._bits = BitVector(bin(value)[2:])

    @classmethod
    def specialize(
        cls,
        num_bits_: int,
        packing_format_letter_: Optional[str] = None,
        name_: Optional[str] = None,
    ):
        if packing_format_letter_ is not None:

            class _UInt(StructPackedBitType[int], cls):
                _num_bits = num_bits_
                packing_format_letter = packing_format_letter_

        else:

            class _UInt(cls):
                _num_bits = num_bits_

        if name_ is not None:
            _UInt.__name__ = name_

        return _UInt


UInt.base_bit_type = UInt


# endregion UInt declaration
# region concrete UInt subclasses
class UInt2(UInt):
    _num_bits = 2


class UInt3(UInt):
    _num_bits = 3


class UInt4(UInt):
    _num_bits = 4


class UInt5(UInt):
    _num_bits = 5


class UInt6(UInt):
    _num_bits = 6


class UInt7(UInt):
    _num_bits = 7


class UInt8(StructPackedBitType, UInt):
    _num_bits = 8
    packing_format_letter = "B"


class UInt9(UInt):
    _num_bits = 9


class UInt10(UInt):
    _num_bits = 10


class UInt11(UInt):
    _num_bits = 11


class UInt12(UInt):
    _num_bits = 12


class UInt13(UInt):
    _num_bits = 13


class UInt14(UInt):
    _num_bits = 14


class UInt15(UInt):
    _num_bits = 15


class UInt16(StructPackedBitType, UInt):
    _num_bits = 16
    packing_format_letter = "H"


class UInt32(StructPackedBitType, UInt):
    _num_bits = 32
    packing_format_letter = "I"


class UInt64(StructPackedBitType, UInt):
    _num_bits = 64
    packing_format_letter = "Q"


class UInt128(UInt):
    _num_bits = 128


class UInt256(UInt):
    _num_bits = 256


# endregion concrete UInt subclasses
# region string declaration
class String(BitType[str]):
    py_type = str
    _codepoint_changes: Optional[
        HashableMapping[BitVector, BitVector] | HashableMapping[str, str]
    ] = None
    _codepoint_changes_cache: Optional[Tuple[int, HashableMapping[str, str]]] = None
    _reverse_codepoint_changes_cache: Optional[
        Tuple[int, HashableMapping[str, str]]
    ] = None
    _codepoint_change_regex_cache: Optional[Tuple[int, re.Pattern[str]]] = None
    _reverse_codepoint_changes_regex_cache: Optional[Tuple[int, re.Pattern[str]]] = None

    @classmethod
    @abstractmethod
    def encoding(cls, value: str) -> BitVector:
        pass

    @classmethod
    @abstractmethod
    def decoding(cls, bits: BitVector) -> str:
        pass

    @classproperty
    @classmethod
    def codepoint_changes(cls) -> Optional[HashableMapping[str, str]]:
        if cls._codepoint_changes is None:
            return None
        if cls._codepoint_changes_cache and cls._codepoint_changes_cache[0] == hash(
            cls._codepoint_changes
        ):
            return cls._codepoint_changes_cache[1]

        codepoint_changes_field = cls._codepoint_changes
        if len(codepoint_changes_field) > 0:
            if isinstance(
                codepoint_changes_field.items().__iter__().__next__()[0], BitVector
            ):
                codepoint_changes_field = FrozenDict(
                    {
                        cls.decoding(k): cls.decoding(v)
                        for k, v in codepoint_changes_field.items()
                    }
                )

        cls._codepoint_changes_cache = (
            hash(cls._codepoint_changes),
            codepoint_changes_field,
        )

    @classproperty
    @classmethod
    def reverse_codepoint_changes(cls) -> Optional[HashableMapping[str, str]]:
        if cls._codepoint_changes is None:
            return None
        if cls._reverse_codepoint_changes_cache and (
            cls._reverse_codepoint_changes_cache[0] == hash(cls._codepoint_changes)
        ):
            return cls._reverse_codepoint_changes_cache[1]

        codepoint_changes = cls.codepoint_changes
        reverse_codepoint_changes = FrozenDict(
            {v: k for k, v in codepoint_changes.items()}
        )
        cls._reverse_codepoint_changes_cache = (
            hash(cls._codepoint_changes),
            reverse_codepoint_changes,
        )

    @classproperty
    @classmethod
    def codepoint_change_regex(cls) -> Optional[re.Pattern]:
        if cls.codepoint_changes:
            if cls._codepoint_change_regex_cache and cls._codepoint_change_regex_cache[
                0
            ] == hash(cls.codepoint_changes):
                return cls._codepoint_change_regex_cache[1]
            else:
                cls._codepoint_change_regex_cache = (
                    hash(cls.codepoint_changes),
                    re.compile(
                        "|".join(re.escape(key) for key in cls.codepoint_changes.keys())
                    ),
                )
            return cls._codepoint_change_regex_cache[1]
        return None

    @classproperty
    @classmethod
    def reverse_codepoint_change_regex(cls) -> Optional[re.Pattern]:
        if cls.codepoint_changes:
            if cls._reverse_codepoint_changes_regex_cache and (
                cls._reverse_codepoint_changes_regex_cache[0]
                == hash(cls.codepoint_changes)
            ):
                return cls._reverse_codepoint_changes_regex_cache[1]
            else:
                cls._reverse_codepoint_changes_regex_cache = (
                    hash(cls.codepoint_changes),
                    re.compile(
                        "|".join(
                            re.escape(key) for key in cls.codepoint_changes.values()
                        )
                    ),
                )
            return cls._reverse_codepoint_changes_regex_cache[1]
        return None

    @codepoint_changes.setter
    @classmethod
    def codepoint_changes(
        cls, value: (HashableMapping[BitVector, BitVector] | HashableMapping[str, str])
    ):
        if len(value) > 0:
            if isinstance(value.items().__iter__().__next__()[0], BitVector):
                value = FrozenDict(
                    {cls.decoding(k): cls.decoding(v) for k, v in value.items()}
                )

        cls._codepoint_changes = value

    @classmethod
    def perform_codepoint_substitution(
        cls,
        input_string,
        codepoint_changes: HashableMapping[str, str],
        changes_regex: re.Pattern[str],
    ):
        return changes_regex.sub(
            lambda match: codepoint_changes[match.group(0)], input_string
        )

    @property
    def value(self):
        temp_value = self.decoding(self.bits)
        codepoint_changes = self.codepoint_changes
        if codepoint_changes is not None:
            codepoint_changes_regex: re.Pattern[str] = self.codepoint_change_regex
            temp_value = self.perform_codepoint_substitution(
                temp_value, codepoint_changes, codepoint_changes_regex
            )
        return temp_value

    @value.setter
    def value(self, value):
        temp_value = value
        reverse_codepoint_changes = self.reverse_codepoint_changes
        if reverse_codepoint_changes is not None:
            reverse_codepoint_changes_regex: re.Pattern[
                str
            ] = self.reverse_codepoint_change_regex
            temp_value = self.perform_codepoint_substitution(
                temp_value, reverse_codepoint_changes, reverse_codepoint_changes_regex
            )
        self.bits = self.encoding(temp_value)

    @classmethod
    def specialize(cls, num_bits_: int, name_: Optional[str] = None):
        class _String(cls):
            _num_bits = num_bits_

        if name_:
            _String.__name__ = name_

        return _String


String.base_bit_type = String


class StandardEncodingString(String):
    py_type = str
    encoding_name: str

    @classmethod
    def encoding(cls, value: str) -> BitVector:
        return BitVector(value.encode(cls.encoding_name))

    @classmethod
    def decoding(cls, bits: BitVector) -> str:
        return bytes(bits).decode(cls.encoding_name)


# endregion string declaration
# region concrete string subclasses
class UTF8String(StandardEncodingString):
    encoding_name = "utf-8"


class Str1(UTF8String):
    _num_bits = 1


class Str2(UTF8String):
    _num_bits = 2


class Str3(UTF8String):
    _num_bits = 3


class Str4(UTF8String):
    _num_bits = 4


class Str5(UTF8String):
    _num_bits = 5


class Str6(UTF8String):
    _num_bits = 6


class Str7(UTF8String):
    _num_bits = 7


class Str8(UTF8String):
    _num_bits = 8


class Str9(UTF8String):
    _num_bits = 9


class Str10(UTF8String):
    _num_bits = 10


class Str11(UTF8String):
    _num_bits = 11


class Str12(UTF8String):
    _num_bits = 12


class Str13(UTF8String):
    _num_bits = 13


class Str14(UTF8String):
    _num_bits = 14


class Str15(UTF8String):
    _num_bits = 15


class Str16(UTF8String):
    _num_bits = 16


class Str32(UTF8String):
    _num_bits = 32


class Str64(UTF8String):
    _num_bits = 64


class Str128(UTF8String):
    _num_bits = 128


class Str256(UTF8String):
    _num_bits = 256


class Str512(UTF8String):
    _num_bits = 512


# endregion concrete string subclasses


BitTypeType = TypeVar("BitTypeType", bound=BitType)


def bytes_to_bittype(unitbytes: bytes, unittype: type[BitTypeType]) -> BitTypeType:
    return unittype(bits=BitVector(unitbytes))
