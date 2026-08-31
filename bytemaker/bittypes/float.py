from __future__ import annotations

import math
import operator
from typing import TYPE_CHECKING, NoReturn

from bytemaker.bittypes.bittype import (
    BitType,
    NarrowingConfig,
    StructPackedBitType,
    _warn_narrowing,
)
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Any, Final, Optional, TypeVar
from bytemaker.utils import classproperty

if TYPE_CHECKING:
    from bytemaker.bittypes.int import Int

#: See the note on ``BitSelf`` in bittypes/bittype.py: a bound TypeVar in
#: both planes, the always-failing typing_redirect import removed.
FloatSelf = TypeVar("FloatSelf", bound="Float")


class Float(BitType[float]):
    """
    A BitType that represents an IEEE-754-style floating-point number.

    Use the `specialize` method to create a subclass with the number of
    exponent and mantissa bits you need, or use one of the pre-defined
    subclasses.

    The floating-point format in use is as follows:
    - The first bit is the sign bit
    - The next `num_exponent_bits` bits are the exponent
    - The next `num_mantissa_bits` bits are the mantissa

    Class Attributes:
    -----------------
    num_bits : int
        The number of bits in the Float.
    base_bit_type : Type[Float]
        The base `BitType` this class derives from. It is `Float`.
    py_type : Type[float]
        The Pythonic type that this `Float` can be converted to/from. It is `float`.
    num_exponent_bits : int
        The number of bits used to store the exponent.
    num_mantissa_bits : int
        The number of bits used to store the mantissa.

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this `Float` object.
    value : float
       The `float` value of this `Float` object.
    """

    py_type = float
    num_exponent_bits: Final[int]
    """The number of bits used to store the exponent."""
    num_mantissa_bits: Final[int]
    """The number of bits used to store the mantissa."""

    @classproperty
    @classmethod
    def num_bits(cls) -> int:
        return 1 + cls.num_exponent_bits + cls.num_mantissa_bits

    def __float__(self) -> float:
        """
        Magic method to convert the `Float` to a `float`.

        Note that python floats are IEEE 754 double-precision floats.
            With 52 bits of mantissa and 11 bits of exponent.
            If you create a float with near to or larger than one,
            of these quantities, there may be precision loss.

        Returns:
            float: The (double approximate) `float` value of this `Float` object.
        """
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
        bias: int = 2 ** (self.num_exponent_bits - 1) - 1

        mantissa: float = sum(
            (self.bits[1 + self.num_exponent_bits + i] * 2 ** -(i + 1))
            for i in range(self.num_mantissa_bits)
        )

        # The all-ones exponent encoding is reserved for
        # infinities (zero mantissa) and NaNs (nonzero mantissa)
        if exponent == 2**self.num_exponent_bits - 1:
            if mantissa == 0:
                return sign * float("inf")
            return float("nan")

        # The all-zeros exponent encoding is reserved for signed
        # zeros and subnormals: there is no implicit leading 1,
        # and the exponent is fixed at 1 - bias
        if exponent == 0:
            return sign * mantissa * 2.0 ** (1 - bias)

        unbiased_exponent: int = exponent - bias

        magnitude: float = 2**unbiased_exponent * (1 + mantissa)

        result = sign * magnitude

        return result

    @value.setter
    def value(self, value):
        # Reject strings explicitly (maintainer ruling), then coerce like the
        # constructor's py_type() path and the struct-packed siblings do, so
        # ints and other real numbers are accepted uniformly across the Float
        # family. Other non-numeric input raises TypeError from float().
        if isinstance(value, str):
            raise TypeError(
                f"{type(self).__name__} value must be a real number,"
                f" not a string; got {value!r}"
            )
        value = float(value)
        self.bits = BitVector(
            self.__class__.to_bitstring(
                value, self.num_exponent_bits, self.num_mantissa_bits
            )
        )
        # Overflow-to-inf is the float analog of integer narrowing: a finite
        # magnitude too large for this width saturates to signed infinity.
        # Report it under warn mode, reusing the narrowing emitter.
        if NarrowingConfig.warn and math.isfinite(value) and math.isinf(self.value):
            _warn_narrowing(value, self.value, type(self).__name__)

    def to_bitstring(
        self: Float | float, num_exponent_bits=8, num_mantissa_bits=23
    ) -> str:
        """
        Convert a `float` (or a `Float`) to a binary string.

        The conversion follows IEEE-754 conventions. Zeros keep their sign,
        and rounding is to nearest with ties going to even. A magnitude
        below the normal range becomes a subnormal, or a signed zero once it
        falls below the subnormal range as well. A magnitude above the
        normal range becomes a signed infinity. NaN encodes as a quiet NaN.

        Args:
            num_exponent_bits (int): The number of bits to use for the exponent.
            num_mantissa_bits (int): The number of bits to use for the mantissa.

        Returns:
            str: The unprefixed binary string representation of the `float`.
        """
        if isinstance(self, Float):
            num = self.value
        else:
            num = self

        sign_bit = "1" if math.copysign(1.0, num) < 0 else "0"
        exponent_all_ones = "1" * num_exponent_bits

        if math.isnan(num):
            # Canonical quiet NaN: all-ones exponent, most significant
            # mantissa bit set, zero payload
            return sign_bit + exponent_all_ones + "1" + "0" * (num_mantissa_bits - 1)
        if math.isinf(num):
            return sign_bit + exponent_all_ones + "0" * num_mantissa_bits
        if num == 0:
            return sign_bit + "0" * (num_exponent_bits + num_mantissa_bits)

        # The bias is 2^(num_exponent_bits - 1) - 1, and the all-ones
        # biased exponent is reserved for infinities and NaNs
        exponent_bias = (2 ** (num_exponent_bits - 1)) - 1
        max_biased_exponent = 2**num_exponent_bits - 1

        # abs(num) == fraction * 2**exponent with fraction in [0.5, 1),
        # i.e. 1.xxx... * 2**(exponent - 1). frexp/ldexp are exact
        # (Python floats are IEEE-754 doubles; scaling by powers of two
        # loses no precision), so all rounding below happens in round(),
        # which rounds to nearest with ties to even -- the IEEE default.
        fraction, exponent = math.frexp(abs(num))
        biased_exponent = exponent - 1 + exponent_bias

        if biased_exponent >= 1:
            # Normal candidate: scale so the implicit leading 1 plus the
            # mantissa form an integer, then round
            significand = round(math.ldexp(fraction, num_mantissa_bits + 1))
            if significand == 2 ** (num_mantissa_bits + 1):
                # Rounding carried into the next binade
                # (1.11...1 rounded up to 10.00...0)
                significand //= 2
                biased_exponent += 1
            if biased_exponent >= max_biased_exponent:
                # Magnitude too large for the exponent field:
                # overflow to signed infinity
                return sign_bit + exponent_all_ones + "0" * num_mantissa_bits
            mantissa_field = significand - 2**num_mantissa_bits
            return (
                sign_bit
                + format(biased_exponent, f"0{num_exponent_bits}b")
                + format(mantissa_field, f"0{num_mantissa_bits}b")
            )

        # Subnormal candidate: all-zeros exponent field, no implicit
        # leading 1, value == mantissa_field * 2**(1 - bias - num_mantissa_bits).
        # Rounding to 0 flushes to signed zero
        mantissa_field = round(
            math.ldexp(fraction, biased_exponent + num_mantissa_bits)
        )
        if mantissa_field >= 2**num_mantissa_bits:
            # Rounded up to the smallest normal number
            return (
                sign_bit + format(1, f"0{num_exponent_bits}b") + "0" * num_mantissa_bits
            )
        return (
            sign_bit
            + "0" * num_exponent_bits
            + format(mantissa_field, f"0{num_mantissa_bits}b")
        )

    @classmethod
    def specialize(
        cls,
        num_exponent_bits_,
        num_mantissa_bits_,
        packing_format_letter_: Optional[str] = None,
        name_: Optional[str] = None,
    ):
        """
        Produce a subclass of Float with the given number of exponent and
        mantissa bits.

        If a packing format letter is provided, the subclass is also a
        `StructPackedBitType` and uses `struct`'s packing and unpacking
        functions with that letter.

        If `name_` is provided, the subclass takes that name after class
        creation. Otherwise it is named _Float.

        Args:
            num_exponent_bits_ (int): The number of bits to use for the exponent.
            num_mantissa_bits_ (int): The number of bits to use for the mantissa.
            packing_format_letter_ (Optional[str], optional): The struct packing format
                letter to use, if any. Defaults to None, meaning no struct (un)packing.
            name_ (Optional[str], optional): What to rename the subclass, if anything.
                Defaults to None, meaning the subclass's name will be _Float.

        Returns:
            type[Float]: The subclass of `Float` with the specified number of bits.
        """
        if packing_format_letter_ is not None:
            # StructPackedBitType comes first so its struct-based value
            # getter/setter wins the MRO, matching the hand-written
            # Float16/Float32/Float64 and Int.specialize
            class _Float(StructPackedBitType[float], cls):
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

    # Promoted operators (D5): arithmetic computes on plain values and
    # returns plain float - previously each op re-encoded the result to this
    # type's width mid-expression, silently losing precision at the operator
    # (the float form of wrap-at-operator). The narrowing cast spelling is
    # the constructor: Float16(a + b). Compound assignment narrows back into
    # self, like C's a += b.

    def __add__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.add)

    def __radd__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y + x)

    def __sub__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.sub)

    def __rsub__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y - x)

    def __mul__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.mul)

    def __rmul__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y * x)

    def __truediv__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.truediv)

    def __rtruediv__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y / x)

    def __floordiv__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.floordiv)

    def __rfloordiv__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y // x)

    def __mod__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.mod)

    def __rmod__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y % x)

    def __pow__(self, other: int | float | Int | Float) -> Any:
        # float ** float can be complex (negative base, fractional
        # exponent), so Any - as in typeshed's float.__pow__.
        return self._promoted_value_op(other, operator.pow)

    def __rpow__(self, other: int | float | Int | Float) -> Any:
        return self._promoted_value_op(other, lambda x, y: y**x)

    def __lt__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.lt)

    def __le__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.le)

    def __gt__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.gt)

    def __ge__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.ge)

    # Compound assignment: type-preserving (returns self after the
    # narrowing re-encode).

    def __iadd__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.add)

    def __isub__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.sub)

    def __imul__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.mul)

    def __itruediv__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.truediv)

    def __ifloordiv__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.floordiv)

    def __imod__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.mod)

    def __ipow__(self: FloatSelf, other: int | float | Int | Float) -> FloatSelf:
        return self._inplace_value_op(other, operator.pow)

    def __neg__(self) -> float:
        return -self.value

    def __pos__(self) -> float:
        return +self.value

    def __abs__(self) -> float:
        return abs(self.value)

    # Floats have no value-plane bitwise meaning (same as C, where bitwise
    # operators reject floating operands). BitType's inherited elementwise
    # operators would silently bit-twiddle instead, so they are overridden
    # to refuse; the bit-plane spelling is explicit: f.bits & other.

    def __and__(self, other):
        return NotImplemented

    def __rand__(self, other):
        return NotImplemented

    def __or__(self, other):
        return NotImplemented

    def __ror__(self, other):
        return NotImplemented

    def __xor__(self, other):
        return NotImplemented

    def __rxor__(self, other):
        return NotImplemented

    def __lshift__(self, other):
        return NotImplemented

    def __rlshift__(self, other):
        return NotImplemented

    def __rshift__(self, other):
        return NotImplemented

    def __rrshift__(self, other):
        return NotImplemented

    def __invert__(self) -> NoReturn:
        raise TypeError(
            f"bad operand type for unary ~: {type(self).__name__!r}"
            f" (the bit-plane spelling is ~self.bits)"
        )


Float.base_bit_type = Float


class Float16(StructPackedBitType[float], Float):
    num_exponent_bits = 5
    num_mantissa_bits = 10
    packing_format_letter = "e"


class Float32(StructPackedBitType[float], Float):
    num_exponent_bits = 8
    num_mantissa_bits = 23
    packing_format_letter = "f"


class Float64(StructPackedBitType[float], Float):
    num_exponent_bits = 11
    num_mantissa_bits = 52
    packing_format_letter = "d"


class BFloat16(Float):
    """
    Google Brain's BFloat16 format with 8 exponent bits and 7 mantissa bits.
    """

    num_exponent_bits = 8
    num_mantissa_bits = 7


class TF19(Float):
    """
    NVidia's TensorFloat-19 format with 8 exponent bits and 10 mantissa bits.
    """

    num_exponent_bits = 8
    num_mantissa_bits = 10


class FP24(Float):
    """
    AMD's FP24 format with 7 exponent bits and 16 mantissa bits.
    """

    num_exponent_bits = 7
    num_mantissa_bits = 16


__all__ = ["Float", "Float16", "Float32", "Float64", "BFloat16", "TF19", "FP24"]
