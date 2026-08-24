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
    PtrValue,
    Space,
    count,
    unknown,
    until,
)
from bytemaker.structs import Array, Struct, StructMeta, array, field

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
    assert p.py_type is PtrValue and p.target is RoomHeader
    assert repr(p) == "Ptr(RoomHeader->UInt32)"
    assert repr(Ptr(None)) == "Ptr(?->UInt32)"
    assert "ptr(RoomHeader)" in p.adapter.name


def test_ptr_decodes_to_an_int_that_knows_its_pointer():
    """Still no proxies and no laziness — nothing is followed until asked —
    but the decoded value is a PtrValue: an int subclass carrying the
    adapter, indistinguishable from the address in every int way."""
    value = space().read(WARPS + 4, Ptr(RoomHeader))
    assert isinstance(value, int) and type(value) is PtrValue
    assert value == ROOM_A and hash(value) == hash(ROOM_A)
    assert {value: "x"}[ROOM_A] == "x"  # dict-key interchangeable
    assert f"{value:#010x}" == "0x08000100"
    assert repr(value) == hex(ROOM_A)  # pointers repr in hex
    assert value.target is RoomHeader


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
    assert report.pointers == () and not report.pointers_audited
    # ...and the report says so: an empty pointer list otherwise reads as
    # "every pointer checked out", which is a different claim.
    assert "pointers: not audited" in report.render()


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
    with pytest.raises(TypeError, match="not in module"):
        p.target
    with pytest.raises(TypeError, match="rom_ptr_test"):
        p.target
    # ... and says the registry was searched too, so the reader knows both
    # lookups happened before giving up
    with pytest.raises(TypeError, match="no concrete Struct class"):
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


def test_deferred_pointers_are_audited_and_verified_when_resolvable():
    """coverage() classifies addresses with no pointee codec needed — and
    when a deferred target DOES resolve (these do: "Node", "ExitList"), the
    claimed hits are additionally type/alignment-verified, which is why they
    still read "claimed" and not a defect verdict."""
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


# ---------------------------------------------- registry fallback (rom-6)
class XModuleRoom(Struct, endian="little"):
    """Deliberately unique name: registry tests must not collide with any
    other Struct in the suite (the registry is process-global)."""

    w: int = field(UInt8)
    h: int = field(UInt8)
    _pad: int = field(UInt16)


def test_registry_resolves_a_name_the_ptr_module_lacks():
    """The cross-module case: the Ptr is declared in a module that never
    imported the record. Module lookup misses; the registry, holding every
    concrete Struct by name, resolves it — because exactly one exists."""
    p = Ptr("XModuleRoom", module="bytemaker.rom")  # name not in rom's globals
    assert p.deferred
    assert p.target is XModuleRoom


def test_module_binding_wins_over_the_registry():
    """A name bound in the Ptr's module resolves there, registry unconsulted:
    the alias author keeps deterministic control."""
    p = Ptr("RoomHeader")  # this module defines RoomHeader
    assert p.target is RoomHeader


def test_ambiguous_registry_names_refuse_with_the_module_list():
    # Two live same-named classes, neither bound at module level (so the
    # current-binding filter cannot break the tie).
    dup_a = StructMeta("XDupRec", (Struct,), {"__annotations__": {"a": UInt8}})
    dup_b = StructMeta("XDupRec", (Struct,), {"__annotations__": {"a": UInt16}})
    p = Ptr("XDupRec", module="bytemaker.rom")
    with pytest.raises(TypeError, match="ambiguous"):
        p.target
    with pytest.raises(TypeError, match="module="):
        p.target
    del dup_a, dup_b


def test_current_binding_filter_prefers_the_class_the_module_still_binds():
    """Redefinition (reload/REPL): a stale same-named class may still be
    alive, but only one is what its module currently means by the name."""
    stale = StructMeta(
        "XModuleRoom", (Struct,), {"__annotations__": {"a": UInt8}}
    )
    p = Ptr("XModuleRoom", module="bytemaker.rom")
    assert p.target is XModuleRoom  # the module-bound one, not `stale`
    del stale


