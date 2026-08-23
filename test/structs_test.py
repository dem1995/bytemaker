"""
Tests for bytemaker.structs: Struct/Array/Codec declaration, both engine
tiers, store-time narrowing, sub-byte and byte-straddling fields, the msb
bit-order differential against the legacy bits path, and the bulk hatches.
"""

import struct as pystruct
from dataclasses import make_dataclass

import pytest

from bytemaker.conversions import _legacy_aggregate as legacy
from bytemaker.bittypes import (
    BFloat16,
    Buffer,
    Float16,
    Float32,
    Float64,
    SInt4,
    SInt6,
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    UInt,
    UInt3,
    UInt4,
    UInt5,
    UInt6,
    UInt8,
    UInt10,
    UInt16,
    UInt32,
    UInt64,
    UTF8String,
    bytes_to_bittype,
)
from bytemaker.bittypes.int import SignedConfig
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Array, Codec, Struct, array, field, u8, u16, u32
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


def test_a_field_whose_slot_would_shadow_an_internal_is_refused():
    """A field's storage is "_bm_<name>", so the collision has a second
    direction the guard used to miss. Every one of these compiled: "repr_of"
    put an int where the repr helper was (the record read and packed fine and
    only repr() broke), "adapters" shadowed the dict rom.Space.deref reads,
    and the rest surfaced as "'tuple' object has no attribute '__set__'" at
    construction -- all of them far from the declaration that caused it."""
    for bad in ("repr_of", "adapters", "fields", "field_types", "endian",
                "concrete"):
        with pytest.raises(PlanCompileError, match="Struct internal") as caught:
            structs_mod.StructMeta(
                "Bad", (Struct,), {"__annotations__": {bad: UInt8}}
            )
        assert f"_bm_{bad}" in str(caught.value)  # names the actual collision
        assert f"{bad}_" in str(caught.value)  # ... and suggests a way out


def test_a_field_named_after_a_plain_internal_prefix_is_still_fine():
    """The guard must key off a real class member, not the "_bm_" spelling:
    "hp" is fine even though "_bm_hp" is where it lives."""

    class Ok(Struct, endian="little"):
        hp: UInt8
        repr_of_: UInt8  # the suggested rename works

    assert repr(Ok(hp=1, repr_of_=2)) == "Ok(hp=1, repr_of_=2)"


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


def test_float_in_shiftmask_is_boxed_not_rejected():
    # Once a PlanCompileError ("the shift/mask tier is integer-only");
    # floats are now boxed through their own codec at the tuple boundary.
    # Full coverage in test/boxed_float_test.py.
    class FloatMix(Struct, endian="little"):
        n: UInt4
        m: UInt4
        f: Float32

    assert FloatMix.plan.tier == "shiftmask"
    fm = FloatMix(n=1, m=2, f=-0.5)
    assert FloatMix.parse(fm.pack()) == fm


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


def test_scalar_parse_plain():
    # The one decoded-scalar rule: decoded scalars are always plain
    # Python values (width lives in the schema; arr.element(v) re-boxes).
    arr = Array.of(UInt16, 3, endian="little")
    out = arr.parse(bytes([1, 0, 2, 0, 0xFF, 0xFF]))
    assert out == [1, 2, 0xFFFF]
    assert all(type(v) is int for v in out)
    assert arr.pack(out) == bytes([1, 0, 2, 0, 0xFF, 0xFF])
    assert arr.pack([1, 2, 0x1FFFF]) == bytes([1, 0, 2, 0, 0xFF, 0xFF])  # narrows


@pytest.mark.parametrize("endian", ["big", "little"])
@pytest.mark.parametrize(
    "elem",
    [
        UInt8, UInt16, UInt32, UInt64,
        SInt8, SInt16, SInt32, SInt64,
        UInt.specialize(24, name_="UInt24T"),  # letter-less: int.from_bytes path
        Float32, Float64,
    ],
)
def test_scalar_array_matches_box_reference(elem, endian):
    """The fast paths must yield exactly what the config-aware box
    reference (element(bits=...).value) yields, for every kind and both
    byte orders — and round-trip."""
    arr = Array.of(elem, 4, endian=endian)
    data = bytes(range(1, 1 + arr.num_bytes))
    out = arr.parse(data)
    size = elem.num_bits // 8
    ref = [
        bytes_to_bittype(data[i : i + size], elem, endianness=endian).value
        for i in range(0, len(data), size)
    ]
    assert out == ref
    assert arr.pack(out) == data


def test_scalar_array_ignores_signed_config():
    """R9 / 13 #17: the new Struct/Plan/Array system is two's-complement and
    config-INDEPENDENT (SignedConfig governs only the legacy layer). A
    standalone Array and the same schema as a Struct field must agree
    byte-for-byte under ANY global config -- both two's complement."""
    data = bytes([0x80, 0x05, 0x00, 0x05])
    arr = Array.of(SInt16, 2, endian="big")

    class Rec(Struct, endian="big"):
        v: SInt16 * 2

    old = SignedConfig.signed_int_format
    for cfg in ("twos_complement", "signed_magnitude", "ones_complement"):
        SignedConfig.signed_int_format = cfg
        try:
            assert arr.parse(data) == [-32763, 5]  # two's complement, always
            assert arr.pack(arr.parse(data)) == data  # standalone round-trip
            assert list(Rec.parse(data).v) == arr.parse(data)  # field == standalone
        finally:
            SignedConfig.signed_int_format = old


