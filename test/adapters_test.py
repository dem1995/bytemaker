"""Tests for the value-transform seam: the foreign value-override guard
(df-3a), the per-field adapters (df-3b), and fused wire types (adapted-1)."""

import copy
import enum
import pickle

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
from bytemaker.typing_redirect import Annotated, List


# ------------------------------------------------- foreign value override
class ThumbPointer(UInt32):
    """The 'natural workaround' a user reaches for: a two-way value
    override. Perfect as a standalone box; silently ignored by the plan
    engine, which is exactly why it must be refused as a field type."""

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


def test_adapted_array_is_a_field_type():
    # adapted-2: this used to be refused ("standalone codec only").
    arr = Array.of(UInt32, 2, endian="little", adapt=THUMB_PTR)

    class R(Struct, endian="little"):
        fns: list = field(arr)

    wire = bytes.fromhex("a9eb0308" "35ec0308")
    r = R.parse(wire)
    assert list(r.fns) == [0x0803EBA8, 0x0803EC34]  # user plane
    assert r.to_tuple() == (0x0803EBA9, 0x0803EC35)  # wire plane
    assert r.pack() == wire


def test_adapt_on_an_array_field_type_points_at_the_element_spelling():
    with pytest.raises(PlanCompileError, match="adapts its ELEMENTS"):

        class R(Struct, endian="little"):
            fns: list = field(Array.of(UInt32, 2, "little"), adapt=THUMB_PTR)


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


def test_fused_biased_scalar_round_trips():
    class Reward(Struct, endian="little"):
        item: Rewarded

    r = Reward(item=90)
    assert r.pack() == b"\x5b"  # 91 on the wire
    assert Reward.parse(b"\x5b").item == 90


# ------------------------------------ adapted Array FIELDS (adapted-2)
#: Two 32-bit THUMB pointers then two Q4 multipliers, little-endian.
ANIM_WIRE = bytes.fromhex("a9eb0308" "35ec0308" "1800" "1000")


class Anim(Struct, endian="little"):
    fns: List[int] = array(ThumbPtr, 2)
    mults: List[float] = array(Mult, 2)


def test_adapted_array_field_reads_the_user_plane():
    a = Anim.parse(ANIM_WIRE)
    assert list(a.fns) == [0x0803EBA8, 0x0803EC34]  # THUMB bit masked off
    assert list(a.mults) == [1.5, 1.0]  # Q4: 0x18, 0x10
    assert a.to_tuple() == (0x0803EBA9, 0x0803EC35, 0x18, 0x10)  # wire


def test_adapted_array_field_round_trips_canonical_wire_exactly():
    assert Anim.parse(ANIM_WIRE).pack() == ANIM_WIRE


def test_adapted_array_field_element_store_is_live_and_user_plane():
    a = Anim.parse(ANIM_WIRE)
    a.fns[0] = 0x0803ED6C
    assert a.fns[0] == 0x0803ED6C  # reads back the user value
    assert a.pack()[:4] == b"\x6d\xed\x03\x08"  # THUMB bit set on the wire
    a.mults[1] = 2.5
    assert list(a.mults) == [1.5, 2.5]
    assert a.pack()[-2:] == b"\x28\x00"  # 2.5 * 16


def test_adapted_array_field_slice_and_whole_list_assignment():
    a = Anim.parse(ANIM_WIRE)
    a.fns[0:2] = [0x08000000, 0x08000004]
    assert list(a.fns) == [0x08000000, 0x08000004]
    assert a.pack()[:8] == b"\x01\x00\x00\x08\x05\x00\x00\x08"
    a.fns = [0x0803EBA8, 0x0803EBA8]  # descriptor path, not the list's
    assert a.pack()[:4] == b"\xa9\xeb\x03\x08"
    with pytest.raises(ValueError, match="length is invariant"):
        a.fns[0:1] = [1, 2]


def test_adapted_array_field_constructor_takes_user_values():
    a = Anim(fns=[0x0803EBA8, 0x0803EC34], mults=[1.5, 1.0])
    assert a.pack() == ANIM_WIRE
    assert a == Anim.parse(ANIM_WIRE)  # equality is on the wire tuple
    assert "fns=[134474664, 134474804]" in repr(a)  # repr is user plane


