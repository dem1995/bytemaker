"""Tests for the Stage-8 plan-engine validation solutions (plans-1, plans-2)."""

import pytest

from bytemaker.bittypes import UInt4, UInt8, UInt12
from bytemaker.structs import Struct


class ShiftRec(Struct, endian="big"):  # sub-byte fields -> shiftmask tier
    a: UInt4
    b: UInt12


class Aligned(Struct, endian="big"):  # byte-aligned -> struct tier
    a: UInt8
    b: UInt8


def test_tiers_are_as_expected():
    assert ShiftRec.plan.tier == "shiftmask"
    assert Aligned.plan.tier == "struct"


# ------------------------------------------------------------- plans-1
@pytest.mark.parametrize("plan", [ShiftRec.plan, Aligned.plan])
def test_unpack_tuple_rejects_wrong_length(plan):
    with pytest.raises(ValueError, match=r"expected 2 bytes, got 1"):
        plan.unpack_tuple(b"\x12")
    with pytest.raises(ValueError, match=r"expected 2 bytes, got 3"):
        plan.unpack_tuple(b"\x12\x34\x56")


def test_unpack_tuple_exact_length_and_memoryview():
    assert ShiftRec.plan.unpack_tuple(b"\x12\x34") == ShiftRec.plan.unpack_tuple(
        memoryview(b"\x12\x34")
    )
    assert Aligned.plan.unpack_tuple(b"\x01\x02") == (1, 2)


def test_iter_tuples_over_count_raises():
    # previously fabricated (0, 0) records from out-of-range slices
    with pytest.raises(ValueError):
        list(ShiftRec.plan.iter_tuples(b"\x12\x34" * 2, 0, count=4))


@pytest.mark.parametrize("plan", [ShiftRec.plan, Aligned.plan])
def test_iter_tuples_rejects_out_of_buffer_offset(plan):
    # A negative offset inflated avail ((len - -8) // size) and sliced
    # Python-style from the END: silently wrong records on the shiftmask
    # tier, a confusing struct.error on the struct tier. Both now raise.
    buf = b"\x12\x34" * 4
    with pytest.raises(ValueError, match="outside the buffer"):
        list(plan.iter_tuples(buf, -2))
    with pytest.raises(ValueError, match="outside the buffer"):
        list(plan.iter_tuples(buf, len(buf) + 1))
    # the boundary itself is legal: zero whole records remain
    assert list(plan.iter_tuples(buf, len(buf))) == []


def test_num_bytes_symmetry():
    """One spelling across the schema surface (Plan had it; Array had it;
    Struct and BitType now do too)."""
    from bytemaker.bittypes import UInt4, UInt16
    from bytemaker.structs import Array

    assert ShiftRec.plan.num_bytes == 2
    assert ShiftRec.num_bytes == 2 == Aligned.num_bytes
    assert Array.of(UInt16, 3).num_bytes == 6
    assert UInt16.num_bytes == 2
    assert UInt4.num_bytes == 1  # sub-byte rounds up, like len(bytes(box))


# ------------------------------------------------------------- plans-2
@pytest.mark.parametrize("plan", [ShiftRec.plan, Aligned.plan])
def test_pack_tuple_rejects_wrong_arity(plan):
    with pytest.raises(ValueError, match=r"expected 2 values, got 1"):
        plan.pack_tuple([5])
    with pytest.raises(ValueError, match=r"expected 2 values, got 3"):
        plan.pack_tuple([5, 6, 7])  # aligned tier previously truncated silently


def test_pack_tuple_exact_count_roundtrips():
    assert ShiftRec.plan.unpack_tuple(ShiftRec.plan.pack_tuple([1, 564])) == (1, 564)
    assert Aligned.plan.unpack_tuple(Aligned.plan.pack_tuple([1, 2])) == (1, 2)
