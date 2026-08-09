"""Regression tests for bugs surfaced by the post-apply adversarial
verification pass and the follow-up commit review:

1. twos_complement_bit_length / Int.min_bit_length used float log2, which
   under-sizes positive powers of two >= 2**49 by one bit (2**k + 1 is
   indistinguishable from 2**k in float). This silently corrupted from_int
   round-trips for those values on all three backends.
2. The option-(c) str declared-width check gated on `field_type is str`
   (identity) while the layout side maps str *subclasses* to the same 8-bit
   codec, so a multi-char str-subclass field bypassed the check and leaked
   over-width bytes on both aggregate paths.
3. plans.iter_tuples let a negative explicit count slip past the count>avail
   guard, diverging between the struct and shiftmask tiers.
4. pop(index, default=None) raised IndexError instead of returning the
   default: the out-of-bounds guard used `if default is not None`, so an
   explicit default=None was indistinguishable from "no default given".
5. The lazy conversions re-export must resolve all names and must not
   reintroduce the import cycle (importing _legacy_aggregate first must work).
"""

import subprocess
import sys
from dataclasses import dataclass

import pytest

from bytemaker.bittypes import UInt4, UInt8, UInt12
from bytemaker.bittypes.int import Int
from bytemaker.bitvector.bitvector_native import BitVector as NativeBitVector
from bytemaker.bitvector.bitvector_speedup import BitVector as SpeedupBitVector
from bytemaker.conversions.aggregate_types import (
    from_bytes_aggregate,
    to_bits_aggregate,
    to_bytes_aggregate,
)
from bytemaker.structs import Struct
from bytemaker.utils import twos_complement_bit_length

_BACKENDS = [
    pytest.param(NativeBitVector, id="native"),
    pytest.param(SpeedupBitVector, id="speedup"),
]
try:
    from bytemaker.bitvector.bitvector_with_bitarray_speedup import (
        BitVector as BitarrayBitVector,
    )

    _BACKENDS.append(pytest.param(BitarrayBitVector, id="bitarray"))
except ImportError:
    pass


# ------------------------------------------------------------- fix 1
@pytest.mark.parametrize("k", [0, 1, 7, 8, 48, 49, 50, 63, 64, 100, 200])
def test_twos_complement_bit_length_powers_of_two(k):
    # a positive power of two 2**k needs k magnitude bits + 1 sign bit
    assert twos_complement_bit_length(2**k) == k + 2


def test_twos_complement_bit_length_matches_integer_oracle():
    for n in list(range(-260, 260)) + [2**49, 2**63 + 5, -(2**49), -(2**63)]:
        if n >= 0:
            expected = n.bit_length() + 1
        else:
            expected = (~n).bit_length() + 1
        assert twos_complement_bit_length(n) == expected, n
    assert twos_complement_bit_length(0) == 1


@pytest.mark.parametrize("BitVector", _BACKENDS)
@pytest.mark.parametrize("k", [49, 50, 63, 64])
def test_from_int_roundtrips_at_power_of_two_boundary(BitVector, k):
    v = 2**k
    # size=None must size for a signed round-trip
    assert BitVector.from_int(v).to_int(signed=True) == v
    # explicit exact width round-trips; one bit short raises
    assert BitVector.from_int(v, k + 2).to_int(signed=True) == v
    with pytest.raises(ValueError):
        BitVector.from_int(v, k + 1)


def test_min_bit_length_boundary():
    assert Int.min_bit_length(2**49) == 51
    assert Int.min_bit_length(2**49, signed=False) == 50
    assert Int.min_bit_length(2**49, bin_format="signed_magnitude") == 51
    # default-width to_bitstring no longer raises for large powers of two
    assert len(Int.to_bitstring(2**49, signed=True)) == 51


# ------------------------------------------------------------- fix 2
class _MyStr(str):
    pass


@dataclass
class _StrSubRec:
    name: _MyStr


def test_str_subclass_width_check_fires_on_both_paths():
    rec = _StrSubRec(_MyStr("hi"))  # 16 bits into an 8-bit str field
    with pytest.raises(ValueError, match="one fixed-width character"):
        to_bits_aggregate(rec)
    with pytest.raises(ValueError, match="one fixed-width character"):
        to_bytes_aggregate(rec)


def test_str_subclass_single_char_still_roundtrips():
    rec = _StrSubRec(_MyStr("h"))
    b = to_bytes_aggregate(rec)
    assert b == b"h"
    assert from_bytes_aggregate(b, _StrSubRec) == rec


# ------------------------------------------------------------- fix 3
class _Aligned(Struct, endian="big"):  # struct tier
    a: UInt8
    b: UInt8


class _Shift(Struct, endian="big"):  # shiftmask tier
    a: UInt4
    b: UInt12


@pytest.mark.parametrize("plan", [_Aligned.plan, _Shift.plan])
def test_iter_tuples_rejects_negative_count(plan):
    buf = b"\x01\x02\x03\x04"
    with pytest.raises(ValueError, match="must be non-negative"):
        list(plan.iter_tuples(buf, 0, count=-1))


# ------------------------------------------------------------- fix 4
@pytest.mark.parametrize("BitVector", _BACKENDS)
def test_pop_honors_explicit_default_none(BitVector):
    v = BitVector("1010")
    # an explicit default (including None) is returned on an out-of-range index
    assert v.pop(99, default=None) is None
    assert v.pop(99, default="x") == "x"
    assert v.pop(99, default=7) == 7
    # omitting the default still raises
    with pytest.raises(IndexError):
        v.pop(99)
    with pytest.raises(IndexError, match="empty"):
        BitVector().pop()
    # an explicit default on an empty vector is returned, not raised
    assert BitVector().pop(0, default=None) is None
    # a normal pop is unchanged (returns the bit and mutates)
    assert v.pop() == 0 and v.to01() == "101"


def test_bound_bits_pop_omitted_default_still_errors():
    # BoundBits wraps a fixed-length field: pop is categorically disallowed
    # (ValueError), and an omitted default must NOT silently become None.
    class R(Struct, endian="big"):
        a: UInt8

    bb = R(a=0b10100000).sizedview.a.bits
    for call in (lambda: bb.pop(99), lambda: bb.pop(99, default=None), lambda: bb.pop()):
        with pytest.raises(ValueError, match="invariant"):
            call()


# ------------------------------------------------------------- fix 5
def test_conversions_lazy_reexport_resolves_all_names():
    import bytemaker.conversions as conv

    for name in conv.__all__:
        assert getattr(conv, name) is not None
    with pytest.raises(AttributeError):
        conv.does_not_exist


def test_legacy_aggregate_importable_first_no_cycle(tmp_path):
    # A fresh interpreter importing the reference implementation FIRST must
    # work (originally a regression guard for a real conversions/__init__
    # import cycle when the module lived at the package root; kept as an
    # import-isolation check now that it lives in conversions/).
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=repo_root)
    code = (
        "from bytemaker.conversions import _legacy_aggregate\n"
        "from bytemaker.conversions import to_bytes_aggregate, ConversionInfo\n"
        "assert to_bytes_aggregate is not None and ConversionInfo is not None\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
