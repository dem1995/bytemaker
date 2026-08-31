"""Tests for bytemaker.fields: the lazy uN/sN alias factory."""

import pytest

import bytemaker.fields as fields
from bytemaker.bittypes import SInt, SInt5, UInt, UInt4
from bytemaker.structs import Struct
from bytemaker.typing_redirect import get_args


def test_lazy_alias_minting_and_cache():
    u31a = fields.u31
    u31b = fields.u31
    assert u31a is u31b  # cached: repeated lookups agree
    bittype = get_args(u31a)[1]
    assert issubclass(bittype, UInt) and bittype.num_bits == 31
    s23 = get_args(fields.s23)[1]
    assert issubclass(s23, SInt) and s23.num_bits == 23


def test_lazy_alias_reuses_canonical_named_classes():
    assert get_args(fields.u4)[1] is UInt4
    assert get_args(fields.s5)[1] is SInt5


def test_eager_aliases_unchanged():
    from bytemaker.bittypes import UInt16

    assert get_args(fields.u16)[1] is UInt16
    assert get_args(fields.f32)[0] is float


def test_structs_reexports_are_the_same_objects():
    from bytemaker.structs import u16 as structs_u16

    assert structs_u16 is fields.u16


def test_lazy_alias_in_struct_roundtrip():
    class Frame(Struct, endian="little"):
        frame: fields.u31
        flag: fields.u1

    f = Frame(frame=0x7FFF_FFFF, flag=1)
    assert Frame.num_bits == 32
    assert Frame.parse(f.pack()) == f
    f.frame = -1  # store narrows, C-style
    assert f.frame == 0x7FFF_FFFF


def test_lazy_signed_alias_in_struct():
    class Odd(Struct):
        a: fields.s5
        b: fields.u3

    o = Odd(a=-16, b=1)
    assert (o.a, o.b) == (-16, 1)
    assert Odd.parse(o.pack()) == o


def test_invalid_alias_names_raise():
    for bad in ("q8", "u0", "u", "s", "u3x", "u-3", "u08x"):
        with pytest.raises(AttributeError):
            getattr(fields, bad)


def test_dir_advertises_common_widths():
    listing = dir(fields)
    assert "u31" in listing and "s5" in listing and "f32" in listing
