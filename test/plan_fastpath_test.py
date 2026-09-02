"""
Differential tests: the plan-compiled fast paths in
bytemaker.conversions.aggregate_types must be byte- and value-identical to
the frozen reference implementation in bytemaker.conversions._legacy_aggregate, over
randomized record layouts and values.
"""

import random
from dataclasses import make_dataclass

import pytest

from bytemaker.bittypes import (
    BitType,
    Buffer,
    Float16,
    Float32,
    Float64,
    SInt,
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    UInt,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
)
from bytemaker.bittypes.int import SignedConfig
from bytemaker.bitvector import BitVector
from bytemaker.conversions import _legacy_aggregate as legacy
from bytemaker.conversions.aggregate_types import (
    from_bytes_aggregate,
    to_bytes_aggregate,
)

UInt24 = UInt.specialize(24, None)  # byte-aligned but letterless: slicing path only
SInt24 = SInt.specialize(24, None)
Buffer32 = Buffer.of(nbytes=4, name="Buffer32")  # 4 bytes (the named zoo is gone)

INT_TYPES = [
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    UInt24,
    SInt24,
]
FLOAT_TYPES = [Float16, Float32, Float64]
ALL_TYPES = INT_TYPES + FLOAT_TYPES + [Buffer32]

_counter = [0]


def random_record_class(rng, types=ALL_TYPES, max_fields=8):
    n = rng.randint(1, max_fields)
    fields = [(f"f{i}", rng.choice(types)) for i in range(n)]
    _counter[0] += 1
    return make_dataclass(f"Rec{_counter[0]}", fields), fields


def random_value(rng, ftype, boxed):
    if issubclass(ftype, SInt):
        lo, hi = -(1 << (ftype.num_bits - 1)), (1 << (ftype.num_bits - 1)) - 1
        v = rng.randint(lo, hi)
        v = rng.choice([v, lo, hi, 0])
        return ftype(v) if boxed else v
    if issubclass(ftype, UInt):
        hi = (1 << ftype.num_bits) - 1
        v = rng.choice([rng.randint(0, hi), 0, hi])
        return ftype(v) if boxed else v
    if ftype in FLOAT_TYPES:
        v = float(rng.randint(-2048, 2048))  # exactly representable at all widths
        return ftype(v) if boxed else v
    if ftype is Buffer32:
        return Buffer32(bits=BitVector(bytes(rng.randint(0, 255) for _ in range(4))))
    raise AssertionError(ftype)


def assert_equal_records(a, b, fields):
    for name, _ in fields:
        va, vb = getattr(a, name), getattr(b, name)
        assert type(va) is type(vb), (name, type(va), type(vb))
        if isinstance(va, BitType):
            assert va.bits.to01() == vb.bits.to01(), name
        else:
            assert va == vb, name


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("endianness", ["big", "little"])
def test_differential_boxed_roundtrip(seed, endianness):
    rng = random.Random(seed)
    cls, fields = random_record_class(rng)
    inst = cls(*(random_value(rng, t, boxed=True) for _, t in fields))

    packed_new = to_bytes_aggregate(inst, endianness=endianness)
    packed_old = legacy.to_bytes_aggregate(inst, endianness=endianness)
    assert packed_new == packed_old

    dec_new = from_bytes_aggregate(packed_new, cls, endianness=endianness)
    dec_old = legacy.from_bytes_aggregate(packed_old, cls, endianness=endianness)
    assert_equal_records(dec_new, dec_old, fields)

    # round-trip identity
    assert to_bytes_aggregate(dec_new, endianness=endianness) == packed_new


