# Solutions — Endianness validation (cross-cutting)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

One canonical helper -- validate_endianness(value, name='endianness', exc=ValueError) -> Literal['big','little'] in bytemaker/utils.py -- is applied at all 14 endianness-string intake boundaries. utils.py imports only typing_redirect, so every consumer (bittypes, conversions, the legacy oracle, structs) can import it without cycles. Vocabulary is strict-exact {'big','little'}: that matches the one already-validated site in the repo (structs.py StructMeta -> PlanCompileError) and the stdlib int.from_bytes contract that BitVector.to_int already delegates to in all three backends; no aliases or case folding (flagged as the one decision). endianness-1 adds the helper and validates the bittypes intake: BitType.__init__ after the source_else_big resolution (which covers every Int/SInt/UInt/Float/String/Buffer constructor -- int.py's SInt merely forwards, so int.py needs no edit) and bytes_to_bittype. endianness-2 applies it at the remaining intakes: pytype_to_bytes/bytes_to_pytype, ctype_to_bytes/bytes_to_ctype, the four legacy-oracle entry points (to_bytes_individual/from_bytes_individual -- re-exported verbatim as THE public functions -- and to_bytes_aggregate/from_bytes_aggregate, synced with the identical checks in the aggregate_types wrappers per the oracle procedure), and structs.py Array.__init__ (new check, PlanCompileError) plus converting the existing StructMeta check to the helper. Apply endianness-1 first (it introduces the helper); endianness-2 depends on it. Sites checked and deliberately NOT patched: BitVector.to_int in all three backends already fails loudly via int.from_bytes (verified: ValueError "byteorder must be either 'little' or 'big'"); BitVector.from_bytes/to_bytes take a reverse_endianness bool, not a string; ctype_to_bits/bits_to_ctype and the array()/Array.of sugar validate transitively through the functions they forward to; plans.py Plan.parse/pack and _pack_all_plain_numbers only ever receive values validated at the aggregate entries. Composes with ctypes-1/2/3 (one-line insertions at function heads their rewrite does not touch), pytypes-1/2/3 (docstring/registry lines, disjoint from these body edits), and narrowing-1/2/4 (no int.py edit here; bittype.py regions disjoint; error style matches narrowing-4's 'X must be ...; got {value!r}'). Both solutions verified together on a patched copy: full suite 854/854 (import path confirmed via bytemaker.__file__).

_2 solutions — 2 apply-now, 2 empirically verified on a patched copy._

---

## 1. Add a validate_endianness helper and reject typo'd endianness at BitType construction and bytes_to_bittype

