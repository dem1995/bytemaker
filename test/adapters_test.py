"""Tests for the value-transform seam: the foreign value-override guard
(df-3a) and the per-field adapters (df-3b)."""

import pytest

from bytemaker.bittypes import UInt8, UInt16, UInt32, UTF8String
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Array, Struct


# ------------------------------------------------- foreign value override
class ThumbPointer(UInt32):
    """The 'natural workaround' a user reaches for: a two-way value
    override. Perfect as a standalone box; silently ignored by the plan
    engine — which is exactly why it must be refused as a field type."""

    @property
    def value(self):
        return super().value & ~1

    @value.setter
    def value(self, v):
        UInt32.value.fset(self, v | 1)


def test_value_override_works_standalone():
    p = ThumbPointer(0x0803EBA8)
    assert p.value == 0x0803EBA8  # override honored on the box
    assert bytes(p.bits)[-1] & 1  # THUMB bit set on the wire


def test_value_override_rejected_as_struct_field():
    with pytest.raises(PlanCompileError, match="silently ignore"):

        class Rec(Struct, endian="little"):
            fn: ThumbPointer

    with pytest.raises(PlanCompileError, match="adapt="):

        class Rec2(Struct, endian="little"):
            fn: ThumbPointer


def test_value_override_rejected_as_array_element():
    with pytest.raises(PlanCompileError, match="silently ignore"):
        Array.of(ThumbPointer, 4)


def test_engine_minted_types_still_compile():
    # of()/specialize()-minted classes define no 'value' of their own, so
    # the guard must not fire on them (String defines value in bytemaker).
    Name4 = UTF8String.of(nbytes=4, name="Name4")
    Narrow = UInt16.specialize(12, name_="Narrow12")

    from bytemaker.bittypes import UInt4

    class Ok(Struct, endian="little"):
        name: Name4
        n: Narrow
        pad: UInt4  # 32 + 12 + 4 = 48 bits, byte-aligned

    assert Ok.plan is not None
    Array.of(UInt8, 3)  # plain engine scalar unaffected
