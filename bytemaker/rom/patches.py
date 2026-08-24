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
    """A patch was applied to a buffer whose bytes are not what the patch
    recorded as the original. Almost always the wrong ROM build."""


class PatchConflict(ValueError):
    """Two patches being composed disagree about the same byte."""


@dataclass(frozen=True)
class Edit:
    """One contiguous replacement: ``new`` goes where ``old`` was.

    Equal lengths, always — an edit that changed a region's size would shift
    everything after it, which is a different (and much larger) operation
    than patching.
    """

    offset: int
    old: bytes
    new: bytes

    def __post_init__(self):
        if len(self.old) != len(self.new):
            raise ValueError(
                f"Edit at {self.offset}: old is {len(self.old)} bytes and new"
                f" is {len(self.new)} — an edit replaces bytes in place"
            )
        if not self.old:
            raise ValueError(f"Edit at {self.offset} is empty")
        if self.offset < 0:
            raise ValueError(f"Edit offset must be non-negative, got {self.offset}")

    @property
    def size(self) -> int:
        return len(self.old)

    @property
    def end(self) -> int:
        """One past the last byte this edit touches."""
        return self.offset + len(self.old)

    @property
    def is_noop(self) -> bool:
        return self.old == self.new


#: IPS record offsets are 24-bit, and an offset of exactly 0x454F46 encodes
#: as the ASCII bytes "EOF" — the same marker that terminates the file.
IPS_EOF_OFFSET = 0x454F46
IPS_MAX_OFFSET = 0xFFFFFF
IPS_MAX_RECORD = 0xFFFF


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
            self.write(e.offset, e.old, e.new)

    # -- building ----------------------------------------------------------
    def write(self, offset: int, old: BytesLike, new: BytesLike) -> None:
        """Record that the bytes ``old`` at ``offset`` become ``new``.

        Later writes win per byte; the earliest ``old`` is kept, so the patch
        always describes a transition from the pristine buffer.
        """
        old_b, new_b = bytes(old), bytes(new)
        if len(old_b) != len(new_b):
            raise ValueError(
                f"Patch.write at {offset}: old is {len(old_b)} bytes and new"
                f" is {len(new_b)} — an edit replaces bytes in place"
            )
        if offset < 0:
            raise ValueError(
                f"Patch.write offset must be non-negative, got {offset}"
            )
        for i, (o, n) in enumerate(zip(old_b, new_b)):
            at = offset + i
            self._old.setdefault(at, o)  # earliest original wins
            self._new[at] = n  # latest edit wins

    @property
    def edits(self) -> tuple:
        """The byte map as maximal contiguous :class:`Edit` runs, in offset
        order."""
        runs: List[List[int]] = []  # [first, last] byte offsets, inclusive
        for at in sorted(self._new):
            if runs and at == runs[-1][1] + 1:
                runs[-1][1] = at
            else:
                runs.append([at, at])
        return tuple(self._edit(first, last) for first, last in runs)

    def _edit(self, start: int, last: int) -> Edit:
        rng = range(start, last + 1)
        return Edit(
            start,
            bytes(self._old[i] for i in rng),
            bytes(self._new[i] for i in rng),
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
        """The patch that undoes this one."""
        out = Patch(name=f"undo({self.name})" if self.name else "")
        out._old = dict(self._new)
        out._new = dict(self._old)
        return out

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
        lines = [
            f"{self._label()}: {len(edits)} edit(s),"
            f" {self.changed_byte_count}/{self.byte_count} bytes changed"
        ]
        for e in edits:
            mark = "  (no-op)" if e.is_noop else ""
            lines.append(
                f"  0x{e.offset:06X}+{e.size:<4} {e.old.hex()} ->"
                f" {e.new.hex()}{mark}"
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
