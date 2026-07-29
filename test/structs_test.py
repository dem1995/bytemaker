"""
Tests for bytemaker.structs: Struct/Array/Codec declaration, both engine
tiers, store-time narrowing, sub-byte and byte-straddling fields, the msb
bit-order differential against the legacy bits path, and the bulk hatches.
"""

import struct as pystruct
from dataclasses import make_dataclass

import pytest

from bytemaker import _legacy_aggregate as legacy
from bytemaker.bittypes import (
    Float32,
    SInt4,
    SInt6,
    SInt16,
    UInt3,
    UInt4,
    UInt5,
    UInt6,
    UInt8,
    UInt10,
    UInt16,
    UInt32,
)
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Array, Codec, Struct, u16, u32
import bytemaker.structs as structs_mod


# --------------------------------------------------------------------- decls
class WarpDestination(Struct, endian="little"):
    room_ptr: UInt32
    x: UInt16
    y: UInt16
    x_offset: SInt16
    y_offset: SInt16


class ConsumableEntry(Struct, endian="little"):
    gid: UInt8
    unk_01: UInt8 = 0
    icon_id: UInt8 = 0
    palette_bank: UInt8 = 0
    unk_04: UInt32 = 0
    use_type: UInt8 = 0
    unk_09: UInt8 = 0
    unk_0a: UInt16 = 0
    unk_0c: UInt32 = 0


class Nibbles(Struct, endian="little"):  # sub-byte: shiftmask tier
    low: UInt4
    high: UInt4


class ThreeFive(Struct, endian="little"):
    flags3: UInt3
    counter5: UInt5


class FourSixes(Struct, endian="little"):  # byte-straddling fields
    a: UInt6
    b: UInt6
    c: UInt6
    d: UInt6


class MixedTier(Struct, endian="little"):  # aligned fields forced to shiftmask
    head: UInt8
    n1: UInt4
    n2: UInt4
    tail: UInt16


class Annotated16(Struct, endian="little"):  # checker-friendly aliases
    a: u16
    b: u32


class Inner(Struct, endian="little"):
    p: UInt8
    q: UInt16


class Outer(Struct, endian="little"):  # nested struct, flattened plan
    head: UInt8
    inner: Inner
    tail: UInt16


# ------------------------------------------------------------------- aligned
def test_aligned_tier_uses_struct():
    assert WarpDestination.plan.tier == "struct"
    assert WarpDestination.num_bits == 96
    assert WarpDestination.plan.struct_obj.format.endswith("IHHhh")


def test_warp_destination_roundtrip():
    raw = pystruct.pack("<IHHhh", 0x0850EF9C, 272, 512, -8, 4)
    d = WarpDestination.parse(raw)
    assert (d.room_ptr, d.x, d.y, d.x_offset, d.y_offset) == (
        0x0850EF9C,
        272,
        512,
        -8,
        4,
    )
    assert type(d.x) is int  # plain values, no boxing
    assert d.pack() == raw


def test_matches_legacy_dataclass_bytes():
    """Struct bytes == legacy dataclass-of-BitTypes bytes for the same layout."""
    LegacyWD = make_dataclass(
        "LegacyWD",
        [
            ("room_ptr", UInt32),
            ("x", UInt16),
            ("y", UInt16),
            ("x_offset", SInt16),
            ("y_offset", SInt16),
        ],
    )
    vals = (0x11223344, 5, 65535, -32768, 32767)
    assert WarpDestination(*vals).pack() == legacy.to_bytes_aggregate(
        LegacyWD(*vals), endianness="little"
    )


def test_defaults_and_repr():
    row = ConsumableEntry(gid=0x40, icon_id=27, palette_bank=6, use_type=4)
    assert row.unk_04 == 0 and row.unk_0c == 0
    assert row.pack() == bytes(
        [0x40, 0, 27, 6, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0]
    )
    assert "gid=64" in repr(row)


def test_narrowing_at_store():
    d = WarpDestination(0, 0, 0, 0, 0)
    d.x = 0x10005
    assert d.x == 5
    d.x = 70000
    assert d.x == 70000 & 0xFFFF
    d.x_offset = 0x8000
    assert d.x_offset == -32768
    d.room_ptr = -1
    assert d.room_ptr == 0xFFFFFFFF
    e = ConsumableEntry(gid=300)  # narrowing applies in __init__ too
    assert e.gid == 44
    with pytest.raises(TypeError):
        d.x = 1.5  # C-style int narrowing accepts ints only


def test_field_store_accepts_boxed_int():
    """Int.__index__ lets boxed values assign through the plain descriptors;
    the value channel narrows regardless of what carries the value."""
    n = Nibbles(low=1, high=2)
    n.low = UInt4(9)
    assert n.low == 9
    n.high = UInt8(0x1F)  # wider box: unwrap, then narrow at the store
    assert n.high == 0xF
    w = WarpDestination(0, 0, 0, 0, 0)
    w.x_offset = UInt16(0x8000)  # unsigned box into a signed field: C store
    assert w.x_offset == -32768


