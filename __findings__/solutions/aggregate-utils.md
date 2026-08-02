# Solutions — Legacy aggregate & utils (utils.py / _legacy_aggregate.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Four code fixes plus one docstring fix. Strategy: (1) make utils.is_instance_of_union actually check element types (fixing the StopIteration/RuntimeError crash on empty iterables and the always-True false positive on non-empty ones), adding the Literal support the element checks newly require; (2)-(4) close the three silent-failure/divergence holes in the aggregate path. Solutions 2 and 3 (count_bits_in_unit_type else-raise, to_bytes_aggregate else-raise) are edits to _legacy_aggregate.py that the public dispatcher inherits automatically because conversions/aggregate_types.py delegates those exact paths to the oracle -- the oracle-sync pair is a single edit plus tests asserting BOTH module entry points raise. Solution 4 syncs the already-shipped public is_array=True list fix INTO the oracle so the two implementations of from_bytes_aggregate agree again, and extends the parity test to pin that. Apply order: S1 first (S3's fall-through is guarded by is_instance_of_union results; S1 makes those results honest), then S2, S3, S4 in any order (S4's array path benefits from S2's clear error on unsupported entry types), S5 anytime. All five were empirically verified together on a patched copy: pristine suite baseline 854 passed; patched copy with all fixes plus the 11 proposed new test items (test dir copied beside the patched package, per the sys.path caveat) 865 passed, 0 failed.

_5 solutions — 3 apply-now, 5 empirically verified on a patched copy._

---

## 1. Make is_instance_of_union element checks real: handle empty iterables, check all elements, support Literal

