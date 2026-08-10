"""bytemaker.rom typed pointers and coverage (rom-3)."""

import copy
import pickle
from typing import Annotated, List

import pytest

from bytemaker.adapters import THUMB_PTR, Adapted
from bytemaker.bittypes import UInt8, UInt16, UInt32
from bytemaker.introspect import fields_of, sizeof
from bytemaker.rom import (
    CoverageReport,
    Entry,
    Ptr,
    PtrAdapter,
    Space,
    count,
    unknown,
    until,
)
from bytemaker.structs import Array, Struct, array, field

BASE = 0x08000000


class RoomHeader(Struct, endian="little"):
    width: int = field(UInt8)
    height: int = field(UInt8)
    flags: int = field(UInt16)


class WarpPoint(Struct, endian="little"):
    sector: int = field(UInt8)
    room: int = field(UInt8)
    pad: int = field(UInt16)
    room_ptr: Annotated[int, Ptr(RoomHeader)]


class AnimSet(Struct, endian="little"):
    """A record with a THUMB'd function-pointer ARRAY field."""

    id_: int = field(UInt16)
    pad: int = field(UInt16)
    fns: List[int] = array(Ptr(None, adapt=THUMB_PTR), 2)


ROOM_A = 0x08000100
ROOM_B = 0x08000104
WARPS = 0x08000010
PTR_TABLE = 0x08000040
ANIMS = 0x08000060


def make_buf():
    buf = bytearray(0x400)
    RoomHeader(width=16, height=12, flags=0xABCD).pack_into(buf, ROOM_A - BASE)
    RoomHeader(width=8, height=8, flags=0x1234).pack_into(buf, ROOM_B - BASE)
    # two warps, the second pointing at ROOM_B
    WarpPoint(sector=1, room=2, pad=0, room_ptr=ROOM_A).pack_into(
        buf, WARPS - BASE
    )
    WarpPoint(sector=3, room=4, pad=0, room_ptr=ROOM_B).pack_into(
        buf, WARPS - BASE + WarpPoint.num_bytes
    )
    # a bare pointer table: room A, room B, an unclaimed address, a wild one,
    # then the null terminator
    at = PTR_TABLE - BASE
    for i, value in enumerate((ROOM_A, ROOM_B, 0x08000300, 0x02010000, 0)):
        buf[at + i * 4 : at + (i + 1) * 4] = value.to_bytes(4, "little")
    # one AnimSet whose two function pointers carry the THUMB bit
    AnimSet(id_=7, pad=0, fns=[0x08000200, 0x08000204]).pack_into(buf, ANIMS - BASE)
    return buf


BUF = make_buf()


def space(buf=None, **kw):
    kw.setdefault("base", BASE)
    kw.setdefault("endian", "little")
    kw.setdefault("name", "ROM")
    return Space(BUF if buf is None else buf, **kw)


# ------------------------------------------------------------- the Ptr codec
def test_ptr_is_an_adapted_scalar_codec():
    p = Ptr(RoomHeader)
    assert isinstance(p, Adapted) and isinstance(p.adapter, PtrAdapter)
    assert p.base is UInt32 and p.num_bits == 32 and sizeof(p) == 4
    assert p.py_type is int and p.target is RoomHeader
    assert repr(p) == "Ptr(RoomHeader->UInt32)"
    assert repr(Ptr(None)) == "Ptr(?->UInt32)"
    assert "ptr(RoomHeader)" in p.adapter.name


def test_ptr_decodes_to_a_plain_int():
    """Grade 1: no proxies, no laziness. Nothing is followed until asked."""
    value = space().read(WARPS + 4, Ptr(RoomHeader))
    assert type(value) is int and value == ROOM_A