def test_text_and_bytes_array_elements_stream_order():
    """String/Buffer elements have no byte order: endian='little' must
    not byte-swap them (it used to, in both parse and pack), matching the
    plan engine's rule for "b" fields and C char[]."""
    Tag2 = UTF8String.of(nbytes=2, name="Tag2")
    tags = Array.of(Tag2, 2, endian="little")
    assert tags.parse(b"hiyo") == ["hi", "yo"]
    assert tags.pack(["hi", "yo"]) == b"hiyo"

    B2 = Buffer.of(nbytes=2, name="B2x")
    bufs = Array.of(B2, 2, endian="little")
    assert bufs.parse(b"\x01\x02\x03\x04") == [b"\x01\x02", b"\x03\x04"]
    assert bufs.pack([b"\x01\x02", b"\x03\x04"]) == b"\x01\x02\x03\x04"


def test_non_ieee_float_carried_not_rejected():
    """Non-IEEE floats classify LETTER-LESS (never the width-keyed IEEE
    letter, which would mis-decode BFloat16 as binary16) and are carried
    by the boxed-codec paths in both Struct fields and Arrays — the old
    hard reject, and before that Array's silent integer fallback, are
    both gone. Full coverage in test/boxed_float_test.py."""
    from bytemaker.bittypes import FP24
    from bytemaker.plans import _classify_scalar

    for nf in (BFloat16, FP24):
        _width, kind, letter = _classify_scalar(nf)
        assert kind == "f" and letter is None

        class Ok(Struct, endian="little"):
            x: nf

        o = Ok(x=-2.0)
        assert Ok.parse(o.pack()).x == -2.0
        arr = Array.of(nf, 2, endian="little")
        assert arr.parse(arr.pack([1.0, -1.0])) == [1.0, -1.0]


def test_array_is_an_immutable_value_object():
    """Byte order and size are compiled into the codec at construction and
    instances are shared via Array.of, so the identity attributes are
    read-only; mutating one used to desync parse (cached codec) from pack
    (live read)."""
    arr = Array.of(UInt16, 2, endian="big")
    for attr in ("element", "count", "endian", "num_bits"):
        with pytest.raises(AttributeError):
            setattr(arr, attr, arr.__getattribute__(attr))


def test_scalar_array_special_float_values_match_reference():
    """The struct fast path must agree with the box reference on NaN,
    infinities, negative zero, and subnormals (Float16), for both byte
    orders."""
    import math

    specials = [
        math.nan, math.inf, -math.inf, 0.0, -0.0,
        5.960464477539063e-08,  # smallest Float16 subnormal
        6.103515625e-05,  # smallest Float16 normal
    ]
    for endian in ("big", "little"):
        arr = Array.of(Float16, len(specials), endian=endian)
        packed = arr.pack(specials)
        out = arr.parse(packed)
        size = 2
        ref = [
            bytes_to_bittype(packed[i : i + size], Float16, endianness=endian).value
            for i in range(0, len(packed), size)
        ]
        for got, want in zip(out, ref):
            assert (math.isnan(got) and math.isnan(want)) or got == want
            # sign of zero must survive too
            if want == 0:
                assert math.copysign(1, got) == math.copysign(1, want)


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
    assert back == [[0, 1], [2, 3], [4, 5]]  # plain values all the way down
    assert grid.pack(back) == blob


def test_array_cache_identity():
    assert (WarpDestination * 3) is (WarpDestination * 3)


# ------------------------------------------------------------ array fields (R8)
def test_array_field_numeric_matches_hand_written_scalars():
    """A numeric array field flattens to repeated leaves and is byte- and
    value-identical to the equivalent hand-written scalar fields."""
    class Packed(Struct, endian="little"):
        a: UInt16
        b: UInt16
        c: UInt16
        d: UInt16

    class Arr(Struct, endian="little"):
        vals: UInt16 * 4

    assert Arr.plan.tier == "struct"
    assert Arr.plan.struct_obj.format == "<HHHH"
    raw = Arr(vals=[1, 2, 3, 40000]).pack()
    assert raw == Packed(a=1, b=2, c=3, d=40000).pack()
    assert Arr.parse(raw).vals == [1, 2, 3, 40000]