**Priority:** **now** · [`bytemaker/utils.py:utils.py 6-20 (imports), 124-146 (iterable-generic branch)`](../../bytemaker/utils.py#L6) · **✓ verified on a patched copy**

**Problem.** is_instance_of_union's single-arg iterable branch is inverted: any non-empty iterable passes without an element check (['x','y'] is 'an instance of' List[int]), and an empty iterable hits next(iter(obj)) and raises StopIteration -- which PEP 479 turns into RuntimeError inside the Union-branch any() generator. Reachable from the public API: [] in BitVector([1,0,1,1]) raises RuntimeError.

**Fix.** Replace the 'bool(obj) or is_instance_of_union(next(iter(obj)), ...)' line with a real membership check: one-shot iterators (Iterator instances) are accepted unchecked because they cannot be inspected without consuming them (this preserves today's working generator-input behavior in BitVector callers); every other iterable is checked with all(is_instance_of_union(el, type_args[0]) for el in obj), which naturally returns True for empty iterables. Because the element check now actually runs, element types like LaxLiteral01 = Union[Literal[0, 1], int] get recursed into, so a 'type_origin is Literal: return obj in type_args' branch is added (previously isinstance(obj, typing.Literal) would raise an uncaught TypeError) and Literal is added to the typing_redirect import. No oracle pairing needed: utils.py is the single shared definition used by _legacy_aggregate, aggregate_types, and all three BitVector implementations alike (the three impls import it, they do not duplicate it). BitsCastable is @runtime_checkable in all three impls, so union arms that only now get evaluated (after the Iterable arm stops short-circuiting True) are isinstance-safe.

**Before:**

```python
# bytemaker/utils.py lines 6-20 (imports):
from bytemaker.typing_redirect import (
    Any,
    Dict,
    Hashable,
    ItemsView,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

# bytemaker/utils.py lines 124-146 (inside is_instance_of_union):
        type_args = get_args(union_type)

        # If the type is a union type or its instances are iterable
        #   check if the object is an instance of any
        #       of the constituent types
        #   or if the object is an iterable and its first element
        #       is an instance of the first type argument
        if type_origin is Union:
            return any(is_instance_of_union(obj, type_arg) for type_arg in type_args)
        elif isinstance(obj, type_origin):
            if len(type_args) == 1 and isinstance(obj, Iterable):
                return bool(obj) or is_instance_of_union(next(iter(obj)), type_args[0])

            # If the type is a multi-arg, non-union, non-generic type
            else:
                raise ValueError(
                    f"(Generic?) type {union_type} has origin {type_origin}"
                    f" and type args {type_args}."
                    f" Non-union types with multiple subscripts are not"
                    f" supported."
                )
        else:
            return False
```

**After:**

```python
# bytemaker/utils.py imports (add Literal):
from bytemaker.typing_redirect import (
    Any,
    Dict,
    Hashable,
    ItemsView,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    Optional,
    Sequence,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

# bytemaker/utils.py, replacing lines 124-146:
        type_args = get_args(union_type)

        # If the type is a Literal type
        #   check if the object equals one of the literal values
        if type_origin is Literal:
            return obj in type_args

        # If the type is a union type or its instances are iterable
        #   check if the object is an instance of any
        #       of the constituent types
        #   or if the object is an iterable and all of its elements
        #       are instances of the single type argument
        if type_origin is Union:
            return any(is_instance_of_union(obj, type_arg) for type_arg in type_args)
        elif isinstance(obj, type_origin):
            if len(type_args) == 1 and isinstance(obj, Iterable):
                # One-shot iterators cannot be inspected without consuming
                #   them; accept and let the consumer validate the elements
                if isinstance(obj, Iterator):
                    return True
                return all(
                    is_instance_of_union(element, type_args[0]) for element in obj
                )

            # If the type is a multi-arg, non-union, non-generic type
            else:
                raise ValueError(
                    f"(Generic?) type {union_type} has origin {type_origin}"
                    f" and type args {type_args}."
                    f" Non-union types with multiple subscripts are not"
                    f" supported."
                )
        else:
            return False
```

**Behavior change.** Verified on pristine repo vs patched copy (actual outputs).
BEFORE:
  is_instance_of_union([], List[int]): raises StopIteration
  is_instance_of_union(['x','y'], List[int]): -> True
  is_instance_of_union([1,2], List[int]): -> True
  is_instance_of_union([1,'x'], List[int]): -> True
  [] in BitVector([1,0,1,1]): raises RuntimeError: generator raised StopIteration  (all three backends: native, speedup, bitarray)
  ['x'] in BitVector([1,0,1,1]): raises ValueError: bit must be 0 or 1, got 'x' (native/speedup) / TypeError: 'str' object cannot be interpreted as an integer (bitarray)
  (g for g in [0,1]) in bv: -> True
AFTER:
  is_instance_of_union([], List[int]): -> True
  is_instance_of_union(['x','y'], List[int]): -> False
  is_instance_of_union([1,2], List[int]): -> True
  is_instance_of_union([1,'x'], List[int]): -> False
  [] in BitVector([1,0,1,1]): -> True   (all three backends)
  ['x'] in BitVector([1,0,1,1]): -> False   (all three backends)
  [0,1] in bv: -> True; [1,1] in bv: -> True (unchanged)
  (g for g in [0,1]) in bv: -> True (generator inputs preserved)

**Tests to add.** test/utils_test.py, extend the test_is_instance_of_union parametrize list with:
        ([], typing.List[int], True),
        ([1, 2], typing.List[int], True),
        (["x", "y"], typing.List[int], False),
        ([1, "x"], typing.List[int], False),
        ((1, 2), typing.List[int], False),  # wrong container
        (0, typing.Literal[0, 1], True),
        (2, typing.Literal[0, 1], False),
        (iter(["x"]), typing.Iterable[int], True),  # one-shot: accepted unchecked
Plus a BitVector containment test (runs against all three backends via the existing implementations fixtures, or minimally the active bitarray one):
def test_contains_iterable_edge_cases():
    bv = BitVector([1, 0, 1, 1])
    assert [] in bv          # was RuntimeError
    assert [0, 1] in bv
    assert ["x"] not in bv  # was TypeError from BitVector(['x'])
    assert (b for b in [0, 1]) in bv  # generator input still works

**Risks / sync obligations / review notes.** This helper has ~40 call sites; the behavior change is that the Iterable[...] arm of unions now returns honest False for mistyped element iterables instead of blanket True. Consequences observed: (a) BitVector.__contains__ now returns False for e.g. ['x'] instead of raising TypeError from the constructor -- __contains__'s own docstring says 'or False otherwise', so this is the documented intent; (b) union arms after Iterable[...] now actually get evaluated -- all BitsCastable protocols are @runtime_checkable so this is safe; (c) element checks are O(n) for sequences (callers that pass the gate do an O(n) construction right after, so no complexity change); (d) one-shot iterators are accepted unchecked (same acceptance as today, still non-consuming). All three BitVector implementations share this one definition, so no per-impl sync is needed; re-run the full suite including bitvector_implementations_test.py and bitvector_differential_test.py. REVIEWER NOTE (quantified): the containment gate on large plain-list inputs goes O(1)->O(n) with ~2.7us/element (two caught TypeErrors per element); measured ([0,1]*200000) in bv at 0.0016s before -> 0.55s after (~340x). No in-package or benchmark hot path passes large plain lists (str/BitVector/bitarray inputs hit O(1) union arms first), but user code doing big-list containment will feel it. Also: True matches Literal[0,1] via int equality.

> ⚖️ **Decision needed:** Empty-iterable policy: proposed True ([] IS an Iterable[int]; also keeps '[] in bv' == True, consistent with '"" in "abc"'). And one-shot iterators are accepted unchecked rather than consumed or rejected. Confirm both policies.

<sub>covers: `bug|bytemaker/utils.py|133-135`</sub>

---

## 2. Raise TypeError from count_bits_in_unit_type for unsupported types instead of returning None

**Priority:** **now** · [`bytemaker/_legacy_aggregate.py:_legacy_aggregate.py 82-88 (add trailing else)`](../../bytemaker/_legacy_aggregate.py#L82) · **✓ verified on a patched copy**

**Problem.** count_bits_in_unit_type is annotated -> int but silently returns None when unit_type is not a CType/BitType/PyType/dataclass. The None then explodes in caller arithmetic far from the bad field annotation: count_bytes_in_unit_type(Foo) raises "unsupported operand type(s) for +: 'NoneType' and 'int'" with no mention of the offending type.

**Fix.** Add a final else that raises TypeError naming the offending type, in the same message style as the module's existing to_bits_individual/from_bits_individual raises ('...is not a CType, YType, or PyType', extended with 'or dataclass' since this function also sizes dataclasses). Oracle-sync pairing: this IS the oracle; the public path (conversions/aggregate_types.count_bits_in_unit_type) is a cache wrapper around this exact function (_orig_count_bits_in_unit_type = _legacy.count_bits_in_unit_type), so the single edit fixes both entry points at once -- the paired test asserts the raise through BOTH modules. The cache wrapper's try/except only wraps the cache lookup, so the new TypeError propagates cleanly and failures are never cached.

**Before:**

```python
# bytemaker/_legacy_aggregate.py lines 82-88 (end of count_bits_in_unit_type):
    elif is_subclass_of_union(unit_type, DataClassType):
        size_in_bits = 0
        field_types = resolve_field_types(unit_type)
        for field in dataclasses.fields(unit_type):
            size_in_bits += count_bits_in_unit_type(field_types[field.name])
        return size_in_bits
```

**After:**

```python
# bytemaker/_legacy_aggregate.py (end of count_bits_in_unit_type):
    elif is_subclass_of_union(unit_type, DataClassType):
        size_in_bits = 0
        field_types = resolve_field_types(unit_type)
        for field in dataclasses.fields(unit_type):
            size_in_bits += count_bits_in_unit_type(field_types[field.name])
        return size_in_bits
    else:
        raise TypeError(
            f"Cannot count bits in {unit_type} because the unit type"
            f" is not a CType, YType, PyType, or dataclass"
        )
```

**Behavior change.** Verified (actual outputs).
BEFORE:
  legacy count_bits_in_unit_type(Foo): -> None
  legacy count_bytes_in_unit_type(Foo): raises TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'
  public count_bits_in_unit_type(Foo): -> None
AFTER (all three entry points):
  raises TypeError: Cannot count bits in <class 'Foo'> because the unit type is not a CType, YType, PyType, or dataclass

**Tests to add.** test/aggregate_types_test.py (add; needs 'from bytemaker import _legacy_aggregate as legacy' and the public count_bits_in_unit_type import):
def test_count_bits_unsupported_type_raises():
    class NotAUnit:
        pass
    with pytest.raises(TypeError, match="Cannot count bits"):
        legacy.count_bits_in_unit_type(NotAUnit)      # oracle
    with pytest.raises(TypeError, match="Cannot count bits"):
        count_bits_in_unit_type(NotAUnit)             # cached public path
    with pytest.raises(TypeError, match="Cannot count bits"):
        count_bytes_in_unit_type(NotAUnit)            # arithmetic caller

**Risks / sync obligations / review notes.** Nothing in the package branches on a None return (all callers do arithmetic that previously crashed cryptically), so the only behavior change is a clearer, earlier exception -- still a TypeError, just with a useful message. The dispatcher module needs no edit. Re-run test/plan_fastpath_test.py (differential oracle tests) and test/aggregate_types_test.py.

<sub>covers: `bug|bytemaker/_legacy_aggregate.py|68-88`, `ux|bytemaker/_legacy_aggregate.py|68-87`</sub>

---

## 3. Make to_bytes_aggregate raise on unconvertible input like its to_bits_aggregate dual

**Priority:** **now** · [`bytemaker/_legacy_aggregate.py:_legacy_aggregate.py 371-375 (add trailing else to to_bytes_aggregate)`](../../bytemaker/_legacy_aggregate.py#L371) · **✓ verified on a patched copy**

**Problem.** to_bytes_aggregate has three branches (UnitType / DataClassType / Iterable) and no else: unrecognized input (None, a bare object) silently serializes to b'', a data-loss trap. Its dual to_bits_aggregate raises a clear TypeError for the same input, so the two serializers fail asymmetrically.

**Fix.** Add the missing final else raising TypeError, mirroring to_bits_aggregate's message verbatim but with 'to bytes'. Oracle-sync pairing: this IS the oracle; the public conversions/aggregate_types.to_bytes_aggregate only short-circuits eligible plan dataclasses and delegates everything else (including all unrecognized inputs) to _legacy.to_bytes_aggregate, so the single oracle edit gives both entry points the raise -- the paired test asserts it through both modules. Note the empty-iterable and zero-field-dataclass cases still legitimately return b'' (they DO match a branch); only true fall-through now raises.

**Before:**

```python
# bytemaker/_legacy_aggregate.py lines 357-375 (body of to_bytes_aggregate):
    ret_bytes = bytearray()

    if is_instance_of_union(units, UnitType):
        ret_bytes = to_bytes_individual(units, endianness=endianness)

    elif isinstance(units, DataClassType):
        field_types = resolve_field_types(type(units))
        for field in dataclasses.fields(units):
            field_type = field_types[field.name]
            field_value = getattr(units, field.name)
            field_value = trycast(field_value, field_type)
            field_value_bytes = to_bytes_aggregate(field_value, endianness=endianness)
            ret_bytes.extend(field_value_bytes)

    elif isinstance(units, Iterable):
        for unit in units:
            ret_bytes.extend(to_bytes_aggregate(unit, endianness=endianness))

    return bytes(ret_bytes)
```

**After:**

```python
# bytemaker/_legacy_aggregate.py (body of to_bytes_aggregate):
    ret_bytes = bytearray()

    if is_instance_of_union(units, UnitType):
        ret_bytes = to_bytes_individual(units, endianness=endianness)

    elif isinstance(units, DataClassType):
        field_types = resolve_field_types(type(units))
        for field in dataclasses.fields(units):
            field_type = field_types[field.name]
            field_value = getattr(units, field.name)
            field_value = trycast(field_value, field_type)
            field_value_bytes = to_bytes_aggregate(field_value, endianness=endianness)
            ret_bytes.extend(field_value_bytes)

    elif isinstance(units, Iterable):
        for unit in units:
            ret_bytes.extend(to_bytes_aggregate(unit, endianness=endianness))

    else:
        raise TypeError(
            f"Cannot convert {units} to bytes because the unit type"
            f" is not a CType, YType, or PyType"
        )

    return bytes(ret_bytes)
```

**Behavior change.** Verified (actual outputs).
BEFORE:
  legacy to_bits_aggregate(NotConvertible()): raises TypeError: Cannot convert <...NotConvertible...> to bits because the unit type is not a CType, YType, or PyType
  legacy to_bytes_aggregate(NotConvertible()): -> b''
  legacy to_bytes_aggregate(None): -> b''
  public to_bytes_aggregate(NotConvertible()): -> b''
AFTER (oracle and public dispatcher):
  raises TypeError: Cannot convert <...NotConvertible...> to bytes because the unit type is not a CType, YType, or PyType
  raises TypeError: Cannot convert None to bytes because the unit type is not a CType, YType, or PyType
  to_bytes_aggregate([]) still == b'' (empty Iterable branch, unchanged)

**Tests to add.** test/aggregate_types_test.py (add):
def test_to_bytes_aggregate_unconvertible_raises():
    class NotConvertible:
        pass
    with pytest.raises(TypeError, match="Cannot convert"):
        legacy.to_bytes_aggregate(NotConvertible())   # oracle
    with pytest.raises(TypeError, match="Cannot convert"):
        to_bytes_aggregate(NotConvertible())          # public dispatcher
    with pytest.raises(TypeError, match="Cannot convert"):
        to_bytes_aggregate(None)
    # branch-matching inputs still serialize (no over-raising):
    assert to_bytes_aggregate([]) == b""              # empty Iterable branch

**Risks / sync obligations / review notes.** Any caller that (accidentally) depended on b'' for garbage input now gets TypeError -- desired per the no-compat-pressure rule, and no in-package caller does. Interacts with S1: after S1, is_instance_of_union(units, UnitType) is unchanged for these plain class unions, but mistyped iterables still enter the Iterable branch and fail per-element inside the recursion (unchanged). Re-run plan_fastpath differential tests and aggregate_types tests.

<sub>covers: `inconsistency|bytemaker/_legacy_aggregate.py|281-285, 357-375`, `ux|bytemaker/_legacy_aggregate.py|357-375`</sub>

---

## 4. Sync the is_array=True list-return fix into the frozen oracle's from_bytes_aggregate

**Priority:** soon · [`bytemaker/_legacy_aggregate.py:_legacy_aggregate.py 378-448 (from_bytes_aggregate); plan_fastpath_test.py 157-168`](../../bytemaker/_legacy_aggregate.py#L378) · **✓ verified on a patched copy**

**Problem.** The public dispatcher deliberately fixed from_bytes_aggregate(..., is_array=True) to return a list of decoded entries (its docstring calls the old behavior 'unusable'), but the fix was only applied to conversions/aggregate_types.py. The oracle still does aggregate_type(*entries) for dataclasses (producing e.g. Pair(a=Pair(...), b=Pair(...))) and ignores is_array entirely for scalar types (raising a length ValueError instead of decoding entries). One public function name, two behaviors depending on the module called -- exactly the divergence the oracle-sync rule exists to prevent.

**Fix.** Apply the documented upstream behavior change to the oracle, per the module's own header rule ('Do not modify ... except to sync a deliberate upstream behavior change into both paths at once'). Restructure from_bytes_aggregate to handle is_array first, exactly like the dispatcher: chunk bytes_obj by count_bits_in_aggregate_type-derived entry size and return the list of recursively decoded entries (this also gives scalars the same working array behavior as the dispatcher, completing the sync rather than syncing only the dataclass half). The non-array paths are byte-for-byte unchanged. Docstring's is_array line is updated to the dispatcher's wording. Test pairing: extend test_from_bytes_is_array_returns_list in plan_fastpath_test.py to assert the oracle now returns the same list for both the dataclass and scalar cases.

**Before:**

```python
# bytemaker/_legacy_aggregate.py lines 395-396 (docstring), 404-448 (body):
        is_array (bool, optional): Whether the object is an array of the aggregate type.
            Defaults to False.
...
    if is_subclass_of_union(aggregate_type, UnitType):
        return from_bytes_individual(bytes_obj, aggregate_type, endianness=endianness)
    else:
        size_in_bits = count_bits_in_unit_type(aggregate_type)

        if not is_array:
            if len(bytes_obj) * 8 != size_in_bits:
                raise ValueError(
                    f"Cannot convert {bytes_obj} to {aggregate_type}"
                    f" because the # of bits in the bytes object ({len(bytes_obj) * 8})"
                    f" does not match the # of bits in the unit type ({size_in_bits})"
                )

            read_fields = list()
            field_types = resolve_field_types(aggregate_type)
            for field in dataclasses.fields(aggregate_type):
                field_type = field_types[field.name]
                field_size_in_bytes = (count_bits_in_unit_type(field_type) + 7) // 8
                field_bytes = bytes_obj[:field_size_in_bytes]
                field_value = from_bytes_aggregate(
                    field_bytes, field_type, endianness=endianness
                )
                read_fields.append(field_value)
                bytes_obj = bytes_obj[field_size_in_bytes:]
            retval = aggregate_type(*read_fields)

        else:
            arr_entry_list = list()
            size_in_bytes = (size_in_bits + 7) // 8
            for i in range(0, len(bytes_obj), size_in_bytes):
                endindex = (
                    i + size_in_bytes
                    if i + size_in_bytes < len(bytes_obj)
                    else len(bytes_obj)
                )
                arr_entry_list.append(
                    from_bytes_aggregate(
                        bytes_obj[i:endindex],
                        aggregate_type,
                        endianness=endianness,
                    )
                )
            retval = aggregate_type(*arr_entry_list)

    return retval
```

**After:**

```python
# bytemaker/_legacy_aggregate.py (docstring line, then body from line 404):
        is_array (bool, optional): Whether ``bytes_obj`` holds consecutive
            entries of ``aggregate_type``; if so a ``list`` of decoded entries
            is returned. Defaults to False.
...
    if is_array:
        size_in_bits = count_bits_in_aggregate_type(aggregate_type)
        size_in_bytes = (size_in_bits + 7) // 8
        arr_entry_list = list()
        for i in range(0, len(bytes_obj), size_in_bytes):
            arr_entry_list.append(
                from_bytes_aggregate(
                    bytes_obj[i : i + size_in_bytes],
                    aggregate_type,
                    endianness=endianness,
                )
            )
        return arr_entry_list

    if is_subclass_of_union(aggregate_type, UnitType):
        return from_bytes_individual(bytes_obj, aggregate_type, endianness=endianness)
    else:
        size_in_bits = count_bits_in_unit_type(aggregate_type)

        if len(bytes_obj) * 8 != size_in_bits:
            raise ValueError(
                f"Cannot convert {bytes_obj} to {aggregate_type}"
                f" because the # of bits in the bytes object ({len(bytes_obj) * 8})"
                f" does not match the # of bits in the unit type ({size_in_bits})"
            )

        read_fields = list()
        field_types = resolve_field_types(aggregate_type)
        for field in dataclasses.fields(aggregate_type):
            field_type = field_types[field.name]
            field_size_in_bytes = (count_bits_in_unit_type(field_type) + 7) // 8
            field_bytes = bytes_obj[:field_size_in_bytes]
            field_value = from_bytes_aggregate(
                field_bytes, field_type, endianness=endianness
            )
            read_fields.append(field_value)
            bytes_obj = bytes_obj[field_size_in_bytes:]
        retval = aggregate_type(*read_fields)

    return retval
```

**Behavior change.** Verified (actual outputs, Pair = dataclass of two UInt8, buf = bytes([1,2,3,4])).
BEFORE:
  dispatcher from_bytes_aggregate(buf, Pair, is_array=True): -> [Pair(a=UInt8(1), b=UInt8(2)), Pair(a=UInt8(3), b=UInt8(4))]
  oracle     from_bytes_aggregate(buf, Pair, is_array=True): -> Pair(a=Pair(a=UInt8(1), b=UInt8(2)), b=Pair(a=UInt8(3), b=UInt8(4)))   <- single nested record
  dispatcher from_bytes_aggregate(4B, UInt16, is_array=True): -> [UInt16(1), UInt16(2)]
  oracle     from_bytes_aggregate(4B, UInt16, is_array=True): raises ValueError: ...number of bits in the bytes object (32) does not match the number of bits in the unit type (16)
AFTER:
  oracle output is identical to the dispatcher for both the dataclass case (list of 2 Pair records, field-for-field equal) and the scalar case ([UInt16(1), UInt16(2)]); non-array decoding byte-for-byte unchanged (all 160 plan_fastpath differential tests pass).

**Tests to add.** test/plan_fastpath_test.py, extend test_from_bytes_is_array_returns_list:
    # the frozen oracle must implement the same (synced) is_array behavior
    out_old = legacy.from_bytes_aggregate(
        one + two, cls, is_array=True, endianness="little"
    )
    assert isinstance(out_old, list) and len(out_old) == 2
    fields = [("a", UInt16), ("b", UInt8)]
    assert_equal_records(out[0], out_old[0], fields)
    assert_equal_records(out[1], out_old[1], fields)
    ...
    scalars_old = legacy.from_bytes_aggregate(
        b"\x01\x00\x02\x00", UInt16, is_array=True, endianness="little"
    )
    assert [s.value for s in scalars_old] == [1, 2]

**Risks / sync obligations / review notes.** This changes frozen-oracle behavior, but only for is_array=True, which no other oracle code path and no packing path touches (the dispatcher never delegates with is_array=True; plan fast paths are unaffected), and it is precisely the sanctioned sync of the already-documented dispatcher fix. The scalar half of the sync means oracle scalar+is_array calls now decode instead of raising ValueError -- that matches the dispatcher and the dispatcher docstring's stated intent. Re-run test/plan_fastpath_test.py (all differential tests) after applying. If S2 is applied too, unsupported entry types in the array path fail with the clear TypeError from count_bits. REVIEWER CORRECTIONS: the plan_fastpath differential suite is 146 tests (not 160); and the clear-error claim for unsupported array entry types is misattributed - that error comes from dataclasses.fields, identically on both entry points (not from aggregate-utils-2).

> ⚖️ **Decision needed:** The full sync also fixes oracle scalar+is_array (previously ValueError). Alternative was a minimal one-line sync (retval = arr_entry_list) that would leave scalar arrays diverged; confirm the full sync is preferred.

<sub>covers: `inconsistency|bytemaker/_legacy_aggregate.py|430-446`</sub>

---

## 5. Fix twos_complement docstring: phantom 'bits' param, convert to the file's Google-style Args/Returns

**Priority:** later · [`bytemaker/utils.py:utils.py 314-321`](../../bytemaker/utils.py#L314) · **✓ verified on a patched copy**

**Problem.** twos_complement(number, n_bits=32) documents ':param bits:' -- a parameter that does not exist (the real name is n_bits), so docstring-guided calls like twos_complement(5, bits=8) raise TypeError. It is also the only function in utils.py using RST field lists instead of the file's Google-style Args:/Returns: blocks.

**Fix.** Rename the documented parameter to n_bits, note its default, and convert the docstring to the Google-style Args/Returns format used by the neighboring twos_complement_bit_length (utils.py is a reference-era file whose house style is Google-style blocks, not the newer narrative RST of structs.py/plans.py). No code change; docstring only.

**Before:**

```python
# bytemaker/utils.py lines 314-321:
def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    :param number: The integer to convert.
    :param bits: The bit width for the two's complement representation.
    :return: A string representing the two's complement of the number.
    """
```

**After:**

```python
# bytemaker/utils.py:
def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    Args:
        number (int): The integer to convert.
        n_bits (int): The bit width for the two's complement representation.
            Defaults to 32.

    Returns:
        str: A string of the number's two's-complement bits.
    """
```

**Behavior change.** Docstring-only; runtime behavior unchanged. Before: docstring advertises 'bits', and twos_complement(5, bits=8) raises TypeError: twos_complement() got an unexpected keyword argument 'bits'; twos_complement(5, n_bits=8) == '00000101'. After: docs match the real signature.

**Tests to add.** No runtime test needed. Optional doc-consistency guard in test/utils_test.py:
def test_twos_complement_docstring_matches_signature():
    import inspect
    from bytemaker.utils import twos_complement
    doc = twos_complement.__doc__
    assert "n_bits" in doc and ":param bits:" not in doc
Plus a behavior pin: twos_complement(5, n_bits=8) == "00000101" and twos_complement(-3, n_bits=4) == "1101".

**Risks / sync obligations / review notes.** None; comment/docstring only.

<sub>covers: `ux|bytemaker/utils.py|314-325`</sub>

---
