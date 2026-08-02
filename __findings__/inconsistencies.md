# Inconsistencies

> **Status: discovery pass, partially re-verified.** These findings come from the bug/inconsistency sweep of a run cut short by a session limit before its own adversarial-verification stage ran. Many findings embed the finder's own repro. Items marked **✓ Reproduced** or **Confirmed by inspection** were independently re-checked here; the rest are strong leads to confirm before acting. See [README.md](README.md).

The same concept spelled or behaving differently across the API or across the three BitVector implementations, plus docstring/stub/README disagreements with the code. Ordered by severity then confidence.

_44 findings — 5 high, 17 medium, 22 low._

---

## 1. Float.specialize lists bases in reverse of Int.specialize and the concrete Float subclasses, so the struct packing path never wins

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:243-248`](../bytemaker/bittypes/float.py#L243)

**What.** When a packing_format_letter_ is passed, specialize builds `class _Float(cls, StructPackedBitType[float])` with Float listed BEFORE StructPackedBitType. The concrete subclasses are written the other way: `class Float32(StructPackedBitType, Float)` (lines 402-417), and Int.specialize uses `class _SInt(StructPackedBitType[int], cls)` / `class _UInt(StructPackedBitType[int], cls)`. Because `value` is resolved by MRO, the reversed order makes Float's buggy pure-Python `value` getter/setter win instead of StructPackedBitType's correct struct-based one. So `Float.specialize(8,23,'f')` does NOT actually use struct despite the docstring promising it, and diverges from the hand-written Float32.

**Evidence.**

float.py:245 `class _Float(cls, StructPackedBitType[float]):` vs float.py:408 `class Float32(StructPackedBitType, Float):` and int.py:644 `class _SInt(StructPackedBitType[int], cls):`. Repro:
  Spec = Float.specialize(8,23,'f','SpecF32')
  SpecF32(0.1).bits = 00111101110011001100110011001000  (value 0.09999996423721313)
  Float32(0.1).bits = 00111101110011001100110011001101  (value 0.10000000149011612)
  struct '>f' ref = 00111101110011001100110011001101
MRO check: SpecF32 value resolved from 'Float'; Float32 value resolved from 'StructPackedBitType'. The specialize docstring (line 224-226) claims it 'will also be a StructPackedBitType and use struct's packing/unpacking functions with the provided letter'.

**Suggestion.** Swap the base order to `class _Float(StructPackedBitType[float], cls)` to match Int.specialize and the concrete Float subclasses, so the struct path takes precedence when a packing letter is supplied.

---

## 2. Zero/inf/special values round-trip correctly on struct-packed Floats but are decoded wrong on non-struct Float subclasses

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:81-111`](../bytemaker/bittypes/float.py#L81)

**What.** The same conceptual value produces different results across the Float family depending only on whether the subclass is struct-packed. Float32/Float64/Float16 resolve `value` from StructPackedBitType (correct struct decode), but BFloat16, TF19, FP24 (and any non-packing `specialize`) resolve `value` from Float's pure-Python getter, which unconditionally computes `2**unbiased_exponent * (1 + mantissa)` with no zero/inf/NaN special-casing. All-zero bits therefore decode as a tiny denormal instead of 0.0. This is a materially deeper instance of the recorded 'value getter never decodes zero/inf/NaN' bug: it is the exact axis (struct vs non-struct) along which the API is internally inconsistent.

**Evidence.**

Float32(0.0).value == 0.0 (struct path). BFloat16(0.0).value == 5.877471754111438e-39 with bits 0000000000000000 (Float pure-Python path). Getter at float.py:107 `magnitude: float = 2**unbiased_exponent * (1 + mantissa)` has no branch for the all-zero / all-ones exponent encodings, unlike StructPackedBitType.value which delegates to struct.unpack.

**Suggestion.** Make Float's `value` getter handle the reserved exponent encodings (zero/subnormal, inf, NaN) so non-struct subclasses match the struct-packed ones, or route all Float subclasses through a single correct decoder.

**✓ Reproduced (repro run):** an all-zero-bit non-struct Float (e=6, m=9) decodes via `.value` to `4.656612873077393e-10` instead of `0.0`; the getter always applies the implicit leading 1 with no zero/inf/NaN case. Struct-packed Float16/32/64 are unaffected (StructPackedBitType.value overrides this getter).

---

## 3. `int_format` constructor arg is silently ignored on SInt8/16/32/64 (skip_struct_packing keys off the global, not the instance)

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/int.py:698-700, 735-737, 744-746, 753-755 (vs specialize 648-650)`](../bytemaker/bittypes/int.py#L698)

**What.** The hardcoded standard-width signed classes gate struct-packing on the PROCESS-GLOBAL config `SignedConfig.signed_int_format`, while the equivalent class minted by `SInt.specialize` gates on the INSTANCE's `self.int_format`. Consequence: `SInt.__init__`'s documented `int_format` parameter (docstring lines 545-547: "set the `int_format` parameter in the constructor") works for non-standard widths and for `specialize()`-minted types, but is silently dropped for SInt8/SInt16/SInt32/SInt64 -- the two struct-packed setter/getter both use two's complement regardless of the instance's int_format. Same conceptual type (an 8-bit signed int asked for sign-magnitude), two opposite behaviors depending only on whether the width happens to be a standard C width or was produced via specialize.

**Evidence.**

Hardcoded SInt8 (lines 698-700):
    @property
    def skip_struct_packing(self):
        return SignedConfig.signed_int_format != "twos_complement"

vs SInt.specialize's generated class (lines 648-650):
                @property
                def skip_struct_packing(self):
                    return self.int_format != "twos_complement"

Repro:
  SInt7(0, int_format='signed_magnitude'); s.value=-5 -> bits '1000101'  (honors int_format: true sign-magnitude)
  SInt8(0, int_format='signed_magnitude'); s.value=-5 -> bits '11111011' (IGNORES int_format: two's complement 0xFB)
  SInt.specialize(8,'b')(int_format='signed_magnitude').skip_struct_packing -> True
  SInt8(int_format='signed_magnitude').skip_struct_packing          -> False
The specialized 8-bit type and SInt8 disagree on the very same request.

**Suggestion.** Make the hardcoded SInt8/16/32/64 `skip_struct_packing` read `self.int_format != "twos_complement"` (matching specialize), so a per-instance `int_format` is honored at every width. If the intent is that the standard widths only ever follow the global config, then `SInt.__init__` should reject a non-default `int_format` on struct-packed sizes rather than accept and ignore it, and the SInt docstring should stop promising the constructor parameter works everywhere.

---

## 4. Empty value on an extended slice silently deletes bits (packed) but raises ValueError (bitarray backend)

**Severity:** high · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:1057-1070`](../bytemaker/bitvector/bitvector_speedup.py#L1057)

**What.** `__setitem__` for a slice with a non-int value routes through `chars[key] = value.to01().encode("ascii")` on the 0/1-per-byte `bytearray`. For an EXTENDED slice (step != 1) with an EMPTY value, CPython's bytearray special-cases this and DELETES the selected positions instead of raising — so a width-locked-looking assignment silently shrinks the vector. The bitarray backend raises ValueError for the same call. This is both a cross-implementation divergence and a direct contradiction of this method's own docstring, which promises "for non-unit slice steps and index sequences, the lengths must agree." (native has the identical behavior; only the bitarray backend, which is the default when bitarray is installed, matches Python's documented extended-slice semantics.) Non-empty mismatched values raise consistently in all three; only the empty case diverges. No parity test covers it.

**Evidence.**

packed __setitem__ (line 1069): `chars[key] = value.to01().encode("ascii")` with docstring (1048-1051): "...for non-unit slice steps and index sequences, the lengths must agree."

Repro:
  v = BitVector('1101'); v[0:4:2] = BitVector('')
  packed  -> v.to01() == '11', len 2   (width silently changed 4->2, no error)
  native  -> '11', len 2
  bitarray-> ValueError: attempt to assign sequence of size 0 to extended slice of size 2
Contrast non-empty mismatch (all three agree):
  v[0:4:2] = BitVector('1') -> ValueError in P, N, and B.

**Suggestion.** Before delegating to `bytearray.__setitem__`, when `key` is an extended slice (step != 1) explicitly compare `len(value)` against `len(range(*key.indices(len(self))))` and raise ValueError on mismatch (including the empty-value case), matching the bitarray backend and the documented contract. Add an empty-value extended-slice case to the parity suite.

---

## 5. __eq__ equates BitVector to a plain bitarray only on the default (bitarray) backend

**Severity:** high · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:633-638`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L633)

**What.** The bitarray backend's __eq__ delegates to `super().__eq__(other)`, so a BitVector compares equal to a raw `bitarray` (BitVector is a bitarray subclass). The other two implementations guard with `isinstance(other, BitVector)` and return NotImplemented/False for a plain bitarray. Because bitvector/bitvector.py selects the bitarray backend whenever bitarray is installed (find_spec('bitarray')), this divergent behavior is the one users actually get by default. It also contradicts the shared docstring on all three impls, which says equality 'will only really [be] true if both objects are BitVectors'. This can silently change set/dict membership and `==` results depending on which backend is loaded.

**Evidence.**

bitarray backend (line 633-638):
    def __eq__(self, other: object) -> bool:
        """...This will only really true if both objects are BitVectors."""
        return super().__eq__(other)
vs native (bitvector_native.py:641-643) and speedup (bitvector_speedup.py:792-794):
    if isinstance(other, BitVector):
        return self._bits == other._bits  # native
    return NotImplemented
Repro (default backend is bitarray):
    >>> from bitarray import bitarray
    >>> import bytemaker.bitvector.bitvector_with_bitarray_speedup as ba
    >>> ba.BitVector('0b101') == bitarray('101')
    True
    >>> import bytemaker.bitvector.bitvector_speedup as spd
    >>> spd.BitVector('0b101') == bitarray('101')
    False
    >>> import bytemaker.bitvector.bitvector_native as nat
    >>> nat.BitVector('0b101') == bitarray('101')
    False

**Suggestion.** Make the bitarray backend's __eq__ mirror the others: return NotImplemented (or False) when `other` is not a BitVector, e.g. `if not isinstance(other, BitVector): return NotImplemented` before delegating. Apply the same guard to __ne__ (which delegates likewise). This restores the documented 'only true if both are BitVectors' contract and cross-backend agreement.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 6. to_bits_aggregate raises TypeError on unconvertible input but sibling to_bytes_aggregate silently returns b''

**Severity:** medium · **Confidence:** high · [`bytemaker/_legacy_aggregate.py:281-285, 357-375`](../bytemaker/_legacy_aggregate.py#L281)

**What.** The two frozen-oracle serializers for the same aggregate concept disagree on how they handle an object that is neither a UnitType, a dataclass, nor iterable-of-convertibles. to_bits_aggregate has an explicit else that raises a clear TypeError; to_bytes_aggregate has NO final else — none of its if/elif branches fire, ret_bytes stays an empty bytearray, and it silently returns b''. A caller who passes a bad value gets a loud, actionable error from the bits path but a silent, wrong-length b'' from the bytes path (which then only surfaces much later as a confusing size-mismatch, or not at all). Sibling serializers should fail symmetrically.

**Evidence.**

to_bits_aggregate (lines 281-285):
    else:
        raise TypeError(
            f"Cannot convert {convertible_object} to bits because the unit type"
            f" is not a CType, YType, or PyType"
        )

to_bytes_aggregate (357-375) has only three branches and no else:
    ret_bytes = bytearray()
    if is_instance_of_union(units, UnitType): ...
    elif isinstance(units, DataClassType): ...
    elif isinstance(units, Iterable): ...
    return bytes(ret_bytes)

Repro:
    to_bits_aggregate(NotConvertible())  -> TypeError: Cannot convert ... to bits because the unit type is not a CType, YType, or PyType
    to_bytes_aggregate(NotConvertible()) -> returns b'' (no error)

**Suggestion.** Add a matching final `else: raise TypeError(...)` to to_bytes_aggregate mirroring the to_bits_aggregate message, so both serializers reject unconvertible input the same way. (Sync into both paths per the frozen-oracle coordination rule.)

---

## 7. from_bytes_aggregate(is_array=True) behavior diverges between the public dispatcher and the frozen oracle

**Severity:** medium · **Confidence:** high · [`bytemaker/_legacy_aggregate.py:430-446`](../bytemaker/_legacy_aggregate.py#L430)

**What.** conversions/aggregate_types.py documents and ships a deliberate fix: from_bytes_aggregate(..., is_array=True) now returns a list of decoded entries, and its own docstring calls the old oracle behavior 'unusable'. That fix was applied to the public dispatcher path only; the frozen oracle's is_array=True branch still does aggregate_type(*arr_entry_list), producing a single record whose fields are the decoded entries — the exact 'unusable' behavior. The same public function name now behaves two different ways depending on which module you call, and the two coexisting implementations of the same concept are out of sync. The oracle is deliberately frozen (do not delete), but per the coordination rule a behavior change is supposed to be synced into both paths; here only one side was updated.

**Evidence.**

aggregate_types.py docstring (lines 15-18): "One deliberate behavior fix vs 0.12: ``from_bytes_aggregate(..., is_array=True)`` now returns a ``list``... (Previously it attempted ``aggregate_type(*entries)``, which was unusable...)"

Oracle still has the old code (_legacy_aggregate.py 430-446):
        else:
            arr_entry_list = list()
            ...
            retval = aggregate_type(*arr_entry_list)

Repro on a 2-entry buffer of a UInt8 pair dataclass:
    dispatcher is_array=True -> list [Pair(a=1,b=2), Pair(a=3,b=4)]
    oracle     is_array=True -> Pair(a=Pair(a=1,b=2), b=Pair(a=3,b=4))

**Suggestion.** Sync the array fix into the oracle branch (return the list of decoded entries) and update the differential test, so _legacy_aggregate.from_bytes_aggregate(is_array=True) matches the documented public behavior. If the oracle's is_array path is intentionally never exercised, at minimum note that in the branch, but the two paths for one public function should not silently disagree.

---

## 8. NarrowingConfig/NarrowingWarning are public API but not re-exported from the bittypes subpackage

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/__init__.py:1-125`](../bytemaker/bittypes/__init__.py#L1)

**What.** NarrowingWarning and NarrowingConfig are defined in bytemaker/bittypes/bittype.py (lines 27 and 39) and are treated as public API: the top-level package re-exports both (bytemaker/__init__.py imports them and lists them in __all__, and README.md line 82 names them in the curated public surface). Yet the bittypes subpackage __init__.py neither imports them nor lists them in __all__, even though every other public symbol from bittype.py (BitType, StructPackedBitType, bytes_to_bittype) IS re-exported there. The result is an inconsistent import surface: `from bytemaker import NarrowingConfig` works, but `from bytemaker.bittypes import NarrowingConfig` (the subpackage the class actually lives in) raises ImportError. observations/05-packaging-and-docs.md line 21 documents `from bytemaker.bittypes import ...` as a supported pattern, so users will reasonably try the subpackage path.

**Evidence.**

bittypes/__init__.py line 1 imports only `BitType, StructPackedBitType, bytes_to_bittype` from bittype and its __all__ (lines 65-125) omits NarrowingConfig/NarrowingWarning. Repro:
>>> import bytemaker.bittypes as b
>>> 'NarrowingConfig' in dir(b), 'NarrowingConfig' in b.__all__
(False, False)
>>> import bytemaker; hasattr(bytemaker, 'NarrowingConfig')
True
>>> bytemaker.NarrowingConfig is __import__('bytemaker.bittypes.bittype', fromlist=['NarrowingConfig']).NarrowingConfig
True  # same object, only the subpackage re-export is missing

**Suggestion.** Add `NarrowingConfig, NarrowingWarning` to the `from bytemaker.bittypes.bittype import ...` line and to __all__ in bytemaker/bittypes/__init__.py, so the subpackage exposes the same public names the top level does.

---

## 9. NarrowingConfig docstring and README promise integer-store warnings that never fire for the standard C widths

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/bittype.py:39-46`](../bytemaker/bittypes/bittype.py#L39)

**What.** The NarrowingConfig docstring states the warning fires for 'Struct field descriptors and Int/UInt/SInt value setters', and README.md line 91 promises it fires 'whenever an integer store actually changes the assigned value'. But the box value setter that actually runs for the standard C widths (UInt8/16/32/64, SInt8/16/32/64) is StructPackedBitType.value.setter (bittype.py 578-601), which does the C-style narrowing itself (lines 588-591) and never calls _warn_narrowing. Only the pure-Python-width UInt/SInt setters in int.py (lines 795 and 607) call _warn_narrowing. So the stated contract holds for UInt6, SInt7, etc., but silently fails for exactly the most common types a user reaches for. This is the documentation/promise side of the two already-recorded behavior findings; the docstring and README overstate coverage rather than scoping it to non-struct-packed widths.

**Evidence.**

NarrowingConfig docstring: 'integer stores that change the assigned value — Struct field descriptors and Int/UInt/SInt value setters — emit a :class:`NarrowingWarning`.' README.md:91: 'emits `NarrowingWarning` whenever an integer store actually changes the assigned value'. Repro (NarrowingConfig.warn=True):
UInt7(value=200) -> stored=72,  warned=True   # pure-python setter
SInt7(value=200) -> stored=-56, warned=True
UInt8(value=300) -> stored=44,  warned=False  # StructPackedBitType setter
UInt16(value=70000) -> stored=4464, warned=False
SInt8(value=200) -> stored=-56, warned=False

**Suggestion.** Either make StructPackedBitType.value.setter call _warn_narrowing when the wrapped/masked value differs (aligning behavior with the pure-Python setters), or, if the recorded behavior findings are fixed that way, no doc change is needed. If the behavior is intentionally scoped, correct the NarrowingConfig docstring and README to say the box-setter warning covers only non-struct-packed widths.

---

## 10. Float value setter rejects ints while struct-packed Floats accept them (inconsistent scalar coercion)

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:113-121`](../bytemaker/bittypes/float.py#L113)

**What.** Float.value.setter raises `ValueError` unless the value is exactly a `float`. But for struct-packed subclasses the setter is resolved from StructPackedBitType (which accepts ints via struct.pack), so `Float32(value=5)` works while the non-struct `BFloat16(value=5)` raises. Assigning a valid Python numeric (int) to a Float box therefore succeeds or fails depending on which subclass you picked. This also clashes with the base contract in `_inplace_value_op` (bittype.py:444 `self.value = self.py_type(result)`), which assumes the setter coerces via py_type, and with Int, whose setters accept any int-like without an isinstance gate.

**Evidence.**

float.py:115 `if not isinstance(value, float): raise ValueError(f"Expected a float, got {type(value)}")`. Repro: `Float32(value=5)` -> 5.0 (OK); `BFloat16(value=5)` -> ValueError "Expected a float, got <class 'int'>". Compare int.py setters which never isinstance-gate the incoming value.

**Suggestion.** Coerce instead of reject: `value = float(value)` (raising TypeError only for genuinely non-numeric inputs), so all Float subclasses accept ints uniformly and match the struct-packed path.

---

## 11. Unary -, +, abs work on Float boxes but raise on Int boxes

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:348-355`](../bytemaker/bittypes/float.py#L348)

**What.** Float defines __neg__/__pos__/__abs__ (returning promoted plain float), but Int defines none of them. For a unified C-analogous numeric-box API this is an asymmetry: `-Float32(5.0)` returns -5.0, while `-UInt8(5)` raises TypeError. Under the stated C-promotion model, unary minus/plus/abs on an integer box should promote and operate just as they do for floats.

**Evidence.**

float.py:348-355 define __neg__/__pos__/__abs__. int.py has no __neg__/__pos__/__abs__ (Int.__dict__ contains no '__neg__'). Repro: `-Float32(5.0)` -> -5.0; `-UInt8(5)` -> TypeError: bad operand type for unary -: 'UInt8'.

**Suggestion.** Add __neg__/__pos__/__abs__ to Int (delegating to the promoted plain value) so both numeric families support unary arithmetic identically, or document the intentional divergence.

---

## 12. NarrowingConfig warning fires on non-standard widths but is silently skipped on the standard struct-packed widths

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/int.py:795-796 (UInt.value setter), 607-608 (SInt.value setter)`](../bytemaker/bittypes/int.py#L795)

**What.** The narrowing warning (`NarrowingConfig.warn` / `_warn_narrowing`, the documented `-Wconversion` analog, observations/12 R5) is implemented only in the `UInt.value` / `SInt.value` setters. For the standard widths (UInt8/16/32/64, SInt8/16/32/64) those setters are overridden by `StructPackedBitType.value` (bittype.py 578-594), which performs its own C-style wrap but never calls `_warn_narrowing`. So the identical out-of-range store warns for the odd widths and is silent for the common power-of-two widths -- the fix landed on one path (the box setters) but not the other (the struct-packed setter). observations/12 R5 explicitly claims coverage 'from the UInt/SInt box value setters', which understates that the most common widths bypass it.

**Evidence.**

UInt.value setter (lines 794-796):
        masked = value & ((1 << self.num_bits) - 1)
        if NarrowingConfig.warn and masked != value:
            _warn_narrowing(value, masked, type(self).__name__)
StructPackedBitType.value setter (bittype.py 588-591) wraps but never warns:
                if self.packing_format_letter.islower():
                    value = ((value + (1 << (n - 1))) % (1 << n)) - (1 << (n - 1))
                else:
                    value &= (1 << n) - 1
Repro (NarrowingConfig.warn=True):
  UInt7.value=200 -> 1 warning ('narrowing store to UInt7: 200 became 72'), value 72
  UInt8.value=300 -> 0 warnings, value 44
  SInt7.value=200 -> 1 warning, value -56
  SInt8.value=200 -> 0 warnings, value -56

**Suggestion.** Move the narrowing-warning check into `StructPackedBitType.value`'s integer branch (or factor a shared `_narrow_int(value, num_bits, signed)` helper used by both the box setters and the struct-packed setter) so the warning is emitted for every width. At minimum the struct-packed integer branch that already computes the wrapped value should compare and call `_warn_narrowing` before packing.

**Related to the confirmed narrowing bug:** the standard struct-packed widths skip the warning path entirely (see the reproduced bittype.py:578 finding).

---

## 13. SInt.value setter docstring promise that non-two's-complement formats 'reject out-of-range values' is unreachable on standard widths

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/int.py:601-609`](../bytemaker/bittypes/int.py#L601)

**What.** The `SInt.value` setter comment states that only two's complement wraps and that 'The other (non-two's-complement) formats have no C analogue and still reject out-of-range values.' That rejection path (via `Int.to_bitstring`'s range check for sign_magnitude/ones_complement) is only reached when this setter actually runs. For SInt8/16/32/64 the setter is shadowed by `StructPackedBitType.value` (because skip_struct_packing is False under the default global config), which two's-complement-WRAPS out-of-range values instead of rejecting them. So the documented reject-vs-wrap distinction holds for odd widths but is silently violated for the standard widths, compounding the int_format-ignored bug above: the doc describes behavior the code does not deliver at those widths.

**Evidence.**

Setter comment + code (lines 601-609):
        if self.int_format == "twos_complement":
            # C-style narrowing conversion: wrap into the signed range
            # ... The other
            # (non-two's-complement) formats have no C analogue and still
            # reject out-of-range values.
            wrapped = ((value + (1 << (n - 1))) % (1 << n)) - (1 << (n - 1))
            ...
            value = wrapped
Repro: SInt8(0, int_format='signed_magnitude'); s.value = 200 -> no exception, s reads back -56 (StructPackedBitType.value ran, two's-complement wrap). By the docstring's rule a sign-magnitude store of 200 into 8 bits should raise (Int.to_bitstring(200, bit_length=8, rep_format='signed_magnitude') does raise ValueError in isolation).

**Suggestion.** Resolve the root skip_struct_packing divergence (finding 1); once SInt8/16/32/64 honor the instance int_format, the reject path becomes reachable and the docstring becomes true. Alternatively, if standard widths are two's-complement-only by design, delete the misleading 'reject out-of-range values' claim from this setter (it never applies to the widths users actually reach here) and document that non-two's-complement is only supported at non-standard widths / via specialize.

---

## 14. errors="ignore"/"backslashreplace" behave differently in TableString vs StandardEncodingString decode

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/string.py:478, 545-552`](../bytemaker/bittypes/string.py#L478)

**What.** The `errors` knob is a single String-class attribute (line 59) documented as "the decode error policy where the codec supports one" (line 52), but the two concrete codec subclasses honor it inconsistently. StandardEncodingString.decoding forwards `cls.errors` straight to Python's str.decode, so it supports the full Python vocabulary ("strict", "replace", "ignore", "backslashreplace", ...). TableString.decoding hard-codes a single special case: only `errors == "replace"` is handled; every other non-strict value (notably "ignore") falls into the else branch and RAISES. So the identical field declaration errors="ignore" silently drops bad bytes under one codec and hard-raises under the other. TableString's own docstring (lines 486-488) only advertises "strict" and "replace", so "ignore" is an undocumented, silent divergence rather than a rejected option.

**Evidence.**

StandardEncodingString (line 478): `return bytes(bits).decode(cls.encoding_name, cls.errors)`  — full errors vocabulary.
TableString (lines 545-552):
```
                if cls.errors == "replace":
                    out.append("�")
                    pos += 1
                else:
                    raise ValueError(
                        f"{cls.__name__}: no table entry decodes byte"
                        f" 0x{raw[pos]:02x} (position {pos})"
                    )
```
Repro (errors="ignore", one unmapped byte 0x99):
- StandardEncodingString('ascii'): value -> `'A'` (bad bytes dropped)
- TableString({0x41:'A'}): raises `ValueError: TableStringx3: no table entry decodes byte 0x99 (position 1)`

**Suggestion.** Make TableString honor at least "ignore" (advance one byte, append nothing) alongside "replace", or explicitly reject any errors value other than {"strict","replace"} at mint time so the two codecs agree on the supported vocabulary. Update the String-class comment (line 52) and TableString docstring to state exactly which error modes each codec accepts.

---

## 15. bitvector.pyi lists bytearray/memoryview in BitsConstructible but the runtime .py union omits them

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:1850`](../bytemaker/bitvector/bitvector_speedup.py#L1850)

**What.** The `.pyi` (described in its own header as the guaranteed spec) was updated so `BitsConstructible = Union["BitVector", bytes, bytearray, memoryview, str, Iterable[_LaxLiteral01], BitsCastable]`, adding `bytearray` and `memoryview`. The runtime `BitsConstructible` in bitvector_speedup.py (and bitvector_native.py) was NOT updated — it is still `Union[BitVector, bytes, str, Iterable[LaxLiteral01], BitsCastable]`. This is a fresh pyi-vs-py divergence: 4 weeks ago the ref pyi's union also omitted bytearray/memoryview, so the pyi side was changed and the .py side was left behind. The runtime union is not merely cosmetic — `__contains__` calls `is_instance_of_union(item, BitsConstructible)` against it, and the accompanying prose docstring for the union (lines 1851-1859) also does not mention bytearray/memoryview. (bytearray/memoryview happen to still satisfy the runtime union via the Iterable arm, so behavior does not visibly break, but the declared contract and the runtime object disagree.)

**Evidence.**

Current pyi (bitvector.pyi lines 62-70): `BitsConstructible = Union["BitVector", bytes, bytearray, memoryview, str, Iterable[_LaxLiteral01], BitsCastable]`
Current runtime (bitvector_speedup.py line 1850): `BitsConstructible = Union[BitVector, bytes, str, Iterable[LaxLiteral01], BitsCastable]`
Ref pyi 4 weeks ago: `Union["BitVector", bytes, str, Iterable[_LaxLiteral01], BitsCastable]` (no bytearray/memoryview) — so the pyi was the side that changed.

**Suggestion.** Add `bytearray` and `memoryview` to the runtime `BitsConstructible` unions in bitvector_speedup.py and bitvector_native.py (and update the trailing prose docstring to mention them) so the spec .pyi and the runtime object agree.

---

## 16. oct() and bin() docstrings claim '0x' prefix on the bitarray backend (fixed in the other two)

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:535, 551`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L535)

**What.** In the bitarray backend, oct()'s docstring says 'Convert the BitVector to an octal string prefixed by 0x' and bin()'s docstring says 'prefixed by 0x'. The code returns '0o'+... and '0b'+... respectively, so both docstrings are wrong. The native and speedup backends carry the corrected wording ('prefixed by 0o' and 'prefixed by 0b'). This is a fix applied to two implementations but not the third; the reference tree (v0.11.0) shows the bitarray file already had the '0x' error four weeks ago, so it was simply left un-synced.

**Evidence.**

bitarray backend:
    line 535:  Convert the BitVector to an octal string prefixed by 0x.  (oct(), returns '0o'+...)
    line 551:  Convert the BitVector to a binary string prefixed by 0x.  (bin(), returns '0b'+...)
vs native/speedup:
    native oct.__doc__: 'Convert the BitVector to an octal string prefixed by 0o.'
    native bin.__doc__: 'Convert the BitVector to a binary string prefixed by 0b.'
Runtime confirms code emits 0o/0b in all three; only the bitarray docstrings disagree.

**Suggestion.** Update the two docstrings in bitvector_with_bitarray_speedup.py to say '0o' (oct) and '0b' (bin), matching the code and the other two backends.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 17. tobytes()/__bytes__ and to_int()'s to_bytes() disagree on partial-byte alignment (all three backends)

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:978-984, 1733-1745`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L978)

**What.** Two conceptually identical 'render the bits as bytes' operations disagree on where the final partial byte's bits go. `bytes(bv)`/`tobytes()` LEFT-aligns the trailing sub-byte (0b101 -> 0xA0 = 10100000), while the transition-era `to_bytes()` RIGHT-aligns it (0b101 -> 0x05 = 00000101). This holds identically in all three backends, so it is not a cross-backend divergence but a single-API inconsistency: the same object serialized two ways gives different bytes for any non-multiple-of-8 length. It is easy to mix these up (e.g. round-tripping via from_bytes/to_bytes vs bytes()). The speedup to_bytes has a comment acknowledging the 'historical accumulate-without-final-shift behavior', suggesting the divergence is known but never reconciled.

**Evidence.**

Repro (identical across native/speedup/bitarray):
    BitVector('0b101'): bytes()=b'\xa0'  to_bytes()=b'\x05'   (differ)
    BitVector('0b100000011'): bytes()=b'\x81\x80'  to_bytes()=b'\x81\x01'  (differ)
bitarray __bytes__ (line 984) -> self.tobytes() (inherited bitarray.tobytes, left-aligned); to_bytes (line 1837-1847 speedup / 1733 bitarray) right-aligns the tail via `self._buf[full_bytes] >> (8 - tail)`.

**Suggestion.** Decide one canonical partial-byte alignment and make tobytes()/__bytes__ and to_bytes() agree (or document the difference prominently at both call sites and in the .pyi). Given to_bytes/from_bytes are marked transition-only, aligning to_bytes with the padded tobytes semantics (left-aligned) would remove the trap.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 18. Bitfield-struct guard in reverse_ctype_endianness only inspects the first field, so a later bitfield raises ValueError instead of the intended NotImplementedError

**Severity:** medium · **Confidence:** high · [`bytemaker/conversions/ctypes_.py:56-63`](../bytemaker/conversions/ctypes_.py#L56)

**What.** The Structure branch is meant to reject ctypes structs that use bitfields (whose `_fields_` entries are 3-tuples `(name, type, width)` rather than 2-tuples) with a clean NotImplementedError. But the guard only checks `ctype_instance_fields[0]` (the FIRST field). If the first field is an ordinary field (2-tuple) but a LATER field is a bitfield (3-tuple), the guard passes, and control reaches the `for field_name, field_type in ctype_instance_fields` loop, which then blows up with an uncaught `ValueError: too many values to unpack (expected 2)` on the 3-tuple. The code's contract (raise NotImplementedError for bitfield structs) is inconsistent with its actual behavior for this common layout. This is the ctypes bitfield-endianness landmine: `ctype_to_bytes`/`bytes_to_ctype` invoke this whenever the requested endianness differs from `sys.byteorder`. (File is unchanged from the 4-weeks-ago reference, so this is pre-existing.)

**Evidence.**

Guard checks only field 0:
```
ctype_instance_fields = list(ctype_instance._fields_)
if len(ctype_instance_fields) > 0 and len(ctype_instance_fields[0]) > 2:
    raise NotImplementedError(...)
for field_name, field_type in ctype_instance_fields:  # unpacks assuming 2-tuples
```
Repro (little-endian host, requesting big):
```
class S(ctypes.Structure):
    _fields_ = [('a', c_uint8), ('b', c_uint16, 4), ('c', c_uint16, 12)]
ctype_to_bytes(S(1,2,3), endianness='big')
# -> ValueError: too many values to unpack (expected 2)  (from line 63)
#    NOT the NotImplementedError the len(...[0])>2 guard was meant to give
```

**Suggestion.** Test every field, not just the first, e.g. `if any(len(f) > 2 for f in ctype_instance_fields): raise NotImplementedError(...)`, so bitfield structs are rejected consistently regardless of position.

**Confirmed by inspection:** the >2-element bitfield guard tests only `_fields_[0]`; a 3-tuple bitfield in any later field slips past and crashes the 2-tuple unpack at line 63 with `ValueError` instead of the intended `NotImplementedError`.

---

## 19. ConversionInfo.to_bytes/from_bytes/num_bytes classmethods reference instance-only fields and always raise AttributeError

**Severity:** medium · **Confidence:** high · [`bytemaker/conversions/pytypes.py:53-81`](../bytemaker/conversions/pytypes.py#L53)

**What.** `ConversionInfo` is a @dataclass whose `to_bits`, `from_bits`, and `num_bits` are per-instance fields (assigned per registered type). The three @classmethod helpers `num_bytes`, `to_bytes`, and `from_bytes` call `cls.num_bits(...)`, `cls.to_bits(...)`, and `cls.from_bits(...)` -- attributes that exist only on instances, never on the class object `cls`. Every invocation (on the class or on an instance, since these are classmethods bound to the class) raises `AttributeError: type object 'ConversionInfo' has no attribute 'num_bits'`. The docstrings promise working byte conversions but the methods are dead/broken. They are also unused anywhere in the package, masking the breakage. Inconsistent contract: docstring says X (converts), code does Y (crashes). (File is byte-identical to the 4-weeks-ago reference, so pre-existing.)

**Evidence.**

```
@classmethod
def to_bytes(cls, pytype) -> bytes:
    ...
    return bytes(cls.to_bits(pytype))   # cls has no to_bits
```
Repro:
```
>>> ConversionInfo.to_bytes(5)
AttributeError: type object 'ConversionInfo' has no attribute 'to_bits'
>>> ConversionConfig.get_conversion_info(int).num_bytes(5)
AttributeError: type object 'ConversionInfo' has no attribute 'num_bits'
```

**Suggestion.** Make these instance methods (drop @classmethod, use `self.num_bits`/`self.to_bits`/`self.from_bits`), or delete them if they are genuinely unused. As instance methods they would work and match how the fields are populated.

---

## 20. .pyi has no __all__, diverging star-import surface from .py

**Severity:** medium · **Confidence:** high · [`bytemaker/fields.pyi:1-162`](../bytemaker/fields.pyi#L1)

**What.** The runtime module fields.py defines __all__ with exactly 11 names (u8,u16,u32,u64,s8,s16,s32,s64,f16,f32,f64), so `from bytemaker.fields import *` binds only those 11. The stub fields.pyi declares ~131 alias classes (u1..u64, s1..s64, f16/f32/f64) plus `__getattr__` and defines NO __all__. A type checker resolving `from bytemaker.fields import *` against the stub therefore treats every declared class as star-exported, while at runtime the same star-import yields only 11 names. The public star-import surface the checker sees does not match what the interpreter actually produces.

**Evidence.**

fields.py:41-53 `__all__ = ["u8","u16","u32","u64","s8","s16","s32","s64","f16","f32","f64"]`. Runtime repro: `from bytemaker.fields import *` -> star-import count: 11 -> ['f16','f32','f64','s16','s32','s64','s8','u16','u32','u64','u8']. fields.pyi has no `__all__` (grep for __all__ in fields.pyi: No matches found) yet declares e.g. `class u1(_UIntAlias): ...` (line 28) through `class s64(_SIntAlias): ...` (line 156).

**Suggestion.** Add an `__all__` to fields.pyi matching fields.py's 11 entries (u8/u16/u32/u64, s8/s16/s32/s64, f16/f32/f64) so the checker's `*`-import surface agrees with the runtime. The lazily-resolvable uN/sN classes can remain declared for direct `from bytemaker.fields import u17` imports without being star-exported.

---

## 21. NarrowingWarning misattributes array-field stores to bytemaker internals (wrong stacklevel)

**Severity:** medium · **Confidence:** high · [`bytemaker/structs.py:1350-1351`](../bytemaker/structs.py#L1350)

**What.** The opt-in NarrowingWarning is emitted with a fixed stacklevel (stacklevel=3 in _warn_narrowing) that is calibrated for the SCALAR field path (user store -> _UIntField/_SIntField.__set__ -> _warn_narrowing). The ARRAY field path has extra intermediate frames (user store -> _ArrayField.__set__ -> Array._coerce_seq -> list comprehension -> Array._coerce_one -> _warn_narrowing), so the same warning points at bytemaker's own structs.py internals instead of the user's assignment. A single conceptual event (a C-narrowing store on a field) reports its location two different ways depending on whether the field is a scalar or an array, and for arrays it blames the library rather than the user's code -- defeating the purpose of the opt-in warning (telling the user WHERE they narrowed). NarrowingList.__setitem__ shares the same root and is affected too.

**Evidence.**

Scalar path (structs.py:174,197): `_warn_narrowing(iv, v, f"field {self._slot.__name__[4:]!r}")` from `_UIntField.__set__`.
Array path (structs.py:1350-1351): `if NarrowingConfig.warn and v != iv:` / `_warn_narrowing(iv, v, f"array element ({element.__name__})")` inside `Array._coerce_one`, reached via `_coerce_seq` (line 1328 `return [self._coerce_one(v) for v in seq]`).
_warn_narrowing (bittypes/bittype.py:51-56) hardcodes `stacklevel=3`.
Repro output:
  scalar warn filename: <string> line 21   (correctly the user's `s.a = 300`)
  array warn filename: structs.py line 1328  (bytemaker internals, not the user's `a.xs = [300, 0]`)

**Suggestion.** Make the warning point at the user's store consistently regardless of field kind: either thread an explicit stacklevel through _warn_narrowing (e.g. deeper for the array path via _coerce_seq/_coerce_one/__setitem__), or compute the caller depth. At minimum document that array narrowings do not report the user site, so the two field kinds do not diverge silently.

---

## 22. Codec protocol advertises pack(self, value) but Struct.pack(self) takes no value -- two incompatible pack conventions under one protocol

**Severity:** medium · **Confidence:** high · [`bytemaker/structs.py:148-150`](../bytemaker/structs.py#L148)

**What.** The Codec protocol declares `pack(self, value) -> bytes` and its docstring states Struct classes and Array objects both "provide num_bits plus parse/pack", implying a uniform codec calling convention. But the two members disagree on pack's signature: Array.pack(self, values) takes the sequence to encode (matching the protocol), while Struct.pack(self) takes NO argument and encodes `self`. Additionally the abstraction level differs: Array satisfies Codec at the INSTANCE level (an Array object has parse+pack), whereas Struct satisfies it at the CLASS level (parse is a classmethod, pack is an unbound instance method needing a materialized instance). Because Codec is only runtime_checkable (attribute-existence only), `isinstance(SomeStruct, Codec)` returns True despite the signature mismatch, so generic code written against `codec.pack(value)` silently breaks when handed a Struct.

**Evidence.**

Protocol (structs.py:148-150): `def parse(self, data) -> Any: ...` / `def pack(self, value) -> bytes: ...`
Docstring (structs.py:141-143): "Scalar BitType classes, Struct classes, and :class:`Array` objects all provide ``num_bits`` plus ``parse``/``pack``".
Actual signatures (verified): `Struct.pack sig: (self) -> 'bytes'` (no value param); `Array.pack sig: (values) -> 'bytes'`.
`isinstance(SomeStruct, Codec)` -> True (attribute-existence only), so the mismatch is invisible to the runtime check.

**Suggestion.** Reconcile the abstraction: document (or model) that Struct fulfils Codec at the class level with pack bound to an instance (pack()), while Array fulfils it at the instance level with pack(values). If the protocol is meant to describe a callable `pack(value)->bytes`, note that a Struct CLASS is not a drop-in Codec instance (use `s.pack()`), and consider tightening the protocol docstring so generic-codec callers are not misled by the passing isinstance check.

---

## 23. BitType.__repr__ docstring describes a format string the code does not emit

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:254-264`](../bytemaker/bittypes/bittype.py#L254)

**What.** The __repr__ docstring claims the returned string is 'ClassName(value)(bits={self.value}, {endianness=self.endianness})', but the code returns 'ClassName(bits={self.bits}, endianness={self.endianness})'. Two concrete mismatches: (1) the docstring shows a spurious '(value)' segment right after ClassName that the code never produces, and (2) it interpolates self.value into the bits= slot, while the code interpolates self.bits. A reader relying on the docstring would expect the repr to embed the pythonic value in a bits= field, which is the opposite of what happens. Pre-existing (same wording in the 4-weeks-ago ref bittype.py line 205), but still a docstring-says-X / code-does-Y inconsistency.

**Evidence.**

Docstring line 260: 'str: ClassName(value)(bits={self.value}, {endianness=self.endianness})'. Code lines 262-264: `f"{self.__class__.__name__}(bits={self.bits}, endianness={self.endianness})"`. Actual output: `UInt8(bits=FixedLengthBitVector('00101000'), endianness=big)` for UInt8(40) — no '(value)' prefix and bits= holds the bits, not the value.

**Suggestion.** Fix the docstring Returns line to match the code, e.g. 'str: ClassName(bits={self.bits}, endianness={self.endianness})'.

---

## 24. Buffer class docstring still points at pre-defined subclasses (Buffer1..Buffer1024) that were deleted

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/buffer.py:20-21, 43-44`](../bytemaker/bittypes/buffer.py#L20)

**What.** The Buffer class docstring twice tells the reader to "use one of the pre-defined subclasses." Four weeks ago buffer.py defined Buffer1, Buffer2, ... Buffer1024 and listed them all in __all__. The rewrite removed every one of those classes (the module now exports only `Buffer`, and Buffer.of/specialize are the intended construction path), but the docstring text was not updated. A user following the docstring and reaching for `bytemaker.Buffer8` finds nothing. The same stale phrasing also appears in the duplicate second docstring literal at lines 40-45.

**Evidence.**

buffer.py lines 20-21:
```
    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.
```
(repeated verbatim at lines 43-44). Current `__all__` (lines 103-105) = `['Buffer']` only. Ref buffer.py __all__ listed Buffer1..Buffer1024. Repro: `bytemaker.Buffer8` -> AttributeError; `'pre-defined subclasses' in Buffer.__doc__` -> True.

**Suggestion.** Replace "or use one of the pre-defined subclasses" with a reference to `Buffer.of(nbytes=...)` (byte-sized) and `Buffer.specialize(num_bits)` (bit-sized), matching how the class is actually used now. Also delete the stray duplicate docstring literal at lines 40-45.

---

## 25. Analogous 'value to binary string' method named to_binstring on Float but to_bitstring on Int

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/float.py:123-125`](../bytemaker/bittypes/float.py#L123)

**What.** The same conceptual operation (encode the value as an unprefixed binary string) is spelled differently across the two numeric BitTypes: Float.to_binstring vs Int.to_bitstring. Neither type exposes the other's spelling, so there is no single name a caller can rely on across the numeric API.

**Evidence.**

float.py:123 `def to_binstring(self: Float | float, ...)`; int.py:197 `def to_bitstring(self: Int | int, ...)`. Introspection: Int has to_bitstring=True/to_binstring=False; Float has to_binstring=True/to_bitstring=False.

**Suggestion.** Pick one spelling (to_bitstring reads more consistent with the rest of the codebase's 'bits' vocabulary) and provide it on both, keeping the other as an alias if backward names matter.

---

## 26. Float class/py_type docstrings copy-pasted from Int ('represents an integer', 'this Int can be converted')

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/float.py:24-42`](../bytemaker/bittypes/float.py#L24)

**What.** The Float class docstring opens 'A BitType that represents an integer.' and the py_type entry reads 'The Pythonic type that this `Int` can be converted to/from. It is `float`.' Both are unedited copy-paste from Int (int.py:29 'A `BitType` that represents an integer.', int.py:40-41 'this Int can be converted'). A docstring for Float that says it represents an integer and refers to `Int` is a docstring-says-X/code-does-Y mismatch. (Pre-existing: also present in the 4-weeks-ago REF float.py:22,40.)

**Evidence.**

float.py:24 `A BitType that represents an integer.`; float.py:42 `The Pythonic type that this `Int` can be converted to/from. It is `float`.` Both mirror int.py:29 and int.py:41 verbatim.

**Suggestion.** Reword to 'A BitType that represents a floating-point number.' and 'The Pythonic type that this `Float` can be converted to/from. It is `float`.'

---

## 27. oct()/bin() docstrings say "prefixed by 0x" in the (default) bitarray backend; packed backend is correct

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:709-711, 722-724`](../bytemaker/bitvector/bitvector_speedup.py#L709)

**What.** The packed target file documents `oct()` as "prefixed by 0o" and `bin()` as "prefixed by 0b" (correct, matching `return "0o" + ...` and `return "0b" + ...`). The bitarray backend — which is the class actually imported when bitarray is installed (the common case) — has a copy-paste error: its `oct()` docstring says "prefixed by 0x" and its `bin()` docstring says "prefixed by 0x", while the code still emits 0o/0b. So the same public methods carry mutually contradictory, and for the default backend actively wrong, docstrings across implementations. This is a fix applied to one implementation but not the sibling.

**Evidence.**

packed (correct): line 710 "Convert the BitVector to an octal string prefixed by 0o."; line 723 "...binary string prefixed by 0b."
bitarray backend (wrong): bitvector_with_bitarray_speedup.py line 535 "...octal string prefixed by 0x."; line 551 "...binary string prefixed by 0x." — while the code returns `"0o" + ...` (546) and `"0b" + ...` (562).
(bitvector_native.py oct/bin docstrings are correct; only the bitarray backend is wrong.)

**Suggestion.** Fix the bitarray backend's `oct()` docstring to "prefixed by 0o" and `bin()` docstring to "prefixed by 0b" to match the packed/native backends and the code.

---

## 28. tobase docstring "power of 2 (< 64)" contradicts code that accepts 64; packed backend fixed, siblings not

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:683-684`](../bytemaker/bitvector/bitvector_speedup.py#L683)

**What.** All three backends accept base 64 in `tobase` (the guard is `if base not in {2, 4, 8, 16, 32, 64}`) and `tobase(64)` works. The packed target file documents this correctly: "a power of 2, at most 64". The native and bitarray backends still carry the stale wording "Currently must be a power of 2 (< 64)", which excludes 64 and contradicts the code. Same method, contradictory docstrings across implementations — the packed docstring was corrected while the siblings were not.

**Evidence.**

packed (correct): line 683 "base (int): The base to convert to (a power of 2, at most 64)." with guard line 683 `if base not in {2, 4, 8, 16, 32, 64}`.
native: bitvector_native.py line 516 "Currently must be a power of 2 (< 64)."
bitarray: bitvector_with_bitarray_speedup.py line 495 "Currently must be a power of 2 (< 64)."
Repro: BitVector('000000').tobase(64) -> 'A' in all three backends.

**Suggestion.** Update the native and bitarray `tobase` docstrings to "a power of 2, at most 64" (or "<= 64") to match the packed backend and the actual guard.

---

## 29. index/rindex/remove error message says 'not in bitarray' vs 'is not in BitVector' on the other backends

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1392, 1425, 1101`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1392)

**What.** The user-facing ValueError text for a missing value differs across backends. Native and speedup raise "{value} is not in BitVector"; the bitarray backend surfaces "{value} not in bitarray" (index/rindex reach the superclass bitarray message before their own hand-written `is not in bitarray` line; remove delegates to super().remove). Same exception type (ValueError) but divergent wording that also leaks the internal 'bitarray' name. Note the hand-written `raise ValueError(f"{value} is not in bitarray")` in index/rindex is also effectively dead code because super().index() raises first.

**Evidence.**

Repro (missing bit 0 in '1111'):
    native/speedup: ValueError '0 is not in BitVector'
    bitarray:       ValueError '0 not in bitarray'
bitvector_with_bitarray_speedup.py:1392 and 1425:  raise ValueError(f"{value} is not in bitarray")  (never reached; super().index raises 'X not in bitarray' first)
remove() line 1092-1101 delegates: super().remove(value) -> 'X not in bitarray'
vs native (bitvector_native.py:1176/1417/1444) and speedup (bitvector_speedup.py:1300/1560/1585): '{value} is not in BitVector'

**Suggestion.** Normalize the message to 'is not in BitVector' across all three: in the bitarray backend, wrap super().index/remove to re-raise with the BitVector-worded ValueError (as native/speedup do), and fix the misspelled 'not in bitarray' literals to match. Also either remove the unreachable hand-written raises or make them the actual error path.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 30. pop-from-empty IndexError message says 'bitarray' not 'BitVector' on the bitarray backend

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1089`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1089)

**What.** pop() raises IndexError('pop from empty bitarray') on the bitarray backend, while native and speedup raise IndexError('pop from empty BitVector'). Same exception type, divergent wording; the bitarray backend leaks the internal class name. Minor but it is the default backend, so it is the message users see.

**Evidence.**

bitvector_with_bitarray_speedup.py:1089:  raise IndexError("pop from empty bitarray")
bitvector_native.py:1160:  raise IndexError("pop from empty BitVector")
bitvector_speedup.py:1274:  raise IndexError("pop from empty BitVector")
Repro: pop(-1) on any vector -> native/speedup 'pop from empty BitVector'; bitarray 'pop from empty bitarray'.

**Suggestion.** Change the literal in the bitarray backend to 'pop from empty BitVector' to match the other two.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 31. find() docstring on bitarray backend omits the subsequence-search behavior documented in the other two

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1320-1321`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1320)

