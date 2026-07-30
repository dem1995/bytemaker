"""Tests for text/char and bytes fields (observations/14): the Str.of
factory, pad/terminator/strip semantics, TableString, and String/Buffer
fields in Struct across both plan tiers."""

import pytest

from bytemaker.bittypes import (
    Buffer,
    String,
    TableString,
    UInt4,
    UInt8,
    UTF8String,
)
from bytemaker.bitvector import BitVector
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
Buf2 = Buffer.of(2, name="Buf2")


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


def test_truncate_clips_whole_table_tokens():
    # Clipping "A[PK]B" one char at a time passes through "A[PK]" (fits)
    # but also "A[PK" (unencodable) - truncation must skip past broken
    # tokens rather than raising or returning oversized bytes.
    TruncT = String.of(2, encoding=MON_TABLE, truncate=True, name="TruncT")
    t = TruncT("A[PK]B")
    assert t.value == "A[PK]" and bytes(t.bits) == b"\x80\xe1"
    TruncT1 = String.of(1, encoding=MON_TABLE, truncate=True, name="TruncT1")
    assert TruncT1("A[PK]").value == "A"  # clips past the broken "[PK" clip
    Long1 = String.of(
        1, encoding={b"\xe1\xe2": "[LONG]"}, truncate=True, name="Long1"
    )
    assert Long1("[LONG]").value == ""  # sole token wider than the field


def test_pad_invalid_in_codec_strips_before_decode():
    # 0xFF is not legal UTF-8 anywhere: decode must strip the pad region
    # at the byte layer first or the codec would raise on the padding.
    PadFF = UTF8String.of(4, pad=0xFF, name="PadFF")
    s = PadFF("ab")
    assert bytes(s.bits) == b"ab\xff\xff"
    assert s.value == "ab"


def test_encode_decode_callable_pair_codec():
    Pair4 = String.of(
        4,
        encoding=(lambda v: v.upper().encode("ascii"),
                  lambda b: b.decode("ascii").lower()),
        name="Pair4",
    )
    p = Pair4("hi")
    assert bytes(p.bits) == b"HI\x00\x00"
    assert p.value == "hi"

    class Tagged(Struct, endian="big"):
        tag: Pair4
        n: UInt8

    t = Tagged(tag="ab", n=3)
    assert t.pack() == b"AB\x00\x00\x03"
    assert Tagged.parse(t.pack()).tag == "ab"


def test_pad_none_requires_exact_width():
    Exact2 = UTF8String.of(2, pad=None, name="Exact2")
    assert Exact2("ab").value == "ab"
    with pytest.raises(ValueError):
        Exact2("a")


def test_table_string_longest_match_and_errors():
    assert issubclass(MonName, TableString)  # mapping encodings mint these
    m = MonName("A[PK]B")
    assert bytes(m.bits) == b"\x80\xe1\x81\x50"
    assert m.value == "A[PK]B"
    with pytest.raises(ValueError):
        MonName("Z")  # no table entry encodes 'Z'
    Lenient = String.of(
        2, encoding=MON_TABLE, errors="replace", name="Lenient"
    )
    v = Lenient(bits=BitVector(b"\x80\x07"))
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
        data: Buf2

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


def test_of_size_spellings_chars_vs_nbytes():
    # chars= derives bytes-per-char for uniform single-byte tables
    Uni3 = String.of(chars=3, encoding={0x80: "A", 0x81: "B"}, name="Uni3")
    assert Uni3.num_bits == 24 and Uni3.bytes_per_char == 1
    # exactly one size spelling
    with pytest.raises(TypeError):
        String.of(4, chars=4, encoding=MON_TABLE)
    with pytest.raises(TypeError):
        String.of(encoding=MON_TABLE)
    # control codes make character count undefined - the error names one
    with pytest.raises(TypeError, match=r"\[PK\]"):
        String.of(chars=4, encoding=MON_TABLE)
    # variable-width codecs declare no bytes-per-char
    with pytest.raises(TypeError, match="bytes-per-char"):
        UTF8String.of(chars=4)


def test_utf16_chars_sizing_and_unit_strip():
    U16 = String.of(
        chars=3, encoding="utf-16-le", bytes_per_char=2, name="U16"
    )
    assert U16.num_bits == 48
    s = U16("ab")  # 4 content bytes + one 0x00 0x00 pad unit
    assert bytes(s.bits) == b"a\x00b\x00\x00\x00"
    # byte-wise stripping would eat "b"'s high NUL and split the code unit
    assert s.value == "ab"


def test_buffer_of_is_byte_counted():
    assert Buf2.num_bits == 16
    B4 = Buffer.of(4)
    assert B4.num_bits == 32 and B4.__name__ == "Bufferx4"
    with pytest.raises(ValueError):
        Buffer.of(0)


def test_sub_byte_text_width_rejected_in_struct():
    Odd = String.of(1, encoding="ascii", name="Odd1")
    Odd._num_bits = 12  # force a non-byte width

    with pytest.raises(PlanCompileError):
        class Bad(Struct):
            t: Odd
            pad: UInt4
