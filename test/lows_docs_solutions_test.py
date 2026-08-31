"""Tests for the Stage-12b lows-docs sweep (the __contains__ code fix + doc pins)."""

import inspect

from bytemaker.bittypes.bittype import BitType
from bytemaker.bittypes.int import Int
from bytemaker.bittypes.string import String
from bytemaker.bitvector import BitVector
from bytemaker.conversions.pytypes import pytype_to_bits
from bytemaker.plans import LegacyRecordPlan, Plan


# ------------------------------------------------------------- code fix (lows-docs-3)
def test_contains_honors_bool_contract():
    assert (object() in BitVector("0b10")) is False
    assert (BitVector("0b1") in BitVector("0b10")) is True
    assert (5 in BitVector("0b10")) is False  # non-bit int


# ------------------------------------------------------- missing docstrings (pattern 4)
def test_public_api_now_documented():
    assert LegacyRecordPlan.parse.__doc__
    assert LegacyRecordPlan.pack.__doc__
    assert Plan.num_bytes.fget.__doc__
    assert String.specialize.__doc__


# ----------------------------------------------------------- phantom params (pattern 1)
def test_phantom_params_removed():
    assert "- integer (int)" not in Int.to_bitstring.__doc__
    assert "- self" in Int.to_bitstring.__doc__
    # pytype_to_bits no longer annotates its instance arg as `type`
    assert (
        inspect.signature(pytype_to_bits).parameters["py_prim"].annotation
        is inspect.Parameter.empty
    )


# ----------------------------------------------------- broken sentences (pattern 2/3/6)
def test_broken_sentences_repaired():
    assert "differing internal bit representations" in BitType.__eq__.__doc__
    assert "differing internal bit representations" in BitType.__ne__.__doc__
    assert "BitSelf" in BitType._inplace_value_op.__doc__  # distinct from _promoted
    from bytemaker.bitvector import FixedLengthBitVector

    assert "frombytes" in FixedLengthBitVector.__doc__
