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
    SInt16,
    SInt32,
    SInt64,
    Str8,
    Str16,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
)
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
