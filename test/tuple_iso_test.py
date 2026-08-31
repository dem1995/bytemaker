"""The public tuple<->record isomorphism (pub-1).

``Plan.unpack_tuple``/``pack_tuple``/``iter_tuples`` were already public, but
the record half of the pair (``_bm_from_tuple``/``_bm_to_tuple``) was private
codegen, so callers who wanted the fast wire-plane lane had to either give up
records entirely or slice-and-``parse`` in a Python loop. These tests pin the
published names: ``Struct.from_tuple``, ``Struct.to_tuple``,
``Struct.iter_records``.
"""

import pytest

from bytemaker.adapters import THUMB_PTR, biased, fixed
from bytemaker.bittypes import Buffer, UInt8, UInt16, UInt32, UTF8String
from bytemaker.plans import PlanCompileError
from bytemaker.structs import Struct, array, field

Name4 = UTF8String.of(nbytes=4, name="Name4")
Buf2 = Buffer.of(nbytes=2, name="Buf2Iso")


class Inner(Struct, endian="little"):
    a: UInt8
    b: UInt16


class Rec(Struct, endian="little"):
    """One of every field flavor, so the tuple math is exercised end to end."""

    scalar: UInt16
    nested: Inner
    nums: list = array(UInt8, 3)
    kids: list = array(Inner, 2)
    text: Name4
    raw: Buf2
    fn: int = field(UInt32, adapt=THUMB_PTR)
    mult: float = field(UInt16, adapt=fixed(4))


def make_rec():
    return Rec(
        scalar=0x1234,
        nested=Inner(a=1, b=2),
        nums=[3, 4, 5],
        kids=[Inner(a=6, b=7), Inner(a=8, b=9)],
        text="hi",
        raw=b"\xaa\xbb",
        fn=0x0803EBA8,
        mult=1.5,
    )


# ------------------------------------------------------------------ round trip
def test_from_tuple_inverts_to_tuple():
    rec = make_rec()
    assert Rec.from_tuple(rec.to_tuple()) == rec


def test_to_tuple_is_the_plans_tuple():
    rec = make_rec()
    assert rec.to_tuple() == Rec.plan.unpack_tuple(rec.pack())
    assert Rec.plan.pack_tuple(rec.to_tuple()) == rec.pack()


def test_tuple_is_flat_and_plan_shaped():
    rec = make_rec()
    values = rec.to_tuple()
    assert len(values) == len(Rec.plan.fields)
    # flat: no nested tuples/lists leak through, one entry per plan field
    assert all(not isinstance(v, (tuple, list)) for v in values)


def test_from_tuple_matches_parse():
    rec = make_rec()
    assert Rec.from_tuple(Rec.plan.unpack_tuple(rec.pack())) == Rec.parse(rec.pack())


# ------------------------------------------------------------- the wire plane
def test_tuple_is_wire_plane_for_adapted_fields():
    rec = make_rec()
    values = rec.to_tuple()
    fn_index = [f.name for f in Rec.plan.fields].index("fn")
    mult_index = [f.name for f in Rec.plan.fields].index("mult")
    assert values[fn_index] == 0x0803EBA9  # THUMB bit set on the wire
    assert values[mult_index] == 0x18  # fixed(4): 1.5 * 16
    # ...while the attributes stay in the user plane
    assert rec.fn == 0x0803EBA8
    assert rec.mult == 1.5


def test_from_tuple_takes_wire_values_for_adapted_fields():
    rec = make_rec()
    values = list(rec.to_tuple())
    fn_index = [f.name for f in Rec.plan.fields].index("fn")
    values[fn_index] = 0x0803EC35  # a wire value, THUMB bit set
    back = Rec.from_tuple(values)
    assert back.fn == 0x0803EC34  # read through the adapter
    assert back.to_tuple()[fn_index] == 0x0803EC35  # and back out unchanged


def test_from_tuple_accepts_a_list_not_only_a_tuple():
    rec = make_rec()
    assert Rec.from_tuple(list(rec.to_tuple())) == rec


# --------------------------------------------------------------- length guard
def test_from_tuple_rejects_wrong_length():
    rec = make_rec()
    values = rec.to_tuple()
    want = len(Rec.plan.fields)
    with pytest.raises(ValueError, match=f"expected {want} values, got {want - 1}"):
        Rec.from_tuple(values[:-1])
    with pytest.raises(ValueError, match=f"expected {want} values, got {want + 1}"):
        Rec.from_tuple(values + (0,))


