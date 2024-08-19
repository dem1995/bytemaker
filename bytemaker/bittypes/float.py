from __future__ import annotations

from typing import TYPE_CHECKING

from bytemaker.bittypes.bittype import BitType, StructPackedBitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Final, Optional, Tuple, TypeVar
from bytemaker.utils import classproperty

if TYPE_CHECKING:
    FloatSelf = TypeVar("FloatSelf", bound="Float")
else:
    try:
        from typing_redirect import Self as FloatSelf
    except ImportError:
        FloatSelf = TypeVar("FloatSelf", bound="Float")


class Float(BitType[float]):
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

        return _Float


Float.base_bit_type = Float


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


__all__ = ["Float", "Float16", "Float32", "Float64", "BFloat16", "TF19", "FP24"]