def test_registry_is_weak():
    import gc

    from bytemaker.structs import _structs_named

    ephemeral = StructMeta(
        "XEphemeralRec", (Struct,), {"__annotations__": {"a": UInt8}}
    )
    assert any(c is ephemeral for c in _structs_named("XEphemeralRec"))
    del ephemeral
    gc.collect()
    assert not _structs_named("XEphemeralRec")


# --------------------------------- typed-pointer verification (rom-7)
def verified_space_and_map():
    """Nodes at 0x10 (3 x 8B), ExitList at 0x40; pointers of every flavor."""
    buf = bytearray(0x100)
    Node(value=7, _pad=0, next=BASE + 0x18).pack_into(buf, 0x10)
    Node(value=9, _pad=0, next=BASE + 0x20).pack_into(buf, 0x18)
    Node(value=11, _pad=0, next=0).pack_into(buf, 0x20)
    ExitList(count_=3, first=5).pack_into(buf, 0x40)
    # a bare typed-pointer table at 0x50: good, mistargeted, misaligned
    for i, v in enumerate((BASE + 0x10, BASE + 0x40, BASE + 0x14, 0)):
        buf[0x50 + i * 4 : 0x54 + i * 4] = v.to_bytes(4, "little")
    s = Space(buf, base=BASE, endian="little", name="V")
    entries = [
        Entry(BASE + 0x10, Node, count(3), name="nodes"),
        Entry(BASE + 0x40, ExitList, count(1), name="exits"),
        Entry(BASE + 0x50, Ptr(Node), until(0), name="node_ptrs"),
    ]
    return s, entries


def test_verified_pointers_report_mistargeted_and_misaligned():
    s, entries = verified_space_and_map()
    report = s.coverage(entries)
    table = [p for p in report.pointers if p.source == "node_ptrs"]
    assert [p.verdict for p in table] == ["claimed", "mistargeted", "misaligned"]
    # the claiming region is still named on the defect verdicts
    assert [p.claimed_by for p in table] == ["nodes", "exits", "nodes"]


def test_self_referential_next_pointers_verify_clean():
    s, entries = verified_space_and_map()
    report = s.coverage(entries)
    nexts = [p for p in report.pointers if p.field == "next"]
    # two point at aligned Node starts; the last is the null terminator
    assert [p.verdict for p in nexts] == ["claimed", "claimed", "null"]


def test_untyped_and_unresolvable_pointers_stay_unverified():
    s, entries = verified_space_and_map()
    plain = entries + [
        # Ptr(None): declares no pointee -> claimed, never a defect verdict
        Entry(BASE + 0x50, Ptr(None), count(2), name="untyped"),
        # unresolvable deferred name: unverifiable, must not crash the audit
        Entry(
            BASE + 0x50,
            Ptr("XNoSuchRecordAnywhere"),
            count(2),
            name="unresolvable",
        ),
    ]
    report = s.coverage(plain)
    for source in ("untyped", "unresolvable"):
        verdicts = [p.verdict for p in report.pointers if p.source == source]
        assert verdicts == ["claimed", "claimed"], source


def test_typed_pointer_into_a_raw_byte_region_is_not_a_defect():
    """A u8-blob region can legitimately contain records the map has not
    modelled at that granularity; only a REGION MAPPED AS RECORDS can
    disagree with a pointer's declared type."""
    buf = bytearray(0x100)
    buf[0x50:0x54] = (BASE + 0x10).to_bytes(4, "little")
    s = Space(buf, base=BASE, endian="little", name="V")
    entries = [
        Entry(BASE + 0x10, UInt8, count(16), name="blob"),
        Entry(BASE + 0x50, Ptr(Node), count(1), name="ptr"),
    ]
    (ref,) = [p for p in s.coverage(entries).pointers if p.source == "ptr"]
    assert ref.verdict == "claimed" and ref.claimed_by == "blob"


def test_defect_verdicts_show_up_in_render():
    s, entries = verified_space_and_map()
    text = s.coverage(entries).render()
    assert "mistargeted" in text and "misaligned" in text
    assert "node_ptrs[1]" in text and "node_ptrs[2]" in text


