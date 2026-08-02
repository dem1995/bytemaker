# Solutions — Buffer bittype (bittypes/buffer.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Three findings, two underlying issues, both in bytemaker/bittypes/buffer.py. The two docstring findings (orphaned duplicate literal at lines 40-45, and the twice-repeated 'use one of the pre-defined subclasses' pointing at a deleted Buffer1..Buffer1024 zoo) are one coherent docstring rewrite (buffer-1): delete the dead literal and point users at the two real entry points, Buffer.of(nbytes=N) and Buffer.specialize(num_bits). The behavioral issue (buffer-2) is that Buffer.value returns the live width-locked bits handle, so mutating a value you read back silently rewrites the box — unlike every other BitType, whose .value is a safe plain-value read; the fix returns a resizable BitVector snapshot, aligning Buffer with the library's own 'value plane = plain value, bits plane = live handle' split (structs.py's one-decoded-scalar rule, and BitType.bits's own 'take BitVector(bits) for a snapshot' advice). Apply buffer-2 first (or together): buffer-1's rewritten Instance Attributes block documents the new snapshot semantics, so it assumes buffer-2 is accepted; if buffer-2 is rejected, keep the 'Identical to bits' wording but add an explicit mutation-hazard warning instead. Both were verified together on a patched copy: the repro flips as expected and the full test suite passes 854/854 before and after. No sync obligations: _legacy_aggregate.py has no Buffer or .value references, and the three BitVector backends are untouched (the fix lives in bittypes, and BitVector(self.bits) copy-construction is already exercised backend-independently via the BitsCastable protocol).

_2 solutions — 1 apply-now, 2 empirically verified on a patched copy._

---

## 1. Rewrite the Buffer class docstring: delete the orphaned duplicate literal and point at of()/specialize() instead of nonexistent pre-defined subclasses

