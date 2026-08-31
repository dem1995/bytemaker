"""Tests for the Stage-7 aggregate & utils solutions (au-1..5)."""

import typing
from dataclasses import dataclass

import pytest

from bytemaker.bittypes import UInt8, UInt16
from bytemaker.bitvector import BitVector
from bytemaker.conversions import _legacy_aggregate as legacy
from bytemaker.conversions.aggregate_types import (
    count_bits_in_unit_type,
    count_bytes_in_unit_type,
    from_bytes_aggregate,
    to_bytes_aggregate,
)
from bytemaker.utils import is_instance_of_union, twos_complement


# ------------------------------------------------------------- au-1
@pytest.mark.parametrize(
    "obj, tp, expected",
    [
        ([], typing.List[int], True),  # empty -> vacuous True
        ([1, 2], typing.List[int], True),
        (["x", "y"], typing.List[int], False),  # was blanket True
        ([1, "x"], typing.List[int], False),
        (0, typing.Literal[0, 1], True),
        (2, typing.Literal[0, 1], False),
    ],
)
def test_is_instance_of_union_element_checks(obj, tp, expected):
    assert is_instance_of_union(obj, tp) is expected


def test_is_instance_of_union_one_shot_iterator_accepted():
    assert is_instance_of_union(iter(["x"]), typing.Iterable[int]) is True


def test_contains_iterable_edge_cases():
    bv = BitVector([1, 0, 1, 1])
    assert [] in bv  # was RuntimeError
    assert [0, 1] in bv
    assert ["x"] not in bv  # was TypeError from BitVector(['x'])
    assert (b for b in [0, 1]) in bv  # generator input still works


# ------------------------------------------------------------- au-2
def test_count_bits_unsupported_type_raises():
    class NotAUnit:
        pass

    with pytest.raises(TypeError, match="Cannot count bits"):
        legacy.count_bits_in_unit_type(NotAUnit)  # oracle
    with pytest.raises(TypeError, match="Cannot count bits"):
        count_bits_in_unit_type(NotAUnit)  # cached public path
    with pytest.raises(TypeError, match="Cannot count bits"):
        count_bytes_in_unit_type(NotAUnit)  # arithmetic caller


# ------------------------------------------------------------- au-3
def test_to_bytes_aggregate_unconvertible_raises():
    class NotConvertible:
        pass

    with pytest.raises(TypeError, match="Cannot convert"):
        legacy.to_bytes_aggregate(NotConvertible())  # oracle
    with pytest.raises(TypeError, match="Cannot convert"):
        to_bytes_aggregate(NotConvertible())  # public dispatcher
    with pytest.raises(TypeError, match="Cannot convert"):
        to_bytes_aggregate(None)
    assert to_bytes_aggregate([]) == b""  # empty Iterable branch still serializes


# ------------------------------------------------------------- au-4
def test_oracle_from_bytes_is_array_returns_list():
    @dataclass
    class Pair:
        a: UInt8
        b: UInt8

    buf = bytes([1, 2, 3, 4])
    oracle_out = legacy.from_bytes_aggregate(buf, Pair, is_array=True)
    disp_out = from_bytes_aggregate(buf, Pair, is_array=True)
    assert isinstance(oracle_out, list) and len(oracle_out) == 2
    assert [(e.a.value, e.b.value) for e in oracle_out] == [(1, 2), (3, 4)]
    # oracle and dispatcher now agree (synced)
    assert [(e.a.value, e.b.value) for e in disp_out] == [
        (e.a.value, e.b.value) for e in oracle_out
    ]
    # scalar case: was a ValueError on the oracle, now decodes like the dispatcher
    scalars = legacy.from_bytes_aggregate(
        b"\x01\x00\x02\x00", UInt16, is_array=True, endianness="little"
    )
    assert [s.value for s in scalars] == [1, 2]


# ------------------------------------------------------------- au-5
def test_twos_complement_docstring_and_behavior():
    doc = twos_complement.__doc__
    assert "n_bits" in doc and ":param bits:" not in doc
    assert twos_complement(5, n_bits=8) == "00000101"
    assert twos_complement(-3, n_bits=4) == "1101"
