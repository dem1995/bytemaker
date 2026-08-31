"""How far a table runs: ``count``, ``until``, ``through``, ``unknown``.

An extent is a value rather than a convention, so a table's length is part
of its declaration instead of a comment beside it. The four subclasses
cover the four things anyone actually knows about a length: an exact
count, a sentinel that ends the table, the address of its last byte, or
nothing yet. A plain int works wherever an extent is accepted, so ``4``
means ``count(4)``.

See :mod:`bytemaker.spaces` for the layer's overview.
"""

from bytemaker.typing_redirect import Any


class Extent:
    """Base class of the four table-length declarations.

    The subclasses are named in lower case because they are used as values
    at a declaration site, as in ``count(4)`` or ``until(0)``.
    """

    __slots__ = ()

    def __repr__(self):
        args = ", ".join(f"{s}={getattr(self, s)!r}" for s in self.__slots__)
        return f"{type(self).__name__}({args})"

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return all(getattr(self, s) == getattr(other, s) for s in self.__slots__)

    def __hash__(self):
        return hash(
            (type(self).__name__,) + tuple(getattr(self, s) for s in self.__slots__)
        )


class count(Extent):
    """Exactly ``n`` items."""

    __slots__ = ("n",)

    def __init__(self, n: int):
        if not isinstance(n, int) or n < 0:
            raise ValueError(f"count(n) needs a non-negative int, got {n!r}")
        self.n = n


class until(Extent):
    """Items up to the first one equal to ``sentinel``, which is excluded.

    The sentinel is matched on the **wire**, before any adapter runs,
    because an adapter must never change what terminates a table.

    ``max_count`` caps the scan. A table with no terminator inside it
    raises rather than reading on to the end of the space.
    """

    __slots__ = ("sentinel", "max_count")

    def __init__(self, sentinel: Any = 0, max_count: int = 4096):
        if not isinstance(max_count, int) or max_count <= 0:
            raise ValueError(
                f"until(max_count=) needs a positive int, got {max_count!r}"
            )
        self.sentinel = sentinel
        self.max_count = max_count


class through(Extent):
    """Items from the entry's address through ``last``, inclusive.

    ``last`` is the address of the table's final byte, because that is the
    form a disassembly listing gives you. (``until`` excludes its sentinel;
    ``through`` includes its last address.) The item width must divide the
    region exactly, so a remainder means the address, the last address, or
    the record shape is wrong.
    """

    __slots__ = ("last",)

    def __init__(self, last: int):
        if not isinstance(last, int):
            raise ValueError(f"through(last) needs an int address, got {last!r}")
        self.last = last

    def __repr__(self):
        # The last address in decimal is unreadable. count's n is a
        # quantity, so it stays decimal.
        return f"through(last=0x{self.last:08X})"


class unknown(Extent):
    """The length is not known, so reads refuse.

    The entry still documents the address and the record shape. A coverage
    report lists it as unresolved and counts it as claiming no bytes,
    giving ``note`` as the reason.
    """

    __slots__ = ("note",)

    def __init__(self, note: str = ""):
        self.note = note


class _Inherit:
    """Marks "no extent passed", distinct from ``0`` or ``count(0)``.

    Both ``0`` and ``count(0)`` are legitimate extents, and a falsiness
    test would read them as absent. This is a named class rather than a
    bare sentinel so that its repr is readable in a signature.
    """

    __slots__ = ()

    def __repr__(self):
        return "<the declared extent>"


_INHERIT = _Inherit()


def _as_extent(extent) -> Extent:
    """Normalize an extent argument.

    ``4`` becomes ``count(4)``, ``None`` becomes ``count(1)``, and an
    :class:`Extent` is already one.
    """
    if extent is None:
        return count(1)
    if isinstance(extent, Extent):
        return extent
    if isinstance(extent, int) and not isinstance(extent, bool):
        return count(extent)
    raise TypeError(
        f"extent must be an int or an Extent (count/until/through/unknown),"
        f" got {extent!r}"
    )
