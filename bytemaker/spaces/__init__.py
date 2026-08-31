"""Map a binary image as an address space: :class:`Space`, extents, :class:`Entry`.

A :class:`Struct` says what a record looks like. It says nothing about
*where* records live, how many there are, or how to get at them. Every
project that maps a binary image therefore rewrites the same three things:
subtract the base address, slice, and decide how the table ends. Each of
those is easy to get subtly wrong.

:class:`Space` is that layer, declared once::

    from bytemaker.spaces import Space, count, until, through

    rom = Space(open("game.gba", "rb").read(), base=0x08000000,
                endian="little", name="AoS")

    palette = rom.read(0x080E1CD0, UInt8, count(4))     # [7, 6, 8, 9]
    rewards = rom.read(0x08526390, BossRushReward, 3)   # 3 records
    rooms   = rom.read(0x0850E968, ThumbPtr, until(0))  # scan to the 0 entry

Three ideas define the layer:

* **The space supplies the byte order.** ``endian`` is a required keyword
  on :class:`Space`, so a scalar read never guesses and no declaration
  repeats it. Composite codecs always carry their own byte order, both
  :class:`~bytemaker.structs.Struct` classes and
  :class:`~bytemaker.structs.Array` objects.
* **Extents are values, not conventions.** ``count(n)``,
  ``until(sentinel)``, ``through(last_addr)`` and ``unknown()`` cover the
  four things anyone actually knows about a table's length. A table's
  length is then part of its declaration rather than a comment beside it.
* **An :class:`Entry` is a declaration, not a reader.** An entry can be
  written with no buffer at all and bound to a :class:`Space` later with
  :meth:`Entry.bind`, so a map module stays importable without the ROM.

Sub-byte codecs are refused, because a byte address has no room for a
4-bit stride. Wrap them in a Struct and map that instead, since the plan
engine packs sub-byte fields properly.

Two layers build on that base:

* :class:`Patch` and :class:`Edit` make an edit a value.
  ``space.write(..., patch=p)`` records the edit instead of mutating, so
  the edits can be verified against the original bytes, inverted, composed,
  and exported as IPS.
* :class:`Ptr` is a typed address. It decodes to a :class:`PtrValue`, an
  integer address that retains its adapter and provides ``deref(space)``.
* :meth:`Space.coverage` reports on the map as a whole: what it accounts
  for, what it double-claims, and which addresses its pointers resolve to.
  Wherever a pointer declares its pointee, the report also verifies the
  record type and the alignment of that address.
  :meth:`CoverageReport.gaps` lists what the map leaves unaccounted for,
  which is where the map has room to grow.

Writing comes in three shapes, and they are not interchangeable. Choosing
the wrong one is the mistake this layer is built to prevent.

**1. Edit an image you have.** Read, change, record. The patch claims only
the bytes that differ, so two features editing different fields of one
record still compose::

    rom = Space(data, base=0x08000000, endian="little")
    p = Patch(name="drop rates")
    enemies = rom.entry(0x080E9644, EnemyDNA, count(113), name="enemies")
    enemies.item(54).field("soul_rate").write(5, expect=32, patch=p)
    combined = p | other_feature_patch      # PatchConflict if they disagree
    ips = combined.to_ips()                 # or combined.save_ips(path)

**2. Build writes for an image you do not have.** This is the generation
half of a randomizer, where the addresses are known but the bytes are not.
A geometry-only space gives the address math with nothing behind it, so the
edits are *blind*. They apply to whatever image the player supplies, and
they cannot be inverted::

    gba = Space(None, size=0x800000, base=0x08000000, endian="little")
    p = Patch(name="item placement")
    for loc in locations:
        gba.entry(loc.addr, Pickup).set(p, kind=4, subtype=2, item=loc.item)
    tokens = {e.offset: e.new for e in p.edits}      # offset -> bytes

**3. Run a pipeline of features over a working copy.** Each step has to see
what the previous ones did, so record *alongside* the mutation rather than
instead of it. Every write lands in the buffer where later features read it,
and every write is captured as it happens::

    work = Space(bytearray(original), base=0x08000000, endian="little")
    p = Patch(name="all features")
    rec = work.recording(p)
    for feature in features:
        feature.apply(rec)                  # each reads the current state
    assert p.apply(original) == work.buf    # p is still pristine-relative

Rebuilding the patch afterwards with ``Patch.diff(original, work.buf)``
also works, and it is the only option when a feature mutates the buffer by
other means. It is strictly weaker, though. It costs a scan of the whole
image, and it **drops every byte written back to the value it already
held**. For a table relocated into zero-filled free space, that can be most
of the table. The resulting patch then applies cleanly to an image that
differs at exactly those bytes. :meth:`Space.recording` claims the whole
span written, so prefer it.

For a live target, the bytes come from a transport the caller owns::

    ewram = Space(None, size=0x40000, base=0x02000000, endian="little")
    vitals = ewram.entry(0x0201327A, PlayerVitals, name="vitals")
    off, size = vitals.request()                     # (0x1327A, 8)
    v = vitals.parse(await conn.read_many([(off, size, "EWRAM")]))
    for at, expected, new in one_field_patch.guards():
        await conn.guarded_write(at, list(new), list(expected), "EWRAM")

The layer is four modules, all re-exported here. Import from
``bytemaker.spaces`` and the split stays an implementation detail:

* :mod:`~bytemaker.spaces.spaces` — :class:`Space`, the extents, :class:`Entry`
* :mod:`~bytemaker.spaces.patches` — :class:`Edit`, :class:`Patch`, IPS export
* :mod:`~bytemaker.spaces.pointers` — :class:`Ptr`, :class:`PtrValue`
* :mod:`~bytemaker.spaces.coverage` — :class:`CoverageReport` and its parts
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
    through,
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
    "through",
    "unknown",
    "until",
]
