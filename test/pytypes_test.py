import pytest

from bytemaker.bits import Bits
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
    (2, int, Bits([0, 1, 0])),  # Two's complement representation of 2
    (0, int, Bits([0])),
    (-1, int, Bits([1])),
    # Strings
    # ("hello", str, Bits(b'hello')),  # Binary representation of "hello"
    ("a", str, Bits(b"a")),
    # Bytes
    # (b'hello', bytes, Bits(b'hello')),  # Binary representation of b'hello'
    # (b'', bytes, Bits(b'')),
    # Booleans
    (True, bool, Bits([1])),
    (False, bool, Bits([0])),
]


@pytest.mark.parametrize("python_value, value_type, expected_bits", test_data)
def test_pytype_to_bits(python_value, value_type, expected_bits):
    print(ConversionConfig._implemented_conversions)
    if value_type == int:
        assert pytype_to_bits(python_value) == expected_bits.padleft(
            up_to_size=32, inplace=False, padvalue=0 if python_value >= 0 else 1
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
        Bits("0b01000000_01001000_11110101_11000011").padleft(
            up_to_size=32, inplace=False
        ),
    ),
    (0.0, float, Bits("0b0").padleft(up_to_size=32, inplace=False)),
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
    assert pytype_to_bits(testval) == Bits([0, 1, 1]).padleft(
        up_to_size=32, inplace=False
    )
    assert bits_to_pytype(Bits([0, 0, 0, 1, 1]), ThreeInt) == 3

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
