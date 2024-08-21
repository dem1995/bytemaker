Quickstart
############

Overview
============
``bytemaker`` revolves around three types of classes:

* :py:class:`~bytemaker.bitvector.BitVector` for bit-level manipulation
* :py:mod:`~bytemaker.bittypes` for interacting with C-like type abstractions
* ``bytemaker.conversions`` for laying out bittype/Python type/ctype objects and converting to/from :py:class:`~bytemaker.bitvector.BitVector`s.

Installation
=============
To install ``bytemaker``, run ``python -m pip install bytemaker``. You can also install development versions by cloning `/dev` branch
on GitHub and running ``python -m pip install bytemaker``.


Example
=============

.. code-block:: python

    from bytemaker.bitvector import BitVector
    from bytemaker.bittypes import SInt16, UInt16, Buffer128, Str64
    from bytemaker.conversions.aggregate_types import to_bits_aggregate, from_bits_aggregate
    from dataclasses import dataclass

    @dataclass
    class SaveInfo:
        name: Str64
        xpos: SInt16
        ypos: SInt16
        health: UInt16,
        inventory: Buffer128

    # Where rom_piece is some bytes object

    rom_piece_bits = BitVector(rom_piece)
    save_info = from_bits_aggregate(SaveInfo, rom_piece_bits)
    print(save_info)


.. toctree::
    :maxdepth: 1
    :caption: Quickstart

    notebooks/bitvector
    notebooks/bittypes
    notebooks/conversions
