API Reference
=============

``bytemaker``'s API is layered. Records (:mod:`~bytemaker.structs`) are the
headline; the :mod:`~bytemaker.rom` package says where records live;
:mod:`~bytemaker.adapters` state per-field encoding conventions; and
:mod:`~bytemaker.introspect` answers shape and size questions about any of
it. Underneath, :mod:`~bytemaker.bittypes` boxes single C-style values and
:class:`~bytemaker.bitvector.BitVector` handles sub-byte data.

Records
-------

:class:`~bytemaker.structs.Struct` record classes, the layout plans compiled
for them, and the ``u8``/``s16`` field aliases.

.. toctree::
   :maxdepth: 3

   structs/structs

Address spaces and patches
--------------------------

:class:`~bytemaker.rom.Space`, :class:`~bytemaker.rom.Entry`,
:class:`~bytemaker.rom.Patch`, :class:`~bytemaker.rom.Ptr` and coverage
reporting — reading and editing records in place (ROM images, save files,
memory dumps).

.. toctree::
   :maxdepth: 3

   rom/rom

Encoding conventions
--------------------

Declarative wire ↔ user transforms, applied per field or fused onto a wire
type.

.. toctree::
   :maxdepth: 3

   adapters/adapters

Introspection
-------------

``sizeof``, ``layout``, ``offset_of`` and friends, for any schema object.

.. toctree::
   :maxdepth: 3

   introspect/introspect

Bit-level foundations
---------------------

:mod:`~bytemaker.bittypes` provides boxed C-like values (ints, floats,
strings, buffers) backed by bit representations;
:mod:`~bytemaker.bitvector` is the ``bytes``/``bytearray`` analogue for
sub-byte bit quantities.

.. toctree::
   :maxdepth: 3

   bittypes/bittypes
   bitvector/bitvector

Legacy conversions
------------------

The original ``@dataclass`` aggregate API and the C-type/Python-type
conversion helpers it builds on. Still supported.

.. toctree::
   :maxdepth: 3

   conversions/conversions

Other modules
-------------

.. toctree::
   :maxdepth: 2

   other_modules/other_modules
