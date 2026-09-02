"""Edits as a value: :class:`Edit`, :class:`Patch`, and IPS export.

A patch records *what would change* instead of changing it. The recorded
edits can then be verified against the bytes they were built from, inverted,
composed with other patches, and exported.

That makes a build reproducible, and it makes a wrong base ROM fail loudly
instead of silently.
"""

from dataclasses import dataclass

from bytemaker.structs import BytesLike
from bytemaker.typing_redirect import Iterable, List, Optional, Tuple


class PatchVerifyError(ValueError):
    """The bytes found are not the bytes that were expected.

    Two situations raise this. One is applying a patch to a buffer that does
    not hold the originals it recorded. The other is a write with
    ``expect=`` that finds different bytes already in place. When that write
    came through an :class:`~bytemaker.spaces.Entry`, the message names the
    entry as well as the address.

    Both are the same mistake caught at different moments, and the cause is
    almost always the wrong build, or a table that moved.
    """


class PatchConflict(ValueError):
    """Two patches being composed disagree about the same byte."""


class PatchUnverifiable(ValueError):
    """An operation needs the original bytes, but this patch did not record
    them for every byte it claims.

    :meth:`Patch.invert` and :meth:`Patch.guards` both raise it, because
    neither can reconstruct those bytes. Undoing an edit means restoring
    what was there, and a compare-and-swap guard means naming what the bytes
    must still be.
    """


