"""bytemaker.spaces patch algebra: Edit, Patch, IPS export (rom-2)."""

import pytest

from bytemaker.bittypes import UInt16, UInt32
from bytemaker.spaces import (
    IPS_EOF_OFFSET,
    Edit,
    Patch,
    PatchConflict,
    PatchUnverifiable,
    PatchVerifyError,
    Space,
)
from bytemaker.structs import Struct, field

BASE = 0x08000000
ORIGINAL = bytes(range(16))


class Reward(Struct, endian="little"):
    frames: int = field(UInt16)
    pad: int = field(UInt16)
    item: int = field(UInt32)


def tiny():
    p = Patch(name="tiny")
    p.write(4, b"\xaa\xbb", b"\x04\x05")
    return p


# -------------------------------------------------------------------- Edit
def test_edit_requires_equal_lengths_and_content():
    e = Edit(4, b"\xaa\xbb", b"\x01\x02")
    assert e.size == 2 and e.end == 6 and not e.is_noop
    assert Edit(0, b"\x01", b"\x01").is_noop
    with pytest.raises(ValueError, match="replaces bytes in place"):
        Edit(0, b"\xaa\xbb", b"\x01")
    with pytest.raises(ValueError, match="empty"):
        Edit(0, b"", b"")
    with pytest.raises(ValueError, match="non-negative"):
        Edit(-1, b"\x02", b"\x01")


def test_edit_is_frozen():
    e = Edit(4, b"\x02", b"\x01")
    with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
        e.offset = 8


# ----------------------------------------------------------- apply / verify
def test_apply_returns_patched_bytes_and_leaves_the_source_alone():
    p = tiny()
    out = p.apply(ORIGINAL)
    assert out == b"\x00\x01\x02\x03\xaa\xbb" + ORIGINAL[6:]
    assert ORIGINAL == bytes(range(16))  # untouched


def test_apply_into_mutates_a_bytearray():
    buf = bytearray(ORIGINAL)
    tiny().apply_into(buf)
    assert bytes(buf[4:6]) == b"\xaa\xbb"


def test_apply_into_refuses_a_readonly_buffer():
    with pytest.raises(TypeError, match="writable buffer"):
        tiny().apply_into(memoryview(ORIGINAL))
    with pytest.raises(TypeError, match="writable buffer"):
        tiny().apply_into(ORIGINAL)


def test_verify_names_the_first_mismatching_offset():
    p = tiny()
    wrong = bytearray(ORIGINAL)
    wrong[4] = 0xFF
    with pytest.raises(PatchVerifyError, match=r"offset 4 \(0x4\) is 0xff"):
        p.apply(bytes(wrong))
    # the SECOND byte mismatching is reported at its own offset
    wrong = bytearray(ORIGINAL)
    wrong[5] = 0xFF
    with pytest.raises(PatchVerifyError, match=r"offset 5 \(0x5\)"):
        p.apply(bytes(wrong))


def test_verify_catches_an_already_applied_patch():
    p = tiny()
    once = p.apply(ORIGINAL)
    with pytest.raises(PatchVerifyError, match="already applied"):
        p.apply(once)


def test_verify_can_be_turned_off_and_says_so_in_the_signature():
    p = tiny()
    wrong = b"\xff" * 16
    assert p.apply(wrong, verify=False)[4:6] == b"\xaa\xbb"


def test_apply_bounds_are_checked_even_without_verify():
    p = Patch()
    p.write(100, b"\x02", b"\x01")
    with pytest.raises(PatchVerifyError, match="past the end"):
        p.apply(ORIGINAL)
    with pytest.raises(PatchVerifyError, match="past the end"):
        p.apply(ORIGINAL, verify=False)


# ------------------------------------------------------------------- invert
def test_invert_round_trips():
    p = tiny()
    patched = p.apply(ORIGINAL)
    assert p.invert().apply(patched) == ORIGINAL
    assert p.invert().invert() == p


def test_invert_of_a_resaved_patch_restores_the_pristine_bytes():
    """Later writes win, but the EARLIEST old is kept -- so undo goes all
    the way back, not one step."""
    p = Patch()
    p.write(4, b"\xaa", b"\x04")
    p.write(4, b"\xbb", b"\xaa")  # a second tweak of the same byte
    assert p.edits == (Edit(4, b"\xbb", b"\x04"),)
    assert p.invert().apply(p.apply(ORIGINAL)) == ORIGINAL


