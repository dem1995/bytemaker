"""The top-level package surface: everything the README quickstart uses
must come from `bytemaker` directly, and `__all__` must be honest."""

import pytest

import bytemaker
from bytemaker import String, Struct, u4, u6, u8, u16


def test_all_names_resolve():
    for name in bytemaker.__all__:
        assert getattr(bytemaker, name) is not None, name


def test_lazy_alias_delegation():
    # uN/sN for any width resolve through bytemaker.fields, cached there
    from bytemaker import s5, u31

    from bytemaker import fields  # the submodule stays importable

    assert u31 is fields.u31
    assert s5 is fields.s5
    with pytest.raises(AttributeError):
        bytemaker.not_a_name
    with pytest.raises(AttributeError):
        bytemaker.u0  # widths start at 1


def test_version_attribute():
    assert isinstance(bytemaker.__version__, str) and bytemaker.__version__


def test_readme_quickstart():
    """The README quickstart, executed verbatim (values pinned)."""
    MonName = String.of(
        nbytes=4,
        encoding={0x80: "A", 0x81: "B", 0xE1: "[PK]"},
        pad=0x50,
        terminator=0x50,
        name="MonName",
    )

    class Monster(Struct, endian="little"):
        name: MonName
        species: u8
        hp: u16

    m = Monster(name="A[PK]", species=25, hp=35)
    assert m.pack() == b"\x80\xe1PP\x19#\x00"
    assert Monster.parse(m.pack()) == m

    class TileAttr(Struct, endian="big"):
        palette: u4
        priority: u6
        bank: u6

    t = TileAttr(palette=3, priority=40, bank=12)
    assert t.priority + 40 == 80
    t.priority = 200
    assert t.priority == 200 & 0x3F == 8
    f = t.sizedview.priority
    assert f.num_bits == 6
    assert list(Monster.plan.iter_tuples(m.pack() * 2)) == [
        (b"\x80\xe1PP", 25, 35),
        (b"\x80\xe1PP", 25, 35),
    ]