def test_narrowing_warning_opt_in():
    """Silent C-style narrowing by default; NarrowingConfig.warn = True is the
    -Wconversion analog (field descriptors and box value setters alike)."""
    import warnings as pywarnings

    from bytemaker.bittypes.bittype import NarrowingConfig, NarrowingWarning

    n = Nibbles(low=1, high=2)
    with pywarnings.catch_warnings():
        pywarnings.simplefilter("error")  # default off: fully silent
        n.low = 17
    assert n.low == 1

    NarrowingConfig.warn = True
    try:
        with pytest.warns(NarrowingWarning):
            n.low = 17  # unsigned field store
        with pytest.warns(NarrowingWarning):
            Nibbles(low=1, high=99)  # __init__ narrows through descriptors
        with pytest.warns(NarrowingWarning):
            WarpDestination(0, 0, 0, 0, 0).x_offset = 0x8000  # signed field
        with pytest.warns(NarrowingWarning):
            UInt4(20)  # box value setter
        with pytest.warns(NarrowingWarning):
            SInt4(8)  # signed box wrap
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("error")  # in-range stores stay silent
            n.low = 5
            UInt4(5)
    finally:
        NarrowingConfig.warn = False


def test_eq_and_detach_copy():
    a = WarpDestination(1, 2, 3, -4, 5)
    b = WarpDestination(1, 2, 3, -4, 5)
    assert a == b and a is not b
    c = a.detach_copy()
    assert c == a
    c.x = 9
    assert c != a


def test_slots_no_dict():
    d = WarpDestination(0, 0, 0, 0, 0)
    with pytest.raises(AttributeError):
        d.stray = 1


# ------------------------------------------------------------------ sub-byte
def test_nibbles_lsb_layout():
    n = Nibbles.parse(bytes([0x1F]))
    assert Nibbles.plan.tier == "shiftmask"
    assert (n.low, n.high) == (0xF, 0x1)  # first field = least significant
    assert Nibbles(low=0xF, high=0x1).pack() == bytes([0x1F])
    n.low = 17
    assert n.low == 1  # 4-bit wrap


def test_three_five_layout():
    # byte = (counter5 << 3) | flags3
    s = ThreeFive(flags3=0b101, counter5=0b10011)
    assert s.pack() == bytes([(0b10011 << 3) | 0b101])
    t = ThreeFive.parse(bytes([0xFF]))
    assert (t.flags3, t.counter5) == (7, 31)


def test_four_sixes_straddle():
    a, b, c, d = 0b100001, 0b110011, 0b101010, 0b011110
    packed = FourSixes(a, b, c, d).pack()
    val = int.from_bytes(packed, "little")
    assert val == a | (b << 6) | (c << 12) | (d << 18)
    back = FourSixes.parse(packed)
    assert (back.a, back.b, back.c, back.d) == (a, b, c, d)


def test_signed_subbyte():
    class S(Struct, endian="little"):
        a: SInt4
        b: SInt4

    s = S.parse(bytes([0xF8]))  # a = 0x8 -> -8, b = 0xF -> -1
    assert (s.a, s.b) == (-8, -1)
    assert S(a=-8, b=-1).pack() == bytes([0xF8])
    s.a = 9
    assert s.a == -7  # 4-bit signed wrap


def test_mixed_tier_free():
    m = MixedTier(head=0xAB, n1=0x2, n2=0x7, tail=0x1234)
    assert MixedTier.plan.tier == "shiftmask"
    assert m.pack() == bytes([0xAB, 0x72, 0x34, 0x12])
    r = MixedTier.parse(m.pack())
    assert (r.head, r.n1, r.n2, r.tail) == (0xAB, 0x2, 0x7, 0x1234)


def test_msb_matches_legacy_bits_stream():
    """bit_order='msb' with big-endian fields reproduces the legacy
    to_bits_aggregate stream order for byte-multiple records."""

    class MsbRec(Struct, endian="big", bit_order="msb"):
        a: UInt3
        b: UInt5
        c: UInt10
        d: SInt6

    LegacyRec = make_dataclass(
        "LegacyRec", [("a", UInt3), ("b", UInt5), ("c", UInt10), ("d", SInt6)]
    )
    for vals in [(0b101, 0b10011, 0x2AB, -17), (7, 31, 1023, -32), (0, 0, 0, 0)]:
        bits = legacy.to_bits_aggregate(
            LegacyRec(UInt3(vals[0]), UInt5(vals[1]), UInt10(vals[2]), SInt6(vals[3]))
        )
        assert MsbRec(*vals).pack() == bytes(bits)
        parsed = MsbRec.parse(bytes(bits))
        assert (parsed.a, parsed.b, parsed.c, parsed.d) == vals


