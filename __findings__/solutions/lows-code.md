# Solutions — Low-severity patterns: code nits

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; 1 flag(s) found and resolved by revision. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

36 lows clustered into 15 entries: 1 mooted ledger + 14 patterns. MOOT COUNT: 12 findings fully MOOTED by accepted cross-group solutions (lows-code-1 maps each to its fixer); 3 more partially mooted with residuals handled here (bwbs Args-lines and native __eq__ typo in lows-code-11, two TODO markers in lows-code-14); the :TEMP_UNUSED stray file (lows-code-15) turned out to be already gone — verified absent and never git-tracked. SEVERITY UPGRADES (1): the _legacy_aggregate multi-char-str divergence (lows-code-7) upgrades low → medium / priority now, because accepted pytypes-3 turns the latent divergence into a hard break (to_bytes_aggregate('hi') would raise); the carve-out must land with or before pytypes-3. Borderline-but-kept-low: from_int sign-bit corruption (lows-code-4) — silent data corruption, but a preserved three-backend contract with one in-tree caller; fixed across all three backends here. APPLY NOTES: lows-code-4 and -5 coordinate with lows-ux-2 / bitvector-behavior-3 on the same lines; lows-code-6 embeds aggregate-utils-5's docstring; lows-code-9's rename applies on top of float-1; lows-code-10 amends pytypes-1's method bodies (bytes(...) → .to_bits(...).to_bytes() for structural parity with the module functions); lows-code-14 keeps bittype.py:349's 'TODO remove' because lows-ux-5 makes it load-bearing. VERIFICATION: every pattern except the ledger and the .pyi widening was applied to the scratch copy at scratchpad/work/lows-code (patch.py, verify.py) — 80+ targeted checks passed and the full suite ran 854/854 both at baseline and with ALL patterns applied simultaneously, with zero test edits (the differential fuzz survived the three-backend from_int change; the little-endian multi-char delta b'ih' → b'hi' in lows-code-7 is confirmed and flagged in its risks).

_15 solutions — 1 apply-now, 14 empirically verified on a patched copy._

---

## 1. Mooted ledger: 12 lows already fixed by accepted cross-group solutions

**Priority:** later · `-`

**Problem.** Twelve of the 36 lows are fully handled by already-accepted solutions from other groups. No new edits are needed; this ledger records the mapping so the refs are accounted for and reviewers can confirm each moot instead of re-fixing.

