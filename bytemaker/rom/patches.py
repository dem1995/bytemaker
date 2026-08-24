"""Edits as a value: :class:`Edit`, :class:`Patch`, and IPS export.

A patch records *what would change* instead of changing it, so the edits can
be verified against the bytes they were built from, inverted, composed with
other patches, and exported. That makes a build reproducible and a wrong
base ROM loud instead of silent.
"""

from dataclasses import dataclass

from bytemaker.structs import BytesLike
from bytemaker.typing_redirect import List, Optional

class PatchVerifyError(ValueError):
    """Bytes are not what they were said to be.

    Raised when a patch is applied to a buffer that does not hold the
    originals it recorded, and when a write with ``expect=`` finds something
    else already there. Both are the same mistake caught at different
    moments — almost always the wrong build, or a table that moved."""


class PatchConflict(ValueError):
    """Two patches being composed disagree about the same byte."""


class PatchUnverifiable(ValueError):
    """An operation needs the original bytes, and this patch does not know
    them for every byte it claims.

    Raised by :meth:`Patch.invert` and :meth:`Patch.guards`, which cannot
    guess: undoing an edit means restoring what was there, and a
    compare-and-swap guard means naming what it must still be.
    """


@dataclass(frozen=True)
class Edit:
    """One contiguous replacement: ``new`` goes where ``old`` was.

    Equal lengths, always — an edit that changed a region's size would shift
    everything after it, which is a different (and much larger) operation
    than patching.

    ``old`` is ``None`` for a **blind** edit: bytes written without the
    original in hand, which is the normal case when a patch is built before
    the target exists (a randomizer emitting writes with no base image). Such
    an edit still applies and still composes; it cannot be verified or
    inverted.
    """

    offset: int
    new: bytes
    old: Optional[bytes] = None

    def __post_init__(self):
        if self.old is not None and len(self.old) != len(self.new):
            raise ValueError(
                f"Edit at {self.offset}: old is {len(self.old)} bytes and new"
                f" is {len(self.new)} — an edit replaces bytes in place"
            )
        if not self.new:
            raise ValueError(f"Edit at {self.offset} is empty")
        if self.offset < 0:
            raise ValueError(f"Edit offset must be non-negative, got {self.offset}")

    @property
    def size(self) -> int:
        return len(self.new)

    @property
    def end(self) -> int:
        """One past the last byte this edit touches."""
        return self.offset + len(self.new)

    @property
    def is_blind(self) -> bool:
        """True when the original bytes are unknown."""
        return self.old is None

    @property
    def is_noop(self) -> bool:
        """True when this edit provably changes nothing. A blind edit is
        never a no-op: unknown is not the same as unchanged."""
        return self.old == self.new


#: IPS record offsets are 24-bit, and an offset of exactly 0x454F46 encodes
#: as the ASCII bytes "EOF" — the same marker that terminates the file.
IPS_EOF_OFFSET = 0x454F46
IPS_MAX_OFFSET = 0xFFFFFF
IPS_MAX_RECORD = 0xFFFF


def _changed_runs(old: BytesLike, new: BytesLike):
    """Yield ``(index, old_run, new_run)`` per maximal run where the two byte
    strings differ.

    What a write *actually changed*, as opposed to the span it happened to
    cover. Recording a whole encoded record would claim the bytes it left
    alone too, which then reads as a disagreement when two independent
    patches touch different fields of one record.
    """
    old_b, new_b = bytes(old), bytes(new)
    i, n = 0, len(old_b)
    while i < n:
        if old_b[i] == new_b[i]:
            i += 1
            continue
        start = i
        while i < n and old_b[i] != new_b[i]:
            i += 1
        yield start, old_b[start:i], new_b[start:i]


