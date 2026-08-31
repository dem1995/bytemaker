Quickstart
############

Overview
============
``bytemaker`` is organized in three layers:

* :py:class:`~bytemaker.structs.Struct` for declaring binary records —
  the headline API
* :py:mod:`bytemaker.spaces` for whole address spaces: reading and editing
  records in place, patches, pointers and coverage reports
* the bit-level layer underneath:
  :py:class:`~bytemaker.bitvector.BitVector` for bit-level manipulation,
  :py:mod:`~bytemaker.bittypes` for boxed C-like values, and
  ``bytemaker.conversions`` for the original ``@dataclass`` aggregate API

Installation
=============
To install ``bytemaker``, run ``python -m pip install bytemaker``. You can also install development versions by cloning `/dev` branch
on GitHub and running ``python -m pip install bytemaker``.


Example
=============

.. code-block:: python

    from bytemaker import Struct, s16, u16, u32

    class SaveInfo(Struct, endian="little"):
        xpos:   s16
        ypos:   s16
        health: u16
        gold:   u32

    # Where save is a bytearray holding a save file

    info = SaveInfo.parse(save[0x10:0x1A])
    print(info)            # SaveInfo(xpos=10, ypos=-12, health=99, gold=1000)

    info.health = 999
    save[0x10:0x1A] = info.pack()

Reading records straight out of an address space, with the base address and
byte order stated once:

.. code-block:: python

    from bytemaker.spaces import Space

    rom = Space(data, base=0x08000000, endian="little")
    info = rom.read(0x08000010, SaveInfo)

The notebooks below tour the bit-level layer.

.. toctree::
    :maxdepth: 1
    :caption: Bit-level quickstarts

    notebooks/bitvector
    notebooks/bittypes
    notebooks/conversions
