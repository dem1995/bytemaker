"""bytemaker.rom: Space, extents, Entry (rom-1).

Synthetic buffers only — no binaries in test/. The addresses use a GBA-style
0x08000000 base because that is the case the layer exists for, but nothing
here is game-specific.
"""

import pytest

from bytemaker.adapters import THUMB_PTR, fixed
from bytemaker.bittypes import UInt8, UInt16, UInt32
from bytemaker.rom import (
    AddressError,
    Edit,
    Entry,
    Patch,
    PatchVerifyError,
    Space,
    count,
    span,
    unknown,
    until,
)
from bytemaker.structs import Array, Struct, array, field

BASE = 0x08000000
ThumbPtr = THUMB_PTR @ UInt32
Mult = fixed(4) @ UInt16


class Reward(Struct, endian="little"):
    max_frames: int = field(UInt16)
    pad: int = field(UInt16)
    item_id: int = field(UInt32)


class Nibbles(Struct, endian="little", bit_order="lsb"):
    lo: UInt8.specialize(4, name_="N4a")  # type: ignore[misc]
    hi: UInt8.specialize(4, name_="N4b")  # type: ignore[misc]


def make_buf():
    buf = bytearray(0x400)
    buf[0x000:0x004] = bytes([7, 6, 8, 9])  # u8 palette
    buf[0x010:0x018] = b"\xa9\xeb\x03\x08\x35\xec\x03\x08"  # 2 THUMB ptrs
    buf[0x020:0x024] = b"\x18\x00\x10\x00"  # 2 Q4 multipliers: 1.5, 1.0
    # 3 Reward records (8 bytes each), then an all-zero one as a terminator
    for i, (frames, item) in enumerate(
        ((14400, 91), (18000, 90), (21600, 69))
    ):
        at = 0x030 + i * 8
        buf[at : at + 8] = (
            frames.to_bytes(2, "little") + b"\x00\x00" + item.to_bytes(4, "little")
        )
    # 0x048..0x050 stays zero: the sentinel record
    buf[0x100:0x108] = b"\x01\x00\x00\x08\x00\x00\x00\x00"  # ptr, then 0
    buf[0x200:0x202] = b"\xcd\xab"  # a big/little-endian witness
    return buf


BUF = make_buf()


def space(buf=None, **kw):
    kw.setdefault("base", BASE)
    kw.setdefault("endian", "little")
    kw.setdefault("name", "T")
    return Space(BUF if buf is None else buf, **kw)


# ------------------------------------------------------------ address math
def test_offset_and_addr_of_are_inverses():
    s = space()
    assert s.offset(BASE) == 0
    assert s.offset(BASE + 0x123) == 0x123
    assert s.addr_of(0x123) == BASE + 0x123
    assert s.base == BASE and len(s) == len(BUF) and s.end == BASE + len(BUF)


def test_offset_rejects_out_of_space_addresses():
    s = space()
    with pytest.raises(AddressError, match="outside the space"):
        s.offset(BASE - 1)
    with pytest.raises(AddressError, match="outside the space"):
        s.offset(BASE + len(BUF) + 1)
    with pytest.raises(TypeError, match="must be an int"):
        s.offset("0x08000000")


def test_contains_classifies_without_raising():
    s = space()
    assert s.contains(BASE) and s.contains(BASE + len(BUF) - 1)
    assert not s.contains(BASE - 1)
    assert not s.contains(BASE + len(BUF))
    assert not s.contains(0x02010000)  # GBA EWRAM: a real address, other space
    assert not s.contains(None)


def test_endian_is_required_and_validated():
    with pytest.raises(TypeError):
        Space(BUF, base=BASE)  # endian is keyword-only AND required
    with pytest.raises(ValueError, match="endian"):
        Space(BUF, base=BASE, endian="bigg")
    with pytest.raises(ValueError, match="base"):
        Space(BUF, base=-1, endian="big")


def test_repr_shows_the_range_and_byte_order():
    r = repr(space())
    assert "0x08000000" in r and "little" in r and "'T'" in r


# ------------------------------------------------------------------- reads
def test_scalar_read_uses_the_spaces_byte_order():
    assert space().read(BASE + 0x200, UInt16) == 0xABCD
    assert space(endian="big").read(BASE + 0x200, UInt16) == 0xCDAB


def test_count_one_returns_one_item_and_count_n_a_list():
    s = space()
    assert s.read(BASE, UInt8) == 7
    assert s.read(BASE, UInt8, 1) == 7
    assert s.read(BASE, UInt8, count(1)) == 7
    assert s.read(BASE, UInt8, 4) == [7, 6, 8, 9]
    assert s.read(BASE, UInt8, count(4)) == [7, 6, 8, 9]


def test_count_zero_reads_nothing():
    s = space()
    assert s.read(BASE, UInt8, 0) == []
    assert s.read(BASE + 0x030, Reward, 0) == []


def test_struct_read_single_and_many():
    s = space()
    one = s.read(BASE + 0x030, Reward)
    assert (one.max_frames, one.item_id) == (14400, 91)
    three = s.read(BASE + 0x030, Reward, 3)
    assert [r.max_frames for r in three] == [14400, 18000, 21600]
    assert [r.item_id for r in three] == [91, 90, 69]


def test_adapted_codec_read_applies_the_adapter():
    s = space()
    assert s.read(BASE + 0x010, ThumbPtr) == 0x0803EBA8  # THUMB bit masked
    assert s.read(BASE + 0x010, ThumbPtr, 2) == [0x0803EBA8, 0x0803EC34]
    assert s.read(BASE + 0x020, Mult, 2) == [1.5, 1.0]
    # ... and the unadapted read still shows the raw wire
    assert s.read(BASE + 0x010, UInt32) == 0x0803EBA9


