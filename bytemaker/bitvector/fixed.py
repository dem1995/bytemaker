"""A BitVector whose length is invariant.

This backs :class:`~bytemaker.bittypes.BitType` storage under the live-bits
policy: handouts of a box's bits are *live* (index and length-preserving
slice writes go through to the box), but a box's width is invariant, so any
mutation that would change the length raises :class:`ValueError` instead of
silently corrupting the box (e.g. a "6-bit" UInt6 reading 113). It is the
mutable-content sibling of the ``FrozenBitVector`` TODO in ``bitvector.pyi``.

Assignment *into* a box snapshots (``u.bits = bv`` copies ``bv`` into locked
storage), so a caller's vector never becomes a hidden alias of a box.
"""

from bytemaker.bitvector.bitvector import BitVector


class FixedLengthBitVector(BitVector):
    """A BitVector rejecting all length-changing mutation.

    Item writes, length-preserving slice writes, ``reverse()``, and other
    content mutations behave exactly like :class:`BitVector`. ``append``,
    ``extend``, ``insert``, ``pop``, ``remove``, ``clear``, ``del b[i]``,
    ``+=``, ``*=``, and length-changing slice assignment raise
    :class:`ValueError`. Make a resizable copy with ``BitVector(b)``.

    Storage is guaranteed *writable and unaliased*: the bitarray backend
    zero-copy imports ``bytes`` buffers read-only (which would make the
    live ``.bits[i] = x`` write-through silently impossible for byte-built
    boxes) and ``bytearray`` buffers as live aliases (which would let a
    caller's later mutation reach inside a box), so byte sources are
    copied into a fresh ``bytearray`` here.
    """

    def __new__(cls, source=None, *args, **kwargs):
        if isinstance(source, (bytes, bytearray)):
            source = bytearray(source)
        return super().__new__(cls, source, *args, **kwargs)

    def _length_violation(self):
        return ValueError(
            f"length is invariant ({len(self)} bits): width-changing"
            f" mutation is not allowed on a FixedLengthBitVector; make a"
            f" resizable copy with BitVector(...) first"
        )

    def append(self, value):
        raise self._length_violation()

    def extend(self, values):
        raise self._length_violation()

    def insert(self, index, value):
        raise self._length_violation()

    def pop(self, index=None, default=None):
        raise self._length_violation()

    def remove(self, value):
        raise self._length_violation()

    def clear(self):
        raise self._length_violation()

    def __delitem__(self, key):
        raise self._length_violation()

    def __iadd__(self, other):
        raise self._length_violation()

    def __imul__(self, count):
        raise self._length_violation()

    # bitarray-backend extras that grow in place; harmless no-such-method
    # equivalents on the other backends.
    def frombytes(self, data):
        raise self._length_violation()

    def fromfile(self, f, n=-1):
        raise self._length_violation()

    def __setitem__(self, key, value):
        # Length-preserving writes pass through; a step-1 slice assigned a
        # different-length value would resize, so pre-check and refuse.
        # (An int value broadcasts across the slice: always preserving.)
        if isinstance(key, slice) and not isinstance(value, int):
            span = len(range(*key.indices(len(self))))
            try:
                vlen = len(value)
            except TypeError:
                value = BitVector(value)
                vlen = len(value)
            if vlen != span:
                raise self._length_violation()
        super().__setitem__(key, value)