**Fix.** CHECKLIST (all MOOTED, no action):
- fields.pyi:162 (module __getattr__ stub returns Any, over-accepting) — MOOTED by lows-ux-5, which explicitly rules to KEEP `-> Any` ('the only spelling that keeps `x: u999` legal in annotation position'), extends the explicit alias ladder with u128/s128/u256/s256, and sharpens the stub's note into the blunt rule the finding asked for ('other widths past 64 type as Any — add a descriptor class here if you need a checked width'). docs-misc-4 additionally adds __all__ to the stub.
- plans.py:249-259 (pack_tuple zip-truncates short value sequences on the shiftmask tier) — MOOTED by plans-2 (arity guard at the top of pack_tuple, both tiers, uniform ValueError).
- bittypes/bittype.py:254-264 (__repr__ docstring describes a format the code never emits) — MOOTED by docs-misc-1 (rewrites __repr__ to an eval-able kwargs form and the docstring with it).
- bittypes/float.py:24-42 (Float class/py_type docstrings copy-pasted from Int) — MOOTED by float-5.
- bittypes/buffer.py:20-21, 43-44 (docstring points at deleted Buffer1..Buffer1024 pre-defined subclasses; duplicate stray docstring literal) — MOOTED by buffer-1 (rewrites the docstring around of()/specialize() and deletes the orphaned literal).
- conversions/pytypes.py:302-314 (bits_to_pytype docstring documents bytes_obj/py_prim_type/PyTypeWithDefaultBytes) — MOOTED by pytypes-2.
- utils.py:314-325 (':param bits:' documents a non-existent parameter; real name is n_bits) — MOOTED by aggregate-utils-5 (renames to n_bits and converts the docstring to the file's Google style). NOTE: lows-code-6 layers range validation on the same function; its after-text embeds aggregate-utils-5's docstring so the two edits compose.
- bitvector_speedup.py:709-711, 722-724 ref (the defect itself is the bitarray backend's oct()/bin() docstrings claiming '0x') — MOOTED by bitvector-polish-1, which fixes bwbs:535 to '0o' and bwbs:551 to '0b'; the packed and native files were verified correct already. Impl coverage: bitarray backend only (the other two are clean).
- bwbs:1392, 1425, 1101 ('not in bitarray' wording; unreachable hand-written raises) — MOOTED by lows-ux-2, which rewords index/rindex to 'is not in BitVector', wraps the super().index() calls in try/except so the hand-written message becomes the real error path (fixing the dead-raise half of this finding), and applies the same one-line wrap to remove() at 1092, coordinated with bitvector-behavior-3's rework of remove()'s value coercion. Impl coverage: bitarray backend only; native/speedup already say 'is not in BitVector'.
- bwbs:1089 ('pop from empty bitarray') — MOOTED by bitvector-behavior-8, which rewrites the pop() prologue identically on all three backends with 'pop from empty BitVector' / 'pop index {raw} out of range for BitVector of length {n}'.
- bwbs:1320-1321 (find() docstring omits subsequence search) — MOOTED by lows-docs-3, which adds the '(or of the subsequence of bits if provided)' clause matching native and speedup.
- conversions/ctypes_.py:65 (commented-out debug print in reverse_ctype_endianness) — MOOTED by ctypes-1 (full rewrite of the function deletes the line; moot noted by the orchestrator).

**Behavior change.** No change; bookkeeping only.

**Tests to add.** None new. Each mooting solution carries its own tests; reviewers should tick this ledger off against those solutions when applying.

**Risks / sync obligations / review notes.** If any mooting solution is rejected or trimmed during application, the mapped low here revives; re-check this ledger after final selection. REVIEWER NIT: the ledger entry citing lows-ux-2 should carry that solution's own caveat - its remove() wrap was never applied to its verified copy and must be applied/verified at landing.

<sub>covers: `bug|bytemaker/fields.pyi|162`, `bug|bytemaker/plans.py|249-259`, `inconsistency|bytemaker/bittypes/bittype.py|254-264`, `inconsistency|bytemaker/bittypes/float.py|24-42`, `inconsistency|bytemaker/bittypes/buffer.py|20-21, 43-44`, `inconsistency|bytemaker/conversions/pytypes.py|302-314`, `inconsistency|bytemaker/utils.py|314-325`, `inconsistency|bytemaker/bitvector/bitvector_speedup.py|709-711, 722-724`, `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|1392, 1425, 1101`, `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|1089`, `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|1320-1321`, `sloppy-code|bytemaker/conversions/ctypes_.py|65`</sub>

---

## 2. plans.py tier parity: validate iter_tuples count; align the struct-tier endian gate with the swap predicate

**Priority:** soon · [`bytemaker/plans.py:plans.py 165-169, 280-290`](../../bytemaker/plans.py#L165) · **✓ verified on a patched copy**

**Problem.** Two remaining spots where the struct tier and the shiftmask tier disagree about the same input. (1) iter_tuples with an explicit count larger than the data: the struct tier silently truncates (iter_unpack yields fewer records), the shiftmask tier slices past the buffer end and fabricates records — and once plans-1's length guard lands in unpack_tuple, the shiftmask tier will raise instead, so the two tiers still disagree (truncate vs raise). (2) The aligned gate requires literal endian agreement from EVERY leaf, while the shiftmask tier's own swap logic knows byte order is meaningless for 'b' fields and single-byte ints; a record made entirely of byte-order-agnostic leaves gets demoted to the slow tier for no observable reason (output verified byte-identical either way by the audit).

**Fix.** CHECKLIST:
- plans.py:280-290 (iter_tuples) — compute avail once, before dispatching on tier; count=None keeps meaning 'as many whole records as fit'; an explicit count > avail raises ValueError naming requested vs available. Both tiers then behave identically, and the shiftmask generator can never slice out of range (defense in depth on top of plans-1's unpack_tuple guard). Fail-fast raise (not clamp) matches plans-1/plans-2's uniform-ValueError policy: an explicit count states a caller expectation.
- plans.py:165-169 (aligned gate) — exempt byte-order-agnostic fields from the endian-agreement clause using the same predicate the shiftmask tier's swap logic uses: kind 'b' (bytes payloads; struct '<Ns>'/'>Ns' are order-preserving either way) and bit_width <= 8 ints ('B'/'b' letters). Floats (kind 'f') are NOT exempted — they are byte-order-sensitive. Sub-byte fields are already excluded by the letter/bit_offset clauses, so the new clause never admits them alone.
Docstrings: iter_tuples gains one sentence stating the count contract, in the file's narrative RST style.

**Before:**

```python
        aligned = (
            all(f.letter is not None for f in fields)
            and all(f.bit_offset % 8 == 0 for f in fields)
            and all(f.endian == endian for f in fields)
        )
...
        size = self.num_bytes
        view = memoryview(buf)
        if count is None:
            count = (len(view) - offset) // size
        end = offset + count * size
```

**After:**

```python
        # Endianness only gates the struct tier where byte order is
        # observable: multi-byte u/s ints and floats. Byte-payload ('b')
        # and single-byte fields are byte-order-agnostic, mirroring the
        # shiftmask tier's swap predicate below.
        aligned = (
            all(f.letter is not None for f in fields)
            and all(f.bit_offset % 8 == 0 for f in fields)
            and all(
                f.endian == endian or f.kind == "b" or f.bit_width <= 8
                for f in fields
            )
        )
...
        size = self.num_bytes
        view = memoryview(buf)
        avail = (len(view) - offset) // size
        if count is None:
            count = avail
        elif count > avail:
            raise ValueError(
                f"iter_tuples: requested {count} records but only {avail}"
                f" whole records are available from offset {offset}"
            )
        end = offset + count * size
```

**Behavior change.** iter_tuples(explicit count too large) raises ValueError on both tiers instead of struct-truncating/shiftmask-fabricating. Records whose only cross-endian leaves are byte-order-agnostic now compile to the struct tier (faster; byte output unchanged). Array.parse always passes exact counts, so the normal API path is untouched.

**Tests to add.** VERIFIED on the patched copy: (a) iter_tuples count>avail raises ValueError on both a struct-tier (u16 record) and a shiftmask-tier (two-UInt4 record) plan ('iter_tuples: requested 3 records but only 2 whole records are available from offset 0'); count=None and exact counts return the same tuples as before (shiftmask tuples follow the plan's lsb bit order, matching parse). (b) The big-endian parent nesting a little-endian child (4-byte Buffer + u8 leaves) now compiles to tier 'struct' and round-trips; a genuinely endian-sensitive nesting (little u16 in a big record) still demotes to shiftmask. Full suite: 854 passed, no test edits needed. Add the (a)/(b) cases to plan_fastpath_test.py when applying.

**Risks / sync obligations / review notes.** Tier selection is observable via Plan.tier introspection and timing only; any test pinning 'shiftmask' for an all-agnostic mixed-endian record would need updating. The gate exemption must not outrun the swap predicate — floats deliberately stay strict.

<sub>covers: `bug|bytemaker/plans.py|272-290`, `inconsistency|bytemaker/plans.py|165-169, 198-207`</sub>

---

## 3. Make 1-bit sign-magnitude (and ones'-complement) SInt constructible: handle the zero-width magnitude field

**Priority:** soon · [`bytemaker/bittypes/int.py:int.py 221-224, 124-137`](../../bytemaker/bittypes/int.py#L221) · **✓ verified on a patched copy**

**Problem.** SInt1(0, int_format='signed_magnitude') crashes: int_to_signed_magnitude emits sign + unsigned_int_to_bitstring(magnitude, 0), and the zero-width helper returns '0' instead of '' (bin(0)[2:].zfill(0) == '0'), producing 2 bits for a 1-bit request. The decode side is equally broken: to_pyint's signed_magnitude branch does int(bitstring[1:], 2) which is int('', 2) → ValueError for a 1-bit string, and the ones_complement negative branch has the same empty-slice int() call. So the 1-bit degenerate width crashes on encode AND decode; both ends need the guard or the fix is untestable.

**Fix.** CHECKLIST (all in bytemaker/bittypes/int.py):
- int.py:221-224 (unsigned_int_to_bitstring, inside to_bitstring) — return '' for bit_length == 0 after the existing range check (which already rejects any n >= 1 at width 0). Only the signed_magnitude path ever passes width 0 (the unsigned entry path requires bit_length >= 1 at line 288-289), so no other caller changes.
- int.py:124-129 (to_pyint signed_magnitude branch) — compute the magnitude as int(bitstring[1:], 2) only when the string has magnitude bits, else 0.
- int.py:131-136 (to_pyint ones_complement negative branch) — same empty-slice guard; '1' decodes as -0 == 0, matching ones'-complement semantics.
int_to_signed_magnitude/int_to_ones_complement range guards already restrict a 1-bit signed value to 0, which is correct (sign bit + empty magnitude).

**Before:**

```python
        def unsigned_int_to_bitstring(n: int, bit_length: int):
            if n < 0 or n >= 2**bit_length:
                raise ValueError("Value out of range for the specified bit_length")
            return bin(n)[2:].zfill(bit_length)
...
        elif bin_format == "signed_magnitude" or bin_format == "sign_magnitude":
            # Handle sign-magnitude for signed integers
            if bitstring[0] == "1":  # Negative number
                int_value = -int(bitstring[1:], 2)
            else:  # Positive number
                int_value = int(bitstring[1:], 2)

        elif bin_format == "ones_complement":
            # Handle one's complement for signed integers
            if bitstring[0] == "1":  # Negative number
                int_value = -((2 ** (bit_length - 1)) - int(bitstring[1:], 2) - 1)
            else:  # Positive number
                int_value = int(bitstring, 2)
```

**After:**

```python
        def unsigned_int_to_bitstring(n: int, bit_length: int):
            if n < 0 or n >= 2**bit_length:
                raise ValueError("Value out of range for the specified bit_length")
            if bit_length == 0:
                return ""
            return bin(n)[2:].zfill(bit_length)
...
        elif bin_format == "signed_magnitude" or bin_format == "sign_magnitude":
            # Handle sign-magnitude for signed integers
            # (a 1-bit string has an empty magnitude field: +0 / -0)
            magnitude = int(bitstring[1:], 2) if bit_length > 1 else 0
            if bitstring[0] == "1":  # Negative number
                int_value = -magnitude
            else:  # Positive number
                int_value = magnitude

        elif bin_format == "ones_complement":
            # Handle one's complement for signed integers
            if bitstring[0] == "1":  # Negative number
                magnitude = int(bitstring[1:], 2) if bit_length > 1 else 0
                int_value = -((2 ** (bit_length - 1)) - magnitude - 1)
            else:  # Positive number
                int_value = int(bitstring, 2)
```

**Behavior change.** SInt1(0, int_format='signed_magnitude') constructs and round-trips (value 0); decoding a 1-bit '1' yields -0 == 0 in both non-two's-complement formats instead of ValueError. All wider widths bit-for-bit unchanged.

**Tests to add.** VERIFIED on the patched copy: SInt1(0, int_format='signed_magnitude') and ('ones_complement') construct with .value == 0 and 1-bit .bits; Int.to_bitstring(0, signed=True, bit_length=1, rep_format='signed_magnitude') == '0'; to_pyint('1') == 0 (minus zero) in both formats; wider widths unchanged (to_pyint('1010') == -2 sign-magnitude / -5 ones'-complement). Full suite 854 passed. Add these cases to bittypes_test.py when applying.

**Risks / sync obligations / review notes.** None beyond the degenerate width: bit_length > 1 paths take the identical int(bitstring[1:], 2) computation. narrowing-3/-4 touch SInt but not to_bitstring/to_pyint internals.

<sub>covers: `bug|bytemaker/bittypes/int.py|265-275`</sub>

---

## 4. from_int: size the overflow check with the two's-complement width so positive values keep their sign bit (all three backends)

**Priority:** soon · [`bytemaker/bitvector/bitvector_native.py:native 1688-1694, speedup 1807-1813, bwbs 1699-1705`](../../bytemaker/bitvector/bitvector_native.py#L1688) · **✓ verified on a patched copy**

**Problem.** from_int is signed by contract — size=None defaults to twos_complement_bit_length and the paired to_int defaults to signed=True — but the explicit-size overflow check uses int.bit_length(), which ignores the sign bit. from_int(127, 7) stores '1111111' and reads back as -1; from_int(-3, 2) stores '01' and reads back as +1. Identical in all three backends and the 4-week reference, so it is a preserved flaw, not a regression — but it silently corrupts round-trips. The only in-tree caller is pytypes.py:244 (int → from_int(num, size=32)), where values in [2**31, 2**32) currently corrupt silently on round-trip and will instead raise.

**Fix.** CHECKLIST (same edit, three files; per the sync convention all backends change together):
- bitvector_native.py:1688-1694 — replace the integer.bit_length() check with the two's-complement width.
- bitvector_speedup.py:1807-1813 — same.
- bitvector_with_bitarray_speedup.py:1699-1705 — same.
Compute `needed = twos_complement_bit_length(integer)` once; size=None keeps defaulting to it, and an explicit size < needed raises. COORDINATE with lows-ux-2, which rewrites the same ValueError's wording ('to a BitVector of size {size}') and the surrounding docstrings: apply its phrasing with this check's `needed` count. The docstring gains 'sized for a signed (two's-complement) round-trip; the minimum size for a non-negative integer includes a leading 0 sign bit'.

**Before:**

```python
        if size is None:
            size = twos_complement_bit_length(integer)
        if integer.bit_length() > size:
            raise ValueError(
                f"Cannot convert {integer} to Bits with size {size},"
                f" because it requires {integer.bit_length()} bits to represent."
            )
```

**After:**

```python
        needed = twos_complement_bit_length(integer)
        if size is None:
            size = needed
        if needed > size:
            raise ValueError(
                f"Cannot convert {integer} to a BitVector of size {size},"
                f" because it requires {needed} bits (sign bit included)"
                f" to represent."
            )
```

**Behavior change.** from_int(v, size) raises ValueError whenever to_int(signed=True) could not recover v — e.g. from_int(127, 7) and from_int(-3, 2) now raise instead of silently decoding as -1/+1. from_int with size=None, and every (value, size) pair that round-trips today, are unchanged. Via pytypes, converting an int in [2**31, 2**32) now raises instead of round-tripping to a negative.

**Tests to add.** VERIFIED on the patched copy, all three backends: from_int(127, 7) and from_int(-3, 2) raise ValueError; from_int(127, 8)/from_int(-3, 3) round-trip through to_int(signed=True); the existing pins (from_int(5) == '0101', from_int(-3) == '101', from_int(8, 2) raises) are unchanged. Full suite 854 passed with NO test edits — the differential fuzz stayed green because all three backends changed identically. Add the four new cases to bitvector_implementations_test.py when applying.

**Risks / sync obligations / review notes.** Behavior change on a documented 'temporary' API: callers deliberately using from_int for unsigned tight-width packing lose that spelling (the in-tree grep found none; the unsigned spelling is Int.to_bitstring/UInt). Differential fuzz generates (value, size) pairs — all three backends change identically so parity holds, but generated cases that formerly packed may now raise; suite run required. REVIEWER NOTE: merge the error-message wording with lows-ux-2 at landing (this fix says e.g. "9 bits", lows-ux-2 prescribes "needed=10, sign bit included" style - pick one voice).

> ⚖️ **Decision needed:** from_int could instead grow a signed: bool = True parameter (signed=False keeping the old bit_length check) — wider API for a method slated for removal; default proposal is the strict signed check only.

<sub>covers: `bug|bytemaker/bitvector/bitvector_speedup.py|1799-1815`</sub>

---

## 5. bitarray-backend __setitem__ int-key: validate the bit value before the index, matching the oracle

**Priority:** soon · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:bwbs 924-929`](../../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L924) · **✓ verified on a patched copy**

**Problem.** For v[i] = bad with BOTH an out-of-range index and an invalid bit value, the bitarray backend delegates raw ints to super().__setitem__, which bounds-checks the index first → IndexError; native and speedup coerce the value first → ValueError('bit must be 0 or 1, got 2'). Same input, different exception type on the default backend vs the oracle.

**Fix.** CHECKLIST:
- bwbs:924-929 — in the int-key branch, route int values through _coerce_bit before delegating, so value validation precedes the index bounds check exactly as in native/speedup. DEPENDS ON bitvector-behavior-3, which introduces the module-level _coerce_bit helper (verbatim from bitvector_speedup.py:128-135) into this file; if applied standalone, copy that eight-line helper in with this edit. Impl coverage: bitarray backend only — native and speedup already coerce first.

**Before:**

```python
        if isinstance(key, int):
            if not isinstance(value, int):
                value = BitVector(value)[0]
        elif not isinstance(value, (int, bitarray)):
            value = self.cast_if_not_bitvector(value)
        super().__setitem__(key, value)  # type: ignore[reportCallIssue]
```

**After:**

```python
        if isinstance(key, int):
            if isinstance(value, int):
                value = _coerce_bit(value)
            else:
                value = BitVector(value)[0]
        elif not isinstance(value, (int, bitarray)):
            value = self.cast_if_not_bitvector(value)
        super().__setitem__(key, value)  # type: ignore[reportCallIssue]
```

**Behavior change.** v[1] = 2 on an empty vector raises ValueError('bit must be 0 or 1, got 2') on all three backends (was IndexError on bitarray). Valid writes and pure index errors (v[1] = 0 on empty) unchanged.

**Tests to add.** VERIFIED on the patched copy (with the standalone _coerce_bit copy): v[1] = 2 on an empty vector raises ValueError('bit must be 0 or 1, got 2') on all three backends; v[1] = 0 on empty still raises IndexError; bool writes unchanged. Full suite 854 passed. Add the parity case to bitvector_implementations_test.py when applying.

**Risks / sync obligations / review notes.** Exception-type change for one already-erroring input; _coerce_bit accepts bools (True == 1) exactly like bitarray does, so no valid input changes.

<sub>covers: `bug|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|924-929`</sub>

---

## 6. twos_complement: validate the range so the result is always exactly n_bits wide

**Priority:** soon · [`bytemaker/utils.py:utils.py 314-325`](../../bytemaker/utils.py#L314) · **✓ verified on a patched copy**

**Problem.** twos_complement(number, n_bits) neither masks nor validates: twos_complement(300, 8) returns 9 characters and twos_complement(-200, 8) returns '00111000' (+56), a wrong-value encoding. The helper is unused in-tree, so this only bites direct callers — but a function named twos_complement that returns a non-two's-complement string is a trap. Out-of-range input is a caller bug: raise, don't mask (masking would silently bless exactly the corruption the finding demonstrates).

**Fix.** CHECKLIST:
- utils.py:314-325 — add a range guard raising ValueError when number is outside [-(2**(n_bits-1)), 2**(n_bits-1) - 1]; document the exact-width guarantee and the Raises. LAYERS ON aggregate-utils-5 (docstring: phantom ':param bits:' → Google-style Args/Returns): the after-text below embeds that accepted docstring and extends it with the width guarantee and Raises block, so apply this as the combined final form of the function.

**Before:**

```python
def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    :param number: The integer to convert.
    :param bits: The bit width for the two's complement representation.
    :return: A string representing the two's complement of the number.
    """
    if number < 0:
        number = (1 << n_bits) + number
    format_string = "{:0" + str(n_bits) + "b}"
    return format_string.format(number)
```

**After:**

```python
def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    Args:
        number (int): The integer to convert. Must fit in ``n_bits`` bits:
            ``-(2**(n_bits-1)) <= number < 2**(n_bits-1)``.
        n_bits (int, optional): The bit width for the two's complement
            representation. Defaults to 32.

    Returns:
        str: A string of exactly ``n_bits`` binary digits.

    Raises:
        ValueError: If ``number`` does not fit in ``n_bits`` bits.
    """
    if not -(1 << (n_bits - 1)) <= number < (1 << (n_bits - 1)):
        raise ValueError(
            f"{number} does not fit in {n_bits} bits in two's complement"
        )
    if number < 0:
        number = (1 << n_bits) + number
    format_string = "{:0" + str(n_bits) + "b}"
    return format_string.format(number)
```

**Behavior change.** In-range values return the identical string as before; out-of-range values raise ValueError instead of returning wrong-width/wrong-value strings. No in-tree callers, so no ripple.

**Tests to add.** VERIFIED on the patched copy: twos_complement(-200, 8) and (300, 8) raise ValueError; (-128, 8) == '10000000', (127, 8) == '01111111', (-1, 8) == '11111111', and the default-width tc(-5) are unchanged. Full suite 854 passed. Add the range cases to utils_test.py when applying.

**Risks / sync obligations / review notes.** None in-tree (helper unused); external callers relying on the overflow behavior were getting wrong answers. REVIEWER NOTE: the aggregate-utils-5 embed is a SUPERSESSION, not a byte-identical embed - this after-text rewrites the accepted Returns line and n_bits annotation. Coherent, but apply THIS version, not both.

<sub>covers: `bug|bytemaker/utils.py|314-325`</sub>

---

## 7. Oracle sync: give to_bytes_aggregate the same multi-char-str carve-out as to_bits_aggregate (required once pytypes-3 lands); drop the commented scaffolding

**Priority:** **now** · [`bytemaker/_legacy_aggregate.py:_legacy_aggregate.py 249-254, 264-266, 275-276, 286-288, 359-360`](../../bytemaker/_legacy_aggregate.py#L249) · **✓ verified on a patched copy**

**Problem.** SEVERITY UPGRADE RECOMMENDED (low → medium as a pairing requirement): to_bits_aggregate routes a multi-char str through the Iterable branch (char-by-char); to_bytes_aggregate sends it whole to to_bytes_individual. Today the outputs coincide (UTF-8 concatenation is per-char concatenation), so this was filed as a latent divergence — but accepted solution pytypes-3 makes the registered str codec a strict one-byte char that REJECTS multi-char strings, explicitly reasoning that 'to_bits_aggregate already routes multi-char strings through the Iterable branch'. Without this carve-out, to_bytes_aggregate('hi') goes from working to ValueError the moment pytypes-3 is applied. The same function region also carries dead commented scaffolding: debug prints, a half-disabled '# try:' / '# except Exception as e:' pair (the cited line 286), and a superseded list-comprehension draft.

**Fix.** ORACLE PROCEDURE: _legacy_aggregate.py is the frozen reference; per the sync-both-paths convention this is a single-copy edit (aggregate_types.to_bytes_aggregate only short-circuits plan-eligible dataclasses and delegates everything else here — verified by aggregate-utils-3's audit of the same function), applied with the parity suite green and the equivalence note recorded.
CHECKLIST:
- _legacy_aggregate.py:359-360 — add the identical carve-out to_bits_aggregate uses at 255-257, so both serializers treat a multi-char str as an iterable of chars. One policy, both paths (Option A of the finding). MUST land with or before pytypes-3.
- _legacy_aggregate.py:249-254, 264-266, 275-276, 286-288 — delete the commented debug prints, the dangling '# try:'/'# except' pair, and the superseded comprehension draft inside to_bits_aggregate (comment-only; zero behavior). COORDINATE: lows-ux-2 rewrites the raise message at 282-285 and aggregate-utils-3 adds the final else-raise to to_bytes_aggregate at 371+; neither edit overlaps these lines textually.
Impl coverage: single file; the public wrapper in conversions/aggregate_types.py re-exports these functions, no second copy exists.

**Before:**

```python
    if is_instance_of_union(units, UnitType):
        ret_bytes = to_bytes_individual(units, endianness=endianness)
...
    # print("to_bits_aggregate", convertible_object)
    # print("type(units)", type(convertible_object))
    # print("isinstance(units, DataClassType)",
    # isinstance(convertible_object, DataClassType))

    # try:
```

**After:**

```python
    if is_instance_of_union(units, UnitType) and not (
        isinstance(units, str) and len(units) > 1
    ):
        ret_bytes = to_bytes_individual(units, endianness=endianness)
...
    (commented scaffolding at 249-254, 264-266, 275-276, 286-288 deleted;
     code lines between them unchanged)
```

**Behavior change.** Multi-char strings serialize per-character through both aggregate entry points; output bytes are identical to today's for every currently-working input (verified before/after). After pytypes-3, to_bytes_aggregate('hi') keeps working instead of raising. Empty and 1-char strings take the individual path as before.

**Tests to add.** VERIFIED on the patched copy: to_bytes_aggregate('hi') == b'hi' == bytes(to_bits_aggregate('hi')), through both bytemaker._legacy_aggregate and the conversions.aggregate_types wrapper; single-char and dataclass-with-str cases unchanged. Full suite (parity oracle included) 854 passed. Add the equality assertion to aggregate_types_test.py when applying.

**Risks / sync obligations / review notes.** Endianness delta, CONFIRMED on the patched copy: to_bytes_aggregate('hi', endianness='little') changes b'ih' → b'hi' — per-char to_bytes_individual applies the byte reversal within each 1-byte char (a no-op) where the old whole-string path reversed the string's bytes. That IS the unification the finding asks for (matching the to_bits path), but it is the one input whose bytes change; flagged for review. REVIEWER DISCLOSURE (substantive, from the three-world reproduction): the "one input whose bytes change" claim is only true against the PRISTINE baseline. Against the pytypes-3 world this carve-out must pair with, to_bytes_aggregate(Rec('ABC', 5)) REVERTS from pytypes-3's loud serialize-time ValueError (literally one of pytypes-3's suggested tests) back to silently emitting non-round-trippable b'ABC\x00\x00\x00\x05'. On the plus side, the carve-out resolves the pytypes-3 bits/bytes dual divergence (both paths per-char).

> ⚖️ **Decision needed:** String policy for the legacy aggregate path - pick one: (a) strict one-char everywhere (pytypes-3 as-is, no carve-out): multi-char strings fail loudly on both paths; simplest and most honest, but breaks to_bytes_aggregate('hi') uses; (b) this carve-out as proposed: per-char semantics restored on both paths, but structured records with multi-char str fields silently emit more bytes than the declared width (the Rec regression above); (c) carve-out PLUS a declared-width check at serialize time: per-char when the encoded length matches the declared bits, loud ValueError when it does not - restores both behaviors at the cost of a few extra lines in both paths (recommended).

<sub>covers: `inconsistency|bytemaker/_legacy_aggregate.py|255-257, 359-360`, `sloppy-code|bytemaker/_legacy_aggregate.py|286`</sub>

---

## 8. fields.py self-consistency: split the int/float alias claim; document the __dir__ 1..64 sample

**Priority:** later · [`bytemaker/fields.py:fields.py 3-6, 8-17, 114-116`](../../bytemaker/fields.py#L3) · **✓ verified on a patched copy**

**Problem.** Two places where the module's own text contradicts its code. (1) The docstring lead-in names f32 as an example of Annotated[int, ...] 'holding a plain int' — but float aliases are Annotated[float, Float32]. (2) The docstring promises 'Any integer width works' while __dir__ advertises only 1..64, so u100 resolves but is invisible to dir()/autocomplete; the bound is fine (dir cannot enumerate an unbounded namespace) but is nowhere stated.

**Fix.** CHECKLIST (doc-only, no behavior):
- fields.py:3-6 — split the sentence: integer aliases are Annotated[int, UIntN/SIntN]; float aliases are Annotated[float, FloatN]. Preserves the em-dash clause verbatim.
- fields.py:8-17 + 114-116 — state the dir() sample bound in the 'any width' paragraph and put a comment on the enumeration in __dir__. Keep the 1..64 list (useful autocomplete surface; matches the stub ladder's checked range per lows-ux-5).
COORDINATE: lows-docs-3 edits fields.py:19-22 and lows-ux-4 edits __getattr__ (88-91); no textual overlap with these lines.

**Before:**

```python
``u8``/``s16``/``f32``-style names are ``Annotated[int, UInt8]`` (etc.) at
runtime: the annotation tells a type checker the field holds a plain ``int``
— which is what ``Struct`` fields hold — while the metadata carries the
BitType for the plan compiler.
...
def __dir__():
    lazy = [f"{prefix}{n}" for prefix in ("u", "s") for n in range(1, 65)]
    return sorted(set(list(globals()) + __all__ + lazy))
```

**After:**

```python
``u8``/``s16``-style names are ``Annotated[int, UInt8]`` (etc.) at runtime,
and ``f16``/``f32``/``f64`` are ``Annotated[float, Float16]`` (etc.): the
annotation tells a type checker the field holds a plain ``int`` or ``float``
— which is what ``Struct`` fields hold — while the metadata carries the
BitType for the plan compiler.
...
just works — canonical named classes (``UInt4``, ``SInt5``, …) are reused
when they exist; other widths are minted via ``specialize`` and cached so
repeated lookups agree. ``dir()``/autocomplete advertise the common 1–64
widths as a sample; the lazy namespace itself is unbounded. Float aliases
are the fixed IEEE set (``f16`` / ``f32`` / ``f64``): an arbitrary float
width does not determine an exponent/mantissa split.
...
def __dir__():
    # dir() cannot enumerate the unbounded lazy namespace; advertise the
    # common 1..64 widths as a sample (__getattr__ accepts any positive
    # width).
    lazy = [f"{prefix}{n}" for prefix in ("u", "s") for n in range(1, 65)]
    return sorted(set(list(globals()) + __all__ + lazy))
```

**Behavior change.** None (docstring and comment only).

**Tests to add.** Docs-only; existing fields tests unaffected. Full suite as a smoke check.

**Risks / sync obligations / review notes.** None.

<sub>covers: `inconsistency|bytemaker/fields.py|3-6`, `inconsistency|bytemaker/fields.py|114-116`</sub>

---

## 9. Public-surface consistency: export NarrowingList, rename Float.to_binstring → to_bitstring, fix the .tbl rejection message

**Priority:** soon · [`bytemaker/structs.py:structs.py 108-131; float.py 118, 123; string.py 34-37`](../../bytemaker/structs.py#L108) · **✓ verified on a patched copy**

**Problem.** Three one-site consistency nits. (1) structs.py hands users live NarrowingList objects (array fields) with a public name and docstring, but exports only its siblings BoundField/BoundBits in __all__ — users cannot star-import the natural isinstance/annotation target. (2) The same operation is Int.to_bitstring but Float.to_binstring; no shared spelling exists across the numeric API. (3) _table_bytes_per_char's rejection reason attaches '(one wire unit, not one character)' to the VALUE, describing the key; the value is neither a wire unit nor a single char, so the user-facing TypeError from String.of(nchars=...) is self-contradictory.

**Fix.** CHECKLIST:
- structs.py:108-131 — add "NarrowingList" to __all__ after "BoundBits" (it is de facto public: returned to users, public name, public docstring at 280-292).
- float.py:123 + 118 — rename to_binstring to to_bitstring (definition and the single internal call site; repo-wide grep found no other references, tests included). No alias: bytemaker has one user and Int's spelling wins ('bits' is the codebase vocabulary). COORDINATE: float-1 rewrites this method's body under the old name — apply this rename to float-1's after-text (signature line and value-setter call site only; float-1's body is name-agnostic).
- string.py:34-37 — reword the reason to describe the value: "{kb!r} maps to {v!r}, which is not a single character". The surrounding docstring (22-27) already explains the control-code rationale.

**Before:**

```python
    "BoundField",
    "BoundBits",
...
    def to_binstring(
        self: Float | float, num_exponent_bits=8, num_mantissa_bits=23
    ) -> str:
...
        if not (isinstance(v, str) and len(v) == 1):
            return None, (
                f"{kb!r} maps to {v!r} (one wire unit, not one character)"
            )
```

**After:**

```python
    "BoundField",
    "BoundBits",
    "NarrowingList",
...
    def to_bitstring(
        self: Float | float, num_exponent_bits=8, num_mantissa_bits=23
    ) -> str:
...
        if not (isinstance(v, str) and len(v) == 1):
            return None, (
                f"{kb!r} maps to {v!r}, which is not a single character"
            )
```

**Behavior change.** from bytemaker.structs import * now provides NarrowingList; Float gains to_bitstring and loses to_binstring (no external callers existed); the String.of() TypeError for character-count-undefined tables reads correctly. No byte-level behavior changes.

**Tests to add.** VERIFIED on the patched copy: NarrowingList importable via star-import surface ('NarrowingList' in structs.__all__); Float32.to_bitstring(1.5) == the instance's bits.to01() and to_binstring is gone; _table_bytes_per_char reason for {0x01: '[PK]'} reads "b'\\x01' maps to '[PK]', which is not a single character". Full suite 854 passed with no test edits (no test referenced to_binstring or pinned __all__).

**Risks / sync obligations / review notes.** The rename breaks any out-of-tree to_binstring caller — none exist and the sole user owns both sides. public_api_test may pin __all__ contents; update it with the new export. REVIEWER CORRECTION: the coordination note misattributes the setter call site - it lives in float-3's after-text, not float-1's.

<sub>covers: `inconsistency|bytemaker/structs.py|108-131`, `inconsistency|bytemaker/bittypes/float.py|123-125`, `inconsistency|bytemaker/bittypes/string.py|34-37`</sub>

---

## 10. ConversionInfo.to_bytes/from_bytes: take endianness and mirror the module functions exactly

**Priority:** soon · [`bytemaker/conversions/pytypes.py:pytypes.py 62-81 (as rewritten by pytypes-1)`](../../bytemaker/conversions/pytypes.py#L62) · **✓ verified on a patched copy**

**Problem.** Two code paths perform the same pytype↔bytes conversion and disagree on endianness: module-level pytype_to_bytes/bytes_to_pytype reverse the byte string for endianness='little', while ConversionInfo.to_bytes/from_bytes have no endianness parameter and always emit canonical order. pytypes-1 (accepted) repairs these from broken classmethods into working instance methods but keeps them endianness-naive, so the API inconsistency survives that fix.

**Fix.** LAYERS ON pytypes-1 (apply after it):
CHECKLIST:
- pytypes.py to_bytes — add endianness: Literal['big', 'little'] = 'big' and use the module function's exact mechanism: self.to_bits(py_prim).to_bytes() then reverse for little. Using .to_bytes() rather than pytypes-1's bytes(...) spelling makes parity with pytype_to_bytes structural, not coincidental (bytes() left-pads sub-byte payloads while .to_bytes() right-aligns them — bool's 1-bit codec would differ: 0x80 vs 0x01).
- pytypes.py from_bytes — add the same parameter, reversing the input first, mirroring bytes_to_pytype.
- Args entries for the new parameter in both docstrings, matching the module functions' wording.

**Before:**

```python
# pytypes-1's accepted after-text (instance methods):
    def to_bytes(self, py_prim) -> bytes:
        ...
        return bytes(self.to_bits(py_prim))

    def from_bytes(self, bytes_obj) -> Any:
        ...
        return self.from_bits(BitVector(bytes_obj))
```

**After:**

```python
    def to_bytes(
        self, py_prim, endianness: Literal["big", "little"] = "big"
    ) -> bytes:
        """
        Convert a Python instance to its bytes representation.

        Args:
            py_prim: The Python instance to convert to bytes
            endianness: The byte order of the output. Defaults to "big".

        Returns:
            bytes: The bytes representation of the Python instance
        """
        retval = self.to_bits(py_prim).to_bytes()
        if endianness == "little":
            retval = retval[::-1]
        return retval

    def from_bytes(
        self, bytes_obj, endianness: Literal["big", "little"] = "big"
    ) -> Any:
        """
        Convert a bytes object to a Python instance.

        Args:
            bytes_obj (bytes): The bytes to convert
            endianness: The byte order of the input bytes. Defaults to "big".
        """
        if endianness == "little":
            bytes_obj = bytes_obj[::-1]
        return self.from_bits(BitVector(bytes_obj))
```

**Behavior change.** info.to_bytes(v, endianness) == pytype_to_bytes(v, endianness) and info.from_bytes(b, e) == bytes_to_pytype(b, type, e) for every registered codec; default 'big' keeps pytypes-1's output for whole-byte codecs.

**Tests to add.** VERIFIED on the patched copy (with pytypes-1's instance-method conversion applied together with this change): for every registered pytype with a conversion (int pos/neg, float, bool, str char), info.to_bytes(v, e) == pytype_to_bytes(v, e) and info.from_bytes round-trips like bytes_to_pytype, for both endianness values. Full suite 854 passed. Add the parity loop to pytypes_test.py when applying.

**Risks / sync obligations / review notes.** Amends pytypes-1's spelling (bytes(...) → .to_bits(...).to_bytes()); for bool the two differ (left- vs right-aligned single bit), and the module functions' .to_bytes() is the authoritative behavior being matched. bitvector-behavior-7 redefines to_bytes() semantics for multi-byte non-multiple-of-8 vectors — registered codecs are 1-bit or whole-byte, so unaffected.

<sub>covers: `inconsistency|bytemaker/conversions/pytypes.py|62-81`</sub>

---

## 11. Cross-backend residuals: tobase docstring, .pyi startswith/endswith union, bitarray-name leaks, tobytes override, __eq__ typo

**Priority:** later · [`bytemaker/bitvector/bitvector_native.py:native 516, 639; bwbs 147, 268, 495, after 984; bitvector.pyi 230-235`](../../bytemaker/bitvector/bitvector_native.py#L516) · **✓ verified on a patched copy**

**Problem.** Five same-shape residuals: a fix or a documented contract landed in one BitVector implementation (or the .pyi) but not its siblings. Each is a small sync; the cluster rule is 'the three backends and the spec file must read identically for identical behavior'. Two of the five are partially handled by accepted solutions; the checklist marks the exact residue.

**Fix.** CHECKLIST:
- (tobase '< 64') native:516 + bwbs:495 — replace 'The base to convert to. Currently must be a power of 2 (< 64).' with the packed file's correct 'The base to convert to (a power of 2, at most 64).' (guard accepts 64 in all three). Impl coverage: native + bitarray; speedup:676 already correct.
- (.pyi startswith/endswith) bitvector.pyi:230-235 — widen substrings from bytes to the union all three implementations accept and document: BitsConstructible | BitVector | Literal[0, 1] | Iterable[BitsConstructible | BitVector] (all names already imported in the stub). The spec file is the narrower/wrong side; bitvector-behavior-2 (bytearray/memoryview) touches the runtime branch only.
- (bitarray-name leaks) bwbs:147 + 268 — 'The bits of the bitarray' → 'The bits of the BitVector' in the __new__/__init__ Args. Residue only: 1166/1254 summary lines are MOOTED by lows-docs-2, and 1221/1293 inline comments stay per lows-docs-2's explicit ruling (they legitimately describe the underlying bitarray storage). Impl coverage: bitarray backend only; native/speedup say BitVector.
- (tobytes override) bwbs, after __bytes__ (984) — add the documented override native:1039/speedup:1157 both have, delegating to super().tobytes(); this puts the padding contract ('padded with 0s until a multiple of 8') and help() text on all three backends. COORDINATE: bitvector-behavior-7 adds to_bytes() docstrings contrasting tobytes(); this override is where the contrasted method's own docstring lives on the bitarray backend.
- (__eq__ typo) native:639 — 'This will only really true' → 'This will only really be true'. Residue only: the identical bwbs:636 typo is MOOTED by bitvector-behavior-6's __eq__ rewrite; speedup:790 already fixed. Impl coverage after this edit: all three correct.

**Before:**

```python
# native:516 / bwbs:495
            base (int): The base to convert to. Currently must be a power of 2 (< 64).
# bitvector.pyi:230-235
    def endswith(
        self, substrings: bytes, start: int = 0, stop: Optional[int] = None
    ) -> bool: ...
    def startswith(
        self, substrings: bytes, start: int = 0, stop: Optional[int] = None
    ) -> bool: ...
# bwbs:147 (and 268)
            source (Optional[Union[BitsConstructible, int]]): The bits of the bitarray
# native:639
        This will only really true if both objects are BitVectors.
```

**After:**

```python
# native:516 / bwbs:495
            base (int): The base to convert to (a power of 2, at most 64).
# bitvector.pyi:230-235
    def endswith(
        self,
        substrings: Union[
            BitsConstructible,
            "BitVector",
            Literal[0, 1],
            Iterable[Union[BitsConstructible, "BitVector"]],
        ],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> bool: ...
    def startswith(
        self,
        substrings: Union[
            BitsConstructible,
            "BitVector",
            Literal[0, 1],
            Iterable[Union[BitsConstructible, "BitVector"]],
        ],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> bool: ...
# bwbs:147 (and 268)
            source (Optional[Union[BitsConstructible, int]]): The bits of the BitVector
# bwbs, inserted after __bytes__ (984):
    def tobytes(self) -> bytes:
        """
        Convert the BitVector to a bytes object, with each group of 8 bits
            (most-significant first) becoming a byte.
        If the length of the BitVector is not a multiple of 8,
            the BitVector is padded with 0s until the length is a multiple of 8.
        """
        return super().tobytes()
# native:639
        This will only really be true if both objects are BitVectors.
```

**Behavior change.** Runtime behavior unchanged everywhere (tobytes() delegates to the same bitarray primitive __bytes__ already used); type checkers stop flagging the documented startswith/endswith forms; help() and docstrings agree across backends.

**Tests to add.** VERIFIED on the patched copy (all parts except the .pyi widening, which is checker-only and was not machine-checked): bytes(bv) == bv.tobytes() on the bitarray backend for byte-aligned and ragged lengths, and the override carries the padding docstring. Full suite 854 passed. Eyeball the stub widening against bitvector_speedup.py:1353-1363 when applying (all names it uses are already imported in the stub).

**Risks / sync obligations / review notes.** bitvector.pyi is the guaranteed-spec file: widening a parameter type is spec-loosening in the safe direction (accepting what implementations already guarantee). BitsConstructible in the stub already includes bytes, so no caller loses.

<sub>covers: `inconsistency|bytemaker/bitvector/bitvector_speedup.py|683-684`, `inconsistency|bytemaker/bitvector/bitvector.pyi|230-235`, `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|1166, 1221, 1254, 1293`, `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|978-984`, `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|636`</sub>

---

## 12. Delete the two remaining commented-out code stubs (BitType.__hash__, SInt.int_format)

**Priority:** later · [`bytemaker/bittypes/bittype.py:bittype.py 338-346; int.py 589-592`](../../bytemaker/bittypes/bittype.py#L338) · **✓ verified on a patched copy**

**Problem.** Two dead commented-out code blocks survive the other groups' deletions: the nine-line __hash__ draft in BitType (which leaves hashability looking undecided) and the four-line classproperty draft of int_format in SInt (superseded by the real instance attribute set in __init__ at 584-586). The hashability question the __hash__ stub raises has a definite answer: BitType defines __eq__ and is mutable (value/bits setters), so Python's implicit __hash__ = None is the correct, intentional state — the draft should go, not be restored.

**Fix.** CHECKLIST:
- bittype.py:338-346 — delete the commented __hash__ block (the adjacent '# Temporary methods / # TODO remove' lines at 348-349 belong to lows-code-14's triage and stay). Hashability stays implicit-None: mutable boxes must not go in sets/dict keys.
- int.py:589-592 — delete the commented '@classproperty/int_format' block (includes the decorator lines 589-590; the finding cites 591-592). The live int_format instance attribute at 584-586 is the real mechanism; narrowing-4 validates it at construction and does not reference the dead block.
Impl coverage: single-file each; no sibling copies exist (grep verified).

**Before:**

```python
    # def __hash__(self):
    #     """
    #     Returns the hash of the BitType.

    #     Because the only thing that matters is that the value for __eq__,
    #     the hash is based on just the BitType value.
    #     """
    #     # return hash(frozenset([self.__class__, self.value]))
    #     return hash(frozenset([self.value]))
...
    # @classproperty
    # @classmethod
    # def int_format(cls) -> str:
    #     return Config.signed_int_format
```

**After:**

```python
    (both blocks deleted; surrounding blank lines collapsed to one)
```

**Behavior change.** None; comments only. BitType instances remain unhashable (hash(UInt8(1)) raises TypeError), as before.

**Tests to add.** VERIFIED on the patched copy: hash(UInt8(1)) raises TypeError (implicit __hash__ = None), and the suite is unaffected by both deletions (854 passed). Optional pin when applying: with pytest.raises(TypeError): hash(UInt8(1)) — records that unhashability is a decision, closing the ambiguity the finding flagged.

**Risks / sync obligations / review notes.** None.

<sub>covers: `sloppy-code|bytemaker/bittypes/bittype.py|338-346`, `sloppy-code|bytemaker/bittypes/int.py|591-592`</sub>

---

## 13. Broad `except Exception` triage: narrow the plan-compile probe, document the byte-convertibility probe, keep the re-raisers

**Priority:** later · [`bytemaker/conversions/aggregate_types.py:aggregate_types.py 137-142; utils.py 245-250; bittype.py 129/142/474 (no change)`](../../bytemaker/conversions/aggregate_types.py#L137) · **✓ verified on a patched copy**

**Problem.** Five broad handlers were flagged. Two swallow: _get_record_plan catches Exception to mean 'not plannable, use the legacy engine', hiding genuine compiler bugs; _ByteConvertibleMeta.__instancecheck__ catches Exception around a bytes() probe. Three re-raise or protocol-return (bittype.py:129/142 wrap as ValueError with context; 474 returns NotImplemented inside the binary-operator protocol) — the finding itself calls these defensible.

**Fix.** CHECKLIST:
- aggregate_types.py:141 — narrow to `except PlanCompileError`. plans.py deliberately funnels every compile-time failure into PlanCompileError (it wraps foreign exceptions at plans.py:448 and 470), so that is the designed 'not plannable' channel; anything else escaping compile is now a real bug surfacing instead of a silent slow-path. Add `PlanCompileError` to the existing `from bytemaker.plans import compile_legacy_record_plan` import (line 41).
- utils.py:249 — KEEP broad, add the justifying comment: this is an isinstance() probe; a foreign __bytes__ raising anything means 'not byte-convertible', and letting it escape would make isinstance() itself throw. Deliberate-broad with a comment is the honest resolution here.
- bittype.py:129, 142 — NO CHANGE: they re-raise as ValueError carrying the original error text.
- bittype.py:474 — NO CHANGE: inside attempt_operation for binary dunders, where returning NotImplemented (rather than propagating a constructor failure) is what keeps reflected operations and duck-typed operands working.

**Before:**

```python
    try:
        return compile_legacy_record_plan(
            aggregate_type, resolve_field_types(aggregate_type)
        )
    except Exception:
        return None
...
    def __instancecheck__(self, __instance: Any) -> bool:
        try:
            bytes(__instance)
            return True
        except Exception:
            return False
```

**After:**

```python
    try:
        return compile_legacy_record_plan(
            aggregate_type, resolve_field_types(aggregate_type)
        )
    except PlanCompileError:
        return None
...
    def __instancecheck__(self, __instance: Any) -> bool:
        try:
            bytes(__instance)
            return True
        except Exception:
            # Deliberately broad: this is an isinstance() probe. A foreign
            # __bytes__ raising anything means "not byte-convertible";
            # propagating would make isinstance() itself throw.
            return False
```

**Behavior change.** Plan compilation failures other than PlanCompileError now propagate from aggregate conversions instead of silently degrading to the legacy engine (resolve_field_types' own failure modes included — it swallows TypeError internally; an escaping NameError from an unresolvable forward reference would previously fail later inside the legacy path anyway). Everything else unchanged.

**Tests to add.** VERIFIED on the patched copy: a dataclass with a non-compilable field (bare list) still yields _get_record_plan(...) is None, i.e. the legacy fallback survives the narrowing; full suite 854 passed (the aggregate round-trip tests exercise the fallback heavily). Add the fallback case to aggregate_types_test.py when applying.

**Risks / sync obligations / review notes.** If some exotic annotation makes compile_legacy_record_plan raise something not wrapped as PlanCompileError, conversion of that type now errors instead of limping through legacy — that surfacing is the point, but it is the one behavioral edge; suite run required. REVIEWER CORRECTION (rationale, not code): compile_legacy_record_plan signals not-plannable by returning None and never raises PlanCompileError from this call site (plans.py 448/470 re-wrap inside compile_plan, not called here) - the narrowed except is effectively dead code and the fallback works via the None channel. The edit is still safe and clearer than the broad except.

<sub>covers: `sloppy-code|bytemaker/conversions/aggregate_types.py|141 (also utils.py:249, bittyp`</sub>

---

## 14. TODO/FIXME triage: 13 markers — 2 mooted, 2 load-bearing keeps, 9 resolved in place

**Priority:** later · [`bytemaker/bittypes/string.py:see checklist`](../../bytemaker/bittypes/string.py#L1) · **✓ verified on a patched copy**

**Problem.** 13 TODO/FIXME/Todo markers remain package-wide: some are stale, one is load-bearing, several document the same unimplemented parameter three times. Blanket deletion would lose real signals; each marker gets an explicit verdict.

**Fix.** CHECKLIST (one verdict per marker; 'errors=' items change all three backends identically):
- bittype.py:349 ('# TODO remove' on to_bits/from_bits) — KEEP. Load-bearing: lows-ux-5 adds DeprecationWarning + migrates the oracle/test callers and explicitly records removal as the later step this marker tracks.
- string.py:112 ('TODO: Add support for sub-byte codepoint changes') — RESOLVE to a documented limitation: 'Sub-byte codepoint changes are not supported.' (a docstring promise nobody is working on becomes a stated contract).
- bitvector_native.py:260, bwbs:250, bitvector_speedup.py:347 (' # TODO' on the unimplemented errors= constructor param) — DELETE the trailing marker in all three; the speedup docstring already records the decision ('accepted for signature parity but not implemented').
- bitvector_native.py:284, bwbs:274 ('The error handling to use. TODO') — RESOLVE: adopt speedup's honest wording, appending its parity sentence to the native/bwbs __init__ docstrings and changing the Args line to 'The error handling to use (not implemented).' Impl coverage: native + bitarray (speedup 351-358 is the model).
- bitvector_native.py:523, bwbs:502 ('# TODO support non-multiple-of-two bases') — DELETE: aspirational; tobase's guard and (post-lows-code-11) docstring define the powers-of-two contract, and the packed backend already dropped the marker.
- bwbs:1013 ('# Todo: Verify memoization procedure' in __deepcopy__) — VERIFY then DELETE: runtime check that deepcopying a structure holding the same BitVector twice yields one shared copy (memo honored), then remove the marker.
- bwbs:1497, 1500 ('# todo' on the commented translate/maketrans stubs) — MOOTED by bitvector-polish-3 (deletes the whole stub block; the intent record lives in bitvector.pyi:268-271).
- fixed.py:8 ('the FrozenBitVector TODO in bitvector.pyi') — KEEP: not a work marker; a factual cross-reference to the recorded stub at bitvector.pyi:319.

**Before:**

```python
        errors: Optional[str] = None,  # TODO
...
            errors (Optional[str]): The error handling to use. TODO
...
        # TODO support non-multiple-of-two bases
        if base not in {2, 4, 8, 16, 32, 64}:
...
        # Todo: Verify memoization procedure
        retval = type(self)()
```

**After:**

```python
        errors: Optional[str] = None,
...
            errors (Optional[str]): The error handling to use (not implemented).
...
        if base not in {2, 4, 8, 16, 32, 64}:
...
        retval = type(self)()
```

**Behavior change.** None; comment and docstring changes only.

**Tests to add.** VERIFIED on the patched copy: the bwbs __deepcopy__ memo check the marker asked for passed (deepcopying [b, b] yields one shared copy, cp[0] is cp[1], distinct from and equal to the original) — the marker can go with its question answered. All triage edits applied; full suite 854 passed.

**Risks / sync obligations / review notes.** Deleting an aspirational marker loses a feature reminder — acceptable for a sole-user library where the contract is now documented instead.

<sub>covers: `sloppy-code|bytemaker (package-wide)|bittype.py:349, string.py:112,`</sub>

---

## 15. :TEMP_UNUSED stray file — already gone; verify absence and record the origin

**Priority:** later · `-` · **✓ verified on a patched copy**

**Problem.** The audit found a zero-byte file named ':TEMP_UNUSED' at the repo root (dated Jul 31 01:48) — a leading colon is invalid on NTFS, so it was almost certainly a shell-redirect artifact created from the WSL side (the worktree's .git file points at /mnt/c paths, so WSL sessions touch this tree).

**Fix.** CHECKLIST:
- Repo root — NO ACTION NEEDED: the file is already gone. Verified 2026-08-02 by three probes: Git Bash `ls -la` (no entry), PowerShell GetFiles + per-character code scan (no literal ':' name and no WSL-escaped U+F03A variant), and `git ls-files` (never tracked; `git status --porcelain` clean, so no deletion is pending either).
- .gitignore — no entry needed: the file was never tracked and the name cannot be created from the Windows side.
- Follow-up for the maintainer: if it reappears, the creating command is the bug — grep WSL shell history for a redirect typo of the shape `> :TEMP_UNUSED` (e.g. a mangled variable expansion like `>$TMP:TEMP_UNUSED`).

**Before:**

```python
-rw-r--r-- 1 belmo 197609 0 Jul 31 01:48 :TEMP_UNUSED   (audit evidence)
```

**After:**

```python
(no such file; nothing tracked, nothing ignored, nothing to delete)
```

**Behavior change.** None.

**Tests to add.** None applicable.

**Risks / sync obligations / review notes.** None. If a WSL process recreates it, deletion is safe (zero bytes, untracked).

<sub>covers: `sloppy-code|:TEMP_UNUSED (repo root, adjacent to the package)|-`</sub>

---