def test_array_field_sugar_inherits_record_endian():
    """`UInt16 * N` (endian unset) inherits the record's byte order (C
    array), so a little-endian record's array field is little-endian and
    equals the standalone codec at the record's endian."""
    class LE(Struct, endian="little"):
        v: UInt16 * 2

    class BE(Struct, endian="big"):
        v: UInt16 * 2

    assert LE(v=[0x0102, 0x0304]).pack() == b"\x02\x01\x04\x03"
    assert BE(v=[0x0102, 0x0304]).pack() == b"\x01\x02\x03\x04"
    raw = LE(v=[7, 8]).pack()
    assert LE.parse(raw).v == Array.of(UInt16, 2, endian="little").parse(raw)


def test_array_field_explicit_endian_is_honored():
    """An explicitly-endianed Array field keeps its byte order even against
    the record's (like a nested Struct with an explicit endian)."""
    BE2 = Array.of(UInt16, 2, endian="big")

    class Mixed(Struct, endian="little"):
        be: BE2
        le: UInt16 * 2

    raw = Mixed(be=[0x0102, 0x0304], le=[0x0102, 0x0304]).pack()
    assert raw[:4] == b"\x01\x02\x03\x04"  # big
    assert raw[4:8] == b"\x02\x01\x04\x03"  # little
    assert Mixed.parse(raw) == Mixed(be=[0x0102, 0x0304], le=[0x0102, 0x0304])


def test_array_field_item_store_narrows_d1():
    """Item and slice writes narrow C-style at the store (D1): a read never
    returns a value pack() would not serialize."""
    class S(Struct, endian="little"):
        vals: UInt16 * 3

    s = S(vals=[0, 0, 0])
    s.vals[0] = 70000
    assert s.vals[0] == 70000 & 0xFFFF == 4464  # narrowed in place
    s.vals[1:3] = [70001, 70002]
    assert s.vals[1:3] == [4465, 4466]
    assert S.parse(s.pack()).vals == [4464, 4465, 4466]


def test_array_field_is_fixed_length():
    class S(Struct, endian="big"):
        vals: UInt8 * 3

    s = S(vals=[1, 2, 3])
    for op in (
        lambda: s.vals.append(4),
        lambda: s.vals.pop(),
        lambda: s.vals.insert(0, 9),
        lambda: s.vals.__delitem__(0),
        lambda: s.vals.__setitem__(slice(0, 2), [1]),  # length-changing slice
    ):
        with pytest.raises(ValueError):
            op()
    assert s.vals == [1, 2, 3]  # untouched by the failures


def test_array_field_assignment_snapshots_and_length_checks():
    class S(Struct, endian="big"):
        vals: UInt8 * 3

    ext = [10, 20, 30]
    s = S(vals=ext)
    ext[0] = 99
    assert s.vals[0] == 10  # snapshot: caller's list is not aliased
    with pytest.raises(ValueError):
        s.vals = [1, 2]  # wrong length


def test_array_field_mutable_default_not_shared():
    class S(Struct, endian="big"):
        vals: UInt8 * 3 = [0, 0, 0]

    a, b = S(), S()
    a.vals[0] = 5
    assert b.vals[0] == 0 and a.vals is not b.vals


def test_array_of_struct_field_and_dotted_offsets():
    class RGB(Struct, endian="little"):
        r: UInt8
        g: UInt8
        b: UInt8

    class Sprite(Struct, endian="little"):
        palette: RGB * 3
        id: UInt16

    assert Sprite.plan.tier == "struct"
    s = Sprite(palette=[RGB(1, 2, 3), RGB(4, 5, 6), RGB(7, 8, 9)], id=42)
    assert Sprite.parse(s.pack()) == s
    assert Sprite.plan.byte_offset("palette.1.g") == 4  # 3-byte RGB + g offset
    s.palette[0].r = 300  # child's own descriptor narrows
    assert s.palette[0].r == 44


def test_array_of_struct_field_keeps_element_endian_shiftmask():
    """A big-endian Struct element inside a little record keeps its endian,
    forcing the shiftmask tier; each leaf must still decode correctly."""
    class BE(Struct, endian="big"):
        x: UInt16

    class Rec(Struct, endian="little"):
        items: BE * 2
        tag: UInt16

    assert Rec.plan.tier == "shiftmask"
    r = Rec(items=[BE(0x0102), BE(0x0304)], tag=0x0506)
    assert Rec.parse(r.pack()) == r
    assert r.pack()[:4] == b"\x01\x02\x03\x04"  # element stayed big-endian


def test_struct_with_array_field_as_array_element():
    """Recursion: an Array of a Struct that itself has an array field."""
    class Row(Struct, endian="little"):
        cells: UInt8 * 2
        flag: UInt8

    grid = Row * 3
    rows = [Row(cells=[i, i + 1], flag=i) for i in range(3)]
    blob = grid.pack(rows)
    assert grid.parse(blob) == rows


def test_array_field_deferred_kinds_rejected():
    from bytemaker.bittypes import UTF8String

    with pytest.raises(PlanCompileError, match="text/bytes"):
        class BadStr(Struct):
            x: UTF8String.of(nbytes=2) * 2

    with pytest.raises(PlanCompileError, match="2-D array"):
        class Bad2D(Struct):
            x: (UInt8 * 2) * 2


