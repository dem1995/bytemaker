# flake8: noqa
import copy

import pytest

from bytemaker.BitArray import BitArray


@pytest.fixture
def empty_bitarray():
    return BitArray()


def test_empty_initialization(empty_bitarray):
    assert len(empty_bitarray) == 0


# region Initialization with various sources
# BitArray(source)
source_to_bits = (
    "source,expected_bin",
    [
        (10, "0" * 10),  # Integer source
        ("1010", "1010"),  # Binary string
        (b"\xA5", "10100101"),  # Bytes-like object
        ([1, 0, 1, 0], "1010"),  # List of bits
        ((1, 0, 1, 0), "1010"),  # Tuple of bits
        (BitArray("1010"), "1010"),  # Another BitArray
        ("0b1010", "1010"),  # Binary string with prefix
    ],
)


@pytest.mark.parametrize(*source_to_bits)
def test_initialization_with_various_sources(source, expected_bin):
    bit_array = BitArray(source)
    assert bit_array.to01() == expected_bin

    bit_array_little_endian = BitArray(source, endianness="little")
    assert bit_array_little_endian.to01() == expected_bin


@pytest.mark.parametrize(
    "source,expected_exception",
    [
        ([1.0, 2.0], Exception),  # Unsupported type
        ({1, 2, 3}, Exception),  # Another unsupported type
    ],
)
def test_invalid_source_type(source, expected_exception):
    with pytest.raises(expected_exception):
        BitArray(source)


# @pytest.mark.parametrize(
#     "source,expected_exception",
#     [
#         ([1.0, 2.0], TypeError),  # Unsupported type
#         ({1, 2, 3}, TypeError)    # Another unsupported type
#     ]
# )
# def test_invalid_source_type(source, expected_exception):
#     with pytest.raises(expected_exception):
#         BitArray(source)

# endregion Initialization with various sources

# region Conversions


# From Conversions
# fromhex
@pytest.mark.parametrize(
    "hex_str,expected_bin",
    [
        ("A5", "10100101"),
        ("FF", "11111111"),
        ("00", "00000000"),
        ("00FF", "0000000011111111"),
    ],
)
def test_from_hex(hex_str, expected_bin):
    bit_array = BitArray.fromhex(hex_str)
    assert bit_array.to01() == expected_bin
    assert bit_array.endianness == "big"

    bit_array_little_endian = BitArray.fromhex(hex_str, endianness="little")

    # if len(expected_bin) > 8 and len(expected_bin) <= 16:
    #     expected_bin_little_endian = expected_bin[8:] + expected_bin[:8]
    # elif len(expected_bin) <= 8:
    #     expected_bin_little_endian = expected_bin
    # else:
    #     raise ValueError("Invalid expected binary string. Longer than anticipated")

    # the provided binary string to the constructor is internal
    # endianness is only a tracker excepting
    # conversions to/from strings and ints
    expected_bin_little_endian = expected_bin
    assert bit_array_little_endian.to01() == expected_bin_little_endian
    assert bit_array_little_endian.endianness == "little"


# fromoct
@pytest.mark.parametrize(
    "oct_str,expected_bin", [("12", "001010"), ("75", "111101"), ("0", "000")]
)
def test_from_octal(oct_str, expected_bin):
    bit_array = BitArray.fromoct(oct_str)
    assert bit_array.to01() == expected_bin
    assert bit_array.endianness == "big"

    bit_array_little_endian = BitArray.fromoct(oct_str, endianness="little")
    assert bit_array_little_endian.to01() == expected_bin
    assert bit_array_little_endian.endianness == "little"


# frombin
@pytest.mark.parametrize(
    "bin_str,expected_bin", [("1010", "1010"), ("0001", "0001"), ("1111", "1111")]
)
def test_from_bin(bin_str, expected_bin):
    bit_array = BitArray.frombin(bin_str)
    assert bit_array.to01() == expected_bin
    assert bit_array.endianness == "big"

    bit_array_little_endian = BitArray.frombin(bin_str, endianness="little")
    assert bit_array_little_endian.to01() == expected_bin
    assert bit_array_little_endian.endianness == "little"


