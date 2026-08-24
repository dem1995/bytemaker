"""Map a binary image as an address space: :class:`Space`, extents, :class:`Entry`.

A :class:`Struct` says what a record looks like, but nothing about *where*
records live, how many there are, or how to get at them, so every project
that maps a binary (a GBA ROM, a save file, a firmware image) reinvents the
same three things: subtract the base address, slice, and decide how the
table ends. The reinvention is where the bugs are.

:class:`Space` is that layer, declared once::

    from bytemaker.rom import Space, count, until, span

    rom = Space(open("game.gba", "rb").read(), base=0x08000000,
                endian="little", name="AoS")

    palette = rom.read(0x080E1CD0, UInt8, count(4))     # [7, 6, 8, 9]
    rewards = rom.read(0x08526390, BossRushReward, 3)   # 3 records
    rooms   = rom.read(0x0850E968, ThumbPtr, until(0))  # scan to the 0 entry

Three ideas carry the module:

* **The space owns the byte order.** ``endian`` is a required keyword on
  :class:`Space`, so scalar reads never guess and no declaration repeats it,
  while composite codecs (:class:`~bytemaker.structs.Struct` classes,
  :class:`~bytemaker.structs.Array` objects) always carry their own.
* **Extents are values, not conventions.** ``count(n)``, ``until(sentinel)``,
  ``span(end_addr)`` and ``unknown()`` are the four things anyone actually
  knows about a table's length, so "how long is it" stops being a comment.
* **An :class:`Entry` is a declaration, not a reader.** An entry can be
  written with no buffer at all and bound to a :class:`Space` later with
  :meth:`Entry.bind`, so a map module stays importable without the ROM.

Sub-byte codecs are refused, because a byte address has no room for a 4-bit
stride. Wrap them in a Struct — the plan engine packs them properly — and
map that.

Two layers build on that base:

* :class:`Patch` / :class:`Edit` — edits as a value. ``space.write(...,
  patch=p)`` records instead of mutating, so the edits can be verified
  against the original bytes, inverted, composed, and exported as IPS.
* :class:`Ptr` and :meth:`Space.coverage` — a typed address plus a report on
  the map as a whole. A ``Ptr`` decodes to a :class:`PtrValue`, an int that
  can ``.deref(space)`` itself, while the report says what a map accounts
  for, what it leaves unaccounted for (:meth:`CoverageReport.gaps`, the
  direction a map grows in), what it double-claims, and where its pointers
  land — verified for record type and alignment wherever a pointer declares
  its pointee.

Writing comes in three shapes, and picking the wrong one is the mistake
this layer exists to prevent.

**1. Edit an image you have.** Read, change, record. The patch claims only
the bytes that differ, so two features editing different fields of one
record still compose::

    rom = Space(data, base=0x08000000, endian="little")
    p = Patch(name="drop rates")
    enemies = rom.entry(0x080E9644, EnemyDNA, count(113), name="enemies")
    enemies.item(54).field("soul_rate").write(5, expect=32, patch=p)
    combined = p | other_feature_patch      # PatchConflict if they disagree
    ips = combined.to_ips()                 # or combined.save_ips(path)

**2. Build writes for an image you do not have.** The generation half of a
randomizer: addresses are known, bytes are not. A geometry-only space gives
the address math with nothing behind it, so the edits are *blind* — they
apply to whatever the player supplies, and they refuse to be inverted::

    gba = Space(None, size=0x800000, base=0x08000000, endian="little")
    p = Patch(name="item placement")
    for loc in locations:
        gba.entry(loc.addr, Pickup).set(p, kind=4, subtype=2, item=loc.item)
    tokens = {e.offset: e.new for e in p.edits}      # offset -> bytes

**3. Run a pipeline of features over a working copy.** When each step must
see what the previous ones did, record *alongside* the mutation: writes land
in the buffer, so later features read them, and each one is captured as it
happens::

    work = Space(bytearray(original), base=0x08000000, endian="little")
    p = Patch(name="all features")
    rec = work.recording(p)
    for feature in features:
        feature.apply(rec)                  # each reads the current state
    assert p.apply(original) == work.buf    # p is still pristine-relative

Rebuilding the patch afterwards with ``Patch.diff(original, work.buf)`` also
works, and is the only option when a feature mutates the buffer by other
means, but it is strictly weaker. It costs a scan of the whole image, and it
**drops every byte written back to the value it already held**, which for a
table relocated into zero-filled free space can be most of it — the result
then applies without complaint to an image that differs exactly there.
:meth:`Space.recording` claims the whole span written, so prefer it.

For a live target, the bytes come from a transport the caller owns::

    ewram = Space(None, size=0x40000, base=0x02000000, endian="little")
    vitals = ewram.entry(0x0201327A, PlayerVitals, name="vitals")
    off, size = vitals.request()                     # (0x1327A, 8)
    v = vitals.parse(await conn.read_many([(off, size, "EWRAM")]))
    for at, expected, new in one_field_patch.guards():
        await conn.guarded_write(at, list(new), list(expected), "EWRAM")

The layer is four modules, re-exported here — import from
``bytemaker.rom`` and the split stays an implementation detail:

* :mod:`~bytemaker.rom.spaces` — :class:`Space`, the extents, :class:`Entry`
* :mod:`~bytemaker.rom.patches` — :class:`Edit`, :class:`Patch`, IPS export
* :mod:`~bytemaker.rom.pointers` — :class:`Ptr`, :class:`PtrValue`
* :mod:`~bytemaker.rom.coverage` — :class:`CoverageReport` and its parts
"""

from .coverage import CoverageReport, Gap, Overlap, PointerRef, Region
from .patches import (
    IPS_EOF_OFFSET,
    Edit,
    Patch,
    PatchConflict,
    PatchUnverifiable,
    PatchVerifyError,
)
from .pointers import Ptr, PtrAdapter, PtrValue
from .spaces import (
    AddressError,
    Entry,
    Extent,
    Space,
    count,
    span,
    unknown,
    until,
)

__all__ = [
    "AddressError",
    "CoverageReport",
    "Edit",
    "Entry",
    "Extent",
    "Gap",
    "IPS_EOF_OFFSET",
    "Overlap",
    "Patch",
    "PatchConflict",
    "PatchUnverifiable",
    "PatchVerifyError",
    "PointerRef",
    "Ptr",
    "PtrAdapter",
    "PtrValue",
    "Region",
    "Space",
    "count",
    "span",
    "unknown",
    "until",
]