def test_array_field_sizedview_rejected_scalar_still_works():
    class S(Struct, endian="little"):
        vals: UInt16 * 2
        id: UInt8

    s = S(vals=[1, 2], id=9)
    with pytest.raises(AttributeError, match="array field"):
        s.sizedview.vals
    assert s.sizedview.id.value == 9  # scalar handle unaffected


def test_array_field_beside_subbyte_forces_record_total_guard():
    """An array field composes with the existing sub-byte record-total
    guard; it adds no new sub-byte code path."""
    with pytest.raises(PlanCompileError, match="whole number of|multiple of 8"):
        class Bad(Struct):
            colors: UInt16 * 3  # 48 bits
            flag: UInt4  # 4 bits -> 52 total, not a byte multiple


def test_array_field_repr_and_equality():
    class S(Struct, endian="little"):
        vals: UInt8 * 3
        id: UInt8

    a = S(vals=[1, 2, 3], id=9)
    b = S(vals=[1, 2, 3], id=9)
    assert a == b
    assert repr(a) == "S(vals=[1, 2, 3], id=9)"
    a.vals[0] = 5
    assert a != b


# -- R8 review fixes -----------------------------------------------------------
class _PickRGB(Struct, endian="little"):  # module-level so pickle can find it
    r: UInt8
    g: UInt8


class _PickArr(Struct, endian="little"):
    vals: UInt16 * 3
    pts: _PickRGB * 2


def test_array_field_copy_deepcopy_pickle_roundtrip():
    """A Struct with an array field must copy/deepcopy/pickle like plain and
    nested Structs (NarrowingList and Array both had unpicklable state)."""
    import copy
    import pickle

    s = _PickArr(vals=[1, 2, 3], pts=[_PickRGB(1, 2), _PickRGB(3, 4)])
    for maker in (
        lambda x: copy.deepcopy(x),
        lambda x: pickle.loads(pickle.dumps(x)),
    ):
        c = maker(s)
        assert c == s and c.vals is not s.vals
        c.vals[0] = 9  # deep/pickle copies are independent
        assert s.vals[0] == 1
    # copy.copy of the live list rebuilds (was a 0-length ValueError)
    cc = copy.copy(s.vals)
    cc[0] = 7
    assert cc[0] == 7 and s.vals[0] == 1


def test_array_int_element_rejects_non_int_like_scalar_field():
    """Item/whole stores narrow C-style through operator.index, so a float
    or str is rejected exactly as a scalar Int field rejects it."""
    class S(Struct, endian="little"):
        scalar: UInt16
        arr: UInt16 * 2

    s = S(scalar=0, arr=[0, 0])
    for bad in (3.7, "5"):
        with pytest.raises(TypeError):
            s.scalar = bad
        with pytest.raises(TypeError):
            s.arr[0] = bad
        with pytest.raises(TypeError):
            s.arr = [bad, 0]


def test_float_array_field_narrows_and_matches_scalar():
    """Float fields (scalar and array) narrow at the store (D1): a read is
    exactly what pack() serializes, and the two paths agree."""
    class S(Struct, endian="little"):
        v: Float32
        arr: Float32 * 2

    s = S(v=0.1, arr=[0.1, 0.2])
    assert s.v == s.arr[0]  # scalar and array element agree
    r = S.parse(s.pack())
    assert r.v == s.v and list(r.arr) == list(s.arr)  # D1 round-trip
    s.arr[0] = 0.3
    assert s.arr[0] == S.parse(s.pack()).arr[0]


def test_array_field_narrowing_warning_opt_in():
    import warnings as pywarnings

    from bytemaker.bittypes.bittype import NarrowingConfig, NarrowingWarning

    class S(Struct, endian="little"):
        arr: UInt16 * 3

    s = S(arr=[0, 0, 0])
    NarrowingConfig.warn = True
    try:
        with pytest.warns(NarrowingWarning):
            s.arr[0] = 70000
        with pytest.warns(NarrowingWarning):
            s.arr[1:3] = [70001, 70002]
        with pytest.warns(NarrowingWarning):
            s.arr = [70000, 70000, 70000]
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("error")  # in-range stays silent
            s.arr[0] = 5
    finally:
        NarrowingConfig.warn = False


def test_array_field_oneshot_iterable_default_not_shared():
    """A generator/map default is materialized once so every instance gets
    an independent snapshot (not consumed by the first)."""
    class S(Struct, endian="big"):
        vals: UInt8 * 3 = (x for x in range(3))

    assert list(S().vals) == [0, 1, 2]
    assert list(S().vals) == [0, 1, 2]  # 2nd instance not empty


