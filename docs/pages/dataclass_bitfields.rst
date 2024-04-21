Dataclass Bitfields
====================

``bytemaker`` supports C-style bitfields through plain-old Python dataclasses.
To this end, it provides the methods :py:meth:`~bytemaker.aggregate_types.to_bits_aggregate` and :py:meth:`~bytemaker.aggregate_types.from_bits_aggregate` for conversion.

These methods recursively support any  ``@dataclass``-decorated classes ultimately annotated with the following types: :py:class:`~bytemaker.ytypes.YType`\s, standard-Python-library :py:data:`~bytemaker.native_types.ctypes\_.CType`\s (``c_uint8``, ``ctypes.STRUCTURE``, etc.), and Python-default :py:class:`~bytemaker.native_types.pytypes.PyType`\s (``int``, ``bool``, ``str`` (char), ``float``).

Example code
-----------------

.. code-block:: python

    import ctypes
    from bytemaker.ytypes import SInt32, Float32, Bit4
    from bytemaker.aggregate_types import to_bits_aggregate, from_bits_aggregate
    from dataclasses import dataclass

    @dataclass
    class PyTypeAggregate:
        a: int
        b: float
        c: str  # Char


    @dataclass
    class CTypeAggregate:
        a: ctypes.c_int32
        b: ctypes.c_float
        c: ctypes.c_char


    @dataclass
    class YTypeAggregate:
        a: SInt32
        b: Float32
        c: Bit4


    @dataclass
    class MixedAggregate:
        pytype_aggregate: PyTypeAggregate
        ctype_aggregate: CTypeAggregate
        ytype_aggregate: YTypeAggregate
        hp: int


    mixedagg = MixedAggregate(
        PyTypeAggregate(
            382,
            3.14,
            'A'
        ),
        CTypeAggregate(
            ctypes.c_int32(382),
            ctypes.c_float(3.14),
            ctypes.c_char('A'.encode('utf-8'))
        ),
        YTypeAggregate(
            SInt32(382),
            Float32(3.14),
            Bit4('0b0100')
        ),
        255
    )

    mixed_agg_as_bits = to_bits_aggregate(mixedagg)
    print(mixed_agg_as_bits.to_hex())

    # 0x00_00_01_7e_40_48_f5_c3_41_00_00_01_7e_40_48_f5_c3_41_00_00_01_7e_40_48_f5_c3_40_00_00_0f_f

    mixed_agg_from_bits = from_bits_aggregate(mixed_agg_as_bits, MixedAggregate)
    print(mixed_agg_from_bits)

    # MixedAggregate(
    #   pytype_aggregate=PyTypeAggregate(a=382, b=3.140000104904175, c='A'),
    #   ctype_aggregate=CTypeAggregate(a=c_long(382), b=c_float(3.140000104904175), c=c_char(b'A')),
    #   ytype_aggregate=YTypeAggregate(a=SInt32, value 382, b=Float32, value 3.140000104904175, c=Bits([0, 1, 0, 0])),
    #   hp=255)
