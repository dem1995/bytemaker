"""Sized integer BitTypes: `Int` and its `SInt`/`UInt` families.

Arithmetic follows the C promotion model. Binary operators compute on plain
values at full width and return a plain `int`, and that includes the bitwise
family and `~`.

Narrowing back to a width happens only at stores, meaning the `value` setter
and compound assignment. It also happens at the constructor, which is the
narrowing cast. See the `Int` docstring for the full contract.
"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, overload

from bytemaker.bittypes.bittype import (
    BitType,
    StructPackedBitType,
    _narrow_int,
)
from bytemaker.bitvector import BitsConstructible, BitVector
from bytemaker.typing_redirect import Final, Literal, Optional, TypeVar
from bytemaker.utils import is_instance_of_union, twos_complement_bit_length

if TYPE_CHECKING:
    from bytemaker.bittypes.float import Float

#: See the note on ``BitSelf`` in bittypes/bittype.py: a bound TypeVar in
#: both planes, the always-failing typing_redirect import removed.
IntSelf = TypeVar("IntSelf", bound="Int")


class Int(BitType[int]):
    """
    A `BitType` that represents an integer.

    It is further subclassed into `SInt` and `UInt` for signed and unsigned
    integers respectively.

    Arithmetic follows the C promotion model. Binary operators compute on
    plain values at full width and return a plain `int`, and that includes
    the bitwise family and `~`. So `UInt8(200) + UInt8(100) == 300`, never a
    wrapped box.

    Width re-attaches only at stores. The constructor is the narrowing cast,
    so `UInt8(a + b)` wraps just like `(uint8_t)(a + b)` does in C. Compound
    assignment such as `u += 1` narrows the result back into the box's own
    width.

    Out-of-range stores wrap silently by default, as in C. Set
    `NarrowingConfig.warn = True` to make each such store also emit a
    `NarrowingWarning`.

    Class Attributes:
    -----------------
    num_bits : int
       The number of bits in the BitType.
    base_bit_type : Type[BitType]
       The base `BitType` this class derives from.
    py_type : Type[T]
       The Pythonic type that this Int can be converted to/from. It is int.
    is_signed : bool
       Whether the integer type is signed.

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this `Int` object.
    value : int
       The `int` value of this `Int` object.
    endianness : Literal["big", "little"]
       The endianness of this `Int` object.
    """

    py_type = int
    is_signed: Final[bool]
    """Whether the integer type is signed."""

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        # Named, explicit lossless-integer protocol: makes boxes usable
        # anywhere a plain int is (hex(), list indexing, range(), and the
        # Struct field descriptors' operator.index() store path) without
        # touching operator semantics.
        return self.value

    def to_pyint(
        self: BitType | BitsConstructible,
        signed: Optional[bool] = None,
        bin_format: Literal[
            "twos_complement", "signed_magnitude", "ones_complement"
        ] = "twos_complement",
    ):
        """
        Convert the bits of `self` to an integer.

        Parameters:

        - self (BitType | BitsConstructible): The object whose bits to
          convert. It may be a `BitType`, a `BitVector`, or anything a
          `BitVector` can be constructed from, such as a "01" string.
          That makes this callable unbound, as `Int.to_pyint("1010")`.
        - signed (Optional[bool], optional): Whether the bits represent a
          signed integer rather than an unsigned one. Defaults to
          `self.is_signed` on `Int` subclasses, and to `True` elsewhere.
        - bin_format (Optional[str], optional): The format for signed
          integers. It can be "twos_complement", "signed_magnitude", or
          "ones_complement". Default is "twos_complement".

        Returns:

        - int: The integer representation of the bits.
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
            # (a 1-bit string has an empty magnitude field: +0 / -0)
            magnitude = int(bitstring[1:], 2) if bit_length > 1 else 0
            if bitstring[0] == "1":  # Negative number
                int_value = -magnitude
            else:  # Positive number
                int_value = magnitude

        elif bin_format == "ones_complement":
            # Handle one's complement for signed integers
            if bitstring[0] == "1":  # Negative number
                magnitude = int(bitstring[1:], 2) if bit_length > 1 else 0
                int_value = -((2 ** (bit_length - 1)) - magnitude - 1)
            else:  # Positive number
                int_value = int(bitstring, 2)
        else:
            raise ValueError(f"Unsupported format: {bin_format}")

        return int_value

    @staticmethod
    def min_bit_length(
        value: int,
        signed: bool = True,
        bin_format: Optional[
            Literal["twos_complement", "signed_magnitude", "ones_complement"]
        ] = None,
    ) -> int:
        """
        Calculate the minimum number of bits required to represent an integer.
        Note that this is not the same as len(bin(value)), which assumes an unsigned
        representation (possibly with - in front).

        Parameters:
           value (int): The integer to represent.
           signed (bool, optional): Whether the representation format should be signed.
                Default is True.
           bin_format (Optional[str], optional): The format for signed integers.
                Can be "twos_complement", "signed_magnitude", or "ones_complement".
                Default is "twos_complement".
        """
        n = value

        # Exact integer arithmetic throughout: float log2 under-sizes powers
        # of two >= 2**49 (2**k + 1 is indistinguishable from 2**k in float).
        if not signed:
            if n == 0:
                return 1
            return n.bit_length()
        else:
            if bin_format is None:
                bin_format = "twos_complement"

            if bin_format == "twos_complement":
                return twos_complement_bit_length(n)
            elif bin_format == "signed_magnitude" or bin_format == "sign_magnitude":
                if n == 0:
                    return 1
                # magnitude bits plus a sign bit
                return abs(n).bit_length() + 1
            elif bin_format == "ones_complement":
                if n == 0:
                    return 1
                # magnitude bits plus a sign bit
                return abs(n).bit_length() + 1
            else:
                raise ValueError(
                    f"Unsupported format: {bin_format!r}. Expected one of"
                    f" 'twos_complement', 'signed_magnitude', or"
                    f" 'ones_complement'."
                )

    def to_bitstring(
        self: Int | int,
        signed: bool = True,
        bit_length: Optional[int] = None,
        rep_format: Optional[
            Literal["twos_complement", "signed_magnitude", "ones_complement"]
        ] = None,
    ) -> str:
        """
        Convert an integer to a bitstring.

        Parameters:

        - self (Int | int): The integer to convert. Call it on an instance
          as ``x.to_bitstring()``, or directly as
          ``Int.to_bitstring(5, ...)``.
        - signed (bool, optional): Whether the integer should be treated as
          signed. Default is True.
        - bit_length (int, optional): The length of the bitstring.
        - rep_format (Optional[str], optional): The format for signed
          integers. It can be "twos_complement", "signed_magnitude", or
          "ones_complement". Default is "twos_complement".

        Returns:

        - str: The bitstring representation of the integer.
        """

        def unsigned_int_to_bitstring(n: int, bit_length: int):
            if n < 0 or n >= 2**bit_length:
                raise ValueError("Value out of range for the specified bit_length")
            if bit_length == 0:
                return ""
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

    # Promoted operators (C integer promotion). Binary ops compute on plain
    # values at full width and return plain int - no wrap-at-operator, which
    # is a behavior C does not have (C never wraps mid-expression; narrowing
    # happens only at stores/casts). The cast spelling is the constructor:
    # UInt8(a + b) wraps exactly like (uint8_t)(a + b). The bitwise family
    # promotes too - in C even ~uint8_t is an int. Compound assignment
    # narrows back into self's width, like C's a += b.

    # Annotations follow the promotion semantics: int-plane operands
    # (int/bool/Int) produce int; a float operand produces float (the
    # overload pairs); division is always float; ** may go float on a
    # negative exponent, so it is Any (as in typeshed's int.__pow__);
    # the bitwise family only accepts the int plane.

    @overload
    def __add__(self, other: int | Int) -> int: ...

    @overload
    def __add__(self, other: float | Float) -> float: ...

    def __add__(self, other):
        return self._promoted_value_op(other, operator.add)

    @overload
    def __radd__(self, other: int | Int) -> int: ...

    @overload
    def __radd__(self, other: float | Float) -> float: ...

    def __radd__(self, other):
        return self._promoted_value_op(other, lambda x, y: y + x)

    @overload
    def __sub__(self, other: int | Int) -> int: ...

    @overload
    def __sub__(self, other: float | Float) -> float: ...

    def __sub__(self, other):
        return self._promoted_value_op(other, operator.sub)

    @overload
    def __rsub__(self, other: int | Int) -> int: ...

    @overload
    def __rsub__(self, other: float | Float) -> float: ...

    def __rsub__(self, other):
        return self._promoted_value_op(other, lambda x, y: y - x)

    @overload
    def __mul__(self, other: int | Int) -> int: ...

    @overload
    def __mul__(self, other: float | Float) -> float: ...

    def __mul__(self, other):
        return self._promoted_value_op(other, operator.mul)

    @overload
    def __rmul__(self, other: int | Int) -> int: ...

    @overload
    def __rmul__(self, other: float | Float) -> float: ...

    def __rmul__(self, other):
        return self._promoted_value_op(other, lambda x, y: y * x)

    def __truediv__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, operator.truediv)

    def __rtruediv__(self, other: int | float | Int | Float) -> float:
        return self._promoted_value_op(other, lambda x, y: y / x)

    @overload
    def __floordiv__(self, other: int | Int) -> int: ...

    @overload
    def __floordiv__(self, other: float | Float) -> float: ...

    def __floordiv__(self, other):
        return self._promoted_value_op(other, operator.floordiv)

    @overload
    def __rfloordiv__(self, other: int | Int) -> int: ...

    @overload
    def __rfloordiv__(self, other: float | Float) -> float: ...

    def __rfloordiv__(self, other):
        return self._promoted_value_op(other, lambda x, y: y // x)

    @overload
    def __mod__(self, other: int | Int) -> int: ...

    @overload
    def __mod__(self, other: float | Float) -> float: ...

    def __mod__(self, other):
        return self._promoted_value_op(other, operator.mod)

    @overload
    def __rmod__(self, other: int | Int) -> int: ...

    @overload
    def __rmod__(self, other: float | Float) -> float: ...

    def __rmod__(self, other):
        return self._promoted_value_op(other, lambda x, y: y % x)

    def __pow__(self, other: int | float | Int | Float) -> Any:
        return self._promoted_value_op(other, operator.pow)

    def __rpow__(self, other: int | float | Int | Float) -> Any:
        return self._promoted_value_op(other, lambda x, y: y**x)

    def __and__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, operator.and_)

    def __rand__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, lambda x, y: y & x)

    def __or__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, operator.or_)

    def __ror__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, lambda x, y: y | x)

    def __xor__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, operator.xor)

    def __rxor__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, lambda x, y: y ^ x)

    def __lshift__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, operator.lshift)

    def __rlshift__(self, other: int | Int) -> int:
        return self._promoted_value_op(other, lambda x, y: y << x)

    def __rshift__(self, other: int | Int) -> int:  # type: ignore[override]
        return self._promoted_value_op(other, operator.rshift)

    def __rrshift__(self, other: int | Int) -> int:
        return self._promoted_value_op(other, lambda x, y: y >> x)

    def __invert__(self) -> int:  # type: ignore[override]
        # The classic C gotcha, faithfully: ~ promotes, so the result is
        # plain -(value + 1). The width-preserving spelling is ~self.bits.
        return ~self.value

    # Unary arithmetic promotes like the binary ops (in C, -uint8_t
    # computes in int): the result is the plain promoted value, and the
    # narrowing cast spelling is the constructor, e.g. UInt8(-u).
    # Mirrors Float.__neg__/__pos__/__abs__.

    def __neg__(self) -> int:
        return -self.value

    def __pos__(self) -> int:
        return +self.value

    def __abs__(self) -> int:
        return abs(self.value)

    # Ordering comparisons (value-based, like __eq__; new in the promotion
    # model - they previously did not exist at all).

    def __lt__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.lt)

    def __le__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.le)

    def __gt__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.gt)

    def __ge__(self, other: int | float | Int | Float) -> bool:
        return self._promoted_value_op(other, operator.ge)

    # Compound assignment: read-promote, compute full-width, narrowing store.
    # Type-preserving (returns self after the narrowing store). mypy reports
    # __i*__/__*__ as incompatible on the arithmetic ops because C compound
    # assignment deliberately diverges from the binary op: ``u += 1`` keeps
    # u's box type (narrowing store) while ``u + 1`` promotes to plain int.
    # The divergence is the intended D5 semantics, so ignore[misc] where it
    # is flagged.

    def __iadd__(  # type: ignore[misc]
        self: IntSelf, other: int | float | Int | Float
    ) -> IntSelf:
        return self._inplace_value_op(other, operator.add)

    def __isub__(  # type: ignore[misc]
        self: IntSelf, other: int | float | Int | Float
    ) -> IntSelf:
        return self._inplace_value_op(other, operator.sub)

    def __imul__(  # type: ignore[misc]
        self: IntSelf, other: int | float | Int | Float
    ) -> IntSelf:
        return self._inplace_value_op(other, operator.mul)

    def __itruediv__(self: IntSelf, other: int | float | Int | Float) -> IntSelf:
        return self._inplace_value_op(other, operator.truediv)

    def __ifloordiv__(  # type: ignore[misc]
        self: IntSelf, other: int | float | Int | Float
    ) -> IntSelf:
        return self._inplace_value_op(other, operator.floordiv)

    def __imod__(  # type: ignore[misc]
        self: IntSelf, other: int | float | Int | Float
    ) -> IntSelf:
        return self._inplace_value_op(other, operator.mod)

    def __ipow__(self: IntSelf, other: int | float | Int | Float) -> IntSelf:
        return self._inplace_value_op(other, operator.pow)

    def __iand__(self: IntSelf, other: int | Int) -> IntSelf:
        return self._inplace_value_op(other, operator.and_)

    def __ior__(self: IntSelf, other: int | Int) -> IntSelf:
        return self._inplace_value_op(other, operator.or_)

    def __ixor__(self: IntSelf, other: int | Int) -> IntSelf:
        return self._inplace_value_op(other, operator.xor)

    def __ilshift__(self: IntSelf, other: int | Int) -> IntSelf:
        return self._inplace_value_op(other, operator.lshift)

    def __irshift__(self: IntSelf, other: int | Int) -> IntSelf:
        return self._inplace_value_op(other, operator.rshift)