# frombase
@pytest.mark.parametrize(
    "base_str,base,expected_bin",
    [("10", 2, "10"), ("12", 8, "001010"), ("A", 16, "1010")],
)
def test_frombase(base_str, base, expected_bin):
    bit_array = BitArray.frombase(base_str, base)
    assert bit_array.to01() == expected_bin
    assert bit_array.endianness == "big"

    bit_array_little_endian = BitArray.frombase(base_str, base, endianness="little")
    assert bit_array_little_endian.to01() == expected_bin
    assert bit_array_little_endian.endianness == "little"


# fromchararray
@pytest.mark.parametrize(
    "char_str,encoding,expected_bin",
    [
        ("A", "utf-8", "01000001"),  # 'A' in UTF-8
        ("あ", "utf-8", "11100011 10000001 10000010"),  # 'あ' (Japanese Hiragana)
    ],
)
def test_from_chararray(char_str, encoding, expected_bin):
    bit_array = BitArray.from_chararray(char_str, encoding)
    print("bit_array_01, big", bit_array.to01())
    assert bit_array.to01() == expected_bin.replace(" ", "")
    assert bit_array.endianness == "big"

    bit_array_little_endian = BitArray.from_chararray(
        char_str, encoding, endianness="little"
    )
    # flip sets of 8 bits
    expected_bin = expected_bin.replace(" ", "")
    expected_bin_little_endian = "".join(
        [expected_bin[i : i + 8] for i in range(0, len(expected_bin), 8)][::-1]
    )
    print("bit_array_01, little", bit_array_little_endian.to01())
    assert bit_array_little_endian.to01() == expected_bin_little_endian
    assert bit_array_little_endian.endianness == "little"


# To Conversions
# hex
@pytest.mark.parametrize(
    "bit_array,expected_hex",
    [
        (BitArray("10100101"), "0xa5"),
        (BitArray("11111111"), "0xff"),
        (BitArray("00000000"), "0x00"),
    ],
)
def test_to_hex(bit_array, expected_hex):
    assert bit_array.hex() == expected_hex


# oct
@pytest.mark.parametrize(
    "bit_array,expected_oct",
    [
        (BitArray("001010"), "0o12"),
        (BitArray("111101"), "0o75"),
        (BitArray("000"), "0o0"),
    ],
)
def test_to_oct(bit_array, expected_oct):
    assert bit_array.oct() == expected_oct


# bin
@pytest.mark.parametrize(
    "bit_array,expected_bin",
    [
        (BitArray("1010"), "0b1010"),
        (BitArray("0001"), "0b0001"),
        (BitArray("1111"), "0b1111"),
    ],
)
def test_to_bin(bit_array, expected_bin):
    assert bit_array.bin() == expected_bin


# tobase
@pytest.mark.parametrize(
    "bit_array,base,expected_base",
    [
        (BitArray("10"), 2, "10"),
        (BitArray("001010"), 8, "12"),
        (BitArray("1010"), 16, "a"),
    ],
)
def test_tobase(bit_array, base, expected_base):
    assert bit_array.tobase(base) == expected_base


# tochararray
@pytest.mark.parametrize(
    "bit_array,encoding,expected_str",
    [
        (BitArray("01000001"), "utf-8", "A"),
        (
            BitArray("11100011 10000001 10000010"),
            "utf-8",
            "あ",
        ),  # Adjust based on actual encoding output
    ],
)
def test_to_chararray(bit_array, encoding, expected_str):
    assert bit_array.to_chararray(encoding) == expected_str


# endregion Conversions

# region Magic Methods


# Equality and Inequality
# __eq__, __ne__
@pytest.mark.parametrize(
    "array1,array2,equal",
    [
        (BitArray("1010"), BitArray("1010"), True),
        (BitArray("1111"), BitArray("1010"), False),
    ],
)
def test_equality(array1, array2, equal):
    assert (array1 == array2) == equal
    assert (array1 != array2) != equal


