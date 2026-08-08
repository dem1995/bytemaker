"""Tests for the Stage-12 docs & API-surface solutions (docs-misc-1..5)."""

import ast

import pytest

import bytemaker.fields as fields
from bytemaker.bittypes.float import Float16
from bytemaker.bittypes.int import (
    Int,
    SInt,
    SInt8,
    SInt16,
    SInt32,
    SInt64,
    UInt6,
    UInt8,
    UInt16,
)


# ------------------------------------------------------------- docs-misc-1
@pytest.mark.parametrize(
    "x",
    [
        UInt6(40),
        UInt16(0xBEEF),
        SInt8(-5),
        Float16(1.5),
        Float16(float("nan")),
        SInt8(bits="10000101", int_format="signed_magnitude"),
        UInt8(1, endianness="little"),
    ],
)
def test_repr_is_eval_roundtrippable(x):
    y = eval(repr(x), {type(x).__name__: type(x)})
    assert type(y) is type(x)
    assert y.bits.to01() == x.bits.to01()
    assert y.endianness == x.endianness


def test_repr_format_pins():
    assert repr(UInt6(40)) == "UInt6(bits='101000', endianness='big')"
    # SInt appends int_format so the same bits decode to the right value
    sm = SInt8(bits="10000101", int_format="signed_magnitude")
    assert repr(sm).endswith("int_format='signed_magnitude')")
    assert eval(repr(sm), {"SInt8": SInt8}).value == sm.value == -5
    assert "recreate" in UInt8.__repr__.__doc__ or "recreates" in UInt8.__repr__.__doc__


# ------------------------------------------------------------- docs-misc-2
def test_to_pyint_docstring_and_behavior():
    doc = Int.to_pyint.__doc__
    assert "bitstring (str)" not in doc and "- self" in doc
    assert Int.to_pyint("1010") == -6
    assert Int.to_pyint("1010", signed=False) == 10
    assert SInt8(-5).to_pyint() == -5
    assert UInt8(200).to_pyint() == 200


# ------------------------------------------------------------- docs-misc-3
def test_sint_docstring_points_at_signedconfig():
    assert "SignedConfig" in SInt.__doc__ and "`Config`" not in SInt.__doc__
    assert SInt.__doc__.count("SignedConfig") == 2


# ------------------------------------------------------------- docs-misc-4
def test_fields_pyi_all_matches_runtime():
    src = open(fields.__file__[:-3] + ".pyi", encoding="utf-8").read()
    stub_all = next(
        ast.literal_eval(n.value)
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "__all__"
    )
    assert stub_all == fields.__all__


# ------------------------------------------------------------- docs-misc-5
@pytest.mark.parametrize("T", [SInt8, SInt16, SInt32, SInt64])
def test_setter_reject_path_reachable_at_standard_widths(T):
    # narrowing-3's per-instance gate makes the setter comment's
    # "reject out-of-range" claim true for the standard widths too.
    x = T(0, int_format="signed_magnitude")
    with pytest.raises(ValueError):
        x.value = 2 ** (T.num_bits - 1)  # out of sign-magnitude range
