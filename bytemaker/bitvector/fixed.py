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
    """A BitVector that rejects every length-changing mutation.

    Content mutations behave exactly as they do on :class:`BitVector`. That
    covers item writes, length-preserving slice writes, ``reverse()``, and
    the rest.

    Length-changing operations raise :class:`ValueError` instead. Those are
    ``append``, ``extend``, ``insert``, ``pop``, ``remove``, ``clear``,
    ``del b[i]``, ``+=``, ``*=``, length-changing slice assignment, and the
    in-place growers ``frombytes`` and ``fromfile``. Make a resizable copy
    with ``BitVector(b)``.

    Storage is writable and unaliased on every backend, because the base
    constructor copies all source-form inputs, byte-likes included. That is
    the 13 #16 ruling, and the parity suite pins the guarantee at the
    ``BitVector`` level. This class used to copy byte sources itself, to
    shield boxes from the bitarray backend's zero-copy import.
    """

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
            # Compare the *bit length* of the coerced value, not the raw
            # element count: e.g. len('0x0') is 3 but BitVector('0x0') is
            # 4 bits, and len(bytes([0xFF])) is 1 but 8 bits.
            if not isinstance(value, BitVector):
                value = BitVector(value)
            if len(value) != span:
                raise self._length_violation()
        super().__setitem__(key, value)
