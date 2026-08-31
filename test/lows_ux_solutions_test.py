"""Tests for the Stage-13 lows-ux behavioral wins.

Covers the applied items: to_bits/from_bits warn-first deprecation (the
DECIDED item), 4*Cls reflected array sugar, mint-time validation
(min_bit_length, unknown encoding), teaching lookup errors (plans, fields),
and the conversions package re-export. (The remaining lows-ux items are
message-text rewords + the pop default=None sentinel, deferred as polish.)
"""

import pytest

import bytemaker.fields as fields
from bytemaker.bittypes import String, UInt8
from bytemaker.bittypes.int import Int
from bytemaker.bitvector import BitVector
from bytemaker.structs import Struct


# ------------------------------------------------------------- lows-ux-5 (deprecation)
def test_to_bits_from_bits_deprecated():
    with pytest.deprecated_call():
        assert UInt8(3).to_bits() == BitVector("00000011")
    with pytest.deprecated_call():
        assert UInt8.from_bits(BitVector("00000011")).value == 3


def test_conversions_package_reexports():
    from bytemaker.conversions import ConversionConfig, to_bytes_aggregate  # noqa: F401

    assert (
        "to_bytes_aggregate"
        in __import__("bytemaker.conversions", fromlist=["x"]).__all__
    )


# ------------------------------------------------------------- pattern 6 (__rmul__)
def test_reflected_array_sugar():
    assert repr(4 * UInt8) == repr(UInt8 * 4)


# ---------------------------------------------------------- pattern 3 (mint validation)
def test_min_bit_length_rejects_unknown_format():
    with pytest.raises(ValueError, match="Unsupported format"):
        Int.min_bit_length(5, signed=True, bin_format="garbage")


def test_of_rejects_unknown_encoding_at_mint():
    with pytest.raises(ValueError, match="unknown encoding"):
        String.of(nbytes=4, encoding="utf-99")
    assert String.of(nbytes=4, encoding="utf-8")("hi").value == "hi"


# --------------------------------------------------------- pattern 4 (teaching lookups)
def test_plan_find_lists_fields():
    class R(Struct, endian="big"):
        a: UInt8
        b: UInt8

    with pytest.raises(ValueError, match=r"no field named 'bb'; fields are"):
        R.plan.byte_offset("bb")


def test_fields_float_alias_teaching():
    with pytest.raises(AttributeError, match="f16/f32/f64"):
        fields.f8
    assert fields.u31 is not None  # arbitrary uN/sN still resolve


def test_no_conversion_error_lists_registered_types():
    from bytemaker.conversions.pytypes import pytype_to_bits

    class _Weird:
        pass

    with pytest.raises(
        TypeError, match=r"No conversion registered.*Registered pytypes:.*int"
    ):
        pytype_to_bits(_Weird())