def test_array_codec_brings_its_own_endian_and_adapter():
    s = space(endian="big")  # deliberately the WRONG order for this table
    arr = Array.of(ThumbPtr, 2, endian="little")
    assert s.read(BASE + 0x010, arr) == [0x0803EBA8, 0x0803EC34]
    # two copies of the array -> a list of lists
    two = s.read(BASE + 0x010, Array.of(UInt32, 1, endian="little"), 2)
    assert two == [[0x0803EBA9], [0x0803EC35]]


def test_an_unset_array_inherits_the_spaces_byte_order():
    """``UInt16 * 2`` carries no byte order of its own, so a standalone
    parse would hit the explicit-endian guard -- even though plain
    ``UInt16`` at the same address reads fine, because the scalar path
    builds its array from the space's order. Both spellings agree now."""
    little, big = space(), space(endian="big")
    assert little.read(BASE + 0x200, UInt16) == 0xABCD
    assert little.read(BASE + 0x200, UInt16 * 1) == [0xABCD]
    assert big.read(BASE + 0x200, UInt16) == 0xCDAB
    assert big.read(BASE + 0x200, UInt16 * 1) == [0xCDAB]
    assert little.read(BASE + 0x010, UInt32 * 2) == [0x0803EBA9, 0x0803EC35]


def test_an_unset_array_writes_in_the_spaces_byte_order():
    buf = bytearray(8)
    s = Space(buf, base=BASE, endian="little")
    s.write(BASE, [0x1234, 0x5678], UInt16 * 2)
    assert bytes(buf[:4]) == b"\x34\x12\x78\x56"
    assert s.read(BASE, UInt16 * 2) == [0x1234, 0x5678]


def test_a_declared_array_endian_wins_over_the_spaces():
    buf = bytearray(8)
    s = Space(buf, base=BASE, endian="little")
    be = Array.of(UInt16, 1, endian="big")
    s.write(BASE, [0x1234], be)
    assert bytes(buf[:2]) == b"\x12\x34"  # big, despite the little space
    assert s.read(BASE, be) == [0x1234]


def test_read_bounds_are_checked():
    s = space()
    with pytest.raises(AddressError, match="past the end"):
        s.read(BASE + len(BUF) - 2, UInt32)
    with pytest.raises(AddressError, match="outside the space"):
        s.read(BASE - 4, UInt32)


def test_subbyte_codecs_are_refused_with_directions():
    s = space()
    N4 = UInt8.specialize(4, name_="N4c")
    with pytest.raises(ValueError, match="sub-byte stride"):
        s.read(BASE, N4)
    # ... and the sanctioned workaround reads fine
    assert s.read(BASE, Nibbles).lo == 7


def test_non_codec_arguments_are_named():
    s = space()
    with pytest.raises(TypeError, match="not a codec"):
        s.read(BASE, "UInt8")


def test_slice_is_a_bounds_checked_view():
    s = space()
    v = s.slice(BASE, 4)
    assert isinstance(v, memoryview) and bytes(v) == bytes([7, 6, 8, 9])
    with pytest.raises(AddressError, match="past the end"):
        s.slice(BASE + len(BUF) - 2, 4)


# ----------------------------------------------------------------- extents
def test_span_resolves_an_inclusive_end_address():
    s = space()
    assert s.read(BASE, UInt8, span(BASE + 3)) == [7, 6, 8, 9]
    assert s.read(BASE + 0x030, Reward, span(BASE + 0x047)) == s.read(
        BASE + 0x030, Reward, 3
    )
    # a span of exactly one item still returns a list (shape follows the
    # declaration, not the data)
    assert s.read(BASE, UInt8, span(BASE)) == [7]


def test_span_must_divide_evenly_and_run_forwards():
    s = space()
    with pytest.raises(ValueError, match="not a whole number"):
        s.read(BASE, UInt32, span(BASE + 5))
    with pytest.raises(ValueError, match="before the start"):
        s.read(BASE + 4, UInt8, span(BASE))
    with pytest.raises(ValueError, match="int address"):
        span("0x100")


def test_until_scans_to_the_sentinel():
    s = space()
    assert s.read(BASE + 0x100, ThumbPtr, until(0)) == [0x08000000]
    assert not hasattr(s, "scan")  # until() is the one spelling for this
    # an all-zero RECORD terminates a struct table
    rewards = s.read(BASE + 0x030, Reward, until(0))
    assert [r.item_id for r in rewards] == [91, 90, 69]


def test_until_compares_the_sentinel_on_the_wire_not_the_user_plane():
    """THUMB_PTR.store(0) is 1, so a user-plane comparison would look for
    0x00000001 — which is the FIRST entry of this table. The sentinel must
    be the unadapted encoding."""
    s = space()
    assert s.read(BASE + 0x100, ThumbPtr, until(0)) == [0x08000000]
    # the same table read unadapted terminates identically
    assert s.read(BASE + 0x100, UInt32, until(0)) == [0x08000001]


def test_until_accepts_a_nonzero_scalar_sentinel_and_raw_bytes():
    buf = bytearray(b"\x01\x02\xff\x03")
    s = Space(buf, base=BASE, endian="little", name="T")
    assert s.read(BASE, UInt8, until(0xFF)) == [1, 2]
    assert s.read(BASE, UInt8, until(b"\xff")) == [1, 2]
    with pytest.raises(ValueError, match="stride"):
        s.read(BASE, UInt8, until(b"\xff\xff"))


def test_until_needs_raw_bytes_for_a_nonzero_composite_sentinel():
    s = space()
    with pytest.raises(TypeError, match="raw bytes"):
        s.read(BASE + 0x030, Reward, until(1))


def test_until_with_an_immediate_sentinel_reads_nothing():
    buf = bytearray(b"\x00\x01\x02")
    s = Space(buf, base=BASE, endian="little")
    assert s.read(BASE, UInt8, until(0)) == []


def test_until_raises_rather_than_running_away():
    s = space()
    with pytest.raises(ValueError, match="no sentinel"):
        s.read(BASE, UInt8, until(0xFF, max_count=8))
    with pytest.raises(AddressError, match="reached the end of the space"):
        s.read(BASE, UInt8, until(0xFF, max_count=10**6))
    with pytest.raises(ValueError, match="positive int"):
        until(0, max_count=0)


