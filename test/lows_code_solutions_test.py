"""Tests for the Stage-14 lows-code solutions.

Behavioral coverage for the code-nit cluster: iter_tuples over-count +
aligned-gate exemption (lows-code-2), 1-bit sign-magnitude/ones'-complement
SInt (lows-code-3), from_int strict signed sizing across all three backends
(lows-code-4), bitarray __setitem__ value-before-index coercion (lows-code-5),
twos_complement range validation (lows-code-6), public-surface consistency
(lows-code-9), the bitarray tobytes override (lows-code-11), unhashability
(lows-code-12), and the narrowed plan-compile fallback (lows-code-13).
"""

from dataclasses import make_dataclass

import pytest

from bytemaker.bitvector.bitvector_native import BitVector as NativeBitVector
from bytemaker.bitvector.bitvector_speedup import BitVector as SpeedupBitVector
from bytemaker.bittypes import Buffer, Float32, UInt8, UInt16
from bytemaker.bittypes.int import Int, SInt
from bytemaker.structs import Struct
from bytemaker.utils import twos_complement

_BACKENDS = [
    pytest.param(NativeBitVector, id="native"),
    pytest.param(SpeedupBitVector, id="speedup"),
]
try:
    from bytemaker.bitvector.bitvector_with_bitarray_speedup import (
        BitVector as BitarrayBitVector,
    )

    _BACKENDS.append(pytest.param(BitarrayBitVector, id="bitarray"))
except ImportError:  # bitarray is optional
    pass

SInt1 = SInt.specialize(1, None)


# ------------------------------------------------------------- lows-code-2
class _AlignedU16(Struct, endian="big"):  # struct tier
    a: UInt16


def test_iter_tuples_over_count_raises_on_struct_tier():
    plan = _AlignedU16.plan
    assert plan.tier == "struct"
    buf = b"\x00\x01\x00\x02"  # two whole records
    with pytest.raises(ValueError, match=r"requested 3 records but only 2"):
        list(plan.iter_tuples(buf, 0, count=3))
    # count=None and exact counts are unchanged
    assert list(plan.iter_tuples(buf)) == [(1,), (2,)]
    assert list(plan.iter_tuples(buf, 0, count=2)) == [(1,), (2,)]


def test_aligned_gate_exempts_byte_order_agnostic_leaves():
    Buffer4 = Buffer.of(nbytes=4, name="Buffer4LC")

    class Child(Struct, endian="little"):  # all order-agnostic leaves
        a: UInt8
        b: Buffer4

    class Parent(Struct, endian="big"):
        c: UInt8
        child: Child

    # Promoted to the struct tier despite the cross-endian nesting.
    assert Parent.plan.tier == "struct"
    p = Parent(c=1, child=Child(a=2, b=b"\x03\x04\x05\x06"))
    # Byte output is unchanged by the promotion (single-byte/'b' leaves are
    # order-agnostic), and the plan reads the same tuple back.
    assert p.pack() == b"\x01\x02\x03\x04\x05\x06"
    assert Parent.plan.unpack_tuple(p.pack()) == (1, 2, b"\x03\x04\x05\x06")

    class Child2(Struct, endian="little"):  # endian-sensitive u16 leaf
        x: UInt16

    class Parent2(Struct, endian="big"):
        c: UInt8
        child: Child2

    assert Parent2.plan.tier == "shiftmask"  # NOT exempted


# ------------------------------------------------------------- lows-code-3
@pytest.mark.parametrize("fmt", ["signed_magnitude", "ones_complement"])
def test_one_bit_signed_constructs_and_roundtrips(fmt):
    x = SInt1(0, int_format=fmt)
    assert x.value == 0
    assert x.bits.to01() == "0"
    # a 1-bit '1' decodes to -0 == 0 in both non-two's formats (was ValueError)
    assert Int.to_pyint("1", signed=True, bin_format=fmt) == 0


def test_one_bit_bitstring_and_wider_widths_unchanged():
    assert Int.to_bitstring(0, signed=True, bit_length=1, rep_format="signed_magnitude") == "0"
    assert Int.to_pyint("1010", signed=True, bin_format="signed_magnitude") == -2
    assert Int.to_pyint("1010", signed=True, bin_format="ones_complement") == -5


# ------------------------------------------------------------- lows-code-4
@pytest.mark.parametrize("BitVector", _BACKENDS)
def test_from_int_sizes_with_sign_bit(BitVector):
    with pytest.raises(ValueError, match="sign bit included"):
        BitVector.from_int(127, 7)
    with pytest.raises(ValueError, match="sign bit included"):
        BitVector.from_int(-3, 2)
    # the round-trippable widths work and recover the value signed
    assert BitVector.from_int(127, 8).to_int(signed=True) == 127
    assert BitVector.from_int(-3, 3).to_int(signed=True) == -3
    # existing pins unchanged
    assert BitVector.from_int(5).to01() == "0101"
    assert BitVector.from_int(-3).to01() == "101"
    with pytest.raises(ValueError):
        BitVector.from_int(8, 2)


# ------------------------------------------------------------- lows-code-5
@pytest.mark.parametrize("BitVector", _BACKENDS)
def test_setitem_validates_value_before_index(BitVector):
    v = BitVector()
    # value validated first -> ValueError, not IndexError, on all backends
    with pytest.raises(ValueError, match="bit must be 0 or 1"):
        v[1] = 2
    # a pure out-of-range index with a valid bit still raises IndexError
    with pytest.raises(IndexError):
        v[1] = 0


# ------------------------------------------------------------- lows-code-6
def test_twos_complement_range_validation():
    with pytest.raises(ValueError, match="does not fit"):
        twos_complement(-200, 8)
    with pytest.raises(ValueError, match="does not fit"):
        twos_complement(300, 8)
    assert twos_complement(-128, 8) == "10000000"
    assert twos_complement(127, 8) == "01111111"
    assert twos_complement(-1, 8) == "11111111"


# ------------------------------------------------------------- lows-code-9
def test_narrowinglist_exported():
    import bytemaker.structs as structs

    assert "NarrowingList" in structs.__all__
    assert structs.NarrowingList is not None


def test_float_to_bitstring_rename():
    assert not hasattr(Float32, "to_binstring")
    assert Float32.to_bitstring(1.5) == Float32(1.5).bits.to01()


def test_table_bytes_per_char_message():
    from bytemaker.bittypes.string import _table_bytes_per_char

    _, reason = _table_bytes_per_char({0x01: "[PK]"})
    assert reason == "b'\\x01' maps to '[PK]', which is not a single character"


# ------------------------------------------------------------- lows-code-11
@pytest.mark.parametrize("BitVector", _BACKENDS)
def test_tobytes_matches_bytes(BitVector):
    for bits in ("00000001", "0000000110"):  # byte-aligned + ragged
        v = BitVector(bits)
        assert bytes(v) == v.tobytes()


# ------------------------------------------------------------- lows-code-12
def test_bittype_is_unhashable():
    with pytest.raises(TypeError):
        hash(UInt8(1))


# ------------------------------------------------------------- lows-code-13
def test_plan_compile_fallback_survives_narrowed_except():
    DC = make_dataclass("DCBareList", [("x", list)])
    from bytemaker.conversions.aggregate_types import _get_record_plan

    assert _get_record_plan(DC) is None
