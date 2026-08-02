# Solutions — Docstring & API-surface fixes (misc mediums)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Five solutions: one behavioral (docs-misc-1 redesigns BitType.__repr__ into a truthful, eval-able kwargs form and adds an SInt override carrying int_format, resolving all three __repr__ findings at once), three pure documentation/stub corrections (docs-misc-2 to_pyint phantom parameter, docs-misc-3 Config->SignedConfig, docs-misc-4 fields.pyi __all__ parity), and one cross-reference (docs-misc-5: the SInt.value setter's 'reject out-of-range' claim becomes true once the already-accepted narrowing-3 per-instance gate lands - verified empirically on a copy with that gate applied; no new edit, contingent comment fix provided if narrowing-3 were rejected). Cross-group interactions checked against accepted solutions: docs-misc-1's SInt.__repr__ insertion sits between the SInt.value setter (rewritten by narrowing-2, whose after-text keeps my insertion anchor verbatim) and specialize, and is textually disjoint from narrowing-4 (581-587), narrowing-6 (file top), and float-4 (int.py 450-453); the NarrowingConfig re-export mentioned in group guidance is not among this group's findings and is already handled by narrowing-5 (fields.pyi needs no matching change - it never mentions NarrowingConfig). No accepted solution touches __repr__, and no test asserts the old repr format. Apply order is free; suggested: docs-misc-2/3/4 (docs-only, 'now'), then docs-misc-1 after maintainer sign-off on the repr design, docs-misc-5 rides with narrowing-3. All five verified empirically on a patched work copy: 854/854 tests pass, patched files have no lines over 88 columns, and mypy 2.3.0 confirms the fields.pyi star-import surface now matches runtime.

_5 solutions — 3 apply-now, 5 empirically verified on a patched copy._

---

## 1. Make __repr__ actually round-trippable (kwargs form, quoted values) instead of documenting a format it never produced

