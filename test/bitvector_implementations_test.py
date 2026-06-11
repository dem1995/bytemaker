# flake8: noqa
"""
Tests run against every available BitVector implementation.

The `BitVector` fixture parametrizes each test over the pure-Python
implementation and (when bitarray is installed) the bitarray-backed one,
so both are held to the behavior specified in bitvector.pyi. Tests in the
"native-only behavior" region cover leniencies the pure-Python
implementation supports beyond the bitarray-backed one.
"""

import copy

import pytest

from bytemaker.bitvector.bitvector_native import BitVector as NativeBitVector

_IMPLEMENTATIONS = [pytest.param(NativeBitVector, id="native")]
try:
    from bytemaker.bitvector.bitvector_with_bitarray_speedup import (
        BitVector as BitarrayBitVector,
    )

    _IMPLEMENTATIONS.append(pytest.param(BitarrayBitVector, id="bitarray"))
except ImportError:  # bitarray is an optional dependency
    pass


@pytest.fixture(params=_IMPLEMENTATIONS, name="BitVector")
def bitvector_implementation(request):
    return request.param


class Castable:
    """Minimal BitsCastable implementation for protocol tests."""

    def __init__(self, cls, bits="11001010"):
        self._cls = cls
        self._bits = bits

    def __Bits__(self):
        return self._cls(self._bits)


class IndexOnly:
    """Has __index__ but no __int__, for strip-argument normalization."""

    def __index__(self):
        return 1


# region construction


def test_construction_from_bitscastable(BitVector):
    assert BitVector(Castable(BitVector, "11001010")).to01() == "11001010"


def test_construction_invalid_source_type(BitVector):
    with pytest.raises(ValueError):
        BitVector(3.5)


def test_construction_from_buffer_kwarg(BitVector):
    assert BitVector(buffer=memoryview(b"\x0f")).to01() == "00001111"


def test_fromsize_negative_is_empty(BitVector):
    assert BitVector(-3).to01() == ""


def test_from01_rejects_other_characters(BitVector):
    with pytest.raises(ValueError):
        BitVector.from01("102")


# endregion construction

# region base conversions


@pytest.mark.parametrize(
    "string,base,expected_bin",
    [
        ("123", 4, "011011"),
        ("7A7A", 32, "11111000001111100000"),
        ("+D", 64, "111110000011"),
    ],
)
def test_frombase_higher_bases(BitVector, string, base, expected_bin):
    assert BitVector.frombase(string, base).to01() == expected_bin


@pytest.mark.parametrize(
    "string,base",
    [
        ("123", 10),  # unsupported base
        ("G", 16),  # invalid hex digit
        ("a", 32),  # base32 alphabet is uppercase
        ("~", 64),  # not in the base64 alphabet
    ],
)
def test_frombase_invalid_inputs(BitVector, string, base):
    with pytest.raises(ValueError):
        BitVector.frombase(string, base)


@pytest.mark.parametrize(
    "bits,base,expected",
    [
        ("011011", 4, "123"),
        ("11111000001111100000", 32, "7A7A"),
        ("111110000011", 64, "+D"),
    ],
)
def test_tobase_higher_bases(BitVector, bits, base, expected):
    assert BitVector(bits).tobase(base) == expected


def test_tobase_invalid_base(BitVector):
    with pytest.raises(ValueError):
        BitVector("1010").tobase(10)


def test_tobase_length_not_multiple_of_digit_size(BitVector):
    with pytest.raises(ValueError):
        BitVector("1010").tobase(8)


def test_tobase_with_separator(BitVector):
    assert BitVector("1010010111110000").tobase(16, sep="_") == "a5_f0"
    assert BitVector("1010010111110000").hex(sep="_") == "0xa5_f0"


# endregion base conversions

# region character-array conversions


def test_from_chararray_with_mapping(BitVector):
    encoding = {"a": "01", "b": "10"}
    assert BitVector.from_chararray("abba", encoding).to01() == "01101001"