def test_ptr_composes_a_value_convention():
    thumb = Ptr(None, adapt=THUMB_PTR)
    s = space()
    raw = s.read(ANIMS + 4, UInt32)
    assert raw & 1  # the THUMB bit is set on the wire
    assert s.read(ANIMS + 4, thumb) == raw - 1  # ... and masked off on read
    with pytest.raises(TypeError, match="must be an Adapter"):
        Ptr(None, adapt="thumb")


def test_ptr_accepts_a_narrower_base():
    p = Ptr(RoomHeader, base=UInt16)
    assert p.base is UInt16 and sizeof(p) == 2


def test_ptr_works_as_an_array_element_and_a_field():
    arr = Array.of(Ptr(RoomHeader), 2, endian="little")
    assert arr.parse(BUF[PTR_TABLE - BASE : PTR_TABLE - BASE + 8]) == [
        ROOM_A,
        ROOM_B,
    ]
    (info,) = [f for f in fields_of(WarpPoint) if f.name == "room_ptr"]
    assert isinstance(info.adapter, PtrAdapter)
    assert info.adapter.target is RoomHeader
    assert info.type is UInt32  # the plan sees the base, as for any Adapted


def test_ptr_survives_pickle_and_deepcopy():
    p = Ptr(RoomHeader, adapt=THUMB_PTR, name="fn")
    for clone in (pickle.loads(pickle.dumps(p)), copy.deepcopy(p)):
        assert isinstance(clone, Ptr) and clone.target is RoomHeader
        assert clone.adapter.name == "fn" and clone.num_bits == 32
    arr = Array.of(Ptr(RoomHeader), 2, endian="little")
    clone = pickle.loads(pickle.dumps(arr))
    assert isinstance(clone._adapter, PtrAdapter)
    assert clone.parse(b"\x00\x01\x00\x08" * 2) == [0x08000100] * 2


# ------------------------------------------------------------------- deref
def test_deref_follows_a_record_field():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    assert warp.room_ptr == ROOM_A
    room = s.deref(warp, "room_ptr")
    assert isinstance(room, RoomHeader)
    assert (room.width, room.height, room.flags) == (16, 12, 0xABCD)


def test_deref_takes_an_extent_like_read():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    both = s.deref(warp, "room_ptr", 2)
    assert [r.width for r in both] == [16, 8]


def test_deref_over_an_adapted_pointer_array_field():
    s = space()
    anim = s.read(ANIMS, AnimSet)
    assert list(anim.fns) == [0x08000200, 0x08000204]  # THUMB bit masked off
    with pytest.raises(TypeError, match="has no target codec"):
        s.deref(anim, "fns")  # Ptr(None): documented, not followable


def test_deref_over_a_pointer_array_field_with_a_target():
    class Table(Struct, endian="little"):
        rooms: List[int] = array(Ptr(RoomHeader), 2)

    s = space()
    t = s.read(PTR_TABLE, Table)
    rooms = s.deref(t, "rooms")
    assert [r.width for r in rooms] == [16, 8]


def test_deref_refuses_a_non_pointer_field_and_lists_the_real_ones():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    with pytest.raises(TypeError, match="not a Ptr field"):
        s.deref(warp, "sector")
    with pytest.raises(TypeError, match="pointer fields here: room_ptr"):
        s.deref(warp, "sector")


def test_deref_value_follows_one_address():
    s = space()
    ptr = Ptr(RoomHeader)
    values = s.read(PTR_TABLE, ptr, 2)
    assert [s.deref_value(v, ptr).width for v in values] == [16, 8]
    # the adapter alone works too (that is what a record field carries)
    assert s.deref_value(values[0], ptr.adapter).width == 16
    with pytest.raises(TypeError, match="not a Ptr"):
        s.deref_value(ROOM_A, UInt32)
    with pytest.raises(TypeError, match="has no target codec"):
        s.deref_value(ROOM_A, Ptr(None))


def test_deref_reports_a_wild_address_as_an_address_error():
    from bytemaker.rom import AddressError

    s = space()
    with pytest.raises(AddressError, match="outside the space"):
        s.deref_value(0x02010000, Ptr(RoomHeader))