def test_unknown_refuses_to_read_and_says_what_to_do():
    s = space()
    with pytest.raises(ValueError, match="unknown"):
        s.read(BASE, UInt8, unknown())
    with pytest.raises(ValueError, match="probably 4"):
        s.read(BASE, UInt8, unknown("probably 4"))


def test_extents_are_value_objects():
    assert count(4) == count(4) and count(4) != count(5)
    assert until(0) == until(0) and until(0) != until(0, max_count=8)
    assert span(1) == span(1) and count(1) != span(1)
    assert len({count(4), count(4), count(5)}) == 2
    assert repr(count(4)) == "count(n=4)"
    with pytest.raises(ValueError, match="non-negative"):
        count(-1)


def test_bare_ints_and_none_normalize_to_count():
    s = space()
    assert s.read(BASE, UInt8, None) == 7
    with pytest.raises(TypeError, match="must be an int or an Extent"):
        s.read(BASE, UInt8, "4")
    with pytest.raises(TypeError, match="must be an int or an Extent"):
        s.read(BASE, UInt8, True)


# ------------------------------------------------------------------ writes
def test_write_splices_scalars_and_lists():
    buf = make_buf()
    s = Space(buf, base=BASE, endian="little")
    s.write(BASE, 42, UInt8)
    assert buf[0] == 42
    s.write(BASE, [1, 2, 3, 4], UInt8)
    assert list(buf[0:4]) == [1, 2, 3, 4]
    s.write(BASE + 0x200, 0x1234, UInt16)
    assert bytes(buf[0x200:0x202]) == b"\x34\x12"


def test_write_applies_adapters():
    buf = make_buf()
    s = Space(buf, base=BASE, endian="little")
    s.write(BASE + 0x010, 0x0803ED6C, ThumbPtr)
    assert bytes(buf[0x010:0x014]) == b"\x6d\xed\x03\x08"  # THUMB bit set
    assert s.read(BASE + 0x010, ThumbPtr) == 0x0803ED6C


def test_write_infers_a_struct_codec_from_the_record():
    buf = make_buf()
    s = Space(buf, base=BASE, endian="little")
    rec = s.read(BASE + 0x030, Reward)
    rec.item_id = 7
    s.write(BASE + 0x030, rec)  # no codec= needed
    assert s.read(BASE + 0x030, Reward).item_id == 7
    s.write(BASE + 0x030, [rec, rec])
    assert [r.item_id for r in s.read(BASE + 0x030, Reward, 2)] == [7, 7]
    with pytest.raises(TypeError, match="cannot infer"):
        s.write(BASE, 42)


def test_write_bounds_and_readonly_buffers():
    buf = make_buf()
    s = Space(buf, base=BASE, endian="little")
    with pytest.raises(AddressError, match="past the end"):
        s.write(BASE + len(buf) - 2, 0, UInt32)
    frozen = Space(bytes(buf), base=BASE, endian="little")
    with pytest.raises(TypeError, match="read-only"):
        frozen.write(BASE, 42, UInt8)


def test_write_type_errors_name_the_codec():
    buf = make_buf()
    s = Space(buf, base=BASE, endian="little")
    with pytest.raises(TypeError, match="expected a Reward record"):
        s.write(BASE + 0x030, 5, Reward)
    with pytest.raises(TypeError, match="expected Reward records"):
        s.write(BASE + 0x030, [5], Reward)


# ----------------------------------------------------------------- entries
def test_entry_declares_without_a_space_and_binds_later():
    e = Entry(BASE, UInt8, count(4), name="palette", note="soul object")
    assert e.space is None
    with pytest.raises(ValueError, match="not bound"):
        e.read()
    bound = e.bind(space())
    assert bound.read() == [7, 6, 8, 9]
    assert e.space is None  # bind returns a copy; the declaration is reusable


def test_space_entry_builds_a_bound_entry():
    e = space().entry(BASE, UInt8, 4, name="palette")
    assert e.space is not None and e.read() == [7, 6, 8, 9]


def test_entry_derives_stride_count_size_and_span():
    e = Entry(BASE + 0x030, Reward, count(3))
    assert e.stride == 8 and e.item_count == 3 and e.size == 24
    assert e.byte_span == (BASE + 0x030, BASE + 0x047)
    sp = Entry(BASE, UInt8, span(BASE + 3))
    assert sp.item_count == 4 and sp.size == 4
    for unresolvable in (Entry(BASE, UInt8, until(0)), Entry(BASE, UInt8, unknown())):
        assert unresolvable.item_count is None
        assert unresolvable.size is None
        assert unresolvable.byte_span is None
    assert Entry(BASE, UInt8, count(0)).byte_span is None


def test_entry_read_extent_override_honors_zero():
    e = space().entry(BASE, UInt8, unknown())
    with pytest.raises(ValueError, match="unknown"):
        e.read()
    assert e.read(4) == [7, 6, 8, 9]
    assert e.read(0) == []  # not "fall back to the declared extent"
    assert e.read(count(0)) == []


def test_entry_write_goes_through_its_codec():
    buf = make_buf()
    e = Space(buf, base=BASE, endian="little").entry(
        BASE + 0x010, ThumbPtr, 1, name="fn"
    )
    e.write(0x0803ED6C)
    assert bytes(buf[0x010:0x014]) == b"\x6d\xed\x03\x08"


def test_entry_is_frozen_and_describes_itself():
    e = Entry(BASE + 0x030, Reward, count(3), name="rewards", note="boss rush")
    with pytest.raises(AttributeError, match="frozen"):
        e.addr = 0
    line = e.describe()
    assert "rewards" in line and "0x08000030" in line and "Reward" in line
    assert "boss rush" in line
    assert "Reward" in repr(e) and "bound" not in repr(e)
    assert "bound" in repr(e.bind(space()))
    with pytest.raises(ValueError, match="non-negative"):
        Entry(-1, UInt8)


