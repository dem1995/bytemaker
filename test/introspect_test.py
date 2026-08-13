"""Tests for the size/introspection front door (wd-2):
sizeof / bitsizeof / fields_of / layout."""

import re
import textwrap

import pytest

from bytemaker import (
    Array,
    FieldInfo,
    Struct,
    bitsizeof,
    field,
    fields_of,
    layout,
    sizeof,
    u8,
    u16,
)
from bytemaker.adapters import biased
from bytemaker.bittypes import Buffer, UInt4, UInt8, UInt16, UInt32, UTF8String
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
    assert by["hp"] == FieldInfo("hp", UInt16, 0, 16, None, "little")
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


# ------------------------------------- per-field byte order (intro-1)
class MixedInner(Struct, endian="little"):
    """Its own two leaves disagree, so no single order describes the field
    it becomes."""

    be: int = field(UInt16, endian="big")
    le: int = field(UInt16)


class Orders(Struct, endian="little"):
    plain: int = field(UInt16)
    over: int = field(UInt16, endian="big")
    nested: Inner  # a record that declares "big" itself
    mixed: MixedInner
    arr: list = field(Array.of(UInt16, 2, "little"))
    arr_big: list = field(Array.of(UInt16, 2, "big"))
    byte: int = field(UInt8)


def test_fields_of_reports_the_wire_byte_order():
    """The one fact a layout listing could not show: a field(T, endian=)
    override rendered identically to its little-endian neighbours."""
    by = {i.name: i.endian for i in fields_of(Orders)}
    assert by["plain"] == "little"  # inherited from the record
    assert by["over"] == "big"  # per-field override (wd-4)
    assert by["nested"] == "big"  # the nested record's own declaration
    assert by["arr"] == "little" and by["arr_big"] == "big"
    assert by["byte"] == "little"  # width-independent: 8-bit fields report too


def test_a_field_whose_leaves_disagree_reports_no_single_order():
    by = {i.name: i.endian for i in fields_of(Orders)}
    assert by["mixed"] is None
    # ... and recursing gives the two orders it is made of
    assert [i.endian for i in fields_of(MixedInner)] == ["big", "little"]


def test_endian_is_the_last_member_so_earlier_positions_are_stable():
    (info,) = fields_of(MixedInner)[:1]
    assert info[:5] == ("be", UInt16, 0, 16, None)
    assert info.endian == "big"


# ------------------------------------------- the layout renderer (intro-2)
#: A layout row: "  +0x04.4   4b  name  Type  note...". Parsed rather than
#: split by position so the assertions below say which COLUMN they mean.
_ROW = re.compile(
    r"^  \+(?P<off>\S+) +(?P<bits>\d+)b +(?P<name>\S+) +(?P<rest>.*)$"
)


def rows_of(text):
    """``{field name: match}`` for a layout's rows (its head line dropped)."""
    out = {}
    for line in text.splitlines()[1:]:
        m = _ROW.match(line)
        assert m is not None, f"unparseable layout row: {line!r}"
        out[m.group("name")] = m
    return out


class Nibbles(Struct, endian="little"):
    lo: int = field(UInt4)
    hi: int = field(UInt4)
    after: int = field(UInt16, endian="big")


def test_layout_header_names_size_tier_and_record_order():
    head = layout(Rec).splitlines()[0]
    assert head.startswith("Rec  (")
    assert f"{sizeof(Rec)} bytes" in head
    assert f"tier={Rec.plan.tier}" in head and "little-endian" in head


def test_layout_has_one_row_per_field_in_wire_order():
    names = [
        _ROW.match(line).group("name") for line in layout(Rec).splitlines()[1:]
    ]
    assert names == [i.name for i in fields_of(Rec)]


def test_layout_rows_carry_the_offset_width_and_type():
    rows = rows_of(layout(Rec))
    assert rows["hp"].group("off") == "0x00"
    assert rows["hp"].group("bits") == "16"
    assert rows["hp"].group("rest") == "UInt16"
    assert rows["name"].group("off") == "0x02"  # 16 bits in
    assert rows["inner"].group("bits") == "16"


def test_layout_marks_a_sub_byte_offset_with_the_bit():
    rows = rows_of(layout(Nibbles))
    assert rows["lo"].group("off") == "0x00"  # byte-aligned: no suffix
    assert rows["hi"].group("off") == "0x00.4"  # the second nibble
    assert rows["after"].group("off") == "0x01"