def test_defect_verdicts_are_not_dangling():
    s, entries = verified_space_and_map()
    report = s.coverage(entries)
    assert not report.dangling  # in-space defects are not wild addresses


# ------------------------------------------- deref from the value (rom-8)
def test_value_deref_matches_space_deref():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    assert warp.room_ptr.deref(s) == s.deref(warp, "room_ptr")
    assert warp.room_ptr.deref(s, 2) == s.deref(warp, "room_ptr", 2)


def test_value_deref_chains_across_records():
    s, entries = verified_space_and_map()
    del entries
    # Node.next is Ptr("Node"): walk the list from the value itself,
    # using PtrValue(0)'s int falsiness as the loop condition.
    node = s.read(BASE + 0x10, Node)
    chain = [node.value]
    while node.next:
        node = node.next.deref(s)
        chain.append(node.value)
    assert chain == [7, 9, 11]


def test_bare_table_elements_carry_deref():
    s = space()
    ptrs = s.read(PTR_TABLE, Ptr(RoomHeader), 2)
    assert all(type(p) is PtrValue for p in ptrs)
    assert [p.deref(s).width for p in ptrs] == [16, 8]


def test_pointer_array_field_elements_carry_deref():
    class Table(Struct, endian="little"):
        rooms: List[int] = array(Ptr(RoomHeader), 2)

    s = space()
    t = s.read(PTR_TABLE, Table)
    assert type(t.rooms[0]) is PtrValue
    assert [p.deref(s).width for p in t.rooms] == [16, 8]


def test_untargeted_value_deref_refuses_by_name():
    s = space()
    anim = s.read(ANIMS, AnimSet)
    assert type(anim.fns[0]) is PtrValue  # THUMB'd Ptr(None) element
    with pytest.raises(TypeError, match="has no target codec"):
        anim.fns[0].deref(s)


def test_arithmetic_collapses_to_plain_int():
    """ptr + 4 is an offset address: it no longer carries the target claim,
    so it cannot silently deref as the ORIGINAL record type."""
    s = space()
    ptr = s.read(WARPS + 4, Ptr(RoomHeader))
    assert type(ptr + 4) is int and type(ptr & ~3) is int
    assert not hasattr(ptr + 4, "deref")


def test_ptrvalue_survives_pickle_and_deepcopy():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    ptr = warp.room_ptr
    for clone in (pickle.loads(pickle.dumps(ptr)), copy.deepcopy(ptr)):
        assert type(clone) is PtrValue and clone == ptr
        assert clone.deref(s).width == 16
    # ... and inside a record with a pointer ARRAY field
    anim2 = pickle.loads(pickle.dumps(s.read(ANIMS, AnimSet)))
    assert type(anim2.fns[0]) is PtrValue and anim2.pack() == s.read(
        ANIMS, AnimSet
    ).pack()


def test_record_repr_shows_pointers_in_hex():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    assert "room_ptr=0x8000100" in repr(warp)


def test_stores_accept_plain_ints_and_ptrvalues_alike():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    warp.room_ptr = ROOM_B  # plain int
    assert warp.room_ptr == ROOM_B and type(warp.room_ptr) is PtrValue
    warp.room_ptr = s.read(WARPS + 4, Ptr(RoomHeader))  # a PtrValue
    assert warp.room_ptr == ROOM_A


def test_wire_plane_stays_plain():
    """to_tuple / plan tuples are the WIRE plane: no PtrValue leaks in."""
    s = space()
    warp = s.read(WARPS, WarpPoint)
    assert type(warp.to_tuple()[3]) is int


def test_annotation_may_be_looser_than_the_runtime_type():
    """int (a superclass of PtrValue) stays a valid annotation — the
    relaxation that keeps every existing Annotated[int, Ptr(...)] alias
    compiling — while a WRONG tighter one is still refused."""
    from bytemaker.plans import PlanCompileError

    class LooseOk(Struct, endian="little"):
        p: int = field(Ptr(RoomHeader))

    class PreciseOk(Struct, endian="little"):
        p: PtrValue = field(Ptr(RoomHeader))

    assert LooseOk.num_bytes == PreciseOk.num_bytes == 4
    with pytest.raises(PlanCompileError, match="disagrees"):

        class Wrong(Struct, endian="little"):
            p: float = field(Ptr(RoomHeader))