def test_adapted_array_field_canonicalizes_noncanonical_wire():
    """The accepted consequence of a USER-plane element list: every element
    round-trips store(load(v)), so wire the adapter cannot represent is
    normalized on repack. Documented in Array's docstring."""
    noncanonical = bytes.fromhex("a8eb0308" "34ec0308" "1800" "1000")
    a = Anim.parse(noncanonical)
    assert list(a.fns) == [0x0803EBA8, 0x0803EC34]  # same user values
    assert a.pack() != noncanonical  # ... but NOT byte-identical
    assert a.pack() == ANIM_WIRE  # canonicalized: THUMB bit set

    # A scalar adapted field keeps slot=wire and exact identity:
    class Scalar(Struct, endian="little"):
        fn: Annotated[int, ThumbPtr]

    assert Scalar.parse(b"\xa8\xeb\x03\x08").pack() == b"\xa8\xeb\x03\x08"
    # ... and reading the same table unadapted preserves the bytes too
    plain = Array.of(UInt32, 2, endian="little")
    assert plain.pack(plain.parse(noncanonical[:8])) == noncanonical[:8]


def test_adapted_array_field_narrows_through_the_wire():
    class Biased(Struct, endian="little"):
        ids: List[int] = array(biased(1) @ UInt8, 2)

    b = Biased(ids=[0, 254])
    assert b.to_tuple() == (1, 255)
    b.ids[0] = 255  # stores 256 -> narrows to 0 -> loads back as -1
    assert b.ids[0] == -1
    assert b.pack() == b"\x00\xff"


def test_adapted_array_field_tuple_iso_and_iter_records():
    a = Anim.parse(ANIM_WIRE)
    assert Anim.from_tuple(a.to_tuple()) == a
    assert list(Anim.iter_records(ANIM_WIRE * 3)) == [a, a, a]


def test_adapted_array_field_element_annotation_is_checked():
    with pytest.raises(PlanCompileError, match=r"list\[float\]"):

        class Bad(Struct, endian="little"):
            mults: List[int] = array(Mult, 2)  # Mult reads as float

    class Good(Struct, endian="little"):
        mults: List[float] = array(Mult, 2)

    assert Good.num_bytes == 4


def test_adapted_array_field_copies_and_pickles():
    a = Anim.parse(ANIM_WIRE)
    for clone in (copy.deepcopy(a), pickle.loads(pickle.dumps(a))):
        assert clone == a and clone.pack() == ANIM_WIRE
        clone.fns[0] = 0x08000000
        assert a.fns[0] == 0x0803EBA8  # independent


def test_adapted_array_field_default_is_user_plane():
    class Defaulted(Struct, endian="little"):
        fns: List[int] = array(ThumbPtr, 2, default=[0x0803EBA8, 0x0803EC34])

    assert Defaulted().pack() == ANIM_WIRE[:8]
    assert Defaulted().fns is not Defaulted().fns  # no shared mutable


def test_fields_of_reports_an_adapted_arrays_element_adapter():
    """The engine keeps an array field's adapter on the Array (its codegen
    converts at the tuple boundary), but introspection must still see that
    the field IS adapted -- rom.Space.deref and coverage() read the schema
    through _bm_adapters."""
    fns, mults = fields_of(Anim)
    assert fns.adapter is ThumbPtr.adapter
    assert mults.adapter is Mult.adapter
    assert set(Anim._bm_adapters) == {"fns", "mults"}

    # a scalar adapted field and an unadapted one still report as before
    class Mixed(Struct, endian="little"):
        plain: List[int] = array(UInt8, 2)
        scalar: Annotated[int, ThumbPtr]

    by_name = {f.name: f.adapter for f in fields_of(Mixed)}
    assert by_name["plain"] is None
    assert by_name["scalar"] is THUMB_PTR


# ------------------------------- attributed load failures (adapted-3)
class Terrain(enum.Enum):
    """A small enum over data that is only partly documented -- the shape
    real ROM tables have, and the reason a load can fail at all."""

    FLOOR = 0
    WALL = 1


class Tile(Struct, endian="little"):
    kind: Terrain = field(UInt8, adapt=enum_(Terrain))
    height: int = field(UInt8)