class SignedConfig:
    """
    A class to change the default representation and conversion for all
    non-user-implemented or non-user-specified signed integers
    simultaneously.

    If this is unadjusted, the default signed integer format is two's
    complement.
    """

    signed_int_format: Literal[
        "signed_magnitude", "ones_complement", "twos_complement"
    ] = "twos_complement"


class SInt(Int):
    """
    A BitType that represents a signed integer.

    Use the `specialize` method to create a subclass with the number of bits
    you need, or use one of the pre-defined subclasses.

    The default signed integer format is two's complement. Change it for a
    single instance through the constructor's `int_format` parameter, or for
    every otherwise-unspecified signed integer through the `SignedConfig`
    class.

    Class Attributes:
        base_bit_type : Type[BitType]
            The base class, which is `SInt` for `SInt` children.
        num_bits : int
            The number of bits in the integer.
        is_signed : bool
            Whether the integer is signed. It is True for SInts.

    Instance Attributes:
        int_format : Optional[str]
            The format for this signed integer. It can be
            "twos_complement", "signed_magnitude", or "ones_complement".
            Leaving it as `None` takes the format from the `SignedConfig`
            class, which itself defaults to "twos_complement".
        value : int
            The `int` value of the `SInt`.
        bits : BitVector
            The bits representing the value.
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
            int_format = SignedConfig.signed_int_format
        elif int_format == "sign_magnitude":  # alias accepted downstream
            int_format = "signed_magnitude"
        if int_format not in (
            "twos_complement",
            "signed_magnitude",
            "ones_complement",
        ):
            raise ValueError(
                f"int_format must be one of 'twos_complement',"
                f" 'signed_magnitude', or 'ones_complement';"
                f" got {int_format!r}"
            )

        self.int_format: Literal[
            "twos_complement", "signed_magnitude", "ones_complement"
        ] = int_format
        super().__init__(source=source, value=value, bits=bits, endianness=endianness)

    @property
    def value(self):
        return Int.to_pyint(self.bits.to01(), signed=True, bin_format=self.int_format)

    @value.setter
    def value(self, value):
        n = self.num_bits
        if self.int_format == "twos_complement":
            # C-style narrowing conversion: wrap into the signed range
            # (mod 2**n), matching (intN_t) truncation in C. The other
            # (non-two's-complement) formats have no C analogue and still
            # reject out-of-range values.
            value = _narrow_int(value, n, signed=True, target=type(self).__name__)
        str_bits = Int.to_bitstring(
            value, signed=True, bit_length=n, rep_format=self.int_format
        )
        self.bits = BitVector(str_bits)

    def __repr__(self):
        """
        Return a string that recreates this SInt when evaluated with the
        class name in scope.

        The repr appends `int_format` to the base `BitType` format. The same
        bits decode to different values under different signed formats, so a
        faithful reconstruction needs the format this instance was built
        with.

        Returns:
            str: ClassName(bits='<01 string>', endianness=..., int_format=...)
        """
        return (
            f"{self.__class__.__name__}(bits={self.bits.to01()!r},"
            f" endianness={self.endianness!r}, int_format={self.int_format!r})"
        )

    @classmethod
    def specialize(
        cls,
        num_bits_: int,
        packing_format_letter_: Optional[str] = None,
        name_: Optional[str] = None,
    ):
        """
        Produce a subclass of SInt with the specified number of bits.

        If a packing format letter is provided, the subclass will also be
        a StructPackedBitType and use struct's packing/unpacking functions
        with the provided letter.

        If ``name_`` is provided, the subclass will have that name
        internally after class creation. Otherwise, the subclass will be named _SInt.

        Args:
            num_bits_ (int): The number of bits in integers of this type.
            packing_format_letter_ (Optional[str], optional): The struct packing format
                letter to use, if any. Defaults to None, meaning no struct (un)packing.
            name_ (Optional[str], optional): What to rename the subclass, if anything.
                Defaults to None, meaning the subclass's name will be _SInt.

        Returns:
            type[SInt]: The subclass of SInt with the specified number of bits.
        """
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


class _StructPackedSInt(StructPackedBitType[int], SInt):
    """Shared base of the struct-packable signed widths (SInt8/16/32/64).

    struct's b/h/i/q letters are two's-complement only. Packing therefore
    applies exactly when this instance's own ``int_format`` is two's
    complement, which is the same per-instance gate that ``SInt.specialize``
    generates. Any other format falls back to the bit-string path on the
    MRO.
    """

    @property
    def skip_struct_packing(self):
        return self.int_format != "twos_complement"


class SInt8(_StructPackedSInt):
    _num_bits = 8
    packing_format_letter = "b"


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


class SInt16(_StructPackedSInt):
    _num_bits = 16
    packing_format_letter = "h"


class SInt32(_StructPackedSInt):
    _num_bits = 32
    packing_format_letter = "i"


class SInt64(_StructPackedSInt):
    _num_bits = 64
    packing_format_letter = "q"


class SInt128(SInt):
    _num_bits = 128


class SInt256(SInt):
    _num_bits = 256


class UInt(Int):
    """
    A BitType that represents an unsigned integer.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.

    Class Attributes:
        base_bit_type (Type[BitType]): The base class (this is UInt).
        num_bits (int): The number of bits in the integer.
        is_signed (bool): Whether the integer is signed. (This is False)

    Properties:
        value (int): The integer value of the bits.
        bits (BitVector): The bits representing the integer value.
    """

    is_signed = False

    @property
    def value(self):
        return int(self.bits.to01(), 2)

    @value.setter
    def value(self, value):
        # C-style narrowing conversion: keep the low num_bits bits
        # (value modulo 2**num_bits), so out-of-range values wrap instead
        # of raising, matching (uintN_t) truncation in C.
        masked = _narrow_int(
            value, self.num_bits, signed=False, target=type(self).__name__
        )
        str_bits = Int.to_bitstring(masked, signed=False, bit_length=self.num_bits)
        self.bits = BitVector(str_bits)

    @classmethod
    def specialize(
        cls,
        num_bits_: int,
        packing_format_letter_: Optional[str] = None,
        name_: Optional[str] = None,
    ):
        """
        Produce a subclass of UInt with the specified number of bits.

        If a packing format letter is provided, the subclass will also be
        a StructPackedBitType and use struct's packing/unpacking functions
        with the provided letter.

        If ``name_`` is provided, the subclass will have that name
        internally after class creation. Otherwise, the subclass will be named _UInt.

        Args:
            num_bits_ (int): The number of bits in integers of this type.
            packing_format_letter_ (Optional[str], optional): The struct packing format
                letter to use, if any. Defaults to None, meaning no struct (un)packing.
            name_ (Optional[str], optional): What to rename the subclass, if anything.
                Defaults to None, meaning the subclass's name will be _UInt.

        Returns:
            type[UInt]: The subclass of UInt with the specified number of bits.
        """
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


class UInt1(UInt):
    _num_bits = 1


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


class UInt8(StructPackedBitType[int], UInt):
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


class UInt16(StructPackedBitType[int], UInt):
    _num_bits = 16
    packing_format_letter = "H"


class UInt32(StructPackedBitType[int], UInt):
    _num_bits = 32
    packing_format_letter = "I"


class UInt64(StructPackedBitType[int], UInt):
    _num_bits = 64
    packing_format_letter = "Q"


class UInt128(UInt):
    _num_bits = 128


class UInt256(UInt):
    _num_bits = 256


__all__ = [
    "Int",
    "SInt",
    "UInt",
    "SignedConfig",
    "SInt1",
    "SInt2",
    "SInt3",
    "SInt4",
    "SInt5",
    "SInt6",
    "SInt7",
    "SInt8",
    "SInt9",
    "SInt10",
    "SInt11",
    "SInt12",
    "SInt13",
    "SInt14",
    "SInt15",
    "SInt16",
    "SInt32",
    "SInt64",
    "SInt128",
    "SInt256",
    "UInt1",
    "UInt2",
    "UInt3",
    "UInt4",
    "UInt5",
    "UInt6",
    "UInt7",
    "UInt8",
    "UInt9",
    "UInt10",
    "UInt11",
    "UInt12",
    "UInt13",
    "UInt14",
    "UInt15",
    "UInt16",
    "UInt32",
    "UInt64",
    "UInt128",
    "UInt256",
]