# Relational Operators
# __lt__, __le__, __gt__, __ge__
@pytest.mark.parametrize(
    "array1,array2,less_than,greater_than",
    [
        (BitArray("1010"), BitArray("1111"), True, False),
        (BitArray("1111"), BitArray("1010"), False, True),
    ],
)
def test_relational_operators(array1, array2, less_than, greater_than):
    assert (array1 < array2) == less_than
    assert (array1 > array2) == greater_than
    assert (array1 <= array2) == (less_than or array1 == array2)
    assert (array1 >= array2) == (greater_than or array1 == array2)


# Arithmetic Operators
# __add__, __iadd__, __mul__, __imul__, __radd__, __rmul__
def test_arithmetic_operators():
    a = BitArray("1010")
    b = BitArray("0101")
    assert a + b == BitArray("10100101")
    assert b * 2 == BitArray("01010101")

    a += b
    assert a == BitArray("10100101")
    b *= 2
    assert b == BitArray("01010101")

    # radd and rmul
    assert [1] + a == BitArray("110100101")
    assert 2 * ([1] + a) == BitArray("110100101 110100101")


# Iteration and Containment
# __iter__, __contains__
def test_iteration_and_containment():
    a = BitArray("1010")
    assert list(a) == [1, 0, 1, 0]
    assert 1 in a
    assert 0 in a
    print(a.to01())
    # with pytest.raises(ValueError):
    assert 2 not in a
    b = BitArray("1111")
    assert 1 in b
    assert 0 not in b
    # with pytest.raises(ValueError):
    assert 2 not in a


# Indexing and Slicing
# __getitem__
@pytest.mark.parametrize(
    "array,index,expected_value",
    [
        (BitArray("1010"), 0, 1),
        (BitArray("1010"), 1, 0),
        (BitArray("1010"), slice(1, 3), BitArray("01")),
        (BitArray("1111"), slice(0, 2), BitArray("11")),
        (BitArray("1010"), slice(0, 4), BitArray("1010")),
        (BitArray("1010"), slice(0, 5), BitArray("1010")),
        (BitArray("1010"), slice(-3, -1), BitArray("01")),
        (BitArray("1010"), slice(-3, 0), BitArray("")),
        (BitArray("1010"), -1, 0),
        (BitArray("10101111000"), slice(0, None, 2), BitArray("111100")),
    ],
)
def test_indexing(array, index, expected_value):
    assert array[index] == expected_value


# __getitem__
@pytest.mark.parametrize(
    "array,slice_obj,expected_slice",
    [
        (BitArray("1010"), slice(1, 3), BitArray("01")),
        (BitArray("1111"), slice(0, 2), BitArray("11")),
    ],
)
def test_slicing(array, slice_obj, expected_slice):
    assert array[slice_obj] == expected_slice


# __setitem__
def test_setitem():
    a = BitArray("1010")
    a[0] = 0
    assert a == BitArray("0010")
    a[1:3] = BitArray("11")
    assert a == BitArray("0110")


# __delitem__
def test_delitem():
    a = BitArray("1010")
    del a[0]
    assert a == BitArray("010")
    del a[1:3]
    assert a == BitArray("0")


# __len__
def test_length():
    a = BitArray("1010")
    assert len(a) == 4
    b = BitArray()
    assert len(b) == 0


# String Representations
# __str__, __repr__
def test_string_representations():
    a = BitArray("1010")
    assert str(a) == "BitArray[big]('1010')"
    assert repr(a) == "BitArray('1010', endianness='big')"
    print(a.hex())
    assert bytes(a) == b"\xa0"  # Adjust based on the expected byte representation


# __format__
def test_format():
    a = BitArray("1010")
    b = BitArray("001010")
    assert format(a, "b") == "0b1010"
    assert format(a, "x") == "0xa"
    assert format(b, "o") == "0o12"