def test_entry_equality_ignores_nothing_that_matters():
    a = Entry(BASE, UInt8, count(4), name="p")
    assert a == Entry(BASE, UInt8, count(4), name="p")
    assert a != Entry(BASE, UInt8, count(5), name="p")
    assert a != Entry(BASE, UInt8, count(4), name="q")
    assert a != a.bind(space())
    assert a != "nope"


# ------------------------------------------------- Struct.parse_at/pack_into
class Aligned(Struct, endian="little"):
    a: UInt16
    b: UInt32


class Unaligned(Struct, endian="little", bit_order="lsb"):
    lo: UInt8.specialize(3, name_="U3r")  # type: ignore[misc]
    mid: UInt8.specialize(5, name_="U5r")  # type: ignore[misc]
    hi: UInt16


def test_parse_at_reads_without_a_call_site_slice():
    for cls in (Aligned, Unaligned):
        rec = cls.parse(bytes(range(1, cls.num_bytes + 1)))
        blob = b"\xff" * 3 + rec.pack() * 2
        assert cls.parse_at(blob, 3) == rec
        assert cls.parse_at(blob, 3 + cls.num_bytes) == rec
        with pytest.raises(ValueError, match="outside the buffer"):
            cls.parse_at(blob, -1)
        with pytest.raises(ValueError, match="only 0 whole records"):
            cls.parse_at(blob, len(blob) - 1)


def test_pack_into_writes_in_place_on_both_tiers():
    for cls in (Aligned, Unaligned):
        rec = cls.parse(bytes(range(1, cls.num_bytes + 1)))
        buf = bytearray(3 + cls.num_bytes * 2)
        rec.pack_into(buf, 3)
        assert bytes(buf[3 : 3 + cls.num_bytes]) == rec.pack()
        assert bytes(buf[: 3]) == b"\x00\x00\x00"  # nothing else touched
        with pytest.raises(ValueError, match="does not fit"):
            rec.pack_into(buf, len(buf) - 1)
        with pytest.raises(ValueError, match="does not fit"):
            rec.pack_into(buf, -1)


def test_pack_into_narrows_like_pack_tuple():
    rec = Aligned.parse(b"\x00" * 6)
    buf = bytearray(6)
    rec.plan.pack_into(buf, 0, (0x1FFFF, 0))  # out of range for u16
    assert bytes(buf) == Aligned.plan.pack_tuple((0x1FFFF, 0))
    with pytest.raises(ValueError, match="expected 2 values"):
        rec.plan.pack_into(buf, 0, (1,))


def test_pack_into_round_trips_through_parse_at():
    rec = Aligned(a=0x1234, b=0xDEADBEEF)
    buf = bytearray(20)
    rec.pack_into(buf, 8)
    assert Aligned.parse_at(buf, 8) == rec


def test_entry_write_refuses_to_outgrow_its_extent():
    """A count(3) table holds three records. Writing five used to splice
    straight through the neighbour with no complaint."""
    buf = bytearray(0x40)
    s = Space(buf, base=BASE, endian="little")
    e = s.entry(BASE, Reward, count(3), name="rewards")
    with pytest.raises(ValueError, match="do not fit the 24 from count"):
        e.write([Reward(max_frames=i, pad=0, item_id=i) for i in range(5)])
    assert bytes(buf) == bytes(0x40)  # nothing was spliced
    e.write([Reward(max_frames=7, pad=0, item_id=9)])  # fewer rows is fine
    assert s.read(BASE, Reward) == Reward(max_frames=7, pad=0, item_id=9)


def test_entry_write_without_a_known_size_only_meets_the_space_bounds():
    buf = bytearray(0x20)
    s = Space(buf, base=BASE, endian="little")
    blob = s.entry(BASE, UInt8, unknown("hook blob"), name="hook")
    blob.write(b"\xde\xad\xbe\xef")
    assert bytes(buf[:4]) == b"\xde\xad\xbe\xef"
    with pytest.raises(AddressError, match="past the end"):
        blob.write(b"\x00" * 0x21)


def test_write_with_expect_guards_against_the_wrong_bytes():
    """`expect=` is a value in the same codec, not bytes: 'this was 32, make
    it 5' -- and say so loudly if it was not 32."""
    buf = bytearray(8)
    s = Space(buf, base=BASE, endian="little")
    s.write(BASE, 0x1234, UInt16)
    s.write(BASE, 0x5678, UInt16, expect=0x1234)  # matches: lands
    assert s.read(BASE, UInt16) == 0x5678
    with pytest.raises(PatchVerifyError, match="but the write expected"):
        s.write(BASE, 0x9ABC, UInt16, expect=0x1234)  # stale expectation
    assert s.read(BASE, UInt16) == 0x5678  # refused, nothing written


def test_expect_is_checked_before_a_patch_records_anything():
    buf = bytearray(8)
    s = Space(buf, base=BASE, endian="little")
    p = Patch()
    with pytest.raises(PatchVerifyError):
        s.write(BASE, 0x9ABC, UInt16, patch=p, expect=0x1234)
    assert not p  # the patch stays empty


def test_expect_must_describe_the_same_bytes_as_the_value():
    s = Space(bytearray(16), base=BASE, endian="little")
    e = s.entry(BASE, Reward, count(2), name="two")
    with pytest.raises(ValueError, match="the same bytes"):
        e.write([Reward(max_frames=1, pad=0, item_id=1)] * 2,
                expect=Reward(max_frames=0, pad=0, item_id=0))


def test_entry_write_with_expect_states_the_guard_in_its_own_codec():
    buf = bytearray(16)
    s = Space(buf, base=BASE, endian="little")
    e = s.entry(BASE, Reward, count(1), name="reward")
    before = Reward(max_frames=0, pad=0, item_id=0)
    e.write(Reward(max_frames=7, pad=0, item_id=9), expect=before)
    assert e.read() == Reward(max_frames=7, pad=0, item_id=9)
    with pytest.raises(PatchVerifyError):
        e.write(Reward(max_frames=8, pad=0, item_id=9), expect=before)


