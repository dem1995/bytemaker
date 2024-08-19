from importlib.util import find_spec

if find_spec("bitarray"):
    from bytemaker.bitvector_with_bitarray_speedup import (
        BitsCastable,
        BitsConstructible,
        BitVector,
    )
else:
    raise NotImplementedError("Add non-bitarray implementation")

__all__ = ["BitVector", "BitsCastable", "BitsConstructible"]
