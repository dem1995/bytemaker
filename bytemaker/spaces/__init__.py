"""Map a binary image as an address space: :class:`Space`, extents, :class:`Entry`.

A :class:`Struct` says what a record looks like. It says nothing about
*where* records live, how many there are, or how to get at them. Every
project that maps a binary image therefore rewrites the same three things:
subtract the base address, slice, and decide how the table ends. Each of
those is easy to get subtly wrong. This layer is that code, written once.

The core is small. A :class:`Space` is the bytes at a base address, and it
owns the byte order, so a scalar read never guesses. An extent says
how far a table runs, as a value rather than a comment: ``count(n)``,
``until(sentinel)``, or ``through(last_addr)``. An :class:`Entry` names
one mapped thing. Declare entries in a map module, bind them to bytes at
load time, and read or write through them::

    from bytemaker.spaces import Entry, Patch, Space, count, until, through

    ENEMIES = Entry(0x080E9644, EnemyDNA, count(113), name="enemies")

    rom = Space(data, base=0x08000000, endian="little", name="AoS")
    palette = rom.read(0x080E1CD0, UInt8, 4)      # a quick look, no entry

    enemies = ENEMIES.bind(rom)
    weakest = enemies.item(54).read()

    p = Patch(name="drop rates")
    enemies.item(54).field("soul_rate").write(5, expect=32, patch=p)
    patched = p.apply(data)                       # or p | other, p.to_ips()

``write(..., patch=p)`` records the edit instead of mutating, and it
claims only the bytes that actually change, so two features editing
different fields of one record still compose under ``|``
(``PatchConflict`` when they disagree). ``expect=`` states what the target
must currently hold; the write, or the patch's later apply, fails when
it does not, which is what catches a wrong build or a moved table.

Which spelling, when:

* **A quick look at one address.** ``space.read(addr, codec, extent)``,
  with no declaration needed. ``space.write(addr, value)`` mutates in place.
* **A thing worth naming.** An :class:`Entry` in a map module. It is a
  declaration, not a reader: it can be written with no buffer at all and
  bound later with :meth:`Entry.bind`, so the map stays importable without
  the binary. ``entry.item(i)`` is one row and ``entry.field(name)`` one
  field, both addressed from the compiled layout rather than by hand
  arithmetic.
* **A change you intend to ship.** Pass ``patch=`` on any write. A
  :class:`Patch` is a value: verify it, invert it, compose it with ``|``,
  export it with :meth:`Patch.to_ips`.

Sub-byte codecs are refused, because a byte address has no room for a
4-bit stride. Wrap them in a Struct and map that instead, since the plan
engine packs sub-byte fields properly.

**Beyond the core.** Reach for these when the task calls for them:

* **An image you do not have yet.** ``Space(None, size=..., base=...,
  endian=...)`` is the same address plane with no bytes behind it, which
  is the generation half of a randomizer. Writes must state ``patch=`` (there is
  nothing to mutate) and the edits are *blind*: they apply to whatever
  image the player supplies, and they cannot be inverted.
* **A live target.** The library never performs I/O. ``entry.request()``
  returns the ``(offset, nbytes)`` a transport needs, ``entry.parse(data)``
  decodes the bytes it fetched, ``entry.pack(value)`` encodes for a
  guarded write, and ``patch.guards()`` yields compare-and-swap triples.
* **A pipeline over a working copy.** :meth:`Space.recording` returns a
  view whose writes land in the buffer AND are recorded, so each feature
  reads what earlier ones wrote while the patch stays pristine-relative.
  Unlike rebuilding the record with :meth:`Patch.diff`, it claims bytes
  written back to the value they already held, which is the difference
  between a patch that verifies on a variant base and one that
  corrupts it silently.
* **Auditing the map.** :meth:`Space.coverage` reports what the map
  accounts for, what it double-claims, and where every declared
  :class:`Ptr` lands, verifying record type and alignment wherever a
  pointer declares its pointee. :meth:`CoverageReport.gaps` lists what is
  left, which is where the map grows next. An entry whose length nobody
  knows yet is declared ``unknown(note)``: it still documents its address
  and shape, and the report lists it as unresolved rather than skipping it.
* **Typed addresses.** :class:`Ptr` decodes to a :class:`PtrValue`, an int
  that kept its adapter: ``value.deref(space)`` reads the pointee with the
  codec the schema declared, and ``space.deref(record, Record.field)``
  follows a record's pointer field.

The layer is six modules, all re-exported here. Import from
``bytemaker.spaces`` and the split stays an implementation detail:

* :mod:`~bytemaker.spaces.spaces`: :class:`Space` itself
* :mod:`~bytemaker.spaces.extents`: ``count``, ``until``, ``through``, ``unknown``
* :mod:`~bytemaker.spaces.entry`: :class:`Entry`, the declarations
* :mod:`~bytemaker.spaces.patches`: :class:`Edit`, :class:`Patch`, IPS export
* :mod:`~bytemaker.spaces.pointers`: :class:`Ptr`, :class:`PtrValue`
* :mod:`~bytemaker.spaces.coverage`: :class:`CoverageReport` and its parts
"""

from .coverage import CoverageReport, Gap, Overlap, PointerRef, Region
from .entry import Entry, FetchRequest
from .extents import Extent, count, through, unknown, until
from .patches import (
    IPS_EOF_OFFSET,
    Edit,
    Patch,
    PatchConflict,
    PatchUnverifiable,
    PatchVerifyError,
)
from .pointers import Ptr, PtrAdapter, PtrValue
from .spaces import AddressError, Space

__all__ = [
    "AddressError",
    "CoverageReport",
    "Edit",
    "Entry",
    "Extent",
    "FetchRequest",
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