def test_space_write_splices_raw_bytes_with_no_codec():
    buf = bytearray(8)
    s = Space(buf, base=BASE, endian="little")
    s.write(BASE + 2, b"\x01\x02\x03")
    assert bytes(buf) == b"\x00\x00\x01\x02\x03\x00\x00\x00"


# ------------------------------------------- item / field / set (rom-15)
class Enemy(Struct, endian="little"):
    hp: int = field(UInt16)
    soul_rate: int = field(UInt8)
    flags: int = field(UInt8)
    ident: int = field(UInt16, endian="big")  # a field with its own order


def enemy_space():
    buf = bytearray(0x40)
    for i, (hp, rate) in enumerate(((100, 32), (200, 16), (300, 8))):
        Enemy(hp=hp, soul_rate=rate, flags=0, ident=0xAABB).pack_into(buf, i * 6)
    return Space(buf, base=BASE, endian="little", name="E"), buf


def test_item_addresses_a_row_without_hand_arithmetic():
    s, _ = enemy_space()
    table = s.entry(BASE, Enemy, count(3), name="enemies")
    assert [table.item(i).addr for i in range(3)] == [BASE, BASE + 6, BASE + 12]
    assert table.item(1).read() == Enemy(hp=200, soul_rate=16, flags=0, ident=0xAABB)
    assert table.item(2).name == "enemies[2]"
    with pytest.raises(IndexError, match="outside this entry"):
        table.item(3)


def test_field_addresses_one_field_of_one_row():
    s, _ = enemy_space()
    table = s.entry(BASE, Enemy, count(3), name="enemies")
    rate = table.item(1).field("soul_rate")
    assert rate.addr == BASE + 6 + 2  # +0x02, from the compiled layout
    assert rate.read() == 16
    assert rate.name == "enemies[1].soul_rate"


def test_field_writes_claim_only_that_fields_bytes():
    s, buf = enemy_space()
    table = s.entry(BASE, Enemy, count(3), name="enemies")
    p = Patch()
    table.item(2).field("soul_rate").write(5, expect=8, patch=p)
    assert p.byte_count == 1 and p.edits == (Edit(14, b"\x05", b"\x08"),)
    assert bytes(buf) == bytes(buf)  # patch recorded, buffer untouched


def test_a_field_keeps_the_byte_order_its_record_declared():
    """`ident` is big-endian inside a little-endian record in a
    little-endian space; reading it as a field has to honour the record."""
    s, _ = enemy_space()
    e = s.entry(BASE, Enemy, count(1), name="e")
    assert e.field("ident").endian == "big"
    assert e.field("ident").read() == 0xAABB  # not 0xBBAA
    e.field("ident").write(0x1234)
    assert e.read().ident == 0x1234
    assert e.field("hp").endian == "little"


def test_field_needs_one_record_so_a_row_is_named_first():
    """"Which field of a 113-row table" has no answer; the row comes first,
    and .item(i) is the one way to say it."""
    s, _ = enemy_space()
    table = s.entry(BASE, Enemy, count(3), name="enemies")
    with pytest.raises(ValueError, match=r"needs one record.*\.item\(0\)"):
        table.field("hp")
    assert table.item(0).field("hp").read() == 100


def test_field_rejects_an_unknown_name_and_a_non_struct_codec():
    s, _ = enemy_space()
    e = s.entry(BASE, Enemy, count(1), name="e")
    with pytest.raises(ValueError, match="no field 'hpp'; it has hp"):
        e.field("hpp")
    with pytest.raises(TypeError, match="needs a Struct codec"):
        s.entry(BASE, UInt16, count(1)).field("hp")


def test_field_refuses_a_field_that_is_not_whole_bytes():
    s = Space(bytearray(8), base=BASE, endian="little")
    e = s.entry(BASE, Nibbles, count(1), name="n")
    with pytest.raises(ValueError, match="does not occupy whole bytes"):
        e.field("hi")


def test_set_writes_several_fields_and_leaves_the_rest_alone():
    s, buf = enemy_space()
    before = bytes(buf)
    e = s.entry(BASE, Enemy, count(1), name="e")
    p = Patch()
    e.set(p, soul_rate=9, flags=3)
    assert p.byte_count == 2  # two adjacent bytes, one coalesced edit
    assert len(p.edits) == 1
    after = Space(p.apply(before), base=BASE, endian="little").read(BASE, Enemy)
    assert after == Enemy(hp=100, soul_rate=9, flags=3, ident=0xAABB)


def test_set_without_a_patch_writes_in_place():
    s, buf = enemy_space()
    s.entry(BASE, Enemy, count(1), name="e").set(soul_rate=9)
    assert buf[2] == 9


def test_set_needs_at_least_one_field():
    s, _ = enemy_space()
    with pytest.raises(TypeError, match="at least one field"):
        s.entry(BASE, Enemy, count(1)).set()


# ------------------------------------------------------ reserve (rom-15)
def test_reserve_bounds_a_write_and_claims_its_room():
    s = Space(bytearray(0x100), base=BASE, endian="little")
    hook = s.entry(BASE, UInt8, unknown("hook blob"), reserve=0x20, name="hook")
    assert hook.capacity == 0x20 and hook.size is None
    hook.write(b"\xde\xad" * 8)  # 16 <= 0x20
    with pytest.raises(ValueError, match="do not fit the 32 from reserve"):
        hook.write(b"\x00" * 0x21)
    # an unknown() extent claims nothing; a reservation claims its room
    report = s.coverage([hook])
    assert report.claimed_bytes == 0x20 and not report.unresolved