def test_to_chararray_with_mapping(BitVector):
    decoding = {"01": "a", "10": "b"}
    assert BitVector("01101001").to_chararray(decoding) == "abba"


# endregion character-array conversions

# region comparisons


def test_ordering_against_non_bitvector_is_a_type_error(BitVector):
    bv = BitVector("10")
    with pytest.raises(TypeError):
        bv < "10"  # noqa: B015
    with pytest.raises(TypeError):
        bv <= "10"  # noqa: B015
    with pytest.raises(TypeError):
        bv > "10"  # noqa: B015
    with pytest.raises(TypeError):
        bv >= "10"  # noqa: B015


def test_equality_with_non_bitvector(BitVector):
    assert BitVector("101") != 51
    assert not BitVector("101") == 51


# endregion comparisons

# region arithmetic and bitwise operators


def test_radd_and_iadd(BitVector):
    bv = BitVector("1010")
    assert ([1] + bv).to01() == "11010"
    bv += "11"
    assert bv.to01() == "101011"


def test_mul_with_non_int_is_unsupported(BitVector):
    with pytest.raises(TypeError):
        BitVector("10") * "3"
    with pytest.raises(TypeError):
        bv = BitVector("10")
        bv *= "3"


def test_imul(BitVector):
    bv = BitVector("10")
    bv *= 3
    assert bv.to01() == "101010"


def test_bitwise_operators(BitVector):
    assert (BitVector("1100") & "1010").to01() == "1000"
    assert (BitVector("1100") | "1010").to01() == "1110"
    assert (BitVector("1100") ^ "1010").to01() == "0110"
    assert ("1010" & BitVector("1100")).to01() == "1000"
    assert ("1010" | BitVector("1100")).to01() == "1110"
    assert ("1010" ^ BitVector("1100")).to01() == "0110"


def test_inplace_bitwise_operators(BitVector):
    bv = BitVector("1100")
    bv &= "1010"
    assert bv.to01() == "1000"
    bv = BitVector("1100")
    bv |= "1010"
    assert bv.to01() == "1110"
    bv = BitVector("1100")
    bv ^= "1010"
    assert bv.to01() == "0110"


def test_bitwise_operators_require_equal_lengths(BitVector):
    for operation in ("__and__", "__or__", "__xor__"):
        with pytest.raises(ValueError):
            getattr(BitVector("101"), operation)(BitVector("1011"))


@pytest.mark.parametrize(
    "count,left,right",
    [
        (0, "1011", "1011"),
        (1, "0110", "0101"),
        (2, "1100", "0010"),
        (9, "0000", "0000"),  # shifting past the length zero-fills
    ],
)
def test_shifts(BitVector, count, left, right):
    assert (BitVector("1011") << count).to01() == left
    assert (BitVector("1011") >> count).to01() == right


def test_inplace_shifts(BitVector):
    bv = BitVector("1011")
    bv <<= 1
    assert bv.to01() == "0110"
    bv = BitVector("1011")
    bv >>= 1
    assert bv.to01() == "0101"


def test_shift_errors(BitVector):
    for operation in ("__lshift__", "__rshift__"):
        with pytest.raises(TypeError):
            getattr(BitVector("1011"), operation)("1")
        with pytest.raises(ValueError):
            getattr(BitVector("1011"), operation)(-1)


def test_invert(BitVector):
    assert (~BitVector("1010")).to01() == "0101"
    assert (~BitVector("")).to01() == ""


# endregion arithmetic and bitwise operators

# region magic methods


def test_format_empty_spec_and_invalid_spec(BitVector):
    bv = BitVector("1010")
    assert format(bv, "") == str(bv)
    with pytest.raises(ValueError):
        format(bv, "q")


