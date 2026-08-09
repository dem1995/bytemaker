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

    # endian=None is the "unset" sentinel, not a typo: construction is fine
    # (as a field it inherits the record's byte order), but standalone use
    # of multi-byte numeric elements now demands an explicit byte order
    # instead of silently meaning big.
    arr = Array(UInt16, 2)
    assert arr.declared_endian is None and "endian=unset" in repr(arr)
    with pytest.raises(ValueError, match="no byte order declared"):
        arr.pack([0x0102, 0x0304])
    explicit = Array(UInt16, 2, endian="big")
    assert explicit.declared_endian == "big"
    assert explicit.pack([0x0102, 0x0304]) == b"\x01\x02\x03\x04"


# ---------------------------------------------- wd-4: per-field endianness
def test_field_endian_override_mixed_record():
    from bytemaker.structs import field

    class Mixed(Struct, endian="little"):
        char_number: int = field(UInt16, endian="big")
        width: UInt16  # record order (little)

    m = Mixed(char_number=0x1234, width=0x5678)
    assert m.pack() == b"\x12\x34\x78\x56"  # BE field beside an LE field
    assert Mixed.parse(m.pack()) == m
    assert Mixed.plan.tier == "shiftmask"  # mixed order leaves the struct tier


def test_field_endian_override_font_shape():
    # The real case: a big-endian index inside a little-endian ROM record,
    # previously only expressible by flipping the whole record's endian
    # (which worked only because the other field was order-agnostic bytes).
    from bytemaker.bittypes import Buffer
    from bytemaker.structs import field

    Pix = Buffer.of(nbytes=2, name="Pix2")

    class FontEntry(Struct, endian="little"):
        char_number: int = field(UInt16, endian="big")
        pixels: Pix

    f = FontEntry.parse(b"\x00\x05" + b"\xab\xcd")
    assert f.char_number == 5
    assert f.pixels == b"\xab\xcd"
    assert f.pack() == b"\x00\x05\xab\xcd"


def test_field_endian_rejects_orderless_and_composite_types():
    from bytemaker.structs import field
    from bytemaker.bittypes import UTF8String

    Name2 = UTF8String.of(nbytes=2, name="Name2E")
    with pytest.raises(PlanCompileError, match="byte-order-agnostic"):

        class S1(Struct, endian="little"):
            name: str = field(Name2, endian="big")

    class Inner(Struct, endian="big"):
        x: UInt16

    with pytest.raises(PlanCompileError, match="ITS class definition"):

        class S2(Struct, endian="little"):
            inner: Inner = field(Inner, endian="big")

    with pytest.raises(PlanCompileError, match=r"array\(element"):

        class S3(Struct, endian="little"):
            xs: list = field(Array.of(UInt16, 2), endian="big")

    with pytest.raises(PlanCompileError, match="field endian"):
        field(UInt16, endian="litle")  # typo caught at the declaration


def test_annotated_endian_tag_is_rejected_not_dropped():
    # Annotated[int, UInt16, "big"] compiled silently and produced
    # record-order bytes; now it names the real spelling.
    try:
        from typing import Annotated
    except ImportError:
        from typing_extensions import Annotated

    with pytest.raises(PlanCompileError, match=r"field\(T, endian="):

        class S(Struct, endian="little"):
            n: Annotated[int, UInt16, "big"]