class TileRow(Struct, endian="little"):
    kinds: List[Terrain] = array(enum_(Terrain) @ UInt8, 2)


def test_scalar_load_failure_names_the_record_and_field():
    t = Tile.parse(b"\x63\x05")  # 0x63 is not a Terrain member
    with pytest.raises(ValueError, match=r"^Tile\.kind: 99 is not a valid"):
        t.kind
    try:
        t.kind
    except ValueError as exc:
        assert isinstance(exc.__cause__, ValueError)  # original chained
        assert "Tile.kind" not in str(exc.__cause__)  # ... and left intact


def test_a_failing_load_leaves_the_wire_plane_usable():
    """parse fills slots wire-plane and never calls load, so an undocumented
    byte must not cost the record: the other fields, the wire tuple and a
    byte-exact repack all still work."""
    t = Tile.parse(b"\x63\x05")
    assert t.height == 5
    assert t.to_tuple() == (99, 5)
    assert t.pack() == b"\x63\x05"


def test_array_element_load_failure_names_the_record_and_field():
    """An adapted ARRAY field loads inside the generated from_tuple, so the
    failure lands in parse() itself -- where an unattributed message named
    neither the record nor the field."""
    with pytest.raises(ValueError, match=r"^TileRow\.kinds: 99 is not a valid"):
        TileRow.parse(b"\x00\x63")
    try:
        TileRow.parse(b"\x00\x63")
    except ValueError as exc:
        assert isinstance(exc.__cause__, ValueError)
    assert list(TileRow.parse(b"\x00\x01").kinds) == [
        Terrain.FLOOR,
        Terrain.WALL,
    ]  # documented data is unaffected


def test_store_side_attribution_is_unchanged():
    t = Tile.parse(b"\x00\x05")
    with pytest.raises(ValueError, match=r"^Tile\.kind: 99 is not a valid"):
        t.kind = 99


#: A load result with an identity to check. Module-level (not a lambda) as
#: the adapters docstring asks, so the schema stays picklable.
_SENTINEL: List[str] = ["untouched"]


def _sentinel_load(wire):
    return _SENTINEL


def _sentinel_store(user):
    return 0


def test_a_successful_load_hands_back_its_own_object():
    """The attribution is exception-path only. Asserting values would pass
    against the pre-adapted-3 code AND against a __get__ that copied or
    coerced what load returned; identity is what actually pins it."""

    class R(Struct, endian="little"):
        v: list = field(
            UInt8, adapt=Adapter(_sentinel_load, _sentinel_store, list, "sentinel")
        )

    r = R.parse(b"\x00")
    assert r.v is _SENTINEL  # not a copy, not wrapped
    assert r.pack() == b"\x00"  # and the wire plane is untouched


def test_repr_shows_the_healthy_fields_and_marks_the_unreadable_one():
    """A repr must never raise: one undocumented byte would otherwise take
    out print(record) for the whole table."""
    t = Tile.parse(b"\x63\x05")
    text = repr(t)
    assert text == "Tile(kind=<unreadable: 99 is not a valid Terrain>, height=5)"
    # the record-and-field prefix adapted-3 adds is noise beside the name
    assert "Tile.kind:" not in text


def test_repr_of_a_readable_record_is_unchanged():
    assert repr(Tile.parse(b"\x01\x05")) == ("Tile(kind=<Terrain.WALL: 1>, height=5)")


def test_only_a_scalar_field_can_hold_an_unreadable_value():
    """Where the load runs decides where it can fail, and the two field
    kinds differ: a scalar adapted field's slot is WIRE, so the load is
    deferred to the read and the record exists either way (repr degrades).
    An adapted array's slot is USER-plane, so its loads run eagerly in
    from_tuple -- an undocumented element means the record is never built,
    and there is no repr to degrade."""
    with pytest.raises(ValueError, match=r"^TileRow\.kinds:"):
        TileRow.from_tuple((0, 99))  # eager: no TileRow to repr
    assert repr(Tile.parse(b"\x63\x05")).startswith("Tile(kind=<unreadable:")


