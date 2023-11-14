Bits
======

``bytemaker`` provides a mutable :py:class:`~bytemaker.bits.Bits` class analogous to `bytearray`. It features the typical `bytearray` methods, ready conversion to/from `bytes` and `bytearray` objects, and a variety of quality-of-life methods for bit manipulation.

:py:class:`~bytemaker.bits.Bits` is also the base class for the various :py:class:`~bytemaker.ytypes.YType`\s, allowing for ready conversion and manipulation of low-level data types.

Example code:
---------------


.. code-block:: python

    from bytemaker.bits import Bits

    #  Construction
    bits = Bits('0b101')
    print(bits)
    # [1, 0, 1]

    # Concatenation
    bits += Bits('0b1')
    print(bits)
    # 0b1011

    # Padding
    bits.padleft(up_to_size=8, inplace=True)
    print(bits)
    # 0b00001011
    bits[0] = 1
    # 0b10001011

    # Hex representation
    print(bits.to_hex())
    # 0x8B

    # Slicing
    print(bits[-4:])
    # "0b1011"

    # Bytes to/from conversion
    bits_as_bytes = bytes(bits)
    print(bits_as_bytes)
    # b'\x8b'
    bytes_as_bits = Bits(bits_as_bytes)
    print(bytes_as_bits)
    # 0b10001011

    # Joining
    print(Bits('0xFF').join([bits, bits, bits]))
    # 0b10001011_11111111_10001011_11111111_10001011

    # Shifting
    bits_lshifted = bits << 4
    print(bits_lshifted)
    # 0b10110000

    # Binary operators
    bits_orred = bits | Bits('0b01010101')
    print(bits, "|", Bits('0b01010101'))
    print(bits_orred)
    #
    # 0b11011111
    bits_xored = bits ^ Bits('0b01010101')
    print(bits)
    print(bits_xored)

    # And more...
