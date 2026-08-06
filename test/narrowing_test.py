"""Tests for the Stage-1 narrowing solutions (narrowing-1..6).

Covers the *new* behavior each solution introduces, on top of the pre-existing
narrowing coverage in structs_test.py / bittypes_test.py:

* narrowing-1 -- NarrowingWarning is attributed to the caller's frame, however
  deep the internal store chain (constructor, box setter, array field).
* narrowing-2 -- the standard struct-packed widths now warn under warn mode
  (previously silent), and the legacy one-call fast path reroutes to the boxed
  (warning) path when warn is on, with byte-identical output.
* narrowing-3 -- SInt8/16/32/64 gate struct packing on the *instance's*
  int_format, so sign-magnitude is honored at the standard widths too.
* narrowing-4 -- int_format is validated at construction (alias normalized).
* narrowing-5 -- NarrowingConfig/NarrowingWarning re-export from the subpackage.
* narrowing-6 -- the C-promotion contract is documented.
"""

import os
import warnings as pywarnings
from dataclasses import dataclass

import pytest

from bytemaker.bittypes import NarrowingConfig, NarrowingWarning  # narrowing-5
from bytemaker.bittypes.int import (
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    UInt8,
    UInt16,
    UInt64,
)
from bytemaker.conversions.aggregate_types import to_bytes_aggregate
from bytemaker.structs import Struct

_THIS_FILE = os.path.basename(__file__)


@pytest.fixture
def warn_on():
    """Enable checked-store warnings for the test, then restore the default."""
    prior = NarrowingConfig.warn
    NarrowingConfig.warn = True
    try:
        yield
    finally:
        NarrowingConfig.warn = prior


# --------------------------------------------------------------- narrowing-1
def test_warning_attributed_to_caller_frame(warn_on):
    """narrowing-1: every store path blames the user's line, not bytemaker
    internals -- so the recorded warning's filename is *this* test module."""

    class S(Struct, endian="little"):
        arr: UInt16 * 3

    s = S(arr=[0, 0, 0])

    for trigger in (
        lambda: UInt8(300),          # constructor chain
        lambda: setattr(UInt8(0), "value", 300),  # box value setter chain
        lambda: s.arr.__setitem__(0, 70000),      # deep array-field chain
    ):
        with pywarnings.catch_warnings(record=True) as rec:
            pywarnings.simplefilter("always")
            trigger()
        assert len(rec) == 1
        assert os.path.basename(rec[0].filename) == _THIS_FILE


# --------------------------------------------------------------- narrowing-2
@pytest.mark.parametrize(
    "cls, raw, expect",
    [
        (UInt8, 300, 44),
        (SInt8, 200, -56),
        (UInt16, 70000, 4464),
        (SInt16, 40000, -25536),
        (UInt64, 2**64, 0),
        (SInt32, 2**31, -(2**31)),
    ],
)
def test_standard_widths_warn_under_warn_mode(warn_on, cls, raw, expect):
    """narrowing-2: the widths users reach for most (backed by struct.pack)
    used to wrap silently; now they warn and store the wrapped value."""
    with pytest.warns(NarrowingWarning):
        constructed = cls(raw)
    assert constructed.value == expect

    box = cls(0)
    with pytest.warns(NarrowingWarning):
        box.value = raw
    assert box.value == expect


@pytest.mark.parametrize("cls, ok", [(UInt8, 44), (SInt8, -56), (UInt16, 4464)])
def test_in_range_stores_stay_silent(warn_on, cls, ok):
    with pywarnings.catch_warnings():
        pywarnings.simplefilter("error")  # any NarrowingWarning -> failure
        assert cls(ok).value == ok


def test_legacy_aggregate_reroutes_and_warns_in_warn_mode():
    """narrowing-2 companion: the all-plain-numbers fast path bails to the
    boxed coercion path under warn mode so the warnings fire there too --
    and the bytes are identical to the silent path."""

    @dataclass
    class TwoWidths:
        a: UInt8
        b: UInt16

    rec = TwoWidths(300, 70000)  # plain ints -> eligible for the fast path

    quiet = NarrowingConfig.warn
    NarrowingConfig.warn = False
    try:
        silent_bytes = to_bytes_aggregate(rec, endianness="little")
        NarrowingConfig.warn = True
        with pywarnings.catch_warnings(record=True) as w:
            pywarnings.simplefilter("always")
            warned_bytes = to_bytes_aggregate(rec, endianness="little")
    finally:
        NarrowingConfig.warn = quiet

    assert warned_bytes == silent_bytes  # reroute is byte-transparent
    assert sum(isinstance(x.message, NarrowingWarning) for x in w) == 2


# --------------------------------------------------------------- narrowing-3
@pytest.mark.parametrize("cls, n", [(SInt8, 8), (SInt16, 16), (SInt32, 32), (SInt64, 64)])
def test_struct_packed_sint_honors_instance_int_format(cls, n):
    """narrowing-3: the standard signed widths gate packing on their own
    int_format, so a per-instance sign-magnitude request is honored (it was
    silently packed two's complement before)."""
    s = cls(0, int_format="signed_magnitude")
    s.value = -5
    assert s.bits.to01() == "1" + "0" * (n - 4) + "101"
    assert s.skip_struct_packing is True
    # default (two's complement) is unchanged and still struct-packed
    assert cls(-5).bits.to01() == "1" * (n - 3) + "011"
    assert cls(0).skip_struct_packing is False


# --------------------------------------------------------------- narrowing-4
def test_sint_construction_validates_int_format():
    """narrowing-4: a typo raises immediately, naming the valid choices; the
    undocumented 'sign_magnitude' alias is normalized-and-accepted."""
    for bad in ("twos-complement", ""):
        with pytest.raises(ValueError, match="int_format must be one of"):
            SInt8(5, int_format=bad)
    assert SInt8(5, int_format="sign_magnitude").int_format == "signed_magnitude"


# --------------------------------------------------------------- narrowing-5/6
def test_narrowing_names_reexported_from_bittypes():
    import bytemaker
    import bytemaker.bittypes as bt

    assert "NarrowingConfig" in bt.__all__ and "NarrowingWarning" in bt.__all__
    assert bt.NarrowingConfig is bytemaker.NarrowingConfig
    assert bt.NarrowingWarning is bytemaker.NarrowingWarning


def test_int_module_documents_promotion_contract():
    import bytemaker.bittypes.int as m

    assert m.__doc__ is not None
    assert "promotion model" in m.__doc__
    assert "narrowing cast" in m.__doc__  # unwrapped in the module docstring
    # the class docstring carries the same contract (line-wrapping tolerant)
    class_doc = " ".join(m.Int.__doc__.split())
    assert "promotion model" in class_doc
    assert "narrowing cast" in class_doc
