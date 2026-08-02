# Solutions — ctypes conversions (conversions/ctypes_.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; 1 flag(s) found and resolved by revision. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

All three findings live in bytemaker/conversions/ctypes_.py and are resolved by one coherent single-file patch, empirically verified on a patched copy (854/854 tests pass, plus a 10-shape repro). The core fix (ctypes-1) replaces the mutating reverse_ctype_endianness with a pure byte-level recursion: a private helper _reversed_ctype_bytes(ctype_type, raw, path) computes the reversed serialization from bytes(obj) without ever touching a ctypes instance, so the caller's object is provably untouched, and it is correct for shapes the old code crashed on or silently skipped (nested Structures, Structures with Array fields, Arrays of multi-byte scalars). The bitfield guard (ctypes-2) is designed into that same recursion: every _fields_ entry of every Structure reached (including nested ones, via the recursion) is length-checked before unpacking, and the NotImplementedError names the offending field by dotted path (e.g. 'bf.a'). The message fix (ctypes-3) corrects the two remaining run-together TypeError strings; the third garbled message (the old NotImplementedError) is replaced wholesale by ctypes-2's new message. Apply as one edit to ctypes_.py: ctypes-1 first (it rewrites lines 14-71 and the two reversal call sites, deleting reverse_bytes_unit), ctypes-2 is contained inside ctypes-1's new Structure branch, ctypes-3 touches only the two TypeError literals. No oracle sync edit is needed: bytemaker/_legacy_aggregate.py imports ctype_to_bytes/bytes_to_ctype/ctype_to_bits/bits_to_ctype from this module, so the frozen-oracle path and the public aggregate path pick up the fix from the same shared functions simultaneously; re-run the aggregate parity/differential tests to confirm (done: full suite green against the patched copy).

_3 solutions — 3 apply-now, 3 empirically verified on a patched copy._

---

## 1. Make ctypes endianness reversal pure: compute reversed bytes from a snapshot, never mutate the caller's object