def test_contains(BitVector):
    bv = BitVector("10100101")
    assert "101" in bv
    assert b"\xa5" in bv
    assert [1, 1] not in bv
    assert Castable(BitVector, "10100101") in bv
    assert 3.5 not in bv
    assert 2 not in bv


def test_getitem_iterable_key_and_invalid_key(BitVector):
    bv = BitVector("10110")
    assert bv[[0, 2, 4]].to01() == "110"
    assert bv[range(2)].to01() == "10"
    with pytest.raises(TypeError):
        bv[object()]


def test_setitem_int_key_with_constructible_value(BitVector):
    bv = BitVector("1010")
    bv[0] = "0"
    assert bv.to01() == "0010"


def test_setitem_invalid_bit_value(BitVector):
    bv = BitVector("1010")
    with pytest.raises(ValueError):
        bv[0] = 2


def test_setitem_slice_with_int_fills(BitVector):
    bv = BitVector("0000")
    bv[1:3] = 1
    assert bv.to01() == "0110"
    bv = BitVector("0000")
    bv[0::2] = 1
    assert bv.to01() == "1010"


def test_setitem_iterable_key_with_int_fills(BitVector):
    bv = BitVector("0000")
    bv[[0, 2]] = 1
    assert bv.to01() == "1010"


def test_setitem_invalid_key(BitVector):
    bv = BitVector("1010")
    with pytest.raises(TypeError):
        bv[object()] = 1


def test_delitem_iterable_key_and_invalid_key(BitVector):
    bv = BitVector("1010")
    del bv[[0, 3]]
    assert bv.to01() == "01"
    with pytest.raises(TypeError):
        del bv[object()]


def test_dunder_bits_returns_equal_copy(BitVector):
    bv = BitVector("1010")
    cast = bv.__Bits__()
    assert cast == bv
    assert cast is not bv


def test_deepcopy_with_memo(BitVector):
    bv = BitVector("1010")
    memo = {}
    deep = copy.deepcopy(bv, memo)
    assert deep == bv
    assert id(bv) in memo


# endregion magic methods

# region basic operations


def test_extend_with_non_iterable_uses_constructor(BitVector):
    bv = BitVector("1")
    bv.extend(3)  # ints construct that many zero bits
    assert bv.to01() == "1000"


def test_extend_with_bitvector(BitVector):
    bv = BitVector("1")
    bv.extend(BitVector("01"))
    assert bv.to01() == "101"


def test_pop_out_of_bounds_without_default(BitVector):
    with pytest.raises(IndexError):
        BitVector().pop()
    with pytest.raises(IndexError):
        BitVector("1").pop(5)
    with pytest.raises(IndexError):
        # negative indices are treated as out of bounds (specified quirk)
        BitVector("1").pop(-1)


def test_remove_missing_bit(BitVector):
    with pytest.raises(ValueError):
        BitVector("111").remove(0)


def test_count_subsequence_and_invalid_bit(BitVector):
    assert BitVector("11111").count(BitVector("11")) == 2  # non-overlapping
    assert BitVector("0110110").count("11") == 2
    with pytest.raises(ValueError):
        BitVector("101").count(2)


# endregion basic operations

# region search


def test_startswith_endswith_argument_forms(BitVector):
    bv = BitVector("1011011")
    assert bv.startswith(BitVector("10"))
    assert bv.startswith(1)
    assert not bv.startswith(0)
    assert bv.startswith([1, 0])
    assert bv.startswith(("00", "10"))
    assert not bv.startswith(("00", "01"))
    assert bv.endswith(BitVector("11"))
    assert bv.endswith(1)
    assert bv.endswith([0, 1, 1])
    assert bv.endswith(("00", "11"))


def test_startswith_iterable_with_invalid_element(BitVector):
    with pytest.raises(ValueError):
        BitVector("1011011").startswith(("10", 3.5))


def test_find_and_rfind_with_constructible_values(BitVector):
    assert BitVector("1011011").find("11") == 2
    assert BitVector("1011011").find("00") == -1
    assert BitVector("1011011").rfind("11") == 5
    assert BitVector("1011011").rfind("00") == -1