# ------------------------------------------------------------------ compose
def test_compose_merges_disjoint_patches():
    a, b = tiny(), Patch(name="other")
    b.write(8, b"\x99", b"\x08")
    both = a | b
    assert len(both) == 2 and both.name == "tiny | other"
    out = both.apply(ORIGINAL)
    assert out[4:6] == b"\xaa\xbb" and out[8] == 0x99
    assert both.invert().apply(out) == ORIGINAL


def test_compose_allows_agreement_and_rejects_disagreement():
    a = tiny()
    same = Patch()
    same.write(4, b"\xaa\xbb", b"\x04\x05")  # identical claim
    assert (a | same).edits == a.edits
    clash = Patch()
    clash.write(5, b"\x01", b"\x05")
    with pytest.raises(PatchConflict, match=r"offset 5 \(0x5\): 0xbb vs 0x01"):
        a | clash


def test_compose_reports_how_many_bytes_conflict():
    a = tiny()
    clash = Patch()
    clash.write(4, b"\x01\x02", b"\x04\x05")
    with pytest.raises(PatchConflict, match="2 bytes conflict"):
        a | clash


def test_compose_with_a_non_patch_is_a_type_error():
    with pytest.raises(TypeError):
        tiny() | 5


# ------------------------------------------------------------ the byte map
def test_adjacent_writes_coalesce_into_one_edit():
    p = Patch()
    p.write(4, b"\xaa", b"\x04")
    p.write(5, b"\xbb", b"\x05")
    p.write(6, b"\xcc", b"\x06")
    assert p.edits == (Edit(4, b"\xaa\xbb\xcc", b"\x04\x05\x06"),)
    p.write(8, b"\xdd", b"\x08")  # a gap -> a second run
    assert len(p.edits) == 2


def test_counts_and_predicates():
    p = Patch()
    p.write(4, b"\xaa\x05", b"\x04\x05")  # second byte is a no-op
    assert p.byte_count == 2 and p.changed_byte_count == 1
    assert p.touches(4) and p.touches(5) and not p.touches(6)
    assert bool(p) and not bool(Patch())
    assert len(Patch()) == 0 and Patch().edits == ()
    assert "2 bytes" in repr(p)


def test_write_validates_its_arguments():
    p = Patch()
    with pytest.raises(ValueError, match="replaces bytes in place"):
        p.write(0, b"\x02\x03", b"\x01")
    with pytest.raises(ValueError, match="non-negative"):
        p.write(-1, b"\x02", b"\x01")


def test_patch_can_be_built_from_edits():
    p = Patch([Edit(4, b"\xaa\xbb", b"\x04\x05")], name="tiny")
    assert p == tiny()


def test_summary_lists_edits_and_marks_noops():
    p = Patch(name="s")
    p.write(4, b"\xaa\x05", b"\x04\x05")
    text = p.summary()
    assert "1 edit(s), 1/2 bytes changed" in text
    assert "0x000004+2" in text and "0405 -> aa05" in text
    assert Patch().summary().endswith("empty")
    assert "(no-op)" in Patch([Edit(0, b"\x01", b"\x01")]).summary()


# ---------------------------------------------------------------- IPS export
def test_ips_golden_bytes():
    """Hand-computed: b'PATCH', then offset u24 BE + size u16 BE + data, then
    b'EOF'."""
    assert tiny().to_ips() == (
        b"PATCH" + b"\x00\x00\x04" + b"\x00\x02" + b"\xaa\xbb" + b"EOF"
    )


def test_ips_empty_patch_is_header_plus_terminator():
    assert Patch().to_ips() == b"PATCHEOF"


def test_ips_splits_records_larger_than_65535_bytes():
    size = 0x1_0000 + 5
    p = Patch()
    p.write(0, b"\xaa" * size, bytes(size))
    ips = p.to_ips()
    assert len(p.edits) == 1  # one logical edit...
    body = ips[5:-3]
    # ... two records: 0xFFFF bytes at offset 0, then the remainder
    assert body[0:3] == b"\x00\x00\x00" and body[3:5] == b"\xff\xff"
    rest = body[5 + 0xFFFF :]
    assert rest[0:3] == (0xFFFF).to_bytes(3, "big")
    assert rest[3:5] == (size - 0xFFFF).to_bytes(2, "big")
    assert len(rest[5:]) == size - 0xFFFF


