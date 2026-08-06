"""Tests for the Stage-6 ctypes solutions (ctypes-1..3 + the Union raise deviation)."""

import sys
from ctypes import (
    Structure,
    Union,
    c_uint8,
    c_uint16,
    c_uint32,
)
from dataclasses import dataclass

import pytest

from bytemaker.conversions.ctypes_ import (
    bytes_to_ctype,
    ctype_to_bytes,
    reverse_ctype_endianness,
)

NONNATIVE = "big" if sys.byteorder == "little" else "little"


class Pt(Structure):
    _fields_ = [("x", c_uint16), ("y", c_uint16)]


class Inner(Structure):
    _fields_ = [("b", c_uint32)]


class Outer(Structure):
    _fields_ = [("a", c_uint16), ("inner", Inner)]


class WithArr(Structure):
    _fields_ = [("n", c_uint16), ("arr", c_uint16 * 3)]


class BitFirst(Structure):
    _fields_ = [("a", c_uint16, 4), ("b", c_uint16, 12), ("c", c_uint8)]


class BitLater(Structure):
    _fields_ = [("a", c_uint8), ("b", c_uint16, 4), ("c", c_uint16, 12)]


class BitNested(Structure):
    _fields_ = [("plain", c_uint16), ("bf", BitFirst)]


class U(Union):
    _fields_ = [("i", c_uint32), ("h", c_uint16)]


class U1(Union):
    _fields_ = [("a", c_uint8), ("b", c_uint8)]


# ------------------------------------------------------------- ctypes-1
def test_reversal_does_not_mutate_the_caller():
    p = Pt(1, 2)
    snap = bytes(p)
    ctype_to_bytes(p, NONNATIVE)
    assert bytes(p) == snap
    arr = (Pt * 2)(Pt(1, 2), Pt(3, 4))
    snap_arr = bytes(arr)
    ctype_to_bytes(arr, NONNATIVE)
    assert bytes(arr) == snap_arr
    s = c_uint16(0x0102)
    ctype_to_bytes(s, NONNATIVE)
    assert s.value == 0x0102
    # reverse_ctype_endianness returns a NEW object, leaving the input intact
    rev = reverse_ctype_endianness(Pt(1, 2))
    assert isinstance(rev, Pt)


def test_nested_and_array_field_structs_reverse():
    assert ctype_to_bytes(Outer(0x0102, Inner(0x0A0B0C0D)), "big") == bytes.fromhex(
        "010200000a0b0c0d"
    )
    w = WithArr(0x1122, (c_uint16 * 3)(0xAABB, 0xCCDD, 0xEEFF))
    assert ctype_to_bytes(w, "big") == bytes.fromhex("1122aabbccddeeff")


def test_array_of_multibyte_scalars_is_reversed():
    # was a silent no-op (native-order bytes returned unchanged)
    assert ctype_to_bytes((c_uint16 * 2)(0x0102, 0x0304), "big") == b"\x01\x02\x03\x04"


def test_reversal_roundtrips():
    for x in (Pt(1, 2), Outer(0x0102, Inner(0x0A0B0C0D))):
        x2 = bytes_to_ctype(ctype_to_bytes(x, "big"), type(x), "big")
        assert bytes(x2) == bytes(x)


# ------------------------------------------------------------- ctypes-2
def test_bitfields_raise_named_notimplemented():
    with pytest.raises(NotImplementedError, match="field 'a' is a bitfield"):
        ctype_to_bytes(BitFirst(1, 2, 3), NONNATIVE)
    with pytest.raises(NotImplementedError, match="field 'b' is a bitfield"):
        ctype_to_bytes(BitLater(1, 2, 3), NONNATIVE)  # later-field (was ValueError)
    with pytest.raises(NotImplementedError, match=r"field 'bf\.a' is a bitfield"):
        ctype_to_bytes(BitNested(0x0102, BitFirst(1, 2, 3)), NONNATIVE)  # dotted path
    # native-order direction still serializes bitfield structs fine
    assert ctype_to_bytes(BitLater(1, 2, 3), sys.byteorder) == bytes(BitLater(1, 2, 3))


# ------------------------------------------------------------- ctypes-3
def test_type_error_messages_are_spaced():
    with pytest.raises(TypeError) as ei:
        ctype_to_bytes(123)
    assert "Structure, Union, and Array objects" in str(ei.value)
    with pytest.raises(TypeError) as ei:
        bytes_to_ctype(b"\x00" * 4, int)
    assert "Structure, Union, and Array types" in str(ei.value)


# ------------------------------------- DEVIATION: multi-byte union raises
def test_multibyte_union_raises_on_swap_but_passes_native():
    u = U()
    u.i = 0x0A0B0C0D
    with pytest.raises(NotImplementedError, match="Union"):
        ctype_to_bytes(u, NONNATIVE)  # cross-endian swap refused
    assert ctype_to_bytes(u, sys.byteorder) == bytes(u)  # native order untouched
    # single-byte union has no swap to do and passes through
    u1 = U1()
    u1.a = 0x7
    assert ctype_to_bytes(u1, NONNATIVE) == bytes(u1)


# ------------------------------------- aggregate path shares the fix (oracle)
def test_aggregate_path_does_not_mutate_ctype_field():
    from bytemaker.conversions.aggregate_types import to_bytes_aggregate

    @dataclass
    class Record:
        pt: Pt

    rec = Record(Pt(0x0102, 0x0304))
    snap = bytes(rec.pt)
    to_bytes_aggregate(rec, endianness=NONNATIVE)
    assert bytes(rec.pt) == snap  # shared _reversed_ctype_bytes -> no mutation