**What.** The bitarray backend's find() docstring describes only 'the given bit', but the method also accepts and searches for a multi-bit subsequence (it converts non-int values to a BitVector and delegates to bitarray find). Native and speedup docstrings state '...the given bit in the BitVector, or of the subsequence of bits if provided.' Same method contract, inconsistent documentation; a caller reading the default backend's docstring would not know subsequence search is supported.

**Evidence.**

bitarray find.__doc__ first line: 'Finds the first occurrence of the given bit in the BitVector. If the bit is not found, -1 is returned.'
native: 'Finds the first occurrence of the given bit in the BitVector, or of the subsequence of bits if provided.'
speedup: 'Finds the first occurrence of the given bit (or subsequence of bits) in the BitVector, returning -1 when absent.'
Code (bitvector_with_bitarray_speedup.py:1333-1336) proves subsequence support: `if not isinstance(value, (bitarray, int)): value = BitVector(value)` then `super().find(value, ...)`.

**Suggestion.** Add the '(or subsequence of bits)' clause to the bitarray backend's find() docstring to match the actual behavior and the other two backends.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 32. startswith/endswith docstrings and comments say 'bitarray' instead of 'BitVector' only on the bitarray backend

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1166, 1221, 1254, 1293`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1166)

**What.** The bitarray backend's startswith/endswith docstrings read 'Checks if the bitarray starts/ends with ...' and their inline comments say 'within the bounds of the bitarray', whereas native and speedup consistently say 'BitVector'. The public class is BitVector; using the internal superclass name in public-facing docstrings is drift that only exists in this one file. Several constructor Args lines here also say 'The bits of the bitarray' (lines 147, 268) where native/speedup say 'the BitVector'.

**Evidence.**

bitvector_with_bitarray_speedup.py:1166 'Checks if the bitarray starts with the given substring.'; 1254 'Checks if the bitarray ends with the given substring.'; 1221/1293 '# ... within the bounds of the bitarray'; 147/268 'The bits of the bitarray'.
vs native startswith.__doc__: 'Checks if the BitVector starts with the given substring.' (bitvector_native.py:1236) and speedup (bitvector_speedup.py:1365).

**Suggestion.** Replace 'bitarray' with 'BitVector' in these public docstrings/comments in bitvector_with_bitarray_speedup.py so the three backends read identically.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 33. bitarray backend omits a tobytes() override (and its docstring) present in native/speedup

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:978-984`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L978)

