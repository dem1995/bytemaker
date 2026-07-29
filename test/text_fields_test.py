"""Tests for text/char and bytes fields (observations/14): the Str.of
factory, pad/terminator/strip semantics, TableString, and String/Buffer
fields in Struct across both plan tiers."""

import pytest

from bytemaker.bittypes import (
    Buffer16,
    Str16,
    String,
    TableString,
    UInt4,
    UInt8,
    UTF8String,
)
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Struct

# A .tbl-style game text table: single-byte glyphs, a multi-byte control
# code, and a terminator/pad byte that is NOT valid text.
MON_TABLE = {0x80: "A", 0x81: "B", 0x82: "C", 0xE1: "[PK]", 0x00: " "}
MonName = String.of(
    4, encoding=MON_TABLE, pad=0x50, terminator=0x50, name="MonName"
)
Ascii6 = UTF8String.of(6, name="Ascii6")
SJis6 = String.of(6, encoding="shift-jis", name="SJis6")


class Monster(Struct, endian="little"):
    name: MonName
    species: UInt8
    hp: UInt8


class Packed(Struct, endian="little"):  # sub-byte siblings: shiftmask tier
    lo: UInt4
    hi: UInt4
    tag: Ascii6


# ------------------------------------------------------------------- boxes
def test_standalone_box_pads_and_strips():
    s = Ascii6("ab")  # short content pads to width now (was ValueError)
    assert len(s.bits) == 48
    assert bytes(s.bits) == b"ab\x00\x00\x00\x00"
    assert s.value == "ab"  # trailing pad stripped on decode


def test_overflow_raises_and_truncate_clips_at_unit_boundary():
    with pytest.raises(ValueError):
        Ascii6("toolongvalue")
    Trunc4 = UTF8String.of(4, truncate=True, name="Trunc4")
    t = Trunc4("aaé!")  # 'aaé!' is 5 UTF-8 bytes; clipping must not split é
    assert t.value == "aaé"
    assert bytes(t.bits) == "aaé".encode()  # exactly fills the 4 bytes
    t2 = Trunc4("ééé")  # 6 bytes -> clip to 'éé' (4) - not 5 (split unit)
    assert t2.value == "éé"


def test_pad_none_requires_exact_width():
    Exact2 = UTF8String.of(2, pad=None, name="Exact2")
    assert Exact2("ab").value == "ab"
    with pytest.raises(ValueError):
        Exact2("a")


def test_table_string_longest_match_and_errors():
    m = MonName("A[PK]B")
    assert bytes(m.bits) == b"\x80\xe1\x81\x50"
    assert m.value == "A[PK]B"
    with pytest.raises(ValueError):
        MonName("Z")  # no table entry encodes 'Z'
    Lenient = String.of(
        2, encoding=MON_TABLE, errors="replace", name="Lenient"
    )
    v = Lenient(bits=__import__("bytemaker.bitvector", fromlist=["BitVector"])
                .BitVector(b"\x80\x07"))
    assert v.value == "A�"  # unmapped byte replaced, position advanced


def test_shift_jis_smoke():
    s = SJis6("アイ")  # 4 bytes in Shift-JIS, padded to 6
    assert s.value == "アイ"
    assert len(bytes(s.bits)) == 6


# ------------------------------------------------------------------ structs
def test_text_field_aligned_tier_roundtrip():
    assert Monster.plan.tier == "struct"
    m = Monster(name="AB", species=7, hp=9)
    raw = m.pack()
    assert raw == b"\x80\x81\x50\x50\x07\x09"  # content, pad, ints
    back = Monster.parse(raw)
    assert back == m and back.name == "AB"


def test_text_field_store_validates_and_canonicalizes():
    m = Monster(name="AB", species=1, hp=1)
    with pytest.raises(ValueError):
        m.name = "AAAAA"  # overflow raises at the STORE, not at pack
    m.name = "C"
    assert m.name == "C"  # slot holds the canonical plain str
    assert isinstance(m.name, str)


def test_terminator_cuts_before_decode():
    # Garbage after the terminator is normal in ROMs - and 0x07 is not in
    # the table, so decoding it would raise; the cut must happen first.
    raw = b"\x82\x50\x07\x07\x05\x06"
    m = Monster.parse(raw)
    assert m.name == "C"
    assert (m.species, m.hp) == (5, 6)


def test_text_field_shiftmask_tier_roundtrip():
    assert Packed.plan.tier == "shiftmask"
    p = Packed(lo=0xF, hi=0x1, tag="hi")
    raw = p.pack()
    assert raw[0] == 0x1F  # lsb bit order: first field least significant
    assert raw[1:] == b"hi\x00\x00\x00\x00"  # wire bytes in stream order
    assert Packed.parse(raw) == p


def test_buffer_field_roundtrip_and_validation():
    class Blob(Struct, endian="little"):
        head: UInt8
        data: Buffer16

    b = Blob(head=1, data=b"\xab\xcd")
    assert b.data == b"\xab\xcd" and isinstance(b.data, bytes)
    assert Blob.parse(b.pack()) == b
    with pytest.raises(ValueError):
        b.data = b"\xab"  # Buffer fields are exact-length


def test_sizedview_on_text_field():
    m = Monster(name="AB", species=1, hp=1)
    f = m.sizedview.name
    assert f.value == "AB" and f.num_bits == 32
    f.value = "C[PK]"  # narrowing store through the handle
    assert m.name == "C[PK]"
    assert f + "!" == "C[PK]!"  # rvalue use promotes to plain str
    snap = f.boxed()
    m.name = "A"
    assert snap.value == "C[PK]" and f.value == "A"  # detached vs live


def test_str16_legacy_exact_behavior_now_pads():
    # Legacy-visible behavior change (ruled): Str16("a") used to raise.
    s = Str16("a")
    assert s.value == "a" and len(s.bits) == 16


def test_sub_byte_text_width_rejected_in_struct():
    Odd = String.of(1, encoding="ascii", name="Odd1")
    Odd._num_bits = 12  # force a non-byte width

    with pytest.raises(PlanCompileError):
        class Bad(Struct):
            t: Odd
            pad: UInt4