# ------------------------------------- deref by class attribute (rom-9)
def test_deref_accepts_the_class_attribute():
    """The no-string spelling of the record form: class-level access returns
    the field descriptor, which knows the name it was installed under, so a
    rename refactor updates the call site and a typo is an AttributeError at
    the call, not a KeyError inside deref."""
    s = space()
    warp = s.read(WARPS, WarpPoint)
    assert s.deref(warp, WarpPoint.room_ptr) == s.deref(warp, "room_ptr")
    assert s.deref(warp, WarpPoint.room_ptr, 2) == s.deref(warp, "room_ptr", 2)


def test_deref_accepts_an_array_field_attribute():
    class Table(Struct, endian="little"):
        rooms: List[int] = array(Ptr(RoomHeader), 2)

    s = space()
    t = s.read(PTR_TABLE, Table)
    assert s.deref(t, Table.rooms) == s.deref(t, "rooms")


def test_deref_with_a_value_instead_of_the_attribute_says_so():
    """warp.room_ptr (instance access) is the VALUE, not the field; the
    mistake is one keystroke away from the right call, so the error names
    all three correct spellings."""
    s = space()
    warp = s.read(WARPS, WarpPoint)
    with pytest.raises(TypeError, match="field's VALUE"):
        s.deref(warp, warp.room_ptr)
    with pytest.raises(TypeError, match=r"value\.deref\(space\)"):
        s.deref(warp, warp.room_ptr)


def test_deref_with_a_non_field_object_is_a_type_error():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    with pytest.raises(TypeError, match="is not a field"):
        s.deref(warp, 3.14)
    with pytest.raises(TypeError, match="is not a field"):
        s.deref(warp, RoomHeader)


def test_a_non_pointer_class_attribute_still_gets_the_pointer_listing():
    s = space()
    warp = s.read(WARPS, WarpPoint)
    with pytest.raises(TypeError, match="pointer fields here: room_ptr"):
        s.deref(warp, WarpPoint.sector)


# ------------------------------------------------ coverage gaps (cov-1)
def gap_map():
    """Claims 0x...10-0x...1F and 0x...30-0x...3F of a 0x400 space, leaving
    a gap at the start, one between, and one running to the end."""
    return [
        Entry(BASE + 0x10, UInt8, count(16), name="a"),
        Entry(BASE + 0x30, UInt8, count(16), name="b"),
    ]


def test_gaps_are_the_complement_of_the_claimed_bytes():
    report = space().coverage(gap_map(), audit_pointers=False)
    assert [(g.start, g.size) for g in report.gaps()] == [
        (BASE, 0x10),  # before the first entry
        (BASE + 0x20, 0x10),  # between the two
        (BASE + 0x40, len(BUF) - 0x40),  # ... and out to the end
    ]
    assert sum(g.size for g in report.gaps()) == report.unclaimed_bytes
    assert report.claimed_bytes + report.unclaimed_bytes == report.space_size


def test_gap_end_is_one_past_the_last_unclaimed_byte():
    (first, *_) = space().coverage(gap_map(), audit_pointers=False).gaps()
    assert first.end == first.start + first.size == BASE + 0x10
    assert first.describe() == "0x08000000-0x0800000F (16 bytes)"


def test_gaps_are_addresses_not_offsets():
    """The report carries the space's base, so a gap in a GBA ROM reads as
    0x08000000, the address a disassembly listing would show."""
    report = space().coverage(gap_map(), audit_pointers=False)
    assert report.space_base == BASE
    assert all(g.start >= BASE for g in report.gaps())


def test_min_size_filters_the_noise():
    report = space().coverage(gap_map(), audit_pointers=False)
    big = report.gaps(min_size=0x20)
    assert [g.start for g in big] == [BASE + 0x40]
    assert report.gaps(min_size=1) == report.gaps()