# ------------------- attribution must not destroy the exception (fix-1)
def test_a_multi_arg_exception_survives_attribution():
    """UnicodeEncodeError is a ValueError with FIVE constructor arguments, so
    rebuilding it from one string made the CONSTRUCTOR fail -- the caller got
    a TypeError about argument counts and lost the message, the type and the
    attribution together. Reachable with no adapter at all: a String field."""
    Name4 = UTF8String.of(nbytes=4, name="Name4Fix1")

    class T(Struct, endian="little"):
        n: str = field(Name4)

    t = T(n="ab")
    with pytest.raises(ValueError) as caught:
        t.n = "\ud800"  # a lone surrogate: not encodable as UTF-8
    assert not isinstance(caught.value, TypeError)
    assert str(caught.value).startswith("T.n: ")
    assert "surrogate" in str(caught.value)  # the real reason survives
    assert isinstance(caught.value.__cause__, UnicodeEncodeError)


class WireNotInTable(ValueError):
    """A user exception whose __init__ takes two arguments -- the shape a
    table-mapping adapter naturally raises."""

    def __init__(self, wire, table):
        super().__init__(f"wire {wire} is not in {table}")
        self.wire = wire


def _strict_table_load(wire):
    if wire != 1:
        raise WireNotInTable(wire, "terrain")
    return "floor"


def test_a_multi_arg_user_exception_keeps_its_message_and_attribution():
    strict = Adapter(_strict_table_load, str, str, "strict_table")

    class R(Struct, endian="little"):
        t: str = field(UInt8, adapt=strict)

    r = R.parse(b"\x63")
    with pytest.raises(ValueError) as caught:
        r.t
    assert str(caught.value) == "R.t: wire 99 is not in terrain"
    assert isinstance(caught.value.__cause__, WireNotInTable)
    # ... and the marker names the reason, not a constructor complaint
    assert repr(r) == "R(t=<unreadable: wire 99 is not in terrain>)"


def test_an_exact_builtin_exception_class_is_preserved():
    """A builtin raised with one argument rebuilds as itself: builtins keep
    no state beyond args, so the rebuild is faithful."""

    def load(wire):
        raise IndexError("beyond the table")

    class R(Struct, endian="little"):
        t: int = field(UInt8, adapt=Adapter(load, int, int, "idx"))

    with pytest.raises(IndexError, match=r"^R\.t: beyond the table"):
        R.parse(b"\x00").t


class _CapturingWire(ValueError):
    """A subclass whose __init__ captures its argument -- rebuilding it from
    the message string would silently replace .wire with that string."""

    def __init__(self, wire):
        super().__init__(f"bad wire {wire}")
        self.wire = wire


def _capturing_load(wire):
    raise _CapturingWire(wire)


def test_a_subclass_wraps_as_its_family_never_a_corrupt_rebuild():
    """A one-arg SUBCLASS could be rebuilt without the constructor raising --
    and its attributes would silently become the message string (.wire would
    hold "R.t: bad wire 99", so a handler's hex(e.wire) explodes). The
    wrapper is therefore the nearest builtin family, and the intact original
    -- correct attributes and all -- is the __cause__."""

    class R(Struct, endian="little"):
        t: int = field(UInt8, adapt=Adapter(_capturing_load, int, int, "cap"))

    with pytest.raises(ValueError, match=r"^R\.t: bad wire 99") as caught:
        R.parse(b"\x63").t
    assert type(caught.value) is ValueError  # the family, not the subclass
    assert isinstance(caught.value.__cause__, _CapturingWire)
    assert caught.value.__cause__.wire == 99  # the real attribute, intact


def test_a_keyerror_subclass_still_satisfies_except_keyerror():
    """The family rule exists for the caller's error handling: a table
    adapter's KeyError subclass (multi-arg, so unrebuildable) must not
    surface as ValueError past an `except KeyError`."""

    class TableMiss(KeyError):
        def __init__(self, wire, table):
            super().__init__(f"wire {wire} is not in {table}")

    def load(wire):
        raise TableMiss(wire, "terrain")

    class R(Struct, endian="little"):
        t: str = field(UInt8, adapt=Adapter(load, str, str, "tbl"))

    with pytest.raises(KeyError) as caught:
        R.parse(b"\x63").t
    assert type(caught.value) is KeyError
    assert "R.t: " in caught.value.args[0] and "99" in caught.value.args[0]
    assert isinstance(caught.value.__cause__, TableMiss)