# __copy__ and __deepcopy__
def test_copy_and_deepcopy():
    original = BitArray("1010")
    shallow_copy = copy.copy(original)
    deep_copy = copy.deepcopy(original)

    # Check initial equality
    assert shallow_copy == original
    assert deep_copy == original

    # Modify the shallow copy and ensure changes don't affect the original
    shallow_copy[0] = 0
    assert shallow_copy != original
    assert deep_copy == original

    # Modify the deep copy and ensure changes don't affect the original
    deep_copy[2] = 0
    print(original)
    assert deep_copy != original
    assert shallow_copy != original
    assert original == BitArray("1010")  # The original remains unchanged


# __sizeof__
def test_sizeof():
    array = BitArray("1010")
    expected_size = array.__sizeof__()
    assert isinstance(expected_size, int)
    assert expected_size > 0


# endregion Magic Methods

# region basic content-modification methods


# Append
@pytest.mark.parametrize(
    "initial, value, expected", [("101", 0, "1010"), ("111", 1, "1111")]
)
def test_append(initial, value, expected):
    array = BitArray(initial)
    array.append(value)
    assert array.to01() == expected


# Extend
@pytest.mark.parametrize(
    "initial, values, expected", [("10", [0, 1], "1001"), ("", [1, 1, 0], "110")]
)
def test_extend(initial, values, expected):
    array = BitArray(initial)
    array.extend(values)
    assert array.to01() == expected


# Insert
@pytest.mark.parametrize(
    "initial, index, value, expected",
    [
        ("1010", 1, 1, "11010"),
        ("100", 2, 0, "1000"),
        # ("111", 1, BitArray("000"), "10000111")
    ],
)
def test_insert(initial, index, value, expected):
    array = BitArray(initial)
    array.insert(index, value)
    assert array.to01() == expected


# Pop
@pytest.mark.parametrize(
    "initial, index, expected_value, expected_array",
    [("1010", None, 0, "101"), ("1111", 1, 1, "111")],
)
def test_pop(initial, index, expected_value, expected_array):
    array = BitArray(initial)
    value = array.pop(index)
    assert value == expected_value
    assert array.to01() == expected_array


# Pop with default
@pytest.mark.parametrize(
    "initial, index, default, expected_value, expected_array",
    [
        ("101", 10, -1, -1, "101"),
    ],
)
def test_pop_with_default(initial, index, default, expected_value, expected_array):
    array = BitArray(initial)
    value = array.pop(index, default)
    assert value == expected_value
    assert array.to01() == expected_array


# Remove
@pytest.mark.parametrize(
    "initial, value, expected", [("10101", 0, "1101"), ("111", 1, "11")]
)
def test_remove(initial, value, expected):
    array = BitArray(initial)
    array.remove(value)
    assert array.to01() == expected


# Clear
@pytest.mark.parametrize("initial", ["101", "111", "0"])
def test_clear(initial):
    array = BitArray(initial)
    array.clear()
    assert len(array) == 0
    assert array.to01() == ""


# Copy
@pytest.mark.parametrize("initial", ["1010", "1111", "0"])
def test_copy(initial):
    original = BitArray(initial)
    copied = original.copy()
    assert original == copied
    assert original is not copied


# Reverse
@pytest.mark.parametrize(
    "initial, expected", [("1010", "0101"), ("1110", "0111"), ("", "")]
)
def test_reverse(initial, expected):
    array = BitArray(initial)
    array.reverse()
    assert array.to01() == expected


# endregion basic content-modificaiton methods

# region search


# count
@pytest.mark.parametrize(
    "array,value,start,end,expected_count",
    [
        ("101010", 1, 0, None, 3),
        ("101010", 0, 0, None, 3),
        ("1111", 1, 0, 2, 2),
        ("", 1, 0, None, 0),
    ],
)
def test_count(array, value, start, end, expected_count):
    bit_array = BitArray(array)
    assert bit_array.count(value, start, end) == expected_count


# endswith
@pytest.mark.parametrize(
    "array,substrings,start,stop,expected_result",
    [
        ("101010", "10", 0, None, True),
        ("101010", "11", 0, None, False),
        ("111", "11", 1, None, True),
        ("", "", 0, None, True),
    ],
)
def test_endswith(array, substrings, start, stop, expected_result):
    bit_array = BitArray(array)
    assert bit_array.endswith(substrings, start, stop) == expected_result


