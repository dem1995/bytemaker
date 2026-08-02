# Solutions — BitVector cleanup (non-behavioral)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Five solutions, all non-behavioral except the assert-to-ValueError conversion (behavioral only on the error path). Two docstring fixes (oct/bin '0x' claims; __Bits__ 'deep' contradiction) and the assert fix were checked in ALL THREE backend files: the __Bits__ line and the garbled assert exist verbatim in all three and are fixed in all three; the oct/bin '0x' error exists only in the bitarray backend. The __main__ scratch block and the garbled assert were confirmed present in the 4-weeks-ago reference .pyc, so both are long-lived, not fresh work-in-progress. All seven commented-out blocks were audited individually and classified as stale scaffolding (each is superseded by live code, references a nonexistent attribute, or is mirrored as a TODO stub in bitvector.pyi), so straight deletion is proposed. Interaction with bitvector-behavior: no edit overlaps, but several are adjacent in bitvector_with_bitarray_speedup.py (their __eq__ rewrite at 633-645 starts 3 lines below my 614-630 deletion; their BitsConstructible/ to_bytes edits at 1733-1759 end 2 lines above my __main__ deletion at 1761; their _coerce_bit insertion lands just below my __Bits__ edit). Recommended apply order: bitvector-behavior FIRST, then this group -- my deletions remove ~132 lines and shift every subsequent line number, while all edits in both groups are verbatim-string-anchored, so behavior-first keeps their verified line references meaningful. Verified empirically: patched copy imports on all three backends, before/after repros run with and without -O, and the full test suite run on the patched package from a neutral cwd (854 passed, 0 failed -- the same 854 the unpatched tree passes; import confirmed via module __file__ pointing into the patched work copy).

_5 solutions — 1 apply-now, 5 empirically verified on a patched copy._

---

## 1. Correct the oct()/bin() docstring prefix claims ('0x' -> '0o'/'0b') in the bitarray backend

