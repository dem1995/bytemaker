# Solutions — BitVector behavioral divergences (3 impls + fixed.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; 1 flag(s) found and resolved by revision. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Strategy: for every cross-backend divergence, pick the semantics that match Python conventions and the documented contract, then implement it identically in all three BitVector implementations (bitarray is the active default); fixed.py rides on the dispatcher so it is patched once. Eight solutions cover the ten findings: two pop() findings merge into one rewrite, and the two float/TypeError findings share one _coerce_bit fix (they carry the same ref). All eight are independent — no fix depends on another being applied first — but a sensible order is: 1 (fixed.py corruption hole), 3 (active-backend bit coercion), 6 (equality contract), 7 (to_bytes alignment, also fixes a latent to_int wrong-value bug), then 4, 2, 5, 8. Solutions 2 and 5 interact benignly (both widen byte-like acceptance; apply in either order). Solutions 4, 7 and 8 embed policy choices recorded in their decision fields (extended-slice raise vs delete; to_bytes right vs left alignment; pop(-1) Python-style vs documented quirk — the latter edits a pinned parity test and its docstrings). Everything was verified empirically on a patched copy: per-finding before/after repros on all three backends, plus the full test suite (857 passed after updating the one pinned pop test; 851/854 green before that update with only the expected 3 pop failures). No changes touch _legacy_aggregate.py or its parity path.

_8 solutions — 4 apply-now, 8 empirically verified on a patched copy._

---

## 1. Compare the coerced bit length, not the raw element count, in FixedLengthBitVector.__setitem__

