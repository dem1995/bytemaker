"""Tests for the Stage-10 string-policy solutions (pytypes-1/2/3 + lows-code-7).

pytypes-3 + lows-code-7 are the maintainer DEVIATION: latin-1 on both sides of
the char codec, and an option-(c) declared-width check on both the bits and
bytes aggregate paths (bare strings serialize per-char; a str value that
overflows a declared-width field raises ValueError).
"""

from dataclasses import dataclass

import pytest

from bytemaker.bitvector import BitVector
from bytemaker.conversions.aggregate_types import (
    from_bytes_aggregate,
    to_bits_aggregate,
    to_bytes_aggregate,
)
from bytemaker.conversions.pytypes import (
    ConversionConfig,
    ConversionInfo,
    bits_to_pytype,
    pytype_to_bits,
)


@dataclass
class Rec:
    name: str
    val: int


# ------------------------------------------------------------- pytypes-3 (latin-1)
def test_char_codec_is_latin1_both_sides():
    assert pytype_to_bits("A") == BitVector(b"A")
    # latin-1 accepts all 256 byte values and round-trips (UTF-8 rejected >=0x80)
    assert bytes(pytype_to_bits(chr(0xE9))) == b"\xe9"
    info = ConversionConfig.get_conversion_info(str)
    assert info.from_bits(BitVector(b"\xe9")) == chr(0xE9)
    assert info.num_bits("") == 8  # fixed width unchanged (test_type_sizes stays green)


@pytest.mark.parametrize("bad", ["ABC", "", chr(0x20AC)])  # multi / empty / non-latin1
def test_char_codec_rejects_non_one_byte(bad):
    with pytest.raises(ValueError, match="fixed-width"):
        pytype_to_bits(bad)


# ------------------------------------------------------------- option (c): bits path
def test_bits_path_option_c():
    assert to_bits_aggregate("ABC").to_bytes() == b"ABC"  # bare -> per-char
    assert to_bits_aggregate(Rec("A", 5)).to_bytes() == b"A\x00\x00\x00\x05"
    with pytest.raises(ValueError, match="str field"):
        to_bits_aggregate(Rec("ABC", 5))  # declared-width overflow (56 vs 40)


# ------------------------------------------------- option (c): bytes path (lows-code-7)
def test_bytes_path_option_c():
    assert to_bytes_aggregate("hi") == b"hi"  # bare -> per-char (carve-out)
    packed = to_bytes_aggregate(Rec("A", 5))
    assert packed == b"A\x00\x00\x00\x05"
    assert from_bytes_aggregate(packed, Rec) == Rec("A", 5)  # round-trip
    with pytest.raises(ValueError, match="str field"):
        to_bytes_aggregate(Rec("ABC", 5))  # declared-width overflow


# ------------------------------------------------------------- pytypes-1 (delete)
def test_conversioninfo_byte_helpers_deleted():
    assert not hasattr(ConversionInfo, "num_bytes")
    assert not hasattr(ConversionInfo, "to_bytes")
    assert not hasattr(ConversionInfo, "from_bytes")


# ------------------------------------------------------------- pytypes-2 (docstring)
def test_bits_to_pytype_docstring_fixed():
    doc = bits_to_pytype.__doc__
    assert "bits_obj" in doc
    assert "py_prim_type" not in doc
    assert "PyTypeWithDefaultBytes" not in doc
