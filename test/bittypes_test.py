import pytest

from bytemaker.bittypes import (
    Buffer4,
    Buffer8,
    Buffer16,
    Buffer32,
    Buffer64,
    Float,
    Float32,
    Float64,
    SInt8,
    SInt10,
    SInt16,
    SInt32,
    SInt64,
    Str8,
    Str16,
    UInt8,
    UInt10,
    UInt16,
    UInt32,
    UInt64,
)
from bytemaker.bittypes.bittype import StructPackedBitType
from bytemaker.bitvector import BitVector

# from bytemaker.bittypes_old import Str8


@pytest.mark.parametrize(
    "bittype_class, constructor_arg, update_arg",
    [
        (UInt16, 2**16 - 1, 2**8),
        (SInt16, -(2**15), 2**8),
        (Float32, 3.1415926535, 2.7182818284),
        (Str8, "a", "b"),
        (
            Buffer8,
            BitVector([0, 1, 1, 1, 0, 1, 0, 1]),
            BitVector([1, 0, 1, 0, 1, 1, 1, 0]),
        ),
    ],
)
def test_cru_bittype(bittype_class, constructor_arg, update_arg):
    bittype_instance = bittype_class(constructor_arg)
    bittype_instance.value = update_arg
    if isinstance(bittype_instance, Float):
        assert abs(bittype_instance.value - update_arg) < 1e-6
    else:
        assert bittype_instance.value == update_arg


# Test cases for Unsigned Integers
@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits",
    [
        (UInt8, 255, BitVector([1] * 8)),
        (UInt16, 65535, BitVector([1] * 16)),
        (UInt32, 2**32 - 1, BitVector([1] * 32)),
        (UInt64, 2**64 - 1, BitVector([1] * 64)),
    ],
)
def test_uint_serialization(bittype_class, input_value, expected_bits):
    bittype_instance = bittype_class(input_value)
    assert bittype_instance.to_bits() == expected_bits


@pytest.mark.parametrize(
    "bittype_class, input_bits, expected_value",
    [
        (UInt8, BitVector([1] * 8), 255),
        (UInt16, BitVector([1] * 16), 65535),
        (UInt32, BitVector([1] * 32), 2**32 - 1),
        (UInt64, BitVector([1] * 64), 2**64 - 1),
    ],
)
def test_uint_deserialization(bittype_class, input_bits, expected_value):
    bittype_instance = bittype_class.from_bits(input_bits)
    assert bittype_instance.value == expected_value


# Test cases for Signed Integers
@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits_length",
    [
        (SInt8, -128, 8),
        (SInt16, -32768, 16),
        (SInt32, -2147483648, 32),
        (SInt64, -9223372036854775808, 64),
    ],
)
def test_sint_serialization(bittype_class, input_value, expected_bits_length):
    bittype_instance = bittype_class(input_value)
    assert len(bittype_instance.to_bits()) == expected_bits_length


# Test cases for Floats
@pytest.mark.parametrize(
    "bittype_class, input_value",
    [
        (Float32, 1.0),
        (Float64, 1.0),
        (Float32, -1.0),
        (Float64, -1.0),
        (Float32, 3.1415926535),
        (Float64, 3.1415926535),
    ],
)
def test_float_serialization_and_deserialization(bittype_class, input_value):
    bittype_instance = bittype_class(input_value)
    deserialized_value = bittype_class.from_bits(bittype_instance.to_bits()).value
    assert abs(deserialized_value - input_value) < 1e-6


# Test cases for Strings
@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits_length",
    [
        (Str8, "a", 8),
        (Str16, "ef", 16),
    ],
)
def test_str_serialization_and_deserialization(
    bittype_class, input_value, expected_bits_length
):
    bittype_instance = bittype_class(input_value)
    assert len(bittype_instance.to_bits()) == expected_bits_length
    deserialized_value = bittype_class.from_bits(bittype_instance.to_bits()).value
    assert deserialized_value == input_value