# ---------------------------------------------------------------- coverage
def rom_map():
    return [
        Entry(ROOM_A, RoomHeader, count(2), name="rooms"),
        Entry(WARPS, WarpPoint, count(2), name="warps"),
        Entry(PTR_TABLE, Ptr(RoomHeader), until(0), name="room_ptrs"),
        Entry(ANIMS, AnimSet, count(1), name="anims"),
    ]


def test_coverage_resolves_every_extent_kind():
    report = space().coverage(rom_map())
    assert isinstance(report, CoverageReport)
    by_name = {r.name: r for r in report.regions}
    assert by_name["rooms"].size == 2 * RoomHeader.num_bytes
    assert by_name["warps"].size == 2 * WarpPoint.num_bytes
    # a scanned table's bytes include its terminator: 4 entries + 1
    assert by_name["room_ptrs"].size == 5 * 4
    assert by_name["anims"].size == AnimSet.num_bytes
    assert not report.unresolved


def test_coverage_totals_and_percent():
    report = space().coverage(rom_map())
    expected = 2 * RoomHeader.num_bytes + 2 * WarpPoint.num_bytes + 20
    expected += AnimSet.num_bytes
    assert report.claimed_bytes == expected
    assert report.percent == pytest.approx(100.0 * expected / len(BUF))
    assert f"{report.claimed_bytes}/{len(BUF)}" in report.render()


def test_coverage_counts_overlapping_bytes_once():
    dup = rom_map() + [Entry(ROOM_A, RoomHeader, count(2), name="rooms_again")]
    report = space().coverage(dup)
    plain = space().coverage(rom_map())
    assert report.claimed_bytes == plain.claimed_bytes  # not double counted
    assert len(report.overlaps) == 1
    (o,) = report.overlaps
    assert {o.a, o.b} == {"rooms", "rooms_again"}
    assert o.start == ROOM_A and o.size == 2 * RoomHeader.num_bytes
    assert "share 8 bytes" in report.render()


def test_coverage_reports_a_partial_overlap():
    shifted = [
        Entry(ROOM_A, RoomHeader, count(2), name="rooms"),
        Entry(ROOM_A + 2, RoomHeader, count(2), name="misaligned"),
    ]
    (o,) = space().coverage(shifted, audit_pointers=False).overlaps
    assert o.start == ROOM_A + 2 and o.size == 6


def test_coverage_reports_unresolved_extents_with_the_reason():
    entries = [
        Entry(ROOM_A, RoomHeader, unknown("length not mapped"), name="mystery"),
        Entry(0x080003F0, RoomHeader, count(8), name="too_long"),
        Entry(0x08000300, Ptr(None), until(0xDEAD), name="runs_off_the_end"),
        Entry(ROOM_A, Ptr(None), until(0xDEAD, max_count=4), name="hits_the_cap"),
    ]
    report = space().coverage(entries)
    reasons = {r.name: r.error for r in report.unresolved}
    assert "length not mapped" in reasons["mystery"]
    assert "outside the space" in reasons["too_long"]
    assert "reached the end of the space" in reasons["runs_off_the_end"]
    assert "no sentinel" in reasons["hits_the_cap"]
    text = report.render()
    assert "unresolved (4)" in text and "length not mapped" in text


def test_coverage_audits_pointers_from_a_bare_table():
    report = space().coverage(rom_map())
    table = [p for p in report.pointers if p.source == "room_ptrs"]
    assert [p.verdict for p in table] == [
        "claimed",
        "claimed",
        "unclaimed",
        "outside",
    ]
    assert [p.index for p in table] == [0, 1, 2, 3]
    assert {p.claimed_by for p in table[:2]} == {"rooms"}
    assert [p.value for p in report.dangling] == [0x02010000]
    assert table[0].field is None


