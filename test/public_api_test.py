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
    from bytemaker import fields  # the submodule stays importable
    from bytemaker import s5, u31

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


def test_adapters_are_importable_from_the_root():
    """field(..., adapt=) requires an Adapter, so the adapters have to be
    reachable from where field() is (pub-2). The rom layer deliberately is
    NOT re-exported -- it is its own namespace -- but the root docstring
    points at it."""
    from bytemaker import (
        THUMB_PTR,
        Adapted,
        Adapter,
        biased,
        enum_,
        fixed,
        scaled,
    )

    assert isinstance(THUMB_PTR, Adapter)
    assert all(isinstance(f(1), Adapter) for f in (biased, fixed, scaled))
    assert isinstance(fixed(4) @ bytemaker.UInt16, Adapted)
    assert enum_ is not None
    assert bytemaker.__doc__ is not None
    assert "bytemaker.adapters" in bytemaker.__doc__
    assert "bytemaker.spaces" in bytemaker.__doc__


def test_the_layout_compiler_is_not_part_of_the_public_surface():
    """Plan is the compiler's output, reached as cls.plan when you want it.
    Exporting it invited users to learn a type they never need, and
    introspect answers the questions they actually have."""
    assert not hasattr(bytemaker, "Plan") and "Plan" not in bytemaker.__all__
    assert hasattr(bytemaker, "PlanCompileError")  # a bad declaration raises

    class R(bytemaker.Struct, endian="little"):
        a: bytemaker.u8

    assert R.plan is not None
    assert bytemaker.offset_of(R, "a") == 0  # the front door for the numbers


def test_the_root_docstrings_example_is_executed_from_the_docstring():
    """Not a hand-typed copy of the example -- the example ITSELF, read out
    of __doc__ and exec'd. A copy pins the behaviour but lets the docstring
    rot independently, which is the failure it was supposed to prevent."""
    from test.conftest import docstring_example

    doc = bytemaker.__doc__
    assert doc is not None
    source = docstring_example(doc, "class SkillEntry")
    assert "adapt=biased(1)" in source and "adapt=fixed(4)" in source

    namespace = {n: getattr(bytemaker, n) for n in bytemaker.__all__}
    exec(compile(source, "<root docstring>", "exec"), namespace)  # noqa: S102
    SkillEntry = namespace["SkillEntry"]

    s = SkillEntry(reward_id=4, multiplier=1.5)
    assert s.pack() == b"\x05\x18\x00"  # wire = id + 1, and 1.5 * 16 = 0x18
    assert SkillEntry.parse(s.pack()) == s
    # the comments in the example claim these two facts; check them
    assert s.to_tuple() == (5, 0x18)
    assert SkillEntry.parse(b"\x05\x10\x00").multiplier == 1.0


def test_version_fallback_matches_pyproject():
    """The literal in __init__'s importlib fallback is what a vendored copy
    reports as __version__, so it must track pyproject's declared version."""
    import re
    from pathlib import Path

    root = Path(bytemaker.__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("no pyproject.toml beside the package (vendored layout)")
    declared = re.search(
        r'^version = "([^"]+)"$', pyproject.read_text(encoding="utf-8"), re.M
    ).group(1)
    source = (root / "bytemaker" / "__init__.py").read_text(encoding="utf-8")
    fallback = re.search(r'__version__ = "([^"]+)"', source).group(1)
    assert fallback == declared


def test_version_ignores_a_distribution_that_is_not_this_copy(monkeypatch):
    """The distribution that importlib.metadata finds by name need not be the
    code that was imported, so its version is reported only when its files
    are this package's."""
    import importlib.metadata
    from pathlib import Path

    here = Path(bytemaker.__file__).resolve().parent

    class Dist:
        version = "9.9.9"

        def __init__(self, site_packages):
            self._site = site_packages

        def locate_file(self, path):
            return self._site / path

    elsewhere = here.parent.parent / "somewhere-else" / "site-packages"
    monkeypatch.setattr(
        importlib.metadata, "distribution", lambda name: Dist(elsewhere)
    )
    assert bytemaker._installed_version() is None

    monkeypatch.setattr(
        importlib.metadata, "distribution", lambda name: Dist(here.parent)
    )
    assert bytemaker._installed_version() == "9.9.9"

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", missing)
    assert bytemaker._installed_version() is None