**Priority:** soon · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:bitvector_with_bitarray_speedup.py 535 (oct) and 551 (bin). Checked siblings: bitvector_native.py 556/572 and bitvector_speedup.py 711/724 already say 0o/0b; hex() says 0x correctly in all three.`](../../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L535) · **✓ verified on a patched copy**

**Problem.** In the ACTIVE backend, oct()'s docstring claims the result is 'prefixed by 0x' (code returns '0o' + ...) and bin()'s claims 'prefixed by 0x' (code returns '0b' + ...). Both are copy-paste slips from hex() that were fixed in the native and speedup backends but never synced here.

**Fix.** Two one-word docstring edits: '0x' -> '0o' in oct(), '0x' -> '0b' in bin(), matching the code and the other two backends. No other wording changes.

**Before:**

```python
# bytemaker/bitvector/bitvector_with_bitarray_speedup.py:533-535 (oct):
    def oct(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to an octal string prefixed by 0x.

# bytemaker/bitvector/bitvector_with_bitarray_speedup.py:549-551 (bin):
    def bin(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to a binary string prefixed by 0x.
```

**After:**

```python
# bytemaker/bitvector/bitvector_with_bitarray_speedup.py (oct):
    def oct(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to an octal string prefixed by 0o.

# bytemaker/bitvector/bitvector_with_bitarray_speedup.py (bin):
    def bin(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to a binary string prefixed by 0b.
```

**Behavior change.** Docstring-only; runtime output already emits 0o/0b. Verified on the patched copy:
  oct doc line: ['Convert the BitVector to an octal string prefixed by 0o.']
  bin doc line: ['Convert the BitVector to a binary string prefixed by 0b.']

**Tests to add.** Optional one-line doc pin in the cross-backend parity suite: for each backend module, assert '0o' in BitVector.oct.__doc__ and '0b' in BitVector.bin.__doc__ and '0x' in BitVector.hex.__doc__ (guards against a future copy-paste re-slip).

**Risks / sync obligations / review notes.** None; single-word docstring edits. No bitvector-behavior solution touches oct()/bin(). Nearest neighbor is their to_chararray region (untouched by them).

<sub>covers: `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|535, 551`, `ux|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|551`</sub>

---

## 2. Delete the __main__ debug scratch block at the end of the bitarray backend

**Priority:** soon · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:bitvector_with_bitarray_speedup.py 1761-1827 (the finding cites 1761-1779, but the block actually runs to end-of-file at 1827: ~30 bare print() calls plus its own commented-out prints at 1792-1794, 1814-1815, 1820-1821)`](../../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1761) · **✓ verified on a patched copy**

**Problem.** The active backend module ends with an if __name__ == '__main__': block of exploratory print() calls (subclass checks, type prints, ad-hoc oct/replace/join/startswith experiments). It is scratch code shipped in the installed package. Confirmed long-lived: the block's marker strings ('-------------------------------', '0o1011', 'a_bitarray') are present in the 4-weeks-ago reference .pyc, so this is not in-flight work being disturbed.

**Fix.** Delete lines 1761-1827 entirely (the whole block plus the blank line before it). The module then ends at the BitsConstructible trailing docstring. Nothing in the repo runs this module as a script (grepped; only imports via bytemaker/bitvector/bitvector.py). Anything genuinely useful in it (e.g. BitVector-plus-bitarray interop) is already covered by the parity test suite; nothing is worth porting -- the prints assert nothing.

**Before:**

```python
# bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1756-1765 (start of block; runs to EOF at 1827):
Please note that you can also use an int to construct a BitVector of that many
zeroes, but this is not included in the type hint because it is less implicitly
a series of bits.
"""

if __name__ == "__main__":
    print("-------------------------------")
    print(issubclass(BitVector, bitarray))

    a_bitarray = BitVector("0o1011")
# ... ~60 more lines of prints ...
# :1826-1827 (end of file):
    print(type(a_bitarray * 3))
```

**After:**

```python
# bytemaker/bitvector/bitvector_with_bitarray_speedup.py, new end of file:
Please note that you can also use an int to construct a BitVector of that many
zeroes, but this is not included in the type hint because it is less implicitly
a series of bits.
"""
```

**Behavior change.** None on import or via the public API (the block only ran under python -m / direct script execution). Verified on the patched copy: module imports cleanly, '__main__' no longer appears in the source, and the full suite passes (854 passed).

**Tests to add.** No test needed (code was unreachable via the library API). The existing parity suite covers the interop behaviors the block poked at.

**Risks / sync obligations / review notes.** None functional. Collision note: bitvector-behavior-5 edits the BitsConstructible union at 1748-1759 and bitvector-behavior-7 rewrites to_bytes at 1733-1745, both ending immediately above this deletion (which starts at the blank line 1760) -- adjacent but non-overlapping; apply behavior first so their verified line numbers stay accurate. REVIEWER NIT: last content line is 1826 (not 1827); the after-snippet is unambiguous so apply by string anchor, not line number.

<sub>covers: `sloppy-code|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|1761-1779`</sub>

---

## 3. Remove the seven commented-out dead-code blocks from the bitarray backend

**Priority:** soon · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:bitvector_with_bitarray_speedup.py 419-438, 614-630, 940-943, 1006, 1121-1122, 1201-1216, 1495-1500 (actual extents; the finding's list is slightly narrower on four of them)`](../../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L419) · **✓ verified on a patched copy**

**Problem.** Seven stretches of commented-out code (about 60 lines) clutter the active backend. Audited individually, every one is stale scaffolding rather than an intent-documenting alternative: 419-438 (from_bytes/frombytes) is superseded by the live from_bytes at 1714; 614-630 (hex/oct/bin/to_base bodies) is superseded by the live hex/oct/bin/tobase at 486-562; 940-943 (__delitem__ isinstance experiments) and 1201-1216 (startswith dispatch experiments) are abandoned alternatives to the live code directly beside them; 1006 comments out a misspelled dunder (__reverse__; the real hook is __reversed__); 1121-1122 (swap_endianness) references self._endianness, an attribute that exists nowhere in the file; 1495-1500 (translate/maketrans stubs) duplicates the commented TODO stubs the spec already keeps at bitvector.pyi:268-271.

**Fix.** Delete all seven blocks, collapsing the doubled blank lines each deletion leaves so exactly one blank line separates the surviving neighbors. Git history preserves everything. The translate/maketrans intent record is NOT lost: bitvector.pyi lines 268-271 carry the same commented stubs with a TODO marker, and the .pyi is the contract file where that record belongs.

**Before:**

```python
# All in bytemaker/bitvector/bitvector_with_bitarray_speedup.py.
# :417-440 (block 1, commented from_bytes/frombytes between fromoct/fromhex helpers and from_chararray):
        return cls(bit_array)

    # @classmethod
    # def from_bytes(
    #         cls: type[Self],
    #         bytes: bytes,
    #         endianness: Literal["little", "big"] = "big") -> Self:
    #     """
    #     Create a BitVector from a bytes object.

    #     Args:
    #         bytes (bytes): The bytes object to convert
    #         endianness (Literal["little", "big"]): The endianness of the BitVector

    #     Returns:
    #         BitVector: The BitVector created from the bytes object
    #     """
    #     return cls(bytes, endianness=endianness)

    # @classmethod
    # def frombytes(*args, **kwargs):
    #     raise Warning("frombytes is not implemented. Use from_bytes instead.")

    @classmethod

# :612-632 (block 2, commented hex/oct/bin/to_base after to_chararray):
            return "".join(str_list)

    # def hex(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
    #     retstring = ba2base(16, self)
    #     if sep is not None:
    #         retstring = sep.join(
    #             retstring[i: i + bytes_per_sep]
    #             for i in range(0, len(retstring), bytes_per_sep)
    #         )
    #     return retstring

    # def oct(self) -> str:
    #     return ba2base(8, self)

    # def bin(self) -> str:
    #     return ba2base(2, self)

    # def to_base(self, base: int) -> str:
    #     return ba2base(base, self)

    # Magic Methods and Overloads

# :940-944 (block 3, inside __delitem__):
        # if isinstance(key, Iterable):
        #     key = list(key)
        # if isinstance(key, Iterable) and not isinstance(key, Sequence):
        #     key = list(key)
        super().__delitem__(key)

# :1004-1008 (block 4, between __copy__ and __deepcopy__):
        return self

    # def __reverse__(self) -> Self:

    def __deepcopy__(self: Self, memo: dict[int, object]) -> Self:

# :1119-1124 (block 5, after reverse()):
        super().reverse()

    # def swap_endianness(self) -> None:
    #     self._endianness = "big" if self._endianness == "little" else "little"

    # Search and Analysis

# :1199-1218 (block 6, inside startswith):
                raise ValueError("Invalid type in provided iterable")

        # if isinstance(substrings, (bitarray, int, str)):
        #     conv_substrings = [substrings]
        # elif isinstance(substrings, Iterable):
        #     conv_substrings = list(substrings)
        # else:
        #     try:
        #         conv_substrings = [BitVector(substrings)]
        #     except TypeError:
        #         pass

        # if isinstance(substrings, Iterable):
        #     for substring in substrings:
        #         if isinstance(substring, bitarray):
        #             conv_substrings.append(substring)
        #         else:
        #             conv_substrings.append(BitVector(substring))

        if stop is None:

# :1493-1502 (block 7, between replace() and join()):
        return self

    # def translate(self,
    #   table: List[BitVector] | bytes, delete: Optional[List[BitVector] | bytes] = None
    #   ) -> Self: ... # todo

    # def maketrans(self, fromstr: List[BitVector]|bytes, tostr: List[BitVector]|bytes
    #   ) -> list[BitVector]: ...  # todo

    def join(self: Self, iterable: Iterable[BitsConstructible]) -> Self:
```

**After:**

```python
# Each block deleted; the surviving neighbors join with one blank line:
# (1)
        return cls(bit_array)

    @classmethod
    def from_chararray(
# (2)
            return "".join(str_list)

    # Magic Methods and Overloads
    def __eq__(self, other: object) -> bool:
# (3)
        """
        super().__delitem__(key)
# (4)
        return self

    def __deepcopy__(self: Self, memo: dict[int, object]) -> Self:
# (5)
        super().reverse()

    # Search and Analysis
# (6)
                raise ValueError("Invalid type in provided iterable")

        if stop is None:
# (7)
        return self

    def join(self: Self, iterable: Iterable[BitsConstructible]) -> Self:
```

**Behavior change.** None; comments only. Verified on the patched copy: module imports, none of the deleted markers remain in the source, file shrinks 1827 -> 1695 lines (with solution 2 also applied), and the full suite passes (854 passed).

**Tests to add.** No tests (comment-only deletion); the existing suite passing on the patched copy is the verification.

**Risks / sync obligations / review notes.** Collision note: block 2's deletion ends at the '# Magic Methods and Overloads' comment (kept), 3 lines above the __eq__/__ne__ pair that bitvector-behavior-6 rewrites -- adjacent, non-overlapping. Block 6 sits inside startswith ~17 lines below bitvector-behavior-2's edit of the (str, bytes, BitsCastable) branch; their before-string still matches after this deletion (and vice versa), but apply behavior first to keep their verified line numbers accurate. Blocks audited as (b)-type candidates: only 1495-1500 (translate/maketrans) documents unshipped intent, and that intent remains recorded at bitvector.pyi:268-271, so nothing is lost.

<sub>covers: `sloppy-code|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|420-437, 614-630, 940-942, 100`</sub>

---

## 4. Reword the __Bits__ method docstring to drop the false 'deep' promise in all three backends

**Priority:** soon · [`bytemaker/bitvector/bitvector_speedup.py:bitvector_speedup.py 76-83 ('deep' at 77); bitvector_native.py 75-82 ('deep' at 76); bitvector_with_bitarray_speedup.py 79-86 ('deep' at 80). The text is byte-identical in all three.`](../../bytemaker/bitvector/bitvector_speedup.py#L76) · **✓ verified on a patched copy**

**Problem.** The BitsCastable class docstring (rewritten since the reference era) states that whether __Bits__ returns a copy or a live view is the implementor's choice, and BitType really does return its bits live (bittypes/bittype.py __Bits__ returns self._bits). But the __Bits__ method docstring on the same protocol still promises 'a deep BitVector representation' -- a direct contradiction, and the method-level claim is the wrong one. Identical stale line in all three backends.

**Fix.** Replace the first line with 'Returns a BitVector representation of the object.' and add a short paragraph deferring to the class docstring's copy-or-live-view policy, noting constructors copy-construct either way. Keeps the file's RST field-list style and the existing 'prioritized when BitVectorSubtype(object) is called' and Returns: lines. Apply the identical replacement in all three files.

**Before:**

```python
# Identical in bytemaker/bitvector/bitvector_speedup.py:76-83,
# bytemaker/bitvector/bitvector_native.py:75-82,
# bytemaker/bitvector/bitvector_with_bitarray_speedup.py:79-86:
        """
        Returns a deep BitVector representation of the object.

        This method is prioritized when BitVectorSubtype(object) is called.

        Returns:
            BitVector: The BitVector representation of the object
        """
```

**After:**

```python
# Identical replacement in all three files:
        """
        Returns a BitVector representation of the object.

        The result may be a copy or a live view of the object's bits;
            which is the implementor's ownership choice (see the
            BitsCastable class docstring). Constructors copy-construct
            from the result either way.

        This method is prioritized when BitVectorSubtype(object) is called.

        Returns:
            BitVector: The BitVector representation of the object
        """
```

**Behavior change.** Docstring-only. Verified on the patched copy (all three backends):
  native  __Bits__ mentions 'deep': False | mentions 'copy or a live view': True
  speedup __Bits__ mentions 'deep': False | mentions 'copy or a live view': True
  bitarray __Bits__ mentions 'deep': False | mentions 'copy or a live view': True

**Tests to add.** Optional cross-backend doc pin: for each backend module, assert 'deep' not in mod.BitsCastable.__Bits__.__doc__ (guards against re-drift when one file is edited without the siblings). BitVector.__Bits__ concrete impls (return copy.copy(self)) keep their own docstrings and need no change -- a copy IS a permitted choice.

**Risks / sync obligations / review notes.** None functional. Collision note: in bitvector_with_bitarray_speedup.py this edit ends at line 87, three lines above the __annotations__ block (90-94) that bitvector-behavior-5 rewrites and near where bitvector-behavior-3 inserts the module-level _coerce_bit helper -- adjacent, non-overlapping. The three files' BitsCastable sections should continue to be edited in lockstep. REVIEWER NIT: the replacement phrase '; which is' is ungrammatical - drop the semicolon when applying.

<sub>covers: `docstring|bytemaker/bitvector/bitvector_speedup.py|65-70, 76-83`</sub>

---

## 5. Replace the to_chararray length assert with an explicit ValueError in all three backends

**Priority:** **now** · [`bytemaker/bitvector/bitvector_speedup.py:bitvector_speedup.py 768-769; bitvector_native.py 618-619; bitvector_with_bitarray_speedup.py 597-598. The assert is byte-identical in all three (the finding cites only speedup; the bitarray copy is long-lived -- the same garbled message string is in the 4-weeks-ago reference .pyc).`](../../bytemaker/bitvector/bitvector_speedup.py#L768) · **✓ verified on a patched copy**

**Problem.** Public to_chararray() guards its 'length must be a multiple of 8' precondition with a bare assert: under python -O the check vanishes and callers get a cryptic UnicodeDecodeError instead; and the backslash line-continuation embeds a 16-space indentation run into the message (82 chars, mostly whitespace). Same defect in all three backends.

**Fix.** Replace the assert with an explicit if len(self) % 8 != 0: raise ValueError(...) using a clean f-string message that includes the actual length ('BitVector length {n} is not a multiple of 8; cannot decode with a standard encoding'). Identical replacement in all three files. Asserts stay reserved for internal invariants (e.g. _check_invariants in bitvector_speedup.py), matching house convention.

**Before:**

```python
# Identical in bytemaker/bitvector/bitvector_speedup.py:767-770,
# bytemaker/bitvector/bitvector_native.py:617-620,
# bytemaker/bitvector/bitvector_with_bitarray_speedup.py:596-599:
        if isinstance(encoding, str):
            assert len(self) % 8 == 0, "BitVector length must be a multiple of 8\
                to use a standard encoding"
            return bytes(self).decode(encoding)
```

**After:**

```python
# Identical replacement in all three files:
        if isinstance(encoding, str):
            if len(self) % 8 != 0:
                raise ValueError(
                    f"BitVector length {len(self)} is not a multiple of 8;"
                    " cannot decode with a standard encoding"
                )
            return bytes(self).decode(encoding)
```

**Behavior change.** Actual outputs for BitVector('0b101').to_chararray('utf-8') on all three backends (identical per backend):
BEFORE normal: AssertionError, len(msg)=82: 'BitVector length must be a multiple of 8                to use a standard encoding'
BEFORE -O:     UnicodeDecodeError: "'utf-8' codec can't decode byte 0xa0 in position 0: invalid start byte" (validation stripped)
AFTER normal:  ValueError: 'BitVector length 3 is not a multiple of 8; cannot decode with a standard encoding'
AFTER -O:      same ValueError (check survives optimization)
Byte-aligned vectors are unaffected (existing to_chararray round-trip tests pass unchanged).

**Tests to add.** Parameterized over all three backends: with pytest.raises(ValueError, match=r'length 3 is not a multiple of 8'): BitVector('0b101').to_chararray('utf-8'). Positive case: BitVector(b'hi').to_chararray('utf-8') == 'hi'. Mapping-encoding path is unaffected (no length precondition) -- keep an existing mapping-decode case as regression. Optionally a subprocess test running the repro under sys.executable -O to pin the -O behavior.

**Risks / sync obligations / review notes.** Exception type changes AssertionError -> ValueError on the error path; no in-repo caller catches AssertionError (and ValueError is what the constructor and siblings already raise for bad input, so any except ValueError handlers become MORE correct). No bitvector-behavior solution touches to_chararray in any file; nearest edits are far away in all three files. Keep the three copies in lockstep if the message is tweaked.

<sub>covers: `ux|bytemaker/bitvector/bitvector_speedup.py|768-770`</sub>

---
