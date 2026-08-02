# Correctness bugs

> **Status: discovery pass, partially re-verified.** These findings come from the bug/inconsistency sweep of a run cut short by a session limit before its own adversarial-verification stage ran. Many findings embed the finder's own repro. Items marked **✓ Reproduced** or **Confirmed by inspection** were independently re-checked here; the rest are strong leads to confirm before acting. See [README.md](README.md).

Logic errors, boundary/edge-case failures, cross-implementation divergences, and contracts that lie. Ordered by severity then confidence.

_28 findings — 11 high, 10 medium, 7 low._

---

## 1. NarrowingWarning never fires for struct-packed widths (UInt/SInt 8/16/32/64)

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/bittype.py:578-594`](../bytemaker/bittypes/bittype.py#L578)

**What.** The `StructPackedBitType.value` setter performs C-style narrowing (mask for unsigned, wrap for signed) but never calls `_warn_narrowing`, so `NarrowingConfig.warn` / the `BYTEMAKER_WARN_NARROWING` env var produce no warning for the standard byte-aligned widths (UInt8/16/32/64, SInt8/16/32/64) — precisely the types users reach for most. The `-Wconversion` knob silently does nothing on the common case. Only the odd/large widths (UInt7, UInt128, SInt7, etc.), whose setters live in int.py and do call `_warn_narrowing`, actually warn. The module docstrings advertise the opposite: `NarrowingConfig` (lines 39-46) states the warning fires for "Int/UInt/SInt value setters", and `NarrowingWarning` (lines 27-36) presents it as the reliable opt-in analog of `-Wconversion`. For a struct-packed box the value setter used at runtime is `StructPackedBitType.value` (confirmed: `SInt8.value.fset.__qualname__ == 'StructPackedBitType.value'`), which shadows the warning-emitting int.py setters via MRO. This is a correctness bug in the narrowing-diagnostics feature and a doc that actively misleads.

**Evidence.**

Setter that narrows but omits the warn call:
```
@value.setter
def value(self, value: T):
    if not self.skip_struct_packing:
        if self.py_type is int and isinstance(value, int):
            n = self.num_bits
            if self.packing_format_letter.islower():
                value = ((value + (1 << (n - 1))) % (1 << n)) - (1 << (n - 1))
            else:
                value &= (1 << n) - 1
        self._bits = FixedLengthBitVector(struct.pack(self.packing_format, value))
```
Contrast int.py UInt setter, which does warn:
```
masked = value & ((1 << self.num_bits) - 1)
if NarrowingConfig.warn and masked != value:
    _warn_narrowing(value, masked, type(self).__name__)