@dataclass(frozen=True)
class Edit:
    """A replacement of one contiguous run of bytes.

    An ``Edit`` has three parts: ``offset`` is where the change applies,
    ``new`` is the bytes written there, and ``old`` is the bytes they
    replace. A run is at least one byte long, with no upper bound.

    ``new`` and ``old`` are always the same length. An edit that changed a
    region's size would shift everything after it, which is a different and
    much larger operation than patching.

    ``old`` is ``None`` for a **blind** edit, meaning bytes written without
    the original in hand. That is the normal case when a patch is built
    before the target exists, such as a randomizer emitting writes with no
    base image. A blind edit still applies and still composes, but it cannot
    be verified or inverted.
    """

    offset: int
    new: bytes
    old: Optional[bytes] = None

    def __post_init__(self):
        if self.old is not None and len(self.old) != len(self.new):
            raise ValueError(
                f"Edit at {self.offset}: old is {len(self.old)} bytes and new"
                f" is {len(self.new)}; an edit replaces bytes in place"
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
        """True when this edit provably changes nothing.

        A blind edit is never a no-op, because unknown is not the same as
        unchanged.
        """
        return self.old == self.new


#: IPS record offsets are 24-bit. An offset of exactly 0x454F46 encodes as
#: the ASCII bytes "EOF", which is also the marker that terminates the file.
IPS_EOF_OFFSET = 0x454F46
IPS_MAX_OFFSET = 0xFFFFFF
IPS_MAX_RECORD = 0xFFFF


def _changed_runs(old: BytesLike, new: BytesLike):
    """Yield ``(index, old_run, new_run)`` per maximal run where the two byte
    strings differ.

    The runs describe what a write *actually changed*, rather than the span
    it happened to cover. Recording a whole encoded record would claim the
    bytes it left alone as well. Those extra bytes then read as a
    disagreement when two independent patches touch different fields of one
    record.
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

    The alternative is mutating a buffer in place, which throws away three
    things you need afterwards: what the bytes used to be, whether you are
    editing the right build at all, and how to undo the change. A patch
    keeps all three::

        p = Patch(name="boss rush reward")
        rom.write(0x08526390, rec, patch=p)   # records, does not mutate
        patched = p.apply(rom.buf)            # verifies old bytes first
        assert p.invert().apply(patched) == rom.buf
        open("fix.ips", "wb").write(p.to_ips())

    An export that wants another container is a one-liner rather than a
    method::

        tokens = {e.offset: e.new for e in p.edits}   # offset -> bytes

    Internally a patch is a sparse byte map rather than a list of edits, so
    overlapping writes have one unambiguous result and the two operations
    below are defined for every input.

    * :meth:`write` is an imperative edit, so **a later write to a byte
      replaces an earlier one**. The patch keeps the EARLIEST ``old`` for
      each byte, so verify and :meth:`invert` still refer to the pristine
      buffer. That matches the natural read-modify-write flow of tweaking a
      field and then tweaking it again.
    * ``a | b`` composes two INDEPENDENT patches. It raises
      :class:`PatchConflict` when they disagree about a byte, because with
      no ordering between them a disagreement is a mistake rather than an
      update.

    :attr:`edits` coalesces the byte map back into maximal contiguous runs,
    so the export format and :meth:`summary` work on whole edits.
    """

    __slots__ = ("_old", "_new", "name")

    def __init__(self, edits: Iterable[Edit] = (), *, name: str = ""):
        self._old: dict = {}
        self._new: dict = {}
        self.name = name
        for e in edits:
            self.write(e.offset, e.new, e.old)

    # -- building ----------------------------------------------------------
    def write(
        self, offset: int, new: BytesLike, old: Optional[BytesLike] = None
    ) -> None:
        """Record that the bytes at ``offset`` become ``new``, replacing
        ``old``.

        A later write to a byte replaces an earlier one, while the earliest
        ``old`` is kept, so the patch always describes a transition from the
        pristine buffer.

        Omitting ``old`` records a **blind** write, meaning the original
        bytes are not known. That happens when the patch is built before the
        target image is in hand, which is the normal case at generation
        time. A blind write applies and composes like any other edit, but
        the patch stops being :attr:`verifiable`, so :meth:`invert` and
        :meth:`guards` raise on it. Writing the same byte again with a known
        original fills that original in.
        """
        new_b = bytes(new)
        old_b = None if old is None else bytes(old)
        if old_b is not None and len(old_b) != len(new_b):
            raise ValueError(
                f"Patch.write at {offset}: old is {len(old_b)} bytes and new"
                f" is {len(new_b)}; an edit replaces bytes in place"
            )
        if offset < 0:
            raise ValueError(f"Patch.write offset must be non-negative, got {offset}")
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
        """Return the patch that turns ``base`` into ``edited``.

        Use this for a build that mutates a working copy in place. Each
        step there reads the state the previous ones left, so the edits
        cannot be recorded as they happen. Diffing the two ends recovers a
        verifiable, invertible, exportable value.

        A byte the build wrote back to the value it already held does not
        differ between the two ends, so the diff neither claims nor guards
        it. Applied to a base that differs at exactly such a byte, the
        patch succeeds and produces the wrong result there. When that
        matters, write through :meth:`Space.recording` instead, which
        records every write as it happens.
        """
        base_b, edited_b = bytes(base), bytes(edited)
        if len(base_b) != len(edited_b):
            raise ValueError(
                f"Patch.diff: buffers are {len(base_b)} and {len(edited_b)}"
                f" bytes; a patch replaces bytes in place, so a length"
                f" change is not expressible"
            )
        out = cls(name=name)
        for at, was, now in _changed_runs(base_b, edited_b):
            out.write(at, now, was)
        return out

    @property
    def edits(self) -> Tuple[Edit, ...]:
        """The byte map as maximal contiguous :class:`Edit` runs, in offset
        order.

        A run also breaks where knowledge of the original breaks, so every
        edit is either wholly verifiable or wholly blind. A run that mixed
        the two could not be inverted, and would not describe one coherent
        edit either.
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
        """How many bytes the patch claims, no-ops included."""
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
        """Return the patch that undoes this one.

        Refuses a patch with blind edits, because restoring bytes whose
        originals were never recorded would mean guessing at them.
        """
        self._require_verifiable("invert()")
        out = Patch(name=f"undo({self.name})" if self.name else "")
        out._old = dict(self._new)
        out._new = dict(self._old)
        return out

    def guards(self) -> Tuple[Tuple[int, bytes, bytes], ...]:
        """Return ``(offset, expected, new)`` per coalesced run.

        Each triple says to write ``new`` at ``offset``, but only while the
        bytes there still equal ``expected``. That is the compare-and-swap
        form a live target needs, because a running game's memory can change
        between the read and the write. Without the guard, such a change is
        overwritten silently.

        A blind patch has nothing to compare against, so this raises. The
        result is a tuple rather than a generator, so that the refusal
        happens when you call ``guards()`` rather than once you start
        iterating. A tuple can also be counted and reused.
        """
        self._require_verifiable("guards()")
        triples: List[Tuple[int, bytes, bytes]] = []
        for e in self.edits:
            # _require_verifiable() has just ruled out blind edits, so ``old``
            # is bytes here; the check narrows it for the type checker too.
            if e.old is None:
                raise PatchUnverifiable(f"{self._label()}: edit at {e.offset} is blind")
            triples.append((e.offset, e.old, e.new))
        return tuple(triples)

    def __or__(self, other: "Patch") -> "Patch":
        """Compose two independent patches, raising :class:`PatchConflict`
        when they disagree about a byte."""
        if not isinstance(other, Patch):
            return NotImplemented
        clash = sorted(
            at for at, n in other._new.items() if at in self._new and self._new[at] != n
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
                continue  # blind byte, so nothing was recorded to check
            if got != want:
                raise PatchVerifyError(
                    f"{self._label()}: buffer byte at offset {at} (0x{at:X})"
                    f" is {got:#04x}, but the patch was built against"
                    f" {want:#04x}; wrong build, or already applied"
                )

    def apply(self, buf: BytesLike, *, verify: bool = True) -> bytes:
        """Return the patched bytes, checking the recorded originals first
        unless ``verify`` is turned off.

        Leave ``verify`` on, because the check is what catches a wrong
        build or an already-patched buffer.
        """
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
        """Return this patch as an IPS file.

        IPS records carry no original bytes, so the export is
        **verification-lossy**. Keep the :class:`Patch`, or its edits, as
        the source artifact, and treat the ``.ips`` as a distribution
        format.

        ``buf`` is only needed for one quirk. An IPS record whose 24-bit
        offset is exactly ``0x454F46`` encodes as the ASCII bytes ``EOF``,
        which naive readers treat as end-of-file. Given the buffer, such a
        record is extended one byte backwards, so its offset lands
        elsewhere. The extra byte is copied from the buffer unchanged.
        Without the buffer, this raises.

        A long edit whose *split boundary* lands on that offset needs no
        buffer. The preceding byte is part of that same edit, so the record
        simply starts one byte earlier.
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
                    # A split boundary landed on the quirk offset. Only
                    # a record after the first one can, because the edit's
                    # own offset was handled above. The preceding byte
                    # therefore belongs to this same edit, so starting one
                    # byte earlier re-emits an identical value and needs no
                    # buffer.
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
        """Write :meth:`to_ips` to ``path``, returning the number of bytes
        written."""
        data = self.to_ips(buf)
        with open(path, "wb") as fh:
            fh.write(data)
        return len(data)

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        """Return a header line plus one line per coalesced edit."""
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