def test_coverage_audits_pointers_from_record_fields():
    report = space().coverage(rom_map())
    warps = [p for p in report.pointers if p.source == "warps"]
    assert [(p.field, p.verdict, p.claimed_by) for p in warps] == [
        ("room_ptr", "claimed", "rooms"),
        ("room_ptr", "claimed", "rooms"),
    ]
    assert "warps.room_ptr[0]" in warps[0].describe()


def test_coverage_audits_pointers_inside_an_array_field():
    report = space().coverage(rom_map())
    anims = [p for p in report.pointers if p.source == "anims"]
    assert len(anims) == 2  # one record x two array elements
    assert [p.value for p in anims] == [0x08000200, 0x08000204]
    assert [p.index for p in anims] == [(0, 0), (0, 1)]
    assert all(p.verdict == "unclaimed" for p in anims)


def test_coverage_classifies_a_null_pointer_separately():
    buf = make_buf()
    buf[WARPS - BASE + 4 : WARPS - BASE + 8] = b"\x00\x00\x00\x00"
    report = space(buf).coverage(rom_map())
    warps = [p for p in report.pointers if p.source == "warps"]
    assert warps[0].verdict == "null" and not warps[0].is_dangling


def test_coverage_can_skip_the_pointer_audit():
    report = space().coverage(rom_map(), audit_pointers=False)
    assert report.pointers == ()
    assert "pointers" not in report.render()


def test_coverage_binds_unbound_entries():
    report = space().coverage(rom_map())  # rom_map() entries carry no space
    assert report.regions and all(r.entry.space is not None for r in report.regions)
    assert report.space_name == "ROM" and report.space_size == len(BUF)


def test_render_truncates_the_pointer_listing_and_says_so():
    report = space().coverage(rom_map())
    noteworthy = [p for p in report.pointers if p.verdict != "claimed"]
    assert len(noteworthy) > 1  # otherwise the truncation is untested
    text = report.render(max_pointers=1)
    assert f"and {len(noteworthy) - 1} more non-claimed pointers" in text
    assert "raise max_pointers" in text
    assert "more non-claimed" not in report.render()


def test_coverage_of_an_empty_map():
    report = space().coverage([])
    assert report.claimed_bytes == 0 and report.percent == 0.0
    assert "0/1024 bytes (0.00%) in 0 entries" in report.render()


# ------------------------------------------------- deferred targets (rom-5)
#: Declared BEFORE the records they name, which is the whole point.
NextNode = Annotated[int, Ptr("Node")]
ExitsPtr = Annotated[int, Ptr("ExitList")]


class Node(Struct, endian="little"):
    """Self-referential: a linked-list node pointing at its own type."""

    value: int = field(UInt16)
    _pad: int = field(UInt16)
    next: NextNode


class Room(Struct, endian="little"):
    w: int = field(UInt8)
    h: int = field(UInt8)
    _pad: int = field(UInt16)
    exits: ExitsPtr


class ExitList(Struct, endian="little"):  # defined AFTER Room references it
    count_: int = field(UInt16)
    first: int = field(UInt16)


def linked_space():
    """Three 8-byte Nodes packed contiguously at 0x10, chained 7 -> 9 -> 11."""
    buf = bytearray(0x100)
    assert Node.num_bytes == 8
    Node(value=7, _pad=0, next=BASE + 0x18).pack_into(buf, 0x10)
    Node(value=9, _pad=0, next=BASE + 0x20).pack_into(buf, 0x18)
    Node(value=11, _pad=0, next=0).pack_into(buf, 0x20)
    Room(w=16, h=12, _pad=0, exits=BASE + 0x40).pack_into(buf, 0x00)
    ExitList(count_=3, first=5).pack_into(buf, 0x40)
    return Space(buf, base=BASE, endian="little", name="L")


