"""What a map accounts for: :class:`CoverageReport` and its parts.

These are the value types a coverage audit produces: resolved
:class:`Region` footprints, :class:`Overlap` pairs, unclaimed :class:`Gap`
runs, and :class:`PointerRef` classifications.

:meth:`Space.coverage` builds them, by delegating to
:func:`compute_coverage` at the bottom of this module. The value types
hold no buffer and no space of their own.
"""

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from bytemaker.introspect import fields_of
from bytemaker.structs import StructMeta
from bytemaker.typing_redirect import Any, List, Optional, Tuple

from .extents import unknown
from .pointers import _checkable_target, _ptr_adapter_of

if TYPE_CHECKING:
    from .entry import Entry


@dataclass(frozen=True)
class Region:
    """One entry's resolved footprint in a coverage report."""

    entry: "Entry"
    size: Optional[int]
    error: Optional[str] = None

    @property
    def name(self) -> str:
        return self.entry.name or f"0x{self.entry.addr:08X}"

    @property
    def start(self) -> int:
        return self.entry.addr

    @property
    def end(self) -> Optional[int]:
        """One past the last claimed address, or None when unresolved."""
        return None if self.size is None else self.entry.addr + self.size

    @property
    def resolved(self) -> bool:
        return self.size is not None


@dataclass(frozen=True)
class Overlap:
    """Two entries claiming the same bytes, which usually means a wrong
    count."""

    a: str
    b: str
    start: int
    size: int


@dataclass(frozen=True)
class Gap:
    """A run of bytes that no resolved entry claims.

    Gaps are the complement of the bytes a report claims. They answer the
    two questions a mapping session actually has: what is still
    undescribed, and where the largest unmapped run sits.
    """

    start: int
    size: int

    @property
    def end(self) -> int:
        """One past the last unclaimed address."""
        return self.start + self.size

    def describe(self) -> str:
        return f"0x{self.start:08X}-0x{self.end - 1:08X} ({self.size} bytes)"


def _enumerate_values(value):
    """Return ``(index, one)`` pairs for a scalar, a list, or None.

    This normalizes the three shapes a Ptr-carrying read can produce.
    """
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(enumerate(value))
    return ((None, value),)


def _overlaps(regions) -> tuple:
    """Return every pair of resolved regions that claims the same bytes.

    The sweep runs in start order, so an entry overlapping three others
    reports three pairs rather than a single vague one.
    """
    live = sorted(
        (r for r in regions if r.resolved and r.size),
        key=lambda r: (r.start, r.end),
    )
    out = []
    for i, a in enumerate(live):
        for b in live[i + 1 :]:
            if b.start >= a.end:
                break  # sorted by start: nothing later can overlap a either
            shared = min(a.end, b.end) - b.start
            if shared > 0:
                out.append(Overlap(a.name, b.name, b.start, shared))
    return tuple(out)


@dataclass(frozen=True)
class PointerRef:
    """One decoded pointer, classified against the map."""

    source: str  #: the entry's name
    field: Optional[str]  #: record field, or None for a bare pointer table
    #: Position: None for a lone pointer, an int for a flat table, and
    #: ``(record, element)`` for a pointer array field inside a record.
    index: Any
    value: int
    #: One of "claimed", "unclaimed", "outside", or "null". A pointer that
    #: declares a record target can also get one of two verified-defect
    #: verdicts. "mistargeted" means it lands in a region mapped as a
    #: different record type. "misaligned" means the record type is right
    #: but the address is off a record boundary.
    verdict: str
    claimed_by: Optional[str] = None

    @property
    def is_dangling(self) -> bool:
        """True when the pointer's address falls outside the space entirely.

        That is almost always a bug. The one legitimate case is an address
        that points into RAM, which the map should declare.
        """
        return self.verdict == "outside"

    def describe(self) -> str:
        where = self.source
        if self.field:
            where += f".{self.field}"
        if isinstance(self.index, tuple):
            where += "".join(f"[{i}]" for i in self.index)
        elif self.index is not None:
            where += f"[{self.index}]"
        tail = f" -> {self.claimed_by}" if self.claimed_by else ""
        return f"{where} = 0x{self.value:08X}  {self.verdict}{tail}"


