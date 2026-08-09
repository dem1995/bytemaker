"""Tests for the size/introspection front door (wd-2):
sizeof / bitsizeof / fields_of."""

import pytest

from bytemaker import (
    Array,
    FieldInfo,
    Struct,
    bitsizeof,
    field,
    fields_of,
    sizeof,
    u8,
    u16,
)
from bytemaker.adapters import biased
from bytemaker.bittypes import Buffer, UInt4, UInt16, UInt32, UTF8String
from bytemaker.fields import s5

Name4 = UTF8String.of(nbytes=4, name="Name4I")
Buf2 = Buffer.of(nbytes=2, name="Buf2I")


class Inner(Struct, endian="big"):
    x: UInt16


class Rec(Struct, endian="little"):
    hp: u16
    name: Name4
    inner: Inner
    colors: list = field(Array.of(UInt16, 3))
    raw: Buf2
    tag: int = field(UInt16, adapt=biased(1), default=0)


def test_bitsizeof_every_schema_shape():
    assert bitsizeof(UInt16) == 16  # BitType class
    assert bitsizeof(UInt16(5)) == 16  # box
    assert bitsizeof(UInt4) == 4  # sub-byte class
    assert bitsizeof(Rec) == Rec.num_bits  # Struct class
    assert bitsizeof(Rec.plan) == Rec.num_bits  # Plan
    assert bitsizeof(Array.of(UInt32, 4)) == 128  # Array object
    assert bitsizeof(u16) == 16  # Annotated alias
    assert bitsizeof(s5) == 5  # lazily-minted alias
    assert bitsizeof(Name4) == 32  # minted String type


def test_bitsizeof_on_instances_and_views():
    r = Rec(hp=1, name="ab", inner=Inner(x=2), colors=[1, 2, 3], raw=b"xy")
    assert bitsizeof(r) == Rec.num_bits
    assert bitsizeof(r.sizedview.hp) == 16  # BoundField handle


def test_sizeof_rounds_up_sub_byte():
    assert sizeof(UInt16) == 2
    assert sizeof(UInt4) == 1  # matches len(bytes(UInt4(1)))
    assert sizeof(Rec) == Rec.num_bits // 8


def test_sizeof_rejects_unsized_with_guidance():
    with pytest.raises(TypeError, match="carries no bit width"):
        bitsizeof(int)
    with pytest.raises(TypeError, match="uN/sN"):
        sizeof("u16")


def test_fields_of_layout():
    infos = fields_of(Rec)
    assert [i.name for i in infos] == ["hp", "name", "inner", "colors", "raw", "tag"]
    by = {i.name: i for i in infos}
    assert by["hp"] == FieldInfo("hp", UInt16, 0, 16, None)
    assert by["name"].bit_offset == 16 and by["name"].bit_width == 32
    assert by["inner"].type is Inner and by["inner"].bit_width == 16
    assert by["colors"].bit_width == 48  # 3 x u16, one entry for the array
    assert by["tag"].adapter is not None and "biased" in by["tag"].adapter.name
    # offsets are contiguous in wire order
    total = 0
    for i in infos:
        assert i.bit_offset == total
        total += i.bit_width
    assert total == Rec.num_bits


def test_fields_of_accepts_instance_and_rejects_others():
    r = Rec(hp=1, name="ab", inner=Inner(x=2), colors=[1, 2, 3], raw=b"xy")
    assert fields_of(r) == fields_of(Rec)
    with pytest.raises(TypeError, match="concrete Struct"):
        fields_of(UInt16)
    with pytest.raises(TypeError, match="concrete Struct"):
        fields_of(Struct)