# -------------------------------------------------------------------- errors
def test_total_not_byte_multiple_is_import_error():
    with pytest.raises(PlanCompileError):

        class Lonely(Struct, endian="little"):
            a: UInt8
            nib: UInt4


def test_bad_annotation_is_import_error():
    with pytest.raises(PlanCompileError):

        class Bad(Struct):
            a: int


def test_subclassing_concrete_struct_forbidden():
    with pytest.raises(PlanCompileError):

        class Child(WarpDestination):
            extra: UInt8


def test_float_in_shiftmask_is_import_error():
    with pytest.raises(PlanCompileError):

        class FloatMix(Struct, endian="little"):
            n: UInt4
            m: UInt4
            f: Float32


# -------------------------------------------------------------------- nested
def test_nested_flattening():
    assert Outer.num_bits == 8 + 24 + 16
    o = Outer(head=1, inner=Inner(p=2, q=0x0304), tail=0x0506)
    assert o.pack() == bytes([1, 2, 0x04, 0x03, 0x06, 0x05])
    r = Outer.parse(o.pack())
    assert isinstance(r.inner, Inner)
    assert (r.head, r.inner.p, r.inner.q, r.tail) == (1, 2, 0x0304, 0x0506)
    with pytest.raises(TypeError):
        o.inner = 5  # nested fields require a child instance


# --------------------------------------------------------------------- codec
def test_codec_protocol():
    assert isinstance(WarpDestination, Codec)
    assert isinstance(UInt16 * 4, Codec)


def test_annotated_aliases():
    a = Annotated16(a=0x1234, b=0x56789ABC)
    assert type(a.a) is int
    assert a.pack() == bytes([0x34, 0x12, 0xBC, 0x9A, 0x78, 0x56])


def test_scalar_parse_boxed():
    arr = Array.of(UInt16, 3, endian="little")
    out = arr.parse(bytes([1, 0, 2, 0, 0xFF, 0xFF]))
    assert [v.value for v in out] == [1, 2, 0xFFFF]
    assert arr.pack(out) == bytes([1, 0, 2, 0, 0xFF, 0xFF])
    assert arr.pack([1, 2, 0x1FFFF]) == bytes([1, 0, 2, 0, 0xFF, 0xFF])  # narrows


# -------------------------------------------------------------------- arrays
def test_struct_array_roundtrip():
    table = WarpDestination * 3
    assert table.num_bits == 96 * 3
    rows = [
        WarpDestination(i, i + 1, i + 2, -i, i) for i in range(3)
    ]
    blob = table.pack(rows)
    assert len(blob) == 36
    back = table.parse(blob)
    assert back == rows


def test_array_of_array():
    grid = (UInt8 * 2) * 3
    blob = bytes(range(6))
    back = grid.parse(blob)
    assert [[v.value for v in row] for row in back] == [[0, 1], [2, 3], [4, 5]]
    assert grid.pack(back) == blob


def test_array_cache_identity():
    assert (WarpDestination * 3) is (WarpDestination * 3)


# --------------------------------------------------------------- bulk hatch
def test_plan_unpack_tuple_and_iter_tuples():
    raw = pystruct.pack("<IHHhh", 7, 8, 9, -1, 1)
    assert WarpDestination.plan.unpack_tuple(raw) == (7, 8, 9, -1, 1)
    buf = raw * 4
    tuples = list(WarpDestination.plan.iter_tuples(buf))
    assert tuples == [(7, 8, 9, -1, 1)] * 4
    some = list(WarpDestination.plan.iter_tuples(buf, offset=12, count=2))
    assert some == [(7, 8, 9, -1, 1)] * 2


def test_plan_pack_tuple_wraps():
    raw = WarpDestination.plan.pack_tuple((0x1_0000_0005, 70000, 0, 0x8000, -4))
    d = WarpDestination.parse(raw)
    assert (d.room_ptr, d.x, d.x_offset) == (5, 70000 & 0xFFFF, -32768)


def test_byte_and_bit_offsets():
    assert ConsumableEntry.plan.byte_offset("icon_id") == 2
    assert FourSixes.plan.bit_offset("c") == 12
    with pytest.raises(ValueError):
        FourSixes.plan.byte_offset("c")
    assert Outer.plan.byte_offset("inner.q") == 2


def test_debug_validate():
    d = WarpDestination(0, 0, 0, 0, 0)
    structs_mod.DEBUG_VALIDATE = True
    try:
        d.pack()  # in-range: fine
        # force a bad slot value around the descriptor to prove pack checks
        object.__setattr__  # noqa: B018 (slots prevent stray attrs; use plan API)
        bad = WarpDestination.plan.validate_tuple
        with pytest.raises(ValueError):
            bad((0, 0x10000, 0, 0, 0))
    finally:
        structs_mod.DEBUG_VALIDATE = False


def test_parse_wrong_length_raises():
    with pytest.raises(ValueError):
        WarpDestination.parse(b"\x00" * 11)