# startswith
@pytest.mark.parametrize(
    "array,substrings,start,stop,expected_result",
    [
        ("101010", "10", 0, None, True),
        ("101010", "11", 0, None, False),
        ("111", "11", 0, 2, True),
        ("", "", 0, None, True),
    ],
)
def test_startswith(array, substrings, start, stop, expected_result):
    bit_array = BitArray(array)
    assert bit_array.startswith(substrings, start, stop) == expected_result


# find
@pytest.mark.parametrize(
    "array,value,start,stop,expected_index",
    [
        ("101010", 1, 0, None, 0),
        ("101010", 0, 0, None, 1),
        ("101010", 1, 2, None, 2),
        ("101", 1, 1, 2, -1),
    ],
)
def test_find(array, value, start, stop, expected_index):
    bit_array = BitArray(array)
    assert bit_array.find(value, start, stop) == expected_index


# rfind
@pytest.mark.parametrize(
    "array,value,start,stop,expected_index",
    [
        ("101010", 1, 0, None, 4),
        ("101010", 0, 0, None, 5),
        ("101", 1, 1, None, 2),
        ("1011", 0, 2, 3, -1),
    ],
)
def test_rfind(array, value, start, stop, expected_index):
    bit_array = BitArray(array)
    assert bit_array.rfind(value, start, stop) == expected_index


# index
@pytest.mark.parametrize(
    "array,value,start,stop,expected_index",
    [("101010", 1, 0, None, 0), ("101010", 0, 0, None, 1), ("101", 1, 2, None, 2)],
)
def test_index(array, value, start, stop, expected_index):
    bit_array = BitArray(array)
    assert bit_array.index(value, start, stop) == expected_index


@pytest.mark.parametrize(
    "array,value,start,stop", [("101010", 2, 0, None), ("101", 1, 1, 2)]
)
def test_index_error(array, value, start, stop):
    bit_array = BitArray(array)
    with pytest.raises(ValueError):
        bit_array.index(value, start, stop)


# rindex
@pytest.mark.parametrize(
    "array,value,start,stop,expected_index",
    [("101010", 1, 0, None, 4), ("101010", 0, 0, None, 5), ("101", 1, 0, 3, 2)],
)
def test_rindex(array, value, start, stop, expected_index):
    bit_array = BitArray(array)
    assert bit_array.rindex(value, start, stop) == expected_index


@pytest.mark.parametrize(
    "array,value,start,stop", [("111010", 0, 0, 2), ("101", "110", 0, 3)]
)
def test_rindex_error(array, value, start, stop):
    bit_array = BitArray(array)
    with pytest.raises(ValueError):
        bit_array.rindex(value, start, stop)


# endregion search

# region modification and translation


# replace
@pytest.mark.parametrize(
    "array,old,new,count,expected",
    [
        ("101010", "10", "01", None, "010101"),
        ("111000", "1", "0", 2, "001000"),
        ("101", "11", "00", None, "101"),
    ],
)
def test_replace(array, old, new, count, expected):
    bit_array = BitArray(array)
    result = bit_array.replace(BitArray(old), BitArray(new), count)
    assert result.to01() == expected


# join
@pytest.mark.parametrize(
    "separator,iterable,expected",
    [
        ("0", ["10", "11"], "10011"),
        ("1", ["01", "00"], "01100"),
        ("", ["10", "10"], "1010"),
    ],
)
def test_join(separator, iterable, expected):
    separator_array = BitArray(separator)
    result = separator_array.join(iterable)
    assert result.to01() == expected


# partition
@pytest.mark.parametrize(
    "array,sep,expected_before,expected_sep,expected_after",
    [
        ("101110", "11", "10", "11", "10"),
        ("110011", "00", "11", "00", "11"),
        ("1001", "11", "1001", "", ""),
    ],
)
def test_partition(array, sep, expected_before, expected_sep, expected_after):
    bit_array = BitArray(array)
    before, separator, after = bit_array.partition(BitArray(sep))
    assert before.to01() == expected_before
    assert separator.to01() == expected_sep
    assert after.to01() == expected_after


