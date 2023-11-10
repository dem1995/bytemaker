import pytest
from bytemaker.native_types.pytypes import py_primitive_to_bits, bits_to_pytype, ConversionConfig
from bytemaker.bits import Bits

# Test cases for different types and values, including edge cases and subtypes
test_data = [
    # Integers
    (2, int, Bits([0, 1, 0])),  # Two's complement representation of 2
    (0, int, Bits([0])),
    (-1, int, Bits([1])),
    # Strings
    ("hello", str, Bits(b'hello')),  # Binary representation of "hello"
    ("", str, Bits(b'')),
    # Bytes
    (b'hello', bytes, Bits(b'hello')),  # Binary representation of b'hello'
    (b'', bytes, Bits(b'')),
    # Booleans
    (True, bool, Bits([1])),
    (False, bool, Bits([0])),
]


@pytest.mark.parametrize("python_value, value_type, expected_bits", test_data)
def test_py_primitive_to_bits(python_value, value_type, expected_bits):
    print(ConversionConfig._implemented_conversions)
    assert py_primitive_to_bits(python_value) == expected_bits


@pytest.mark.parametrize("python_value, value_type, bits_value", test_data)
def test_bits_to_pytype(python_value, value_type, bits_value):
    assert bits_to_pytype(bits_value, value_type) == python_value


# Test cases for different types and values, including edge cases and subtypes
test_data_approx = [
    # Floats
    (3.14, float,  # Binary representation of 3.14 as a float
     Bits('0b11000011_11110101_01001000_01000000').padleft(up_to_size=32, inplace=False)),
    (0.0, float, Bits('0b0').padleft(up_to_size=32, inplace=False)),
]

epsilon = 1e-6


@pytest.mark.parametrize("python_value, value_type, expected_bits", test_data_approx)
def test_py_primitive_to_bits_approx(python_value, value_type, expected_bits):
    print(ConversionConfig._implemented_conversions)
    assert py_primitive_to_bits(python_value) == expected_bits


@pytest.mark.parametrize("python_value, value_type, bits_value", test_data_approx)
def test_bits_to_pytype_approx(python_value, value_type, bits_value):
    assert bits_to_pytype(bits_value, value_type) - python_value < epsilon