**Priority:** **now** · [`bytemaker/conversions/ctypes_.py:14-71 (reverse_bytes_unit + reverse_ctype_endianness, replaced), 96-99 and 148-152 (reversal call sites)`](../../bytemaker/conversions/ctypes_.py#L14) · **✓ verified on a patched copy**

**Problem.** Serializing a ctypes Structure (or Array of Structures) with non-native endianness byte-swaps the caller's object in place and leaves it corrupted, including through the aggregate path (to_bytes_aggregate on a dataclass with a ctypes field). Worse, nested-Structure and Array-field structs crash with TypeError AFTER partially reversing the caller, and Arrays of multi-byte scalars are silently not reversed at all.

**Fix.** Replace the mutate-in-place recursion with a pure byte-level one. A new private helper _reversed_ctype_bytes(ctype_type, raw, path) maps native-order bytes to reversed bytes structurally: _SimpleCData -> raw[::-1]; Array -> per-element recursion on sizeof(elem) slices; Structure -> per-field recursion using each field descriptor's .offset and sizeof(field_type) over a bytearray copy (so padding bytes pass through); Union -> unchanged (active member unknowable; historical behavior, now documented). reverse_ctype_endianness becomes a thin non-mutating wrapper (bytes -> _reversed_ctype_bytes -> from_buffer_copy into a fresh instance), and ctype_to_bytes/bytes_to_ctype call the byte-level helper directly. Byte-level was chosen over a recursive instance copy because it is provably side-effect-free (never holds a mutable ctypes view of anything), handles padding and every nesting shape uniformly, and fixes the shapes the old value-based recursion could not represent: field_type(field_value) blew up on nested Structure/Array fields, and arr[i] on scalar arrays yields plain ints the old code silently skipped. reverse_bytes_unit (lines 14-27) is deleted; the old reverse_ctype_endianness was its only caller.

**Before:**

```python
    if isinstance(ctype_instance, _SimpleCData):
        # Reverse the byte order for single, multi-byte objects
        byte_size = ctypes.sizeof(ctype_instance)
        if byte_size > 1:
            ctype_instance = reverse_bytes_unit(ctype_instance)

    if isinstance(ctype_instance, Array):
        for i in range(len(ctype_instance)):
            ctype_instance[i] = reverse_ctype_endianness(ctype_instance[i])

    if isinstance(ctype_instance, Structure):
        ctype_instance_fields = list(ctype_instance._fields_)
        if len(ctype_instance_fields) > 0 and len(ctype_instance_fields[0]) > 2:
            raise NotImplementedError(
                "ctype structures with _fields_ with more than 2 elements are"
                "not supported."
                f"Ctype instance: {ctype_instance}"
                f"Ctype instance fields: {ctype_instance_fields}"
            )
        for field_name, field_type in ctype_instance_fields:  # type: ignore
            field_value = getattr(ctype_instance, field_name)
            # print(field_name, field_value, type(field_value))
            simple_c_data = field_type(field_value)  # type: ignore[reportCallIssue]
            assert isinstance(simple_c_data, _SimpleCData)
            reversed_unit = reverse_ctype_endianness(simple_c_data)
            setattr(ctype_instance, field_name, reversed_unit)

    return ctype_instance

...  # ctype_to_bytes, lines 96-99:

    if endianness != sys.byteorder:
        ctype_obj = reverse_ctype_endianness(ctype_obj)

    return bytes(ctype_obj)

...  # bytes_to_ctype, lines 148-152:

    ctype_obj = ctype_type.from_buffer_copy(bytes_obj)
    if endianness != sys.byteorder:
        ctype_obj = reverse_ctype_endianness(ctype_obj)

    return ctype_obj
```

**After:**

```python
def _reversed_ctype_bytes(ctype_type: type, raw: bytes, path: str) -> bytes:
    """
    Computes the byte-order-reversed serialization of a ctypes value from
    its native-order bytes, without touching any ctypes instance.

    Scalars are byte-reversed whole. Arrays are reversed element-by-element.
    Structures are reversed field-by-field (padding bytes pass through
    unchanged). Union bytes are returned unchanged, because which member is
    active is unknowable.

    Args:
        ctype_type (type): The ctypes type that describes ``raw``.
        raw (bytes): The native-order bytes of the value.
        path (str): Dotted path from the root object, used in error messages.

    Returns:
        bytes: The reversed-endianness bytes.

    Raises:
        NotImplementedError: If a Structure reached by the reversal declares
            bitfields (3-tuple ``_fields_`` entries).
    """
    if issubclass(ctype_type, _SimpleCData):
        return raw[::-1]

    if issubclass(ctype_type, Array):
        elem_type = ctype_type._type_
        elem_size = ctypes.sizeof(elem_type)
        if elem_size == 0:  # array of zero-sized elements: nothing to reverse
            return raw
        return b"".join(
            _reversed_ctype_bytes(
                elem_type,
                raw[offset : offset + elem_size],
                f"{path}[{offset // elem_size}]",
            )
            for offset in range(0, len(raw), elem_size)
        )

    if issubclass(ctype_type, Structure):
        out = bytearray(raw)  # padding bytes pass through unchanged
        for field in ctype_type._fields_:
            field_name, field_type = field[0], field[1]
            field_path = f"{path}.{field_name}" if path else field_name
            if len(field) > 2:
                raise NotImplementedError(
                    f"Cannot reverse the endianness of"
                    f" {ctype_type.__name__!r}: field {field_path!r}"
                    f" is a bitfield (3-tuple entry in _fields_), and"
                    f" ctypes bitfield storage cannot be reversed per-field."
                )
            offset = getattr(ctype_type, field_name).offset
            size = ctypes.sizeof(field_type)
            out[offset : offset + size] = _reversed_ctype_bytes(
                field_type, raw[offset : offset + size], field_path
            )
        return bytes(out)

    # ctypes.Union: no per-member reversal is possible without knowing the
    # active member; pass the bytes through unchanged (the historical
    # behavior of this module).
    return raw


def reverse_ctype_endianness(ctype_instance: CType) -> CType:
    """
    Returns a copy of a ctypes object with the endianness reversed.

    The input object is never modified: the reversal is computed on the
    object's serialized bytes and materialized into a fresh instance with
    ``from_buffer_copy``. Nested Structures, Arrays (including arrays of
    multi-byte scalars), and combinations thereof are reversed
    field-by-field / element-by-element; Union bytes pass through unchanged
    because the active member is unknowable.

    Args:
        ctype_instance (ctypes._SimpleCData | ctypes.Structure |
                ctypes.Union | ctypes.Array):
            The ctypes object to reverse the endianness of.

    Returns:
        ctypes._SimpleCData | ctypes.Structure | ctypes.Union | ctypes.Array:
            A new ctypes object of the same type with the endianness
            reversed.

    Raises:
        NotImplementedError: If a Structure reached by the reversal declares
            bitfields (3-tuple ``_fields_`` entries).
    """
    ctype_type = type(ctype_instance)
    reversed_raw = _reversed_ctype_bytes(ctype_type, bytes(ctype_instance), "")
    return ctype_type.from_buffer_copy(reversed_raw)

...  # ctype_to_bytes tail becomes:

    if endianness != sys.byteorder:
        return _reversed_ctype_bytes(type(ctype_obj), bytes(ctype_obj), "")

    return bytes(ctype_obj)

...  # bytes_to_ctype tail becomes:

    if endianness != sys.byteorder:
        bytes_obj = _reversed_ctype_bytes(ctype_type, bytes(bytes_obj), "")

    return ctype_type.from_buffer_copy(bytes_obj)
```

**Behavior change.** Verified on the patched copy (host byteorder: little). Caller mutation, BEFORE -> AFTER:
  [simple struct] Pt(0x0102, 0x0304); ctype_to_bytes(p,'big') returns 01020304 in both.
    BEFORE: after call x=0x0201 y=0x0403 raw=01020304, caller bit-identical: False (CORRUPTED)
    AFTER:  after call x=0x0102 y=0x0304 raw=02010403, caller bit-identical: True
  [aggregate] dataclass Record(pt=Pt(0x0102,0x0304)); to_bytes_aggregate(rec,'big') -> 01020304 in both.
    BEFORE: rec.pt after: x=0x0201 y=0x0403 bit-identical=False   AFTER: x=0x0102 y=0x0304 bit-identical=True
  [array of struct] (Pt*2)(...); returns 0102030405060708 in both.
    BEFORE: caller raw flipped to 0102030405060708 (bit-identical=False)   AFTER: bit-identical=True
Shapes the old code crashed on (and partially corrupted before crashing):
  [nested struct] Outer{a:c_uint16=0x0102, inner:Inner{b:c_uint32=0x0A0B0C0D}}, native raw 020100000d0c0b0a
    BEFORE: RAISED TypeError: incompatible types, Inner instance instead of c_ulong instance; caller left PARTIALLY REVERSED (raw=010200000d0c0b0a)
    AFTER:  returns 010200000a0b0c0d (field-wise big-endian, padding preserved); caller bit-identical=True
  [struct+array field] WithArr{n:c_uint16=0x1122, arr:(c_uint16*3)(0xAABB,0xCCDD,0xEEFF)}
    BEFORE: RAISED TypeError: incompatible types, c_ushort_Array_3 instance instead of c_ushort instance; caller partially reversed
    AFTER:  returns 1122aabbccddeeff; caller bit-identical=True
Shape the old code silently got wrong:
  [array of u16] (c_uint16*2)(0x0102,0x0304), ctype_to_bytes(arr,'big')
    BEFORE: 02010403 (native order returned unchanged -- silent no-op)   AFTER: 01020304
Unchanged-by-design:
  [union] U{i:c_uint32,h:c_uint16} with i=0x0A0B0C0D: 0d0c0b0a passthrough, caller untouched, in both.
  [little on little host] no reversal, caller untouched, in both.
  [bytes_to_ctype big] b'\x01\x02\x03\x04' -> Pt(x=0x0102, y=0x0304) in both; round-trip big->big preserved.
Full test suite against the patched copy: 854 passed (import path confirmed via module __file__).

**Tests to add.** In test/ctypes_test.py (use nonnative = 'big' if sys.byteorder == 'little' else 'little' so tests are host-independent):
1. Non-mutation: p = TestStructure(1, 2); snapshot = bytes(p); ctype_to_bytes(p, nonnative); assert bytes(p) == snapshot. Same assertion for a (TestStructure * 2) array and for a c_uint16 scalar.
2. Nested struct: Outer{a: c_uint16, inner: Inner{b: c_uint32}}; assert ctype_to_bytes(Outer(0x0102, Inner(0x0A0B0C0D)), 'big') == bytes.fromhex('010200000a0b0c0d') and the input is bit-identical afterwards.
3. Struct with array field: WithArr{n: c_uint16, arr: c_uint16*3}(0x1122, (0xAABB,0xCCDD,0xEEFF)); assert ctype_to_bytes(w, 'big') == bytes.fromhex('1122aabbccddeeff').
4. Array of multi-byte scalars: assert ctype_to_bytes((c_uint16*2)(0x0102, 0x0304), 'big') == b'\x01\x02\x03\x04' (was the silent no-op).
5. Round-trips: for each shape above, x2 = bytes_to_ctype(ctype_to_bytes(x, 'big'), type(x), 'big'); assert bytes(x2) == bytes(x).
6. Union passthrough: u = TestUnion(); u.field1 = 0x0A0B0C0D; assert ctype_to_bytes(u, nonnative) == bytes(u) and bytes(u) unchanged.
7. Aggregate non-mutation: @dataclass Record(pt: TestStructure); to_bytes_aggregate(rec, nonnative); assert bytes(rec.pt) unchanged (exercises the shared path used by both aggregate_types and the _legacy_aggregate oracle).

**Risks / sync obligations / review notes.** (1) reverse_ctype_endianness changes contract: it now returns a NEW object instead of mutating and returning the input. Its only in-repo callers were ctype_to_bytes/bytes_to_ctype, both updated in this patch; grep confirms no other callers. (2) reverse_bytes_unit is deleted; its only caller was the old reverse_ctype_endianness (grep: no other references outside findings/observations docs). (3) Deliberate output change: arrays of multi-byte scalars are now actually reversed (old code silently returned native-order bytes), and nested/array-field structs now serialize instead of raising TypeError after partially corrupting the input -- any downstream code that had baked in the old wrong bytes would notice; with one user this is the better design. (4) Oracle sync: bytemaker/_legacy_aggregate.py imports these functions from conversions/ctypes_.py rather than duplicating them, so the frozen-oracle and fast aggregate paths change together automatically; no edit to _legacy_aggregate.py is needed, but re-run the aggregate parity/differential tests (done: full suite 854 passed on the patched copy). (5) The three BitVector backends are untouched (this module only constructs BitVector from bytes). (6) Known pre-existing limitation kept: fields inherited from a base Structure subclass are not reversed (both old and new code walk only the most-derived class's _fields_); pointers inside structs remain nonsensical to reverse, as before. REVISION (adversarial review): arrays of zero-sized elements (e.g. (EmptyStruct * 3)()) crashed the element loop with range(0,0,0) ValueError where old code returned b""; guarded with an elem_size == 0 early return of raw (which is itself b"" for such arrays, preserving old behavior exactly).

> ⚖️ **Decision needed:** Union policy: reversal currently passes Union bytes through unchanged (the historical behavior, now documented). Since the active member is unknowable, a silent passthrough can produce wrong-endianness output without warning -- should Unions (and structs containing them) instead raise NotImplementedError when a byte-order swap is actually required (endianness != sys.byteorder)? Passthrough keeps the existing test-visible behavior; raising is stricter and more honest.

<sub>covers: `bug|bytemaker/conversions/ctypes_.py|63-69, 96-97`</sub>

---

## 2. Check every _fields_ entry (including nested structures') for bitfields and name the offending field in the error

**Priority:** **now** · [`bytemaker/conversions/ctypes_.py:55-63 (old guard + unpacking loop; replaced by the Structure branch of _reversed_ctype_bytes in ctypes-1)`](../../bytemaker/conversions/ctypes_.py#L55) · **✓ verified on a patched copy**

**Problem.** The bitfield guard only inspects _fields_[0], so a struct whose FIRST field is ordinary but a LATER field is a bitfield escapes the guard and dies with an uncaught 'ValueError: too many values to unpack (expected 2)'; a bitfield struct NESTED inside another struct dies with an unrelated TypeError. The intended contract (clean NotImplementedError for bitfield structs) only holds for first-field bitfields.

**Fix.** Designed into the ctypes-1 rewrite rather than as a pre-pass: the Structure branch of _reversed_ctype_bytes length-checks EVERY field tuple before unpacking it, and because the byte-reverser recurses into nested Structure fields and Array elements, nested bitfield structs are detected by the exact same check. The recursion threads a dotted `path` string, so the NotImplementedError names the owning type and the offending field by path (e.g. Cannot reverse the endianness of 'BitFirst': field 'bf.a' is a bitfield ...). Guard coverage is deliberately congruent with what the reversal actually processes: Unions are passed through, so bitfields inside Unions are not rejected (consistent with the union passthrough policy flagged in ctypes-1's decision). The message is properly spaced, fixing the old garbled NotImplementedError text as a side effect.

**Before:**

```python
    if isinstance(ctype_instance, Structure):
        ctype_instance_fields = list(ctype_instance._fields_)
        if len(ctype_instance_fields) > 0 and len(ctype_instance_fields[0]) > 2:
            raise NotImplementedError(
                "ctype structures with _fields_ with more than 2 elements are"
                "not supported."
                f"Ctype instance: {ctype_instance}"
                f"Ctype instance fields: {ctype_instance_fields}"
            )
        for field_name, field_type in ctype_instance_fields:  # type: ignore
```

**After:**

```python
# Contained in the ctypes-1 rewrite: the Structure branch of _reversed_ctype_bytes
# checks EVERY field tuple before unpacking, and the recursion carries a dotted
# path so nested bitfields are both detected and named:

    if issubclass(ctype_type, Structure):
        out = bytearray(raw)  # padding bytes pass through unchanged
        for field in ctype_type._fields_:
            field_name, field_type = field[0], field[1]
            field_path = f"{path}.{field_name}" if path else field_name
            if len(field) > 2:
                raise NotImplementedError(
                    f"Cannot reverse the endianness of"
                    f" {ctype_type.__name__!r}: field {field_path!r}"
                    f" is a bitfield (3-tuple entry in _fields_), and"
                    f" ctypes bitfield storage cannot be reversed per-field."
                )
            offset = getattr(ctype_type, field_name).offset
            size = ctypes.sizeof(field_type)
            out[offset : offset + size] = _reversed_ctype_bytes(
                field_type, raw[offset : offset + size], field_path
            )
        return bytes(out)
```

**Behavior change.** Verified (host little, requesting 'big'):
  BitFirst = [('a', c_uint16, 4), ('b', c_uint16, 12), ('c', c_uint8)]  (bitfield FIRST)
  BitLater = [('a', c_uint8), ('b', c_uint16, 4), ('c', c_uint16, 12)]  (bitfield LATER)
  BitNested = [('plain', c_uint16), ('bf', BitFirst)]                    (bitfield NESTED)
BEFORE:
  BitFirst  -> NotImplementedError: "ctype structures with _fields_ with more than 2 elements arenot supported.Ctype instance: <...BitFirst object...>Ctype instance fields: [...]"  (garbled)
  BitLater  -> ValueError: too many values to unpack (expected 2)   (guard missed it)
  BitNested -> TypeError: incompatible types, BitFirst instance instead of c_ushort instance   (guard missed it)
AFTER:
  BitFirst  -> NotImplementedError: Cannot reverse the endianness of 'BitFirst': field 'a' is a bitfield (3-tuple entry in _fields_), and ctypes bitfield storage cannot be reversed per-field.
  BitLater  -> NotImplementedError: Cannot reverse the endianness of 'BitLater': field 'b' is a bitfield (3-tuple entry in _fields_), and ctypes bitfield storage cannot be reversed per-field.
  BitNested -> NotImplementedError: Cannot reverse the endianness of 'BitFirst': field 'bf.a' is a bitfield (3-tuple entry in _fields_), and ctypes bitfield storage cannot be reversed per-field.
Also fixes the garbled old message ("arenot supported.Ctype instance: ...") as a side effect.

**Tests to add.** With nonnative = 'big' if sys.byteorder == 'little' else 'little':
1. pytest.raises(NotImplementedError, match="field 'a' is a bitfield") for ctype_to_bytes(BitFirst(1,2,3), nonnative).
2. pytest.raises(NotImplementedError, match="field 'b' is a bitfield") for BitLater(1,2,3) -- the later-field case that used to raise ValueError.
3. pytest.raises(NotImplementedError, match=r"field 'bf\.a' is a bitfield") for BitNested(0x0102, BitFirst(1,2,3)) -- nested detection with dotted path.
4. Same three via bytes_to_ctype(b'...', BitLater, nonnative) to cover the decode direction.
5. Native-order direction (endianness == sys.byteorder) still serializes bitfield structs fine (no reversal is attempted): ctype_to_bytes(BitLater(1,2,3), sys.byteorder) == bytes(BitLater(1,2,3)).

**Risks / sync obligations / review notes.** Not separable from ctypes-1: this guard lives inside the new _reversed_ctype_bytes; if the maintainer rejects ctypes-1, the standalone equivalent is to replace the _fields_[0] check with `if any(len(f) > 2 for f in ctype_instance_fields):` in the old code (which fixes the later-field ValueError but not nested detection or the mutation bug). Behavior change: bitfield structs nested inside other structs/arrays now raise NotImplementedError instead of TypeError -- strictly more consistent with the documented contract. Bitfields inside Unions are still passed through unreversed (union no-op policy, see ctypes-1 decision). No oracle or BitVector-backend sync needed beyond ctypes-1's.

<sub>covers: `inconsistency|bytemaker/conversions/ctypes_.py|56-63`</sub>

---

## 3. Fix run-together words in the ctype_to_bytes / bytes_to_ctype TypeError messages

**Priority:** **now** · [`bytemaker/conversions/ctypes_.py:91-94 (ctype_to_bytes TypeError), 143-146 (bytes_to_ctype TypeError); the third cited site, 57-62, is deleted and replaced by ctypes-2's new message`](../../bytemaker/conversions/ctypes_.py#L91) · **✓ verified on a patched copy**

**Problem.** Adjacent implicitly-concatenated string literals lack separating spaces, so the rendered errors read '...Structure,Union, and Array...' and the old NotImplementedError read '...elements arenot supported.Ctype instance: XCtype instance fields: Y' -- garbled diagnostics that fuse the interpolated values into the following labels.

**Fix.** Add the missing space at the start of the second fragment in both TypeError messages (' Union, and Array ...'). The garbled NotImplementedError at lines 57-62 needs no separate patch: ctypes-2 deletes it and its replacement message is properly spaced and more informative (names the bitfield by dotted path). Lands in the same single-file patch as ctypes-1/-2.

**Before:**

```python
    if not is_instance_of_union(ctype_obj, CType):  # type: ignore
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f"Union, and Array objects, not {type(ctype_obj)}."
        )

...  # bytes_to_ctype, lines 142-146:

    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure,"
            f"Union, and Array types, not {ctype_type}."
        )
```

**After:**

```python
    if not is_instance_of_union(ctype_obj, CType):  # type: ignore
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f" Union, and Array objects, not {type(ctype_obj)}."
        )

...  # bytes_to_ctype:

    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure,"
            f" Union, and Array types, not {ctype_type}."
        )
```

**Behavior change.** Verified:
BEFORE: ctype_to_bytes(123) -> TypeError: ctype_to_bytes only accepts _SimpleCData, Structure,Union, and Array objects, not <class 'int'>.
AFTER:  ctype_to_bytes(123) -> TypeError: ctype_to_bytes only accepts _SimpleCData, Structure, Union, and Array objects, not <class 'int'>.
BEFORE: bytes_to_ctype(b'\x00'*4, int) -> TypeError: bytes_to_ctype only accepts _SimpleCData, Structure,Union, and Array types, not <class 'int'>.
AFTER:  bytes_to_ctype(b'\x00'*4, int) -> TypeError: bytes_to_ctype only accepts _SimpleCData, Structure, Union, and Array types, not <class 'int'>.
The third garbled message cited by the finding (lines 57-62, "...arenot supported.Ctype instance: XCtype instance fields: Y") is deleted outright by ctypes-2, whose replacement message is well-formed and names the offending field.

**Tests to add.** 1. with pytest.raises(TypeError) as ei: ctype_to_bytes(123); assert 'Structure, Union, and Array objects' in str(ei.value).
2. with pytest.raises(TypeError) as ei: bytes_to_ctype(b'\x00'*4, int); assert 'Structure, Union, and Array types' in str(ei.value).
(The existing test_invalid_ctype_to_bytes / test_invalid_bytes_to_ctype only assert the exception type, so they keep passing either way.)

**Risks / sync obligations / review notes.** None functional -- message-text only; no code matches on these strings (existing tests assert only the exception type). The lines 57-62 portion of the finding is covered by ctypes-2's replacement message, so do not additionally patch the old NotImplementedError text. No oracle/BitVector sync needed.

<sub>covers: `ux|bytemaker/conversions/ctypes_.py|57-62, 92-93, 144-145`</sub>

---