def test_reserve_may_not_be_smaller_than_the_extent_declares():
    with pytest.raises(ValueError, match="smaller than the 24 bytes"):
        Entry(BASE, Reward, count(3), reserve=8, name="rewards")


# --------------------------------------------- geometry-only Space (rom-14)
def gba():
    """The GBA cart address plane, with no cart in hand."""
    return Space(None, size=0x800000, base=BASE, endian="little", name="GBA")


def test_a_geometry_only_space_needs_a_size_and_refuses_a_buffer_with_one():
    with pytest.raises(ValueError, match="needs size="):
        Space(None, base=BASE, endian="little")
    with pytest.raises(ValueError, match="already knows its own length"):
        Space(BUF, size=8, base=BASE, endian="little")
    with pytest.raises(TypeError, match="bytes-like or None"):
        Space("not bytes", base=BASE, endian="little")


def test_geometry_only_address_math_works_without_bytes():
    s = gba()
    assert not s.backed and s.buf is None
    assert len(s) == 0x800000 and s.end == BASE + 0x800000
    assert s.offset(BASE + 0x521B8C) == 0x521B8C  # the whole point
    assert s.contains(BASE + 0x100) and not s.contains(BASE + 0x800000)
    with pytest.raises(AddressError, match="outside the space"):
        s.offset(BASE - 1)


def test_geometry_only_reads_refuse_and_say_why():
    s = gba()
    for call in (
        lambda: s.read(BASE, UInt16),
        lambda: s.slice(BASE, 4),
        lambda: s.read(BASE, Reward),
    ):
        with pytest.raises(ValueError, match="geometry only"):
            call()


def test_geometry_only_writes_record_blind_edits():
    """The generation-time flow: emit writes for an image that does not
    exist yet, then apply them to whatever the player supplies."""
    s = gba()
    p = Patch(name="tokens")
    s.write(BASE + 0x10, 0xBBAA, UInt16, patch=p)
    assert not p.verifiable
    assert p.edits == (Edit(0x10, b"\xaa\xbb"),)
    real = bytearray(0x20)
    assert p.apply(bytes(real))[0x10:0x12] == b"\xaa\xbb"


def test_a_geometry_only_write_needs_a_patch_to_land_in():
    with pytest.raises(ValueError, match="nothing to mutate"):
        gba().write(BASE, 1, UInt16)


def test_an_expect_guard_claims_its_full_span():
    """The guard you state is the guard you get: a u16 whose high byte
    happens to match must still be guarded as a whole u16, or a live CAS
    checks less than the caller said."""
    s = gba()
    p = Patch()
    s.write(BASE + 4, 6, UInt16, patch=p, expect=5)  # only the low byte differs
    assert p.edits == (Edit(4, b"\x06\x00", b"\x05\x00"),)  # 2 bytes, not 1
    assert p.guards() == ((4, b"\x05\x00", b"\x06\x00"),)


def test_writing_the_expected_value_still_records_the_check():
    """new == expect is 'verify it is still 5 and write 5' -- an idempotent
    guarded write, not nothing. Trimming it away would silently turn a CAS
    into no check at all."""
    s = gba()
    p = Patch()
    s.write(BASE + 4, 5, UInt16, patch=p, expect=5)
    assert p.byte_count == 2 and p.changed_byte_count == 0
    assert p.edits[0].is_noop and not p.edits[0].is_blind
    assert p.guards() == ((4, b"\x05\x00", b"\x05\x00"),)
    wrong = bytearray(16)  # holds 0, not 5
    with pytest.raises(PatchVerifyError):
        p.apply(bytes(wrong))


def test_a_backed_expect_guard_is_also_recorded_whole():
    buf = bytearray(16)
    buf[4:6] = (5).to_bytes(2, "little")
    s = Space(buf, base=BASE, endian="little")
    p = Patch()
    s.write(BASE + 4, 6, UInt16, patch=p, expect=5)
    assert p.edits == (Edit(4, b"\x06\x00", b"\x05\x00"),)  # full span
    q = Patch()
    s.write(BASE + 4, 6, UInt16, patch=q)  # no guard stated: changed-only
    assert q.byte_count == 1


def test_expect_without_bytes_is_carried_into_the_patch():
    """Nothing to compare against now, so the claim rides into the patch and
    is checked when it is applied."""
    s = gba()
    p = Patch()
    s.write(BASE + 4, 5, UInt8, patch=p, expect=32)
    assert p.verifiable and p.edits == (Edit(4, b"\x05", b"\x20"),)
    wrong = bytearray(8)  # holds 0, not 32
    with pytest.raises(PatchVerifyError, match="offset 4"):
        p.apply(bytes(wrong))
    right = bytearray(8)
    right[4] = 32
    assert p.apply(bytes(right))[4] == 5


def test_geometry_only_coverage_audits_declarations_and_says_it_read_nothing():
    s = gba()
    report = s.coverage([
        Entry(BASE + 0x100, Reward, count(3), name="rewards"),
        Entry(BASE + 0x108, Reward, count(2), name="overlapping"),
        Entry(BASE + 0x400, Reward, unknown("length TBD"), name="mystery"),
    ])
    # claimed bytes are a union, so the overlapping entry adds none of its own
    assert report.claimed_bytes == 24
    assert [(o.a, o.b, o.size) for o in report.overlaps] == [
        ("rewards", "overlapping", 16)
    ]
    assert [r.name for r in report.unresolved] == ["mystery"]
    assert not report.pointers_audited
    assert "pointers: not audited" in report.render()


# ------------------------------------------- bytes in hand (rom-16)
class Vitals(Struct, endian="little"):
    current_hp: int = field(UInt16)
    max_hp: int = field(UInt16)


def test_request_says_where_and_how_many_bytes_to_fetch():
    ewram = Space(None, size=0x40000, base=0x02000000, endian="little", name="EW")
    vitals = ewram.entry(0x0201327A, Vitals, count(1), name="vitals")
    assert vitals.request() == (0x1327A, 4)  # domain offset, size from the type
    unknown_len = ewram.entry(0x02000000, UInt8, unknown("?"), name="mystery")
    with pytest.raises(ValueError, match="not known"):
        unknown_len.request()


