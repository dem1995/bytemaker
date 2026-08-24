"""What a map accounts for: :class:`CoverageReport` and its parts.

The value types a coverage audit produces — resolved :class:`Region`
footprints, :class:`Overlap` pairs, unclaimed :class:`Gap` runs, and
:class:`PointerRef` classifications. :meth:`Space.coverage` builds them; they
hold no buffer and no space themselves.
"""

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from bytemaker.typing_redirect import Any, List, Optional, Tuple

if TYPE_CHECKING:
    from .spaces import Entry

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
    """Two entries claiming the same bytes — usually a wrong count."""

    a: str
    b: str
    start: int
    size: int


@dataclass(frozen=True)
class Gap:
    """A run of bytes no resolved entry claims.

    The complement of a coverage report, and the question a mapping session
    actually runs on: not "how much have I got" but "what is left, and where
    is the big one".
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
    """``(index, one)`` pairs for a scalar, a list, or None: normalizes the
    three shapes a Ptr-carrying read can produce."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(enumerate(value))
    return ((None, value),)


def _overlaps(regions) -> tuple:
    """Pairs of resolved regions that claim the same bytes.

    Sweeps in start order, so an entry overlapping three others reports
    three pairs rather than one vague complaint.
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
    #: "claimed" | "unclaimed" | "outside" | "null" — plus, when the pointer
    #: declares a record target, the two verified-defect verdicts
    #: "mistargeted" (lands in a region mapped as a different record type)
    #: and "misaligned" (right type, off a record boundary).
    verdict: str
    claimed_by: Optional[str] = None

    @property
    def is_dangling(self) -> bool:
        """Points outside the space entirely — the one that is always a bug
        (or a pointer into RAM, which a ROM map should say so about)."""
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
    double-claims, and where its pointers land.

    :attr:`claimed_bytes` and :meth:`gaps` are the two halves of one
    partition of the space; :attr:`overlaps` and :attr:`pointers` report the
    two ways a map can be wrong about bytes it does claim.
    """

    space_name: str
    space_size: int
    space_base: int
    regions: tuple
    overlaps: tuple
    pointers: tuple

    @cached_property
    def _merged_spans(self) -> "Tuple[tuple, ...]":
        """Resolved footprints merged into maximal disjoint ``(start, end)``
        runs, in address order, clipped to the space.

        What the map claims and what it does not are both read off this one
        list, which is what makes them two views of a single partition:
        ``claimed_bytes + unclaimed_bytes == space_size``, always. The
        clipping only bites for a report assembled by hand —
        :meth:`Space.coverage` never resolves a region outside its own
        bounds — but without it a stray region would inflate the claim and
        stretch a gap past the end of the space it describes.

        Cached: the report is frozen and one ``render()`` reads this several
        times over what can be thousands of regions.
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
        """Distinct bytes claimed by at least one resolved entry (overlaps
        counted once)."""
        return sum(end - start for start, end in self._merged_spans)

    def gaps(self, min_size: int = 1) -> tuple:
        """Runs of at least ``min_size`` bytes that no resolved entry
        claims, as :class:`Gap` values in address order.

        The complement of :attr:`claimed_bytes`, and the direction a map
        actually grows in: percentages say how far along you are, gaps say
        where to look next — especially paired with the ``unclaimed``
        pointer verdicts, which name addresses something already points at.

        An UNRESOLVED region claims nothing, so its bytes read as gap. That
        is deliberate (the entry may be right about the address and wrong
        about the length, and a report must not credit a length it could not
        resolve); :attr:`unresolved` names those entries and why.
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
        """``space_size - claimed_bytes``, which is also the total bytes in
        :meth:`gaps` — the two agree because both sides are read off
        :attr:`_merged_spans`, whose spans are clipped to the space. The
        equality is pinned by a test against the gap sum, so this can stay
        the cheap arithmetic form (the sum allocates a Gap per run just to
        add its sizes)."""
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
        """A text report. Truncates the pointer and gap listings, and says by
        how much — a silent cap would read as "all clear"."""
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
                    f"    {o.a} and {o.b} share {o.size} bytes at"
                    f" 0x{o.start:08X}"
                )
        gaps = self.gaps()
        if gaps:
            # Listed LARGEST first, unlike gaps() itself: on a real map the
            # first gaps by address are the least interesting (a ROM starts
            # with code), and the question being asked is where the big
            # unmapped region is.
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
        return "\n".join(lines)