def test_ips_rejects_offsets_past_16_mib():
    p = Patch()
    p.write(0x100_0000, b"\x02", b"\x01")
    with pytest.raises(ValueError, match="24-bit"):
        p.to_ips()


def test_ips_rejects_a_split_record_that_crosses_16_mib():
    """The first record fits under the 24-bit ceiling; the SECOND, at
    start + 0xFFFF, does not. The check has to be inside the split loop."""
    start = 0xFF0001  # start + 0xFFFF == 0x1000000, one past the ceiling
    p = Patch()
    p.write(start, b"\xaa" * 0x1_0010, bytes(0x1_0010))
    with pytest.raises(ValueError, match=r"offset 0x1000000 exceeds"):
        p.to_ips()


def test_ips_eof_offset_quirk_needs_the_buffer():
    """A record at offset 0x454F46 encodes as the ASCII bytes 'EOF', which
    naive readers treat as end-of-file."""
    p = Patch(name="q")
    p.write(IPS_EOF_OFFSET, b"\xaa\xbb", b"\x00\x00")
    assert IPS_EOF_OFFSET.to_bytes(3, "big") == b"EOF"
    with pytest.raises(ValueError, match="'EOF'"):
        p.to_ips()
    buf = bytearray(IPS_EOF_OFFSET + 8)
    buf[IPS_EOF_OFFSET - 1] = 0x77  # the byte the record borrows
    ips = p.to_ips(bytes(buf))
    body = ips[5:-3]
    assert body[0:3] == (IPS_EOF_OFFSET - 1).to_bytes(3, "big")
    assert body[3:5] == b"\x00\x03"
    assert body[5:8] == b"\x77\xaa\xbb"  # unchanged byte carried along
    assert b"EOF" not in ips[5:-3]


def test_ips_split_boundary_never_lands_on_the_eof_offset():
    """The edit's own offset is fine; the SECOND record, at offset + 0xFFFF,
    would encode as the ASCII bytes 'EOF' and truncate the patch for naive
    readers. The quirk check has to be inside the split loop -- and needs no
    buffer, since the byte it borrows belongs to the same edit."""
    start = IPS_EOF_OFFSET - 0xFFFF  # the second record starts on the quirk
    p = Patch(name="split")
    p.write(start, b"\xaa" * 0x1_0005, bytes(0x1_0005))
    ips = p.to_ips()  # no buf needed
    body = ips[5:-3]
    assert b"EOF" not in body
    second = body[5 + 0xFFFF :]
    assert second[0:3] == (IPS_EOF_OFFSET - 1).to_bytes(3, "big")
    # the borrowed byte is this edit's own, so the record still writes 0xaa
    assert second[5:6] == b"\xaa"
    # every byte of the edit still lands where it belongs
    assert p.apply(bytes(0x50_0000)) == _ips_applied(ips, bytes(0x50_0000))


def _ips_applied(ips: bytes, buf: bytes) -> bytes:
    """Minimal IPS reader: apply `ips` to `buf` the way a patcher would."""
    out, i = bytearray(buf), 5
    while ips[i : i + 3] != b"EOF":
        at = int.from_bytes(ips[i : i + 3], "big")
        size = int.from_bytes(ips[i + 3 : i + 5], "big")
        out[at : at + size] = ips[i + 5 : i + 5 + size]
        i += 5 + size
    return bytes(out)


def test_ips_offset_next_to_the_eof_quirk_is_untouched():
    p = Patch()
    p.write(IPS_EOF_OFFSET - 1, b"\xaa", b"\x00")
    body = p.to_ips()[5:-3]
    assert body[0:3] == (IPS_EOF_OFFSET - 1).to_bytes(3, "big")
    p2 = Patch()
    p2.write(IPS_EOF_OFFSET + 1, b"\xaa", b"\x00")
    body2 = p2.to_ips()[5:-3]
    assert body2[0:3] == (IPS_EOF_OFFSET + 1).to_bytes(3, "big")


