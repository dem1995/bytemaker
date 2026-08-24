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
    assert s.scan(BASE + 0x100, ThumbPtr) == [0x08000000]
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


def test_space_bind_binds_a_whole_map():
    rom_map = [
        Entry(BASE, UInt8, count(4), name="palette"),
        Entry(BASE + 0x030, Reward, count(3), name="rewards"),
    ]
    bound = space().bind(rom_map)
    assert [e.name for e in bound] == ["palette", "rewards"]
    assert bound[0].read() == [7, 6, 8, 9]
    assert len(bound[1].read()) == 3


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
    with pytest.raises(ValueError, match="do not fit the 24 declared"):
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


def test_space_write_uses_the_in_place_path_for_records():
    buf = bytearray(32)
    s = Space(buf, base=BASE, endian="little")
    rec = Aligned(a=1, b=2)
    s.write(BASE + 4, rec)
    assert Aligned.parse_at(buf, 4) == rec
    assert bytes(buf[:4]) == b"\x00\x00\x00\x00"