def test_array_field_annotated_checker_spelling_roundtrips():
    """The checker-friendly spelling `Annotated[list[T], Elem * N]` (see
    test/_typing_repro.py for the mypy contract) works identically at
    runtime -- the Array metadata is unwrapped exactly like the terse
    `Elem * N`."""
    from typing import Annotated

    Colors = Annotated[list, UInt16 * 3]  # module-alias style

    class P(Struct, endian="little"):
        colors: Colors
        tiles: Annotated[list, WarpDestination * 2]  # struct-element array
        count: UInt8

    rows = [WarpDestination(i, i + 1, i + 2, -i, i) for i in range(2)]
    p = P(colors=[1, 2, 70000], tiles=rows, count=2)
    assert p.colors == [1, 2, 4464]  # item narrowed at the store
    assert P.parse(p.pack()) == p  # round-trips like the terse spelling
    assert P.plan.byte_offset("colors.2") == 4


def test_struct_valued_defaults_detach_copied_per_instance():
    """A Struct-valued default (scalar field or array element) is
    detach-copied per instance at __init__ time, so default-constructed
    records never share one mutable instance; explicit assignment still
    stores by reference (live handles, like _StructField)."""
    class RGB(Struct, endian="big"):
        r: UInt8

    class S(Struct, endian="big"):
        pts: RGB * 1 = [RGB(0)]

    a, b = S(), S()
    assert a.pts[0] is not b.pts[0]  # each instance owns its default
    a.pts[0].r = 7
    assert b.pts[0].r == 0  # ...so mutating one cannot corrupt another

    class Boxed(Struct, endian="big"):
        c: RGB = field(RGB, default=RGB(5))

    o1, o2 = Boxed(), Boxed()
    assert o1.c is not o2.c  # scalar nested-Struct default: same rule
    o1.c.r = 99
    assert o2.c.r == 5

    shared = RGB(1)
    p, q = Boxed(c=shared), Boxed(c=shared)
    assert p.c is shared and q.c is shared  # explicit args still alias

    # numeric arrays were always independent (immutable ints)
    class N(Struct, endian="big"):
        vals: UInt8 * 3 = [0, 0, 0]

    x, y = N(), N()
    x.vals[0] = 5
    assert y.vals[0] == 0 and x.vals is not y.vals


def test_explicit_default_object_kept_live_via_missing_sentinel():
    """The _MISSING sentinel (deviation): passing the *exact* default object
    explicitly keeps a live reference rather than detach-copying it -- the
    corner an object-identity trigger would get wrong."""
    class RGB(Struct, endian="big"):
        r: UInt8

    the_default = RGB(5)

    class Boxed(Struct, endian="big"):
        c: RGB = field(RGB, default=the_default)

    passed = Boxed(c=the_default)
    assert passed.c is the_default  # explicit -> live, even for the default obj
    defaulted = Boxed()
    assert defaulted.c is not the_default  # omitted -> detach-copied


def test_boundbits_backend_extra_mutators_write_through():
    """In-place mutators BoundBits does not override explicitly (bitarray's
    setall/invert/sort on the bitarray backend) must write back through the
    width-validating store, not mutate a throwaway derivation."""
    n = Nibbles(low=0b0011, high=0)
    bb = n.sizedview.low.bits
    if not hasattr(bb, "setall"):
        pytest.skip("backend has no bitarray extras")
    bb.setall(1)
    assert n.low == 0b1111  # wrote through
    n.low = 0b0011
    bb.invert()
    assert n.low == 0b1100
    n.low = 0b0110
    bb.sort()
    assert n.low == 0b0011  # ascending: zeros then ones
    # readers still pass through, and non-callables are returned as-is
    assert bb.to01() == "0011"
    assert bb.count(1) == 2


def test_boundbits_width_changing_backend_extra_raises():
    """A backend extra that grows in place (bitarray's fill pads to a byte
    boundary) raises at the width-validating write-back; struct untouched."""
    n = Nibbles(low=0b1010, high=0)
    bb = n.sizedview.low.bits
    if not hasattr(bb, "fill"):
        pytest.skip("backend has no bitarray extras")
    with pytest.raises(ValueError):
        bb.fill()
    assert n.low == 0b1010  # failed mutation leaves the struct untouched


def test_codec_class_level_pack_convention():
    """A Struct CLASS is the codec object: parse is a classmethod and
    S.pack(s) is s.pack(); Array satisfies Codec at the instance level;
    scalar BitTypes do not satisfy it at all."""
    assert isinstance(WarpDestination, Codec)
    assert isinstance(UInt16 * 4, Codec)
    assert not isinstance(UInt16, Codec)
    d = WarpDestination(1, 2, 3, -4, 5)
    assert WarpDestination.pack(d) == d.pack()
    assert Array.of(UInt16, 2, endian="big").pack([1, 2]) == b"\x00\x01\x00\x02"
    # T * N leaves the byte order unset: standalone multi-byte numeric use
    # must say which (as a field it inherits the record's).
    with pytest.raises(ValueError, match="no byte order declared"):
        (UInt16 * 2).pack([1, 2])


