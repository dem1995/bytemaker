# Solutions — pytype conversions (conversions/pytypes.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

All three fixes live in bytemaker/conversions/pytypes.py and are mechanically independent; apply in order pytypes-1, pytypes-3, pytypes-2 (any order works). pytypes-1 repairs ConversionInfo's three always-AttributeError byte helpers by making them instance methods, and pytypes-3 makes the registered str conversion a strict one-byte char whose encoder refuses anything its advertised num_bits=8 cannot represent; together they make the ConversionInfo contract coherent (num_bits/num_bytes are truthful for every value to_bits/to_bytes accepts). pytypes-2 is a docstring-only fix for bits_to_pytype (plus the same nonexistent-type phrase in its sibling bytes_to_pytype). No edit to _legacy_aggregate.py is needed: both the oracle and the plan fast path consume these conversions through the same shared ConversionConfig registry (the fast path delegates PyType fields to the oracle anyway), so there is no dual-path sync to perform — but the parity tests were re-run as required. All three fixes were verified empirically on a patched copy; the full test suite (854 tests) passes against it unchanged.

_3 solutions — 1 apply-now, 3 empirically verified on a patched copy._

---

## 1. Convert ConversionInfo.num_bytes/to_bytes/from_bytes from broken classmethods to working instance methods