```
Repro (NarrowingConfig.warn = True, warnings recorded):
```
UInt8(300).value = 44   | warnings: 0   (struct-packed)
SInt8(200).value = -56  | warnings: 0   (struct-packed)
UInt16(70000) = 4464    | warnings: 0   (struct-packed)
SInt16(40000) = -25536  | warnings: 0   (struct-packed)
UInt7(200).value = 72   | warnings: 1   (NOT struct-packed)
SInt7(200).value = -56  | warnings: 1   (NOT struct-packed)
```
MRO confirmation: `SInt8.__mro__` = [SInt8, StructPackedBitType, SInt, Int, BitType, ...] and `SInt8.value.fset.__qualname__ == 'StructPackedBitType.value'`.

**Suggestion.** In the `StructPackedBitType.value` setter, after computing the narrowed `value` in each branch, mirror int.py: capture the original, and if `NarrowingConfig.warn and narrowed != original` call `_warn_narrowing(original, narrowed, type(self).__name__)`. (Requires importing `NarrowingConfig` and `_warn_narrowing` here, or refactoring the narrowing+warn into a shared helper the int.py setters and this setter both call so the two paths cannot drift.)

**✓ Reproduced (repro run):** with `NarrowingConfig.warn=True`, `UInt8(300)`->44 and `SInt8(200)`->-56 emit **0** warnings -- `StructPackedBitType.value` narrows without calling `_warn_narrowing`, so the diagnostic never fires for the standard C widths.

---

## 2. value getter never decodes zero/inf/NaN exponent encodings (round-trip broken)

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:81-111`](../bytemaker/bittypes/float.py#L81)

**What.** The `value` property unconditionally applies the normal-number formula `magnitude = 2**unbiased_exponent * (1 + mantissa)`. It never special-cases the all-zero exponent (which IEEE uses for zero and subnormals) or the all-ones exponent (inf/NaN). Consequently every pure-Python Float subclass (BFloat16, TF19, FP24, or any specialize() without a packing_format_letter) fails to round-trip these values: an all-zero bit pattern decodes to a tiny subnormal instead of 0.0, and the inf bit pattern written by to_binstring decodes to a finite number. This is a genuine data-corruption round-trip failure, not just cosmetic. (Also present in REF, but a real user bug.)

**Evidence.**

getter always does:
    magnitude: float = 2**unbiased_exponent * (1 + mantissa)
    result = sign * magnitude
Repro:
  >>> BFloat16(0.0).bits -> '00000000 00000000'
  >>> BFloat16(0.0).value -> 5.877471754111438e-39   # expected 0.0
  >>> BFloat16(float('inf')).value -> 3.402823669209385e+38  # expected inf
to_binstring writes the correct special patterns but the getter cannot read them back.

**Suggestion.** Before applying the normal formula, branch on the stored biased exponent: all-zero exponent -> return signed 0.0 when mantissa==0 else a subnormal (2**(1-bias) * mantissa, no implicit 1); all-ones exponent -> return signed inf when mantissa==0 else NaN. Make the getter the exact inverse of to_binstring's special cases.

**✓ Reproduced (repro run):** an all-zero-bit non-struct Float (e=6, m=9) decodes via `.value` to `4.656612873077393e-10` instead of `0.0`; the getter always applies the implicit leading 1 with no zero/inf/NaN case. Struct-packed Float16/32/64 are unaffected (StructPackedBitType.value overrides this getter).

---

## 3. to_binstring(NaN) raises ValueError instead of encoding NaN

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:147`](../bytemaker/bittypes/float.py#L147)

**What.** The NaN guard `if num == float("NaN")` can never be true because NaN compares unequal to everything, including itself. NaN therefore falls through to `integral_part = int(abs_num)` at line 191, which raises `ValueError: cannot convert float NaN to integer`. Any attempt to store NaN into a pure-Python Float (e.g. BFloat16(float('nan'))) crashes. (Present in REF too, but a real user bug.)

**Evidence.**

if num == float("NaN"):   # always False: NaN != NaN
        return "0" + "1" * (num_exponent_bits + 1) + "0" * (num_mantissa_bits - 1)
Repro:
  >>> BFloat16(float('nan'))
  ValueError: cannot convert float NaN to integer  (from int(abs_num) at line 191)

**Suggestion.** Detect NaN with `num != num` (or math.isnan(num)) and place that check before the int() conversion. Note the intended NaN pattern also writes a leading exponent+1 bits which for a 1-bit-mantissa/edge format could underflow the mantissa slice; validate widths too.

**✓ Reproduced (repro run):** `Float.to_binstring(float("nan"),8,23)` -> `ValueError: cannot convert float NaN to integer`. The NaN guard on line 147 (`num == float("NaN")`) is itself dead code, since NaN never equals NaN.

---

## 4. to_binstring overflows the field width for large magnitudes (produces oversized bitstring)

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:175-186, 200`](../bytemaker/bittypes/float.py#L175)

**What.** When a value's exponent exceeds the representable range, `biased_exponent` exceeds 2**num_exponent_bits - 1 but `int_to_binary` only zfills (never truncates) and there is no overflow-to-infinity handling. `assemble_bits` then returns a string longer than num_bits, which the BitVector rejects. A user storing a finite-but-too-large value gets a confusing 'Expected N bits, got N+1' error instead of a clean overflow to infinity. (Present in REF too.)

**Evidence.**

def int_to_binary(integer: int, bits: int) -> str:
        binary = bin(integer).replace("0b", "")
        return binary.zfill(bits)   # zfill never shrinks; no cap at `bits`
Repro:
  >>> Float.to_binstring(1e40, 8, 7) -> '01000000111101011' (len 17, expected 16)
  >>> BFloat16(1e40) -> ValueError: Expected 16 bits, got 17

**Suggestion.** After computing biased_exponent, detect biased_exponent >= (2**num_exponent_bits - 1) and return the signed infinity encoding (all-ones exponent, zero mantissa) instead of assembling an oversized string.

**✓ Reproduced (repro run):** `Float.to_binstring(1e300,8,23)` returns a **35-bit** string for a 1+8+23=32-bit field. `int_to_binary` zero-fills but never truncates/clamps the exponent field.

---

## 5. to_binstring crashes on subnormal/underflow magnitudes ('substring not found')

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:165-167, 195-197`](../bytemaker/bittypes/float.py#L165)

**What.** For a nonzero magnitude too small to have any 1 bit within the computed integral+fractional window (i.e. values in or below the subnormal range), `combined` is all zeros and `combined.index("1")` in normalize() raises `ValueError: substring not found`. Storing a small value such as 1e-39 into a BFloat16 crashes with a cryptic error instead of producing a subnormal or flushing to zero. (Present in REF too.)

**Evidence.**

def normalize(binary_int, binary_frac):
        combined = binary_int + binary_frac
        first_one = combined.index("1")   # ValueError if no '1'
Repro:
  >>> Float.to_binstring(1e-40, 8, 7) -> ValueError: substring not found
  >>> BFloat16(1e-39)                 -> ValueError: substring not found

**Suggestion.** Guard normalize(): if combined contains no '1', either encode a subnormal (all-zero exponent, mantissa from the leading fractional bits) or flush to signed zero, matching what the value getter should decode.

**✓ Reproduced (repro run):** `Float.to_binstring(1e-40,8,23)` -> `ValueError: substring not found` (`normalize()` calls `combined.index("1")` on an all-zero string).

---

## 6. Empty (non-None) codepoint_changes crashes every encode and decode with AttributeError

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/string.py:248-264`](../bytemaker/bittypes/string.py#L248)

**What.** _substitute_forward / _substitute_reverse decide whether to substitute with `if codepoint_changes is not None`, but the compiled regex is built by `_codepoint_change_regex` / `_reverse_codepoint_change_regex`, which return None when the mapping is falsy (`if cls.codepoint_changes:` on line 165/190 treats an empty dict as no-op). So when `_codepoint_changes` is an EMPTY-but-not-None mapping (a natural way to spell "no substitutions", or the result of `codepoint_changes = {}`), the substitute helpers see a non-None mapping and call `None.sub(...)`, crashing. Both the encode path (value setter -> _encode_padded -> _substitute_reverse) and the decode path (value getter -> _decode_wire / sub-byte -> _substitute_forward) are affected, so the field becomes completely unusable. The None-vs-falsy mismatch is the root cause; the two sides must agree (both should treat empty as no-op).

**Evidence.**

Repro (current tree):
```
S = String.of(nbytes=4, encoding='ascii', pad=0x00)
S._codepoint_changes = FrozenDict({})
S(value='ab')
# AttributeError: 'NoneType' object has no attribute 'sub'
#   at perform_codepoint_substitution -> changes_regex.sub(...)
```
Decode path also crashes: `s.value` on an existing instance -> `_decode_wire` -> `_substitute_forward` -> same AttributeError. Code: `_substitute_forward` uses `if codepoint_changes is not None:` (line 251) while `_codepoint_change_regex` guards with `if cls.codepoint_changes:` (line 165) and returns None for an empty mapping.

**Suggestion.** Guard the substitute helpers on truthiness, not identity: `if codepoint_changes:` (and `if reverse_changes:`), or return early when the regex is None. This makes an empty mapping a genuine no-op instead of a crash. (Pre-existing since the reference implementation used the same `is not None` pattern in the value getter/setter; the new _substitute_* refactor carried it forward — note observations pass if relevant.)

---

## 7. bitarray backend rejects float bit values (1.0/0.0) in append/insert/remove/extend that both reference impls accept

**Severity:** high · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1036, 1049, 1061, 1101`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1036)

**What.** In the ACTIVE production backend (bitvector.py imports bitvector_with_bitarray_speedup when bitarray is installed), append/insert/remove/extend forward the raw value straight to the bitarray superclass (super().append(value), super().insert(index, value), super().remove(value), super().extend(values)) without routing through _coerce_bit. The two reference implementations (bitvector_native.py and bitvector_speedup.py, the latter being the fuzz-tested twin of the native oracle) both call _coerce_bit, which is documented to accept 'a 0 or 1 (or equal to one of them, e.g. booleans)' and therefore accepts 1.0/0.0. So the same call succeeds on the oracle and silently changes state there, but raises TypeError in the shipped backend, and the two vectors end up with different contents. The differential fuzz test only compares native against speedup, never against the bitarray backend, so this gap is completely untested. It is a real, reachable behavior split between shipped implementations of the same public API.

**Evidence.**

Repro (native/speedup vs the ACTIVE bitarray backend):
  append(0.0 )  native=('ok','01010') speedup=('ok','01010') bitarray=('exc','TypeError')
  append(1.0 )  native=('ok','01011') speedup=('ok','01011') bitarray=('exc','TypeError')
  insert(0.0)   native ok, speedup ok, bitarray TypeError: 'float' object cannot be interpreted as an integer
  remove(1.0)   native '101', speedup '101', bitarray TypeError
  extend([1.0,0.0]) native='110' speedup='110' bitarray=TypeError
The backend code has no coercion:
    def append(self, value: int) -> None:
        super().append(value)
    def insert(self, index: int, value: int) -> None:
        super().insert(index, value)
    def remove(self, value: int) -> None:
        super().remove(value)
    def extend(self, values): ...; super().extend(values)
Compare bitvector_native.py append: `self._bits.append(_coerce_bit(value))`.

**Suggestion.** Route the bit value through _coerce_bit before delegating: append -> super().append(_coerce_bit(value)); insert -> super().insert(index, _coerce_bit(value)); remove -> super().remove(_coerce_bit(value)); and in extend, when the iterable is not a BitVector, coerce each element (mirroring the native/speedup path). Import/define _coerce_bit in this module (it currently lacks it).

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 8. FixedLengthBitVector slice-setitem guard uses len(value) instead of bit-length, both false-blocking valid writes and false-allowing width changes

**Severity:** high · **Confidence:** high · [`bytemaker/bitvector/fixed.py:79-88`](../bytemaker/bitvector/fixed.py#L79)

**What.** The width-invariance guard in FixedLengthBitVector.__setitem__ compares the slice span to `len(value)`, the element count of the RAW source, rather than the number of bits the value contributes once coerced to a BitVector. For any non-BitVector BitsConstructible whose element count differs from its bit length (str like '0b..'/'0x..'/'0o..', bytes, bytearray, memoryview), the two disagree. This produces two opposite failures: (1) FALSE ALLOW that actually breaks the invariant this class exists to protect -- e.g. `v[0:3] = '0x0'` passes because len('0x0')==3==span, but BitVector('0x0') is 4 bits, so the base setitem resizes the 'fixed' vector from 8 to 9 bits; (2) FALSE BLOCK of legitimate length-preserving writes -- e.g. `v[0:8] = bytes([0xFF])` (8 bits into an 8-bit slice) and `v[0:2] = '0b11'` (2 bits into a 2-bit slice) both raise ValueError even though the base BitVector accepts them. Since this class backs BitType box storage (per the module docstring, guarding e.g. a 6-bit UInt6 against a width change), the false-allow case is a real silent-corruption path. fixed.py is new (did not exist in the 4-week-ago reference), so this is a new bug.

**Evidence.**

Guard code:
```
79  if isinstance(key, slice) and not isinstance(value, int):
80      span = len(range(*key.indices(len(self))))
81      try:
82          vlen = len(value)          # <-- element count of RAW source, not bit length
83      except TypeError:
84          value = BitVector(value)
85          vlen = len(value)
86      if vlen != span:
87          raise self._length_violation()
88  super().__setitem__(key, value)
```
Repro (active bitarray backend; identical on pure-Python backend):
```
v = F('0b'+'0'*8)            # 8-bit fixed
v[0:3] = '0x0'               # len('0x0')==3==span but BitVector('0x0')==4 bits
# -> len(v) == 9  (invariant broken; guard bypassed)

v2 = F(bytes([0,0]))         # 16-bit fixed
v2[0:8] = bytes([0xFF])      # 8 bits into 8-bit slice = length-preserving
# -> WRONGLY raises ValueError (len(bytes([0xFF]))==1 != span 8)

v3 = F('0b11110000')
v3[0:2] = '0b11'             # 2 bits into 2-bit slice
# -> WRONGLY raises ValueError
```
Base BitVector accepts all three; only FixedLengthBitVector mishandles them.

**Suggestion.** Compare against the coerced bit length, not the raw source length. Normalize the value once up front, e.g. `bv = value if isinstance(value, BitVector) else BitVector(value); if len(bv) != span: raise self._length_violation(); super().__setitem__(key, bv)`. (An int value still short-circuits earlier as length-preserving.) This both admits valid length-preserving writes and closes the resize hole.

**Confirmed by inspection:** the slice-setitem guard compares `len(value)` (element/byte count) against the bit span, so a `bytes`/`bytearray` value is mis-measured -- false-blocking valid writes and mis-sizing others.

---

## 9. ctype_to_bytes mutates the caller's ctypes Structure in place, silently corrupting it

**Severity:** high · **Confidence:** high · [`bytemaker/conversions/ctypes_.py:63-69, 96-97`](../bytemaker/conversions/ctypes_.py#L63)

**What.** reverse_ctype_endianness() reverses a ctypes Structure by writing each field back onto the SAME object via setattr (line 69) and then returns that same object. ctype_to_bytes() calls it whenever endianness != sys.byteorder (line 96-97). Because the input object is reassigned to the return value (ctype_obj = reverse_ctype_endianness(ctype_obj)) but that return value IS the caller's original object, the caller's Structure is left byte-swapped after the call. So a benign-looking serialization call like ctype_to_bytes(pt, 'big') on a little-endian machine silently corrupts pt (its field values change). The bug is platform-dependent: on a little-endian host it triggers for endianness='big'; on a big-endian host for endianness='little'. It also propagates through the aggregate path (to_bytes_aggregate on a dataclass with a ctypes Structure field corrupts that field) and through ctype_to_bits (which calls ctype_to_bytes). _SimpleCData scalars are NOT affected because reverse_bytes_unit returns a fresh object via from_buffer_copy; only Structure (and Array of Structure) fields are mutated. Note: this file is byte-for-byte identical to the 4-weeks-ago reference (only CRLF vs LF differs), so it is a pre-existing bug rather than a July regression, and it is distinct from the ctypes-bitfield NotImplementedError already noted in observations/06 section G (which is about 3-tuple bitfield _fields_, not in-place mutation).

**Evidence.**

reverse_ctype_endianness (Structure branch):
    for field_name, field_type in ctype_instance_fields:
        field_value = getattr(ctype_instance, field_name)
        simple_c_data = field_type(field_value)
        assert isinstance(simple_c_data, _SimpleCData)
        reversed_unit = reverse_ctype_endianness(simple_c_data)
        setattr(ctype_instance, field_name, reversed_unit)   # mutates caller's object
    return ctype_instance   # same object returned

ctype_to_bytes:
    if endianness != sys.byteorder:
        ctype_obj = reverse_ctype_endianness(ctype_obj)   # rebinds to the SAME object
    return bytes(ctype_obj)

Repro (little-endian host):
    sys.byteorder = little
    class Pt(ctypes.Structure): _fields_ = [('x', c_uint16), ('y', c_uint16)]
    p = Pt(0x0102, 0x0304)
    before: x=0x0102 y=0x0304  raw=02010403
    out = ctype_to_bytes(p, 'big')   # returned bytes: 01020304 (correct)
    after : x=0x0201 y=0x0403  raw=01020304   <-- caller object CORRUPTED

Also via the aggregate path:
    Structure field after to_bytes_aggregate(record, 'big'): x = 0x201  (was 0x102)

**Suggestion.** Reverse a copy, not the original: in reverse_ctype_endianness, for the Structure/Array branches operate on a deep copy of ctype_instance (e.g. type(ctype_instance).from_buffer_copy(bytes(ctype_instance)) then mutate/return the copy), or have ctype_to_bytes take a from_buffer_copy snapshot before reversing. The _SimpleCData branch already does this correctly; the Structure/Array branches should be made non-mutating to match, so serialization never has side effects on the caller's object.

**✓ Reproduced (repro run):** a 2-field `ctypes.Structure` `(a,b)=(258,772)` became `(513,1027)` in the caller after `ctype_to_bytes(s,"big")` -- `reverse_ctype_endianness` setattr-mutates the passed instance (line 69).

---

## 10. BoundBits width-preserving mutators (setall/invert/sort) silently no-op instead of writing through

**Severity:** high · **Confidence:** high · [`bytemaker/structs.py:1069-1073`](../bytemaker/structs.py#L1069)

**What.** BoundBits (minted by `struct.sizedview.<field>.bits`) is documented as a live handle where "Width-preserving mutation writes through" and "mutators are defined explicitly below so their results write back through the width-validating store". Only a hand-picked set of mutators is overridden (__setitem__, __delitem__, __iadd__, append, extend, insert, pop, remove, clear, reverse). Every OTHER BitVector mutator falls through __getattr__, which returns `getattr(self._cur(), name)` where `_cur()` builds a FRESH throwaway BitVector from the slot. Calling such a mutator therefore mutates the throwaway and silently drops the write to the struct. BitVector's in-place, width-preserving mutators setall/invert/sort are exactly this case: they should write through (like the overridden `reverse`) but instead silently do nothing. This is silent data loss in a documented, public feature.

**Evidence.**

structs.py __getattr__ (readers only):
    def __getattr__(self, name):
        # Reader methods (to01, hex, to_bytes, count, ...) delegate to a
        # fresh derivation; mutators are defined explicitly below ...
        return getattr(self._cur(), name)
and the class docstring: "Width-preserving mutation writes through".

Repro (python -c):
  setall   before=00110011 after=00110011  -> NO-OP (bug)
  invert   before=00110011 after=00110011  -> NO-OP (bug)
  sort     before=00110011 after=00110011  -> NO-OP (bug)
Contrast, the overridden `reverse` DOES write through:
  after reverse value 11110000
BitVector confirms these are in-place width-preserving mutators (return None): `setall ret None bv now 1111`, `invert ret None bv2 now 0011`, `sort ret None bv3 now 0011`.

**Suggestion.** Treat unknown attribute access uniformly against a known mutator allow/deny set instead of returning the throwaway's bound method verbatim. Either (a) add explicit RMW overrides for the remaining width-preserving in-place mutators (setall, invert, sort) that call `_write(b)` after mutating, mirroring `reverse`; or (b) in __getattr__, wrap any callable whose name is a known in-place mutator so it performs read-modify-write-back, and let width-changing ones raise at _write. At minimum, do not silently return a bound method that mutates a copy the caller can never see.

---

## 11. is_instance_of_union crashes on empty iterables and mis-matches non-empty ones

**Severity:** high · **Confidence:** high · [`bytemaker/utils.py:133-135`](../bytemaker/utils.py#L133)

**What.** The single-arg iterable-generic branch is logically inverted and unsafe. `return bool(obj) or is_instance_of_union(next(iter(obj)), type_args[0])` is meant to accept an iterable if it is empty OR its first element matches the element type. But (a) for a NON-empty iterable `bool(obj)` is True, so the function returns True without ever checking the element type -- so e.g. a list of strings is reported as an instance of `List[int]`; and (b) for an EMPTY iterable `bool(obj)` is False, so evaluation proceeds to `next(iter(obj))`, which raises `StopIteration`. Because the caller on line 132 wraps this in an `any(...)` generator, PEP 479 turns the StopIteration into a `RuntimeError`. This is reachable from the public API: `BitsConstructible` (used by `BitVector.__contains__` etc.) contains `Iterable[Union[Literal[0,1], int]]`, so `[] in some_bitvector` hits this path. Unchanged from the 4-week reference, but the observations only mention this helper for its call count, not this defect -- so it is a new finding.

**Evidence.**

utils.py line 133-135:
```
        elif isinstance(obj, type_origin):
            if len(type_args) == 1 and isinstance(obj, Iterable):
                return bool(obj) or is_instance_of_union(next(iter(obj)), type_args[0])
```
Repro 1 (public API crash):
```
>>> from bytemaker.bitvector import BitVector
>>> bv = BitVector([1,0,1,1])
>>> [] in bv
RuntimeError: generator raised StopIteration
```
Repro 2 (false positive + crash directly):
```
>>> from bytemaker.utils import is_instance_of_union
>>> from typing import List
>>> is_instance_of_union(['x','y'], List[int])   # wrong element type
True
>>> is_instance_of_union([], List[int])
StopIteration
```

**Suggestion.** Handle emptiness explicitly and check the element only when present, e.g. `if not obj: return True` (or False, per intended semantics) then `return all(is_instance_of_union(el, type_args[0]) for el in obj)` -- or at minimum guard the `next(iter(obj))` so an empty iterable does not raise, and check the element type instead of short-circuiting on `bool(obj)`.

**✓ Reproduced (repro run):** `is_instance_of_union([], List[int])` raises `StopIteration`; `is_instance_of_union(["x"], List[int])` returns `True` (should be `False`). `bool(obj) or ...` short-circuits on any non-empty iterable and `next(iter(obj))` explodes on an empty one.

---

## 12. count_bits_in_unit_type returns None for unsupported types, yielding an opaque TypeError downstream

**Severity:** medium · **Confidence:** high · [`bytemaker/_legacy_aggregate.py:68-88`](../bytemaker/_legacy_aggregate.py#L68)

**What.** `count_bits_in_unit_type` is annotated `-> int` and has no final `else: raise`. When `unit_type` is none of CType/BitType/PyType/DataClassType, all `if`/`elif` branches are skipped and the function implicitly returns `None`. Callers immediately do arithmetic on the result (e.g. `count_bytes_in_unit_type` computes `(count_bits_in_unit_type(unit_type) + 7) // 8`, and `from_bytes_aggregate` line 421 does the same), so a user who passes an unsupported field type gets the cryptic `TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'` instead of a clear 'unsupported type' error. `count_bits_in_aggregate_type` (line 99-103) has the same latent issue when summing an unknown field type. The `-> int` contract is also violated.

**Evidence.**

_legacy_aggregate.py lines 82-88 (no trailing else/raise):
```
    elif is_subclass_of_union(unit_type, DataClassType):
        size_in_bits = 0
        field_types = resolve_field_types(unit_type)
        for field in dataclasses.fields(unit_type):
            size_in_bits += count_bits_in_unit_type(field_types[field.name])
        return size_in_bits
```
Repro:
```
>>> from bytemaker._legacy_aggregate import count_bits_in_unit_type, count_bytes_in_unit_type
>>> class Foo: pass
>>> count_bits_in_unit_type(Foo)
None
>>> count_bytes_in_unit_type(Foo)
TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'
```

**Suggestion.** Add a final `else: raise TypeError(f"Cannot count bits in {unit_type}: not a CType, BitType, PyType, or dataclass")` (mirroring the error style already used in to_bits_individual/from_bits_individual) so unsupported types fail with a clear message rather than propagating None into arithmetic.

---

## 13. Narrowing warning never fires for the standard C-width int types (SInt8/16/32/64, UInt8/16/32/64)

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/bittype.py:578-594`](../bytemaker/bittypes/bittype.py#L578)

**What.** NarrowingConfig's docstring promises that "integer stores that change the assigned value — Struct field descriptors and Int/UInt/SInt value setters — emit a NarrowingWarning". The Int/UInt/SInt value setters in int.py (UInt.value.setter L794-796, SInt.value.setter L606-609) do call _warn_narrowing. But every fixed-width power-of-two type (SInt8/16/32/64, UInt8/16/32/64) is a StructPackedBitType, so its value setter resolves to StructPackedBitType.value.setter, which performs its OWN silent wrap/mask (L588-591) and never calls _warn_narrowing. Result: the -Wconversion feature is a no-op for exactly the widths users reach for most, while it works for the odd widths (UInt3, SInt5, ...). This is a documented-vs-actual divergence, not intended behavior.

**Evidence.**

StructPackedBitType.value.setter wraps but never warns:
    if self.packing_format_letter.islower():
        value = ((value + (1 << (n - 1))) % (1 << n)) - (1 << (n - 1))
    else:
        value &= (1 << n) - 1
    self._bits = FixedLengthBitVector(struct.pack(self.packing_format, value))

Repro (NarrowingConfig.warn = True):
  SInt8 200 -> warnings: 0
  SInt16 40000 -> warnings: 0
  SInt32 2147483648 -> warnings: 0
  UInt16 70000 -> warnings: 0
  UInt64 18446744073709551616 -> warnings: 0
  SInt3 4 -> warnings: 1   (only the non-struct-packed width warns)

**Suggestion.** In StructPackedBitType.value.setter, after computing the wrapped/masked value, mirror the int.py setters: if NarrowingConfig.warn and the wrapped value != the original value, call _warn_narrowing(original, wrapped, type(self).__name__). Alternatively route the packed setter's narrowing through the same helper the int.py setters use so the warning is emitted in one place.

**✓ Reproduced (repro run):** with `NarrowingConfig.warn=True`, `UInt8(300)`->44 and `SInt8(200)`->-56 emit **0** warnings -- `StructPackedBitType.value` narrows without calling `_warn_narrowing`, so the diagnostic never fires for the standard C widths.

---

## 14. to_binstring drops the sign of negative zero

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:141-142`](../bytemaker/bittypes/float.py#L141)

**What.** The `if num == 0` branch returns an all-zero string (sign bit 0) for both +0.0 and -0.0, because -0.0 == 0.0 is True and the branch fires before the sign bit is computed. IEEE distinguishes -0.0 (sign bit set); struct.pack('>f', -0.0) yields a set sign bit. bytemaker silently discards it. (Present in REF too.)

**Evidence.**

if num == 0:
        return "0" + "0" * (num_exponent_bits + num_mantissa_bits)
Repro:
  >>> Float.to_binstring(-0.0, 8, 7) -> '0000000000000000'
  >>> struct.pack('>f', -0.0) top16 -> '1000000000000000'

**Suggestion.** Compute the sign via math.copysign(1.0, num) (or `str(num)[0]=='-'`) and emit that sign bit for the zero case: e.g. `(1 if math.copysign(1, num) < 0 else 0)` followed by all-zero exponent and mantissa.

**✓ Reproduced (repro run):** `Float.to_binstring(-0.0,8,23)[0] == "0"` -> negative zero encodes as +0.0.

---

## 15. Codepoint change mapping a character to the empty string corrupts encoding (match-everywhere regex)

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/string.py:187-210, 257-264`](../bytemaker/bittypes/string.py#L187)

**What.** When a codepoint change maps a character to the empty string (a plausible "delete this codepoint" rule, e.g. dropping a control character on decode), the reverse mapping becomes `{'': key}` and `_reverse_codepoint_change_regex` compiles `re.escape('')` == '' into the alternation. An empty alternative matches the zero-width position between every character, so `changes_regex.sub` inserts the mapped key at every position instead of doing nothing. The value is silently corrupted rather than raising. The forward direction has the symmetric flaw if a KEY is empty. This bypasses the leftmost-longest ordering entirely because the empty alternative wins at position 0.

**Evidence.**

Repro (current tree):
```
S = String.of(nbytes=8, encoding='ascii', pad=0x00)
S._codepoint_changes = FrozenDict({'A':''})
S._reverse_codepoint_changes  -> {'': 'A'}
S._reverse_codepoint_change_regex.pattern -> ''   # empty pattern
S._substitute_reverse('xy')  -> 'AxAyA'           # 2 chars became 5
```
The regex is built with no filtering of empty keys/values: `re.compile('|'.join(re.escape(key) for key in sorted(cls.codepoint_changes.values(), key=len, reverse=True)))` (lines 200-208).

**Suggestion.** Reject empty keys/values at the codepoint_changes setter (they have no well-defined substitution semantics), or filter zero-length alternatives out of the compiled pattern and handle deletions explicitly. At minimum, raise a clear error rather than silently producing an every-position match.

---

## 16. String.of accepts nbytes not divisible by bytes_per_char, yielding a field that can't decode its own output

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/string.py:399-437`](../bytemaker/bittypes/string.py#L399)

**What.** of() validates that bytes_per_char is a positive int and that nbytes is a positive int, but never checks that `nbytes % bytes_per_char == 0`. _decode_wire strips pad and cuts terminators in whole `unit = bytes_per_char` steps, so a field whose byte width is not a multiple of the character width can be left with a partial trailing unit that then fails to decode. The field packs fine but raises on read-back, breaking the pack/parse round-trip invariant. It also interacts badly with truncate=True: a value can pack successfully yet be un-decodable.

**Evidence.**

Repro 1 (mis-sized field, current tree):
```
S = String.of(nbytes=5, encoding='utf-16-le', bytes_per_char=2, strip=True)  # accepted, num_bits=40
s = S(value='hi')   # packs: 68 00 69 00 00
s.value             # UnicodeDecodeError: 'utf-16-le' can't decode byte 0x69 in position 2
```
(strip removes ONE 2-byte unit -> leaves `68 00 69`, 3 bytes, which is not valid UTF-16.)
Repro 2 (truncate produces un-decodable output):
```
tbl = {b'\x02\x03':'X', b'\x04\x05':'Y'}   # bytes_per_char derived = 2
S = String.of(nbytes=1, encoding=tbl, truncate=True, pad=0x00)  # accepted, nbytes=1 not a multiple of 2
s = S(value='XY')   # truncates to b'' then pads -> b'\x00'
s.value             # ValueError: no table entry decodes byte 0x00 (position 0)
```

**Suggestion.** In of(), after resolving bpc and nbytes, if bpc is not None require `nbytes % bpc == 0` and raise a TypeError/ValueError explaining that the byte width must be a whole number of characters for this codec. (nchars= already guarantees this; the gap is the explicit nbytes= + bytes_per_char= combination and derived-bpc table codecs.)

---

## 17. startswith/endswith reject bytearray (a documented BitsConstructible) with a spurious 'bit must be 0 or 1' ValueError

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:1444-1459`](../bytemaker/bitvector/bitvector_speedup.py#L1444)

**What.** _normalize_substrings dispatches a single substring only for `isinstance(substrings, (str, bytes, BitsCastable))`. It omits bytearray and memoryview, which are both listed in the BitsConstructible union in bitvector.pyi. A bytearray therefore falls through to the trailing `Iterable` branch, which iterates its byte values (0-255) and feeds them to BitVector(list_of_substrings) as if they were individual bits, raising `ValueError: bit must be 0 or 1, got 222`. So `v.startswith(bytes([0xde]))` works but `v.startswith(bytearray([0xde]))` crashes, even though `bytearray([0xde]) in v` (via __contains__) works fine. The inconsistency is confusing and the crash is user-facing for a type the API advertises as constructible.

**Evidence.**

```
elif isinstance(substrings, (str, bytes, BitsCastable)):   # bytearray / memoryview missing
    return [BitVector(substrings)]
elif isinstance(substrings, Iterable):
    list_of_substrings = list(substrings)
    if all(isinstance(substring, int) for substring in list_of_substrings):
        return [BitVector(list_of_substrings)]   # <-- bytearray lands here; 0xde is not a bit
```
Repro:
```
v = BitVector(bytes([0xde, 0xad]))
v.startswith(bytes([0xde]))       # True
v.startswith(bytearray([0xde]))   # ValueError: bit must be 0 or 1, got 222
bytearray([0xde]) in v            # True (works via __contains__)
```
(Same behavior on both backends.)

**Suggestion.** Add bytearray and memoryview to the single-substring branch, e.g. `isinstance(substrings, (str, bytes, bytearray, memoryview, BitsCastable))`, so byte-like inputs are treated as one substring consistently with bytes and with __contains__.

---

## 18. bitarray backend raises TypeError (not ValueError) for invalid bit values in append/insert/remove/extend

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1036, 1049, 1061, 1101`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1036)