# ------------------------------------------------ field()/array() specifiers
def test_field_specifier_all_kinds_roundtrip():
    """field()/array() carry the wire type on the RHS so the annotation is
    the plain checker type; runtime behaves identically to the annotation
    forms. (mypy contract: test/_typing_repro.py.)"""
    Name4 = UTF8String.of(nbytes=4)
    Buf2 = Buffer.of(nbytes=2)

    class RGB(Struct, endian="little"):
        r: int = field(UInt8)
        g: int = field(UInt8)

    class Rec(Struct, endian="little"):
        hp: int = field(UInt8)
        speed: float = field(Float32)
        name: str = field(Name4)
        data: bytes = field(Buf2)
        child: RGB = field(RGB)
        colors: list = array(UInt16, 3)

    r = Rec(hp=1, speed=1.5, name="ab", data=b"xy",
            child=RGB(r=1, g=2), colors=[10, 20, 30])
    assert Rec.parse(r.pack()) == r
    assert isinstance(r.hp, int) and isinstance(r.name, str)
    assert isinstance(r.data, bytes) and isinstance(r.child, RGB)
    assert r.colors == [10, 20, 30]
    r.colors[0] = 70000  # array element still narrows at the store
    assert r.colors[0] == 4464


def test_field_specifier_matches_annotation_form_bytes():
    """A field() spec produces byte-identical layout to the equivalent
    annotation-carried spelling."""
    class ViaSpec(Struct, endian="little"):
        a: int = field(UInt16)
        b: int = field(UInt8)

    class ViaAnno(Struct, endian="little"):
        a: u16
        b: UInt8

    assert ViaSpec(a=0x0102, b=3).pack() == ViaAnno(a=0x0102, b=3).pack()


def test_field_specifier_default_and_mutable_default():
    class S(Struct, endian="little"):
        hp: int = field(UInt8, default=100)
        colors: list = array(UInt8, 3, default=[1, 2, 3])

    a, b = S(), S()
    assert a.hp == 100 and list(a.colors) == [1, 2, 3]
    a.colors[0] = 9
    assert b.colors[0] == 1 and a.colors is not b.colors  # per-instance snapshot


def test_field_specifier_coexists_with_alias_and_bare():
    """One record mixing every declaration style compiles and round-trips."""
    from typing import Annotated

    class RGB(Struct, endian="little"):
        r: u8

    class Mix(Struct, endian="little"):
        a: u8                                  # terse alias
        b: int = field(UInt8)                  # specifier
        c: Annotated[int, UInt8]               # explicit Annotated
        d: RGB                                 # bare nested Struct
        e: list = array(UInt8, 2)              # array specifier

    m = Mix(a=1, b=2, c=3, d=RGB(r=4), e=[5, 6])
    assert Mix.parse(m.pack()) == m


def test_field_specifier_array_explicit_endian_honored():
    class M(Struct, endian="little"):
        be: list = array(UInt16, 2, endian="big")
        le: list = array(UInt16, 2)

    raw = M(be=[0x0102, 0x0304], le=[0x0102, 0x0304]).pack()
    assert raw[:4] == b"\x01\x02\x03\x04"  # explicit big honored
    assert raw[4:8] == b"\x02\x01\x04\x03"  # inherits little


def test_field_specifier_required_after_default_rejected():
    with pytest.raises(PlanCompileError, match="follows fields with defaults"):
        class Bad(Struct, endian="big"):
            a: int = field(UInt8, default=1)
            b: int = field(UInt8)  # required (no default) after a defaulted field


def test_field_specifier_annotation_must_match_wire_type():
    """The checker trusts the annotation; the runtime uses the spec. They
    must agree or bytemaker would vouch for a static type it contradicts
    (R10 review finding). The annotation-carried path already enforces this
    via _unwrap_annotation; the spec path must too."""
    from typing import Any, List

    class RGB(Struct, endian="little"):
        r: int = field(UInt8)

    # lies -> rejected at class definition
    for ann, spec in [
        (str, lambda: field(UInt8)),        # str over int wire
        (bool, lambda: field(UInt8)),       # bool over int (int subclass, still a lie)
        (float, lambda: field(UInt8)),      # float over int
        (int, lambda: field(Float32)),      # int over float
        (List[str], lambda: array(UInt16, 2)),  # list[str] over list[int]
        (int, lambda: array(UInt16, 2)),    # int over a list field
    ]:
        with pytest.raises(PlanCompileError, match="disagrees with"):
            type("Lie", (Struct,), {"__annotations__": {"x": ann}, "x": spec()})

    # truthful (incl. bare list, parameterized list, Any opt-out) -> compile
    class OK(Struct, endian="little"):
        a: int = field(UInt8)
        b: bytes = field(Buffer.of(nbytes=2))
        c: RGB = field(RGB)
        d: list = array(UInt8, 2)
        e: List[int] = array(UInt16, 2)
        f: Any = field(UInt8)

    assert OK.parse(OK(a=1, b=b"xy", c=RGB(r=1), d=[1, 2], e=[3, 4], f=9).pack())


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


