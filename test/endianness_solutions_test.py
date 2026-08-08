"""Tests for the Stage-9 endianness solutions (endianness-1, endianness-2)."""

import ctypes
from dataclasses import dataclass

import pytest

from bytemaker import _legacy_aggregate as legacy
from bytemaker.bittypes import SInt16, UInt8, UInt16, bytes_to_bittype
from bytemaker.conversions.aggregate_types import (
    from_bytes_aggregate,
    from_bytes_individual,
    to_bytes_aggregate,
    to_bytes_individual,
)
from bytemaker.conversions.ctypes_ import bytes_to_ctype, ctype_to_bytes
from bytemaker.conversions.pytypes import bytes_to_pytype, pytype_to_bytes
from bytemaker.structs import Array, PlanCompileError, Struct
from bytemaker.utils import validate_endianness

_BAD = ("bigg", "litle", "LE", "BE", "Little", "")
_MSG = r"must be 'big' or 'little'"


# ------------------------------------------------------------- helper
def test_validate_endianness_helper():
    assert validate_endianness("big") == "big"
    assert validate_endianness("little") == "little"
    with pytest.raises(ValueError, match=r"foo must be 'big' or 'little'; got 'x'"):
        validate_endianness("x", name="foo")
    with pytest.raises(PlanCompileError):
        validate_endianness("x", exc=PlanCompileError)


# ------------------------------------------------------------- endianness-1
@pytest.mark.parametrize("bad", _BAD)
def test_bittype_intakes_reject_typos(bad):
    with pytest.raises(ValueError, match=_MSG):
        UInt16(0x0102, endianness=bad)
    with pytest.raises(ValueError, match=_MSG):
        SInt16(5, endianness=bad)  # covers int.py constructors via the base
    with pytest.raises(ValueError, match=_MSG):
        bytes_to_bittype(b"\x01\x02", UInt16, endianness=bad)


def test_bittype_happy_paths_unchanged():
    assert bytes(UInt16(0x0102, endianness="big")) == b"\x01\x02"
    assert bytes(UInt16(0x0102, endianness="little")) == b"\x02\x01"
    assert UInt16(1).endianness == "big"  # source_else_big resolves to big
    assert UInt16(UInt16(1, endianness="little")).endianness == "little"


# ------------------------------------------------------------- endianness-2
def test_conversion_intakes_reject_typos():
    with pytest.raises(ValueError, match=_MSG):
        pytype_to_bytes(1, endianness="litle")
    with pytest.raises(ValueError, match=_MSG):
        bytes_to_pytype(b"\x00" * 4, int, endianness="litle")
    with pytest.raises(ValueError, match=_MSG):
        ctype_to_bytes(ctypes.c_uint16(1), "bigg")  # fires even w/o a swap
    with pytest.raises(ValueError, match=_MSG):
        bytes_to_ctype(b"\x00\x01", ctypes.c_uint16, "litle")


def test_aggregate_and_oracle_intakes_reject_typos():
    with pytest.raises(ValueError, match=_MSG):
        to_bytes_individual(UInt16(1), "litle")
    with pytest.raises(ValueError, match=_MSG):
        from_bytes_individual(b"\x00\x01", UInt16, "litle")

    @dataclass
    class Rec:
        a: UInt16
        b: UInt8

    rec = Rec(UInt16(0x0102), UInt8(3))
    for fn in (to_bytes_aggregate, legacy.to_bytes_aggregate):
        with pytest.raises(ValueError, match=_MSG):
            fn(rec, endianness="bigg")
    for fn in (from_bytes_aggregate, legacy.from_bytes_aggregate):
        with pytest.raises(ValueError, match=_MSG):
            fn(b"\x01\x02\x03", Rec, endianness="bigg")


def test_public_and_oracle_raise_identical_message():
    @dataclass
    class Rec:
        a: UInt16

    try:
        to_bytes_aggregate(Rec(UInt16(1)), endianness="bigg")
        public_msg = None
    except ValueError as e:
        public_msg = str(e)
    try:
        legacy.to_bytes_aggregate(Rec(UInt16(1)), endianness="bigg")
        oracle_msg = None
    except ValueError as e:
        oracle_msg = str(e)
    assert public_msg == oracle_msg is not None  # lockstep


def test_schema_intakes_reject_typos():
    with pytest.raises(PlanCompileError, match=r"Array endian .*must be 'big'"):
        Array(UInt16, 2, endian="litle")
    with pytest.raises(PlanCompileError, match=_MSG):

        class S(Struct, endian="litle"):
            a: UInt16

    # endian=None still inherits (no validation on the sentinel)
    assert Array(UInt16, 2).pack([0x0102, 0x0304]) == b"\x01\x02\x03\x04"
