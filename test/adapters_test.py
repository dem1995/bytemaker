"""Tests for the value-transform seam: the foreign value-override guard
(df-3a), the per-field adapters (df-3b), and fused wire types (adapted-1)."""

import copy
import enum
import pickle
from typing import Annotated

import pytest

from bytemaker.adapters import (
    THUMB_PTR,
    Adapted,
    Adapter,
    biased,
    enum_,
    fixed,
    scaled,
)
from bytemaker.bittypes import UInt8, UInt16, UInt32, UTF8String
from bytemaker.introspect import bitsizeof, fields_of, sizeof
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Array, Struct, array, field


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


# ------------------------------------------- fused wire types (adapted-1)
ThumbPtr = THUMB_PTR @ UInt32
Mult = fixed(4) @ UInt16
Rewarded = biased(1) @ UInt8


def test_matmul_builds_an_adapted():
    assert isinstance(ThumbPtr, Adapted)
    assert ThumbPtr.base is UInt32 and ThumbPtr.adapter is THUMB_PTR
    assert repr(ThumbPtr) == "THUMB_PTR@UInt32"
    assert repr(Mult) == "fixed(q4)@UInt16"


def test_adapted_reports_its_width_and_user_type():
    assert ThumbPtr.num_bits == 32 and ThumbPtr.num_bytes == 4
    assert sizeof(ThumbPtr) == 4 and bitsizeof(Mult) == 16
    assert ThumbPtr.py_type is int and Mult.py_type is float


def test_adapted_is_frozen():
    with pytest.raises(AttributeError, match="frozen"):
        ThumbPtr.base = UInt16


def test_fused_and_adapt_spellings_are_the_same_class():
    class Fused(Struct, endian="little"):
        fn: ThumbPtr
        m: float = field(Mult)
        boxed: Annotated[int, ThumbPtr]

    class Spelled(Struct, endian="little"):
        fn: int = field(UInt32, adapt=THUMB_PTR)
        m: float = field(UInt16, adapt=fixed(4))
        boxed: int = field(UInt32, adapt=THUMB_PTR)

    assert Fused.num_bytes == Spelled.num_bytes
    assert sorted(Fused._bm_adapters) == sorted(Spelled._bm_adapters)
    args = dict(fn=0x0803EBA8, m=1.5, boxed=0x08014628)
    assert Fused(**args).pack() == Spelled(**args).pack()
    assert Fused(**args).to_tuple() == Spelled(**args).to_tuple()
    # ... and the plan layer never sees an Adapted: the field type is the base
    assert Fused._bm_field_types["fn"] is UInt32
    assert [f.name for f in Fused.plan.fields] == ["fn", "m", "boxed"]


def test_fused_field_reads_user_plane_and_packs_wire():
    class Anim(Struct, endian="little"):
        fn: ThumbPtr
        m: float = field(Mult)

    a = Anim(fn=0x0803EBA8, m=1.5)
    assert a.fn == 0x0803EBA8 and a.m == 1.5
    assert a.pack() == b"\xa9\xeb\x03\x08\x18\x00"  # THUMB bit set, 1.5*16
    assert Anim.parse(a.pack()) == a
    assert a.to_tuple() == (0x0803EBA9, 0x18)  # wire plane


def test_fused_introspection_reports_base_plus_adapter():
    class Anim(Struct, endian="little"):
        fn: ThumbPtr

    (info,) = fields_of(Anim)
    assert info.type is UInt32 and info.adapter is THUMB_PTR
    assert (info.bit_offset, info.bit_width) == (0, 32)


def test_fused_element_in_a_standalone_array():
    arr = Array.of(ThumbPtr, 2, endian="little")
    assert arr.element is UInt32 and arr._adapter is THUMB_PTR
    wire = b"\xa9\xeb\x03\x08\x35\xec\x03\x08"
    assert arr.parse(wire) == [0x0803EBA8, 0x0803EC34]
    assert arr.pack([0x0803EBA8, 0x0803EC34]) == wire


def test_fused_element_star_sugar_and_of_cache_share_one_array():
    assert (ThumbPtr * 2) is Array.of(ThumbPtr, 2)
    assert (2 * ThumbPtr) is Array.of(ThumbPtr, 2)
    # a module-level fused alias is reused, so the cache hits
    assert Array.of(ThumbPtr, 4, "little") is Array.of(ThumbPtr, 4, "little")


def test_fused_array_pickles_and_copies():
    arr = Array.of(ThumbPtr, 4, endian="little")
    wire = b"\xa9\xeb\x03\x08" * 4
    expect = [0x0803EBA8] * 4
    assert arr.parse(wire) == expect
    for clone in (pickle.loads(pickle.dumps(arr)), copy.deepcopy(arr)):
        assert clone.parse(wire) == expect
        assert clone.pack(expect) == wire
    clone = pickle.loads(pickle.dumps(ThumbPtr))
    assert clone.base is UInt32 and clone.num_bits == 32


def test_fused_annotation_is_checked_against_the_adapter_py_type():
    with pytest.raises(PlanCompileError, match="float"):

        class Bad(Struct, endian="little"):
            m: int = field(Mult)  # Mult reads as float

    class Good(Struct, endian="little"):
        m: float = field(Mult)

    assert Good.num_bytes == 2


def test_double_adapt_is_rejected():
    with pytest.raises(PlanCompileError, match="already carries an adapter"):

        class R(Struct, endian="little"):
            fn: int = field(ThumbPtr, adapt=biased(1))

    with pytest.raises(PlanCompileError, match="already carries an adapter"):
        Array.of(ThumbPtr, 2, "little", biased(1))


def test_fusing_onto_a_composite_or_a_fused_codec_is_rejected():
    class Inner(Struct, endian="little"):
        x: UInt8

    with pytest.raises(TypeError, match="scalar BitType class only"):
        THUMB_PTR @ Inner
    with pytest.raises(TypeError, match="scalar BitType class only"):
        THUMB_PTR @ Array.of(UInt8, 2)
    with pytest.raises(TypeError, match="scalar BitType class only"):
        THUMB_PTR @ 3
    with pytest.raises(TypeError, match="already-adapted"):
        biased(1) @ ThumbPtr


def test_array_adapter_on_composite_elements_is_rejected():
    class Inner(Struct, endian="little"):
        x: UInt8

    with pytest.raises(PlanCompileError, match="scalar element values"):
        Array.of(Inner, 2, "little", biased(1))
    with pytest.raises(PlanCompileError, match="scalar element values"):
        Array.of(Array.of(UInt8, 2), 2, "little", biased(1))


def test_fused_element_as_a_struct_field_is_still_refused():
    # adapted-2 lifts this; until then the rejection must name the reason.
    with pytest.raises(PlanCompileError, match="carrying an adapter"):

        class R(Struct, endian="little"):
            fns: list = array(ThumbPtr, 4)


def test_fused_biased_scalar_round_trips():
    class Reward(Struct, endian="little"):
        item: Rewarded

    r = Reward(item=90)
    assert r.pack() == b"\x5b"  # 91 on the wire
    assert Reward.parse(b"\x5b").item == 90
