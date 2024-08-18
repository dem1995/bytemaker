import pytest

from bytemaker.bitvector import BitVector


# Fixture for an empty BitVector instance
@pytest.fixture
def empty_bits():
    return BitVector([])


# Fixture for a BitVector instance with some data
@pytest.fixture
def some_bits():
    return BitVector([1, 0, 1])


# Fixture for a BitVector instance representing a byte
@pytest.fixture
def byte_bits():
    return BitVector([1, 0, 1, 0, 0, 0, 0, 0])


# Test the initialization of the BitVector class
def test_bits_init(empty_bits, some_bits):
    # Test with empty initialization
    assert list(empty_bits) == []

    # Test with some bit data
    assert list(some_bits) == [1, 0, 1]


# Test the string representation of BitVector
def test_bits_str(some_bits):
    assert str(some_bits) == "BitVector('101')"


# Test the append method
def test_bits_append(some_bits):
    assert some_bits.bin() == "0b101"
    some_bits.append(1)
    assert some_bits.bin() == "0b1011"

    # some_bits.append(1, inplace=True)
    # assert str(some_bits) == "0b1011"


# Test padding
def test_bits_padright(some_bits):
    new_some_bits = some_bits.rpad(width=5)
    assert new_some_bits.bin() == "0b10100"
    assert some_bits.bin() == "0b101"

    # some_bits.padright(up_to_size=5, inplace=True)
    # assert str(some_bits) == "0b10100"


def test_bits_lpad(some_bits):
    new_some_bits = some_bits.lpad(width=5)
    assert new_some_bits.bin() == "0b00101"
    assert some_bits.bin() == "0b101"

    # some_bits.padleft(up_to_size=5, inplace=True)
    # assert str(some_bits) == "0b00101"


# Test the pop method
def test_bits_pop(some_bits, byte_bits):
    bit = some_bits.pop()
    assert bit == 1
    assert some_bits.bin() == "0b10"

    bit = byte_bits.pop(2)
    assert bit == 1
    assert byte_bits.bin() == "0b1000000"

    # bit = some_bits.pop(inplace=True)
    # assert bit == 1
    # assert str(some_bits) == "0b10"


# Test the to_bytes method
def test_bits_to_bytes(byte_bits):
    print(byte_bits)
    # print(byte_bits)
    [print(bit) for bit in byte_bits]
    assert byte_bits.to_bytes() == b"\xa0"


# Test the from_bytes class method
def test_bits_from_bytes():
    bits = BitVector(b"\xa0")
    bits_right = [int(i) for i in bin(160)[2:].zfill(len(bits))]
    assert list(bits) == bits_right


def test_bits_from_str():
    bits = BitVector("0b101")
    assert list(bits) == [1, 0, 1]
    bits = BitVector("0b1_01")
    assert list(bits) == [1, 0, 1]
    bits = BitVector("101")
    assert list(bits) == [1, 0, 1]

    bits = BitVector("01_10 11:11 0-0-0-0")
    assert list(bits) == [0, 1, 1, 0, 1, 1, 1, 1, 0, 0, 0, 0]

    bits = BitVector("0xFE")
    assert list(bits) == [1, 1, 1, 1, 1, 1, 1, 0]

    bits1 = BitVector("0x0000_0F0F")
    bits2 = BitVector("0x00000F0F")
    assert bits1 == bits2

    bits = BitVector("0x00000f0f")
    # fmt: off
    assert list(bits) == [
        0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 1, 1, 1, 1,
        0, 0, 0, 0, 1, 1, 1, 1,
    ]
    # fmt: on
    assert bits.hex().replace("_", "") == "0x00000f0f"

    bits = BitVector("0o707")
    assert list(bits) == [1, 1, 1, 0, 0, 0, 1, 1, 1]


# def test_bits_from_int():
#     integer = 5
#     bits = BitVector.from_int(integer)
#     assert bits.to01() == [0, 1, 0, 1]

#     bits = BitVector.from_int(integer, 32)
#     # fmt: off
#     assert bits.to01() == [
#         0, 0, 0, 0, 0, 0, 0, 0,
#         0, 0, 0, 0, 0, 0, 0, 0,
#         0, 0, 0, 0, 0, 0, 0, 0,
#         0, 0, 0, 0, 0, 1, 0, 1,
#     ]
#     # fmt: on


# # Test the to_int method
# def test_bits_to_int():
#     pos_num = BitVector("0b0101")
#     assert pos_num.to_int() == 5

#     neg_num = BitVector("0b101")
#     assert BitVector(neg_num).to_int() == -3

#     neg_num = BitVector("0b10101")
#     assert BitVector(neg_num).to_int() == -11

#     assert BitVector("0b1_01").to_int() == -3


# Test the equality method
def test_bits_eq(some_bits):
    bits2 = BitVector([1, 0, 1])
    assert some_bits == bits2

    bits3 = BitVector([0, 1, 1])
    assert some_bits != bits3

    nonbits = 51
    assert some_bits != nonbits


# # Test the shrinkequals method
# def test_bits_shrinkequals():
#     bits1 = BitVector([1, 1, 0, 0])
#     bits2 = BitVector([0, 1, 1, 1])
#     assert not bits1 == bits2


def test_bits_join():
    bits0 = BitVector([1, 0, 1, 1, 0])
    bits1 = BitVector([1, 1, 0, 0])
    bits2 = BitVector([0, 1, 1, 1])

    bits3 = BitVector().join([bits0, bits1, bits2])
    assert list(bits3) == [1, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 1]

    bits4 = BitVector().join([])
    assert list(bits4) == []

    bits5 = BitVector().join([bits0])
    assert list(bits5) == [1, 0, 1, 1, 0]

    bits6 = bits0.join([bits1, bits2, bits1])
    # fmt: off
    assert list(bits6) == [
        1, 1, 0, 0, 1, 0, 1, 1,
        0, 0, 1, 1, 1, 1, 0, 1,
        1, 0, 1, 1, 0, 0,
    ]
    # fmt: on


# def test_bits_concat():
#     bits1 = BitVector([1, 1, 0, 0])
#     bits2 = BitVector([0, 1, 1, 1])

#     bits2_5 = bits1.concat(bits2)
#     assert bits2_5.to01() == [1, 1, 0, 0, 0, 1, 1, 1]

#     bits3 = BitVector.concat(bits1, bits2)
#     assert bits3.to01() == [1, 1, 0, 0, 0, 1, 1, 1]

#     bits4 = BitVector.concat(bits3, bits3, bits3)
#     assert bits4.to01() == \
#   [1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1]

#     bits5 = BitVector.concat()
#     assert bits5.to01() == []
