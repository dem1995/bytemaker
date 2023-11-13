
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
    assert some_bits.to_int() == -3

    assert Bits().bitlist == []


# Test the string representation of Bits
def test_bits_str(some_bits):
    assert str(some_bits) == '0b101'


# Test the append method
def test_bits_append(some_bits):
    new_some_bits = some_bits.append(1, inplace=False)
    assert str(new_some_bits) == '0b1011'
    assert str(some_bits) == '0b101'

    some_bits.append(1, inplace=True)
    assert str(some_bits) == '0b1011'


# Test padding
def test_bits_padright(some_bits):
    new_some_bits = some_bits.padright(up_to_size=5, inplace=False)
    assert str(new_some_bits) == '0b10100'
    assert str(some_bits) == '0b101'

    some_bits.padright(up_to_size=5, inplace=True)
    assert str(some_bits) == '0b10100'


def test_bits_padleft(some_bits):
    new_some_bits = some_bits.padleft(up_to_size=5, inplace=False)
    assert str(new_some_bits) == '0b00101'
    assert str(some_bits) == '0b101'

    some_bits.padleft(up_to_size=5, inplace=True)
    assert str(some_bits) == '0b00101'


# Test the pop method
def test_bits_pop(some_bits, byte_bits):
    bit = some_bits.pop(inplace=False)
    assert bit == 1
    assert str(some_bits) == '0b101'

    bit = byte_bits.pop(2, inplace=False)
    assert bit == 1
    assert str(byte_bits) == '0b10100000'

    bit = some_bits.pop(inplace=True)
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


def test_bits_from_str():
    bits = Bits('0b101')
    assert bits.bitlist == [1, 0, 1]
    bits = Bits('0b1_01')
    assert bits.bitlist == [1, 0, 1]

    bits = Bits('0xFE')
    assert bits.bitlist == [1, 1, 1, 1, 1, 1, 1, 0]


# Test the to_int method
def test_bits_to_int():
    pos_num = Bits('0b0101')
    assert pos_num.to_int() == 5

    neg_num = Bits('0b101')
    assert Bits(neg_num).to_int() == -3

    neg_num = Bits('0b10101')
    assert Bits(neg_num).to_int() == -11

    assert Bits('0b1_01').to_int() == -3


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


def test_bits_join():
    bits0 = Bits([1, 0, 1, 1, 0])
    bits1 = Bits([1, 1, 0, 0])
    bits2 = Bits([0, 1, 1, 1])

    bits3 = Bits().join([bits0, bits1, bits2])
    assert bits3.bitlist == [1, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 1]

    bits4 = Bits().join([])
    assert bits4.bitlist == []

    bits5 = Bits().join([bits0])
    assert bits5.bitlist == [1, 0, 1, 1, 0]

    bits6 = bits0.join([bits1, bits2, bits1])
    assert bits6.bitlist == [
        1, 1, 0, 0,
        1, 0, 1, 1, 0,
        0, 1, 1, 1,
        1, 0, 1, 1, 0,
        1, 1, 0, 0
    ]


# def test_bits_concat():
#     bits1 = Bits([1, 1, 0, 0])
#     bits2 = Bits([0, 1, 1, 1])

#     bits2_5 = bits1.concat(bits2)
#     assert bits2_5.bitlist == [1, 1, 0, 0, 0, 1, 1, 1]

#     bits3 = Bits.concat(bits1, bits2)
#     assert bits3.bitlist == [1, 1, 0, 0, 0, 1, 1, 1]

#     bits4 = Bits.concat(bits3, bits3, bits3)
#     assert bits4.bitlist == [1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1]

#     bits5 = Bits.concat()
#     assert bits5.bitlist == []
