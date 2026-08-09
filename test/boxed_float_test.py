"""Boxed floats on the shiftmask tier (wd-3): non-IEEE float types
(BFloat16/TF19/FP24) as fields and Array elements, IEEE floats knocked
off the struct tier by sub-byte siblings or a cross-endian override, and
misaligned float widths. The tier converts float <-> bit pattern through
the type's OWN codec at the tuple boundary; byte order rides the same
swap as multi-byte ints."""

import math

import pytest

from bytemaker.bittypes import (
    BFloat16,
    FP24,
    Float32,
    TF19,
    UInt4,
    UInt5,
    UInt8,
)
from bytemaker.structs import Array, Struct, field


class BfRec(Struct, endian="little"):
    scale: BFloat16
    n: UInt8


class MixedF32(Struct, endian="little"):  # sub-byte siblings force shiftmask
    lo: UInt4
    hi: UInt4
    f: Float32


class Tf19Rec(Struct, endian="big"):  # misaligned 19-bit float, padded
    t: TF19
    pad: UInt5


def test_bfloat16_field_roundtrip():
    assert BfRec.plan.tier == "shiftmask"
    for val in (1.5, -2.0, 0.0, 0.25):
        r = BfRec(scale=val, n=7)
        back = BfRec.parse(r.pack())
        assert back == r and back.scale == val
    # wire check: BFloat16(1.5) pattern is 0x3FC0, little-endian on the wire
    assert BfRec(scale=1.5, n=7).pack() == b"\xc0\x3f\x07"


def test_bfloat16_narrows_through_codec_at_store():
    r = BfRec(scale=0.0, n=0)
    r.scale = 1.0 + 2**-9  # below bf16 precision at 1.0: quantizes
    assert r.scale == 1.0  # the slot holds exactly what pack() serializes


def test_ieee_float_beside_sub_byte_fields():
    # Previously: PlanCompileError "float fields require byte alignment...
    # (record fell back to the shift/mask tier, which is integer-only)".
    assert MixedF32.plan.tier == "shiftmask"
    for val in (0.5, -0.5, float("inf")):
        m = MixedF32(lo=1, hi=2, f=val)
        assert MixedF32.parse(m.pack()).f == val
    n = MixedF32(lo=0, hi=0, f=float("nan"))
    assert math.isnan(MixedF32.parse(n.pack()).f)


def test_cross_endian_float_field():
    class XE(Struct, endian="little"):
        f: float = field(Float32, endian="big")
        n: UInt8

    x = XE(f=1.0, n=3)
    assert x.pack() == bytes.fromhex("3f800000") + b"\x03"  # BE IEEE 1.0
    assert XE.parse(x.pack()) == x


def test_misaligned_tf19_field():
    for val in (1.5, -1.5, 0.0):
        t = Tf19Rec(t=val, pad=0)
        assert Tf19Rec.parse(t.pack()).t == val
    assert Tf19Rec.num_bits == 24


def test_fp24_field_and_array():
    class F24(Struct, endian="little"):
        x: FP24

    f = F24(x=-3.25)
    assert F24.parse(f.pack()).x == -3.25

    arr = Array.of(FP24, 2, endian="big")
    assert arr.parse(arr.pack([1.0, -1.0])) == [1.0, -1.0]


def test_bfloat16_standalone_array_both_endians():
    values = [1.5, -2.0, 0.25]
    le = Array.of(BFloat16, 3, endian="little")
    be = Array.of(BFloat16, 3, endian="big")
    assert le.parse(le.pack(values)) == values
    assert be.parse(be.pack(values)) == values
    assert le.pack(values) == b"\xc0\x3f\x00\xc0\x80\x3e"
    assert be.pack(values)[:2] == b"\x3f\xc0"  # byte order applied


def test_pure_ieee_records_keep_the_struct_tier():
    class Pure(Struct, endian="little"):
        a: Float32

    assert Pure.plan.tier == "struct"  # no regression on the fast path


def test_nested_struct_with_boxed_float_flattens():
    class Inner(Struct, endian="little"):
        s: BFloat16

    class Outer(Struct, endian="little"):
        head: UInt8
        inner: Inner

    o = Outer(head=1, inner=Inner(s=-2.0))
    assert Outer.parse(o.pack()) == o  # codec survives the leaf copy