**Priority:** **now** · [`bytemaker/utils.py:utils.py: 6-20 (add Literal) and new function after Trie (~line 95); bittype.py: 21 (import), 148-151 (BitType.__init__ tail), 621-625 (bytes_to_bittype). int.py needs no edit: SInt.__init__ (571-587) forwards endianness verbatim to the now-validating base.`](../../bytemaker/utils.py#L6) · **✓ verified on a patched copy**

**Problem.** BitType.__init__ stores any endianness string verbatim and __bytes__ special-cases only 'big', so every typo or variant ('bigg', 'litle', 'BE', 'LE', 'Little') silently serializes little-endian -- bytes(UInt16(0x0102, endianness='bigg')) == b'\x02\x01' with no error -- and str()/repr() print the bogus tag as if accepted. The SInt/UInt constructors in int.py re-declare and forward the parameter unvalidated, so the trap manifests through every integer type; bytes_to_bittype has the mirror-image trap (only 'little' special-cased, so a typo silently means big).

**Fix.** Add one canonical helper, validate_endianness(endianness, name='endianness', exc=ValueError) -> Literal['big','little'], to bytemaker/utils.py (chosen because utils imports only typing_redirect and is already imported by bittype.py, pytypes.py, ctypes_.py, _legacy_aggregate.py -- no cycle risk anywhere in the package). It raises `{name} must be 'big' or 'little'; got {value!r}` -- same shape as narrowing-4's int_format error -- and returns the value so call sites can validate inline; the `name`/`exc` knobs let schema intakes (endianness-2) blame their own parameter and raise PlanCompileError. Then validate the two bittypes intakes: (a) BitType.__init__, immediately after the 'source_else_big' sentinel resolves, so the stored _endianness is provably canonical and __bytes__'s big-vs-else branch can never see garbage -- this single edit covers the constructors of every BitType subclass (Int/SInt/UInt/Float/String/Buffer), including int.py's SInt/UInt which just forward the parameter, so int.py itself needs no change and cannot conflict with narrowing-2/narrowing-4's edits there; (b) bytes_to_bittype, whose only use of the parameter is the reversal test, validated inline at that first use (the function's intake). Validation at intake, not at use: the typo fails at the call boundary with the parameter named, instead of surfacing as byte-reversed output downstream.

**Before:**

```python
# --- bytemaker/utils.py, imports (lines 6-20; Literal is added) ---
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

# --- bytemaker/utils.py: the helper is inserted between the end of Trie
# --- (line 94) and this line (97):
def is_instance_of_union(obj, union_type: type):

# --- bytemaker/bittypes/bittype.py line 21 (import) ---
from bytemaker.utils import classproperty

# --- bytemaker/bittypes/bittype.py 148-151 (BitType.__init__ tail) ---
        if endianness == "source_else_big":
            endianness = "big"
        endianness: Literal["big", "little"]
        self._endianness = endianness

# --- bytemaker/bittypes/bittype.py 621-625 (bytes_to_bittype body) ---
    if endianness == "little":
        unitbytes = unitbytes[::-1]
    # bytes go straight to the bits setter, which snapshots into locked
    # storage; a BitVector(...) wrap here would just be a second copy.
    return unittype(bits=unitbytes)
```

**After:**

```python
# --- bytemaker/utils.py, imports: add Literal (alphabetical) ---
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

# --- bytemaker/utils.py: new function after the Trie class, before
# --- is_instance_of_union ---
def validate_endianness(
    endianness: Any, name: str = "endianness", exc: type = ValueError
) -> Literal["big", "little"]:
    """
    Validates a byte-order argument at an API intake point.

    Every bytemaker parameter that selects a byte order accepts exactly
    "big" or "little". Historically any other string fell through into
    whichever branch a call site's equality test happened to pick (a typo
    like "bigg" serialized little-endian through BitType.__bytes__ but
    big-endian through pytype_to_bytes), so the check lives here and runs
    at intake, not at use.

    Args:
        endianness: The value to validate.
        name (str): The parameter name to blame in the error message.
            Defaults to "endianness".
        exc (type): The exception class to raise. Defaults to ValueError;
            schema-compile intake points pass PlanCompileError.

    Returns:
        Literal["big", "little"]: ``endianness``, unchanged.

    Raises:
        exc: If ``endianness`` is not exactly "big" or "little".
    """
    if endianness not in ("big", "little"):
        raise exc(f"{name} must be 'big' or 'little'; got {endianness!r}")
    return endianness

# --- bytemaker/bittypes/bittype.py line 21 ---
from bytemaker.utils import classproperty, validate_endianness

# --- bytemaker/bittypes/bittype.py (BitType.__init__ tail; the bare
# --- Literal annotation-statement is dropped -- the helper's return type
# --- performs the same narrowing for checkers) ---
        if endianness == "source_else_big":
            endianness = "big"
        self._endianness = validate_endianness(endianness)

# --- bytemaker/bittypes/bittype.py (bytes_to_bittype body) ---
    if validate_endianness(endianness) == "little":
        unitbytes = unitbytes[::-1]
    # bytes go straight to the bits setter, which snapshots into locked
    # storage; a BitVector(...) wrap here would just be a second copy.
    return unittype(bits=unitbytes)
```

**Behavior change.** All outputs below are from actual runs (host byteorder: little).
BEFORE (pristine repo):
  bytes(UInt16(0x0102, endianness='bigg'))  -> b'\x02\x01'  (silently little-endian)
  bytes(UInt16(0x0102, endianness='litle')) -> b'\x02\x01'  (silently little-endian)
  str(UInt8(1, endianness='LE'))            -> 'UInt8[LE](1 = 00000001)'  (bogus tag accepted and printed)
  bytes_to_bittype(b'\x01\x02', UInt16, endianness='litle') -> stores 0x0102  (silently BIG: opposite fallback direction from the constructor path)
AFTER (patched copy):
  UInt16(0x0102, endianness='bigg')  -> ValueError: endianness must be 'big' or 'little'; got 'bigg'
  UInt16(0x0102, endianness='litle') -> ValueError: endianness must be 'big' or 'little'; got 'litle'
  UInt8(1, endianness='LE')          -> ValueError: endianness must be 'big' or 'little'; got 'LE'
  bytes_to_bittype(b'\x01\x02', UInt16, 'litle') -> ValueError: endianness must be 'big' or 'little'; got 'litle'
Happy paths unchanged (verified byte-identical before/after):
  bytes(UInt16(0x0102)) == bytes(UInt16(0x0102, endianness='big')) == b'\x01\x02'; endianness='little' -> b'\x02\x01';
  explicit endianness='source_else_big' still resolves to 'big'; UInt16(UInt16(1, endianness='little')).endianness == 'little' (source propagation);
  bytes_to_bittype(b'\x01\x02', UInt16, 'little') -> b'\x02\x01'.
Full suite against the patched copy (with endianness-2 also applied): 854 passed.

**Tests to add.** In test/bittypes_test.py: (1) for bad in ('bigg', 'litle', 'LE', 'BE', 'Little', ''): pytest.raises(ValueError, match="endianness must be 'big' or 'little'") for UInt16(0x0102, endianness=bad) and for SInt16(5, endianness=bad) (proves the int.py constructors are covered via the base) and for bytes_to_bittype(b'\x01\x02', UInt16, endianness=bad). (2) The error names the offending value: match="got 'bigg'". (3) Happy paths: bytes(UInt16(0x0102, endianness='big')) == b'\x01\x02', endianness='little' -> b'\x02\x01', explicit 'source_else_big' -> endianness == 'big', and UInt16(UInt16(1, endianness='little')).endianness == 'little'. In test/utils_test.py (or alongside): validate_endianness('big') == 'big'; validate_endianness('little') == 'little'; pytest.raises(ValueError, match="foo must be 'big' or 'little'; got 'x'") for validate_endianness('x', name='foo'); pytest.raises(PlanCompileError) for validate_endianness('x', exc=PlanCompileError).

**Risks / sync obligations / review notes.** Behavior change is reject-only: constructions that previously 'worked' by silently emitting little-endian bytes for a typo now raise at the constructor (sole-user policy: loud beats silent-wrong; no repo code or test passes a non-canonical string -- suite 854/854). The bare `endianness: Literal[...]` annotation-statement in __init__ is dropped; the helper's return annotation preserves the checker-visible narrowing. BitVector backends need NO sync: to_int in all three implementations delegates to int.from_bytes, which already raises "ValueError: byteorder must be either 'little' or 'big'" (verified on the bitarray backend), and from_bytes/to_bytes take a reverse_endianness bool, not a string. Oracle: bytes_to_bittype is one shared function consumed by both _legacy_aggregate.from_bytes_individual and plans.Plan.parse, so the oracle and the fast path change together; parity tests green. Cross-group merges: narrowing-1 adds `import sys` to bittype.py's stdlib import block and narrowing-2 rewrites the StructPackedBitType.value setter -- disjoint from this fix's regions (from-import line 21, __init__ tail 148-151, bytes_to_bittype tail); narrowing-2/float-4 edit int.py, which this fix does not touch at all. Re-run: full suite.

> ⚖️ **Decision needed:** Vocabulary: strict-exact {'big','little'} (proposed), matching structs.py's existing check and the int.from_bytes contract BitVector.to_int already exposes -- or should the helper lowercase-normalize (accept 'Big'/'LITTLE') and/or accept aliases ('le'/'be'/'<'/'>')? Strict-exact keeps every intake in the package and the stdlib delegate accepting the identical vocabulary; normalizing only the helper-guarded sites would make UInt8(1, endianness='BIG') legal while BitVector.to_int('BIG') and struct-compile stay illegal.

<sub>covers: `ux|bytemaker/bittypes/bittype.py|117-151`, `ux|bytemaker/bittypes/int.py|571-587`</sub>

---

## 2. Validate endianness at every conversion, aggregate, oracle, and schema intake (pytypes, ctypes, legacy aggregate, wrappers, Array)

**Priority:** **now** · [`bytemaker/conversions/pytypes.py:pytypes.py: 8 (import), 296-299, 341-343; ctypes_.py: 9 (import), 90 (ctype_to_bytes head), 142 (bytes_to_ctype head); aggregate_types.py: 43 (import), 192 (to_bytes_aggregate head), 229 (from_bytes_aggregate head); _legacy_aggregate.py: 39 (import), 137 (to_bytes_individual), 202 (from_bytes_individual), 357 (to_bytes_aggregate), 404 (from_bytes_aggregate); structs.py: import block (~77), 752-755 (StructMeta), 1303-1304 (Array.__init__)`](../../bytemaker/conversions/pytypes.py#L8) · **✓ verified on a patched copy**

**Problem.** Every remaining endianness intake special-cases exactly one string, so a typo silently picks the other byte order -- and not even consistently: pytype_to_bytes/bytes_to_pytype and the aggregate fast path fall through to BIG, the BitType constructor path (finding 1) falls through to LITTLE, and ctype_to_bytes/bytes_to_ctype compare against sys.byteorder so a typo means reverse-of-HOST (direction changes with the machine). Array(elem, n, endian='litle') compiles a big-endian codec without complaint. Same silent-corruption class everywhere; only structs.py's Struct-class intake already validates.

**Fix.** Apply endianness-1's validate_endianness at each remaining intake boundary, always as the first touch of the parameter. Conversion functions -- pytype_to_bytes, bytes_to_pytype (inline at their single reversal test, the first use), ctype_to_bytes, bytes_to_ctype (statement at the head of the body, before the ctype-type guard, so the check also fires when no byte-swap would run). ctype_to_bits/bits_to_ctype forward endianness verbatim to those two and are covered transitively. Aggregate layer -- the public wrappers aggregate_types.to_bytes_aggregate/from_bytes_aggregate validate at entry (this is what protects the plan fast path and plan.pack/parse, whose '<' if little else '>' logic would otherwise silently pick big), and the four public-facing oracle functions in _legacy_aggregate.py validate identically: to_bytes_individual/from_bytes_individual ARE the public functions (re-exported verbatim -- one edit updates oracle and public path simultaneously, like the ctypes group's shared-function reasoning), and the oracle's to_bytes_aggregate/from_bytes_aggregate get the same one-line check as their wrappers so direct oracle calls (differential tests) and the public path stay in lockstep per the sync procedure. Schema layer (structs.py) -- Array.__init__ validates an explicit endian (None stays the 'inherit from record' sentinel) raising PlanCompileError, the established schema-compile error (a ValueError subclass), via the helper's exc parameter; the existing StructMeta check is converted to the same helper, which upgrades its message to include the offending value. The array()/Array.of sugar forwards to Array.__init__ and is covered transitively.

**Before:**

```python
# --- bytemaker/conversions/pytypes.py line 8 (import) ---
from bytemaker.utils import is_subclass_of_union

# --- pytypes.py 296-299 (pytype_to_bytes body) ---
    retval = pytype_to_bits(py_prim).to_bytes()
    if endianness == "little":
        retval = retval[::-1]
    return retval

# --- pytypes.py 341-343 (bytes_to_pytype body) ---
    if endianness == "little":
        bytes_obj = bytes_obj[::-1]
    return bits_to_pytype(BitVector(bytes_obj), pytype)

# --- bytemaker/conversions/ctypes_.py line 9 (import) ---
from bytemaker.utils import is_instance_of_union, is_subclass_of_union

# --- ctypes_.py 90-94 (head of ctype_to_bytes body) ---
    if not is_instance_of_union(ctype_obj, CType):  # type: ignore
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f"Union, and Array objects, not {type(ctype_obj)}."
        )

# --- ctypes_.py 142-146 (head of bytes_to_ctype body) ---
    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure,"
            f"Union, and Array types, not {ctype_type}."
        )

# --- bytemaker/conversions/aggregate_types.py line 43 (import) ---
from bytemaker.utils import DataClassType, is_instance_of_union, is_subclass_of_union

# --- aggregate_types.py 192-193 (head of to_bytes_aggregate body) ---
    if isinstance(units, DataClassType) and not is_instance_of_union(units, UnitType):
        plan = _get_record_plan(type(units))

# --- aggregate_types.py 229-230 (head of from_bytes_aggregate body) ---
    if is_array:
        entry_bits = count_bits_in_aggregate_type(aggregate_type)

# --- bytemaker/_legacy_aggregate.py line 39 (import) ---
from bytemaker.utils import DataClassType, is_instance_of_union, is_subclass_of_union

# --- _legacy_aggregate.py 136-138 (head of to_bytes_individual body) ---
    Function to convert a single Python primitive or ctypes object into bytes.
    """

    if is_instance_of_union(unit, CType):

# --- _legacy_aggregate.py 199-204 (head of from_bytes_individual body) ---
        endianness: The byte order of the input bytes.
            Defaults to "big".
    """

    size_in_bits = count_bits_in_unit_type(unittype)
    if len(unitbytes) * 8 != size_in_bits:

# --- _legacy_aggregate.py 355-357 (head of to_bytes_aggregate body) ---
        bytes: The bytes representation of the objects
    """
    ret_bytes = bytearray()

# --- _legacy_aggregate.py 402-404 (head of from_bytes_aggregate body) ---
            the bytes.
    """
    if is_subclass_of_union(aggregate_type, UnitType):

# --- bytemaker/structs.py 752-755 (StructMeta.__new__) ---
        if endian is None:
            endian = "big"
        if endian not in ("big", "little"):
            raise PlanCompileError(f"{name}: endian must be 'big' or 'little'")

# --- structs.py 1303-1304 (Array.__init__) ---
        self._endian_set = endian is not None
        resolved = endian if endian is not None else "big"
```

**After:**

```python
# --- bytemaker/conversions/pytypes.py line 8 ---
from bytemaker.utils import is_subclass_of_union, validate_endianness

# --- pytypes.py (pytype_to_bytes body) ---
    retval = pytype_to_bits(py_prim).to_bytes()
    if validate_endianness(endianness) == "little":
        retval = retval[::-1]
    return retval

# --- pytypes.py (bytes_to_pytype body) ---
    if validate_endianness(endianness) == "little":
        bytes_obj = bytes_obj[::-1]
    return bits_to_pytype(BitVector(bytes_obj), pytype)

# --- bytemaker/conversions/ctypes_.py line 9 ---
from bytemaker.utils import (
    is_instance_of_union,
    is_subclass_of_union,
    validate_endianness,
)

# --- ctypes_.py: `validate_endianness(endianness)` becomes the FIRST
# --- statement of the ctype_to_bytes body (the guard below is shown as in
# --- pristine source; ctypes-3 respaces its message and ctypes-1 rewrites
# --- the function tail -- neither touches this insertion point) ---
    validate_endianness(endianness)
    if not is_instance_of_union(ctype_obj, CType):  # type: ignore
        raise TypeError(
            f"ctype_to_bytes only accepts _SimpleCData, Structure,"
            f"Union, and Array objects, not {type(ctype_obj)}."
        )

# --- ctypes_.py: same one-line insertion at the head of bytes_to_ctype ---
    validate_endianness(endianness)
    if not is_subclass_of_union(ctype_type, CType):
        raise TypeError(
            f"bytes_to_ctype only accepts _SimpleCData, Structure,"
            f"Union, and Array types, not {ctype_type}."
        )

# --- bytemaker/conversions/aggregate_types.py line 43 ---
from bytemaker.utils import (
    DataClassType,
    is_instance_of_union,
    is_subclass_of_union,
    validate_endianness,
)

# --- aggregate_types.py (head of to_bytes_aggregate body) ---
    validate_endianness(endianness)
    if isinstance(units, DataClassType) and not is_instance_of_union(units, UnitType):
        plan = _get_record_plan(type(units))

# --- aggregate_types.py (head of from_bytes_aggregate body) ---
    validate_endianness(endianness)
    if is_array:
        entry_bits = count_bits_in_aggregate_type(aggregate_type)

# --- bytemaker/_legacy_aggregate.py line 39 ---
from bytemaker.utils import (
    DataClassType,
    is_instance_of_union,
    is_subclass_of_union,
    validate_endianness,
)

# --- _legacy_aggregate.py (head of to_bytes_individual body) ---
    Function to convert a single Python primitive or ctypes object into bytes.
    """
    validate_endianness(endianness)

    if is_instance_of_union(unit, CType):

# --- _legacy_aggregate.py (head of from_bytes_individual body) ---
        endianness: The byte order of the input bytes.
            Defaults to "big".
    """
    validate_endianness(endianness)

    size_in_bits = count_bits_in_unit_type(unittype)
    if len(unitbytes) * 8 != size_in_bits:

# --- _legacy_aggregate.py (head of to_bytes_aggregate body) ---
        bytes: The bytes representation of the objects
    """
    validate_endianness(endianness)
    ret_bytes = bytearray()

# --- _legacy_aggregate.py (head of from_bytes_aggregate body) ---
            the bytes.
    """
    validate_endianness(endianness)
    if is_subclass_of_union(aggregate_type, UnitType):

# --- bytemaker/structs.py: add after the typing_redirect import block
# --- (line 77) ---
from bytemaker.utils import validate_endianness

# --- structs.py (StructMeta.__new__; converted to the shared helper --
# --- message gains the offending value) ---
        if endian is None:
            endian = "big"
        validate_endianness(endian, name=f"{name}: endian", exc=PlanCompileError)

# --- structs.py (Array.__init__; new validation, schema error domain) ---
        self._endian_set = endian is not None
        resolved = (
            validate_endianness(endian, name="Array endian", exc=PlanCompileError)
            if endian is not None
            else "big"
        )
```

**Behavior change.** All outputs below are from actual runs (host byteorder: little). BEFORE (pristine repo) -- every typo accepted, with INCONSISTENT fallback directions:
  pytype_to_bytes(1, endianness='litle')                 -> b'\x00\x00\x00\x01'  (silently BIG)
  bytes_to_pytype(b'\x00\x00\x00\x01', int, 'litle')     -> 1                   (silently BIG)
  ctype_to_bytes(c_uint16(0x0102), 'bigg')               -> b'\x01\x02'          (reverse-of-HOST: 'right' by accident here, wrong for 'litle', flips meaning on a big-endian host)
  bytes_to_ctype(b'\x01\x02', c_uint16, 'litle')         -> 258 (=0x0102)        (reverse-of-host, wrong)
  to_bytes_individual(UInt16(0x0102), 'litle')           -> b'\x01\x02'          (silently BIG; contrast: the constructor path treats typos as LITTLE)
  from_bytes_individual(b'\x01\x02', UInt16, 'litle')    -> UInt16(0x0102)       (silently BIG)
  to_bytes_aggregate(Rec(UInt16(0x0102), UInt8(3)), 'bigg')  [plan fast path] -> b'\x01\x02\x03' (silently BIG)
  from_bytes_aggregate(b'\x01\x02\x03', Rec, 'bigg')     -> decoded as BIG, no error
  legacy.to_bytes_aggregate / legacy.from_bytes_aggregate with 'bigg' -> same silent acceptance (oracle path)
  Array(UInt16, 2, endian='litle').pack([0x0102, 0x0304]) -> b'\x01\x02\x03\x04' (silently BIG)
  class S(Struct, endian='litle') -> PlanCompileError: S: endian must be 'big' or 'little'  (the one already-loud site)
AFTER (patched copy) -- every intake raises immediately:
  pytype_to_bytes / bytes_to_pytype / ctype_to_bytes / bytes_to_ctype / to_bytes_individual / from_bytes_individual / to_bytes_aggregate / from_bytes_aggregate (public AND direct legacy.*) -> ValueError: endianness must be 'big' or 'little'; got 'litle' (or 'bigg')
  Array(UInt16, 2, endian='litle') -> PlanCompileError: Array endian must be 'big' or 'little'; got 'litle'
  class S(Struct, endian='litle') -> PlanCompileError: S: endian must be 'big' or 'little'; got 'litle'
Happy paths byte-identical before/after: pytype_to_bytes(1, 'little') == b'\x01\x00\x00\x00'; ctype_to_bytes(c_uint16(0x0102), 'big') == b'\x01\x02'; to_bytes_aggregate(Rec, 'little') == b'\x02\x01\x03' with round-trip and legacy-vs-public parity True; Array(UInt16, 2, endian='little').pack -> b'\x02\x01\x04\x03'; Array(UInt16, 2) (endian=None, inherit-unset) -> b'\x01\x02\x03\x04'. Full suite against the patched copy: 854 passed (includes test/plan_fastpath_test.py oracle-parity differentials and the endianness='little' cases in aggregate_types_test.py/ctypes_test.py).

**Tests to add.** test/pytypes_test.py: pytest.raises(ValueError, match="endianness must be 'big' or 'little'; got 'litle'") for pytype_to_bytes(1, endianness='litle') and bytes_to_pytype(b'\x00'*4, int, endianness='litle'); happy 'little' round-trip unchanged. test/ctypes_test.py: same raises for ctype_to_bytes(ctypes.c_uint16(1), endianness='bigg') and bytes_to_ctype(b'\x00\x01', ctypes.c_uint16, endianness='litle'); note the check fires even for native-order requests (no reversal needed) -- intake validation, not use validation. test/aggregate_types_test.py: raises for to_bytes_individual(UInt16(1), endianness='litle'), from_bytes_individual(b'\x00\x01', UInt16, endianness='litle'), to_bytes_aggregate(rec, endianness='bigg') for BOTH a fast-path-eligible dataclass (all BitType fields) and a legacy-fallback shape (e.g. a ctypes field), and from_bytes_aggregate(..., endianness='bigg'). test/plan_fastpath_test.py: parity of the failure -- both aggregate_types.to_bytes_aggregate and _legacy_aggregate.to_bytes_aggregate raise the identical ValueError for a typo (message equality), keeping oracle/fast-path behavior in lockstep. test/structs_test.py: pytest.raises(PlanCompileError, match="Array endian must be 'big' or 'little'; got 'litle'") for Array(UInt16, 2, endian='litle') and for array(UInt16, 2, endian='litle') inside a Struct body; pytest.raises(PlanCompileError, match="endian must be 'big' or 'little'; got") for class S(Struct, endian='litle'); Array(UInt16, 2) with endian=None still compiles and inherits the record's byte order as a field.

**Risks / sync obligations / review notes.** Depends on endianness-1 (the helper) -- apply after it. Behavior change is reject-only: calls that silently produced wrong-direction bytes now raise; no repo code or test passes a non-canonical string (854/854). ORACLE SYNC (deliberate, per the legacy-aggregate procedure): _legacy_aggregate.py is edited -- one import plus four one-line entry validations. to_bytes_individual/from_bytes_individual are re-exported verbatim by aggregate_types, so oracle and public path are literally the same function (one edit, both paths); to_bytes_aggregate/from_bytes_aggregate get the identical check in both modules so a direct oracle call and the public wrapper raise the same error (parity tests green; valid-input bytes untouched -- differential suite passed). Double validation on delegating paths (wrapper -> oracle -> converter) costs a tuple membership test each, negligible. CROSS-GROUP: ctypes-1/2/3 rewrite reverse_ctype_endianness/_reversed_ctype_bytes and the tails of ctype_to_bytes/bytes_to_ctype -- this fix only inserts one statement at each function HEAD, which their rewrite does not touch; apply in either order (if ctypes-3 lands first, the guard message below the insertion point has a space in ' Union' -- insertion unchanged). pytypes-1/2/3 touch ConversionInfo methods, the char registration, and the bytes_to_pytype DOCSTRING; this fix edits the bytes_to_pytype BODY and the import line -- no overlapping lines, but merge the import edit if both land. StructMeta's error message gains '; got {value!r}' -- no test matches the old text (grepped test/). plans.py Plan.parse/pack and _pack_all_plain_numbers keep their == 'little' comparisons but are only reachable through validated entries (private module boundary; validating there would be validate-at-use). BitVector backends: untouched and none needed (see endianness-1 risks). Re-run: full suite, especially test/plan_fastpath_test.py, test/aggregate_types_test.py, test/ctypes_test.py, test/structs_test.py. REVIEWER NOTES: (a) pytypes validates at first-use rather than function head, so a pytypes-3 char ValueError can mask the endianness error when both inputs are bad - harmless but slightly untidy ordering; (b) if applied in reverse order with ctypes-3, the literal-patch anchors shift - apply endianness after the ctypes rewrite or re-anchor.

<sub>covers: `ux|bytemaker/conversions/pytypes.py|281-299, 324-343`</sub>

---