**Priority:** soon · [`bytemaker/conversions/pytypes.py:53-81`](../../bytemaker/conversions/pytypes.py#L53) · **✓ verified on a patched copy**

**Problem.** ConversionInfo's three byte helpers are @classmethods that call cls.num_bits/cls.to_bits/cls.from_bits, but those are per-instance dataclass fields; every invocation raises AttributeError, so the documented byte-conversion API is dead on arrival (masked only because nothing in the package calls it).

**Fix.** Drop @classmethod and dispatch through self, so the helpers use the to_bits/from_bits/num_bits callables stored on the registered instance — matching how the fields are populated and how callers obtain a ConversionInfo (via ConversionConfig.get_conversion_info). Also rename to_bytes's parameter from the misleading 'pytype' (it shadows the dataclass field and receives an instance, not a type) to 'py_prim', matching the module-level functions' naming, and fix its Args entry accordingly. bytes(BitVector) is safe: all three BitVector backends implement __bytes__. Repair rather than delete: the helpers complete the per-registration codec surface (bits and bytes) and become genuinely useful once pytypes-3 makes num_bits truthful.

**Before:**

```python
    @classmethod
    def num_bytes(cls, typeinstance) -> int:
        """
        Function to get the number of bytes in the BitVector representation of\
            the Python instance.
        """
        default = (cls.num_bits(typeinstance) + 7) // 8
        return default if default > 0 else 1

    @classmethod
    def to_bytes(cls, pytype) -> bytes:
        """
        Function to convert a Python instance to the bytes representation
            of that instance.

        Args:
            pytype (type): The Python instance to convert to bytes

        Returns:
            bytes: The bytes representation of the Python instance
        """
        return bytes(cls.to_bits(pytype))

    @classmethod
    def from_bytes(cls, bytes_obj) -> Any:
        """
        Function to convert a bytes object to a Python instance.
        """
        return cls.from_bits(BitVector(bytes_obj))
```

**After:**

```python
    def num_bytes(self, typeinstance) -> int:
        """
        Function to get the number of bytes in the BitVector representation of\
            the Python instance.
        """
        default = (self.num_bits(typeinstance) + 7) // 8
        return default if default > 0 else 1

    def to_bytes(self, py_prim) -> bytes:
        """
        Function to convert a Python instance to the bytes representation
            of that instance.

        Args:
            py_prim: The Python instance to convert to bytes

        Returns:
            bytes: The bytes representation of the Python instance
        """
        return bytes(self.to_bits(py_prim))

    def from_bytes(self, bytes_obj) -> Any:
        """
        Function to convert a bytes object to a Python instance.
        """
        return self.from_bits(BitVector(bytes_obj))
```

**Behavior change.** BEFORE (pristine repo, PYTHONPATH=repo root):
info = ConversionConfig.get_conversion_info(int)
info.num_bytes(5) -> AttributeError: type object 'ConversionInfo' has no attribute 'num_bits'
info.to_bytes(5) -> AttributeError: type object 'ConversionInfo' has no attribute 'to_bits'
info.from_bytes(b'\x00\x00\x00\x05') -> AttributeError: type object 'ConversionInfo' has no attribute 'from_bits'

AFTER (patched copy):
info.num_bytes(5) -> 4
info.to_bytes(5) -> b'\x00\x00\x00\x05'
info.from_bytes(b'\x00\x00\x00\x05') -> 5

**Tests to add.** In test/pytypes_test.py: info = ConversionConfig.get_conversion_info(int); assert info.num_bytes(0) == 4; assert info.to_bytes(5) == b'\x00\x00\x00\x05'; assert info.from_bytes(b'\x00\x00\x00\x05') == 5. bool: ConversionConfig.get_conversion_info(bool).num_bytes(True) == 1 (1 bit rounds up to the 1-byte floor). With pytypes-3 applied: str info.to_bytes('A') == b'A' and info.from_bytes(b'A') == 'A'.

**Risks / sync obligations / review notes.** Near zero: every call previously raised AttributeError, so no code can depend on the old behavior; grep confirms no callers of these helpers anywhere in the package or tests. The pytype->py_prim parameter rename only affects keyword callers (none exist). No _legacy_aggregate.py sync needed (the oracle never calls these helpers). Re-run: test/pytypes_test.py + full suite (done on patched copy: 854 passed).

> ⚖️ **Decision needed:** Repair (proposed) vs delete: these helpers have zero callers in the package — if you would rather shrink the API surface, deleting the three methods is equally safe.

<sub>covers: `inconsistency|bytemaker/conversions/pytypes.py|53-81`</sub>

---

## 2. Fix bits_to_pytype docstring to document the real parameters (bits_obj: BitVector, pytype: type)

**Priority:** soon · [`bytemaker/conversions/pytypes.py:302-314 (and sibling phrase at 331-333)`](../../bytemaker/conversions/pytypes.py#L302) · **✓ verified on a patched copy**

**Problem.** bits_to_pytype's Args block documents 'bytes_obj (bytes)' and 'py_prim_type (type)' — neither name exists in the signature def bits_to_pytype(bits_obj: BitVector, pytype: type), and the first parameter is a BitVector, not bytes. A reader following the docstring passes wrong keyword names (TypeError) and the wrong argument type. Copy-paste residue from bytes_to_pytype.

**Fix.** Rename the documented params to match the signature (bits_obj (BitVector), pytype (type)), and while in the block fix two adjacent lies: the reference to the nonexistent type 'PyTypeWithDefaultBytes' (replaced with the true contract: a suitable conversion registered in ConversionConfig — the same phrase is fixed in the sibling bytes_to_pytype docstring, which names the same phantom type) and the 'thee' typo in Returns. Keeps the file's existing Args:/Returns: field-list style.

**Before:**

```python
    """
    Function to convert bits into instances of Python types.

    Args:
        bytes_obj (bytes): The bits object to convert to a Python primitive
        py_prim_type (type): The type of the Python primitive to convert to.
            Must be a member of PyTypeWithDefaultBytes

    Returns:
        pytype: The instance of thee provided Python type represented by the
            bits
    """
```

**After:**

```python
    """
    Function to convert bits into instances of Python types.

    Args:
        bits_obj (BitVector): The bits object to convert to a Python primitive
        pytype (type): The type of the Python primitive to convert to.
            Must have a suitable conversion registered in ConversionConfig

    Returns:
        pytype: The instance of the provided Python type represented by the
            bits
    """

# --- and in the sibling bytes_to_pytype docstring (lines 331-333), replace ---
        bytes_obj (bytes): The bytes object to convert to a Python primitive
        pytype (type): The type of the Python primitive to convert to.
            Must be a member of PyTypeWithDefaultBytes
# --- with ---
        bytes_obj (bytes): The bytes object to convert to a Python primitive
        pytype (type): The type of the Python primitive to convert to.
            Must have a suitable conversion registered in ConversionConfig
```

**Behavior change.** Docstring-only; no runtime change. Sanity-checked programmatically: BEFORE: bits_to_pytype.__doc__ mentions bytes_obj: True | py_prim_type: True | bits_obj: False. AFTER: mentions bytes_obj: False | py_prim_type: False | bits_obj: True.

**Tests to add.** None required (docstring-only). Optional guard if desired: assert 'bits_obj' in bits_to_pytype.__doc__ and 'py_prim_type' not in bits_to_pytype.__doc__.

**Risks / sync obligations / review notes.** None. No behavior change; no oracle or BitVector-backend sync. The bytes_to_pytype touch-up is one phrase in its Args block; its param names were already correct. REVIEWER NOTE: the "after" field embeds a pseudo-diff comment for the sibling edit; apply the docstring text only - do not paste the commentary line into the module.

<sub>covers: `docstring|bytemaker/conversions/pytypes.py|302-314`</sub>

---

## 3. Make the registered str conversion a strict one-byte char: reject strings whose UTF-8 encoding is not exactly 8 bits

**Priority:** **now** · [`bytemaker/conversions/pytypes.py:207-213`](../../bytemaker/conversions/pytypes.py#L207) · **✓ verified on a patched copy**

**Problem.** The str ConversionInfo advertises a fixed width of 8 bits via num_bits but its to_bits encodes the entire UTF-8 string (24 bits for 'ABC', 16 for a single 'é'). Layout code that sizes fields from the type (count_bits_in_unit_type calls num_bits('') with a placeholder) under-counts, so aggregate serialization emits bytes that either fail round-trip with a confusing far-from-cause ValueError or, in narrower paths (is_array slicing), silently truncate.

**Fix.** Keep num_bits=8 and make the encoder honor it: replace the lambda with a named _char_to_bits that raises a clear ValueError at the point of misuse when the string's UTF-8 encoding is not exactly one byte (multi-char, non-ASCII, and empty strings all refused). Strict-char was chosen over variable-width num_bits (len(s.encode())*8) because the legacy engine sizes fields from the TYPE alone — _legacy_aggregate.count_bits_in_unit_type passes a placeholder '' — so a variable num_bits would return 0 for the placeholder and mis-size layouts even worse; because the registration is literally named _char_conversion_info (the variable-width _string_conversion_info variant sits deliberately commented out just above it); and because to_bits_aggregate already routes multi-char strings through the Iterable branch (per-char, 8 bits each), i.e. the engine's own semantics for str are char semantics. After this fix every value the encoder accepts occupies exactly the advertised 8 bits, so widths, offsets, and round-trips are consistent.

**Before:**

```python
_char_conversion_info = ConversionInfo(
    pytype=str,
    to_bits=lambda string: BitVector(string.encode("utf-8")),
    from_bits=lambda bits: bits.to_bytes().decode("utf-8"),
    num_bits=lambda _: 8,
)
ConversionConfig.set_conversion_info(_char_conversion_info)
```

**After:**

```python
def _char_to_bits(string: str) -> BitVector:
    """
    Function to convert a single one-byte character into its 8-bit BitVector.

    The registered str conversion is a fixed-width char (num_bits reports 8),
    so this encoder refuses any string whose UTF-8 encoding is not exactly
    one byte rather than silently emitting a width that disagrees with
    num_bits.

    Args:
        string (str): The character to convert.
            Must encode to exactly one UTF-8 byte.

    Returns:
        BitVector: The 8-bit representation of the character

    Raises:
        ValueError: If the string does not encode to exactly one UTF-8 byte.
    """
    encoded = string.encode("utf-8")
    if len(encoded) != 1:
        raise ValueError(
            f"The registered str conversion is a fixed-width char (8 bits),"
            f" but {string!r} encodes to {len(encoded)} UTF-8 bytes."
            f" Serialize longer strings character-by-character or register"
            f" a custom ConversionInfo for str."
        )
    return BitVector(encoded)


_char_conversion_info = ConversionInfo(
    pytype=str,
    to_bits=_char_to_bits,
    from_bits=lambda bits: bits.to_bytes().decode("utf-8"),
    num_bits=lambda _: 8,
)
ConversionConfig.set_conversion_info(_char_conversion_info)
```

**Behavior change.** BEFORE (pristine repo):
num_bits('ABC') -> 8   (but the encoder emits 24 bits)
pytype_to_bytes('A') -> b'A'
pytype_to_bytes('ABC') -> b'ABC'
pytype_to_bytes('\u00e9') -> b'\xc3\xa9'
pytype_to_bytes('') -> b''
to_bytes_aggregate(Rec('ABC', 5)) -> b'ABC\x00\x00\x00\x05'  (7 bytes)
roundtrip -> ValueError: Cannot convert b'ABC\x00\x00\x00\x05' to <class '__main__.Rec'> because the # of bits in the bytes object (56) does not match the # of bits in the unit type (40)

AFTER (patched copy):
num_bits('ABC') -> 8   (unchanged; encoder now only accepts what 8 bits can hold)
pytype_to_bytes('A') -> b'A'
pytype_to_bytes('ABC') -> ValueError: The registered str conversion is a fixed-width char (8 bits), but 'ABC' encodes to 3 UTF-8 bytes. Serialize longer strings character-by-character or register a custom ConversionInfo for str.
pytype_to_bytes('\u00e9') -> ValueError: ... encodes to 2 UTF-8 bytes ...
pytype_to_bytes('') -> ValueError: ... encodes to 0 UTF-8 bytes ...
to_bytes_aggregate(Rec('ABC', 5)) -> ValueError at serialization time (the point of misuse) instead of emitting bytes that cannot round-trip
to_bytes_aggregate(Rec('A', 5)) -> b'A\x00\x00\x00\x05'; roundtrip -> Rec(name='A', val=5) (unchanged)
to_bits_aggregate('ABC').to_bytes() -> b'ABC' (bit-level per-char Iterable path unchanged)

**Tests to add.** pytype_to_bits('A') == BitVector(b'A'); pytest.raises(ValueError): pytype_to_bits('ABC'), pytype_to_bits(''), pytype_to_bits('\u00e9'); ConversionConfig.get_conversion_info(str).num_bits('') == 8 (existing test_type_sizes stays green); round-trip: @dataclass Rec(name: str, val: int); to_bytes_aggregate(Rec('A', 5)) == b'A\x00\x00\x00\x05' and from_bytes_aggregate(that, Rec) == Rec('A', 5); pytest.raises(ValueError): to_bytes_aggregate(Rec('ABC', 5)) (fails loudly at serialize time now); to_bits_aggregate('ABC').to_bytes() == b'ABC' (bit-level per-char path unchanged).

**Risks / sync obligations / review notes.** Behavior change on the public conversion functions: pytype_to_bytes/to_bytes_aggregate now raise ValueError for multi-char, non-ASCII, or empty str values where they previously emitted bytes that could not round-trip (sole-user policy: loud failure preferred over silent-wrong). from_bits/decoding is unchanged. No edit inside _legacy_aggregate.py: the oracle and the plan fast path consume the same ConversionConfig registry (the fast path delegates PyType fields to the oracle), so both paths change together by construction — no dual-path sync, but per the sync procedure the parity tests were re-run (test/plan_fastpath_test.py: green; randomized layouts use no str fields). BitVector backends unaffected. Re-run full suite after applying (done on patched copy: 854 passed, including pytypes_test.py's single-char 'a' cases). REVIEWER FINDING (substantive): this fix creates a bits/bytes dual divergence - to_bytes_aggregate('ABC') becomes ValueError while to_bits_aggregate('ABC') still emits b'ABC' per-char (the len>1 str exclusion exists only in the bits path: _legacy_aggregate.py:255 vs 359). Residual silent-wrong also remains: to_bits_aggregate(Rec('ABC', 5)) still emits 56 bits vs the declared 40, failing far from cause at deserialize. PRE-EXISTING: str from_bits raises UnicodeDecodeError for any byte >= 0x80.

> ⚖️ **Decision needed:** Should the char codec stay UTF-8 (proposed; rejects non-ASCII one-char strings like '\u00e9' since they need 2+ bytes) or switch to latin-1 so all 256 one-byte values round-trip? UTF-8 keeps today's decode side and byte values < 0x80 identical; latin-1 would widen the accepted alphabet but change the meaning of decoded bytes >= 0x80. ALSO: Should the one-byte-char enforcement be extended to the bits path too (to_bits_aggregate raising the same ValueError for len!=1 strings, syncing the duals per the oracle procedure), or is the bytes-path-only change acceptable?

<sub>covers: `ux|bytemaker/conversions/pytypes.py|207-213`</sub>

---