def test_from_tuple_rejects_empty():
    with pytest.raises(ValueError, match="from_tuple"):
        Rec.from_tuple(())


# -------------------------------------------------------------- iter_records
def test_iter_records_matches_a_slice_parse_loop():
    recs = [make_rec() for _ in range(4)]
    for i, r in enumerate(recs):
        r.scalar = i
    blob = b"".join(r.pack() for r in recs)
    n = Rec.num_bytes
    expected = [Rec.parse(blob[i * n : (i + 1) * n]) for i in range(4)]
    assert list(Rec.iter_records(blob)) == expected


def test_iter_records_honors_offset_and_count():
    recs = [make_rec() for _ in range(4)]
    for i, r in enumerate(recs):
        r.scalar = i
    blob = b"\xff" * 7 + b"".join(r.pack() for r in recs)
    got = list(Rec.iter_records(blob, 7, 2))
    assert [r.scalar for r in got] == [0, 1]


def test_iter_records_count_none_reads_whole_records_only():
    rec = make_rec()
    n = Rec.num_bytes
    blob = rec.pack() * 3 + b"\x00" * (n - 1)  # a trailing partial record
    assert len(list(Rec.iter_records(blob))) == 3


def test_iter_records_is_lazy():
    rec = make_rec()
    blob = rec.pack() * 3
    it = Rec.iter_records(blob)
    assert not isinstance(it, list)
    assert next(it).scalar == rec.scalar  # decoding happens on demand
    assert len(list(it)) == 2


def test_iter_records_inherits_the_iter_tuples_guards():
    blob = make_rec().pack()
    with pytest.raises(ValueError, match="outside the buffer"):
        list(Rec.iter_records(blob, -1))
    with pytest.raises(ValueError, match="outside the buffer"):
        list(Rec.iter_records(blob, len(blob) + 1))
    with pytest.raises(ValueError, match="only 1"):
        list(Rec.iter_records(blob, 0, 2))


def test_iter_records_over_a_memoryview_does_not_copy():
    rec = make_rec()
    buf = bytearray(rec.pack() * 2)
    got = list(Rec.iter_records(memoryview(buf)))
    assert len(got) == 2 and got[0] == rec


def test_iter_records_yields_detached_records():
    rec = make_rec()
    buf = bytearray(rec.pack() * 2)
    got = list(Rec.iter_records(buf))
    got[0].scalar = 0xBEEF & 0xFFFF
    assert Rec.parse(bytes(buf[: Rec.num_bytes])).scalar == rec.scalar


# ------------------------------------------------------- shiftmask tier too
class Packed(Struct, endian="little", bit_order="lsb"):
    """Unaligned widths force the shiftmask tier; the iso must hold there."""

    lo: UInt8.specialize(3, name_="U3")  # type: ignore[misc]  # noqa: F821
    mid: UInt8.specialize(5, name_="U5")  # type: ignore[misc]  # noqa: F821
    hi: UInt16.specialize(12, name_="U12")  # type: ignore[misc]  # noqa: F821
    pad: UInt8.specialize(4, name_="U4")  # type: ignore[misc]  # noqa: F821


def test_iso_holds_on_the_shiftmask_tier():
    assert Packed.plan.tier == "shiftmask"
    p = Packed(lo=5, mid=17, hi=0xABC, pad=3)
    assert Packed.from_tuple(p.to_tuple()) == p
    blob = p.pack() * 3
    assert [r.hi for r in Packed.iter_records(blob)] == [0xABC] * 3


# ------------------------------------------------------------- name reserved
@pytest.mark.parametrize("name", ["from_tuple", "to_tuple", "iter_records"])
def test_published_names_are_reserved_field_names(name):
    with pytest.raises(PlanCompileError, match="reserved"):
        type(
            "Clash",
            (Struct,),
            {"__annotations__": {name: UInt8}},
        )


# ------------------------------------------------------------ adapted arrays
class Simple(Struct, endian="little"):
    ids: list = array(UInt8, 3)
    tag: int = field(UInt8, adapt=biased(1))


def test_iso_with_array_and_adapted_scalar():
    s = Simple(ids=[1, 2, 3], tag=7)
    assert s.to_tuple() == (1, 2, 3, 8)  # biased(+1) on the wire
    back = Simple.from_tuple((1, 2, 3, 8))
    assert back.tag == 7 and list(back.ids) == [1, 2, 3]
    assert back == s