# endregion search

# region modification and translation


def test_replace_accepts_constructibles_and_does_not_mutate(BitVector):
    bv = BitVector("101010")
    assert bv.replace("10", "01").to01() == "010101"
    assert bv.to01() == "101010"


def test_replace_with_different_lengths(BitVector):
    assert BitVector("101010").replace("10", "0").to01() == "000"
    assert BitVector("101010").replace("0", "11", 1).to01() == "1111010"


def test_strip_argument_normalization(BitVector):
    # objects with __int__ (e.g. floats) work
    assert BitVector("0111").lstrip(0.0).to01() == "111"
    assert BitVector("1110").rstrip(1.0).to01() == "1110".rstrip("1")
    # objects with __index__ but no __int__ work
    assert BitVector("1110").rstrip(IndexOnly()).to01() == "1110".rstrip("1")


def test_pads_return_self_when_wide_enough(BitVector):
    bv = BitVector("1010")
    assert bv.lpad(3) is bv
    assert bv.rpad(4) is bv


# endregion modification and translation

# region transitional methods


def test_from_int_default_size_and_overflow(BitVector):
    assert BitVector.from_int(5).to01() == "0101"
    assert BitVector.from_int(-3).to01() == "101"
    with pytest.raises(ValueError):
        BitVector.from_int(8, 2)


def test_from_bytes_reversed(BitVector):
    assert BitVector.from_bytes(b"\x0f\xf0", reverse_endianness=True).to01() == (
        "1111000000001111"
    )


def test_to_bytes_reversed(BitVector):
    assert BitVector("0000111111110000").to_bytes(reverse_endianness=True) == (
        b"\xf0\x0f"
    )


def test_to_int(BitVector):
    assert BitVector("0101").to_int() == 5
    assert BitVector("101").to_int() == -3
    assert BitVector("101").to_int(signed=False) == 5
    assert BitVector("0000000100000000").to_int(endianness="little", signed=False) == 1


# endregion transitional methods

# region native-only behavior
# The pure-Python implementation accepts some spec-permitted inputs that the
# bitarray-backed one rejects (or, for replace("", ...), does not terminate on).


def test_native_comparison_dunders_return_notimplemented():
    bv = NativeBitVector("10")
    for operation in ("__lt__", "__le__", "__gt__", "__ge__"):
        assert getattr(bv, operation)("10") is NotImplemented


def test_native_from01_accepts_char_sequences():
    assert NativeBitVector.from01(["1", "0", "1"]).to01() == "101"


def test_native_castable_preserves_sub_byte_lengths():
    assert NativeBitVector(Castable(NativeBitVector, "1100")).to01() == "1100"


def test_native_setitem_slice_with_constructible_resizes():
    bv = NativeBitVector("0000")
    bv[1:3] = "111"
    assert bv.to01() == "01110"


def test_native_setitem_extended_slice_requires_matching_length():
    bv = NativeBitVector("1010")
    with pytest.raises(ValueError):
        bv[0::2] = "111"


def test_native_setitem_iterable_key_with_constructible_value():
    bv = NativeBitVector("0000")
    bv[[1, 3]] = "11"
    assert bv.to01() == "0101"
    with pytest.raises(ValueError):
        bv[[0, 2]] = "111"


def test_native_delitem_iterable_key_with_negative_indices():
    bv = NativeBitVector("1010")
    del bv[[0, -1]]
    assert bv.to01() == "01"


def test_native_startswith_non_constructible_is_a_type_error():
    with pytest.raises(TypeError):
        NativeBitVector("1011011").startswith(3.5)


def test_native_replace_empty_old_returns_copy():
    bv = NativeBitVector("1010")
    result = bv.replace("", "1")
    assert result == bv
    assert result is not bv


# endregion native-only behavior
