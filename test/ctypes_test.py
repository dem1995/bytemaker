import pytest
from ctypes import c_int, c_uint, Structure, Union, Array, c_char
from bytemaker.native_types.ctypes_ import ctype_to_bytes, bytes_to_ctype


class TestStructure(Structure):
    _fields_ = [("field1", c_int), ("field2", c_uint)]


class TestUnion(Union):
    _fields_ = [("field1", c_int), ("field2", c_uint)]


class TestArray(Array):
    _type_ = c_char
    _length_ = 4


# Test converting ctypes to bytes
@pytest.mark.parametrize("ctype_obj, expected_bytes", [
    (c_int(42), b'\x2a\x00\x00\x00'),
    (TestStructure(1, 2), b'\x01\x00\x00\x00\x02\x00\x00\x00'),
])
def test_ctype_to_bytes(ctype_obj, expected_bytes):
    assert ctype_to_bytes(ctype_obj) == expected_bytes


# Test converting bytes to ctypes
@pytest.mark.parametrize("bytes_obj, ctype_type, expected_ctype_obj", [
    (b'\x2a\x00\x00\x00', c_int, c_int(42)),
    (b'\x01\x00\x00\x00\x02\x00\x00\x00', TestStructure, TestStructure(1, 2)),
])
def test_bytes_to_ctype(bytes_obj, ctype_type, expected_ctype_obj):
    ctype_instance = bytes_to_ctype(bytes_obj, ctype_type)
    if isinstance(ctype_instance, Structure):
        assert ctype_instance.field1 == expected_ctype_obj.field1
        assert ctype_instance.field2 == expected_ctype_obj.field2
    else:
        assert ctype_instance.value == expected_ctype_obj.value


# Test reversing endianness
@pytest.mark.parametrize("ctype_obj, expected_bytes_reversed", [
    (c_int(42), b'\x00\x00\x00\x2a'),
    (TestStructure(1, 2), b'\x00\x00\x00\x02\x00\x00\x00\x01'),
    # Add more cases for Union, Array, and different initial endianness
])
def test_reverse_endianness(ctype_obj, expected_bytes_reversed):
    assert ctype_to_bytes(ctype_obj, reverse_endianness=True) == expected_bytes_reversed


# Test invalid inputs
def test_invalid_ctype_to_bytes():
    with pytest.raises(TypeError):
        ctype_to_bytes(123)  # Not a ctype object


def test_invalid_bytes_to_ctype():
    with pytest.raises(TypeError):
        bytes_to_ctype(b'\x2a\x00\x00\x00', int)  # Not a ctype type
