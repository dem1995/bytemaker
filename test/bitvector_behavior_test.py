"""Tests for the Stage-3 BitVector behavioral divergences (bb-1..8).

bb-8 (pop) is covered in bitvector_implementations_test.py. This module locks
in the other cross-backend divergences, parameterized over every available
backend so the three implementations stay in lockstep.
"""

from typing import get_args

import pytest

import bytemaker.bitvector.bitvector_native as native_mod
import bytemaker.bitvector.bitvector_speedup as speedup_mod
from bytemaker.bitvector import FixedLengthBitVector
from bytemaker.bitvector.bitvector_native import BitVector as NativeBitVector
from bytemaker.bitvector.bitvector_speedup import BitVector as SpeedupBitVector

_IMPLS = [
    pytest.param(NativeBitVector, id="native"),
    pytest.param(SpeedupBitVector, id="speedup"),
]
_MODULES = [native_mod, speedup_mod]
try:
    import bitarray as _bitarray_pkg

    import bytemaker.bitvector.bitvector_with_bitarray_speedup as bitarray_mod
    from bytemaker.bitvector.bitvector_with_bitarray_speedup import (
        BitVector as BitarrayBitVector,
    )

    _IMPLS.append(pytest.param(BitarrayBitVector, id="bitarray"))
    _MODULES.append(bitarray_mod)
except ImportError:  # optional dependency
    _bitarray_pkg = None


@pytest.fixture(params=_IMPLS, name="BitVector")
def _bitvector(request):
    return request.param


# --------------------------------------------------------------- bb-1 (fixed.py)
def test_fixed_setitem_compares_coerced_bit_length():
    f = FixedLengthBitVector("0b" + "0" * 8)
    with pytest.raises(ValueError):
        f[0:3] = "0x0"  # len 3 but 4 bits -> would resize
    assert len(f) == 8

    f2 = FixedLengthBitVector(bytes(2))
    f2[0:8] = bytes([0xFF])  # 8 bits, length-preserving -> now accepted
    assert f2.to01() == "1111111100000000"

    f3 = FixedLengthBitVector("0b11110000")
    f3[0:2] = "0b11"
    assert f3.to01() == "11110000"
    f3[0:3] = 1  # int broadcast
    assert f3.to01()[:3] == "111" and len(f3) == 8
    with pytest.raises(ValueError):
        f3[0:3] = "11"


# --------------------------------------------------------------- bb-2
def test_startswith_endswith_accept_bytearray_memoryview(BitVector):
    v = BitVector(bytes([0xDE, 0xAD]))
    assert v.startswith(bytearray([0xDE]))
    assert v.startswith(memoryview(bytes([0xDE])))
    assert v.endswith(bytearray([0xAD]))
    assert not v.startswith(bytearray([0xAD]))


# --------------------------------------------------------------- bb-3
def test_mutators_coerce_bits_uniformly(BitVector):
    v = BitVector("0101")
    v.append(1.0)
    v.insert(0, 0.0)
    assert v.to01() == "001011"
    v.remove(1.0)
    assert v.to01() == "00011"
    w = BitVector("1")
    w.extend([1.0, False, True])
    assert w.to01() == "1101"
    for op in (
        lambda x: x.append("1"),
        lambda x: x.insert(0, "0"),
        lambda x: x.remove("1"),
        lambda x: x.extend(["1"]),
    ):
        with pytest.raises(ValueError, match="bit must be 0 or 1"):
            op(BitVector("0101"))


# --------------------------------------------------------------- bb-4
def test_extended_slice_length_mismatch_raises(BitVector):
    v = BitVector("00000000")
    with pytest.raises(ValueError):
        v[1:8:2] = BitVector("")  # empty value: silent-delete quirk closed
    assert v.to01() == "00000000"
    with pytest.raises(ValueError):
        v[::2] = ""
    v[2:2:2] = BitVector("")  # empty span, empty value: no-op
    assert v.to01() == "00000000"
    v2 = BitVector("1101")
    v2[::-1] = "0011"  # negative-step full assignment still works
    assert v2.to01() == "1100"


# --------------------------------------------------------------- bb-5
def test_runtime_union_includes_byte_likes():
    for mod in _MODULES:
        types = {a for a in get_args(mod.BitsConstructible) if isinstance(a, type)}
        assert {bytes, bytearray, memoryview, str} <= types


# --------------------------------------------------------------- bb-6
def test_equality_reserved_for_bitvectors(BitVector):
    v = BitVector("0b101")
    assert v == BitVector("0b101")
    assert v != BitVector("0b100")
    assert (v == "101") is False  # str is not a BitVector
    if _bitarray_pkg is not None:
        ba = _bitarray_pkg.bitarray("101")
        assert (v == ba) is False
        assert (ba == v) is False
        assert v != ba
    # FixedLengthBitVector is a BitVector subclass -> compares by value
    assert FixedLengthBitVector("0b101") == FixedLengthBitVector("0b101")


# --------------------------------------------------------------- bb-7
def test_to_bytes_is_whole_vector_right_aligned(BitVector):
    assert BitVector("0b101").to_bytes() == b"\x05"
    assert bytes(BitVector("0b101")) == b"\xa0"  # tobytes stays left-aligned
    assert BitVector("0b100000011").to_bytes() == b"\x01\x03"
    assert BitVector("0b0100000011").to_bytes() == b"\x01\x03"
    assert BitVector("0b0100000011").to_int(signed=False) == 259  # latent bug fixed
    assert BitVector("0b00001111").to_bytes() == b"\x0f"  # byte-aligned unchanged
    assert BitVector().to_bytes() == b""
    for w in range(1, 18):
        v = BitVector("1" * w)
        assert int.from_bytes(v.to_bytes(), "big") == v.to_int(signed=False)


# ---------------------------------------------------------------- polish-5
def test_to_chararray_raises_valueerror_on_non_byte_aligned(BitVector):
    # bare assert -> explicit ValueError (survives python -O; names the length)
    with pytest.raises(ValueError, match=r"length 3 is not a multiple of 8"):
        BitVector("0b101").to_chararray("utf-8")
    assert BitVector(b"hi").to_chararray("utf-8") == "hi"  # byte-aligned unaffected


# ------------------------------------------------------------- polish-1 / polish-4
def test_bitvector_docstring_pins():
    for mod in _MODULES:
        assert "0o" in mod.BitVector.oct.__doc__  # polish-1
        assert "0b" in mod.BitVector.bin.__doc__  # polish-1
        assert "0x" in mod.BitVector.hex.__doc__
        bits_castable = getattr(mod, "BitsCastable", None)
        if bits_castable is not None and bits_castable.__Bits__.__doc__:
            assert "deep" not in bits_castable.__Bits__.__doc__  # polish-4
            assert "live view" in bits_castable.__Bits__.__doc__
