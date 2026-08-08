"""Tests for the Stage-11 buffer solutions (buffer-1, buffer-2)."""

import inspect

from bytemaker.bittypes import Buffer
from bytemaker.bitvector import BitVector


# ------------------------------------------------------------- buffer-2
def test_value_is_independent_resizable_snapshot():
    B8 = Buffer.specialize(8)
    b = B8(BitVector([0] * 8))
    v = b.value
    assert v == b.bits and v is not b.bits  # equal by value, not the live handle
    v[0] = 1
    assert b.bits.to01() == "00000000"  # reading .value cannot corrupt the box
    v.append(1)
    assert len(v) == 9 and len(b.bits) == 8  # snapshot is resizable
    b.bits[0] = 1
    assert b.value.to01() == "10000000"  # live-plane writes show in a fresh read


def test_copy_construction_from_a_box_unaffected():
    B8 = Buffer.specialize(8)
    b = B8(BitVector([0] * 8))
    assert B8(b).bits == b.bits and B8(b).bits is not b.bits


# ------------------------------------------------------------- buffer-1
def test_class_docstring_points_at_real_entry_points():
    doc = Buffer.__doc__
    assert "pre-defined subclasses" not in doc
    assert "of" in doc and "specialize" in doc
    # the orphaned duplicate literal is gone
    assert (
        inspect.getsource(Buffer).count("A BitType that represents a buffer of bits.")
        == 1
    )