@dataclass(frozen=True)
class CoverageReport:
    """What a map accounts for, what it leaves unaccounted for, what it
    double-claims, and what its pointers resolve to.

    :attr:`claimed_bytes` and :meth:`gaps` are the two halves of one
    partition of the space. :attr:`overlaps` and :attr:`pointers` report the
    two ways a map can be wrong about bytes it does claim.
    """

    space_name: str
    space_size: int
    space_base: int
    regions: tuple
    overlaps: tuple
    pointers: tuple
    #: False when no pointer audit ran. It is reported separately so that
    #: an empty :attr:`pointers` is not read as "every pointer checked
    #: out".
    pointers_audited: bool = True

    @cached_property
    def _merged_spans(self) -> "Tuple[tuple, ...]":
        """Resolved footprints merged into maximal disjoint ``(start, end)``
        runs, in address order, clipped to the space.

        What the map claims and what it does not are both read off this one
        list. They are therefore two views of a single partition, which is
        why ``claimed_bytes + unclaimed_bytes == space_size`` always holds.

        The clipping only matters for a report assembled by hand, because
        :meth:`Space.coverage` never resolves a region outside its own
        bounds. Without the clipping, a stray region would inflate the claim
        and stretch a gap past the end of the space it describes.

        The result is cached because the report is frozen, and because a
        single ``render()`` reads it several times over what can be
        thousands of regions.
        """
        low = self.space_base
        high = low + self.space_size
        merged: "List[List[int]]" = []
        for start, end in sorted(
            (max(low, r.start), min(high, r.end))
            for r in self.regions
            if r.resolved and r.size
        ):
            if end <= start:
                continue  # lies entirely outside the space
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return tuple((start, end) for start, end in merged)

    @property
    def claimed_bytes(self) -> int:
        """Distinct bytes claimed by at least one resolved entry, counting
        overlaps once."""
        return sum(end - start for start, end in self._merged_spans)

    def gaps(self, min_size: int = 1) -> tuple:
        """Return the runs of at least ``min_size`` bytes that no resolved
        entry claims, as :class:`Gap` values in address order.

        Gaps are the complement of :attr:`claimed_bytes`, and they are what
        a mapping session works from next. A percentage says how far along
        the map is, while a gap says which addresses to look at. Pair them
        with the ``unclaimed`` pointer verdicts, which name addresses that
        something already points at.

        An UNRESOLVED region claims nothing, so its bytes read as gap. That
        is deliberate. The entry may be right about the address and wrong
        about the length, and a report must not credit a length it could not
        resolve. :attr:`unresolved` names those entries and why each failed.
        """
        gaps = []
        cursor = self.space_base
        limit = self.space_base + self.space_size
        for start, end in self._merged_spans:
            if start > cursor:
                gaps.append(Gap(cursor, start - cursor))
            cursor = max(cursor, end)
        if cursor < limit:
            gaps.append(Gap(cursor, limit - cursor))
        return tuple(g for g in gaps if g.size >= min_size)

    @property
    def unclaimed_bytes(self) -> int:
        """``space_size - claimed_bytes``, which is also the total size of
        the runs :meth:`gaps` returns.

        The two agree because both are read off :attr:`_merged_spans`,
        whose spans are clipped to the space. A test pins that equality
        against the gap sum. This can therefore stay the cheap arithmetic
        form rather than allocating a Gap per run just to add up its sizes.
        """
        return self.space_size - self.claimed_bytes

    @property
    def percent(self) -> float:
        if not self.space_size:
            return 0.0
        return 100.0 * self.claimed_bytes / self.space_size

    @property
    def unresolved(self) -> tuple:
        return tuple(r for r in self.regions if not r.resolved)

    @property
    def dangling(self) -> tuple:
        return tuple(p for p in self.pointers if p.is_dangling)

    def render(self, max_pointers: int = 20, max_gaps: int = 10) -> str:
        """Return the report as text.

        The pointer and gap listings are truncated. The report says by how
        much, because a silent cap would read as "all clear".
        """
        label = self.space_name or "space"
        lines = [
            f"coverage of {label}: {self.claimed_bytes}/{self.space_size} bytes"
            f" ({self.percent:.2f}%) in {len(self.regions)} entries"
        ]
        if self.unresolved:
            lines.append(f"  unresolved ({len(self.unresolved)}):")
            for r in self.unresolved:
                lines.append(f"    {r.name}: {r.error}")
        if self.overlaps:
            lines.append(f"  overlaps ({len(self.overlaps)}):")
            for o in self.overlaps:
                lines.append(
                    f"    {o.a} and {o.b} share {o.size} bytes at" f" 0x{o.start:08X}"
                )
        gaps = self.gaps()
        if gaps:
            # Listed LARGEST first, unlike gaps() itself. On a real map
            # the first gaps by address are the least interesting, because a
            # ROM starts with code, and the question being asked is where
            # the big unmapped region is.
            lines.append(
                f"  gaps ({len(gaps)}): {self.unclaimed_bytes} bytes"
                f" unclaimed, largest first"
            )
            by_size = sorted(gaps, key=lambda g: (-g.size, g.start))
            for g in by_size[:max_gaps]:
                lines.append(f"    {g.describe()}")
            if len(by_size) > max_gaps:
                lines.append(
                    f"    ... and {len(by_size) - max_gaps} more gaps"
                    f" (raise max_gaps to see them)"
                )
        if self.pointers:
            counts: dict = {}
            for p in self.pointers:
                counts[p.verdict] = counts.get(p.verdict, 0) + 1
            tally = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
            lines.append(f"  pointers ({len(self.pointers)}): {tally}")
            interesting = [p for p in self.pointers if p.verdict != "claimed"]
            for p in interesting[:max_pointers]:
                lines.append(f"    {p.describe()}")
            if len(interesting) > max_pointers:
                lines.append(
                    f"    ... and {len(interesting) - max_pointers} more"
                    f" non-claimed pointers (raise max_pointers to see them)"
                )
        elif not self.pointers_audited:
            # Saying nothing here would read as "no pointer lands anywhere
            # odd", which is a different claim from "no pointer audit ran".
            lines.append("  pointers: not audited")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Computing a report