# rpartition
@pytest.mark.parametrize(
    "array,sep,expected_before,expected_sep,expected_after",
    [
        ("101110", "11", "101", "11", "0"),
        ("110011", "00", "11", "00", "11"),
        ("1001", "11", "", "", "1001"),
    ],
)
def test_rpartition(array, sep, expected_before, expected_sep, expected_after):
    bit_array = BitArray(array)
    before, separator, after = bit_array.rpartition(BitArray(sep))
    assert before.to01() == expected_before
    assert separator.to01() == expected_sep
    assert after.to01() == expected_after


# lstrip
@pytest.mark.parametrize(
    "array,bitarrays,expected",
    [
        ("001010", "0", "1010"),
        ("1110", "1", "0"),
        ("1111", "0", "1111"),
        ("1111", "1", ""),
        ("1001", None, "1001"),
    ],
)
def test_lstrip(array, bitarrays, expected):
    print(BitArray("001010").lstrip(0).to01())
    bit_array = BitArray(array)
    result = bit_array.lstrip(bitarrays)
    assert result.to01() == expected


# rstrip
@pytest.mark.parametrize(
    "array,bitarrays,expected",
    [
        ("010100", "0", "0101"),
        ("0111", "1", "0"),
        ("1111", "0", "1111"),
        ("1111", "1", ""),
        ("1001", None, "1001"),
    ],
)
def test_rstrip(array, bitarrays, expected):
    bit_array = BitArray(array)
    result = bit_array.rstrip(bitarrays)
    assert result.to01() == expected


# strip
@pytest.mark.parametrize(
    "array,bitarrays,expected",
    [("0010100", "0", "101"), ("1111110", "1", "0"), ("1001", None, "1001")],
)
def test_strip(array, bitarrays, expected):
    bit_array = BitArray(array)
    result = bit_array.strip(bitarrays)
    assert result.to01() == expected


# endregion modification and translation

# region bonus tests


# Fixture for an empty Bits instance
@pytest.fixture
def empty_bits():
    return BitArray([])


# Fixture for a Bits instance with some data
@pytest.fixture
def some_bits():
    return BitArray([1, 0, 1])


# Fixture for a Bits instance representing a byte
@pytest.fixture
def byte_bits():
    return BitArray([1, 0, 1, 0, 0, 0, 0, 0])


# Test the initialization of the Bits class
def test_bits_init(empty_bits, some_bits):
    # # Test with empty initialization
    # assert empty_bits.to_int() == 0

    # # Test with some bit data
    # assert some_bits.to_int() == -3

    assert list(BitArray()) == []


# Test the string representation of Bits
def test_bits_str(some_bits):
    assert some_bits.bin() == "0b101"


# Test the append method
def test_bits_append(some_bits):
    # new_some_bits = some_bits.append(1, inplace=False)
    # assert str(new_some_bits) == "0b1011"
    # assert str(some_bits) == "0b101"
    some_bits.append(1)
    assert some_bits.bin() == "0b1011"


# # Test padding
# def test_bits_padright(some_bits):
#     new_some_bits = some_bits.padright(up_to_size=5, inplace=False)
#     assert str(new_some_bits) == "0b10100"
#     assert str(some_bits) == "0b101"

#     some_bits.padright(up_to_size=5, inplace=True)
#     assert str(some_bits) == "0b10100"


# def test_bits_padleft(some_bits):
#     new_some_bits = some_bits.padleft(up_to_size=5, inplace=False)
#     assert str(new_some_bits) == "0b00101"
#     assert str(some_bits) == "0b101"

#     some_bits.padleft(up_to_size=5, inplace=True)
#     assert str(some_bits) == "0b00101"


# Test the pop method
def test_bits_pop(some_bits, byte_bits):
    # bit = some_bits.pop(inplace=False)
    # assert bit == 1
    # assert str(some_bits) == "0b101"

    # bit = byte_bits.pop(2, inplace=False)
    # assert bit == 1
    # assert str(byte_bits) == "0b10100000"

    bit = some_bits.pop()
    assert bit == 1
    assert some_bits.bin() == "0b10"


