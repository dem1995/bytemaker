.. _bytemaker_docs_mainpage:

#########################
Bytemaker documentation
#########################


.. toctree::
   :maxdepth: 2
   :hidden:

   Quickstart Guide <quickstart/index>
   API Reference <reference/index>


**Version**: |version|

**Useful links**:
`Source Repository <https://github.com/dem1995/bytemaker>`_ |
`Issue Tracker <https://github.com/dem1995/bytemaker/issues>`_


What is it?
-----------------------

``bytemaker`` is a pure-Python library (3.8+) for C-style binary records
and bit manipulation. You declare a record's layout as a class; parsing and
packing are compiled once from that declaration, and fields hold plain
Python values (``int``, ``float``, ``str``, ``bytes``)::

   from bytemaker import Struct, u8, u16

   class Monster(Struct, endian="little"):
       species: u8
       hp:      u16
       attack:  u16

   m = Monster.parse(rom[0x100:0x105])
   m.hp = 999
   rom[0x100:0x105] = m.pack()


What can you do with it?
------------------------

- Declare :py:class:`~bytemaker.structs.Struct` records with C-style fields
  of any bit width (``u8``, ``s16``, ``u31``, …), nested records, arrays,
  strings with custom encodings, and per-field endianness.
- Work with whole address spaces via :py:mod:`bytemaker.rom`: a
  :py:class:`~bytemaker.rom.Space` reads and writes records by address, a
  :py:class:`~bytemaker.rom.Patch` records edits you can verify, invert and
  export (including IPS), a :py:class:`~bytemaker.rom.Ptr` is a typed
  address you can follow, and coverage reports show claims, overlaps and
  gaps.
- State encoding conventions once, in the schema, with
  :py:mod:`bytemaker.adapters` (bias, fixed-point, scaling, enums, pointer
  encodings) instead of at every call site.
- Answer shape and size questions with :py:mod:`bytemaker.introspect`
  (``sizeof``, ``layout``, ``offset_of``, ``span_of``).
- Drop below the record layer when needed: :py:mod:`~bytemaker.bittypes`
  boxes single C-like values (ints, floats, strings, buffers), and
  :py:class:`~bytemaker.bitvector.BitVector` is a ``bytes``/``bytearray``
  analogue for sub-byte bit quantities.
- Keep using the original ``@dataclass`` aggregate API
  (:py:mod:`bytemaker.conversions.aggregate_types`) — it remains supported.




.. raw:: html

   <div style="height: 20px;"></div>

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card::
      :img-top: ../source/_static/compass-solid.svg
      :text-align: center

      **Quickstart guide**
      ^^^^^^^^^^^^^^^^^^^^

      Use the quickstart guide to familiarize yourself with the basics of bytemaker.

      :doc:`To the quickstart guide <quickstart/index>`

   .. grid-item-card::
      :text-align: center

      .. image:: ../source/_static/book-open-solid.svg
         :align: center
         :height: 100px

      **API reference**
      ^^^^^^^^^^^^^^^^^

      For more in-depth details of the library, refer to the API reference.

      :doc:`To the API reference <reference/index>`