**Priority:** soon · [`bytemaker/bittypes/buffer.py:17-45`](../../bytemaker/bittypes/buffer.py#L17) · **✓ verified on a patched copy**

**Problem.** The Buffer class docstring twice tells users to 'use one of the pre-defined subclasses' that no longer exist (only Buffer is exported; the of() docstring itself records that the BufferN zoo was removed), sending readers hunting for Buffer8/Buffer16. Immediately after the real docstring, an unassigned copy-paste duplicate of its first two paragraphs sits dead in the class body (lines 40-45), repeating the same stale advice.

**Fix.** One edit replaces the whole block. Delete the orphaned bare string literal entirely. In the real docstring, replace the stale 'or use one of the pre-defined subclasses' guidance with the two actual entry points — Buffer.of(nbytes=N) for byte-sized buffers (the Struct-field door, echoing of()'s own docstring language) and Buffer.specialize(num_bits) for bit-counted ones. Also update the Instance Attributes lines for bits/value: the old text framed the mutation aliasing ('Identical to value'/'Identical to bits') as a feature; the new text states that bits is the live width-locked handle and value is an independent snapshot — matching solution buffer-2. Keeps the file's existing section-header docstring style (Class Attributes / Instance Attributes with 'name : type' entries).

**Before:**

```python
    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.

    Class Attributes:
    -----------------
    num_bits : int
        The number of bits in instances of this `Buffer` subclass.
    base_bit_type : Type[Buffer]
        The base `BitType` this class derives from. It will be `Buffer`.
    py_type : Type[BitVector]
        The type that this `BitType` represents. It is `BitVector`.

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this `Buffer` object. Identical to `value`.
    value : BitVector
       The `BitVector` value of this `Buffer` object. Identical to `bits`.
    """

    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.
    """
```

**After:**

```python
    """
    A BitType that represents a buffer of bits.

    Use the `of` classmethod to create a subclass sized in bytes
        (the Struct-field door) or the `specialize` classmethod
        to create one with an exact number of bits.

    Class Attributes:
    -----------------
    num_bits : int
        The number of bits in instances of this `Buffer` subclass.
    base_bit_type : Type[Buffer]
        The base `BitType` this class derives from. It will be `Buffer`.
    py_type : Type[BitVector]
        The type that this `BitType` represents. It is `BitVector`.

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this `Buffer` object.
           The handout is live and width-locked (see `BitType.bits`).
    value : BitVector
       An independent, resizable snapshot of this `Buffer` object's bits.
           Equal to `bits` by value; mutating it does not affect the buffer.
    """
```

**Behavior change.** Doc/dead-code only; no runtime behavior change beyond the docstring text. Verified on the patched copy: "'pre-defined subclasses' in Buffer.__doc__" flips True -> False, and inspect.getsource(Buffer).count('A BitType that represents a buffer of bits.') drops 2 -> 1 (the orphan literal is gone). Full test suite: 854 passed before, 854 passed after.

**Tests to add.** Add to test/bittypes_test.py: (1) assert 'pre-defined subclasses' not in Buffer.__doc__; (2) assert 'of' in Buffer.__doc__ and 'specialize' in Buffer.__doc__ (the docstring names the real entry points); (3) optionally, a source-hygiene check that inspect.getsource(Buffer).count('A BitType that represents a buffer of bits.') == 1 so the orphan cannot silently return.

**Risks / sync obligations / review notes.** None functionally — the deleted literal was an inert expression statement and Python only binds the first string as __doc__. The one coupling: the rewritten Instance Attributes text describes value as an independent snapshot, which is only true once buffer-2 is applied. Apply buffer-2 first or in the same commit; if buffer-2 is rejected, keep 'Identical to bits' but append an explicit warning that mutating the returned vector rewrites the buffer. No _legacy_aggregate.py or BitVector-backend sync needed.

<sub>covers: `docstring|bytemaker/bittypes/buffer.py|40-45`, `ux|bytemaker/bittypes/buffer.py|20-21, 43-44`</sub>

---

## 2. Make Buffer.value return an independent BitVector snapshot instead of the live width-locked bits handle

**Priority:** **now** · [`bytemaker/bittypes/buffer.py:49-51`](../../bytemaker/bittypes/buffer.py#L49) · **✓ verified on a patched copy**

**Problem.** Buffer.value returns self.bits — the live, width-locked handle — so 'v = buf.value; v[0] = 1' silently mutates the buffer in place, and v.append(...) raises a surprising width-lock ValueError. Every other BitType's .value is a safe plain-value read (int/float/str), so this is a silent-wrong footgun unique to Buffer.

**Fix.** Return BitVector(self.bits) from the getter: a fresh, resizable, independent snapshot. This is exactly the escape hatch BitType.bits's own docstring prescribes ('Take BitVector(bits) for a resizable snapshot') and restores the library-wide two-plane contract: .value is the plain decoded value (structs.py's one-decoded-scalar rule), .bits is the deliberate live handle. Callers who want in-place bit surgery keep .bits; callers who read .value can no longer corrupt the box by accident. A getter docstring states the policy explicitly. The setter is untouched (it already snapshots via the bits setter). Constructor, __eq__, __str__, __format__, and copy-construction from a box all work unchanged on the copy — BitType.__init__ already copy-constructs py_type(source.value), and equality is by value.

**Before:**

```python
    @property
    def value(self):
        return self.bits
```

**After:**

```python
    @property
    def value(self):
        """
        The `BitVector` value of this `Buffer`.

        The getter hands out an independent, resizable snapshot — the safe
        read every other BitType's `value` provides. Mutating the returned
        vector does not touch this buffer; use the `bits` property for the
        live, width-locked handle.

        Returns:
            BitVector: A copy of this buffer's bits.
        """
        return BitVector(self.bits)
```

**Behavior change.** Repro (Buffer.specialize(8) instance of all zeros; script run once with PYTHONPATH at the pristine repo, once at the patched copy).
BEFORE (pristine repo):
  inst.value is inst.bits: True
  inst.value == inst.bits: True
  bits after mutating the read value: 10000000   <- silent corruption
  append on read value raised ValueError: length is invariant (8 bits): width-changing mutation is not allowed on a FixedLengthBitVector; make a resizable copy with BitVector(...) first
  fresh value == bits: True
AFTER (patched copy):
  inst.value is inst.bits: False
  inst.value == inst.bits: True
  bits after mutating the read value: 00000000   <- box untouched
  append on read value: ok, len(v) = 9 ; len(inst.bits) = 8
  fresh value == bits: True
Full test suite on the patched copy: 854 passed (identical to the pristine baseline, 854 passed).

**Tests to add.** Add to test/bittypes_test.py (mirroring test_bittype_Bits_cast_protocol's structure): (1) B8 = Buffer.specialize(8); b = B8(BitVector([0]*8)); v = b.value; assert v == b.bits and v is not b.bits; (2) v[0] = 1; assert b.bits.to01() == '00000000' (read is a snapshot); (3) v.append(1); assert len(v) == 9 and len(b.bits) == 8 (snapshot is resizable); (4) b.bits[0] = 1; assert b.value.to01() == '10000000' (live-plane writes still show up in fresh value reads); (5) assert B8(b).bits == b.bits and B8(b).bits is not b.bits (copy-construction from a box unaffected).

**Risks / sync obligations / review notes.** Any caller relying on .value being a live write-through alias breaks — repo-wide grep found none: Struct Buffer fields hold plain bytes (_BytesField), Array decodes Buffer elements to plain bytes, tests only compare Buffer.value by equality, and _legacy_aggregate.py never touches Buffer or .value, so no oracle sync and no parity-test updates are needed. The fix is in bittypes, not the three BitVector implementations, so no backend sync either (BitVector copy-construction from a FixedLengthBitVector is already covered by the __Bits__ protocol test). Cost: one O(num_bits) copy per value read — irrelevant at this library's scale, and the live .bits plane remains for zero-copy access. Re-run: full pytest suite (done, 854/854) plus the new tests above. Apply before or together with buffer-1, whose docstring describes these snapshot semantics.

> ⚖️ **Decision needed:** Confirm the value-plane policy: Buffer.value now returns a resizable BitVector snapshot (chosen — matches every other BitType's safe .value read and the documented 'BitVector(bits) for a snapshot' idiom), rather than keeping the live alias and merely documenting the hazard. If you prefer the returned snapshot to stay width-locked (FixedLengthBitVector copy) instead of resizable, say so — resizable was chosen because py_type is plain BitVector and the .bits docstring calls BitVector(bits) 'a resizable snapshot'.

<sub>covers: `ux|bytemaker/bittypes/buffer.py|49-51`</sub>

---
