# Solutions — Plan engine validation (plans.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Both findings are the same disease in the two halves of the Plan bulk escape hatch: the shiftmask tier trusts the caller's argument shape (int.from_bytes with no length check; zip that truncates), while the struct tier mostly fails loudly via struct.error -- so the same documented public method (plans.py:122-124 promotes unpack_tuple/pack_tuple/iter_tuples as the 'public bulk escape hatch') silently corrupts on one tier and raises on the other, and the tier a record lands on is invisible to callers. The fix is one explicit shape guard at the top of each method, applied to BOTH tiers, raising a uniform ValueError that names expected vs actual -- this also fixes a latent struct-tier hole verified during repro: pack_tuple with too MANY values silently truncated on the aligned tier too, because the wrap-retry path re-packs with zip-truncated _wrap_values. Uniform ValueError (rather than mimicking struct.error) matches the style of Struct.parse and Plan.validate_tuple, and with a single user there is no compat pressure to preserve the old exception type. The two solutions are independent; apply plans-1 then plans-2 (adjacent methods, file order). The internal fast paths are unaffected: Struct.parse pre-validates length, Struct.pack always passes an exact tuple, and the struct-tier iter_tuples branch bypasses unpack_tuple via iter_unpack, so the added cost is one len() comparison per call. Verified on a patched copy: all four wrong-shape cases now raise on both tiers, correct usage is byte-identical, and the full 854-test suite passes. No sync needed with _legacy_aggregate.py or the BitVector triplet -- neither uses these methods.

_2 solutions — 2 apply-now, 2 empirically verified on a patched copy._

---

## 1. Validate buffer length at the top of Plan.unpack_tuple so both tiers reject wrong-length input with a uniform ValueError