def test_the_repr_marker_is_clean_for_a_keyerror():
    """KeyError's str() is repr(args[0]) -- quoted -- which used to defeat
    the prefix strip and leak "'Tile2.kind: 99'" into the marker. The marker
    reads args[0] directly."""
    table = Adapter(TERRAIN_TABLE.__getitem__, str, str, "table")

    class Tile2(Struct, endian="little"):
        kind: str = field(UInt8, adapt=table)

    assert repr(Tile2.parse(b"\x63")) == "Tile2(kind=<unreadable: 99>)"


def test_a_messageless_exception_marks_with_its_type_name():
    """ "R.v: " stripped to nothing must fall back to the type, not render a
    blank <unreadable: > marker."""

    def load(wire):
        raise ValueError()

    class R(Struct, endian="little"):
        v: int = field(UInt8, adapt=Adapter(load, int, int, "bare"))

    assert repr(R.parse(b"\x00")) == "R(v=<unreadable: ValueError>)"


TERRAIN_TABLE = {0: "floor", 1: "wall"}


def test_a_dict_table_adapters_keyerror_is_attributed():
    """Adapter(TABLE.__getitem__, ...) is the obvious way to decode a game's
    character table, and it raises KeyError -- not ValueError -- on exactly
    the undocumented byte this attribution exists for."""
    table = Adapter(TERRAIN_TABLE.__getitem__, str, str, "table")

    class Tile2(Struct, endian="little"):
        kind: str = field(UInt8, adapt=table)

    with pytest.raises(KeyError) as caught:
        Tile2.parse(b"\x63").kind
    assert "Tile2.kind" in str(caught.value) and "99" in str(caught.value)
    assert isinstance(caught.value.__cause__, KeyError)


def test_a_dict_table_adapters_keyerror_is_attributed_in_an_array_too():
    table = Adapter(TERRAIN_TABLE.__getitem__, str, str, "table")

    class Row2(Struct, endian="little"):
        kinds: List[str] = array(table @ UInt8, 2)

    with pytest.raises(KeyError) as caught:
        Row2.parse(b"\x00\x63")  # fails inside parse
    assert "Row2.kinds" in str(caught.value)
    assert list(Row2.parse(b"\x00\x01").kinds) == ["floor", "wall"]


def test_the_field_handle_repr_degrades_like_the_records():
    """repr-1 stated "a repr must never raise" absolutely, but the sizedview
    handle for the same field still read the user plane -- so the session that
    got a degraded record repr and reached for the handle to inspect the
    offending field was met with a raise after all."""
    t = Tile.parse(b"\x63\x05")
    handle = t.sizedview.kind
    assert repr(handle) == (
        "<bound UInt8 kind=<unreadable: 99 is not a valid Terrain> of Tile>"
    )
    # the WIRE plane still reads: that is how you inspect the actual byte
    assert handle.boxed().value == 99
    assert handle.bits.to01() == "01100011"
    assert repr(t.sizedview.height) == "<bound UInt8 height=5 of Tile>"


def test_the_sized_view_repr_degrades_through_the_record():
    t = Tile.parse(b"\x63\x05")
    assert repr(t.sizedview) == f"<sizedview of {t!r}>"
    assert "<unreadable: 99 is not a valid Terrain>" in repr(t.sizedview)


# ---------------- element-store attribution (fix-8; five ways total)
def test_every_way_to_trip_an_array_element_type_names_the_field():
    """Of the five ways a value crosses an element type (loads at parse,
    stores at pack, whole-list assignment/__init__, and the element store),
    the element store was named last -- and it is the one a user reaches
    for most."""
    row = TileRow.parse(b"\x00\x01")
    for do in (
        lambda: row.kinds.__setitem__(0, 99),  # element store
        lambda: row.kinds.__setitem__(slice(0, 2), [99, 0]),  # slice store
        lambda: setattr(row, "kinds", [99, 0]),  # whole-list assignment
        lambda: TileRow.parse(b"\x00\x63"),  # load, inside parse
    ):
        with pytest.raises(ValueError, match=r"^TileRow\.kinds: 99 is not") as c:
            do()
        assert isinstance(c.value.__cause__, ValueError)
    # ... and the record is unharmed by the refused stores
    assert list(row.kinds) == [Terrain.FLOOR, Terrain.WALL]