def test_parse_and_pack_move_between_fetched_bytes_and_values():
    """The live-memory round trip: the caller owns the transport, the
    declaration owns the address, the size and the decoding."""
    ewram = Space(None, size=0x40000, base=0x02000000, endian="little", name="EW")
    vitals = ewram.entry(0x0201327A, Vitals, count(1), name="vitals")

    fetched = b"\x64\x00\xc8\x00"  # what a read_many() would hand back
    v = vitals.parse(fetched)
    assert v == Vitals(current_hp=100, max_hp=200)

    v.current_hp = 1
    assert vitals.pack(v) == b"\x01\x00\xc8\x00"  # new bytes for a write
    assert vitals.pack(vitals.parse(fetched)) == fetched  # and the guard bytes


def test_parse_reads_a_table_and_checks_the_length_it_was_given():
    s = Space(None, size=0x100, base=BASE, endian="little")
    table = s.entry(BASE, Reward, count(2), name="two")
    data = Reward(max_frames=1, pad=0, item_id=2).pack() + Reward(
        max_frames=3, pad=0, item_id=4
    ).pack()
    assert [r.max_frames for r in table.parse(data)] == [1, 3]
    with pytest.raises(ValueError, match="needs 16 bytes, got 8"):
        table.parse(data[:8])


def test_parse_refuses_an_extent_that_needs_the_buffer():
    s = Space(None, size=0x100, base=BASE, endian="little")
    e = s.entry(BASE, UInt8, until(0), name="scanned")
    with pytest.raises(ValueError, match="needs a length known up front"):
        e.parse(b"\x01\x02\x00")


def test_a_declaration_reads_real_bytes_by_binding_to_them():
    """A map declared against an address plane meets an image with one
    verb, and that verb serves every accessor -- not just read()."""
    plane = Space(None, size=0x400, base=BASE, endian="little", name="plane")
    rewards = plane.entry(BASE + 0x030, Reward, count(3), name="rewards")
    with pytest.raises(ValueError, match="geometry only"):
        rewards.read()
    got = rewards.bind(space()).read()  # the same declaration, real bytes
    assert [r.max_frames for r in got] == [14400, 18000, 21600]


def test_binding_keeps_a_fields_own_byte_order():
    s, _ = enemy_space()
    plane = Space(None, size=0x40, base=BASE, endian="little")
    ident = plane.entry(BASE, Enemy, count(1), name="e").field("ident")
    assert ident.bind(s).read() == 0xAABB  # big-endian field, honoured


def test_space_write_uses_the_in_place_path_for_records():
    buf = bytearray(32)
    s = Space(buf, base=BASE, endian="little")
    rec = Aligned(a=1, b=2)
    s.write(BASE + 4, rec)
    assert Aligned.parse_at(buf, 4) == rec
    assert bytes(buf[:4]) == b"\x00\x00\x00\x00"


# ------------------------------------------ the module's own examples (rom-17)
def test_the_module_docstrings_three_write_flows_actually_run():
    """The overview shows three ways to write, and picking between them is
    the point of the section. An example that has drifted from the code
    teaches the wrong one, so all three are executed here."""
    import bytemaker.rom as rom_pkg
    from test.conftest import docstring_example

    class EnemyDNA(Struct, endian="little"):
        hp: int = field(UInt16)
        soul_rate: int = field(UInt8)
        flags: int = field(UInt8)

    class Pickup(Struct, endian="little"):
        kind: int = field(UInt8)
        subtype: int = field(UInt8)
        item: int = field(UInt16)

    class Loc:
        def __init__(self, addr, item):
            self.addr, self.item = addr, item

    class Feature:
        """Reads the current state, then writes -- the pipeline shape."""

        def __init__(self, at):
            self.at = at

        def apply(self, work):
            work.write(self.at, work.read(self.at, UInt8) + 1, UInt8)

    data = bytearray(0xF0000)
    rate_at = 0xE9644 + 54 * 4 + 2  # enemies[54].soul_rate
    data[rate_at] = 32
    other = Patch(name="other")
    other.write(0x10, b"\x07", bytes(1))
    original = bytes(range(256))

    ns = {
        "Space": Space, "Patch": Patch, "count": count,
        "UInt8": UInt8, "UInt16": UInt16,
        "EnemyDNA": EnemyDNA, "Pickup": Pickup, "UInt32": UInt32,
        "data": bytes(data), "other_feature_patch": other,
        "locations": [Loc(0x08000100, 7), Loc(0x08000200, 9)],
        "original": original, "features": [Feature(BASE + 4), Feature(BASE + 8)],
    }
    for marker in ("rom = Space(data", "gba = Space(", "work = Space("):
        block = docstring_example(rom_pkg.__doc__, marker)
        exec(compile(block, f"<rom docstring: {marker}>", "exec"), ns)

    assert ns["ips"].startswith(b"PATCH")
    assert ns["tokens"] == {0x100: b"\x04\x02\x07\x00", 0x200: b"\x04\x02\x09\x00"}
    assert ns["p"].verifiable  # flow 3's diff knows the originals
    assert ns["p"].apply(original)[4] == 5 and ns["p"].apply(original)[8] == 9


# ------------------------------------------ alias codecs (rom-23)
def test_field_aliases_work_anywhere_a_codec_does():
    """`u16` and `UInt16` are two spellings of one scalar. The aliases are
    how records are declared, so they arrive at every codec boundary too --
    and used to fail three layers down with an Annotated compile error."""
    from bytemaker import u8 as u8_alias, u16 as u16_alias

    s = space()
    assert s.read(BASE + 0x200, u16_alias) == 0xABCD  # == the UInt16 read
    assert s.entry(BASE, u8_alias, count(4)).read() == [7, 6, 8, 9]
    assert Entry(BASE, u8_alias, count(4)).bind(s).read() == [7, 6, 8, 9]
    assert Array.of(u8_alias, 4).parse(bytes([1, 2, 3, 4])) == [1, 2, 3, 4]
    buf = bytearray(4)
    Space(buf, base=BASE, endian="little").write(BASE, 0xBEEF, u16_alias)
    assert bytes(buf[:2]) == b"\xef\xbe"