@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits",
    [
        (Str8, "a", BitVector([0, 1, 1, 0, 0, 0, 0, 1])),
        (Str16, "ef", BitVector([0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0])),
    ],
)
def test_str_endianess(bittype_class, input_value, expected_bits):
    bittype_instance = bittype_class(input_value)
    assert bittype_instance.to_bits() == expected_bits

    # little endian
    bittype_instance = bittype_class(input_value, endianness="little")
    reversed_chunks = bytes(reversed(bytes(expected_bits)))

    assert bytes(bittype_instance) == reversed_chunks


@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits_length",
    [
        (Buffer4, BitVector([0, 1, 1, 1]), BitVector([0, 1, 1, 1])),
        (
            Buffer8,
            BitVector([0, 1, 1, 1, 0, 1, 0, 1]),
            BitVector([0, 1, 1, 1, 0, 1, 0, 1]),
        ),
        (
            Buffer16,
            BitVector([0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1]),
            BitVector([0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1]),
        ),
        (
            Buffer32,
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
            # fmt: on
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
        ),
        (
            Buffer64,
            # fmt: on
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
            # fmt: on
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
            # fmt: on
        ),
    ],
)
def test_bit_serialization_and_deserialization(
    bittype_class, input_value, expected_bits_length
):
    bittype_instance = bittype_class(input_value)
    bittype_instance_type = type(bittype_instance)
    print("BitType instance is:", bittype_instance)
    print("BitType instance type is:", bittype_instance_type)
    assert bittype_instance.to_bits() == expected_bits_length
    deserialized_value = bittype_class.from_bits(bittype_instance.to_bits()).value
    assert deserialized_value == input_value


class UInt12Packed(StructPackedBitType, UInt16.__mro__[2]):
    """A 12-bit unsigned int that uses struct packing with 'H' (unsigned short).
    Used to test StructPackedBitType.value padding for non-multiple-of-8 bit counts."""

    _num_bits = 12
    base_bit_type = UInt16.__mro__[2]
    py_type = int
    packing_format_letter = "H"


def test_struct_packed_bittype_non_byte_aligned_value():
    """Regression test: StructPackedBitType.value must pad bits to a byte
    boundary before calling struct.unpack. Previously it computed the
    padded bits into a local variable but then passed the unpadded
    self.bits to struct.unpack instead."""
    from bytemaker.bitvector import BitVector

    # 12 bits representing the value 42: 000000101010
    bits_42 = BitVector("0b000000101010")
    instance = UInt12Packed(bits=bits_42)
    assert instance.value == 42


def test_uint_non_struct_value_setter_zero_pads():
    """Regression test: the non-struct UInt.value setter must produce exactly
    num_bits, zero-padded, through the validating bits property. Previously it
    assigned BitVector(bin(value)[2:]) straight to self._bits, yielding
    minimal-width bits (UInt10(1).bits had length 1, not 10) and breaking
    aggregate serialization."""
    u = UInt10(1)
    assert len(u.bits) == UInt10.num_bits == 10
    assert u.bits.to01() == "0000000001"
    assert u.value == 1
    assert len(u.to_bits()) == 10

    # zero and the maximum stay full-width and round-trip through the bits
    assert len(UInt10(0).bits) == 10
    hi = UInt10(2**10 - 1)
    assert len(hi.bits) == 10 and hi.value == 2**10 - 1
    assert UInt10.from_bits(hi.to_bits()).value == 2**10 - 1

    # out-of-range values wrap modulo 2**num_bits, like a C (uint10_t) cast
    u.value = 2**10  # 1024 -> 0
    assert u.value == 0 and len(u.bits) == 10
    u.value = 2**10 + 5  # 1029 -> 5
    assert u.value == 5
    u.value = -1  # -> 1023 (all ones), like (uint10_t)(-1)
    assert u.value == 2**10 - 1


def test_sint_non_struct_value_setter_wraps_like_c():
    """The non-struct (two's-complement) SInt.value setter narrows an
    out-of-range value by truncation, matching a C (int10_t) cast, rather
    than raising."""
    s = SInt10(0, int_format="twos_complement")
    assert len(s.bits) == 10

    s.value = 2**9  # 512 overflows the top of [-512, 511] -> -512
    assert s.value == -(2**9)
    s.value = -(2**9) - 1  # -513 underflows -> 511
    assert s.value == 2**9 - 1
    assert len(s.bits) == 10