# ------------------------------------------------- blind edits (rom-12)
def test_a_blind_write_applies_but_is_not_verifiable():
    """Writes built before the target image exists have no original bytes to
    record -- the generation-time half of a randomizer pipeline."""
    p = Patch(name="tokens")
    p.write(4, b"\xaa\xbb")
    assert not p.verifiable
    assert p.edits == (Edit(4, b"\xaa\xbb"),)
    assert p.edits[0].is_blind and not p.edits[0].is_noop
    assert p.apply(ORIGINAL)[4:6] == b"\xaa\xbb"  # applies to anything
    assert p.to_ips().startswith(b"PATCH")


def test_invert_and_guards_refuse_a_blind_patch_by_offset():
    p = Patch(name="tokens")
    p.write(4, b"\xaa")
    p.write(9, b"\xcc")
    with pytest.raises(PatchUnverifiable, match=r"invert\(\).*0x4, 0x9"):
        p.invert()
    with pytest.raises(PatchUnverifiable, match=r"guards\(\)"):
        p.guards()  # refuses when asked, not when iterated


def test_guards_hand_back_the_compare_and_swap_triples():
    p = Patch()
    p.write(4, b"\xaa\xbb", b"\x04\x05")
    p.write(9, b"\xcc", b"\x09")
    assert list(p.guards()) == [(4, b"\x04\x05", b"\xaa\xbb"), (9, b"\x09", b"\xcc")]


def test_a_known_original_upgrades_a_blind_byte():
    p = Patch()
    p.write(4, b"\xaa")
    assert not p.verifiable
    p.write(4, b"\xbb", b"\x04")
    assert p.verifiable and p.edits == (Edit(4, b"\xbb", b"\x04"),)


def test_edits_never_mix_known_and_blind_bytes():
    p = Patch()
    p.write(4, b"\xaa", b"\x04")
    p.write(5, b"\xbb")  # contiguous, but nothing known about it
    assert p.edits == (Edit(4, b"\xaa", b"\x04"), Edit(5, b"\xbb"))


def test_summary_marks_the_blind_bytes():
    p = Patch(name="tokens")
    p.write(4, b"\xaa\xbb")
    head, line = p.summary().splitlines()
    assert "2 blind" in head
    assert "???? -> aabb" in line  # two bytes of unknown original


def test_verify_skips_blind_bytes_but_still_checks_the_known_ones():
    p = Patch()
    p.write(4, b"\xaa")
    p.write(9, b"\xcc", b"\x09")
    assert p.apply(ORIGINAL)[4] == 0xAA
    wrong = bytearray(ORIGINAL)
    wrong[9] = 0x77
    with pytest.raises(PatchVerifyError, match="offset 9"):
        p.apply(bytes(wrong))


# ------------------------------------------------------- diff (rom-12)
def test_diff_recovers_a_patch_from_a_mutated_working_copy():
    """The artifact for a build that edits a working copy in place, where
    each step reads what the previous ones left."""
    work = bytearray(ORIGINAL)
    work[4:6] = b"\xaa\xbb"
    work[9] = 0xCC
    p = Patch.diff(ORIGINAL, work, name="all features")
    assert p.verifiable and p.byte_count == 3
    assert p.edits == (Edit(4, b"\xaa\xbb", b"\x04\x05"), Edit(9, b"\xcc", b"\x09"))
    assert p.apply(ORIGINAL) == bytes(work)
    assert p.invert().apply(bytes(work)) == ORIGINAL


def test_diff_of_identical_buffers_is_empty():
    assert not Patch.diff(ORIGINAL, ORIGINAL)


def test_diff_refuses_a_length_change():
    with pytest.raises(ValueError, match="replaces bytes in place"):
        Patch.diff(ORIGINAL, ORIGINAL + b"\x00")


def test_save_ips_writes_the_file(tmp_path):
    dest = tmp_path / "fix.ips"
    n = tiny().save_ips(dest)
    assert dest.read_bytes() == tiny().to_ips() and n == len(dest.read_bytes())


# --------------------------------------------------- Space.write(patch=...)
def test_space_write_with_a_patch_records_and_does_not_mutate():
    buf = bytearray(ORIGINAL)
    s = Space(buf, base=BASE, endian="little")
    p = Patch(name="via space")
    s.write(BASE + 4, 0xBBAA, UInt16, patch=p)
    assert bytes(buf) == ORIGINAL  # untouched
    assert p.edits == (Edit(4, b"\xaa\xbb", b"\x04\x05"),)
    assert p.apply(buf)[4:6] == b"\xaa\xbb"