# --------------------------------------------------------- wd-5: sub-byte arrays
def test_sub_byte_array_field_roundtrips_on_shiftmask():
    # The plan flattens each element into an ordinary sub-byte leaf, so
    # an Array of UInt4 needs no special engine support as a FIELD (the
    # old constructor guard rejected it before the plan ever saw it).
    from bytemaker.structs import array

    class Tiles(Struct, endian="big"):
        ids: list = array(UInt4, 6)  # 24 bits of nibbles
        tag: UInt8

    t = Tiles(ids=[1, 2, 3, 4, 5, 6], tag=0xAB)
    assert Tiles.plan.tier == "shiftmask"
    assert Tiles.parse(t.pack()) == t
    t.ids[2] = 0x1F  # narrowing store still applies element-wise
    assert t.ids[2] == 0xF
    assert Tiles.parse(t.pack()).ids == [1, 2, 0xF, 4, 5, 6]


def test_sub_byte_array_standalone_parse_pack_guarded():
    # Standalone parse/pack slice whole element BYTES; sub-byte elements
    # raise an informative error instead of dividing by zero.
    arr = Array.of(UInt4, 6)
    with pytest.raises(ValueError, match="whole-byte elements"):
        arr.parse(b"\x12\x34\x56")
    with pytest.raises(ValueError, match="Struct FIELD"):
        arr.pack([1, 2, 3, 4, 5, 6])


# ------------------------------------------------- wd-8: error attribution
def test_store_errors_name_class_and_field():
    """Runtime value errors previously surfaced bare ('str' object cannot
    be interpreted as an integer), naming nothing on a 20-field record."""
    from bytemaker.adapters import scaled
    from bytemaker.bittypes import Float32, UTF8String
    from bytemaker.structs import field

    Name2 = UTF8String.of(nbytes=2, name="Name2W8")
    Buf2b = Buffer.of(nbytes=2, name="Buf2W8")

    class Inner8(Struct, endian="big"):
        x: UInt8

    class Big(Struct, endian="big"):
        a: UInt16
        b: SInt16
        f: Float32
        s: Name2
        raw: Buf2b
        inner: Inner8
        xs: list = array(UInt8, 2)
        alt: int = field(UInt8, adapt=scaled(4))

    r = Big(
        a=1, b=-1, f=0.5, s="ab", raw=b"xy", inner=Inner8(x=1),
        xs=[1, 2], alt=8,
    )
    with pytest.raises(TypeError, match=r"Big\.a: "):
        r.a = "x"
    with pytest.raises(TypeError, match=r"Big\.b: "):
        r.b = None
    with pytest.raises(TypeError, match=r"Big\.f: "):
        r.f = object()
    with pytest.raises(ValueError, match=r"Big\.s: "):
        r.s = "toolong"
    with pytest.raises(ValueError, match=r"Big\.raw: expected exactly 2"):
        r.raw = b"x"
    with pytest.raises(TypeError, match=r"Big\.inner: expected a Inner8"):
        r.inner = 5
    with pytest.raises(ValueError, match=r"Big\.xs: "):
        r.xs = [1, 2, 3]
    with pytest.raises(ValueError, match=r"Big\.alt: "):
        r.alt = 7  # scaled(4) exact-multiple store
    # __init__ stores run through the same descriptors
    with pytest.raises(TypeError, match=r"Big\.a: "):
        Big(a="x", b=0, f=0.0, s="", raw=b"xy", inner=Inner8(x=1),
            xs=[0, 0], alt=0)
    # the original error survives as cause and suffix
    try:
        r.a = "x"
    except TypeError as exc:
        assert exc.__cause__ is not None
        assert "interpreted as an integer" in str(exc)


# --------------------------------------------- nested bit_order (find-29)
class _NibblesMsb(Struct, endian="little", bit_order="msb"):
    x: UInt4
    y: UInt4


def test_a_nested_records_bit_order_must_match_its_parents():
    """endian survives flattening (it lives on each leaf); bit_order is one
    value per Plan, so a child compiled under the other order was silently
    REPACKED under the parent's -- InnerMsb(x=1, y=2) packed b'\x12'
    standalone and b'\x21' nested, with nothing left after compilation to
    reveal it. The mismatch now refuses at class definition, the same answer
    wd-1 gave the unset-endian Array."""
    with pytest.raises(PlanCompileError, match="bit_order") as caught:

        class OuterLsb(Struct, endian="little"):  # default lsb
            i: _NibblesMsb

    msg = str(caught.value)
    assert "OuterLsb.i" in msg and "_NibblesMsb" in msg
    assert "'msb'" in msg and "'lsb'" in msg
    assert "same bit_order" in msg  # ... and it names the way out


def test_an_array_of_mismatched_bit_order_records_is_refused_too():
    """Array-of-Struct elements flatten through the same nested branch, so
    the guard covers them without a second check."""
    with pytest.raises(PlanCompileError, match="bit_order"):

        class ArrOuter(Struct, endian="little"):
            rows: list = field(_NibblesMsb * 2)


