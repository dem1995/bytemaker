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


# ----------------------------------------------------------------- sizedview
def test_sizedview_boundfield_lvalue():
    n = Nibbles(low=5, high=2)
    f = n.sizedview.low
    assert f.value == 5 and f.num_bits == 4
    n.low = 9
    assert f.value == 9  # live: struct -> handle
    f.value = 200  # store narrows: 200 & 0xF
    assert n.low == 8  # live: handle -> struct
    f += 9  # RMW: read-promote, full-width compute, narrowing store
    assert n.low == 1
    n.sizedview.high += 200  # compound assignment through the view
    assert n.high == (2 + 200) & 0xF
    n.sizedview.low = UInt8(0x1F)  # boxed assignment: unwrap, narrow
    assert n.low == 0xF


def test_boundfield_promotion_and_display():
    n = Nibbles(low=5, high=2)
    f = n.sizedview.low
    assert f + 3 == 8 and 3 + f == 8  # plain results, full width
    assert f > 4 and f <= 5 and f != 4
    assert f == 5 and f == UInt4(5)
    assert f == n.sizedview.low  # fresh handles compare by value
    with pytest.raises(TypeError):
        {f: 1}  # unhashable: live value under a hash is the mutable-key trap
    assert int(f) == 5 and float(f) == 5.0 and bool(f)
    assert f"{f:02x}" == "05"  # a spec formats the value
    assert f"{f}" == str(f)  # no spec = sized display, agrees with print
    assert "UInt4" in str(f)
    assert repr(f) == "<bound UInt4 low=5 of Nibbles>"
    assert "low" in dir(n.sizedview) and "high" in dir(n.sizedview)
    with pytest.raises(AttributeError):
        n.sizedview.nope
    with pytest.raises(AttributeError):
        f.valeu = 3  # typo guard: only .value / .bits are assignable


def test_boundfield_contested_operators_absent():
    for dunder in (
        "__index__",
        "__and__",
        "__or__",
        "__xor__",
        "__lshift__",
        "__rshift__",
        "__invert__",
        "__iand__",
        "__ior__",
        "__ixor__",
    ):
        # Check the MRO's own dicts: plain hasattr() would false-positive on
        # __or__ via type.__or__ (PEP 604 class-union), which binds to the
        # class object, not to instances.
        assert not any(
            dunder in c.__dict__ for c in structs_mod.BoundField.__mro__
        )
    f = Nibbles(low=5, high=2).sizedview.low
    with pytest.raises(TypeError):
        f & 1  # two lawful meanings: name the plane instead
    with pytest.raises(TypeError):
        hex(f)  # handles aren't numbers; use f"{f:#x}" or hex(f.value)
    assert f.value & 1 == 1  # the value-plane spelling


def test_boundbits_live_and_width_guarded():
    n = Nibbles(low=4, high=0)
    f = n.sizedview.low
    f.bits[2] = 1  # 0100 -> 0110, written through
    assert n.low == 6
    b = f.bits
    n.low = 15
    assert b.to01() == "1111"  # held handles never go stale
    assert len(b) == 4 and b == UInt4(15).bits
    with pytest.raises(ValueError):
        b.append(1)  # width is invariant
    assert n.low == 15  # failed mutation leaves the struct untouched
    with pytest.raises(ValueError):
        b.pop()
    f.bits = "0101"  # width-strict decode + store
    assert n.low == 5
    with pytest.raises(ValueError):
        f.bits = "01010"  # 5 bits into a 4-bit field
    n.sizedview.high.bits = f.bits  # BoundBits accepted as a source
    assert n.high == 5
    b.reverse()  # width-preserving: writes through (0101 -> 1010)
    assert n.low == 0b1010


def test_boundfield_bit_indexing():
    n = Nibbles(low=4, high=0)
    f = n.sizedview.low
    assert f[0] == 0 and f[1] == 1
    f[0] = 1
    assert n.low == 0b1100


def test_sizedview_signed_field():
    w = WarpDestination(0, 0, 0, -4, 0)
    f = w.sizedview.x_offset
    assert f.value == -4 and f < 0
    f.value = 40000  # out of SInt16 range: wraps, C-style
    assert w.x_offset == 40000 - 65536


def test_sizedview_nested_struct():
    o = Outer(head=1, inner=Inner(p=2, q=3), tail=4)
    child = o.sizedview.inner  # nested field: the child's own sizedview
    assert isinstance(child, type(o.inner.sizedview))
    child.q.value = 70000  # narrows at the store (UInt16)
    assert o.inner.q == 70000 & 0xFFFF
    o.inner.p = 9
    assert child.p.value == 9  # child view aliases the same instance


def test_boundfield_boxed_detach_and_endian():
    w = WarpDestination(1, 2, 3, -4, 5)
    f = w.sizedview.x
    snap = f.boxed()
    assert snap.value == 2
    assert snap.endianness == "little"  # record's declared endian
    w.x = 7
    assert snap.value == 2  # detached: survives later mutation
    assert f.value == 7  # ...unlike the live handle


def test_sizedview_float_field():
    class PixelF(Struct, endian="little"):
        x: UInt16
        gamma: Float32

    p = PixelF(x=3, gamma=1.5)
    g = p.sizedview.gamma
    assert g + 0.5 == 2.0  # same promotion path as int handles
    g.value = 2.5
    assert p.gamma == 2.5
    assert g[0] == 0  # sign bit of the Float32 pattern
    assert g.num_bits == 32


def test_sizedview_pack_roundtrip():
    n = Nibbles(low=1, high=2)
    n.sizedview.low.bits[1] = 1  # 0001 -> 0101
    n.sizedview.high += 1
    assert n.low == 5 and n.high == 3
    assert Nibbles.parse(n.pack()) == n


# ------------------------------------------------------------ reserved names
def test_reserved_field_names_guarded():
    for bad in ("pack", "parse", "plan", "num_bits", "sizedview",
                "detach_copy", "_bm_x"):
        with pytest.raises(PlanCompileError, match="reserved"):
            structs_mod.StructMeta(
                "Bad", (Struct,), {"__annotations__": {bad: UInt8}}
            )

    class _Padded(Struct):  # leading underscore stays legal (padding fields)
        _reserved: UInt3
        flags: UInt5

    p = _Padded(_reserved=0, flags=9)
    assert p.flags == 9


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
