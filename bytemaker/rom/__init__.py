"""Mapping a base-mapped address space: :class:`Space`, extents, :class:`Entry`.

A :class:`Struct` says what a record looks like. It says nothing about
*where* records live, how many there are, or how to get at them — so every
project that maps a binary (a GBA ROM, a save file, a firmware image)
reinvents the same three things: subtract the base address, slice, and
decide how the table ends. The reinvention is where the bugs are.

:class:`Space` is that layer, declared once::

    from bytemaker.rom import Space, count, until, span

    rom = Space(open("game.gba", "rb").read(), base=0x08000000,
                endian="little", name="AoS")

    palette = rom.read(0x080E1CD0, UInt8, count(4))     # [7, 6, 8, 9]
    rewards = rom.read(0x08526390, BossRushReward, 3)   # 3 records
    rooms   = rom.read(0x0850E968, ThumbPtr, until(0))  # scan to the 0 entry

Three ideas carry the module:

* **The space owns the byte order.** ``endian`` is a required keyword on
  :class:`Space`, so scalar reads never guess and no declaration repeats it.
  Composite codecs (:class:`~bytemaker.structs.Struct` classes,
  :class:`~bytemaker.structs.Array` objects) always carry their own.
* **Extents are values, not conventions.** ``count(n)``, ``until(sentinel)``,
  ``span(end_addr)`` and ``unknown()`` are the four things anyone actually
  knows about a table's length, so "how long is it" stops being a comment.
* **An :class:`Entry` is a declaration, not a reader.** Entries can be
  written with no buffer at all — a map module stays importable without the
  ROM — and bound to a :class:`Space` later with :meth:`Entry.bind`.

Sub-byte codecs are refused: a byte address has no room for a 4-bit stride.
Wrap those in a Struct (the plan engine packs them properly) and map that.

Two layers build on that base:

* :class:`Patch` / :class:`Edit` — edits as a value. ``space.write(...,
  patch=p)`` records instead of mutating, so the edits can be verified
  against the original bytes, inverted, composed, and exported as IPS.
* :class:`Ptr` and :meth:`Space.coverage` — a typed address (decoding to a
  :class:`PtrValue`, an int that can ``.deref(space)`` itself) plus a report
  of what a map accounts for, what it leaves unaccounted for
  (:meth:`CoverageReport.gaps`, the direction a map grows in), what it
  double-claims, and where its pointers land — verified for record type and
  alignment where a pointer declares its pointee.

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