def test_element_store_attribution_covers_unadapted_arrays_too():
    class Plain(Struct, endian="little"):
        colors: List[int] = array(UInt16, 2)

    p = Plain(colors=[1, 2])
    with pytest.raises(TypeError, match=r"^Plain\.colors: "):
        p.colors[0] = "x"


def test_a_standalone_arrays_list_has_no_field_to_name():
    """An Array is standalone-capable, so its list is not always owned by a
    field; with no label the original error passes through untouched."""
    values = Array.of(UInt8, 2, "little").field_list([1, 2])
    with pytest.raises(TypeError) as caught:
        values[0] = "x"
    assert "." not in str(caught.value).split(":")[0]  # no "Record.field:"


# --------------------- array attribution, completed (fix-10)
_TBL = {0: "floor", 1: "wall"}
_REV = {"floor": 0, "wall": 1}
_TableAdapter = Adapter(_TBL.__getitem__, _REV.__getitem__, str, "tbl2")


class _TableRow(Struct, endian="little"):
    kinds: List[str] = array(_TableAdapter @ UInt8, 2)


def test_whole_list_assignment_and_init_attribute_store_failures():
    """The bulk spellings of the element store were the one adapter call
    site left on a (TypeError, ValueError) shortlist, so a table adapter's
    KeyError escaped bare with no __cause__."""
    row = _TableRow.parse(b"\x00\x01")
    for do in (
        lambda: setattr(row, "kinds", ["floor", "bogus"]),
        lambda: _TableRow(kinds=["bogus", "floor"]),
    ):
        with pytest.raises(KeyError) as caught:
            do()
        assert "_TableRow.kinds" in str(caught.value)
        assert isinstance(caught.value.__cause__, KeyError)
    assert list(row.kinds) == ["floor", "wall"]  # refused stores change nothing


class _PlainColors(Struct, endian="little"):
    """Module-level so the pickle round-trip below can find it."""

    colors: List[int] = array(UInt16, 2)


def test_copies_keep_the_element_store_attribution():
    """NarrowingList.__reduce__ dropped the label, so any copied record
    regressed to the anonymous error the attribution exists to prevent."""
    p = _PlainColors(colors=[1, 2])
    for clone in (copy.deepcopy(p), pickle.loads(pickle.dumps(p))):
        with pytest.raises(TypeError, match=r"^_PlainColors\.colors: "):
            clone.colors[0] = "x"


def test_length_violations_name_the_field_too():
    p = _PlainColors(colors=[1, 2])
    for do in (
        lambda: p.colors.append(3),
        lambda: p.colors.pop(),
        lambda: p.colors.__delitem__(0),
        lambda: p.colors.__setitem__(slice(0, 1), [1, 2]),
    ):
        with pytest.raises(ValueError, match=r"^_PlainColors\.colors: length is"):
            do()


def _boxing_load(wire):
    return [wire]  # a MUTABLE user value: the pack-direction hazard


def _boxing_store(user):
    if len(user) != 1:
        raise ValueError(f"cannot re-encode {user!r}: exactly one entry")
    return user[0]


def test_pack_of_a_drifted_element_names_the_record_and_field():
    """The pack-direction way to trip an element type: an adapted array's
    slot is user-plane, so pack() re-encodes through store -- and a mutable
    user value can have drifted into a state store refuses since it was
    stored."""
    boxing = Adapter(_boxing_load, _boxing_store, list, "boxing")

    class Rec(Struct, endian="little"):
        xs: List[list] = array(boxing @ UInt8, 2)

    rec = Rec.parse(b"\x01\x02")
    assert rec.pack() == b"\x01\x02"  # healthy round trip
    rec.xs[0].append(9)  # drift: mutate the user value in place
    with pytest.raises(ValueError, match=r"^Rec\.xs: cannot re-encode") as c:
        rec.pack()
    assert isinstance(c.value.__cause__, ValueError)