**What.** Native and speedup both define an explicit, documented `tobytes(self)` method; the bitarray backend defines only `__bytes__` (which calls the inherited, undocumented bitarray.tobytes). So `BitVector.tobytes` exists and is documented on two backends but is an inherited superclass method with a bitarray-specific docstring on the third. Callers introspecting help(bv.tobytes) get different documentation depending on backend, and the padding contract native/speedup state ('padded with 0s until a multiple of 8') is only asserted in two of the three files.

**Evidence.**

grep 'def tobytes' -> present in bitvector_native.py:1039 and bitvector_speedup.py:1157, absent in bitvector_with_bitarray_speedup.py (only def __bytes__ at 978, def to_bytes at 1733). __bytes__ (line 984) returns self.tobytes() which resolves to bitarray.tobytes.

**Suggestion.** Add a tobytes() override with the same docstring/contract in the bitarray backend (it can just `return super().tobytes()`), so the public method and its documented padding behavior are uniform across all three implementations.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 34. __eq__ docstring grammar 'will only really true' unfixed in native and bitarray backends

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:636`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L636)

**What.** The __eq__ docstring reads 'This will only really true if both objects are BitVectors' (missing 'be') in both the native and bitarray backends, but the speedup backend corrected it to 'will only really be true'. A trivial wording fix was applied to one of the three files only. (The __ne__ docstring right below correctly says 'will only really be false' in all three, making the mismatch visible within each file.)

**Evidence.**

bitvector_with_bitarray_speedup.py:636 'This will only really true if both objects are BitVectors.'
bitvector_native.py:639 'This will only really true if both objects are BitVectors.'
bitvector_speedup.py:790 'This will only really be true if both objects are BitVectors.'  (fixed)
All three __ne__ docstrings: 'will only really be false' (bitarray:643, native:648).

**Suggestion.** Insert 'be' in the native and bitarray __eq__ docstrings to match the speedup backend and the neighboring __ne__ wording.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 35. ConversionInfo.to_bytes/from_bytes ignore endianness while the module-level pytype_to_bytes/bytes_to_pytype honor it

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:62-81`](../bytemaker/conversions/pytypes.py#L62)

**What.** Two byte-producing/consuming code paths exist for the same PyType conversions and disagree on endianness. The module-level `pytype_to_bytes` reverses the byte string for little-endian (`retval = retval[::-1]`) and `bytes_to_pytype` reverses on input, but `ConversionInfo.to_bytes`/`from_bytes` take no endianness parameter and always operate in the canonical (big) order. Were the classmethods not already broken (see the AttributeError finding), they would silently return big-endian bytes where the module functions return little-endian for the same value, an API inconsistency between two paths that ostensibly do the same job.

**Evidence.**

Classmethod, no endianness:
```
@classmethod
def to_bytes(cls, pytype) -> bytes:
    return bytes(cls.to_bits(pytype))
```
Module function, endianness-aware (lines 296-299):
```
retval = pytype_to_bits(py_prim).to_bytes()
if endianness == "little":
    retval = retval[::-1]
return retval
```

**Suggestion.** If the classmethods are kept, give them an `endianness` parameter and apply the same reversal as the module functions so the two paths agree; otherwise remove them.

---

## 36. bits_to_pytype docstring documents parameter names (bytes_obj, py_prim_type) that do not match the actual signature (bits_obj, pytype)

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:302-314`](../bytemaker/conversions/pytypes.py#L302)

**What.** The `bits_to_pytype(bits_obj, pytype)` docstring's Args block documents `bytes_obj (bytes)` and `py_prim_type (type)` -- neither name nor type matches the real parameters `bits_obj (BitVector)` and `pytype (type)`. The prose also refers to a non-existent type `PyTypeWithDefaultBytes`. This appears copy-pasted from `bytes_to_pytype` (which does take `bytes_obj`) and left unedited. Docstring says X, code does Y. (Pre-existing: file is unchanged from the reference.)

**Evidence.**

```
def bits_to_pytype(bits_obj: BitVector, pytype: type):
    """
    ...
    Args:
        bytes_obj (bytes): The bits object to convert to a Python primitive
        py_prim_type (type): The type of the Python primitive to convert to.
            Must be a member of PyTypeWithDefaultBytes
```

**Suggestion.** Rename the documented params to `bits_obj (BitVector)` and `pytype (type)`, and drop the stale `PyTypeWithDefaultBytes` reference (there is no such type in the codebase).

---

## 37. __dir__ caps uN/sN at width 64, contradicting the module's "any integer width works" promise

**Severity:** low · **Confidence:** high · [`bytemaker/fields.py:114-116`](../bytemaker/fields.py#L114)

**What.** The module docstring (line 8-9) states "Any integer width works, not just the pre-declared ones" and `__getattr__` (via _ALIAS_PATTERN = r"(u|s)([1-9][0-9]*)") accepts unbounded widths, so `bytemaker.fields.u100` resolves fine at runtime. But `__dir__` only advertises widths `range(1, 65)` (1..64). The result: `u100`/`s200` are valid attributes but invisible to `dir(bytemaker.fields)` and to REPL/IDE autocompletion, so the advertised discovery surface disagrees with the actual attribute surface. The upper bound 64 is arbitrary given the pattern imposes none.

**Evidence.**

Docstring line 8: "Any integer width works, not just the pre-declared ones". __getattr__ line 83: `_ALIAS_PATTERN = re.compile(r"(u|s)([1-9][0-9]*)")` (no upper bound). __dir__ line 115: `lazy = [f"{prefix}{n}" for prefix in ("u", "s") for n in range(1, 65)]`. Repro: `F.u100` succeeds; `'u100' in F.__dir__()` -> False; `'u65' in F.__dir__()` -> False.

**Suggestion.** Either document that __dir__ intentionally lists only the common 1..64 range as a convenience sample, or drop the bounded enumeration (dir cannot enumerate an unbounded lazy namespace anyway). Aligning the docstring wording ("any width works") with the bounded dir list avoids the implied contradiction.

---

## 38. Module docstring cites f32 as an example of Annotated[int, ...] holding a plain int

**Severity:** low · **Confidence:** high · [`bytemaker/fields.py:3-6`](../bytemaker/fields.py#L3)

**What.** The opening docstring groups f32 together with u8/s16 and then says these names are `Annotated[int, UInt8]` (etc.) and that "the annotation tells a type checker the field holds a plain int". But the float aliases are `Annotated[float, Float32]` (line 78-80) and hold a plain float, not int. The example the sentence explicitly names (f32) is the one case where its own claim is false, so the docstring's lead-in description contradicts the code a few lines below.

**Evidence.**

Docstring lines 3-6: "``u8``/``s16``/``f32``-style names are ``Annotated[int, UInt8]`` (etc.) at runtime: the annotation tells a type checker the field holds a plain ``int``". Code lines 78-80: `f16 = Annotated[float, Float16]` / `f32 = Annotated[float, Float32]` / `f64 = Annotated[float, Float64]`. Repro: `typing.get_args(F.f32)` -> `(<class 'float'>, <class 'bytemaker.bittypes.float.Float32'>)`.

**Suggestion.** Split the description: state that integer aliases are `Annotated[int, UIntN/SIntN]` (field holds int) and float aliases are `Annotated[float, FloatN]` (field holds float). The later paragraph at lines 15-17 already treats floats separately; the opening sentence should not fold f32 into the int case.

---

## 39. Aligned-tier gate treats byte-order-agnostic fields' endian as significant; shiftmask swap logic does not

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:165-169, 198-207`](../bytemaker/plans.py#L165)

**What.** The two engines disagree on when a field's declared endianness matters. The aligned/struct-tier gate rejects a record if ANY leaf's endian differs from the record's, keying on a literal `f.endian == endian` comparison for every field regardless of kind or width. But the shiftmask tier's byte-swap logic correctly recognizes that endianness is meaningless for byte-order-agnostic fields: `swap` is only computed when `f.kind in ('u','s') and f.bit_width % 8 == 0 and f.bit_width > 8` -- i.e. 8-bit ints, bytes/String/Buffer ('b') fields, and sub-byte fields never swap. Consequence: a record composed entirely of byte-order-agnostic leaves (8-bit ints, Buffer/String) can be forced into the slower whole-record shiftmask tier merely because a nested cross-endian Struct's leaves carry the child's endian. The output is byte-identical either way (verified), so this is a tier-selection/performance inconsistency, not a correctness bug -- but the aligned gate is stricter than the tier's own definition of 'endianness matters'.

**Evidence.**

Gate (line 165-169):
        aligned = (
            all(f.letter is not None for f in fields)
            and all(f.bit_offset % 8 == 0 for f in fields)
            and all(f.endian == endian for f in fields)   # <- literal, every field
        )
Shiftmask swap (line 198-207):
                whole_bytes = (
                    f.kind in ("u", "s")
                    and f.bit_width % 8 == 0
                    and f.bit_width > 8
                )
                swap = (
                    f.bit_width // 8
                    if whole_bytes and f.endian != natural
                    else 0
                )
Repro: a big-endian Parent nesting a little-endian Child whose only leaves are a 4-byte Buffer and two UInt8 fields. All three leaves are byte-order-agnostic, yet:
  Child tier: struct
  Parent tier (expected struct): shiftmask
    c.tag endian=little kind=b
    c.flag endian=little kind=u
    x endian=big kind=u
  pack 414243440709  roundtrip True   (identical to what the struct tier would produce)

**Suggestion.** Make the aligned gate use the same 'does byte order actually matter' predicate the shiftmask tier uses. Replace `all(f.endian == endian for f in fields)` with a per-field check that only demands endian agreement where a swap would otherwise be needed, e.g. `all(f.endian == endian or f.kind == 'b' or f.bit_width <= 8 for f in fields)` (sub-byte fields are already excluded by the `bit_offset % 8 == 0` / `letter is not None` clauses). This keeps the two engines' notion of endianness consistent and lets more records ride the fast struct tier.

---

## 40. NarrowingList (user-facing live array-field type) is missing from __all__ though sibling BoundField/BoundBits are exported

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:108-131`](../bytemaker/structs.py#L108)

**What.** Array field access returns a live NarrowingList (the array analog of the BoundField/BoundBits live handles). NarrowingList has a public name (no leading underscore) and a full public docstring, and users receive it directly, so it is de facto public API and the natural type to isinstance-check or annotate against. Yet BoundField and BoundBits are both listed in __all__ while NarrowingList is not -- an inconsistent export policy across the three live-view types this module hands out.

**Evidence.**

__all__ (structs.py:108-131) contains "BoundField" and "BoundBits" but NOT "NarrowingList".
Verified: for `class P(Struct): colors: Annotated[list, UInt16*4]`, `type(p.colors).__name__ == 'NarrowingList'` and `isinstance(p.colors, NarrowingList) == True`; while `'NarrowingList' in structs.__all__` is False and `'BoundBits' in __all__`, `'BoundField' in __all__` are both True.
NarrowingList is declared public with a docstring at structs.py:280-292.

**Suggestion.** Add "NarrowingList" to __all__ alongside BoundField/BoundBits, or, if it is intended to be internal, rename it with a leading underscore and stop presenting it with a public docstring -- so the export policy for the live-view types is uniform.

---

## 41. twos_complement docstring documents ':param bits:' but the parameter is named n_bits

**Severity:** low · **Confidence:** high · [`bytemaker/utils.py:314-325`](../bytemaker/utils.py#L314)

**What.** The function signature is `twos_complement(number, n_bits=32)`, but the reStructuredText field list documents the width parameter as ':param bits:'. There is no parameter named 'bits'. A tooltip/Sphinx render would show documentation for a non-existent parameter and no doc for the real n_bits. This is a docstring-vs-code name mismatch, distinct from the already-recorded out-of-range behavior bug.

**Evidence.**

def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    :param number: The integer to convert.
    :param bits: The bit width for the two's complement representation.
    :return: A string representing the two's complement of the number.
    """

**Suggestion.** Rename the doc field to ':param n_bits:' to match the actual parameter name.

---

## 42. Multi-character str handled by different code paths in to_bits_aggregate vs to_bytes_aggregate

**Severity:** low · **Confidence:** medium · [`bytemaker/_legacy_aggregate.py:255-257, 359-360`](../bytemaker/_legacy_aggregate.py#L255)

**What.** to_bits_aggregate deliberately excludes a multi-character str from the 'individual unit' fast path with `and not (isinstance(..., str) and len(...) > 1)`, so a multi-char string falls through to the Iterable branch and is serialized character-by-character. to_bytes_aggregate has no such carve-out: since str is part of UnitType, a multi-char string is routed straight to to_bytes_individual/pytype_to_bytes as one whole unit. For plain ASCII the results coincide, but the two sibling serializers structurally handle the same input via different paths, so any encoding where whole-string bytes differ from per-character concatenation would round-trip differently through the two functions. This is a latent divergence between two implementations of the same aggregate concept.

**Evidence.**

to_bits_aggregate (255-257):
    if is_instance_of_union(convertible_object, UnitType) and not (
        isinstance(convertible_object, str) and len(convertible_object) > 1
    ):
        ret_bits = to_bits_individual(convertible_object)

to_bytes_aggregate (359-360) — no str carve-out:
    if is_instance_of_union(units, UnitType):
        ret_bytes = to_bytes_individual(units, endianness=endianness)

**Suggestion.** Decide on one policy for multi-char str and apply it to both functions: either add the same `not (isinstance(units, str) and len(units) > 1)` carve-out to to_bytes_aggregate, or remove it from to_bits_aggregate so both treat a string as a single unit. Sync into both paths.

---

## 43. _table_bytes_per_char reason message describes the key when the failing condition is the value

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/string.py:34-37`](../bytemaker/bittypes/string.py#L34)

**What.** The rejection reason surfaced when a table cannot declare a fixed bytes-per-char is worded as if it is describing the key, but the branch it belongs to fires on the VALUE (`v`) not being a single character (e.g. a control code like "[PK]"). The parenthetical "(one wire unit, not one character)" is attached after `{v!r}`, reading as though `v` is one wire unit; but `v` is the decoded text side, and the thing that is "not one character" is precisely `v`. The message ends up self-contradictory: it says the value is "one wire unit, not one character" when the value is neither a wire unit nor a single char. This string is user-facing: it is embedded into the TypeError raised by String.of() when nchars= is used with such a table (lines 415-421).

**Evidence.**

```
        if not (isinstance(v, str) and len(v) == 1):
            return None, (
                f"{kb!r} maps to {v!r} (one wire unit, not one character)"
            )
```
The check rejects when `v` is not a length-1 str, but the message frames `v` as "one wire unit". A clearer message would name the value: e.g. `f"{kb!r} maps to {v!r}, which is not a single character"`.

**Suggestion.** Reword to describe the value: `f"{kb!r} maps to {v!r} (a control code / multi-character value, so character count is undefined)"`, so the reason string matches the condition it reports.

---

## 44. pyi types startswith/endswith substrings as bytes, but the .py accepts a much wider union

**Severity:** low · **Confidence:** medium · [`bytemaker/bitvector/bitvector.pyi:230-235`](../bytemaker/bitvector/bitvector.pyi#L230)

**What.** The spec .pyi declares `startswith(self, substrings: bytes, ...)` and `endswith(self, substrings: bytes, ...)`, but every runtime implementation accepts a far wider parameter — `Union[BitsConstructible, BitVector, Literal[0, 1], Iterable[Union[BitsConstructible, BitVector]]]` — and is documented and tested against that union (e.g. `startswith(('101','0'))`, `startswith(1)`). A caller passing anything other than `bytes` (the normal case: a BitVector, a 0/1 str, an int, or a tuple of substrings) is flagged by a type checker against the guaranteed spec even though it is the intended, working API. The .pyi is the narrower/wrong side.

**Evidence.**

pyi (bitvector.pyi lines 233-235): `def startswith(self, substrings: bytes, start: int = 0, stop: Optional[int] = None) -> bool: ...` (endswith identical, 230-232).
.py (bitvector_speedup.py lines 1353-1363): `substrings: Union[BitsConstructible, BitVector, Literal[0, 1], Iterable[Union[BitsConstructible, BitVector]]]`.
Repro: BitVector('0101').startswith(('01','10')) -> True (works); passing anything but bytes violates the pyi type.

**Suggestion.** Widen the .pyi `startswith`/`endswith` `substrings` parameter to the same union the implementations declare (BitsConstructible / bit / iterable of substrings), so the guaranteed spec matches the real, documented signature.

---