def test_end_makes_adjacency_a_one_liner():
    """Table clusters are checked by abutment: a.end == b.addr. Without
    .end, every such check hand-spells addr + capacity."""
    a = Entry(BASE, Reward, count(3), name="a")
    b = Entry(BASE + 24, Reward, count(2), name="b")
    assert a.end == b.addr and b.end == BASE + 40
    hook = Entry(BASE + 0x100, UInt8, unknown("blob"), reserve=0x20)
    assert hook.end == BASE + 0x120  # a reservation ends where its room does
    assert Entry(BASE, UInt8, unknown("?")).end is None


def test_a_buffer_codec_is_the_blob_reservation_spelling():
    """A pure reservation needs no meaningless scalar filler: a byte-payload
    codec sizes it, bounds writes, and reads back as bytes."""
    from bytemaker.bittypes import Buffer

    s = Space(bytearray(0x40), base=BASE, endian="little")
    hook = s.entry(BASE + 0x10, Buffer.of(nbytes=0x10), name="hook")
    hook.write(b"\xde\xad\xbe\xef")  # short blob fits
    assert hook.read()[:4] == b"\xde\xad\xbe\xef"
    with pytest.raises(ValueError, match="do not fit"):
        hook.write(b"\x00" * 0x11)
    assert hook.end == BASE + 0x20


# ------------------------------------ the mutating recorder (rom-25)
def relocation_fixture():
    """A vanilla table and a zero-filled destination -- the shape that
    exposed the diff hole, since a verbatim copy re-writes many zeros."""
    rom = bytearray(0x400)
    rom[0x100:0x110] = bytes([0, 0, 3, 0, 0, 0, 7, 0, 0, 0, 0, 0, 0, 0, 0, 9])
    return bytes(rom)


def test_a_recording_write_lands_and_is_recorded():
    pristine = relocation_fixture()
    work = bytearray(pristine)
    s = Space(work, base=BASE, endian="little")
    p = Patch(name="chain")
    rec = s.recording(p)
    rec.write(BASE + 0x200, bytes(work[0x100:0x110]))  # relocate the table
    assert bytes(work[0x200:0x210]) == pristine[0x100:0x110]  # landed
    assert p.apply(pristine) == bytes(work)                   # and recorded


def test_a_recording_write_claims_every_byte_it_wrote():
    """The bug this exists for: Patch.diff drops bytes written back to the
    value they already held, so a table relocated into zero-filled space
    loses its zeros -- and the patch then applies cleanly to an image that
    differs exactly there and produces the wrong bytes, silently."""
    pristine = relocation_fixture()
    table = pristine[0x100:0x110]
    work = bytearray(pristine)
    p = Patch(name="relocate")
    Space(work, base=BASE, endian="little").recording(p).write(BASE + 0x200, table)

    claimed = {e.offset + i for e in p.edits for i in range(e.size)}
    assert claimed == set(range(0x200, 0x210))  # all 16, zeros included
    assert Patch.diff(pristine, bytes(work)).byte_count < 16  # what diff loses

    # ...so it still lands correctly on an image whose free space is not zero
    variant = bytearray(pristine)
    variant[0x200:0x210] = b"\xff" * 16
    with pytest.raises(PatchVerifyError):
        p.apply(bytes(variant))  # loudly refuses rather than half-applying
    assert p.apply(pristine)[0x200:0x210] == table


def test_a_recorded_chain_stays_a_transition_from_the_pristine_image():
    """Each write records the intermediate state it replaced, but the
    earliest-known-original rule keeps the accumulation pristine-relative."""
    pristine = relocation_fixture()
    work = bytearray(pristine)
    p = Patch(name="two features")
    rec = Space(work, base=BASE, endian="little").recording(p)
    rec.write(BASE + 0x300, b"\x01\x02")   # feature 1
    rec.write(BASE + 0x300, b"\x03\x04")   # feature 2 overwrites it
    assert p.apply(pristine) == bytes(work)
    assert p.invert().apply(bytes(work)) == pristine  # undo goes all the way
    assert p.verifiable


def test_a_recording_space_lets_later_reads_see_earlier_writes():
    pristine = relocation_fixture()
    s = Space(bytearray(pristine), base=BASE, endian="little")
    rec = s.recording(Patch())
    rec.write(BASE + 0x300, 0x1234, UInt16)
    assert rec.read(BASE + 0x300, UInt16) == 0x1234  # the chain's whole need
    assert s.read(BASE + 0x300, UInt16) == 0x1234    # same bytes underneath


def test_recording_carries_through_entries_and_field_writes():
    """Feature bodies are written once: the pipeline decides by handing them
    a plain space or a recording one."""
    pristine = bytearray(0x40)
    Reward(max_frames=1, pad=0, item_id=2).pack_into(pristine, 0)
    work = bytearray(pristine)
    p = Patch()
    rec = Space(work, base=BASE, endian="little").recording(p)
    rec.entry(BASE, Reward, count(1), name="r").set(item_id=9)
    assert Reward.parse_at(work, 0).item_id == 9
    assert p.apply(bytes(pristine)) == bytes(work)


def test_recording_refuses_a_second_destination_and_an_unbacked_space():
    s = Space(bytearray(16), base=BASE, endian="little")
    rec = s.recording(Patch(name="mine"))
    with pytest.raises(ValueError, match="already records into"):
        rec.write(BASE, 1, UInt8, patch=Patch(name="other"))
    with pytest.raises(ValueError, match="nothing to mutate"):
        Space(None, size=16, base=BASE, endian="little").recording(Patch())