def test_layout_notes_only_what_the_row_cannot_show():
    rows = rows_of(layout(Rec))
    assert "adapt=biased(+1)" in rows["tag"].group("rest")  # the convention
    assert "endian=big" in rows["inner"].group("rest")  # differs from record
    assert "endian" not in rows["hp"].group("rest")  # matches: no noise


def test_layout_reports_a_mixed_nested_record_as_mixed():
    rows = rows_of(layout(Orders))
    assert "endian=mixed" in rows["mixed"].group("rest")
    assert "endian=big" in rows["over"].group("rest")
    assert "endian" not in rows["plain"].group("rest")


def test_layout_renders_an_array_field_as_its_declaration_spelling():
    """Not the Array's repr: that repeats the row's adapt= note and would
    print endian=unset for an array that inherits the record's order."""
    rest = rows_of(layout(Rec))["colors"].group("rest")
    assert rest == "UInt16 * 3"
    assert "unset" not in rest and "Array(" not in rest


def test_layout_of_an_adapted_array_names_the_element_adapter_once():
    class Table(Struct, endian="little"):
        mults: list = field(Array.of(UInt16, 3, "little", biased(1)))

    rest = rows_of(layout(Table))["mults"].group("rest")
    assert rest == "UInt16 * 3  adapt=biased(+1)"


def test_layout_takes_an_instance_and_rejects_a_non_record():
    r = Rec(hp=1, name="ab", inner=Inner(x=2), colors=[1, 2, 3], raw=b"xy")
    assert layout(r) == layout(Rec)
    with pytest.raises(TypeError, match="concrete Struct"):
        layout(UInt16)


def test_layout_columns_align_across_uneven_name_and_offset_widths():
    """Nibbles mixes a 0x00.4 offset with byte-aligned ones, and Orders
    mixes 1- and 2-digit bit widths -- the cases fixed-width columns get
    wrong. The width column is RIGHT-aligned (so "8b" and "16b" line up on
    the b, not on the digit); the name and type columns are left-aligned."""
    for cls in (Rec, Orders, Nibbles):
        rows = [_ROW.match(line) for line in layout(cls).splitlines()[1:]]
        assert len({m.end("bits") for m in rows}) == 1, cls
        assert len({m.start("name") for m in rows}) == 1, cls
        assert len({m.start("rest") for m in rows}) == 1, cls


def _docstring_example(doc, first_word):
    """The indented block in ``doc`` that starts with ``first_word``."""
    lines = doc.splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith(first_word)
    )
    block = []
    for ln in lines[start:]:
        if not ln.strip():
            break
        block.append(ln)
    return textwrap.dedent("\n".join(block))


def test_layout_docstring_example_is_real_output():
    """A rendering example that drifts from the renderer is worse than none:
    the docstring promised a `Buffer96` type column and three-space gutter
    that layout() never produced. Now the docstring IS the assertion."""
    Pixels12 = Buffer.of(nbytes=0xC)  # unnamed: __name__ is what renders

    class FontPixelEntry(Struct, endian="little"):
        char_number: int = field(UInt16, endian="big")
        pixels: bytes = field(Pixels12)

    expected = _docstring_example(layout.__doc__, "FontPixelEntry")
    assert layout(FontPixelEntry) == expected


def test_layout_header_states_the_bit_order():
    """bit_order is what gives a sub-byte offset its meaning -- +0x00.4 names
    a different nibble under lsb than under msb -- so the .bit suffix is
    ambiguous without it."""

    class Lsb(Struct, endian="little", bit_order="lsb"):
        a: UInt4
        b: UInt4

    class Msb(Struct, endian="little", bit_order="msb"):
        a: UInt4
        b: UInt4

    assert "lsb-first" in layout(Lsb).splitlines()[0]
    assert "msb-first" in layout(Msb).splitlines()[0]
    # the two pack the same values to DIFFERENT bytes, so the listings must
    # not read identically
    assert Lsb(a=1, b=2).pack() != Msb(a=1, b=2).pack()
    assert layout(Lsb).splitlines()[1:] == layout(Msb).splitlines()[1:]
    assert layout(Lsb) != layout(Msb)  # ... the header is the only difference


def test_endian_is_none_for_an_array_of_internally_mixed_records():
    """The None case is "the leaves disagree", which a field can do in more
    than one way -- not only as a nested record."""

    class Row(Struct, endian="little"):
        entries: list = field(Array.of(MixedInner, 2, "little"))

    (info,) = fields_of(Row)
    assert info.endian is None
    assert "endian=mixed" in layout(Row)