class Patch:
    """A set of byte edits, as a value you can verify, invert and compose.

    The alternative — mutating a buffer in place — throws away everything
    you need afterwards: what the bytes used to be, whether you are even
    editing the right build, and how to undo it. A patch keeps all three::

        p = Patch(name="boss rush reward")
        rom.write(0x08526390, rec, patch=p)   # records, does not mutate
        patched = p.apply(rom.buf)            # verifies old bytes first
        assert p.invert().apply(patched) == rom.buf
        open("fix.ips", "wb").write(p.to_ips())

    Two exports are one-liners over :attr:`edits`, deliberately not methods —
    the container a caller wants differs by caller::

        tokens = {e.offset: e.new for e in p.edits}   # offset -> bytes
        pins = {e.name: e.addr for e in ROM_MAP}      # the map's own digest

    Internally a patch is a sparse byte map, not a list of edits, which is
    what makes the algebra total: overlapping writes have no ambiguity.

    * :meth:`write` is an imperative edit — **later writes win**, and the
      patch keeps the EARLIEST ``old`` for each byte, so verify and
      :meth:`invert` still refer to the pristine buffer. This is the natural
      read-modify-write flow (tweak a field, then tweak it again).
    * ``a | b`` composes two INDEPENDENT patches and raises
      :class:`PatchConflict` when they disagree about a byte, because with no
      ordering between them a disagreement is a mistake, not an update.

    :attr:`edits` coalesces the byte map back into maximal contiguous runs,
    so the export format and :meth:`summary` see whole edits.
    """

    __slots__ = ("_old", "_new", "name")

    def __init__(self, edits=(), *, name: str = ""):
        self._old: dict = {}
        self._new: dict = {}
        self.name = name
        for e in edits:
            self.write(e.offset, e.new, e.old)

    # -- building ----------------------------------------------------------
    def write(
        self, offset: int, new: BytesLike, old: Optional[BytesLike] = None
    ) -> None:
        """Record that ``offset`` becomes ``new``, replacing ``old``.

        Later writes win per byte; the earliest ``old`` is kept, so the patch
        always describes a transition from the pristine buffer.

        Omitting ``old`` records a **blind** write — the original bytes are
        not known, because the patch is being built before the target image
        is in hand, which is the normal case at generation time. The edit
        applies and composes like any other, but the patch stops being
        :attr:`verifiable` (see :meth:`invert`, :meth:`guards`). A byte later
        written with a known original upgrades: more information wins over
        less.
        """
        new_b = bytes(new)
        old_b = None if old is None else bytes(old)
        if old_b is not None and len(old_b) != len(new_b):
            raise ValueError(
                f"Patch.write at {offset}: old is {len(old_b)} bytes and new"
                f" is {len(new_b)} — an edit replaces bytes in place"
            )
        if offset < 0:
            raise ValueError(
                f"Patch.write offset must be non-negative, got {offset}"
            )
        for i, n in enumerate(new_b):
            at = offset + i
            o = None if old_b is None else old_b[i]
            if o is not None and self._old.get(at) is None:
                self._old[at] = o  # earliest KNOWN original wins
            else:
                self._old.setdefault(at, o)
            self._new[at] = n  # latest edit wins

    @classmethod
    def diff(cls, base: BytesLike, edited: BytesLike, *, name: str = "") -> "Patch":
        """The patch that turns ``base`` into ``edited``.

        The honest artifact for a build that mutates a working copy in place
        — where each step reads the state the previous ones left, so the
        edits cannot be recorded as they happen. Diff the ends and you get a
        verifiable, invertible, exportable value back.
        """
        base_b, edited_b = bytes(base), bytes(edited)
        if len(base_b) != len(edited_b):
            raise ValueError(
                f"Patch.diff: buffers are {len(base_b)} and {len(edited_b)}"
                f" bytes — a patch replaces bytes in place, so a length"
                f" change is not expressible"
            )
        out = cls(name=name)
        for at, was, now in _changed_runs(base_b, edited_b):
            out.write(at, now, was)
        return out

    @property
    def edits(self) -> tuple:
        """The byte map as maximal contiguous :class:`Edit` runs, in offset
        order.

        A run also breaks where knowledge of the original does, so an edit is
        either wholly verifiable or wholly blind — never a mix that neither
        :meth:`invert` nor a reader could make sense of.
        """
        runs: List[List[int]] = []  # [first, last] byte offsets, inclusive
        for at in sorted(self._new):
            known = self._old[at] is not None
            if runs and at == runs[-1][1] + 1 and known == runs[-1][2]:
                runs[-1][1] = at
            else:
                runs.append([at, at, known])
        return tuple(self._edit(first, last) for first, last, _ in runs)

    def _edit(self, start: int, last: int) -> Edit:
        rng = range(start, last + 1)
        blind = self._old[start] is None
        return Edit(
            start,
            bytes(self._new[i] for i in rng),
            old=None if blind else bytes(self._old[i] for i in rng),
        )

    @property
    def verifiable(self) -> bool:
        """True when the original bytes are known for every byte claimed."""
        return all(o is not None for o in self._old.values())

    def _blind_offsets(self) -> List[int]:
        return sorted(at for at, o in self._old.items() if o is None)

    def _require_verifiable(self, what: str) -> None:
        blind = self._blind_offsets()
        if not blind:
            return
        shown = ", ".join(f"0x{at:X}" for at in blind[:4])
        more = f" (+{len(blind) - 4} more)" if len(blind) > 4 else ""
        raise PatchUnverifiable(
            f"{self._label()}: {what} needs the original bytes, but"
            f" {len(blind)} byte(s) were written blind: {shown}{more}"
        )

    def __len__(self) -> int:
        """The number of coalesced edits."""
        return len(self.edits)

    def __bool__(self) -> bool:
        return bool(self._new)

    @property
    def byte_count(self) -> int:
        """How many bytes the patch claims (no-ops included)."""
        return len(self._new)

    @property
    def changed_byte_count(self) -> int:
        """How many bytes the patch actually changes."""
        return sum(1 for at, n in self._new.items() if self._old[at] != n)

    def touches(self, offset: int) -> bool:
        """True if ``offset`` is claimed by this patch."""
        return offset in self._new

    # -- algebra -----------------------------------------------------------
    def invert(self) -> "Patch":
        """The patch that undoes this one.

        Refuses a patch with blind edits: restoring bytes nobody recorded is
        not something to guess at.
        """
        self._require_verifiable("invert()")
        out = Patch(name=f"undo({self.name})" if self.name else "")
        out._old = dict(self._new)
        out._new = dict(self._old)
        return out

    def guards(self) -> tuple:
        """``(offset, expected, new)`` per coalesced run: write ``new`` at
        ``offset``, but only while the bytes there still equal ``expected``.

        The compare-and-swap triple a live target wants — a running game's
        memory can change under a read, so a guarded write is the difference
        between a correct update and a lost one. Refuses a blind patch, which
        has nothing to compare against.

        A tuple rather than a generator, so the refusal happens when you ask
        rather than when you get around to iterating, and so the result can
        be counted and reused.
        """
        self._require_verifiable("guards()")
        return tuple((e.offset, e.old, e.new) for e in self.edits)

    def __or__(self, other: "Patch") -> "Patch":
        """Compose two independent patches; disagreement is a
        :class:`PatchConflict`."""
        if not isinstance(other, Patch):
            return NotImplemented
        clash = sorted(
            at
            for at, n in other._new.items()
            if at in self._new and self._new[at] != n
        )
        if clash:
            at = clash[0]
            extra = f" ({len(clash)} bytes conflict)" if len(clash) > 1 else ""
            raise PatchConflict(
                f"patches disagree at offset {at} (0x{at:X}):"
                f" {self._new[at]:#04x} vs {other._new[at]:#04x}{extra}"
            )
        names = [n for n in (self.name, other.name) if n]
        out = Patch(name=" | ".join(names))
        out._old = {**other._old, **self._old}  # earliest original wins
        out._new = {**self._new, **other._new}
        return out

    # -- applying ----------------------------------------------------------
    def _check_range(self, at: int, size: int) -> None:
        if at >= size:
            raise PatchVerifyError(
                f"{self._label()}: offset {at} (0x{at:X}) is past the end of a"
                f" {size}-byte buffer"
            )

    def _verify(self, view: memoryview) -> None:
        size = view.nbytes
        for at in sorted(self._new):
            self._check_range(at, size)
            want, got = self._old[at], view[at]
            if want is None:
                continue  # blind byte: nothing was recorded to check against
            if got != want:
                raise PatchVerifyError(
                    f"{self._label()}: buffer byte at offset {at} (0x{at:X})"
                    f" is {got:#04x}, but the patch was built against"
                    f" {want:#04x} — wrong build, or already applied"
                )

    def apply(self, buf: BytesLike, *, verify: bool = True) -> bytes:
        """The patched bytes. ``verify`` checks the original bytes first —
        leave it on; it is the whole point."""
        out = bytearray(buf)
        self.apply_into(out, verify=verify)
        return bytes(out)

    def apply_into(self, buf, *, verify: bool = True) -> None:
        """Apply in place to a ``bytearray`` (or writable ``memoryview``)."""
        view = memoryview(buf)
        if view.readonly:
            raise TypeError(
                f"{self._label()}: apply_into needs a writable buffer; use"
                f" apply() to get patched bytes back instead"
            )
        if verify:
            self._verify(view)
        size = view.nbytes
        for at, n in self._new.items():
            self._check_range(at, size)
            view[at] = n

    # -- export ------------------------------------------------------------
    def to_ips(self, buf: Optional[BytesLike] = None) -> bytes:
        """This patch as an IPS file.

        IPS records carry no original bytes, so the export is
        **verification-lossy**: keep the :class:`Patch` (or its edits) as the
        source artifact and treat the ``.ips`` as a distribution format.

        ``buf`` is only needed for one quirk: an IPS record whose 24-bit
        offset is exactly ``0x454F46`` encodes as the ASCII bytes ``EOF``,
        which naive readers treat as end-of-file. Given the buffer, such a
        record is extended one byte backwards (carrying the unchanged byte
        along) so its offset lands elsewhere; without it, this raises.
        A long edit whose *split boundary* lands there needs no buffer: the
        preceding byte is part of that same edit, so the record simply
        starts one byte earlier.
        """
        parts = [b"PATCH"]
        for edit in self.edits:
            offset, data = edit.offset, edit.new
            if offset == IPS_EOF_OFFSET:
                if buf is None:
                    raise ValueError(
                        f"{self._label()}: an IPS record at offset"
                        f" 0x{IPS_EOF_OFFSET:06X} encodes as the ASCII bytes"
                        f" 'EOF' and would truncate the patch for naive"
                        f" readers; pass to_ips(buf=<the original bytes>) so"
                        f" the record can start one byte earlier"
                    )
                offset -= 1
                data = bytes(memoryview(buf)[offset : offset + 1]) + data
            start = 0
            while start < len(data):
                at = offset + start
                if at == IPS_EOF_OFFSET:
                    # A split boundary landed on the quirk offset. Only a
                    # record after the first can (the edit's own offset was
                    # handled above), so the preceding byte belongs to this
                    # same edit: starting one byte earlier re-emits an
                    # identical value and needs no buffer.
                    start -= 1
                    at -= 1
                chunk = data[start : start + IPS_MAX_RECORD]
                if at > IPS_MAX_OFFSET:
                    raise ValueError(
                        f"{self._label()}: IPS offsets are 24-bit; offset"
                        f" 0x{at:X} exceeds 0x{IPS_MAX_OFFSET:06X} (16 MiB)"
                    )
                parts.append(at.to_bytes(3, "big"))
                parts.append(len(chunk).to_bytes(2, "big"))
                parts.append(chunk)
                start += len(chunk)
        parts.append(b"EOF")
        return b"".join(parts)

    def save_ips(self, path, buf: Optional[BytesLike] = None) -> int:
        """Write :meth:`to_ips` to ``path``; returns the byte count."""
        data = self.to_ips(buf)
        with open(path, "wb") as fh:
            fh.write(data)
        return len(data)

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        """A header line plus one line per coalesced edit."""
        edits = self.edits
        if not edits:
            return f"{self._label()}: empty"
        blind = len(self._blind_offsets())
        head = (
            f"{self._label()}: {len(edits)} edit(s),"
            f" {self.changed_byte_count}/{self.byte_count} bytes changed"
        )
        lines = [head + (f", {blind} blind" if blind else "")]
        for e in edits:
            mark = "  (no-op)" if e.is_noop else ""
            was = "??" * e.size if e.old is None else e.old.hex()
            lines.append(
                f"  0x{e.offset:06X}+{e.size:<4} {was} ->" f" {e.new.hex()}{mark}"
            )
        return "\n".join(lines)

    def _label(self) -> str:
        return f"Patch {self.name!r}" if self.name else "Patch"

    def __repr__(self):
        label = f" {self.name!r}" if self.name else ""
        return f"<Patch{label} {len(self.edits)} edits, {self.byte_count} bytes>"

    def __eq__(self, other):
        if not isinstance(other, Patch):
            return NotImplemented
        return self._old == other._old and self._new == other._new

    __hash__ = None  # type: ignore[assignment]  # mutable, like a bytearray
