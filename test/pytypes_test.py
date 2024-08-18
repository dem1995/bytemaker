import pytest

from bytemaker.bitvector import BitVector
from bytemaker.native_types.pytypes import (
    ConversionConfig,
    PyType,
    bits_to_pytype,
    pytype_to_bits,
)
from bytemaker.utils import is_subclass_of_union

# Test cases for different types and values, including edge cases and subtypes
test_data = [
    # Integers
    (2, int, BitVector([0, 1, 0])),  # Two's complement representation of 2
    (0, int, BitVector([0])),
    (-1, int, BitVector([1])),
    # Strings
    # ("hello", str, BitVector(b'hello')),  # Binary representation of "hello"
    ("a", str, BitVector(b"a")),
    # Bytes
    # (b'hello', bytes, BitVector(b'hello')),  # Binary representation of b'hello'
    # (b'', bytes, BitVector(b'')),
    # Booleans
    (True, bool, BitVector([1])),
    (False, bool, BitVector([0])),
]


@pytest.mark.parametrize("python_value, value_type, expected_bits", test_data)
def test_pytype_to_bits(python_value, value_type, expected_bits):
    print(ConversionConfig._implemented_conversions)
    if value_type == int:
        assert pytype_to_bits(python_value) == expected_bits.lpad(
            32, fillbit=0 if python_value >= 0 else 1
        )
    else:
        assert pytype_to_bits(python_value) == expected_bits


@pytest.mark.parametrize("python_value, value_type, bits_value", test_data)
def test_bits_to_pytype(python_value, value_type, bits_value):
    assert bits_to_pytype(bits_value, value_type) == python_value


# Test cases for different types and values, including edge cases and subtypes
test_data_approx = [
    # Floats
    (
        3.14,
        float,  # Binary representation of 3.14 as a float
        BitVector("0b01000000_01001000_11110101_11000011").lpad(width=32),
    ),
    (0.0, float, BitVector("0b0").lpad(width=32)),
]

epsilon = 1e-6


@pytest.mark.parametrize("python_value, value_type, expected_bits", test_data_approx)
def test_pytype_to_bits_approx(python_value, value_type, expected_bits):
    print(ConversionConfig._implemented_conversions)
    assert pytype_to_bits(python_value) == expected_bits


@pytest.mark.parametrize("python_value, value_type, bits_value", test_data_approx)
def test_bits_to_pytype_approx(python_value, value_type, bits_value):
    assert bits_to_pytype(bits_value, value_type) - python_value < epsilon


class ThreeInt(int):
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls, 3)


test_types = [
    (int, True),
    (str, True),
    (bytes, False),
    (bool, True),
    (float, True),
    (list, False),
    (dict, False),
    (tuple, False),
    (set, False),
    (frozenset, False),
    (type, False),
    (ThreeInt, True),
]


@pytest.mark.parametrize("a_type, is_pytype", test_types)
def test_pytype_finding(a_type, is_pytype):
    assert is_subclass_of_union(a_type, PyType) == is_pytype


def test_subclass_pytype():
    assert issubclass(ThreeInt, PyType)

    testval = ThreeInt(5)
    assert pytype_to_bits(testval) == BitVector([0, 1, 1]).lpad(width=32)
    assert bits_to_pytype(BitVector([0, 0, 0, 1, 1]), ThreeInt) == 3

    assert ConversionConfig._known_furthest_descendant_mappings[ThreeInt] == int


type_sizes = [
    (int, 32),
    (str, 8),
    (float, 32),
    (bool, 1),
]


@pytest.mark.parametrize("a_type, size", type_sizes)
def test_type_sizes(a_type, size):
    assert ConversionConfig.get_conversion_info(a_type).num_bits == size
