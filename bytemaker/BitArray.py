from importlib.util import find_spec

if find_spec("bitarray"):
    from bytemaker.BitArray_with_bitarray_speedup import (
        BitArray,
        BitsCastable,
        BitsConstructible,
    )
else:
    raise NotImplementedError("Add non-bitarray implementation")

__all__ = ["BitArray", "BitsCastable", "BitsConstructible"]
