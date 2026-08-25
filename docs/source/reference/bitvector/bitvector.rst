bitvector package
=================

The ``bitvector`` package provides :class:`~bytemaker.bitvector.BitVector`,
the ``bytes``/``bytearray`` analogue for sub-byte bit quantities, and
:class:`~bytemaker.bitvector.FixedLengthBitVector`.

Three interchangeable backends implement the same ``BitVector`` API.
``bytemaker.bitvector.bitvector`` selects one at import time: the
bitarray-backed implementation
(``bytemaker.bitvector.bitvector_with_bitarray_speedup``) when the optional
``bitarray`` dependency is installed, and the pure-Python implementation
(``bytemaker.bitvector.bitvector_speedup``) otherwise. A straightforward
reference implementation (``bytemaker.bitvector.bitvector_native``) is kept
for comparison and testing. The API below is documented from the
pure-Python backend; the structural contract all backends satisfy lives in
``bitvector.pyi``.

Modules
-------

BitVector
^^^^^^^^^

.. automodule:: bytemaker.bitvector.bitvector_speedup
   :members:
   :undoc-members:
   :show-inheritance:

FixedLengthBitVector
^^^^^^^^^^^^^^^^^^^^

.. automodule:: bytemaker.bitvector.fixed
   :members:
   :undoc-members:
   :show-inheritance:
