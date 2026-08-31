"""Tests for the Stage-2 float solutions (float-1..5).

* float-1 -- the pure-Python Float codec is a correct IEEE-754 encoder/decoder
  (signed zero, subnormals, inf, NaN, overflow-to-inf, round-to-nearest-even),
  verified exhaustively against struct's half codec; plus the two net-new
  deviations: struct-packed floats saturate an out-of-range store to +/-inf
  (was OverflowError), and float overflow-to-inf warns under warn mode.
* float-2 -- specialize-with-letter uses the struct value path (MRO order).
* float-3 -- the value setter rejects strings but coerces other numbers.
* float-4 -- Int has promoted unary -/+/abs.
* float-5 -- the Float class docstring no longer says "integer".
"""

import math
import struct
import warnings as pywarnings

import pytest

from bytemaker.bittypes import NarrowingConfig, NarrowingWarning
from bytemaker.bittypes.bittype import StructPackedBitType
from bytemaker.bittypes.float import (
    FP24,
    TF19,
    BFloat16,
    Float,
    Float16,
    Float32,
)
from bytemaker.bittypes.int import SInt8, UInt8, UInt16

PyHalf = Float.specialize(5, 10, name_="PyHalf")  # pure-Python codec path


@pytest.fixture
def warn_on():
    prior = NarrowingConfig.warn
    NarrowingConfig.warn = True
    try:
        yield
    finally:
        NarrowingConfig.warn = prior


# --------------------------------------------------------------- float-1
def test_pure_python_codec_matches_struct_half_exhaustively():
    """Every 16-bit pattern decodes exactly like struct '>e', and every
    non-NaN value re-encodes to the same 16 bits."""
    dec_fail = enc_fail = 0
    for p in range(2**16):
        bits = format(p, "016b")
        got = PyHalf(bits=bits).value
        ref = struct.unpack(">e", p.to_bytes(2, "big"))[0]
        if math.isnan(ref):
            if not math.isnan(got):
                dec_fail += 1
            continue
        if got != ref or math.copysign(1.0, got) != math.copysign(1.0, ref):
            dec_fail += 1
        if PyHalf(ref).bits.to01() != bits:
            enc_fail += 1
    assert dec_fail == 0
    assert enc_fail == 0


def test_pure_python_rounding_is_ties_to_even():
    import random

    rng = random.Random(20260806)
    for _ in range(5000):
        v = rng.uniform(-60000, 60000)  # inside half's normal range
        assert PyHalf(v).bits.to01() == format(
            int.from_bytes(struct.pack(">e", v), "big"), "016b"
        )


def test_ieee_special_values_pure_path():
    assert BFloat16(0.0).value == 0.0
    assert BFloat16(0.0).bits.to01() == "0" * 16
    assert BFloat16(-0.0).bits.to01() == "1" + "0" * 15
    assert math.copysign(1.0, BFloat16(-0.0).value) == -1.0
    assert BFloat16(float("inf")).value == float("inf")
    assert BFloat16(float("-inf")).value == float("-inf")
    assert math.isnan(BFloat16(float("nan")).value)
    assert BFloat16(float("nan")).bits.to01() == "0111111111000000"


def test_subnormals_and_underflow_pure_path():
    assert BFloat16(1e-39).value == 1.0101904577379033e-39
    assert Float.to_bitstring(1e-40, 8, 7) == "0" * 15 + "1"  # smallest subnormal
    assert BFloat16(1e-50).value == 0.0  # deep underflow flushes to +0
    assert math.copysign(1.0, BFloat16(-1e-50).value) == -1.0  # keeps sign


def test_rounding_and_roundtrip_pure_path():
    assert BFloat16(0.1).bits.to01() == "0011110111001101"  # correctly rounded
    assert Float.to_bitstring(65520.0, 5, 10) == "0" + "1" * 5 + "0" * 10  # ties->inf
    for v in [0.0, -0.0, 1.5, -2.25, 1e-39, float("inf")]:
        assert TF19(TF19(v).value).bits == TF19(v).bits


def test_struct_packed_overflow_saturates_to_inf():
    """float-1 net-new (a): out-of-range store on the struct widths yields
    +/-inf instead of raising struct's OverflowError."""
    assert Float32(1e300).value == float("inf")
    assert Float32(-1e300).value == float("-inf")
    assert Float16(70000.0).value == float("inf")


def test_float_overflow_warns_under_warn_mode(warn_on):
    """float-1 net-new (b): finite -> inf saturation warns on both paths."""
    with pytest.warns(NarrowingWarning):
        BFloat16(1e40)  # pure-Python path
    with pytest.warns(NarrowingWarning):
        Float32(1e300)  # struct-packed path
    with pywarnings.catch_warnings():
        pywarnings.simplefilter("error")  # in-range (incl. mere rounding) stays silent
        BFloat16(0.1)
        Float32(1.5)


# --------------------------------------------------------------- float-2
def test_specialize_with_letter_uses_struct_path():
    SpecF32 = Float.specialize(8, 23, "f", "SpecF32")
    assert issubclass(SpecF32, StructPackedBitType)
    expected = format(int.from_bytes(struct.pack(">f", 0.1), "big"), "032b")
    assert SpecF32(0.1).bits.to01() == Float32(0.1).bits.to01() == expected
    assert SpecF32(0.0).value == 0.0 and SpecF32(value=5).value == 5.0
    owner = next(k for k in SpecF32.__mro__ if "value" in vars(k))
    assert owner is StructPackedBitType


# --------------------------------------------------------------- float-3
def test_value_setter_coerces_numbers_rejects_strings():
    assert BFloat16(value=1).value == 1.0
    assert FP24(value=True).value == 1.0
    t = TF19(1.0)
    t.value = 3
    assert t.value == 3.0
    t += 1  # exercises _inplace_value_op through the coercing setter
    assert isinstance(t, TF19) and t.value == 4.0
    assert BFloat16(value=2).bits == BFloat16(2.0).bits
    with pytest.raises(TypeError):
        BFloat16(value="1.5")  # strings rejected (maintainer ruling)
    with pytest.raises(TypeError):
        BFloat16(value=object())  # from float()


# --------------------------------------------------------------- float-4
def test_int_unary_operators_promote():
    assert -UInt8(5) == -5 and type(-UInt8(5)) is int
    assert UInt8(-UInt8(5)).value == 251  # narrowing-cast spelling wraps like C
    assert +SInt8(-3) == -3
    assert abs(SInt8(-3)) == 3 and type(abs(SInt8(-3))) is int
    assert abs(UInt16(7)) == 7
    assert -SInt8(-128) == 128  # promotes, no overflow


# --------------------------------------------------------------- float-5
def test_float_docstring_no_int_leftovers():
    doc = Float.__doc__
    assert "floating-point" in doc
    assert "represents an integer" not in doc
    assert "this `Int`" not in doc