**Priority:** **now** · [`bytemaker/plans.py:220-236`](../../bytemaker/plans.py#L220) · **✓ verified on a patched copy**

**Problem.** unpack_tuple is the documented public bulk escape hatch, but on the shiftmask tier it decodes ANY input length: too-long buffers read fields from the wrong byte positions and too-short buffers fabricate records with missing high bytes read as zero -- silent data corruption, while the struct tier raises struct.error for the same mistake.

**Fix.** Add a length guard as the first statement of unpack_tuple, before the tier branch: if len(data) != self.num_bytes, raise ValueError naming expected vs actual. Guarding both tiers (not just the shiftmask branch) makes the error type and message identical regardless of which engine the record compiled to -- the tier is an invisible implementation detail, so cross-tier uniformity is the point. ValueError is chosen over struct.error to match Struct.parse (structs.py:829-832) and Plan.validate_tuple, which already raise ValueError for shape problems. The docstring gains a sentence documenting the contract, in the file's narrative RST style. Cost is one O(1) len() comparison; the struct-tier iter_tuples branch bypasses unpack_tuple entirely (iter_unpack), so the aligned bulk hot loop is untouched.

**Before:**

```python
    def unpack_tuple(self, data) -> tuple:
        """Decode one record's bytes into a flat tuple of plain values."""
        if self.tier == "struct":
            return self.struct_obj.unpack(data)
        raw = int.from_bytes(bytes(data), self._int_order)
        out = []
        for shift, mask, sign_bit, swap, nbytes in self.shift_masks:
            v = (raw >> shift) & mask
            if nbytes:
                out.append(v.to_bytes(nbytes, self._int_order))
                continue
            if swap:
                v = _bswap(v, swap)
            if sign_bit and v & sign_bit:
                v -= sign_bit << 1
            out.append(v)
        return tuple(out)
```

**After:**

```python
    def unpack_tuple(self, data) -> tuple:
        """Decode one record's bytes into a flat tuple of plain values.

        ``data`` must be exactly :attr:`num_bytes` long; a wrong-length
        buffer raises ``ValueError`` on both tiers rather than decoding
        from the wrong byte positions.
        """
        size = data.nbytes if isinstance(data, memoryview) else len(data)
        if size * 8 != self.num_bits:
            raise ValueError(
                f"unpack_tuple: expected {self.num_bits // 8} bytes, got {size}"
            )
        if self.tier == "struct":
            return self.struct_obj.unpack(data)
        raw = int.from_bytes(bytes(data), self._int_order)
        out = []
        for shift, mask, sign_bit, swap, nbytes in self.shift_masks:
            v = (raw >> shift) & mask
            if nbytes:
                out.append(v.to_bytes(nbytes, self._int_order))
                continue
            if swap:
                v = _bswap(v, swap)
            if sign_bit and v & sign_bit:
                v -= sign_bit << 1
            out.append(v)
        return tuple(out)
```

**Behavior change.** Repro (Shift = UInt4+UInt12, shiftmask tier, num_bytes=2; Aligned = UInt8+UInt8, struct tier, num_bytes=2).
BEFORE (pristine repo):
  unpack_tuple shiftmask b'\x12'   -> (2, 1)          [silent, fabricated: missing high byte read as 0]
  unpack_tuple shiftmask b'\x124V' -> (2, 833)        [silent garbage from wrong byte positions]
  unpack_tuple struct    b'\x12'   -> error: unpack requires a buffer of 2 bytes
  unpack_tuple struct    b'\x124V' -> error: unpack requires a buffer of 2 bytes
AFTER (patched copy):
  unpack_tuple shiftmask b'\x12'   -> ValueError: unpack_tuple: expected 2 bytes, got 1
  unpack_tuple shiftmask b'\x124V' -> ValueError: unpack_tuple: expected 2 bytes, got 3
  unpack_tuple struct    b'\x12'   -> ValueError: unpack_tuple: expected 2 bytes, got 1
  unpack_tuple struct    b'\x124V' -> ValueError: unpack_tuple: expected 2 bytes, got 3
Correct usage unchanged: roundtrip shiftmask (1, 564) ok; roundtrip struct (1, 2) ok; memoryview input ok; iter_tuples over b'\x12\x34'*3 -> [(2, 833), (2, 833), (2, 833)].
Side effect (beneficial): iter_tuples with an over-large explicit count on the shiftmask tier previously fabricated zero records -- BEFORE: iter_tuples(2-record buf, 0, count=4) -> [(2, 833), (2, 833), (0, 0), (0, 0)]; AFTER -> ValueError: unpack_tuple: expected 2 bytes, got 0.
Full suite on the patched copy: 854 passed.

**Tests to add.** In test/structs_test.py, next to test_plan_unpack_tuple_and_iter_tuples (line 1135), using a shiftmask-tier Struct (e.g. class ShiftRec(Struct): a: UInt4; b: UInt12) and an aligned one (a: UInt8; b: UInt8):
1. pytest.raises(ValueError, match=r"expected 2 bytes, got 1"): ShiftRec.plan.unpack_tuple(b"\x12") -- and the same for the aligned plan (previously struct.error).
2. pytest.raises(ValueError, match=r"expected 2 bytes, got 3"): ShiftRec.plan.unpack_tuple(b"\x12\x34\x56").
3. Exact-length still decodes: ShiftRec.plan.unpack_tuple(b"\x12\x34") == (4 low bits, 12 high bits) per bit_order, and memoryview(b"\x12\x34") is accepted identically.
4. Regression for the iter_tuples side effect: pytest.raises(ValueError): list(ShiftRec.plan.iter_tuples(b"\x12\x34" * 2, 0, count=4)) -- previously yielded two fabricated (0, 0) records.

**Risks / sync obligations / review notes.** 1) Exception-type change on the aligned tier: wrong-length input now raises ValueError instead of struct.error. No test relied on struct.error (854/854 pass on the patched copy). 2) data must now support len(): bytes/bytearray/memoryview all do; a hypothetical iterable-of-ints input that bytes(data) used to accept would now fail -- every internal caller (Struct.parse, iter_tuples' shiftmask branch, Array.parse via iter_tuples) passes sized byte buffers. A memoryview with itemsize > 1 would count items, not bytes, but no caller produces one. 3) Behavior change in iter_tuples: an explicit over-large count on the shiftmask tier now raises ValueError instead of fabricating (0, 0) records from out-of-range slices (verified; see behavior). This partially overlaps bugs.md finding 26 (iter_tuples over-count) -- if another group fixes iter_tuples directly, coordinate so its chosen error/truncation policy supersedes this incidental raise. 4) No sync needed: _legacy_aggregate.py and the three BitVector implementations do not use unpack_tuple. Re-run: full pytest suite (done, 854 passed). REVISION (adversarial review): guard rewritten to use the num_bits slot instead of the num_bytes property (reviewer measured the property at +45% per-call on the aligned tier; slot access is near-free) and to count memoryview inputs by nbytes, fixing the false rejection of itemsize>1 memoryviews that previously decoded correctly. Amended guard re-verified: bytes/bytearray/itemsize-1 and itemsize-2 memoryviews accepted at correct byte length, wrong lengths rejected. REVIEWER NOTE: the iter_tuples over-count side effect does NOT unify tiers - the struct tier still silently truncates on over-count; bugs.md finding 26 still owns that.

> ⚖️ **Decision needed:** Wrong-length input on the ALIGNED tier now raises ValueError instead of struct.error, and iter_tuples with an over-large explicit count on the shiftmask tier now raises instead of fabricating zero records -- confirm uniform ValueError is the wanted policy (the alternative is raising struct.error to keep the aligned tier's historical type).

<sub>covers: `bug|bytemaker/plans.py|220-236`, `ux|bytemaker/plans.py|220-236`</sub>

---

## 2. Validate value count at the top of Plan.pack_tuple so both tiers reject wrong-arity sequences with a uniform ValueError

**Priority:** **now** · [`bytemaker/plans.py:238-259`](../../bytemaker/plans.py#L238) · **✓ verified on a patched copy**

**Problem.** pack_tuple on the shiftmask tier zips shift_masks against values, so too-few values silently zero-fill the missing fields and too-many values are silently dropped -- wrong bytes with no signal. Verification also exposed that the ALIGNED tier silently truncates too-many values: struct.pack raises, and the wrap-retry fallback re-packs with zip-truncated _wrap_values (pack_tuple([5, 6, 7]) on a 2-field aligned plan returned b'\x05\x06').

**Fix.** Add an arity guard as the first statement of pack_tuple, before the tier branch: if len(values) != len(self.fields), raise ValueError naming expected vs actual counts. Placing it at the top (rather than inside the shiftmask branch) fixes the shiftmask zip-truncation AND the aligned tier's wrap-retry truncation in one guard, gives both tiers an identical error, and skips the wasted struct.pack attempt + retry the aligned tier previously burned on wrong-arity input. ValueError matches Struct.parse and validate_tuple. len(self.fields) is the right arity (one tuple entry per leaf field on both tiers; shift_masks is per-field too but is None on the struct tier). The docstring gains a sentence documenting the contract, keeping the existing wrap-semantics sentence intact. The internal caller Struct.pack always passes _bm_to_tuple(), which is exact by construction, so the hot path only pays one len() comparison.

**Before:**

```python
    def pack_tuple(self, values: Sequence) -> bytes:
        """Encode a flat sequence of plain values into one record's bytes.

        Out-of-range integers narrow C-style (wrap) rather than raising, at
        every width.
        """
        if self.tier == "struct":
            try:
                return self.struct_obj.pack(*values)
            except (_struct.error, TypeError):
                return self.struct_obj.pack(*self._wrap_values(values))
        acc = 0
        for (shift, mask, sign_bit, swap, nbytes), v in zip(
            self.shift_masks, values
        ):
            if nbytes:
                v = int.from_bytes(v, self._int_order)
            v &= mask
            if swap:
                v = _bswap(v, swap)
            acc |= v << shift
        return acc.to_bytes(self.num_bits // 8, self._int_order)
```

**After:**

```python
    def pack_tuple(self, values: Sequence) -> bytes:
        """Encode a flat sequence of plain values into one record's bytes.

        ``values`` must hold exactly one entry per leaf field; a wrong
        count raises ``ValueError`` on both tiers rather than zero-filling
        missing fields or dropping extras. Out-of-range integers narrow
        C-style (wrap) rather than raising, at every width.
        """
        if len(values) != len(self.fields):
            raise ValueError(
                f"pack_tuple: expected {len(self.fields)} values,"
                f" got {len(values)}"
            )
        if self.tier == "struct":
            try:
                return self.struct_obj.pack(*values)
            except (_struct.error, TypeError):
                return self.struct_obj.pack(*self._wrap_values(values))
        acc = 0
        for (shift, mask, sign_bit, swap, nbytes), v in zip(
            self.shift_masks, values
        ):
            if nbytes:
                v = int.from_bytes(v, self._int_order)
            v &= mask
            if swap:
                v = _bswap(v, swap)
            acc |= v << shift
        return acc.to_bytes(self.num_bits // 8, self._int_order)
```

**Behavior change.** Repro (same Shift/Aligned plans as plans-1, both need exactly 2 values).
BEFORE (pristine repo):
  pack_tuple shiftmask [5]       -> 0500               [missing field silently packed as 0]
  pack_tuple shiftmask [5, 6, 7] -> 6500               [extra value silently dropped]
  pack_tuple struct    [5]       -> error: pack expected 2 items for packing (got 1)
  pack_tuple struct    [5, 6, 7] -> 0506               [ALSO silent: struct.pack raises, the wrap-retry re-packs with zip-truncated _wrap_values]
AFTER (patched copy):
  pack_tuple shiftmask [5]       -> ValueError: pack_tuple: expected 2 values, got 1
  pack_tuple shiftmask [5, 6, 7] -> ValueError: pack_tuple: expected 2 values, got 3
  pack_tuple struct    [5]       -> ValueError: pack_tuple: expected 2 values, got 1
  pack_tuple struct    [5, 6, 7] -> ValueError: pack_tuple: expected 2 values, got 3
Correct usage unchanged: pack_tuple([1, 564]) -> b'\x41\x23' roundtrips to (1, 564) on shiftmask; (1, 2) on struct.
Full suite on the patched copy: 854 passed.

**Tests to add.** Same two record classes:
1. pytest.raises(ValueError, match=r"expected 2 values, got 1"): plan.pack_tuple([5]) on BOTH tiers.
2. pytest.raises(ValueError, match=r"expected 2 values, got 3"): plan.pack_tuple([5, 6, 7]) on BOTH tiers (the aligned tier previously returned b"\x05\x06" silently via the wrap-retry).
3. Exact count still packs and roundtrips: plan.unpack_tuple(plan.pack_tuple([1, 564])) == (1, 564) (shiftmask) and ([1, 2]) == (1, 2) (aligned); existing test_plan_pack_tuple_wraps (structs_test.py:1145) keeps passing (wrap semantics untouched).

**Risks / sync obligations / review notes.** 1) values must now support len(): the signature already declares Sequence, every internal caller passes a tuple, and the pre-existing struct-tier retry (_wrap_values) plus validate_tuple already zip over values, so generators were never reliably supported -- but a caller passing an iterator would now get TypeError from len() instead of (wrong) bytes. 2) Exception-type change on the aligned tier for too-few values: struct.error -> ValueError. 3) Aligned tier too-many values previously returned truncated bytes silently; code depending on that would break -- that dependence would be a live bug. 4) No sync needed: _legacy_aggregate.py and the BitVector triplet do not use pack_tuple; the C-style wrap narrowing semantics (test_plan_pack_tuple_wraps) are untouched. Re-run: full pytest suite (done, 854 passed with both guards applied). REVIEWER CORRECTION: correct-arity generators produced CORRECT bytes on both tiers pre-patch; the arity guard makes them TypeError (len() on a generator) - loud and arguably acceptable, but it is a regression on previously-working input, not a formalization of unsupported behavior as originally framed.

<sub>covers: `ux|bytemaker/plans.py|249-259`</sub>

---
