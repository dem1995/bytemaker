
import typing
from bytemaker.utils import is_instance_of_union, is_subclass_of_union, ByteConvertible, twos_complement_bit_length
import pytest


# Test for is_instance_of_union
@pytest.mark.parametrize("obj, union_type, expected", [
    (10, typing.Union[int, str], True),
    ("hello", typing.Union[int, str], True),
    (10.5, typing.Union[int, str], False),
    ([], typing.Union[int, str], False),
    (10, int, True)  # Non-union type should still return True for isinstance
])
def test_is_instance_of_union(obj, union_type, expected):
    assert is_instance_of_union(obj, union_type) == expected


# Test for is_subclass_of_union
@pytest.mark.parametrize("obj_type, union_type, expected", [
    (int, typing.Union[int, str], True),
    (str, typing.Union[int, str], True),
    (float, typing.Union[int, str], False),
    (list, typing.Union[int, str], False),
    (int, int, True)  # Non-union type should still return True for issubclass
])
def test_is_subclass_of_union(obj_type, union_type, expected):
    assert is_subclass_of_union(obj_type, union_type) == expected


# Test for ByteConvertible
def test_byte_convertible_instance():
    assert isinstance(b"", ByteConvertible)
    assert isinstance(bytearray(), ByteConvertible)
    assert not isinstance("string", ByteConvertible)


def test_byte_convertible_subclass():
    assert issubclass(bytes, ByteConvertible)
    assert issubclass(bytearray, ByteConvertible)
    assert not issubclass(str, ByteConvertible)


# Test for signed_bit_length
@pytest.mark.parametrize("integer, expected", [
    (0, 1),
    (1, 2),
    (-1, 1),
    (2, 3),
    (-2, 2),
    (2**7, 9),
    (-2**7, 8),
    (2**16, 18),
    (-(2**16), 17)
])
def test_twos_complement_bit_length(integer, expected):
    assert twos_complement_bit_length(integer) == expected
