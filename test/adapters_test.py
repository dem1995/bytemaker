"""Tests for the value-transform seam: the foreign value-override guard
(df-3a) and the per-field adapters (df-3b)."""

import copy
import enum
import pickle

import pytest

from bytemaker.adapters import THUMB_PTR, Adapter, biased, enum_, fixed, scaled
from bytemaker.bittypes import UInt8, UInt16, UInt32, UTF8String
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Array, Struct, field


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


# ------------------------------------------------------------ the adapters
class Element(enum.Enum):
    NONE = 0
    FIRE = 1
    ICE = 2


class SkillEntry(Struct, endian="little"):
    anim_fn: int = field(UInt32, adapt=THUMB_PTR)
    multiplier: float = field(UInt16, adapt=fixed(4))
    reward_id: int = field(UInt8, adapt=biased(1))
    element: Element = field(UInt8, adapt=enum_(Element))


WIRE = b"\xa9\xeb\x03\x08" + b"\x18\x00" + b"\x05" + b"\x02"


def test_adapted_fields_load_on_parse():
    s = SkillEntry.parse(WIRE)
    assert s.anim_fn == 0x0803EBA8  # THUMB bit masked off
    assert s.multiplier == 1.5  # 0x18 / 16
    assert s.reward_id == 4  # wire 5, bias 1
    assert s.element is Element.ICE


def test_adapted_parse_pack_identity():
    # The slot holds the WIRE value, so parse -> pack is the identity even
    # for non-canonical wire (nothing round-trips through store()).
    assert SkillEntry.parse(WIRE).pack() == WIRE


def test_adapted_fields_store_on_assignment():
    s = SkillEntry.parse(WIRE)
    s.anim_fn = 0x0803EC34  # store sets the THUMB bit
    s.multiplier = 2.5  # -> 0x28
    s.reward_id = 9  # -> wire 10
    s.element = Element.FIRE
    assert s.pack() == b"\x35\xec\x03\x08" + b"\x28\x00" + b"\x0a" + b"\x01"
    assert s.anim_fn == 0x0803EC34  # reads back through load
    s.element = 2  # plain value validated through the enum
    assert s.element is Element.ICE
    with pytest.raises(ValueError):
        s.element = 99  # not a member


def test_adapted_field_constructor_and_default():
    class R(Struct, endian="little"):
        id_: int = field(UInt8, adapt=biased(1), default=4)

    assert R().pack() == b"\x05"  # user default 4 stored as wire 5
    assert R(id_=7).pack() == b"\x08"
    assert R.parse(b"\x05").id_ == 4


def test_adapted_store_still_narrows_wire():
    class R(Struct, endian="little"):
        id_: int = field(UInt8, adapt=biased(1))

    r = R(id_=0)
    r.id_ = 0xFF  # store -> 0x100, then u8 wire narrowing wraps to 0
    assert r.pack() == b"\x00"
    assert r.id_ == -1  # load(0) with bias 1; narrowing is wire-plane


def test_sizedview_planes_on_adapted_field():
    s = SkillEntry.parse(WIRE)
    f = s.sizedview.anim_fn
    assert f.value == 0x0803EBA8  # user plane
    assert f.boxed().value == 0x0803EBA9  # wire plane (serialization box)
    assert f.bits.to_bytes() == b"\x08\x03\xeb\xa9"  # wire bits, box order
    f.value = 0x0803EC34  # user-plane store through the adapter
    assert s.anim_fn == 0x0803EC34
    assert s.pack()[:4] == b"\x35\xec\x03\x08"


def test_sizedview_bits_writes_stay_wire_plane():
    s = SkillEntry.parse(WIRE)
    f = s.sizedview.reward_id
    f.bits = UInt8(7).bits  # wire write: no store() applied
    assert s.pack()[6] == 7
    assert s.reward_id == 6  # load(7) = 7 - 1


def test_standalone_adapted_array():
    arr = Array.of(UInt32, 2, endian="little", adapt=THUMB_PTR)
    wire = b"\xa9\xeb\x03\x08\x35\xec\x03\x08"
    assert arr.parse(wire) == [0x0803EBA8, 0x0803EC34]
    assert arr.pack([0x0803EBA8, 0x0803EC34]) == wire
    assert "THUMB_PTR" in repr(arr)


def test_adapted_array_rejected_as_field():
    arr = Array.of(UInt32, 2, endian="little", adapt=THUMB_PTR)
    with pytest.raises(PlanCompileError, match="standalone codec"):

        class R(Struct, endian="little"):
            fns: list = field(arr)


def test_adapter_on_composite_field_rejected():
    class Inner(Struct, endian="little"):
        x: UInt8

    with pytest.raises(PlanCompileError, match="scalar field types"):

        class R(Struct, endian="little"):
            inner: Inner = field(Inner, adapt=biased(1))


def test_annotation_checked_against_adapter_py_type():
    with pytest.raises(PlanCompileError, match="float"):

        class Bad(Struct, endian="little"):
            m: int = field(UInt16, adapt=fixed(4))  # reads as float

    class Good(Struct, endian="little"):
        m: float = field(UInt16, adapt=fixed(4))

    assert Good.plan is not None


def test_scaled_requires_exact_multiple():
    class R(Struct, endian="little"):
        alt: int = field(UInt8, adapt=scaled(4))

    r = R(alt=8)
    assert r.pack() == b"\x02"
    with pytest.raises(ValueError, match="multiple"):
        r.alt = 7


def test_adapter_is_frozen_and_validated():
    with pytest.raises(AttributeError, match="frozen"):
        THUMB_PTR.load = None
    with pytest.raises(TypeError, match="callable"):
        Adapter(1, 2)
    with pytest.raises(TypeError, match="Adapter"):
        field(UInt8, adapt="thumb")


def test_adapted_array_pickles_and_copies():
    arr = Array.of(UInt16, 3, endian="little", adapt=fixed(4))
    wire = b"\x18\x00\x10\x00\x08\x00"
    expect = [1.5, 1.0, 0.5]
    assert arr.parse(wire) == expect
    for clone in (pickle.loads(pickle.dumps(arr)), copy.deepcopy(arr)):
        assert clone.parse(wire) == expect
        assert clone.pack(expect) == wire


def test_repr_and_eq_use_user_plane_and_wire_plane_respectively():
    s = SkillEntry.parse(WIRE)
    assert f"anim_fn={0x0803EBA8}" in repr(s)  # user plane
    t = SkillEntry.parse(WIRE)
    assert s == t
    t.reward_id = 4  # same user value -> same wire -> still equal
    assert s == t