@pytest.mark.parametrize("seed", range(40, 70))
@pytest.mark.parametrize("endianness", ["big", "little"])
def test_differential_plain_values(seed, endianness):
    """Plain ints/floats in the fields (the trycast path), including
    out-of-range ints that must C-narrow identically."""
    rng = random.Random(seed)
    cls, fields = random_record_class(rng, types=INT_TYPES + FLOAT_TYPES)
    values = []
    for _, t in fields:
        v = random_value(rng, t, boxed=False)
        if isinstance(v, int) and rng.random() < 0.3:
            v += (1 << t.num_bits) * rng.choice([1, -1, 2])  # force wrap
        values.append(v)
    inst = cls(*values)
    assert to_bytes_aggregate(inst, endianness=endianness) == legacy.to_bytes_aggregate(
        inst, endianness=endianness
    )


@pytest.mark.parametrize("endianness", ["big", "little"])
def test_differential_signed_magnitude_config(endianness):
    """With a non-default global signed format the one-call struct shortcut is
    ineligible; the boxed coercion path must still match the oracle."""
    cls = make_dataclass("RecSM", [("a", SInt16), ("b", SInt8)])
    old_format = SignedConfig.signed_int_format
    SignedConfig.signed_int_format = "signed_magnitude"
    try:
        inst = cls(-5, -3)
        assert to_bytes_aggregate(
            inst, endianness=endianness
        ) == legacy.to_bytes_aggregate(inst, endianness=endianness)
    finally:
        SignedConfig.signed_int_format = old_format


def test_ineligible_layouts_fall_back():
    """ctypes/PyType/nested-dataclass fields must still work and round-trip.

    (This used to also assert equality with legacy.to_bytes_aggregate,
    a tautology: for ineligible layouts the public function DELEGATES to
    the reference implementation, so both sides ran the same code and the
    comparison could never fail. The real content is that the fallback
    routing works end to end.)"""
    import ctypes

    Inner = make_dataclass("Inner", [("x", UInt8)])
    Outer = make_dataclass("Outer", [("n", Inner), ("c", ctypes.c_uint16), ("p", int)])
    inst = Outer(Inner(UInt8(7)), ctypes.c_uint16(513), 9)
    for endianness in ("big", "little"):
        blob = to_bytes_aggregate(inst, endianness=endianness)
        assert isinstance(blob, bytes) and len(blob) == (8 + 16 + 32) // 8
        back = from_bytes_aggregate(blob, Outer, endianness=endianness)
        assert back.n.x.value == 7 and back.c.value == 513 and back.p == 9


def test_from_bytes_is_array_returns_list():
    cls = make_dataclass("RecArr", [("a", UInt16), ("b", UInt8)])
    one = to_bytes_aggregate(cls(UInt16(0x0102), UInt8(3)), endianness="little")
    two = to_bytes_aggregate(cls(UInt16(0x0405), UInt8(6)), endianness="little")
    out = from_bytes_aggregate(one + two, cls, is_array=True, endianness="little")
    assert isinstance(out, list) and len(out) == 2
    assert out[0].a.value == 0x0102 and out[1].b.value == 6

    scalars = from_bytes_aggregate(
        b"\x01\x00\x02\x00", UInt16, is_array=True, endianness="little"
    )
    assert [s.value for s in scalars] == [1, 2]


def test_legacy_bfloat16_bypasses_struct_shortcut():
    """BFloat16 is 16 bits but not IEEE binary16: the one-call struct
    shortcut must not claim it via the width-keyed letter (regression: a
    plain-float value packed as IEEE half, diverging from the boxed
    path and from the type's own wire format)."""
    from bytemaker.bittypes import BFloat16

    cls = make_dataclass("RecBF", [("a", BFloat16)])
    plain = to_bytes_aggregate(cls(1.5), endianness="big")
    boxed = to_bytes_aggregate(cls(BFloat16(1.5)), endianness="big")
    assert plain == boxed == bytes(BFloat16(1.5).bits)


def test_parse_length_mismatch_raises():
    cls = make_dataclass("RecLen", [("a", UInt32)])
    with pytest.raises(ValueError):
        from_bytes_aggregate(b"\x00" * 3, cls, endianness="little")