def test_matching_bit_order_nests_byte_compatibly():
    """The property the guard buys: when the orders DO match, a nested record
    occupies exactly the bytes it packs standalone."""

    class OuterMsb(Struct, endian="little", bit_order="msb"):
        i: _NibblesMsb
        tail: UInt8

    inner = _NibblesMsb(x=1, y=2)
    outer = OuterMsb(i=_NibblesMsb(x=1, y=2), tail=0xAB)
    assert inner.pack() == b"\x12"  # msb-first: x in the high nibble
    assert outer.pack() == b"\x12\xab"
    assert outer.pack()[:1] == inner.pack()
    assert OuterMsb.parse(outer.pack()) == outer


class _AlignedMsb(Struct, endian="little", bit_order="msb"):
    """Whole-byte leaves only: bit_order carries no information about its
    bytes (differentially pinned below)."""

    a: UInt8
    b: UInt16


def test_a_byte_aligned_child_is_exempt_from_the_bit_order_guard():
    """Refusing it would claim bytes could differ when they provably cannot
    -- and would make one byte-aligned child unusable across parents that
    disagree about an order it does not even express."""

    class L(Struct, endian="little"):  # default lsb
        i: _AlignedMsb
        tail: UInt8

    class M(Struct, endian="little", bit_order="msb"):
        i: _AlignedMsb
        tail: UInt8

    inner = _AlignedMsb(a=1, b=0x1234)
    for outer_cls in (L, M):  # ... including BOTH parents at once
        outer = outer_cls(i=_AlignedMsb(a=1, b=0x1234), tail=9)
        assert outer.pack()[:3] == inner.pack()  # standalone == nested
        assert outer_cls.parse(outer.pack()) == outer


def test_bit_order_is_a_noop_for_whole_byte_leaves():
    """The fact the exemption rests on, pinned differentially: byte-aligned
    records pack identically under both orders, both endians, both tiers."""
    from bytemaker.structs import StructMeta

    for endian in ("little", "big"):
        packs = []
        for bo in ("lsb", "msb"):
            cls = StructMeta(
                f"BA_{bo}_{endian}",
                (Struct,),
                {"__annotations__": {"a": UInt16, "b": UInt8, "c": UInt32}},
                endian=endian,
                bit_order=bo,
            )
            packs.append(cls(a=0x2233, b=0x11, c=0x44556677).pack())
        assert packs[0] == packs[1], endian


def test_a_sub_byte_child_is_still_refused_and_the_error_says_sub_byte():
    with pytest.raises(PlanCompileError, match="sub-byte") as caught:

        class Outer(Struct, endian="little"):
            i: _NibblesMsb

    assert "same bit_order" in str(caught.value)


def test_the_array_guard_error_names_the_field_not_element_zero():
    with pytest.raises(PlanCompileError, match=r"ArrOuter\.rows: ") as caught:

        class ArrOuter(Struct, endian="little"):
            rows: list = field(_NibblesMsb * 2)

    assert "rows.0" not in str(caught.value)


def test_boxed_serializes_in_the_fields_own_byte_order():
    """boxed() stamped the RECORD's endianness, so for a field(T, endian=)
    override the one object documented as the wire-inspection path
    serialized byte-swapped relative to what pack() writes."""

    class R(Struct, endian="little"):
        x: int = field(UInt16, endian="big")
        y: int = field(UInt16)

    r = R(x=0x1234, y=0x5678)
    assert r.pack() == b"\x12\x34\x78\x56"  # big-endian x, little-endian y
    bx, by = r.sizedview.x.boxed(), r.sizedview.y.boxed()
    assert bx.endianness == "big" and by.endianness == "little"
    assert bytes(bx) == r.pack()[:2]  # the box IS the wire, both orders
    assert bytes(by) == r.pack()[2:]
    assert (bx.value, by.value) == (0x1234, 0x5678)  # values unaffected


def test_boxed_is_the_wire_for_byte_payload_fields_too():
    """String/Buffer fields have no byte order -- pack() writes them in
    stream order whatever the record declares -- but their box used to be
    stamped with the record's endianness, so in a little-endian record
    bytes(boxed()) came out REVERSED relative to the wire. Every field
    kind's box must serialize as its pack() slice."""
    Name4 = UTF8String.of(nbytes=4, name="Name4Boxed")
    Buf3 = Buffer.of(nbytes=3, name="Buf3Boxed")

    class R(Struct, endian="little"):
        n: str = field(Name4)
        raw: bytes = field(Buf3)
        x: int = field(UInt16)

    r = R(n="ab", raw=b"\x01\x02\x03", x=0x1234)
    wire = r.pack()
    assert wire == b"ab\x00\x00\x01\x02\x03\x34\x12"
    assert bytes(r.sizedview.n.boxed()) == wire[0:4]  # was 00006261
    assert bytes(r.sizedview.raw.boxed()) == wire[4:7]  # was 030201
    assert bytes(r.sizedview.x.boxed()) == wire[7:9]  # numerics unchanged
    assert r.sizedview.n.boxed().value == "ab"  # values unaffected