# --------------------------------------------------------------------------


def compute_coverage(space, entries, *, audit_pointers: bool = True) -> CoverageReport:
    """Build a :class:`CoverageReport` for ``entries`` against ``space``.

    The public caller is :meth:`Space.coverage`, which delegates here so
    that the computation lives beside the report it produces.
    """
    bound = [e if e.space is not None else e.bind(space) for e in entries]
    regions = tuple(_resolve_region(space, e) for e in bound)
    overlaps = _overlaps(regions)
    # Following a pointer means reading the address it holds, so a
    # geometry-only space cannot audit pointers. It still resolves the
    # declarations, and pointers_audited reports how far it got.
    audited = audit_pointers and space.buf is not None
    pointers: list = []
    if audited:
        for region in regions:
            pointers.extend(_audit_pointers(space, region, regions))
    return CoverageReport(
        space_name=space.name,
        space_size=len(space),
        space_base=space.base,
        regions=regions,
        overlaps=overlaps,
        pointers=tuple(pointers),
        pointers_audited=audited,
    )


def _resolve_region(space, entry: "Entry"):
    declared = entry.size
    if declared is not None:
        end = entry.addr + declared
        if not (space.contains(entry.addr) and end <= space.end):
            return Region(
                entry,
                None,
                f"0x{entry.addr:08X}+{declared} runs outside the space",
            )
        return Region(entry, declared)
    if isinstance(entry.extent, unknown):
        note = entry.extent.note or "extent not declared"
        return Region(entry, None, f"unknown(): {note}")
    try:
        values = entry.read()
    except (ValueError, TypeError) as exc:
        return Region(entry, None, f"{type(exc).__name__}: {exc}")
    # A scanned table's bytes include its terminator.
    return Region(entry, (len(values) + 1) * entry.stride)


def _audit_pointers(space, region, regions) -> list:
    entry = region.entry
    codec = entry.codec
    source = region.name
    direct = _ptr_adapter_of(codec)
    out: list = []
    if direct is not None:
        for index, value in _enumerate_values(_safe_read(entry)):
            verdict, owner = _classify_address(space, value, regions, direct)
            out.append(PointerRef(source, None, index, value, verdict, owner))
        return out
    if not isinstance(codec, StructMeta):
        return out
    ptr_fields = [
        (info.name, _ptr_adapter_of(info.adapter))
        for info in fields_of(codec)
        if _ptr_adapter_of(info.adapter) is not None
    ]
    if not ptr_fields:
        return out
    records = _safe_read(entry)
    if records is None:
        return out
    if not isinstance(records, list):
        records = [records]
    for rec_index, rec in enumerate(records):
        for field_name, ptr_adapter in ptr_fields:
            value = getattr(rec, field_name)
            for sub, one in _enumerate_values(value):
                index = rec_index if sub is None else (rec_index, sub)
                verdict, owner = _classify_address(space, one, regions, ptr_adapter)
                out.append(PointerRef(source, field_name, index, one, verdict, owner))
    return out


def _safe_read(entry: "Entry"):
    try:
        return entry.read()
    except (ValueError, TypeError):
        return None


def _classify_address(space, addr, regions, adapter=None):
    if not isinstance(addr, int):
        return ("outside", None)
    if addr == 0:
        return ("null", None)
    if not space.contains(addr):
        return ("outside", None)
    for region in regions:
        end = region.end
        if end is not None and region.start <= addr < end:
            return _verify_target(addr, region, adapter)
    return ("unclaimed", None)


def _verify_target(addr, region, adapter):
    """Classify an address that landed inside ``region``.

    The verdict is ``claimed`` unless the pointer DECLARES a record
    type different from the one the region is mapped as.

    That check only runs when the region's entry codec is a Struct
    class and the pointer's target is a Struct class, or resolves to
    one. A raw-byte or scalar region can legitimately contain records
    the map has not modelled at that granularity, and ``Ptr(None)`` or
    an unresolvable name declares nothing to check.

    Two defect verdicts can come out of the check. ``mistargeted``
    means the address lands in a region mapped as a DIFFERENT record
    type. ``misaligned`` means the record type is right but the address
    is not on a record boundary, which is usually an off-by-one in the
    region's address or an interior pointer worth knowing about.
    """
    target = _checkable_target(adapter)
    codec = region.entry.codec
    if target is None or not isinstance(codec, StructMeta):
        return ("claimed", region.name)
    if codec is not target:
        return ("mistargeted", region.name)
    if (addr - region.start) % region.entry.stride:
        return ("misaligned", region.name)
    return ("claimed", region.name)
