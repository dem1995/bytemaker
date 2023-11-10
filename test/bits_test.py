
from bytemaker.bits import Bits
import pytest


# Fixture for an empty Bits instance
@pytest.fixture
def empty_bits():
    return Bits([])


# Fixture for a Bits instance with some data
@pytest.fixture
def some_bits():
    return Bits([1, 0, 1])


# Fixture for a Bits instance representing a byte
@pytest.fixture
def byte_bits():
    return Bits([1, 0, 1, 0, 0, 0, 0, 0])


# Test the initialization of the Bits class
def test_bits_init(empty_bits, some_bits):
    # Test with empty initialization
    assert empty_bits.to_int() == 0

    # Test with some bit data
    assert some_bits.to_int() == 5


# Test the string representation of Bits
def test_bits_str(some_bits):
    assert str(some_bits) == '0b101'


# Test the append method
def test_bits_append(some_bits):
    some_bits.append(1)
    assert str(some_bits) == '0b1011'


# Test padding
def test_bits_padright(some_bits):
    some_bits.padright(2)
    assert str(some_bits) == '0b10100'


def test_bits_padleft(some_bits):
    some_bits.padleft(2)
    assert str(some_bits) == '0b00101'


# Test the pop method
def test_bits_pop(some_bits):
    bit = some_bits.pop()
    assert bit == 1
    assert str(some_bits) == '0b10'


# Test the to_bytes method
def test_bits_to_bytes(byte_bits):
    print(byte_bits)
    print(int(byte_bits))
    [print(bit) for bit in byte_bits]
    assert byte_bits.to_bytes() == b'\xa0'


# Test the from_bytes class method
def test_bits_from_bytes():
    bits = Bits.from_bytes(b'\xa0')
    bits_right = [int(i) for i in bin(160)[2:].zfill(len(bits))]
    assert (bits.bitlist == bits_right)


# Test the to_int method
def test_bits_to_int(byte_bits):
    assert byte_bits.to_int() == 160


# Test the equality method
def test_bits_eq(some_bits):
    bits2 = Bits([1, 0, 1])
    assert some_bits == bits2

    bits3 = Bits([0, 1, 1])
    assert some_bits != bits3


# Test the shrinkequals method
def test_bits_shrinkequals():
    bits1 = Bits([1, 1, 0, 0])
    bits2 = Bits([0, 1, 1, 1])
    assert not bits1.shrinkequals(bits2)