# Test the to_bytes method
def test_bits_to_bytes(byte_bits):
    print(byte_bits)
    # print(int(byte_bits))
    [print(bit) for bit in byte_bits]
    assert bytes(byte_bits) == b"\xa0"


# Test the from_bytes class method
def test_bits_from_bytes():
    # bits = BitArray().from_bytes(b"\xa0")
    bits = BitArray(b"\xa0")
    bits_right = [int(i) for i in bin(160)[2:].zfill(len(bits))]
    assert list(bits) == bits_right


def test_bits_from_str():
    bits = BitArray("0b101")
    assert list(bits) == [1, 0, 1]
    bits = BitArray("0b1_01")
    assert list(bits) == [1, 0, 1]
    bits = BitArray("101")
    assert list(bits) == [1, 0, 1]

    bits = BitArray("01_10 11:11 0-0-0-0")
    assert list(bits) == [0, 1, 1, 0, 1, 1, 1, 1, 0, 0, 0, 0]

    bits = BitArray("0xFE")
    assert list(bits) == [1, 1, 1, 1, 1, 1, 1, 0]

    bits1 = BitArray("0x0000_0F0F")
    bits2 = BitArray("0x00000F0F")
    assert bits1 == bits2

    bits = BitArray("0x00000f0f")
    # fmt: off
    assert list(bits) == [
        0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 1, 1, 1, 1,
        0, 0, 0, 0, 1, 1, 1, 1,
    ]
    # fmt: on
    assert bits.hex() == "0x00000f0f"

    bits = BitArray("0o707")
    assert list(bits) == [1, 1, 1, 0, 0, 0, 1, 1, 1]


# def test_bits_from_int():
#     integer = 5
#     bits = Bits.from_int(integer)
#     assert list(bits) == [0, 1, 0, 1]

#     bits = Bits.from_int(integer, 32)
#     # fmt: off
#     assert list(bits) == [
#         0, 0, 0, 0, 0, 0, 0, 0,
#         0, 0, 0, 0, 0, 0, 0, 0,
#         0, 0, 0, 0, 0, 0, 0, 0,
#         0, 0, 0, 0, 0, 1, 0, 1,
#     ]
#     # fmt: on


# # Test the to_int method
# def test_bits_to_int():
#     pos_num = BitArray("0b0101")
#     assert pos_num.to_int() == 5

#     neg_num = BitArray("0b101")
#     assert BitArray(neg_num).to_int() == -3

#     neg_num = BitArray("0b10101")
#     assert BitArray(neg_num).to_int() == -11

#     assert BitArray("0b1_01").to_int() == -3


# Test the equality method
def test_bits_eq(some_bits):
    bits2 = BitArray([1, 0, 1])
    assert some_bits == bits2

    bits3 = BitArray([0, 1, 1])
    assert some_bits != bits3

    nonbits = 51
    assert some_bits != nonbits


# # Test the shrinkequals method
# def test_bits_shrinkequals():
#     bits1 = BitArray([1, 1, 0, 0])
#     bits2 = BitArray([0, 1, 1, 1])
#     assert not bits1.shrinkequals(bits2)


def test_bits_join():
    bits0 = BitArray([1, 0, 1, 1, 0])
    bits1 = BitArray([1, 1, 0, 0])
    bits2 = BitArray([0, 1, 1, 1])

    bits3 = BitArray().join([bits0, bits1, bits2])
    assert list(bits3) == [1, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1, 1, 1]

    bits4 = BitArray().join([])
    assert list(bits4) == []

    bits5 = BitArray().join([bits0])
    assert list(bits5) == [1, 0, 1, 1, 0]

    bits6 = bits0.join([bits1, bits2, bits1])
    # fmt: off
    assert list(bits6) == [
        1, 1, 0, 0, 1, 0, 1, 1,
        0, 0, 1, 1, 1, 1, 0, 1,
        1, 0, 1, 1, 0, 0,
    ]


# endregion bonus tests