**What.** Same root cause as the float finding, but the exception TYPE diverges for clearly invalid inputs. When a caller passes an invalid bit such as the string '0'/'1' to append/insert/remove/extend, both reference implementations raise ValueError('bit must be 0 or 1, ...') via _coerce_bit, while the shipped bitarray backend raises TypeError from bitarray's C layer. Code that catches ValueError to validate user input (a natural choice given the reference behavior and the ValueError docstring on remove) will fail to catch it on the production backend.

**Evidence.**

append('1') native=('exc','ValueError') speedup=('exc','ValueError') bitarray=('exc','TypeError')
  insert('0') native ValueError, speedup ValueError, bitarray TypeError: 'str' object cannot be interpreted as an integer
  remove('1') native ValueError, speedup ValueError, bitarray TypeError
remove's own docstring in this file: 'Raises: ValueError: If the bit is not found', and _coerce_bit (native/speedup) raises `ValueError(f"bit must be 0 or 1, got {value!r}")`.

**Suggestion.** Fixing the previous finding (coerce via _coerce_bit before delegating) also fixes the exception type: _coerce_bit raises ValueError for out-of-range/invalid values, matching the oracle and the documented contract.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 19. Extended-slice assignment of an empty value: bitarray backend raises while native/speedup silently delete

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:908-929`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L908)

**What.** Assigning an empty value to an extended (step != 1) slice diverges three ways. native (bitvector_native.py __setitem__ slice branch) does self._bits[key] = value._bits on a bytearray, and bytearray has a quirk where `ba[i:j:step] = b''` silently DELETES the stepped positions instead of raising; bitvector_speedup.py reproduces the same behavior (its fuzz twin). The shipped bitarray backend delegates to super().__setitem__ and follows Python list semantics, raising ValueError on any extended-slice length mismatch (including empty). So the same statement silently shrinks the vector on the oracle/fallback backend but raises on the production backend. This is a genuine cross-implementation inconsistency; the silent-delete behavior on native/speedup is itself surprising (no standard Python sequence deletes on an empty extended-slice assignment except bytearray).

**Evidence.**

v = C('00000000'); v[1:8:2] = C('')
  native            SILENTLY DELETED -> len=4 '0000'
  speedup           SILENTLY DELETED -> len=4 '0000'
  bitarray(ACTIVE)  EXC ValueError: attempt to assign sequence of size 0 to extended slice of size 4
For comparison, `list(range(10))[1:8:2] = []` raises ValueError, and `bytearray(range(10))[1:8:2] = b''` deletes -> [0,2,4,6,8,9]. native/speedup inherit the bytearray quirk.

**Suggestion.** Pick one semantics and make all three agree. The list-like ValueError (current bitarray behavior) is the least surprising; to adopt it in native/speedup, special-case extended slices in __setitem__ and raise when len(value) != number-of-selected-positions instead of delegating to bytearray. If the silent-delete is intended, document it and replicate it in the bitarray backend.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 20. unpack_tuple silently returns garbage on wrong-length input in the shiftmask tier (struct tier raises)

**Severity:** medium · **Confidence:** high · [`bytemaker/plans.py:220-236`](../bytemaker/plans.py#L220)

**What.** unpack_tuple is documented as part of the public bulk escape hatch (Plan docstring, lines 122-124: ":meth:`unpack_tuple` ... are the public bulk escape hatch"). Its behavior on a wrong-length `data` argument depends on which tier the record compiled to, and the two tiers disagree incompatibly. The struct tier delegates to `struct_obj.unpack(data)`, which raises `struct.error` if the buffer is not exactly num_bytes. The shiftmask tier does `int.from_bytes(bytes(data), self._int_order)` with NO length check, so any length is accepted: too-long input reads from the wrong byte positions and returns silently-wrong values; too-short input fabricates a record with missing high bytes read as zero. A user of the escape hatch who passes a slice of the wrong width gets a clean exception with a struct-tier record but silent data corruption with a shiftmask-tier record of the same logical layout. (Struct.parse guards length upstream at structs.py:757, so the normal .parse() path is safe; this bites only direct escape-hatch use.)

**Evidence.**

Code: `raw = int.from_bytes(bytes(data), self._int_order)` (line 224) has no length validation, unlike the struct tier's `return self.struct_obj.unpack(data)` (line 223).

Repro output (Shift = shiftmask tier UInt4+UInt4+UInt8 = 2 bytes; Str = struct tier UInt16 = 2 bytes):
== unpack_tuple, 4 bytes given, 2 expected ==
shiftmask -> (1, 1, 34)   (silent garbage)
struct    -> error: unpack requires a buffer of 2 bytes
== unpack_tuple, 1 byte given, 2 expected ==
shiftmask -> (1, 1, 0)    (silent, fabricated)
struct    -> error: unpack requires a buffer of 2 bytes

**Suggestion.** In unpack_tuple, validate the shiftmask branch's input length before decoding, e.g. `data = bytes(data); if len(data) != self.num_bytes: raise ValueError(...)` (or `struct.error` to match the struct tier), so both tiers reject wrong-length buffers identically.

---

## 21. Codec protocol docstring falsely claims scalar BitType classes provide parse/pack

**Severity:** medium · **Confidence:** high · [`bytemaker/structs.py:139-150`](../bytemaker/structs.py#L139)

**What.** The Codec protocol docstring states "Scalar BitType classes, Struct classes, and Array objects all provide num_bits plus parse/pack; composition ... should demand only this." That is false for scalar BitType classes: UInt16/SInt16/Float32 etc. have `num_bits` but NO `parse`/`pack` methods (they use the constructor + `bytes()`), so `isinstance(UInt16, Codec)` is False and `UInt16.parse` raises AttributeError. Generic code written to the documented contract (accept any Codec, call `.parse`/`.pack`) will reject or crash on scalar BitTypes. Separately, the protocol declares `pack(self, value) -> bytes`, but `Struct.pack(self)` takes no `value` argument, so the arity claimed by the protocol also disagrees with the Struct implementation the docstring lists.

**Evidence.**

Docstring: "Scalar BitType classes, Struct classes, and :class:`Array` objects all provide ``num_bits`` plus ``parse``/``pack``".
Protocol body: `def pack(self, value) -> bytes: ...` vs `Struct.pack(self)` (no value param).
Repro (python -c):
  S class is Codec True
  Array is Codec True
  UInt16 is Codec False
  (BitType) has parse False / has pack False / has num_bits True

**Suggestion.** Correct the docstring to match reality: only Struct classes and Array objects satisfy this protocol; scalar BitType classes expose `num_bits` but serialize via the constructor and `bytes()`, not `parse`/`pack`. If scalar BitTypes are meant to be first-class Codecs, add thin `parse`/`pack` shims to BitType; otherwise stop asserting they satisfy the protocol. Also reconcile the `pack(self, value)` signature with `Struct.pack(self)` (e.g. document that Struct packs `self`, or that the protocol's `pack` value is the record itself).

---

## 22. 1-bit sign-magnitude SInt is unconstructible (to_bitstring emits 2 bits for bit_length=1)

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/int.py:265-275`](../bytemaker/bittypes/int.py#L265)

**What.** int_to_signed_magnitude builds the result as sign_bit + unsigned_int_to_bitstring(magnitude, bit_length - 1). For bit_length == 1 the magnitude field width is 0, but unsigned_int_to_bitstring(0, 0) returns bin(0)[2:].zfill(0) == '0' (a spurious digit) rather than '', so the function returns a 2-character string for a 1-bit request. The BitType.bits setter then rejects it ("Expected 1 bits, got 2"), so any 1-bit sign-magnitude SInt raises on construction of even the value 0. (ones_complement happens to avoid this because it uses the full bit_length for the magnitude string.) Degenerate width and pre-existing (same in REF), but it is a hard crash on a value that should be representable.

**Evidence.**

def int_to_signed_magnitude(n, bit_length):
    ...
    if n >= 0:
        return "0" + unsigned_int_to_bitstring(n, bit_length - 1)

Repro:
  >>> SInt1(0, int_format='signed_magnitude')
  ValueError: Expected 1 bits, got 2
  >>> Int.to_bitstring(0, signed=True, bit_length=1, rep_format='signed_magnitude')
  '00'                     # should be a 1-char string
  >>> Int.to_bitstring(0, signed=True, bit_length=1, rep_format='ones_complement')
  '0'                      # ones_complement path is fine

**Suggestion.** Guard the zero-width magnitude case: when bit_length - 1 == 0, the magnitude field is empty, so return just the sign bit (or special-case n == 0 -> '0'). E.g. in unsigned_int_to_bitstring return '' for bit_length == 0, or in int_to_signed_magnitude short-circuit bit_length == 1.

---

## 23. setitem with int key validates index before value, diverging from oracle on invalid bit at OOB index

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:924-929`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L924)

**What.** For an int key with an out-of-range index AND an invalid bit value (e.g. v[1] = 2 on an empty vector), the shipped bitarray backend delegates to super().__setitem__, which checks the index first and raises IndexError, whereas native/speedup validate the value first (via _coerce_bit) and raise ValueError. On a valid index the two agree (bitarray coincidentally uses the same 'bit must be 0 or 1' ValueError message), so this only shows up when both index and value are bad. Minor, but it is a real exception-type divergence between the oracle and the production backend for the same input.

**Evidence.**

v = C(''); v[1] = 2
  native            EXC ValueError: bit must be 0 or 1, got 2
  speedup           EXC ValueError
  bitarray(ACTIVE)  EXC IndexError: bitarray assignment index out of range
native __setitem__ int branch: `self._bits[key] = _coerce_bit(value)` (coerces the value, which raises ValueError, before the bytearray index write).

**Suggestion.** In the bitarray backend __setitem__ int-key branch, coerce the value with _coerce_bit(value) before delegating, so value validation precedes index bounds checking and the exception type matches the oracle.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 24. Stub module __getattr__ returns Any, hiding runtime AttributeError for invalid alias names

**Severity:** low · **Confidence:** high · [`bytemaker/fields.pyi:162`](../bytemaker/fields.pyi#L162)

**What.** The stub declares `def __getattr__(name: str) -> Any: ...`, which tells a type checker that ANY attribute access on the `bytemaker.fields` module is valid and typed `Any`. The runtime `__getattr__` in fields.py, however, only resolves names matching `(u|s)([1-9][0-9]*)` (plus the eagerly-defined float aliases `f16/f32/f64`); everything else raises `AttributeError`. So imports/accesses like `from bytemaker.fields import banana`, `fields.f128`, `fields.f8`, `fields.u_5`, or `fields.x99` type-check cleanly but crash at runtime. This is a genuine stub-vs-runtime disagreement (the explicit unit hint asks the .pyi to agree with the .py). It is the well-known limitation of stubbing a module-level `__getattr__`, so it is minor, but the stub silently blesses names the runtime rejects.

**Evidence.**

fields.pyi line 162:
    def __getattr__(name: str) -> Any: ...

fields.py __getattr__ raises for non-matching names:
    match = _ALIAS_PATTERN.fullmatch(name)
    if match is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

Repro output (all pass type-checking as Any, all raise at runtime):
    f128 AttributeError at runtime (stub says Any -> no checker error)
    f8   AttributeError at runtime
    banana AttributeError at runtime
    x99  AttributeError at runtime
    u_5  AttributeError at runtime

**Suggestion.** Either drop the `__getattr__` stub entirely (so unknown names are reported by the checker as errors, matching runtime) and rely on the explicit `u1..u64`/`s1..s64`/`f16/f32/f64` class stubs plus manually-added wider widths as needed, or narrow the return so only the intended escape hatch (widths >64) is `Any`. If keeping the catch-all, add a comment noting it intentionally over-accepts because module `__getattr__` cannot be Literal-constrained in a stub.

---

## 25. pack_tuple silently drops/zero-fills fields on a short value sequence in the shiftmask tier (struct tier raises)

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:249-259`](../bytemaker/plans.py#L249)

**What.** pack_tuple (also part of the documented public escape hatch) uses `zip(self.shift_masks, values)` in the shiftmask tier, which silently truncates when `values` is shorter than the field count: the trailing fields simply never contribute to `acc`, so they encode as zero and pack_tuple returns a full-length record with silently-wrong contents. The struct tier's `struct_obj.pack(*values)` raises `struct.error` ("pack expected N items ... (got M)") for the same mistake. Same tier-dependent divergence as the unpack_tuple finding, on the encode side. (Normal Struct.pack always supplies a correctly-sized tuple via _bm_to_tuple, so this only affects direct escape-hatch callers.)

**Evidence.**

Code: `for (shift, mask, sign_bit, swap, nbytes), v in zip(self.shift_masks, values):` (lines 250-252) tolerates len(values) < len(shift_masks).

Repro output:
== pack_tuple, too few values ==
shiftmask -> 2100   (silent, missing field=0)
struct    -> error: pack expected 1 items for packing (got 0)

**Suggestion.** Add an explicit length check at the top of pack_tuple (both tiers) or in the shiftmask branch: `if len(values) != len(self.fields): raise ValueError(...)`, matching the struct tier's fail-fast behavior.

---

## 26. iter_tuples over-count: shiftmask tier fabricates zero records from out-of-range slices; struct tier truncates

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:272-290`](../bytemaker/plans.py#L272)

**What.** When called with an explicit `count` larger than the number of whole records available from `offset`, the two tiers behave differently. `end = offset + count * size` can exceed `len(view)`. The struct tier passes `view[offset:end]` (a truncated slice) to `iter_unpack`, which yields only as many records as actually fit -> fewer than `count`, silently. The shiftmask tier iterates `range(offset, end, size)` and calls `unpack_tuple(view[start:start+size])` for each; the final iterations slice past the buffer end, producing empty/short byte slices that unpack_tuple (see the related finding) turns into fabricated zero/garbage records -> exactly `count` records, some fabricated from no data. Neither is validated, and they disagree. Array.parse always passes a matching count with exact-length data, so this is not hit through the normal API.

**Evidence.**

Struct branch: `return self.struct_obj.iter_unpack(view[offset:end])` (line 286) vs shiftmask branch: `return (self.unpack_tuple(view[start : start + size]) for start in range(offset, end, size))` (lines 287-290).

Repro (Sm = shiftmask, 3 bytes/record; Sd = struct, 2 bytes/record), 2 records of data, count=3 requested:
struct tier    -> [(1,), (2,)]                 (len 2, silently truncated)
shiftmask tier -> [(0,0,1),(0,0,2),(0,0,0)]    (len 3, 3rd fabricated from empty slice)

**Suggestion.** Clamp or validate count against available bytes once, before dispatching on tier: e.g. `avail = (len(view) - offset) // size; if count is None: count = avail; elif count > avail: raise ValueError(...)`. That makes both tiers agree and prevents fabricating records from out-of-range slices.

---

## 27. from_int does not reserve the sign bit, silently corrupting positive values that need it (e.g. from_int(127, 7) -> -1)

**Severity:** low · **Confidence:** medium · [`bytemaker/bitvector/bitvector_speedup.py:1799-1815`](../bytemaker/bitvector/bitvector_speedup.py#L1799)

**What.** from_int's overflow check is `if integer.bit_length() > size`. int.bit_length() ignores the sign bit, so a positive value whose magnitude fits in `size` bits but which needs a sign bit to be recovered as positive passes the check and is stored without a leading zero. Reading it back as signed then yields a wrong (negative) value. e.g. from_int(127, 7) accepts and stores '1111111', which to_int(signed=True) decodes as -1. This is in the explicitly 'temporary / transition' block and, importantly, is byte-for-byte identical to the 4-week reference (bitvector_native.py) and to the active bitarray backend, so it is a preserved (if flawed) contract rather than a new regression -- hence low severity. Reported for completeness since a user calling from_int with a tight size can silently corrupt data.

**Evidence.**

```
if size is None:
    size = twos_complement_bit_length(integer)
if integer.bit_length() > size:      # 127.bit_length()==7, size 7 -> passes
    raise ValueError(...)
return cls._with_buf(_pack_int(integer, size), size)
```
Repro:
```
b = BitVector.from_int(127, 7)
b.to01()            # '1111111'
b.to_int(signed=True)   # -1   (silent corruption; no error raised)
```
Reference bitvector_native.py (commit 1a894a2) has the identical check, so behavior is unchanged across backends.

**Suggestion.** If a signed round-trip is intended, size the check with the two's-complement width, e.g. compare against `twos_complement_bit_length(integer)` (which reserves the sign bit) rather than `integer.bit_length()`. Because this matches the frozen reference and both backends, coordinate any change across all three per the legacy-sync convention rather than fixing one path in isolation.

---

## 28. twos_complement silently produces wrong-width / invalid output for out-of-range inputs

**Severity:** low · **Confidence:** medium · [`bytemaker/utils.py:314-325`](../bytemaker/utils.py#L314)

**What.** `twos_complement(number, n_bits)` performs no range validation or masking. For a positive value that does not fit in `n_bits` it emits a string wider than `n_bits` (so downstream `n_bits`-wide consumers break), and for a negative value below the representable minimum it emits a string that decodes to the wrong number. `tc(-200, 8)` returns `00111000`, which is +56, not a valid 8-bit encoding of -200; `tc(300, 8)` returns a 9-character string. The docstring claims to return 'the two's complement of the number' with no caveat. This helper is currently unused elsewhere in bytemaker (only the unrelated `twos_complement_bit_length` is used), so impact is limited to direct callers, hence low severity.

**Evidence.**

utils.py lines 322-325:
```
    if number < 0:
        number = (1 << n_bits) + number
    format_string = "{:0" + str(n_bits) + "b}"
    return format_string.format(number)
```
Repro:
```
>>> from bytemaker.utils import twos_complement as tc
>>> tc(-200, 8)
'00111000'      # decodes to +56, not -200
>>> tc(300, 8)
'100101100'     # 9 chars, wider than n_bits=8
```

**Suggestion.** Either mask into range (`number &= (1 << n_bits) - 1`) so the result is always exactly `n_bits` wide, or validate that `number` fits `[-(1<<(n_bits-1)), (1<<(n_bits-1))-1]` and raise `ValueError` otherwise. Update the docstring to state the width guarantee.

---