**Priority:** soon · [`bytemaker/bittypes/bittype.py:bittype.py 254-264 (__repr__); int.py insertion after 613 (between SInt.value setter and SInt.specialize)`](../../bytemaker/bittypes/bittype.py#L254) · **✓ verified on a patched copy**

**Problem.** The __repr__ docstring promises a string 'that can be used to recreate the object' and documents the format as 'ClassName(value)(bits={self.value}, {endianness=self.endianness})'. Both claims are false: actual output is UInt8(bits=FixedLengthBitVector('00101000'), endianness=big) - no '(value)' segment, bits holds the BitVector not the value - and eval(repr(x)) raises NameError (FixedLengthBitVector not in user namespaces; endianness=big is a bare identifier, so it still fails even with FixedLengthBitVector imported - both failure modes reproduced).

**Fix.** Design decision (sole user, no compat pressure): rather than rewording the docstring to describe a broken format, change __repr__ to a truthful, genuinely eval-able form: ClassName(bits='<01 string>', endianness='big'). The bits= kwarg already accepts a '01' string (verified: UInt8(bits='00101000', endianness='big') constructs), so eval(repr(x)) round-trips with only the class name in scope. bits-form (not value-form) is deliberate: it is exact for every BitType (float NaN payloads, non-canonical signed patterns, strings), while str() already provides the friendly value-form display UInt6[big](40 = 101000). One companion override: SInt.__repr__ appends int_format=..., because the same bits decode to different values under different signed formats - without it the new docstring's round-trip promise would be a fresh lie for non-default-format SInts (a signed_magnitude SInt8 rebuilt without int_format decodes per SignedConfig). Docstrings rewritten to match, in the file's Returns-block style.

**Before:**

```python
# --- bytemaker/bittypes/bittype.py 254-264 ---
    def __repr__(self):
        """
        Returns a string representation of the BitType.
        That can be used to recreate the object.

        Returns:
            str: ClassName(value)(bits={self.value}, {endianness=self.endianness})
        """
        return (
            f"{self.__class__.__name__}(bits={self.bits}, endianness={self.endianness})"
        )

# --- bytemaker/bittypes/int.py 610-617 (insertion anchor: SInt.value setter tail) ---
        str_bits = Int.to_bitstring(
            value, signed=True, bit_length=n, rep_format=self.int_format
        )
        self.bits = BitVector(str_bits)

    @classmethod
    def specialize(
```

**After:**

```python
# --- bytemaker/bittypes/bittype.py ---
    def __repr__(self):
        """
        Returns a string representation of the BitType
        that recreates the object when evaluated
        with the class name in scope.

        Uses the exact bits rather than the value, so patterns the value
            setter would normalize (e.g. float NaN payloads) survive the
            round trip. Subclasses with extra constructor state append it
            as further keyword arguments (`SInt` appends `int_format=...`).

        Returns:
            str: ClassName(bits='<01 string>', endianness=<'big' or 'little'>)
        """
        return (
            f"{self.__class__.__name__}"
            f"(bits={self.bits.to01()!r}, endianness={self.endianness!r})"
        )

# --- bytemaker/bittypes/int.py: insert between SInt.value setter and specialize ---
        str_bits = Int.to_bitstring(
            value, signed=True, bit_length=n, rep_format=self.int_format
        )
        self.bits = BitVector(str_bits)

    def __repr__(self):
        """
        Returns a string representation of the SInt
        that recreates the object when evaluated
        with the class name in scope.

        Appends `int_format` to the base `BitType` format: the same bits
            decode to different values under different signed formats, so a
            faithful reconstruction needs the format this instance was
            built with.

        Returns:
            str: ClassName(bits='<01 string>', endianness=..., int_format=...)
        """
        return (
            f"{self.__class__.__name__}(bits={self.bits.to01()!r},"
            f" endianness={self.endianness!r}, int_format={self.int_format!r})"
        )

    @classmethod
    def specialize(
```

**Behavior change.** BEFORE: repr(UInt6(40)) == "UInt6(bits=FixedLengthBitVector('101000'), endianness=big)"; eval(repr(UInt8(40)), {'UInt8': UInt8}) -> NameError: name 'FixedLengthBitVector' is not defined; with FixedLengthBitVector added to the namespace it still fails: NameError: name 'big' is not defined. AFTER (all actual outputs from the patched copy): repr(UInt6(40)) == "UInt6(bits='101000', endianness='big')"; repr(SInt8(-5)) == "SInt8(bits='11111011', endianness='big', int_format='twos_complement')"; repr(Float16(1.5)) == "Float16(bits='0011111000000000', endianness='big')"; repr(UTF8String.of(nbytes=4)('hi')) == "UTF8Stringx4(bits='01101000011010010000000000000000', endianness='big')"; a signed-magnitude box reprs as "SInt8(bits='10000101', endianness='big', int_format='signed_magnitude')". eval(repr(x), {ClassName: Class}) round-trips type, bits, endianness, and value for UInt6/UInt8/UInt16/SInt8 (both formats)/SInt7/Float16 (incl. NaN bit pattern)/UTF8Stringx4 - all checked True. str() output is unchanged (UInt6[big](40 = 101000)). Full suite on the patched copy: 854/854 passed (no test asserts the old format; verified the suite imports the patched package via its __file__).

**Tests to add.** (1) for x in [UInt6(40), UInt16(0xBEEF), SInt8(-5), Float16(1.5), Float16(float('nan')), UTF8String.of(nbytes=4)('hi'), SInt8(bits='10000101', int_format='signed_magnitude')]: y = eval(repr(x), {type(x).__name__: type(x)}); assert type(y) is type(x) and y.bits.to01() == x.bits.to01() and y.endianness == x.endianness; (2) assert repr(UInt6(40)) == "UInt6(bits='101000', endianness='big')" (format pin); (3) SInt round-trip preserves decode: eval'd signed_magnitude repr has value -123, not the twos_complement -117; (4) little-endian box round-trips endianness='little'; (5) doc smoke: 'recreate' claim in BitType.__repr__.__doc__ stays paired with an eval test so the promise can never silently rot again. REVIEWER CORRECTION: proposed test #3 uses mathematically impossible values (-123/-117 do not correspond); pick a real signed-magnitude pair when writing the test.

**Risks / sync obligations / review notes.** Behavioral change to repr output: no test asserts the old format (repo-wide grep; suite green), Struct's own repr is independent (renders plain field values), and _legacy_aggregate.py/BitVector implementations are untouched (repr is display-only; no sync obligation). Stored notebook outputs showing the old repr (docs/source/quickstart/notebooks/conversions.ipynb, .binder/binder.ipynb) go stale - refresh when convenient. Coordination: the SInt.__repr__ insertion anchor (value-setter tail + '@classmethod def specialize') is preserved verbatim by narrowing-2's accepted rewrite of that setter, so the two apply cleanly in either order; disjoint from narrowing-4/6 and float-4 regions in int.py. The open lows-ux finding about String/Buffer display prefers value-form output - that concerns str()/display and can override on String/Buffer independently; this base repr stays bits-exact and universal. REVIEWER NOTE: anonymous specialize() classes repr as _UInt/_SInt which need a manual name binding to eval - the docstring wording already keeps this honest.

> ⚖️ **Decision needed:** Chose to fix the code to match the docstring's promise (truthful eval-able repr) rather than weaken the docstring - and bits-form over value-form (UInt8(40, ...)) because bits are exact for every subclass while str() already shows the value. Confirm you prefer bits-form; switching to value-form is a two-line variant but loses NaN-payload/odd-pattern fidelity and needs per-family thought.

<sub>covers: `docstring|bytemaker/bittypes/bittype.py|254-264`, `ux|bytemaker/bittypes/bittype.py|254-264`, `ux|bytemaker/bittypes/bittype.py|259-260`</sub>

---

## 2. Document to_pyint's real receiver instead of a phantom `bitstring` parameter

**Priority:** **now** · [`bytemaker/bittypes/int.py:76-89 (to_pyint docstring)`](../../bytemaker/bittypes/int.py#L76) · **✓ verified on a patched copy**

**Problem.** The Parameters section leads with '- bitstring (str): The bitstring to convert.' but the signature is to_pyint(self: BitType | BitsConstructible, signed=None, bin_format=...) - no bitstring parameter exists. The bit source is self (coerced from BitType/BitVector/BitsConstructible at lines 96-105), and self is undocumented; the signed default is also described as 'cls.is_signed' when the code reads getattr(self, 'is_signed', True).

**Fix.** Rewrite the docstring in the file's established dash-list Parameters/Returns style: document self as the receiver (BitType, BitVector, or anything a BitVector can be constructed from, e.g. a '01' string - which is why the module itself calls it unbound as Int.to_pyint(self.bits.to01(), ...)), correct the signed default to self.is_signed-where-present, keep bin_format verbatim, and fix the missing colon typo after '(Optional[bool], optional)'. Signature untouched.

**Before:**

```python
        """
        Convert a bitstring to an integer.

        Parameters:
        - bitstring (str): The bitstring to convert.
        - signed (Optional[bool], optional) Whether the bitstring represents
            a signed integer (vs unsigned). Default is `cls.is_signed` or `True`.
        - bin_format (Optional[str], optional): The format for signed integers.
            Can be "twos_complement", "signed_magnitude", or "ones_complement".
            Default is "twos_complement".

        Returns:
        - int: The integer representation of the bitstring.
        """
```

**After:**

```python
        """
        Convert the bits of `self` to an integer.

        Parameters:
        - self (BitType | BitsConstructible): The object whose bits to convert.
            May be a `BitType`, a `BitVector`, or anything a `BitVector` can
            be constructed from (e.g. a "01" string), so this is also
            callable unbound, as `Int.to_pyint("1010")`.
        - signed (Optional[bool], optional): Whether the bits represent
            a signed integer (vs unsigned). Default is `self.is_signed`
            where that exists (`Int` subclasses), else `True`.
        - bin_format (Optional[str], optional): The format for signed integers.
            Can be "twos_complement", "signed_magnitude", or "ones_complement".
            Default is "twos_complement".

        Returns:
        - int: The integer representation of the bits.
        """
```

**Behavior change.** Documentation-only; every documented claim runtime-checked on the patched copy: Int.to_pyint('1010') == -6 (unbound '01'-string call, signed defaults True when no is_signed attr), Int.to_pyint('1010', signed=False) == 10, Int.to_pyint(BitVector('1010'), signed=False) == 10, SInt8(-5).to_pyint() == -5 (bound call, is_signed honored). 854/854 tests pass.

**Tests to add.** Doc smoke test: assert 'bitstring (str)' not in Int.to_pyint.__doc__ and '- self' in Int.to_pyint.__doc__. Behavioral pins for the documented claims: Int.to_pyint('1010') == -6; Int.to_pyint('1010', signed=False) == 10; SInt8(-5).to_pyint() == -5; UInt8(200).to_pyint() == 200 (is_signed False picked up).

**Risks / sync obligations / review notes.** None (docstring-only; no oracle or BitVector sync). Region is untouched by the other groups' int.py edits (narrowing-2 starts at the imports and line 598; narrowing-6 edits lines 1-53's docstrings above but its Int-class paragraph insertion is at the class head, not inside to_pyint).

<sub>covers: `docstring|bytemaker/bittypes/int.py|76-89`</sub>

---

## 3. Point the SInt docstring at SignedConfig, the class that actually exists

**Priority:** **now** · [`bytemaker/bittypes/int.py:545-547 and 561-562 (SInt class docstring)`](../../bytemaker/bittypes/int.py#L545) · **✓ verified on a patched copy**

**Problem.** The SInt docstring twice directs users to 'the `Config` class', but no Config symbol exists anywhere in the package - the class is SignedConfig (int.py line 525), which is what __init__ actually reads (int_format = SignedConfig.signed_int_format, line 582). A user searching for Config finds nothing.

**Fix.** Rename `Config` to `SignedConfig` in both places, wrapping the second line to stay under 88 columns, and fix the adjacent unclosed quote typo on line 562 ('Default is "twos_complement.' -> 'Default is "twos_complement".'). Style (hanging-indent narrative attribute list) preserved.

**Before:**

```python
# --- int.py 545-547 ---
    To change the signed integer format, use the `Config` class
        (or set the `int_format` parameter in the constructor).
        The default signed integer format is two's complement.

# --- int.py 561-562 ---
            If this is left as `None`, the format will be taken from the `Config` class.
            Default is "twos_complement.
```

**After:**

```python
# --- int.py 545-547 ---
    To change the signed integer format, use the `SignedConfig` class
        (or set the `int_format` parameter in the constructor).
        The default signed integer format is two's complement.

# --- int.py 561-562 ---
            If this is left as `None`, the format will be taken from
                the `SignedConfig` class.
            Default is "twos_complement".
```

**Behavior change.** Documentation-only. Verified on the patched copy: 'SignedConfig' in SInt.__doc__, '`Config`' no longer appears, bytemaker.bittypes.int.SignedConfig exists (and is exported via __all__), and no patched line exceeds 88 columns. 854/854 tests pass.

**Tests to add.** Doc smoke test: assert 'SignedConfig' in SInt.__doc__ and '`Config`' not in SInt.__doc__; assert SInt.__doc__.count('SignedConfig') == 2; and the existing-symbol guard: from bytemaker.bittypes.int import SignedConfig.

**Risks / sync obligations / review notes.** None (docstring-only). narrowing-6's accepted docstring additions touch the Int class docstring (lines 29-53), not SInt's - disjoint regions.

<sub>covers: `docstring|bytemaker/bittypes/int.py|545-547, 561`</sub>

---

## 4. Add __all__ to fields.pyi so the checker's star-import surface matches runtime

**Priority:** **now** · [`bytemaker/fields.pyi:insert after line 14 (the typing import), before the class declarations`](../../bytemaker/fields.pyi#L14) · **✓ verified on a patched copy**

**Problem.** fields.py defines __all__ with exactly 11 names (u8/u16/u32/u64, s8/s16/s32/s64, f16/f32/f64) - runtime star-import verified to bind exactly those 11 - but the stub declares 131 public alias classes (u1..u64, s1..s64, f16/f32/f64) with no __all__, so a type checker treats all 131 as star-exported: 120 names diverge (uN and sN for every N outside {8,16,32,64}). Code like 'from bytemaker.fields import *; x: u1' type-checks clean but raises NameError at runtime.

**Fix.** Add an __all__ to the stub, identical to fields.py's 11 entries and in the same order, with a short comment stating the parity contract. Per stub semantics the other declared aliases remain importable by name (from bytemaker.fields import u17) and widths past 64 still resolve via the stub __getattr__; they are simply no longer star-exported.

**Before:**

```python
from typing import Any, SupportsFloat, SupportsIndex

class _UIntAlias:
```

**After:**

```python
from typing import Any, SupportsFloat, SupportsIndex

# Star-import surface: keep identical to the runtime __all__ in fields.py.
# The other declared aliases stay importable by name (and any width resolves
# via __getattr__); they are just not star-exported.
__all__ = [
    "u8",
    "u16",
    "u32",
    "u64",
    "s8",
    "s16",
    "s32",
    "s64",
    "f16",
    "f32",
    "f64",
]

class _UIntAlias:
```

**Behavior change.** Checker-only change, verified with mypy 2.3.0 on a probe file (from bytemaker.fields import *; from bytemaker.fields import u17; annotations u8/f32/u1/s63/u17). BEFORE (pristine stub): zero errors - u1 and s63 accepted from the star import even though runtime raises NameError. AFTER (patched stub): exactly two errors, matching runtime: "Name 'u1' is not defined; did you mean 'u16' or 'u17'?" and "Name 's63' is not defined"; u8/f32 via star and the direct u17 import stay accepted. Runtime is untouched: star-import still binds the same 11 names and direct imports of u1/u17/s63 still work (verified). 854/854 tests pass.

**Tests to add.** Parity guard runnable without a type checker: parse the stub with ast (ast.literal_eval of the __all__ assignment in bytemaker/fields.pyi) and assert it equals bytemaker.fields.__all__. Optionally a mypy-based test (if mypy joins the dev deps): a probe using u1 after star-import must produce name-defined, and one using u8 must not.

**Risks / sync obligations / review notes.** A checker now (correctly) rejects star-imported odd widths that previously type-checked and crashed at runtime; anyone wanting u1 spelled that way imports it directly, which keeps working in both worlds. No runtime file changes, no oracle/BitVector sync. Unrelated to narrowing-5's bittypes/__init__.py re-export (fields.pyi never references NarrowingConfig, so no parity edit is needed there). REVIEWER NOTE: the clean mypy verification requires an isolated invocation (--follow-imports=silent); a bare mypy run drowns in ~100 pre-existing package errors.

<sub>covers: `inconsistency|bytemaker/fields.pyi|1-162`</sub>

---

## 5. SInt.value setter's 'reject out-of-range' claim: resolved by narrowing-3's per-instance gate (no new edit)

**Priority:** later · [`bytemaker/bittypes/int.py:598-613 (SInt.value setter comment)`](../../bytemaker/bittypes/int.py#L598) · **✓ verified on a patched copy**

**Problem.** The setter comment says non-two's-complement formats 'still reject out-of-range values', but on SInt8/16/32/64 this setter is shadowed by StructPackedBitType.value (skip_struct_packing gates on the process global, not the instance's int_format), which wraps instead: SInt8(0, int_format='signed_magnitude'); s.value = 200 silently reads back -56 on the current repo (reproduced).

**Fix.** Defer: the root cause is the gate, and the accepted narrowing-3 solution already fixes it (SInt8/16/32/64 gain a per-instance skip_struct_packing via _StructPackedSInt reading self.int_format). Once that lands, every non-two's-complement SInt - standard widths included - reaches this setter and the reject path, making the comment true as written; narrowing-2's accepted rewrite of this same setter deliberately keeps the sentence. Verified empirically by applying narrowing-3's gate to a work copy: the claim flips from false to true. No docs-misc edit is proposed; a contingent one-comment fallback is included below ONLY for the case that narrowing-3 is ultimately rejected.

**Before:**

```python
    @value.setter
    def value(self, value):
        n = self.num_bits
        if self.int_format == "twos_complement":
            # C-style narrowing conversion: wrap into the signed range
            # (mod 2**n), matching (intN_t) truncation in C. The other
            # (non-two's-complement) formats have no C analogue and still
            # reject out-of-range values.
            wrapped = ((value + (1 << (n - 1))) % (1 << n)) - (1 << (n - 1))
            if NarrowingConfig.warn and wrapped != value:
                _warn_narrowing(value, wrapped, type(self).__name__)
            value = wrapped
        str_bits = Int.to_bitstring(
            value, signed=True, bit_length=n, rep_format=self.int_format
        )
        self.bits = BitVector(str_bits)
```

**After:**

```python
PRIMARY: no change - apply narrowing-3 (and narrowing-2's setter rewrite, which keeps this comment); the sentence is then accurate for every width.

CONTINGENT FALLBACK (only if narrowing-3 is rejected) - replace the comment inside the twos_complement branch:
            # C-style narrowing conversion: wrap into the signed range
            # (mod 2**n), matching (intN_t) truncation in C. The other
            # (non-two's-complement) formats have no C analogue and
            # reject out-of-range values here - but note SInt8/16/32/64
            # only reach this setter when skip_struct_packing is true;
            # under the default global config StructPackedBitType.value
            # runs instead and two's-complement-wraps regardless of
            # int_format.
```

**Behavior change.** On the current repo (reproduced): SInt8(0, int_format='signed_magnitude'); s.value = 200 -> no exception, s.value == -56 (comment's claim false at standard widths). On a work copy with narrowing-3's per-instance gate applied (reproduced): the same store raises ValueError('Value out of range for the specified bit_length for sign-magnitude notation.') - identical to SInt7's existing behavior - while in-range stores still work (s.value = -5 -> bits 10000101) and two's-complement SInt8 still wraps (200 -> -56). The comment becomes true with zero text changes.

**Tests to add.** Covered by narrowing-3's proposed tests (per-format parity of SInt8..64 against SInt.specialize). Add one claim-pinning case here: for T in (SInt8, SInt16, SInt32, SInt64): x = T(0, int_format='signed_magnitude'); pytest.raises(ValueError): x.value = T(0).num_bits and 2 ** (T.num_bits - 1) as the stored value (e.g. 200 for SInt8) - asserting the reject path documented in the setter comment is reachable at standard widths.

**Risks / sync obligations / review notes.** None from this solution itself (no edit). Sync obligation is inherited from narrowing-3 (already reviewed: oracle parity 854/854). If the maintainer rejects narrowing-3, apply the contingent comment instead so the docs stop promising an unreachable path.

> ⚖️ **Decision needed:** Confirm the deferral: this finding produces no edit because narrowing-3 makes the documented behavior real (empirically verified). Apply the fallback comment only if narrowing-3 is dropped.

<sub>covers: `inconsistency|bytemaker/bittypes/int.py|601-609`</sub>

---
