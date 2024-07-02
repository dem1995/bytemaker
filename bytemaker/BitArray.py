from importlib.util import find_spec

if find_spec("bitarray"):
    from bytemaker.BitArray_with_bitarray_speedup import BitArray, BitsCastable
else:
    raise NotImplementedError("TODO")

__all__ = ["BitArray", "BitsCastable"]
