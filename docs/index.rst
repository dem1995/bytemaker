.. bytemaker documentation master file, created by
   sphinx-quickstart on Mon Nov 13 11:08:33 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

What is it?
-----------------------

``bytemaker`` is a Python 3.8-compatible zero-dependency library for byte serialization/deserialization. It brings C bitfield functionality over to Python version 3.8+. To that end, it provides methods and types for converting ``@dataclass``-decorated classes.


What can you do with it?
------------------------

``bytemaker`` gives you the following:

- A :py:class:`~bytemaker.bits.Bits` class analogous to Python's ``bytes`` and ``bytearray`` classes, but for sub-byte bit quantities. :py:class:`~bytemaker.bits.Bits` readily supports conversion from and to both, as well as lists and bit/octet/hex strings.
- A set of :py:mod:`~bytemaker.ytypes` classes, including various-sized Bit classes, various-sized Byte classes, common memory-specified types (U8, U16, U32, U64, S8, S16..., and Float16, Float32, Float64), and factories to create these and chararrays to arbitrary bitcounts. All of these can be instantiated from their respective types, derive from ``Bits`` (and thus can be instantiated in the same way ``Bits`` objects can), and can be cast into each other in additional ways as needed.
- Support for serializing/deserializing ``@dataclass``-decorated classes, where the annotations can be :py:class:`~bytemaker.ytypes.YType`\s, a standard-Python-library :py:data:`~bytemaker.native_types.ctypes\_.CType`\s (``c_uint8``, ``ctypes.STRUCTURE``, etc.), or Python-default :py:class:`~bytemaker.native_types.pytypes.PyType`\s (``int``, ``bool``, ``str`` (char), ``float``). Nested types? No problem!
- Automagic support for handling any of the aforementioned objects via ``aggregate_types.to_bits_aggregate`` and ``aggregate_types.from_bits_aggregate``.

How do I install it?
---------------------

First, make sure you have Python 3.8 or greater.
Then, run ``python -m pip install bytemaker``.

What's up with the union-class typing nonsense?
------------------------------------------------
Python 3.8 is missing many type-checking quality-of-life features of Python 3.9+, one of which being the ability to use ``isinstance`` and ``issubclass`` on union types. Python 3.8 is the last version to officially support Windows 7, however, so some projects still need 3.8 (and, further, Windows 7 users can use it out of the box). Further, the way ``bytemaker`` is implemented presents no forward-compatibility issues as of Python 3.12 (the most recent version at time of writing).

Index
--------------------

.. toctree::
   :maxdepth: -1
   :caption: Contents:

   Overview <self>
   Bits <pages/bits>
   Dataclass Bitfields <pages/dataclass_bitfields>
   YTypes <source/bytemaker.ytypes>
   source/modules
   source/sub_index