def test_overlapping_claims_do_not_split_a_gap():
    overlapping = gap_map() + [Entry(BASE + 0x18, UInt8, count(16), name="c")]
    report = space().coverage(overlapping, audit_pointers=False)
    # a..c now covers 0x10-0x27, so the middle gap shrinks rather than
    # appearing twice
    assert [(g.start, g.size) for g in report.gaps()][1] == (BASE + 0x28, 8)
    assert report.claimed_bytes == 0x18 + 0x10  # overlap counted once


def test_a_fully_covered_space_has_no_gaps():
    entries = [Entry(BASE, UInt8, count(len(BUF)), name="all")]
    report = space().coverage(entries, audit_pointers=False)
    assert report.gaps() == () and report.unclaimed_bytes == 0
    assert "gaps" not in report.render()


def test_an_unresolved_region_claims_nothing_so_its_bytes_are_gap():
    """An entry that cannot resolve its length may still be right about its
    address -- but a report must not credit a length it could not resolve.
    The unresolved section says which entry and why."""
    entries = [Entry(BASE + 0x10, RoomHeader, unknown("length unknown"), name="m")]
    report = space().coverage(entries, audit_pointers=False)
    assert [(g.start, g.size) for g in report.gaps()] == [(BASE, len(BUF))]
    assert [r.name for r in report.unresolved] == ["m"]


def test_render_lists_the_largest_gaps_first_and_says_so():
    report = space().coverage(gap_map(), audit_pointers=False)
    text = report.render()
    assert f"gaps (3): {report.unclaimed_bytes} bytes unclaimed" in text
    assert "largest first" in text
    listed = [
        line for line in text.splitlines() if line.startswith("    0x")
    ]
    assert listed[0].startswith(f"    0x{BASE + 0x40:08X}")  # the big one


def test_render_truncates_the_gap_listing_and_says_by_how_much():
    report = space().coverage(gap_map(), audit_pointers=False)
    text = report.render(max_gaps=1)
    assert "... and 2 more gaps (raise max_gaps to see them)" in text
    assert "more gaps" not in report.render()


def test_an_empty_map_is_one_whole_gap():
    report = space().coverage([])
    (only,) = report.gaps()
    assert (only.start, only.size) == (BASE, len(BUF))
    assert "0/1024 bytes (0.00%)" in report.render()


def test_claimed_and_unclaimed_partition_the_space_even_when_hand_built():
    """The two are documented as one partition, so they must be read off the
    same list. A hand-assembled report (the dataclass is public) with a region
    hanging off the end used to inflate the claim AND stretch a gap past the
    space's own end."""
    from bytemaker.rom import CoverageReport, Region

    s = space()
    past_end = Entry(BASE + len(BUF) - 4, UInt8, count(4), name="tail").bind(s)
    # Straddles the LOW edge too: two of its four bytes lie below the base.
    # The low-side clip is the half of the docstring's promise a mutation
    # test showed nothing exercised.
    before = Entry(BASE + 2, UInt8, count(4), name="head")
    report = CoverageReport(
        space_name="hand",
        space_size=8,  # deliberately smaller than the regions describe
        space_base=BASE + 4,  # ... and past the "head" region's start
        regions=(
            Region(past_end, 4),
            Region(before, 4),
            Region(Entry(BASE + 8, UInt8, count(2)), 2),  # disjoint, in-space
        ),
        overlaps=(),
        pointers=(),
    )
    assert report.claimed_bytes + report.unclaimed_bytes == report.space_size
    low, high = report.space_base, report.space_base + report.space_size
    assert all(low <= g.start and g.end <= high for g in report.gaps())
    # the straddling region contributes only its in-space bytes to the claim
    assert report.claimed_bytes == 2 + 2  # head's clipped half + the real one


def test_unclaimed_bytes_is_the_sum_of_the_gaps():
    """Falsifiable on purpose: unclaimed_bytes is computed as
    space_size - claimed_bytes, so equality with the gap sum pins that the
    two views really are one partition (they share _merged_spans)."""
    for entries in ([], gap_map(), rom_map()):
        report = space().coverage(entries, audit_pointers=False)
        assert report.unclaimed_bytes == sum(g.size for g in report.gaps())
        assert report.claimed_bytes + report.unclaimed_bytes == len(BUF)