**Priority:** **now** · [`bytemaker/bitvector/fixed.py:fixed.py 75-88 (__setitem__ guard, 79-88)`](../../bytemaker/bitvector/fixed.py#L75) · **✓ verified on a patched copy**

**Problem.** The width-invariance guard compares the slice span to len(value) of the RAW source, not the bit length after coercion. 'v[0:3] = "0x0"' passes the guard (len 3 == span 3) but writes 4 bits, silently resizing the 'fixed' vector from 8 to 9 bits (silent BitType box corruption); conversely 'v2[0:8] = bytes([0xFF])' (8 bits, length-preserving) is wrongly rejected because len(bytes([0xFF])) == 1.

**Fix.** Normalize the value to a BitVector up front (unless it is an int, which broadcasts and is always length-preserving) and compare len(coerced) against the span. This admits every legitimate length-preserving write the base class accepts (bytes, '0b..'/'0x..' strings, memoryview, BitsCastable) and closes the resize hole, because the compared quantity is exactly what super().__setitem__ will write. Passing the already-coerced BitVector down to super() also avoids a second coercion. The guard logic is backend-agnostic (verified by simulating it over all three backends).

**Before:**

```python
    def __setitem__(self, key, value):
        # Length-preserving writes pass through; a step-1 slice assigned a
        # different-length value would resize, so pre-check and refuse.
        # (An int value broadcasts across the slice: always preserving.)
        if isinstance(key, slice) and not isinstance(value, int):
            span = len(range(*key.indices(len(self))))
            try:
                vlen = len(value)
            except TypeError:
                value = BitVector(value)
                vlen = len(value)
            if vlen != span:
                raise self._length_violation()
        super().__setitem__(key, value)
```

**After:**

```python
    def __setitem__(self, key, value):
        # Length-preserving writes pass through; a step-1 slice assigned a
        # different-length value would resize, so pre-check and refuse.
        # (An int value broadcasts across the slice: always preserving.)
        if isinstance(key, slice) and not isinstance(value, int):
            span = len(range(*key.indices(len(self))))
            # Compare the *bit length* of the coerced value, not the raw
            # element count: e.g. len('0x0') is 3 but BitVector('0x0') is
            # 4 bits, and len(bytes([0xFF])) is 1 but 8 bits.
            if not isinstance(value, BitVector):
                value = BitVector(value)
            if len(value) != span:
                raise self._length_violation()
        super().__setitem__(key, value)
```

**Behavior change.** Actual outputs (active bitarray backend; guard also simulated over native/speedup subclasses with identical results).
BEFORE:
  v[0:3]='0x0' : ('ok', None) len now 9   <- invariant broken, 8-bit fixed vector became 9 bits
  v2[0:8]=bytes([0xFF]): ('exc','ValueError','length is invariant (16 bits)...')   <- false block
  v3[0:2]='0b11': ('exc','ValueError','length is invariant (8 bits)...')   <- false block
AFTER:
  v[0:3]='0x0' : ('exc','ValueError','length is invariant (8 bits)...') len now 8
  v2[0:8]=bytes([0xFF]): ('ok', None) to01 1111111100000000
  v3[0:2]='0b11': ('ok', None) to01 11110000
Unchanged: same-length str write ok; wrong-length str write raises; int broadcast ok.

**Tests to add.** In the FixedLengthBitVector suite: (a) f = FixedLengthBitVector('0b'+'0'*8); with pytest.raises(ValueError): f[0:3] = '0x0'; assert len(f) == 8. (b) f = FixedLengthBitVector(bytes(2)); f[0:8] = bytes([0xFF]); assert f.to01() == '1111111100000000'. (c) f = FixedLengthBitVector('0b11110000'); f[0:2] = '0b11'; assert f.to01() == '11110000'. (d) f[0:3] = 1 broadcasts; assert f.to01()[:3] == '111' and len unchanged. (e) with pytest.raises(ValueError): f[0:3] = '11'. The class always sits on the dispatcher backend, so one suite suffices; if the parity suite grows a FixedLength section, parameterize over backends by subclassing each.

**Risks / sync obligations / review notes.** Non-BitVector values are now always coerced before the length check, so a value whose construction raises (e.g. malformed str) raises ValueError from the constructor instead of reaching super(); the base class would have done the same coercion anyway. BitType box writes go through this path (bittype.py 232, 592): re-run bittypes_test.py and structs_test.py (done: full suite green, 857 passed).

<sub>covers: `bug|bytemaker/bitvector/fixed.py|79-88`</sub>

---

## 2. Treat bytearray and memoryview as single substrings in startswith/endswith on all three backends

**Priority:** soon · [`bytemaker/bitvector/bitvector_speedup.py:bitvector_speedup.py 1444 (_normalize_substrings); bitvector_native.py 1321 (_normalize_substrings); bitvector_with_bitarray_speedup.py 1183 (startswith) and 1272 (endswith)`](../../bytemaker/bitvector/bitvector_speedup.py#L1444) · **✓ verified on a patched copy**

**Problem.** The single-substring dispatch checks isinstance(substrings, (str, bytes, BitsCastable)) and omits bytearray/memoryview, so those fall into the iterable-of-ints branch and each BYTE is fed to BitVector as a bit: v.startswith(bytearray([0xde])) raises ValueError('bit must be 0 or 1, got 222') on ALL THREE backends, while v.startswith(bytes([0xde])) and 'bytearray([0xde]) in v' both work.

**Fix.** Add bytearray and memoryview to the byte-like single-substring branch, matching the BitsConstructible spec in bitvector.pyi and the constructor's byte-source handling. The finding cites only bitvector_speedup, but the identical branch exists in bitvector_native._normalize_substrings and inline in the bitarray backend's startswith AND endswith (that file has no shared helper), so all four sites change identically. One-line change per site.

**Before:**

```python
# bitvector_speedup.py 1440-1445 and bitvector_native.py 1317-1322 (identical):
        if isinstance(substrings, BitVector):
            return [substrings]
        elif isinstance(substrings, int):
            return [BitVector([substrings])]
        elif isinstance(substrings, (str, bytes, BitsCastable)):
            return [BitVector(substrings)]

# bitvector_with_bitarray_speedup.py startswith 1183-1184 (endswith 1272-1273 identical):
        elif isinstance(substrings, (str, bytes, BitsCastable)):
            conv_substrings = [BitVector(substrings)]
```

**After:**

```python
# bitvector_speedup.py / bitvector_native.py:
        if isinstance(substrings, BitVector):
            return [substrings]
        elif isinstance(substrings, int):
            return [BitVector([substrings])]
        elif isinstance(substrings, (str, bytes, bytearray, memoryview, BitsCastable)):
            return [BitVector(substrings)]

# bitvector_with_bitarray_speedup.py, in BOTH startswith and endswith:
        elif isinstance(substrings, (str, bytes, bytearray, memoryview, BitsCastable)):
            conv_substrings = [BitVector(substrings)]
```

**Behavior change.** Actual outputs, v = BitVector(bytes([0xDE, 0xAD])):
BEFORE (all three backends identical):
  sw(bytes)=('ok', True) sw(bytearray)=('exc','ValueError','bit must be 0 or 1, got 222') sw(memoryview)=('exc','ValueError','bit must be 0 or 1, got 222') ew(bytearray)=('exc','ValueError','bit must be 0 or 1, got 173')
AFTER (all three backends identical):
  sw(bytes)=('ok', True) sw(bytearray)=('ok', True) sw(memoryview)=('ok', True) ew(bytearray)=('ok', True)

**Tests to add.** In test_startswith_endswith_argument_forms (already parameterized over all backends): bv = BitVector(bytes([0xde, 0xad])); assert bv.startswith(bytearray([0xde])); assert bv.startswith(memoryview(bytes([0xde]))); assert bv.endswith(bytearray([0xad])); assert not bv.startswith(bytearray([0xad])). Also keep an iterable-of-substrings case with a bytearray element: bv.startswith((bytearray([0xad]), bytearray([0xde]))) is True (that path already worked via is_instance_of_union once solution 5 lands, and via BitVector(bytearray) regardless).

**Risks / sync obligations / review notes.** A caller who deliberately passed bytearray([0,1,1]) expecting per-element bits now gets an 8-bits-per-byte interpretation — this matches how the constructor and __contains__ already treat bytearray, so the change unifies rather than splits behavior. Sites to keep in sync: 4 (two files' _normalize_substrings, plus startswith and endswith in the bitarray backend). Re-run bitvector_implementations_test.py and the differential fuzz (done: green).

<sub>covers: `bug|bytemaker/bitvector/bitvector_speedup.py|1444-1459`</sub>

---

## 3. Route append/insert/remove/extend through _coerce_bit in the bitarray backend

**Priority:** **now** · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:bitvector_with_bitarray_speedup.py 90-94 (new helper after __annotations__), 1030-1036 (append), 1038-1049 (extend), 1051-1061 (insert), 1092-1101 (remove)`](../../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L90) · **✓ verified on a patched copy**

**Problem.** The ACTIVE backend forwards bit values raw to bitarray's C layer, so (a) float bits 1.0/0.0 that both reference implementations accept raise TypeError, and (b) clearly invalid bits like '1' raise TypeError instead of the documented ValueError('bit must be 0 or 1, ...'). Same statement, different state/exception depending on which backend loaded. (This one solution resolves both findings at these lines — they share one root cause and one ref string.)

**Fix.** Define the same module-level _coerce_bit helper the other two implementations have (verbatim from bitvector_speedup.py) and call it in append, insert, and remove. In extend, keep the bitarray fast path for bitarray/BitVector inputs and coerce elementwise otherwise, mirroring the native implementation's split (BitVector concat vs per-element _coerce_bit). This makes value handling — including the ValueError type and message — byte-for-byte identical to the native oracle and its fuzz twin.

**Before:**

```python
    def append(self, value: int) -> None:
        """Appends the provided bit to end (right) of the BitVector.

        Args:
            value (int): The bit to append
        """
        super().append(value)

    def extend(  # type: ignore[reportIncompatibleMethodOverride]
        self, values: BitsConstructible
    ) -> None:
        """Extends the BitVector with the provided bits (appends them
            on the right).

        Args:
            values (BitsConstructible): The bits to append
        """
        if not isinstance(values, (Iterable)) or isinstance(values, str):
            values = BitVector(values)
        super().extend(values)

    def insert(  # type: ignore[reportIncompatibleMethodOverride]
        self, index: int, value: int
    ) -> None:
        """Inserts the provided bit at the given index (zero-indexed).
        All bits at or to the right of the index are shifted right.

        Args:
            index (int): The index at which to insert the bit
            value (int): The bit to insert
        """
        super().insert(index, value)

# ... and in remove (line 1101):
        super().remove(value)
```

**After:**

```python
# New module-level helper, placed after the __annotations__ block (line ~94),
# verbatim from bitvector_speedup.py:
def _coerce_bit(value: LaxLiteral01) -> int:
    """Validates that `value` is a 0 or 1 (or equal to one of them,
    e.g. booleans) and returns it as a plain int."""
    if value == 0:
        return 0
    if value == 1:
        return 1
    raise ValueError(f"bit must be 0 or 1, got {value!r}")


    def append(self, value: int) -> None:
        """Appends the provided bit to end (right) of the BitVector.

        Args:
            value (int): The bit to append
        """
        super().append(_coerce_bit(value))

    def extend(  # type: ignore[reportIncompatibleMethodOverride]
        self, values: BitsConstructible
    ) -> None:
        """Extends the BitVector with the provided bits (appends them
            on the right).

        Args:
            values (BitsConstructible): The bits to append
        """
        if not isinstance(values, (Iterable)) or isinstance(values, str):
            values = BitVector(values)
        if isinstance(values, bitarray):
            super().extend(values)
        else:
            super().extend(_coerce_bit(value) for value in values)

    def insert(  # type: ignore[reportIncompatibleMethodOverride]
        self, index: int, value: int
    ) -> None:
        """Inserts the provided bit at the given index (zero-indexed).
        All bits at or to the right of the index are shifted right.

        Args:
            index (int): The index at which to insert the bit
            value (int): The bit to insert
        """
        super().insert(index, _coerce_bit(value))

# ... and in remove:
        super().remove(_coerce_bit(value))
```

**Behavior change.** Actual outputs on v = BitVector('0b0101') (native and speedup shown for reference; they are unchanged):
BEFORE bitarray: append(1.0)=TypeError("'float' object cannot be interpreted as an integer"); insert(0,0.0)=TypeError; remove(1.0)=TypeError; extend([1.0,0.0])=TypeError; append('1')=TypeError("'str' object..."); insert(0,'0')=TypeError; remove('1')=TypeError; extend(['1'])=TypeError
AFTER bitarray (now identical to native/speedup): append(1.0)=('ok','01011'); insert(0,0.0)=('ok','00101'); remove(1.0)=('ok','001'); extend([1.0,0.0])=('ok','010110'); append('1')=ValueError("bit must be 0 or 1, got '1'"); insert(0,'0')=ValueError; remove('1')=ValueError; extend(['1'])=ValueError
Unchanged everywhere: append(2)=ValueError('bit must be 0 or 1, got 2'); extend('01') ok; extend(3) constructs 3 zero bits; extend(b'\xde')=ValueError('bit must be 0 or 1, got 222') on all three.

**Tests to add.** Parameterized over all three backends: (a) v=BitVector('0101'); v.append(1.0); v.insert(0, 0.0); assert v.to01()=='001011'; v.remove(1.0); assert v.to01()=='00011'... (b) v=BitVector('1'); v.extend([1.0, False, True]); assert v.to01()=='1101'. (c) for op in [lambda v: v.append('1'), lambda v: v.insert(0,'0'), lambda v: v.remove('1'), lambda v: v.extend(['1'])]: with pytest.raises(ValueError, match='bit must be 0 or 1'): op(BitVector('0101')). Also extend the differential fuzz harness to drive the bitarray backend in lockstep too (its _random_bit_value already generates 0.0/1.0/'1'), which would have caught this gap.

**Risks / sync obligations / review notes.** extend on plain non-bitarray iterables now runs Python-level per-element coercion instead of bitarray's C loop — a minor slowdown only on the generic-iterable path (BitVector/bitarray inputs keep the C fast path). bool remains accepted (== 0/1). frozenbitarray inputs are bitarray instances and keep the fast path. Re-run bitvector_implementations_test.py + differential fuzz (done: 857 passed).

<sub>covers: `bug|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|1036, 1049, 1061, 1101`</sub>

---

## 4. Raise ValueError for length-mismatched extended-slice assignment (including empty) on native and speedup

**Priority:** soon · [`bytemaker/bitvector/bitvector_native.py:bitvector_native.py 957-961 (__setitem__ slice/else branch); bitvector_speedup.py 1064-1070 (__setitem__ slice/else branch); bitvector_with_bitarray_speedup.py 908-929 cited but intentionally unchanged (it already has the chosen semantics)`](../../bytemaker/bitvector/bitvector_native.py#L957) · **✓ verified on a patched copy**

**Problem.** v[1:8:2] = BitVector('') silently DELETES the four selected positions on native and speedup (a bytearray quirk their storage inherits), while the ACTIVE bitarray backend raises ValueError — so the same statement shrinks the vector on two backends and raises on the third, and the silent shrink contradicts the method's own docstring ('for non-unit slice steps and index sequences, the lengths must agree').

**Fix.** Policy: the bitarray backend's list-like semantics WIN — any extended-slice (step != 1, including negative steps) assignment with a length mismatch raises ValueError, empty value included. It matches every standard Python sequence except bytearray, matches the already-documented contract, and is what the default backend already does. Implement by pre-checking span vs len(value) in the non-int slice branch of native and speedup __setitem__ before delegating to the backing bytearray; the bitarray backend needs no change. Side benefit: the error message ('attempt to assign sequence of size N to extended slice of size M') now matches the bitarray backend's wording instead of bytearray's 'attempt to assign bytes...'.

**Before:**

```python
# bitvector_native.py 957-961:
            else:
                value = self.cast_if_not_bitvector(value)
                # bytearray handles resizing for unit-step slices and
                # enforces matching lengths for extended slices
                self._bits[key] = value._bits

# bitvector_speedup.py 1064-1070:
            else:
                value = self.cast_if_not_bitvector(value)
                chars = self._to01_bytearray()
                # bytearray handles resizing for unit-step slices and
                # enforces matching lengths for extended slices
                chars[key] = value.to01().encode("ascii")
                self._reset01(chars)
```

**After:**

```python
# bitvector_native.py:
            else:
                value = self.cast_if_not_bitvector(value)
                if key.step not in (None, 1):
                    # Pre-check extended slices: bytearray would silently
                    # DELETE the selected positions for an empty value
                    # instead of raising like other sequences.
                    span = len(range(*key.indices(len(self._bits))))
                    if len(value._bits) != span:
                        raise ValueError(
                            f"attempt to assign sequence of size"
                            f" {len(value._bits)} to extended slice"
                            f" of size {span}"
                        )
                # bytearray handles resizing for unit-step slices
                self._bits[key] = value._bits

# bitvector_speedup.py:
            else:
                value = self.cast_if_not_bitvector(value)
                if key.step not in (None, 1):
                    # Pre-check extended slices: bytearray would silently
                    # DELETE the selected positions for an empty value
                    # instead of raising like other sequences.
                    span = len(range(*key.indices(self._len)))
                    if len(value) != span:
                        raise ValueError(
                            f"attempt to assign sequence of size {len(value)}"
                            f" to extended slice of size {span}"
                        )
                chars = self._to01_bytearray()
                # bytearray handles resizing for unit-step slices
                chars[key] = value.to01().encode("ascii")
                self._reset01(chars)
```

**Behavior change.** Actual outputs, v = BitVector('00000000'); v[1:8:2] = BitVector(''):
BEFORE: native ('ok') to01=0000 len=4 (SILENT DELETE); speedup ('ok') to01=0000 len=4; bitarray ValueError('attempt to assign sequence of size 0 to extended slice of size 4')
AFTER: all three ValueError('attempt to assign sequence of size 0 to extended slice of size 4'), vector unchanged (len 8).
Unchanged on all three: non-empty mismatch v[0:4:2]=len-1 still ValueError (message on native/speedup now says 'sequence' instead of bytearray's 'bytes'); empty-to-empty v[2:2:2]='' still a no-op; v[::-1]='0011' still assigns reversed; unit-step resize v[0:4:1]=len-2 still resizes.

**Tests to add.** Extend test_setitem_extended_slice_requires_matching_length (parameterized over all three backends): bv = BitVector('00000000'); with pytest.raises(ValueError): bv[1:8:2] = BitVector(''); assert bv.to01() == '00000000'. Also: with pytest.raises(ValueError): bv[::2] = ''; empty-span no-op bv[2:2:2] = BitVector('') leaves bv unchanged; negative-step full assignment bv2 = BitVector('1101'); bv2[::-1] = '0011'; assert bv2.to01() == '1100'. Add the empty-value extended-slice case to the differential fuzz value pool (setitem_slice already generates step 2/-1 with length-0 values, so the fuzz covers it once both sides raise).

**Risks / sync obligations / review notes.** Anyone relying on the bytearray delete quirk breaks loudly (ValueError) — no known caller does, and the ACTIVE backend already raised. The pre-check adds one len(range(...)) per extended-slice write (rare path). Keep the two comments in sync ('bytearray handles resizing for unit-step slices'). Re-run the differential fuzz and parity suites (done: green).

> ⚖️ **Decision needed:** Extended-slice-with-empty-value policy: adopt list/bitarray semantics (raise ValueError) everywhere, rather than replicating bytearray's silent delete in the bitarray backend. Confirm raising is the intended semantics (it matches the docstring and the active backend).

<sub>covers: `bug|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|908-929`, `inconsistency|bytemaker/bitvector/bitvector_speedup.py|1057-1070`</sub>

---

## 5. Add bytearray/memoryview to the runtime BitsConstructible unions to match bitvector.pyi

**Priority:** soon · [`bytemaker/bitvector/bitvector_speedup.py:bitvector_speedup.py 1850-1859; bitvector_native.py 1737-1746; bitvector_with_bitarray_speedup.py 90-94 (__annotations__ hack) and 1748-1759`](../../bytemaker/bitvector/bitvector_speedup.py#L1850) · **✓ verified on a patched copy**

**Problem.** bitvector.pyi (the guaranteed spec) declares BitsConstructible = Union[BitVector, bytes, bytearray, memoryview, str, Iterable[...], BitsCastable], but the runtime unions in all three implementation modules still omit bytearray and memoryview; the runtime object is load-bearing (is_instance_of_union in __contains__ and startswith/endswith iterable dispatch), and the trailing prose docstrings also omit the types.

**Fix.** Add bytearray and memoryview to the runtime union in all three modules (keeping the bitarray backend's extra bitarray arm) and mention byte-likes in the prose docstring. Also update the bitarray module's __annotations__ forward-declaration string at the top of the file, which encodes the same union (and incidentally fix its misplaced bracket). Behavior is nearly unchanged today because bytearray/memoryview happen to satisfy the Iterable arm through is_instance_of_union's recursive fallback, but the declared contract and the runtime object should agree, and the explicit arms are robust if the Iterable arm's handling ever changes.

**Before:**

```python
# bitvector_speedup.py 1850 and bitvector_native.py 1737 (identical):
BitsConstructible = Union[BitVector, bytes, str, Iterable[LaxLiteral01], BitsCastable]
"""
The types that can be used to construct a BitVector.
These include the BitVector class itself, bytes, str, iterables of 0s and 1s,
and objects that can be cast to a BitVector.

# bitvector_with_bitarray_speedup.py 1748-1754:
BitsConstructible = Union[
    BitVector, bytes, str, Iterable[LaxLiteral01], BitsCastable, bitarray
]
"""
The types that can be used to construct a BitVector.
These include the BitVector class itself, bytes, str, iterables of 0s and 1s,
objects that can be cast to a BitVector, and bitarrays.

# bitvector_with_bitarray_speedup.py 90-94:
__annotations__ = {
    "BitsConstructible": 'Union["BitVector", bytes, str, Iterable[LaxLiteral01]]'
    ", BitsCastable, bitarray.bitarray]"
}  # Warning! Long-term support for bitarray is not guaranteed
```

**After:**

```python
# bitvector_speedup.py and bitvector_native.py:
BitsConstructible = Union[
    BitVector, bytes, bytearray, memoryview, str, Iterable[LaxLiteral01], BitsCastable
]
"""
The types that can be used to construct a BitVector.
These include the BitVector class itself, byte-like objects (bytes,
bytearray, memoryview), str, iterables of 0s and 1s,
and objects that can be cast to a BitVector.

# bitvector_with_bitarray_speedup.py:
BitsConstructible = Union[
    BitVector,
    bytes,
    bytearray,
    memoryview,
    str,
    Iterable[LaxLiteral01],
    BitsCastable,
    bitarray,
]
"""
The types that can be used to construct a BitVector.
These include the BitVector class itself, byte-like objects (bytes,
bytearray, memoryview), str, iterables of 0s and 1s,
objects that can be cast to a BitVector, and bitarrays.

# bitvector_with_bitarray_speedup.py top-of-module:
__annotations__ = {
    "BitsConstructible": 'Union["BitVector", bytes, bytearray, memoryview, str,'
    " Iterable[LaxLiteral01], BitsCastable, bitarray.bitarray]"
}  # Warning! Long-term support for bitarray is not guaranteed
```

**Behavior change.** Declarative sync; observable runtime behavior unchanged (verified: 'bytearray([0xDE]) in v' and 'memoryview(bytes([0xDE])) in v' return True on all three backends both before and after, because the Iterable arm caught byte-likes via is_instance_of_union's fallback). AFTER, the printed unions now contain bytearray and memoryview arms on all three modules, matching bitvector.pyi lines 62-70.

**Tests to add.** Contract test parameterized over the three modules: from typing import get_args; assert {bytes, bytearray, memoryview, str} <= {a for a in get_args(mod.BitsConstructible) if isinstance(a, type)}. Behavior pin (all backends): v = BitVector(bytes([0xde, 0xad])); assert bytearray([0xde]) in v; assert memoryview(bytes([0xde])) in v; assert bytearray([0x01]) not in v.

**Risks / sync obligations / review notes.** None foreseen at runtime (union only widens). Keep the three runtime unions, the __annotations__ string, and bitvector.pyi in lockstep for any future edits. Interacts with solution 2: together they make byte-likes uniform across constructor, __contains__, and startswith/endswith.

<sub>covers: `inconsistency|bytemaker/bitvector/bitvector_speedup.py|1850`</sub>

---

## 6. Restrict bitarray-backend __eq__/__ne__ to BitVector operands, matching the other backends

**Priority:** **now** · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:bitvector_with_bitarray_speedup.py 633-645`](../../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L633) · **✓ verified on a patched copy**

**Problem.** On the default backend, BitVector('0b101') == bitarray('101') is True (raw C-level comparison), while native and speedup return False — contradicting the shared docstring ('only really true if both objects are BitVectors') and making ==/set/dict behavior depend on which backend loaded.

**Fix.** Guard __eq__: non-BitVector bitarray operands compare unequal (return False, in BOTH operand orders — Python's subclass-priority rule routes 'plain_bitarray == bitvector' through this method first); all other non-BitVector types return NotImplemented so third-party types keep their reflected-op say, exactly like native/speedup. Returning NotImplemented for plain bitarrays would NOT work here: the fallback would re-enter bitarray.__eq__ which happily compares a subclass instance, yielding True again — hence the explicit False for that one case. Rewrite __ne__ in terms of __eq__ (the native/speedup pattern) instead of delegating to bitarray.__ne__. Also fixes the 'will only really true' docstring typo.

**Before:**

```python
    def __eq__(self, other: object) -> bool:
        """
        Returns whether this BitVector's bits are equal to another object's bits.
        This will only really true if both objects are BitVectors.
        """
        return super().__eq__(other)

    def __ne__(self, other: object) -> bool:
        """
        Returns whether this BitVector's bits are not equal to another object's bits.
        This will only really be false if both objects are BitVectors.
        """
        return super().__ne__(other)
```

**After:**

```python
    def __eq__(self, other: object) -> bool:
        """
        Returns whether this BitVector's bits are equal to another object's bits.
        This will only really be true if both objects are BitVectors.
        """
        if not isinstance(other, BitVector):
            if isinstance(other, bitarray):
                # A plain bitarray would compare bit-equal through the
                # C-level fallback; the documented contract (and the other
                # backends) reserve equality for BitVectors.
                return False
            return NotImplemented
        return super().__eq__(other)

    def __ne__(self, other: object) -> bool:
        """
        Returns whether this BitVector's bits are not equal to another object's bits.
        This will only really be false if both objects are BitVectors.
        """
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result
```

**Behavior change.** Actual outputs, v = BitVector('0b101'), ba = bitarray('101'):
BEFORE: native v==ba False, ba==v False | speedup False, False | bitarray backend v==ba True, ba==v True, v!=ba False
AFTER: all three backends: v==ba False, ba==v False, v!=ba True; v == BitVector('0b101') True; v == 5 False (unchanged).
Full test suite incl. bittypes/structs/differential: 857 passed.

**Tests to add.** Parameterized over all three backends (bitarray import-guarded): v = BitVector('0b101'); ba = bitarray('101'); assert (v == ba) is False; assert (ba == v) is False; assert v != ba; assert ba != v; assert v == BitVector('0b101'); assert v != BitVector('0b100'); assert (v == '101') is False (str is not a BitVector); FixedLengthBitVector('0b101') == BitVector('0b101') is True (subclass symmetry).

**Risks / sync obligations / review notes.** Any code that relied on cross-type BitVector==bitarray equality breaks silently (now False) — the demo __main__ block in this file is the only in-repo place mixing the two, and it does not compare them. Ordered comparisons (<, <=, ...) still accept plain bitarrays on this backend (they diverge from native/speedup differently and are out of this finding's scope). FixedLengthBitVector inherits the guard via isinstance(other, BitVector). Re-run parity + bittypes suites (done: green).

<sub>covers: `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|633-638`</sub>

---

## 7. Make to_bytes() whole-vector right-aligned (integer bytes), documented against left-aligned tobytes()

**Priority:** **now** · [`bytemaker/bitvector/bitvector_native.py:bitvector_native.py 1722-1734; bitvector_speedup.py 1837-1847; bitvector_with_bitarray_speedup.py 1733-1745 (__bytes__/tobytes at 978-984 / native 1031-1055 / speedup 1149-1165 unchanged, contrast documented in to_bytes docstring)`](../../bytemaker/bitvector/bitvector_native.py#L1722) · **✓ verified on a patched copy**

**Problem.** bytes(bv)/tobytes() LEFT-aligns a trailing partial byte (0b101 -> 0xA0) while to_bytes() right-aligns it PER BYTE (0b101 -> 0x05) — and the per-byte scheme is incoherent for multi-byte partial widths: BitVector('0b0100000011') (10 bits, value 259) gives to_bytes() b'@\x03' and therefore to_int(signed=False) == 16387 instead of 259. Same on all three backends: one object, three different byte renderings.

**Fix.** Give to_bytes() one coherent meaning: the bits form a big-endian integer, zero-padded on the LEFT to whole bytes (equivalent to int(bits,2).to_bytes(ceil(n/8),'big')). NOT the finding's left-align suggestion: to_int() round-trips through to_bytes() and the pinned test_to_int cases (BitVector('101').to_int(signed=False) == 5) require right alignment for sub-byte vectors; left-aligning would break them and make to_bytes redundant with tobytes. Whole-vector right alignment keeps every byte-aligned and sub-byte result identical, FIXES to_int for multi-byte non-multiple-of-8 widths (a latent wrong-value bug), and reduces the two APIs to two documented conventions: tobytes/bytes() = bit-stream (pad right), to_bytes = integer (pad left). Each implementation gets a docstring stating the contrast, using its natural mechanism (native: accumulate over _bits; speedup: _as_int(); bitarray: accumulate over self). Also replaces native/bitarray's 'bytes(reversed(byte_arr))' with the explicit byte_arr.reverse() used by speedup.

**Before:**

```python
# bitvector_native.py 1722-1734 and bitvector_with_bitarray_speedup.py 1733-1745
# (identical except native iterates self._bits via self[...]):
    def to_bytes(self, reverse_endianness=False) -> bytes:
        byte_arr = bytearray()
        for i in range(0, len(self), 8):
            byte = 0
            byte_end_index = min(i + 8, len(self))

            for bit in self[i:byte_end_index]:
                byte = (byte << 1) | bit
            byte_arr.append(byte)

        if reverse_endianness:
            byte_arr = reversed(byte_arr)
        return bytes(byte_arr)

# bitvector_speedup.py 1837-1847:
    def to_bytes(self, reverse_endianness=False) -> bytes:
        full_bytes, tail = divmod(self._len, 8)
        byte_arr = bytearray(self._buf[:full_bytes])
        if tail:
            # A trailing partial byte is right-aligned within its byte,
            # matching the historical accumulate-without-final-shift behavior.
            byte_arr.append(self._buf[full_bytes] >> (8 - tail))

        if reverse_endianness:
            byte_arr.reverse()
        return bytes(byte_arr)
```

**After:**

```python
# bitvector_native.py:
    def to_bytes(self, reverse_endianness=False) -> bytes:
        """
        Converts the BitVector to bytes, RIGHT-aligned: the bits form a
        big-endian integer, zero-padded on the left to a whole number of
        bytes. Contrast tobytes()/bytes(), which LEFT-align (zero-pad on
        the right) a trailing partial byte.
        """
        value = 0
        for bit in self._bits:
            value = (value << 1) | bit
        byte_arr = bytearray(value.to_bytes((len(self._bits) + 7) // 8, "big"))

        if reverse_endianness:
            byte_arr.reverse()
        return bytes(byte_arr)

# bitvector_speedup.py:
    def to_bytes(self, reverse_endianness=False) -> bytes:
        """
        Converts the BitVector to bytes, RIGHT-aligned: the bits form a
        big-endian integer, zero-padded on the left to a whole number of
        bytes. Contrast tobytes()/bytes(), which LEFT-align (zero-pad on
        the right) a trailing partial byte.
        """
        nbytes = (self._len + 7) >> 3
        byte_arr = bytearray(self._as_int().to_bytes(nbytes, "big"))

        if reverse_endianness:
            byte_arr.reverse()
        return bytes(byte_arr)

# bitvector_with_bitarray_speedup.py:
    def to_bytes(self, reverse_endianness=False) -> bytes:
        """
        Converts the BitVector to bytes, RIGHT-aligned: the bits form a
        big-endian integer, zero-padded on the left to a whole number of
        bytes. Contrast tobytes()/bytes(), which LEFT-align (zero-pad on
        the right) a trailing partial byte.
        """
        value = 0
        for bit in self:
            value = (value << 1) | bit
        byte_arr = bytearray(value.to_bytes((len(self) + 7) // 8, "big"))

        if reverse_endianness:
            byte_arr.reverse()
        return bytes(byte_arr)
```

**Behavior change.** Actual outputs (identical across all three backends before AND after):
  '0b101':        bytes b'\xa0', to_bytes BEFORE b'\x05' -> AFTER b'\x05' (unchanged)
  '0b00001111':   both b'\x0f' before and after (byte-aligned unchanged)
  '0b100000011':  to_bytes BEFORE b'\x81\x01' -> AFTER b'\x01\x03' (= 259, the vector's value)
  '0b0100000011': to_bytes BEFORE b'@\x03' -> AFTER b'\x01\x03'
  to_int('0b0100000011', signed=False): BEFORE 16387 -> AFTER 259 (latent bug fixed)
  to_int 9-bit MSB=1 signed: -253 before and after (lpad path, unchanged); unsigned BEFORE 33025 -> AFTER 259
  Pinned cases unchanged: to_int '0101'=5, '101' signed=-3, '101' unsigned=5, 16-bit little=1; to_bytes(reverse_endianness=True) on byte-aligned input unchanged.
Full suite: 857 passed (incl. differential to_bytes parity at bitvector_differential_test.py:507).

**Tests to add.** Parameterized over all three backends: assert BitVector('0b101').to_bytes() == b'\x05'; assert bytes(BitVector('0b101')) == b'\xa0'; assert BitVector('0b100000011').to_bytes() == b'\x01\x03'; assert BitVector('0b0100000011').to_int(signed=False) == 259; assert BitVector('0b0100000011').to_int() == 259; assert BitVector().to_bytes() == b''; round-trip: int.from_bytes(v.to_bytes(), 'big') == v.to_int(signed=False) for widths 1..17. Consider a .pyi comment on to_bytes noting the right-aligned convention.

**Risks / sync obligations / review notes.** Any caller serializing NON-byte-aligned vectors longer than 8 bits via to_bytes sees different bytes (that output was meaningless under the old per-byte scheme). In-repo callers — conversions/ctypes_.py:175, conversions/pytypes.py (str/bytes/float from_bits), to_int in all three impls — all operate on byte-aligned vectors or benefit from the fix. to_bytes/from_bytes are marked transitional ('TODO remove these methods' in the .pyi), further reducing exposure. The three implementations plus the differential test's to_bytes comparison must move together. Re-run pytypes/ctypes/structs suites (done: green).

> ⚖️ **Decision needed:** to_bytes partial-byte policy: whole-vector RIGHT alignment (integer semantics, chosen here because to_int and its pinned tests depend on it and it fixes to_int for multi-byte partial widths) versus the finding's alternative of left-aligning to match tobytes (which would break BitVector('101').to_int(signed=False)==5 and require a to_int rewrite). Confirm the right-aligned choice.

<sub>covers: `inconsistency|bytemaker/bitvector/bitvector_with_bitarray_speedup.py|978-984, 1733-1745`</sub>

---

## 8. Give pop() Python-style negative indexing and honest out-of-range errors on all three backends

**Priority:** soon · [`bytemaker/bitvector/bitvector_native.py:bitvector_native.py 1134-1163; bitvector_speedup.py 1248-1287; bitvector_with_bitarray_speedup.py 1063-1090; test/bitvector_implementations_test.py 483-490 (pinned quirk test must change)`](../../bytemaker/bitvector/bitvector_native.py#L1134) · **✓ verified on a patched copy**

**Problem.** Two pop() defects with one root: (1) any out-of-range or negative index raises IndexError('pop from empty BitVector') — a false statement for a 4-bit vector ('pop from empty bitarray' on the default backend, inconsistent wording to boot); (2) pop alone treats negative indices as out of bounds while __getitem__/__setitem__/__delitem__/insert all normalize them, so pop(-1, default) silently returns the sentinel instead of the last bit.

**Fix.** Rewrite the shared prologue identically in all three implementations: normalize index=None to len-1; remember the raw index for the error message; normalize negatives Python-style (index += len); bounds-check once; on out-of-bounds return the default if provided, else raise 'pop from empty BitVector' only when actually empty and otherwise 'pop index {raw} out of range for BitVector of length {n}'. Each implementation's removal mechanics after the prologue are untouched (native: del _bits[index]; speedup: tail fast path — which the normalization feeds correctly since a normalized -1 IS _len-1; bitarray: super().pop(index)). Docstrings updated: drop 'negative indices are treated as out of bounds', add 'Negative indices count from the end, as with __getitem__'. The parity test pinning the quirk is updated (pop(-2) on a 1-bit vector still raises; new test asserts pop(-1) pops the last bit).

**Before:**

```python
# bitvector_speedup.py 1253-1255 (docstring; the quirk is documented):
        If a default is provided and the index is out of bounds,
        the default is returned; negative indices are treated as
        out of bounds.
# bitvector_speedup.py 1269-1274 (bitvector_native.py 1155-1160 shares this shape):
        if index is None:
            index = len(self) - 1
        if index >= len(self) or index < 0:
            if default is not None:
                return default
            raise IndexError("pop from empty BitVector")
# bitvector_with_bitarray_speedup.py 1084-1090 (note the different wording):
        if index is None:
            index = len(self) - 1
        if index >= len(self) or index < 0:
            if default is not None:
                return default
            raise IndexError("pop from empty bitarray")
        return super().pop(index)
```

**After:**

```python
# Shared prologue, identical in all three implementations (docstring line
# becomes: "Negative indices count from the end, as with __getitem__.\n
# If a default is provided and the index is out of bounds,\n
# the default is returned."):
        if index is None:
            index = len(self) - 1
        raw_index = index
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            if default is not None:
                return default
            if len(self) == 0:
                raise IndexError("pop from empty BitVector")
            raise IndexError(
                f"pop index {raw_index} out of range for"
                f" BitVector of length {len(self)}"
            )
# ...then each backend's existing removal mechanics, unchanged:
#   native:   value = self._bits[index]; del self._bits[index]; return value
#   speedup:  value = self[index]; <tail fast path / del self[index]>; return value
#   bitarray: return super().pop(index)

# --- bytemaker/structs.py (BoundBits.pop, lines 1180-1186) ---
# The comment codifying the old contract becomes false once negatives are
# Python-style; replace lines 1181-1182 with:
    def pop(self, index=None, default=None):
        # Mirrors the BitVector contract (None = last bit; negative
        # indices count from the end, as in list.pop).
        b = self._cur()
        value = b.pop(index, default)
        self._write(b)
        return value
```

**Behavior change.** Actual outputs on BitVector('0b1010') (all three backends identical after; before, bitarray said 'bitarray' where others said 'BitVector'):
BEFORE: pop(99) -> IndexError('pop from empty BitVector') [false: len 4]; pop(-1) -> IndexError('pop from empty BitVector'); pop(-1, 9) -> 9 [silent sentinel]; pop(-4) -> IndexError
AFTER: pop(99) -> IndexError('pop index 99 out of range for BitVector of length 4'); pop(-1) -> 0 (last bit popped); pop(-1, 9) -> 0; pop(-4) -> 1 (first bit); pop(-5) -> IndexError('pop index -5 out of range for BitVector of length 4'); pop() on empty -> IndexError('pop from empty BitVector') (unchanged)
Parity suite updated accordingly; full suite 857 passed.

**Tests to add.** Update test_pop_out_of_bounds_without_default: keep BitVector().pop() and BitVector('1').pop(5) raising IndexError; replace the pop(-1) quirk pin with BitVector('1').pop(-2). Add test_pop_negative_index_counts_from_end (parameterized over all backends): assert BitVector('10').pop(-1) == 0; assert BitVector('10').pop(-2) == 1; assert BitVector('10').pop(-1, 9) == 0 (in-bounds negatives never return the default). Optionally pin messages: pytest.raises(IndexError, match='pop index 99 out of range'); pytest.raises(IndexError, match='pop from empty BitVector').

**Risks / sync obligations / review notes.** CONTRACT CHANGE: pop(-1) previously raised/returned the default by documented design ('specified quirk' in the parity test); any caller using pop(-1, sentinel) as an 'is empty?' probe changes meaning — none exist in-repo (sole in-repo pop() callers are the tests and the fuzz harness, whose native/speedup lockstep stays consistent). FixedLengthBitVector.pop overrides with a length violation and is unaffected. Files to sync: all three impls + test/bitvector_implementations_test.py; bitvector.pyi signatures are unchanged (overloads already permit this). Re-run parity + differential suites (done: green). REVISION (adversarial review): the original claim that no in-repo code calls pop() was wrong — bytemaker/structs.py:1180-1186 (BoundBits.pop) delegates to BitVector.pop and its comment codifies the old "negatives are out of bounds" contract. Behavior there is empirically unaffected (FixedLengthBitVector.pop raises unconditionally on width-locked bits), but the comment must be updated as part of this change set — included in "after" above.

> ⚖️ **Decision needed:** pop(-1) semantics: switch from the documented 'negative indices are out of bounds' quirk to Python-standard from-the-end indexing (list.pop parity). This edits a pinned parity test — confirm the quirk was not load-bearing for anything outside the repo.

<sub>covers: `ux|bytemaker/bitvector/bitvector_speedup.py|1269-1274`, `ux|bytemaker/bitvector/bitvector_speedup.py|1248-1274`</sub>

---
