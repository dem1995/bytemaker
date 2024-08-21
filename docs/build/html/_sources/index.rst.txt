.. _bytemaker_docs_mainpage:

###################
Bytemaker documentation
###################


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

``bytemaker`` is a Python 3.8-compatible library for byte serialization/deserialization. It brings C bitfield functionality over to Python version 3.8+. To that end, it provides methods and types for converting ``@dataclass``-decorated classes.


What can you do with it?
------------------------

``bytemaker`` gives you the following:

- A :py:class:`~bytemaker.bitvector.BitVector` class analogous to Python's ``bytes`` and ``bytearray`` classes, but for sub-byte bit quantities. :py:class:`~bytemaker.bitvector.BitVector` readily supports conversion between bit representations and various C customizable data types.
- A set of :py:mod:`~bytemaker.bittypes` classes, including various-sized buffers, unsigned/signed ints, floats, and strings, that have underlying :py:class:`~bytemaker.bitvector.BitVector` representations.
- Support for serializing/deserializing ``@dataclass``-decorated classes, where the annotations can be :py:mod:`~bytemaker.bittypes`\s, standard-library :py:data:`~bytemaker.conversions.ctypes\_.CType`\s (``c_uint8``, ``ctypes.STRUCTURE``, etc.), or Python-default :py:class:`~bytemaker.conversions.pytypes.PyType`\s (``int``, ``bool``, ``str`` (char), ``float``). Nested types? No problem!
- Automagic support for handling any of the aforementioned objects via :py:meth:`bytemaker.conversions.aggregate_types.to_bits_aggregate` and :py:meth:`bytemaker.aggregate_types.from_bits_aggregate`.




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
