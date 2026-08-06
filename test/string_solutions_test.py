"""Tests for the Stage-5 String solutions (string-1..6)."""

import pytest

from bytemaker.bittypes import String, UTF8String
from bytemaker.bitvector import BitVector
from bytemaker.utils import FrozenDict


# ------------------------------------------------------------- string-1
def test_empty_codepoint_changes_is_noop():
    S = String.of(nbytes=4, encoding="ascii", pad=0x00, name="EmptyCC")
    S._codepoint_changes = FrozenDict({})
    s = S(value="ab")
    assert bytes(s.bits) == b"ab\x00\x00"  # encode path
    assert s.value == "ab"  # decode path, round-trip
    assert S(bits=BitVector(b"cd\x00\x00")).value == "cd"


# ------------------------------------------------------------- string-2
def test_empty_codepoint_change_entries_rejected():
    S = String.of(nbytes=8, encoding="ascii", pad=0x00, name="CCVal")
    S._codepoint_changes = FrozenDict({"A": ""})
    with pytest.raises(ValueError, match="non-empty"):
        S(value="xy")  # encode path
    S2 = String.of(nbytes=8, encoding="ascii", pad=0x00, name="CCVal2")
    S2._codepoint_changes = FrozenDict({"": "A"})
    with pytest.raises(ValueError, match="non-empty"):
        S2(bits=BitVector(b"xy" + b"\x00" * 6)).value  # decode path
    inst = String.of(nbytes=4, encoding="ascii", name="CCVal3")(value="B")
    with pytest.raises(ValueError, match="non-empty"):
        inst.codepoint_changes = FrozenDict({"B": ""})  # setter fails immediately


# ------------------------------------------------------------- string-3
def test_of_rejects_partial_character_widths():
    with pytest.raises(ValueError, match="whole number"):
        String.of(nbytes=5, encoding="utf-16-le", bytes_per_char=2)
    with pytest.raises(ValueError, match="whole number"):
        String.of(nbytes=1, encoding={b"\x02\x03": "X"}, truncate=True)  # derived bpc=2
    U16 = String.of(nchars=3, encoding="utf-16-le", bytes_per_char=2)  # still fine
    with pytest.raises(ValueError, match="whole number"):
        U16.of(nbytes=5)  # inherited class-attr bpc also enforced
    ok = String.of(nbytes=6, encoding="utf-16-le", bytes_per_char=2, name="Ok6")
    assert ok("ab").value == "ab"  # round-trip control


# ------------------------------------------------------------- string-4
def test_errors_vocabulary_unified():
    TI = String.of(
        nbytes=4, encoding={0x41: "A", 0x42: "B"}, errors="ignore", pad=0x00, name="TI"
    )
    assert TI(bits=BitVector(b"A\x99B\x00")).value == "AB"  # ignore skips unmapped
    t = TI(value="AB")
    assert bytes(t.bits) == b"AB\x00\x00" and t.value == "AB"  # round-trip
    with pytest.raises(ValueError, match="stricct"):
        String.of(nbytes=4, encoding="ascii", errors="stricct")  # typo fails at mint
    with pytest.raises(ValueError, match="table codecs support"):
        String.of(nbytes=4, encoding={0x41: "A"}, errors="backslashreplace")
    String.of(nbytes=4, encoding="ascii", errors="backslashreplace")  # still fine
    String.of(nbytes=4, encoding={0x41: "A"}, errors="replace")  # still fine
    # callable-pair codec is exempt: it decides what errors means
    String.of(
        nbytes=4,
        encoding=(lambda v: v.encode(), lambda b: b.decode()),
        errors="custom",
    )


# ------------------------------------------------------------- string-5
def test_of_validates_pad_and_terminator_bytes():
    for bad in (0x100, -1, 999, "x", 1.5):
        with pytest.raises(ValueError, match="pad must be a byte"):
            UTF8String.of(nbytes=8, pad=bad)
    with pytest.raises(ValueError, match="terminator must be a byte"):
        UTF8String.of(nbytes=8, terminator=999)
    assert UTF8String.of(nbytes=2, pad=None, name="Ex")("ab").value == "ab"
    assert UTF8String.of(nbytes=4, pad=0xFF, name="Pf")("ab").value == "ab"


# ------------------------------------------------------------- string-6
def test_string_class_has_docstring():
    assert String.__doc__
    assert "pad" in String.__doc__ and "terminator" in String.__doc__
