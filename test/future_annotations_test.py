"""Regression tests for PEP 563 stringized annotations.

This module imports ``from __future__ import annotations`` at the top, which
turns every dataclass field annotation below into a string (e.g. "SInt16")
instead of the type object. Aggregate (de)serialization must resolve those
strings in the *defining module's* namespace via typing.get_type_hints. A
previous implementation used a bare ``eval`` that resolved them in bytemaker's
own namespace, raising ``NameError: name 'SInt16' is not defined`` for any
caller that used this future import.
"""

from __future__ import annotations

from dataclasses import dataclass

from bytemaker.bittypes import SInt16, UInt8, UInt16
from bytemaker.conversions.aggregate_types import (
    count_bits_in_aggregate_type,
    from_bits_aggregate,
    from_bytes_aggregate,
    to_bits_aggregate,
    to_bytes_aggregate,
)


@dataclass
class Vitals:
    hp: SInt16  # signed, so 0xFFFF -> -1
    max_hp: UInt16


@dataclass
class WithNested:
    tag: UInt8
    vitals: Vitals


def test_count_bits_with_stringized_annotations():
    assert count_bits_in_aggregate_type(Vitals) == 32
    assert count_bits_in_aggregate_type(WithNested) == 8 + 32


def test_to_from_bytes_with_stringized_annotations():
    raw = to_bytes_aggregate(Vitals(SInt16(-1), UInt16(100)))
    assert raw == b"\xff\xff\x00\x64"
    result = from_bytes_aggregate(raw, Vitals)
    assert result.hp.value == -1
    assert result.max_hp.value == 100


def test_to_from_bits_with_stringized_annotations():
    original = Vitals(SInt16(-50), UInt16(999))
    bits = to_bits_aggregate(original)
    result = from_bits_aggregate(bits, Vitals)
    assert result.hp.value == -50
    assert result.max_hp.value == 999


def test_nested_dataclass_with_stringized_annotations():
    original = WithNested(UInt8(7), Vitals(SInt16(-1), UInt16(100)))

    bits = to_bits_aggregate(original)
    from_bits = from_bits_aggregate(bits, WithNested)
    assert from_bits.tag.value == 7
    assert from_bits.vitals.hp.value == -1
    assert from_bits.vitals.max_hp.value == 100

    raw = to_bytes_aggregate(original)
    from_bytes = from_bytes_aggregate(raw, WithNested)
    assert from_bytes.tag.value == 7
    assert from_bytes.vitals.hp.value == -1
    assert from_bytes.vitals.max_hp.value == 100