def test_space_write_with_a_patch_works_on_a_readonly_space():
    s = Space(ORIGINAL, base=BASE, endian="little")  # bytes, not bytearray
    p = Patch()
    s.write(BASE + 4, 0xBBAA, UInt16, patch=p)  # no TypeError
    assert p.apply(ORIGINAL)[4:6] == b"\xaa\xbb"


def test_patch_a_record_field_end_to_end():
    """The realistic flow: read a record, change one field, record the edit,
    export, and prove the undo."""
    original = bytearray(32)
    rec = Reward(frames=14400, pad=0, item=91)
    rec.pack_into(original, 8)
    frozen = bytes(original)

    s = Space(frozen, base=BASE, endian="little", name="ROM")
    p = Patch(name="reward 91 -> 42")
    edited = s.read(BASE + 8, Reward)
    edited.item = 42
    s.write(BASE + 8, edited, patch=p)

    assert p.changed_byte_count == 1  # only the low byte of item changed
    patched = p.apply(frozen)
    assert Space(patched, base=BASE, endian="little").read(BASE + 8, Reward).item == 42
    assert p.invert().apply(patched) == frozen
    assert p.to_ips().startswith(b"PATCH") and p.to_ips().endswith(b"EOF")


def _one_reward(frames=14400, item=90):
    buf = bytearray(16)
    Reward(frames=frames, pad=0, item=item).pack_into(buf, 0)
    return bytes(buf)


def test_two_patches_on_one_record_but_different_fields_compose():
    """A whole-record write used to claim the fields it did not touch, so two
    features editing one record 'disagreed' about bytes neither changed."""
    frozen = _one_reward()
    s = Space(frozen, base=BASE, endian="little")

    faster, richer = Patch(name="faster"), Patch(name="richer")
    r = s.read(BASE, Reward)
    r.frames = 7200
    s.write(BASE, r, patch=faster)
    r = s.read(BASE, Reward)
    r.item = 91
    s.write(BASE, r, patch=richer)

    assert (faster.byte_count, richer.byte_count) == (2, 1)  # not 8 and 8
    out = Space((faster | richer).apply(frozen), base=BASE, endian="little")
    assert out.read(BASE, Reward) == Reward(frames=7200, pad=0, item=91)


def test_read_modify_write_through_a_patch_keeps_the_earlier_edit():
    """Reads never see pending edits, so the second read returns pristine
    bytes. Claiming only what changed is what stops the second write from
    stamping the first edit back to that pristine value."""
    frozen = _one_reward()
    s = Space(frozen, base=BASE, endian="little")

    p = Patch(name="rmw")
    r = s.read(BASE, Reward)
    r.frames = 1
    s.write(BASE, r, patch=p)

    again = s.read(BASE, Reward)
    assert again.frames == 14400  # pristine: the buffer was never touched
    again.item = 9
    s.write(BASE, again, patch=p)

    out = Space(p.apply(frozen), base=BASE, endian="little")
    assert out.read(BASE, Reward) == Reward(frames=1, pad=0, item=9)


def test_a_recorded_write_that_changes_nothing_claims_nothing():
    frozen = _one_reward()
    s = Space(frozen, base=BASE, endian="little")
    p = Patch()
    s.write(BASE, s.read(BASE, Reward), patch=p)
    assert not p and p.byte_count == 0 and p.edits == ()


def test_two_independent_field_patches_compose():
    original = bytearray(32)
    Reward(frames=1, pad=0, item=2).pack_into(original, 0)
    Reward(frames=3, pad=0, item=4).pack_into(original, 8)
    frozen = bytes(original)
    s = Space(frozen, base=BASE, endian="little")

    first, second = Patch(name="a"), Patch(name="b")
    r0 = s.read(BASE, Reward)
    r0.item = 20
    s.write(BASE, r0, patch=first)
    r1 = s.read(BASE + 8, Reward)
    r1.item = 40
    s.write(BASE + 8, r1, patch=second)

    out = (first | second).apply(frozen)
    later = Space(out, base=BASE, endian="little")
    assert [later.read(BASE, Reward).item, later.read(BASE + 8, Reward).item] == [
        20,
        40,
    ]