def test_a_bare_forward_name_cannot_work():
    """Ptr(Node) inside Node's own body is evaluated before the class exists,
    even under deferred annotations -- the metaclass resolves hints during
    class creation. This is why the string form exists."""
    with pytest.raises(NameError):

        class Broken(Struct, endian="little"):
            v: int = field(UInt16)
            _pad: int = field(UInt16)
            nxt: Annotated[int, Ptr(Broken)]  # noqa: F821


def test_deferred_target_resolves_on_first_use_and_memoizes():
    p = Ptr("Node")
    assert p.deferred and p.adapter.deferred
    assert p.target is Node
    assert not p.deferred  # memoized
    assert p.target is Node  # stable


def test_repr_does_not_force_resolution():
    p = Ptr("NeverDefinedAnywhere")
    assert repr(p) == "Ptr(NeverDefinedAnywhere->UInt32)"
    assert p.deferred  # repr left it deferred
    assert "ptr(NeverDefinedAnywhere)" in p.adapter.name


def test_self_referential_pointer_walks_a_linked_list():
    s = linked_space()
    n = s.read(BASE + 0x10, Node)
    chain = [n.value]
    while n.next:
        n = s.deref(n, "next")
        chain.append(n.value)
    assert chain == [7, 9, 11]


def test_forward_reference_to_a_later_class():
    s = linked_space()
    r = s.read(BASE, Room)
    exits = s.deref(r, "exits")
    assert isinstance(exits, ExitList)
    assert (exits.count_, exits.first) == (3, 5)


def test_callable_target_is_the_no_magic_escape_hatch():
    p = Ptr(lambda: Node)
    assert p.deferred and p.target is Node
    s = linked_space()
    assert s.deref_value(BASE + 0x10, p).value == 7


def test_unresolvable_deferred_target_says_where_it_looked():
    p = Ptr("NoSuchRecord")
    with pytest.raises(TypeError, match="no such name in module"):
        p.target
    with pytest.raises(TypeError, match="rom_ptr_test"):
        p.target


def test_deferred_target_resolving_to_a_non_codec_is_refused():
    p = Ptr("BASE")  # a module-level int, not a codec
    with pytest.raises(TypeError, match="is not a codec"):
        p.target


def test_explicit_module_overrides_the_captured_one():
    p = Ptr("UInt16", module="bytemaker.bittypes")
    assert p.target is UInt16 and not p.deferred


def test_bad_target_types_are_refused_at_construction():
    with pytest.raises(TypeError, match="Ptr target must be a codec"):
        Ptr(3)
    with pytest.raises(TypeError, match="Ptr target must be a codec"):
        Ptr(b"Node")


def test_deferred_target_survives_pickle_while_still_deferred():
    p = Ptr("Node")
    clone = pickle.loads(pickle.dumps(p))
    assert isinstance(clone, Ptr) and clone.deferred
    assert clone.target is Node  # resolves in the unpickling process too


def test_resolved_target_pickles_by_reference():
    p = Ptr("Node")
    assert p.target is Node  # force resolution first
    clone = pickle.loads(pickle.dumps(p))
    assert clone.target is Node and not clone.deferred


def test_deferred_pointers_are_audited_without_being_resolved():
    """coverage() classifies addresses; it must not need the pointee's codec
    (and must not blow up on a target that cannot resolve)."""
    s = linked_space()
    entries = [
        Entry(BASE + 0x10, Node, count(3), name="nodes"),
        Entry(BASE, Room, count(1), name="room"),
        Entry(BASE + 0x40, ExitList, count(1), name="exits"),
    ]
    report = s.coverage(entries)
    by_field = {(p.source, p.field): p for p in report.pointers}
    assert by_field[("room", "exits")].verdict == "claimed"
    assert by_field[("room", "exits")].claimed_by == "exits"
    nodes = [p for p in report.pointers if p.source == "nodes"]
    assert [p.verdict for p in nodes] == ["claimed", "claimed", "null"]
