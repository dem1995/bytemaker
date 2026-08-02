# UX / DX

> **Status: verified discovery pass.** Single-pass sweep of this lens, each finding then checked by an independent fairness judge that read the cited code and dropped nitpicks / inaccuracies / flags of the intentional house style (26 of 137 candidates were rejected across the three lenses). Skews toward polish. See [README.md](README.md).

User- and developer-experience problems: context-free error messages, footguns, missing/unhelpful repr, discoverability gaps, surprising ergonomics, and validation that fails late.

_62 findings — 0 high, 25 medium, 37 low._

---

## 1. count_bits_in_unit_type silently returns None for unrecognized types

**Severity:** medium · **Confidence:** high · [`bytemaker/_legacy_aggregate.py:68-87`](../bytemaker/_legacy_aggregate.py#L68)

**What.** count_bits_in_unit_type is an if/elif chain over CType/BitType/PyType/DataClassType with NO final else and no fallback raise. If a user annotates an aggregate field with anything else (a plain object, a typing construct, a forgotten import that resolved to the wrong symbol, a Struct subclass), the function falls off the end and returns None. That None then flows into caller arithmetic — e.g. count_bits_in_aggregate_type does 'size_in_bits += count_bits_in_unit_type(...)' (line 102) and from_bytes_individual does '(count_bits_in_unit_type(field_type) + 7) // 8' — producing a cryptic 'unsupported operand type(s) for +=: int and NoneType' far from the field that actually caused it, with no field name or type in the message. This is a classic fail-late/fail-cryptic footgun.

**Evidence.**

if is_subclass_of_union(unit_type, CType):
        return ctypes.sizeof(unit_type) * 8
    elif is_subclass_of_union(unit_type, BitType):
        return unit_type.num_bits
    elif is_subclass_of_union(unit_type, PyType):
        ...
    elif is_subclass_of_union(unit_type, DataClassType):
        ...
        return size_in_bits   # <- last branch; no else, no final return/raise

**Suggestion.** Add a final 'else: raise TypeError(f"Cannot size field type {unit_type!r}: not a ctype, BitType, supported Python type, or dataclass")' so an unsupported annotation fails immediately with the offending type named, instead of surfacing as a NoneType arithmetic error somewhere downstream.

_Fairness-judge verified: Accurate and verified. bytemaker/_legacy_aggregate.py:68-87 is an if/elif chain over CType/BitType/PyType/DataClassType with no final else and no fallback raise, so an unrecognized-but-valid type annotation (e.g. a Struct subclass) causes issubclass to return False for all four branches and the …_

---

## 2. to_bytes_aggregate silently returns b'' for unrecognized input instead of raising

**Severity:** medium · **Confidence:** high · [`bytemaker/_legacy_aggregate.py:357-375`](../bytemaker/_legacy_aggregate.py#L357)

**What.** to_bytes_aggregate has three branches (UnitType / DataClassType / Iterable) and NO else. If 'units' is none of these (e.g. None, a bare custom object, a dict passed by mistake), the function skips every branch and returns bytes(bytearray()) == b''. The caller gets empty bytes with no error, which then corrupts a larger record or writes a zero-length blob — a silent-wrong data-loss trap. This directly contradicts its sibling to_bits_aggregate (lines 281-285), which for the exact same unrecognized-input case raises TypeError. Two functions that are supposed to be duals disagree on error handling, so behavior depends on which serializer path the user happens to call.

**Evidence.**

if is_instance_of_union(units, UnitType):
        ret_bytes = to_bytes_individual(units, endianness=endianness)
    elif isinstance(units, DataClassType):
        ...
    elif isinstance(units, Iterable):
        ...
    return bytes(ret_bytes)   # <- no else; unrecognized 'units' returns b''

**Suggestion.** Mirror to_bits_aggregate: add 'else: raise TypeError(f"Cannot convert {units!r} to bytes: not a ctype, BitType, Python primitive, dataclass, or iterable")' so silently producing empty output becomes impossible and the two dual functions behave consistently.

_Fairness-judge verified: Verified accurate against current code. bytemaker/_legacy_aggregate.py:357-375 (to_bytes_aggregate) has exactly three branches — is_instance_of_union(units, UnitType), isinstance(units, DataClassType), isinstance(units, Iterable) — and NO else, returning bytes(ret_bytes) where ret_bytes was …_

---

## 3. __repr__ claims it can recreate the object but eval(repr(x)) raises NameError

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/bittype.py:254-264`](../bytemaker/bittypes/bittype.py#L254)

**What.** The __repr__ docstring promises a reconstructable representation ("That can be used to recreate the object"), but the produced string cannot be eval'd. It emits UInt8(bits=FixedLengthBitVector('00101000'), endianness=big): FixedLengthBitVector is not a name in any normal user namespace, and endianness=big is a bare (unquoted) identifier, so eval(repr(x)) fails with NameError. A repr that advertises round-trip but doesn't is a classic debugging footgun — users copy it into a REPL or a test fixture and it blows up cryptically.

**Evidence.**

Docstring: "Returns a string representation of the BitType.\n        That can be used to recreate the object." Actual: repr(UInt8(40)) == "UInt8(bits=FixedLengthBitVector('00101000'), endianness=big)"; eval(repr(UInt8(40))) raises "NameError: name 'FixedLengthBitVector' is not defined".

**Suggestion.** Either make repr round-trip (e.g. f"{cls.__name__}(bits=BitVector('{self.bits.to01()}'), endianness={self.endianness!r})" and ensure BitVector is importable where users eval, or emit the value form UInt8(40, endianness='big')), or drop the "can be used to recreate the object" promise from the docstring. Quote the endianness string with !r regardless.

_Fairness-judge verified: Accurate and reproduced. bittype.py:254-264 __repr__ docstring promises "That can be used to recreate the object," but I confirmed by execution that repr(UInt8(40)) == "UInt8(bits=FixedLengthBitVector('00101000'), endianness=big)" and eval(repr(x)) raises NameError: name 'FixedLengthBitVector' is …_

---

## 4. __repr__ docstring documents a stale/garbled format that does not match the output

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/bittype.py:259-260`](../bytemaker/bittypes/bittype.py#L259)

**What.** The Returns line describes the repr format as ClassName(value)(bits={self.value}, {endianness=self.endianness}) — which is internally inconsistent (says bits={self.value}, i.e. the bits slot holds the value; has a malformed {endianness=...} f-string fragment; and a phantom leading (value) group). The real output is ClassName(bits=<bits>, endianness=<endianness>). A developer reading the docstring to understand or match the repr format is actively misled.

**Evidence.**

Docstring: "str: ClassName(value)(bits={self.value}, {endianness=self.endianness})". Actual return: f"{self.__class__.__name__}(bits={self.bits}, endianness={self.endianness})" → "UInt8(bits=FixedLengthBitVector('00101000'), endianness=big)".

**Suggestion.** Rewrite the Returns line to match the real template: "ClassName(bits=<BitVector>, endianness=<endianness>)", and fix it in tandem with any round-trip change above.

_Fairness-judge verified: Confirmed by reading bytemaker/bittypes/bittype.py directly. The __repr__ docstring Returns line (259-260) reads: "str: ClassName(value)(bits={self.value}, {endianness=self.endianness})". The actual code (262-264) returns f"{self.__class__.__name__}(bits={self.bits}, endianness={self.endianness})". …_

---

## 5. endianness argument accepts any string with no validation, silently producing wrong bytes

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/bittype.py:117-151`](../bytemaker/bittypes/bittype.py#L117)

**What.** __init__ types endianness as Literal["big", "little", "source_else_big"] but never validates it at runtime. Any string is stored verbatim. Because __bytes__ tests `if self.endianness == "big": ... else: reverse`, a common typo/variant like "Little", "LE", or "BE" is silently treated as little-endian and yields byte-reversed output with no error — a silent-wrong trap that only surfaces as corrupted binary far downstream. str()/repr() also happily print the bogus tag (UInt8[LE]), reinforcing the false sense that it was accepted correctly.

**Evidence.**

UInt8(1, endianness='LE') succeeds; `u.endianness == 'LE'`; str(u) == 'UInt8[LE](1 = 00000001)'. __bytes__: "if self.endianness == 'big':\n            return temp_bytes\n        else:\n            return temp_bytes[::-1]" — so 'LE'/'Little'/'BE' all fall into the little-endian (reverse) branch.

**Suggestion.** After resolving source_else_big, validate: `if endianness not in ('big', 'little'): raise ValueError(f"endianness must be 'big' or 'little', got {endianness!r}")`. Fail fast at construction rather than mis-serializing later.

_Fairness-judge verified: Verified against current code and confirmed empirically. In bytemaker/bittypes/bittype.py, __init__ (lines 117-151) types endianness as Literal["big","little","source_else_big"] but never validates it at runtime; after resolving "source_else_big" it just does `self._endianness = endianness`, …_

---

## 6. Buffer.value getter returns the live width-locked bits; mutating the read value silently mutates the box

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/buffer.py:49-51`](../bytemaker/bittypes/buffer.py#L49)

**What.** Buffer.value returns self.bits, which BitType documents as a live, width-locked handle. So `v = buf.value; v[0] = 1` silently mutates the Buffer in place. Every other BitType's .value returns a fresh plain Python value (int/float/str), so a user reasonably treats .value as a safe read; here it is a live alias. This is a silent-wrong footgun, and the class docstring frames the aliasing ('Identical to bits') as a feature without warning that a caller who mutates the returned vector rewrites the buffer.

**Evidence.**

`@property\n    def value(self):\n        return self.bits` (lines 49-51). Reproduced: `inst.value is inst.bits` -> True; `v = inst.value; v[0] = 1` changes `inst.bits` to '1000...'. Docstring: 'value : BitVector ... Identical to bits.'

**Suggestion.** Either return a snapshot copy `return BitVector(self.bits)` from the value getter (matching the safe-read expectation set by other BitTypes), or, if the live alias is intentional, document the hazard explicitly in the property docstring and the class Instance Attributes block so users know reads are mutable.

_Fairness-judge verified: Verified accurate and reproducible. bytemaker/bittypes/buffer.py:49-51 defines `value` as `return self.bits`, and `self.bits` (bytemaker/bittypes/bittype.py:208-222) is documented as "**live and width-locked**: index and length-preserving slice writes mutate this BitType in place." Reproduced: for …_

---

## 7. Buffer docstring twice tells users to 'use one of the pre-defined subclasses' that do not exist

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/buffer.py:20-21, 43-44`](../bytemaker/bittypes/buffer.py#L20)

**What.** The Buffer class docstring says 'Use the specialize method ... or use one of the pre-defined subclasses' -- but unlike Int (UInt8, ...) and Float (Float32, ...), no predefined Buffer subclasses exist or are exported. bittypes/__init__.py exports only 'Buffer'. This sends the user hunting for classes like Buffer8/Buffer16 that were removed (the of() docstring even references a former Buffer16), a direct discoverability dead-end. It also appears twice: the class docstring (lines 17-38) is followed by a second bare copy-pasted docstring literal (lines 40-45) sitting dead in the class body.

**Evidence.**

Line 21 and again line 44: `or use one of the pre-defined subclasses.` Only `Buffer` is exported (`bittypes/__all__` Buffer-ish exports: ['Buffer']). The stray second literal begins line 40: `"""\n    A BitType that represents a buffer of bits.\n ... or use one of the pre-defined subclasses.\n    """`.

**Suggestion.** Delete the duplicate bare docstring at lines 40-45. In the real docstring, drop 'or use one of the pre-defined subclasses' (there are none) and instead point users at the actual entry points: `Buffer.of(nbytes=N)` for Struct/byte fields and `Buffer.specialize(num_bits)` for bit-counted boxes.

_Fairness-judge verified: Every claim is verified directly in bytemaker/bittypes/buffer.py. (1) The real class docstring (lines 17-38) says on line 20-21: "Use the `specialize` method to create a subclass ... or use one of the pre-defined subclasses." (2) A second bare copy-pasted docstring literal sits dead in the class …_

---

## 8. Float class docstring says it "represents an integer"

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:24`](../bytemaker/bittypes/float.py#L24)

**What.** The one-line summary of the Float class is a copy-paste from Int and actively misdescribes the type. A developer skimming help(Float32), an IDE hover, or generated API docs is told the floating-point type "represents an integer", which is exactly wrong and undermines trust in the docs for the headline numeric type. (Present in the 4-weeks-ago reference too, but never corrected.)

**Evidence.**

Line 24: '    A BitType that represents an integer.' (verbatim same first line as Int's docstring, line 30 of int.py: 'A `BitType` that represents an integer.')

**Suggestion.** Change to something like 'A BitType that represents an IEEE-754-style binary floating-point number.' While there, fix the stale copy-paste on line 42 ('The Pythonic type that this `Int` can be converted to/from. It is `float`.') to say `Float` instead of `Int`.

_Fairness-judge verified: Verified in current code. bytemaker/bittypes/float.py line 24 reads verbatim "A BitType that represents an integer." — the one-line summary of the Float class, which is factually wrong (Float is a floating-point type, not an integer). It is a verbatim copy-paste of Int's docstring first line …_

---

## 9. Float.value setter rejects int/bool with an unhelpful, inconsistent error

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:114-116`](../bytemaker/bittypes/float.py#L114)

**What.** The pure-Python value setter requires isinstance(value, float), so any int (or bool, which is an int subclass) is refused. This creates a same-object contradiction: for non-struct subclasses (BFloat16, TF19, FP24) the positional-source constructor path coerces via py_type() and succeeds, but the keyword/attribute path fails. Verified: BFloat16(1) -> 1.0 succeeds, but BFloat16(value=1) raises ValueError, and b.value = 3 on an existing box raises ValueError. Meanwhile the struct-packed siblings (Float16/32/64) accept ints fine (their StructPackedBitType setter wins the MRO). So 'assign an int to a float field' works or fails depending on which Float subclass and which assignment spelling the user picked. The message itself is context-free: it interpolates type(value) (rendering '<class 'int'>'), names no field, and gives no hint that a plain int is a perfectly good float value the caller likely intended.

**Evidence.**

Lines 114-116: 'def value(self, value):\n        if not isinstance(value, float):\n            raise ValueError(f"Expected a float, got {type(value)}")'. Observed: BFloat16(value=1) -> ValueError "Expected a float, got <class 'int'>"; BFloat16(1) -> 1.0 (accepted); Float32(value=1) -> 1.0 (accepted, different setter).

**Suggestion.** Accept anything float() accepts: coerce with value = float(value) inside the setter (mirrors the constructor's py_type() coercion and the struct-packed siblings), or at minimum widen the guard to isinstance(value, (int, float)) so ints/bools are accepted uniformly. If a guard is kept, use type(value).__name__ and the accepted-types hint, e.g. f"Float value must be a real number, got {type(value).__name__!r}".

_Fairness-judge verified: Accurate and fair; downgraded high->medium. Every claim reproduces against current code. bytemaker/bittypes/float.py:114-116 is: `def value(self, value):` / `if not isinstance(value, float): raise ValueError(f"Expected a float, got {type(value)}")`. Empirically confirmed: BFloat16(1) -> 1.0 …_

---

## 10. SInt.__init__ accepts any int_format string with no validation; the failure surfaces late and the message names neither the argument nor the valid choices

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/int.py:571-587`](../bytemaker/bittypes/int.py#L571)

**What.** The SInt constructor stores int_format verbatim (falling back to SignedConfig.signed_int_format) without checking it against the three valid literals. A plausible typo like the hyphenated 'twos-complement' is accepted at construction, then fails later inside the value setter's call to to_bitstring/to_pyint with 'ValueError: Unsupported format: twos-complement'. That message quotes the format string but never says it came from the int_format constructor argument, never names the offending type, and never lists the valid options, so the user has no hint that the correct spelling is the underscore form. Worse, on the struct-packed widths (SInt8/16/32/64) a typo can be silently accepted and produce twos-complement bits, hiding the mistake entirely.

**Evidence.**

if int_format is None:
    int_format = SignedConfig.signed_int_format

self.int_format: Literal[
    "twos_complement", "signed_magnitude", "ones_complement"
] = int_format
super().__init__(...)

# observed: SInt3(2, int_format='twos-complement')
#   -> ValueError: Unsupported format: twos-complement   (raised late, from to_bitstring)
# observed: SInt8(5, int_format='twos-complement') -> silently constructs bits 00000101

**Suggestion.** Validate int_format at the top of SInt.__init__ against {'twos_complement','signed_magnitude','ones_complement'} and raise immediately with a message that names the parameter, the bad value, and the valid choices, e.g. raise ValueError(f"int_format must be one of 'twos_complement', 'signed_magnitude', 'ones_complement'; got {int_format!r}"). This fails at the construction site and makes the fix obvious.

_Fairness-judge verified: Verified against current code and empirically reproduced. SInt.__init__ (bytemaker/bittypes/int.py:581-587) stores int_format verbatim with no validation, only defaulting None to SignedConfig.signed_int_format. Both claimed behaviors reproduce exactly:  1. Non-struct width: SInt3(2, …_

---

## 11. Typo'd endianness (e.g. 'bigg', 'litle') is silently accepted through the Int/SInt/UInt constructors and treated as little-endian

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/int.py:571-587`](../bytemaker/bittypes/int.py#L571)

**What.** The SInt/UInt constructors (and the base __init__ they forward to) declare endianness as a Literal['big','little','source_else_big'] but never validate the string. Because the byte-order logic only special-cases exactly 'big' (else it reverses), any typo silently produces LITTLE-endian output. UInt16(0x0102, endianness='bigg') yields bytes 0201 — the opposite of what the user intended — with no error or warning. A wrong byte order is exactly the kind of silent-wrong bug this library exists to prevent, and it stems from a one-character typo being accepted. (Root cause is the base BitType.__init__/__bytes__ in bittype.py, but it manifests directly through the int.py constructors, which re-declare and forward endianness without validation.)

**Evidence.**

def __init__(self, ..., endianness: Literal["big", "little", "source_else_big"] = "source_else_big", ...):
    ...
    super().__init__(source=source, value=value, bits=bits, endianness=endianness)

# observed:
#   bytes(UInt16(0x0102, endianness='big'))   -> 0102
#   bytes(UInt16(0x0102, endianness='bigg'))  -> 0201  (silently little-endian)
#   bytes(UInt16(0x0102, endianness='litle')) -> 0201  (silently little-endian)

**Suggestion.** Validate endianness against {'big','little','source_else_big'} in __init__ (ideally in the base BitType.__init__) and raise ValueError naming the bad value and the valid options, so a typo fails loudly at construction instead of silently flipping byte order.

_Fairness-judge verified: Verified in current code and empirically reproduced. In bittype.py, BitType.__init__ (lines 148-151) stores the endianness string unvalidated: if it isn't "source_else_big" it is assigned to self._endianness as-is. __bytes__ (lines 333-336) then special-cases only "big" (`if self.endianness == …_

---

## 12. of() accepts out-of-range pad/terminator that fail late with a context-free ValueError

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/string.py:300, 314, 356-357`](../bytemaker/bittypes/string.py#L300)

**What.** String.of() validates bytes_per_char (positive int, lines 399-405) but never validates pad or terminator, even though both must be single-byte ints (0-255). An out-of-range value like pad=0x100 is accepted at mint time and only blows up much later, during encode/decode, with a bare ValueError 'bytes must be in range(0, 256)' that names neither the class, nor which parameter caused it. The failure surfaces far from the declaration that is actually wrong, and the message gives the user nothing to act on.

**Evidence.**

of() signature: `pad: Optional[int] = 0x00, terminator: Optional[int] = None`; used unchecked at encode `raw += bytes((cls.pad,)) * (nbytes - len(raw))` (line 300) and decode `term = bytes((cls.terminator,)) * unit` (line 314). Reproduced: `UTF8String.of(nbytes=8, pad=0x100)` mints fine, then `T('hi')` raises `ValueError: bytes must be in range(0, 256)`; `terminator=999` raises the same at decode. Neither message mentions the field or the parameter.

**Suggestion.** Validate pad and terminator in of() (and ideally when set as class attrs) at mint time: require None or an int in range(0, 256), and raise a TypeError/ValueError that names the class and the offending parameter, e.g. f"{cls.__name__}.of(): pad must be a byte value 0-255 or None, got {pad!r}". This matches the existing bytes_per_char check and fails at the declaration site.

_Fairness-judge verified: Verified accurate and fair. In bytemaker/bittypes/string.py, of() (lines 348-457) validates nbytes/nchars, bytes_per_char (399-405), and field size (423-427), but never validates pad or terminator — they flow straight into the class namespace at lines 430-431 with defaults `pad: Optional[int] = …_

---

## 13. errors= typos and codec-unsupported policies fail late with a bare LookupError

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/string.py:359, 478, 545`](../bytemaker/bittypes/string.py#L359)

**What.** of() takes errors: str = 'strict' but never validates it. A typo like errors='stricct' mints a type happily, then fails at first decode with a bare stdlib `LookupError: unknown error handler name 'stricct'` that never mentions the String class or field. Worse for TableString: its decoding() only special-cases 'replace' and treats everything else as strict-raise, so a user who mints a TableString with errors='ignore' or errors='backslashreplace' gets a silent-wrong contract (the policy is quietly ignored) and then a hard ValueError on the first unmapped byte, contradicting the of() docstring which says 'errors is the decode error policy where the codec supports one'.

**Evidence.**

StandardEncodingString: `return bytes(bits).decode(cls.encoding_name, cls.errors)` (line 478) -> `LookupError: unknown error handler name 'stricct'` at decode, class name absent. TableString: `if cls.errors == 'replace': out.append('�') ... else: raise ValueError(...)` (lines 545-552) -- errors='ignore' silently behaves as strict; reproduced: `TableString.of(nbytes=4, encoding={0x41:'A'}, errors='ignore')` still raises on byte 0xff.

**Suggestion.** Validate errors in of() at mint time against the codec's real capabilities: for StandardEncodingString accept the stdlib handler names (or eagerly probe b''.decode(encoding, errors)); for TableString accept only {'strict','replace'} and raise a TypeError naming the class and listing the supported policies. Fail at the declaration, not at the first unlucky byte.

_Fairness-judge verified: Verified by reading and reproducing at runtime. All three code claims hold in current code (bytemaker/bittypes/string.py):  1. `of()` (line 359) takes `errors: str = "strict"` and never validates it. `String.of(nbytes=4, encoding='ascii', errors='stricct')` mints a type happily (confirmed: …_

---

## 14. pop() on out-of-range (or negative) index reports "pop from empty BitVector"

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:1269-1274`](../bytemaker/bitvector/bitvector_speedup.py#L1269)

**What.** pop() raises IndexError with the fixed text "pop from empty BitVector" for ANY out-of-bounds or negative index, even when the vector is non-empty. Verified: BitVector('0b1010').pop(99) and .pop(-1) both raise "pop from empty BitVector" though the vector has 4 bits. The message names neither the offending index nor the actual length, and actively misleads the reader into thinking the vector is empty when it is not.

**Evidence.**

if index >= len(self) or index < 0:
    if default is not None:
        return default
    raise IndexError("pop from empty BitVector")

**Suggestion.** Distinguish the empty case from out-of-range, and include the offending index and length, e.g. raise IndexError(f"pop index {index} out of range for BitVector of length {len(self)}") (reserve "pop from empty" for len(self) == 0).

_Fairness-judge verified: Accurate and reproducible. In bytemaker/bitvector/bitvector_speedup.py:1271-1274, pop() raises `IndexError("pop from empty BitVector")` for ANY out-of-range or negative index, regardless of the actual length: `if index >= len(self) or index < 0: ... raise IndexError("pop from empty BitVector")`. So …_

---

## 15. pop() treats negative indices as out-of-bounds, silently returning the default instead of the last bit

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:1248-1274`](../bytemaker/bitvector/bitvector_speedup.py#L1248)

**What.** Every other indexed method (__getitem__, __setitem__/_set_bit, __delitem__, insert) normalizes negative indices Python-style (key += len). pop() alone treats any negative index as out of bounds. With a default supplied this is a silent-wrong trap: BitVector('0b1010').pop(-1, 9) returns 9 instead of popping the last bit (1). A user reasonably expecting list.pop(-1) semantics gets the sentinel back with no error. The docstring even flags this as intentional ("negative indices are treated as out of bounds"), but it contradicts the rest of the class and list.pop.

**Evidence.**

If a default is provided and the index is out of bounds,
the default is returned; negative indices are treated as
out of bounds.
...
if index >= len(self) or index < 0:
    if default is not None:
        return default

**Suggestion.** Normalize negatives like the rest of the class (if index < 0: index += len(self)) before the bounds check, so pop(-1) pops the last bit. If the asymmetry is truly intended, at minimum surface it loudly rather than silently returning the sentinel.

_Fairness-judge verified: Accurate and fair. In bytemaker/bitvector/bitvector_speedup.py, pop() (lines 1248-1287) checks `if index >= len(self) or index < 0` (line 1271) and treats every negative index as out of bounds, whereas the other four indexed methods all normalize negatives Python-style first: __getitem__ (`if key < …_

---

## 16. to_chararray() validates length with assert (stripped under -O) and the message contains a run of stray whitespace

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:768-770`](../bytemaker/bitvector/bitvector_speedup.py#L768)

**What.** Public API to_chararray() enforces the 'length must be a multiple of 8' precondition with a bare assert. Under `python -O` the assert is stripped and bytes(self).decode() then fails later with a cryptor error (or silently drops the partial byte via tobytes padding), so the validation vanishes in optimized runs. Separately, the backslash line-continuation inside the assert string embeds ~16 spaces of source indentation into the runtime message (verified length 82 chars, most of it whitespace): "...multiple of 8                to use a standard encoding".

**Evidence.**

assert len(self) % 8 == 0, "BitVector length must be a multiple of 8\
    to use a standard encoding"

**Suggestion.** Replace the assert with an explicit `if len(self) % 8: raise ValueError(f"BitVector length {len(self)} is not a multiple of 8; cannot decode with a standard encoding")`, and collapse the continuation so the message has no embedded indentation.

_Fairness-judge verified: Verified against current code at bytemaker/bitvector/bitvector_speedup.py:768-769. to_chararray() is a public method (no underscore, documented) whose 'length must be a multiple of 8' precondition is guarded by a bare assert on caller-supplied input. Confirmed empirically: under `python -O` the …_

---

## 17. bin() docstring says the result is 'prefixed by 0x' (should be 0b)

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:551`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L551)

**What.** In the active backend, bin()'s docstring wrongly states the output is prefixed by 0x. The code returns `"0b" + self.to01(...)`. The pure-Python sibling has correct wording ('prefixed by 0b', bitvector_native.py:572). Both oct() and bin() in this file were evidently copy-pasted from hex() and never edited, so a developer sees the wrong prefix for the binary method too.

**Evidence.**

"""\n        Convert the BitVector to a binary string prefixed by 0x."  (line 551, method returns "0b" + self.to01(...))

**Suggestion.** Fix the docstring to 'Convert the BitVector to a binary string prefixed by 0b.' to match the code and the native backend.

_Fairness-judge verified: Verified at bytemaker/bitvector/bitvector_with_bitarray_speedup.py:551: the bin() docstring reads "Convert the BitVector to a binary string prefixed by 0x." but the method returns `"0b" + self.to01(sep, bytes_per_sep)` (line 562). The native sibling has the correct wording at …_

---

## 18. ctypes error messages have run-together words (missing spaces at concatenation boundaries)

**Severity:** medium · **Confidence:** high · [`bytemaker/conversions/ctypes_.py:57-62, 92-93, 144-145`](../bytemaker/conversions/ctypes_.py#L57)

**What.** Three user-facing error messages are built from adjacent implicitly-concatenated string literals with no trailing space, so words collide in the rendered message. A developer who hits these reads garbled text, which undermines trust and makes the message look broken. In the NotImplementedError the collision also fuses the diagnostic values (instance and fields) into one unreadable run, defeating the purpose of including them.

**Evidence.**

ctype_to_bytes: f"ctype_to_bytes only accepts _SimpleCData, Structure," f"Union, and Array objects, not {type(ctype_obj)}." renders as "...Structure,Union, and Array objects...". bytes_to_ctype: same pattern renders "...Structure,Union, and Array types...". reverse_ctype_endianness NotImplementedError renders "...more than 2 elements arenot supported.Ctype instance: XCtype instance fields: Y" ("arenot", "supported.Ctype", "XCtype").

**Suggestion.** Add a space (or newline) at the end of each fragment: "...Structure, " "Union, and Array objects, not {...}."; and in the NotImplementedError put " " or "\n" between "are"/"not", after "supported.", and before each "Ctype instance:" fragment.

_Fairness-judge verified: Verified all three locations by direct read of bytemaker/conversions/ctypes_.py. Python adjacent string-literal concatenation makes the rendered messages exactly as claimed. Lines 92-93 (ctype_to_bytes TypeError): "...Structure," + "Union,..." -> "...Structure,Union, and Array objects..." (missing …_

---

## 19. str/char conversion's num_bits lies (reports 8 bits, encodes the whole string)

**Severity:** medium · **Confidence:** high · [`bytemaker/conversions/pytypes.py:207-213`](../bytemaker/conversions/pytypes.py#L207)

**What.** The registered conversion for str advertises a fixed width of 8 bits via num_bits, but to_bits encodes the entire UTF-8 string (24 bits for 'ABC'). Any caller that trusts num_bits/num_bytes for sizing or offset computation (e.g. count_bits_in_unit_type, aggregate layout) will under-count and silently produce wrong offsets/lengths for multi-character strings. This is a silent-wrong trap with no error at the point of misuse.

**Evidence.**

pytype=str, to_bits=lambda string: BitVector(string.encode("utf-8")), from_bits=lambda bits: bits.to_bytes().decode("utf-8"), num_bits=lambda _: 8. Verified: pytype_to_bytes('ABC') -> b'ABC' (3 bytes) while ConversionInfo.num_bits('ABC') returns 8.

**Suggestion.** Make num_bits reflect the actual encoding: num_bits=lambda s: len(s.encode('utf-8')) * 8 (matching the bytesish entries), or restrict the conversion to a single character and validate len(s)==1 in to_bits with a clear error. A width that disagrees with the encoder must not ship.

_Fairness-judge verified: Accurate and reproducible. In bytemaker/conversions/pytypes.py:207-213 the str ConversionInfo registers `to_bits=lambda string: BitVector(string.encode("utf-8"))` (variable width) but `num_bits=lambda _: 8` (fixed). Verified: ConversionInfo.num_bits('ABC') == 8 while pytype_to_bytes('ABC') == …_

---

## 20. Typo'd endianness value is silently treated as big-endian instead of rejected

**Severity:** medium · **Confidence:** high · [`bytemaker/conversions/pytypes.py:281-299, 324-343`](../bytemaker/conversions/pytypes.py#L281)

**What.** endianness is typed Literal['big','little'] but never validated at runtime. The code only special-cases the exact string 'little' (reverses); any other value, including a typo like 'litle' or 'small', falls through to the big-endian path and produces wrong bytes with no error. The same all-branches-else-is-big pattern appears in to_bytes_aggregate/ctype_to_bytes (endianness != sys.byteorder / == 'little'). This is a classic silent-wrong footgun that surfaces only as corrupted output far downstream.

**Evidence.**

pytype_to_bytes: if endianness == "little": retval = retval[::-1]. Verified: pytype_to_bytes(1, endianness='litle') == b'\x00\x00\x00\x01' (silently big-endian, no error), identical to endianness='big'.

**Suggestion.** Validate at entry: if endianness not in ('big','little'): raise ValueError(f"endianness must be 'big' or 'little', got {endianness!r}"). Apply consistently across pytypes/ctypes_/aggregate_types entry points.

_Fairness-judge verified: Verified in current code and reproduced at runtime. In bytemaker/conversions/pytypes.py, pytype_to_bytes (lines 281-299) and bytes_to_pytype (lines 324-343) only special-case the exact string "little" (`if endianness == "little": retval = retval[::-1]`); every other value falls through to …_

---

## 21. shiftmask unpack_tuple silently decodes wrong-sized data into garbage

**Severity:** medium · **Confidence:** high · [`bytemaker/plans.py:220-236`](../bytemaker/plans.py#L220)

**What.** unpack_tuple is documented as the 'public bulk escape hatch' (line 122-124), so users call it directly. On the shiftmask tier it does int.from_bytes(bytes(data), ...) with NO length check, then shifts/masks bits out of that int. Wrong-sized input therefore returns a plausible-looking tuple of wrong values instead of raising. The struct tier, by contrast, DOES raise (struct.error: 'unpack requires a buffer of N bytes'), so the same public method fails loudly on one tier and silently corrupts on the other. This is a classic silent-wrong footgun: a user who slices one byte short gets a tuple back and no indication anything is amiss.

**Evidence.**

raw = int.from_bytes(bytes(data), self._int_order)  (line 224) with no length guard. Confirmed empirically on a U4+U12 shiftmask plan (num_bytes=2): plan.unpack_tuple(b'\x12') returns (0, 18) and plan.unpack_tuple(b'\x12\x34\x56') returns (3, 1110); the aligned tier raises 'unpack requires a buffer of 3 bytes' for the same mistake.

**Suggestion.** At the top of unpack_tuple (or just before int.from_bytes), guard: `if len(data) != self.num_bytes: raise ValueError(f"expected {self.num_bytes} bytes, got {len(data)}")` so both tiers reject wrong-sized input with the same clear message.

_Fairness-judge verified: Accurate and fair, but claimed severity is too high. VERIFIED: plans.py:224 does `raw = int.from_bytes(bytes(data), self._int_order)` with no length guard on the shiftmask tier, then shifts/masks. The struct tier (plans.py:222-223) delegates to struct.Struct.unpack, which raises. Empirically …_

---

## 22. shiftmask pack_tuple silently ignores wrong number of values (zip truncation)

**Severity:** medium · **Confidence:** high · [`bytemaker/plans.py:249-259`](../bytemaker/plans.py#L249)

**What.** pack_tuple on the shiftmask tier zips self.shift_masks against values. If the caller passes too FEW values, zip stops early and the missing fields are silently packed as their initial 0 bits; if too MANY, the extras are silently dropped. Either way the caller gets bytes back with no error. The struct tier raises struct.error ('pack expected N items ... got M') for the same mistake, so the public method is again loud on one tier and silent on the other.

**Evidence.**

`for (shift, mask, sign_bit, swap, nbytes), v in zip(self.shift_masks, values):` (lines 250-252). Confirmed on the U4+U12 shiftmask plan (needs 2 values): plan.pack_tuple([5]) returns bytes 5000 (missing field silently 0) and plan.pack_tuple([5,6,7]) returns 5006 (extra 7 dropped); the aligned tier raises 'pack expected 2 items for packing (got 1)'.

**Suggestion.** Guard at the start of pack_tuple: `if len(values) != len(self.fields): raise ValueError(f"expected {len(self.fields)} values, got {len(values)}")`, applied to both tiers so behavior is uniform and the error names the mismatch.

_Fairness-judge verified: Confirmed by direct reproduction. plans.py:250-252 zips self.shift_masks against values, so on the shiftmask tier pack_tuple silently zero-fills missing fields (too-few) and drops extras (too-many) with no error, while the struct tier raises struct.error for the same mistake. Reproduced with a real …_

---

## 23. field(Struct, default=...) silently shares one mutable instance across all Structs

**Severity:** medium · **Confidence:** high · [`bytemaker/structs.py:631-645`](../bytemaker/structs.py#L631)

**What.** A nested-Struct default supplied via field(default=SomeStruct(...)) is stored once and stored by reference for every instance (the descriptor and _bm_from_tuple never deep-copy struct values), so mutating the field on one instance mutates the shared default on all instances -- the classic mutable-default footgun, silent and wrong. Verified live: with `a: Inner = field(Inner, default=Inner(5))`, `o1.a.x = 99` makes `o2.a.x == 99`. The _ArrayField docstring (352-363) explicitly acknowledges this hazard for struct *array* elements, but field()'s own docstring gives no warning for the scalar nested-Struct case and there is no defensive copy.

**Evidence.**

def field(bittype: Any, *, default: Any = _MISSING) -> Any:
    ...
    return _FieldSpec(bittype, default)

**Suggestion.** Either deep/detach-copy a mutable (Struct/Array) default per instance at __init__ time, or at minimum document the aliasing in field()'s docstring the way _ArrayField documents it, and recommend a default_factory-style pattern for mutable defaults.

_Fairness-judge verified: Accurate and live-verified. With `a: Inner = field(Inner, default=Inner(5))`, two default-constructed Outers share one Inner: `o1.a is o2.a` is True, and `o1.a.x = 99` makes `o2.a.x == 99`. Confirmed the code path in bytemaker/structs.py: the __init__ codegen (lines 522-534) binds a scalar Struct …_

---

## 24. twos_complement docstring documents a parameter that does not exist and a wrong return semantics label

**Severity:** medium · **Confidence:** high · [`bytemaker/utils.py:314-325`](../bytemaker/utils.py#L314)

**What.** The signature is 'def twos_complement(number, n_bits=32)', but the docstring documents ':param bits:' — there is no 'bits' parameter; the real second parameter is 'n_bits'. A developer relying on the docstring (or an IDE surfacing it) will try twos_complement(5, bits=8) and get 'unexpected keyword argument bits'. The ':return:' line also says it returns 'A string representing the two's complement', which is correct here, but the mismatched param name is the load-bearing DX error. This is also a style/format drift: this one function uses ':param:/:return:' RST field lists while the rest of utils.py (twos_complement_bit_length, is_instance_of_union, etc.) uses Google-style 'Args:/Returns:'.

**Evidence.**

def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    :param number: The integer to convert.
    :param bits: The bit width for the two's complement representation.
    :return: A string representing the two's complement of the number.
    """

**Suggestion.** Rename the docstring param to match the signature: ':param n_bits: The bit width ...'. For consistency with the rest of the file, prefer the Google-style 'Args:/Returns:' block used by the neighboring twos_complement_bit_length.

_Fairness-judge verified: Verified in current code at bytemaker/utils.py:314-321. Signature is `def twos_complement(number, n_bits=32)` but the docstring documents `:param bits:` (line 319) — no `bits` parameter exists; the real one is `n_bits`. A developer trusting the docstring/IDE hint would call `twos_complement(5, …_

---

## 25. The surprising C-promotion / narrowing behavior is undocumented in any user-facing docstring (module and Int class have no mention)

**Severity:** medium · **Confidence:** medium · [`bytemaker/bittypes/int.py:28-53`](../bytemaker/bittypes/int.py#L28)

**What.** The July rewrite gave Int a C-style promotion model where UInt8(200) + UInt8(100) returns a PLAIN int 300 (not a wrapped UInt8(44)), and where compound assignment narrows but binary ops do not. This is genuinely surprising for a type that otherwise behaves like a sized int, and it is the single most likely thing to confuse a new user. Yet the module has no docstring at all (module.__doc__ is None), and the Int class docstring (lines 29-53) says nothing about promotion or narrowing. The only explanation lives in inline implementation comments (lines 304-316, 450-453, 470-476) that never appear in help(UInt8), __doc__, or rendered API docs. A user who reads the public docstring has no way to learn that arithmetic promotes to plain int and only the constructor / compound assignment narrows.

**Evidence.**

class Int(BitType[int]):
    """
    A `BitType` that represents an integer.

    Is further subclassed into `SInt` and `UInt` for signed and unsigned integers,
    ...
    """   # <- no mention of promotion, narrowing, or that `a + b` returns a plain int

# observed: UInt8(200) + UInt8(100) == 300  (type int, NOT UInt8(44))
# import bytemaker.bittypes.int as m; m.__doc__ is None

**Suggestion.** Add a short user-facing summary of the promotion/narrowing contract to the Int class docstring (and/or a module docstring): binary ops promote to plain int (no wrap), the constructor UInt8(x) and compound assignment += are the narrowing casts. Move the essential points out of the private inline comments so help()/rendered docs surface the one behavior users will trip over.

_Fairness-judge verified: Verified against current code and runtime. All factual claims hold: (1) bytemaker/bittypes/int.py module __doc__ is None; (2) the Int class docstring (lines 29-53) has no mention of promotion, narrowing, or wrap ("A `BitType` that represents an integer... Is further subclassed into `SInt` and …_

---

## 26. User-facing conversion errors reference undefined internal jargon 'YType'

**Severity:** low · **Confidence:** high · [`bytemaker/_legacy_aggregate.py:126-128, 148-151, 181-183, 218-220, 283-285`](../bytemaker/_legacy_aggregate.py#L126)

**What.** Five different TypeError messages that a user will actually see tell them the unit type is 'not a CType, YType, or PyType'. 'YType' is a stale internal name — the public, importable, documented type is BitType (see the module's own import 'from bytemaker.bittypes import BitType' and __init__.__all__). No symbol named 'YType' exists anywhere in the public API, so a user reading this error cannot map it to anything they can act on. The comment at line 44-45 even admits the rename ('YType is a Union of ...'). This makes the most common failure mode of the aggregate API undebuggable-by-name.

**Evidence.**

raise TypeError(
            f"Cannot convert {unit} to bits because"
            f" the unit type is not a CType, YType, or PyType"
        )   # 'YType' is not a real, importable name; the public type is BitType

**Suggestion.** Replace 'YType' with 'BitType' in all five messages (lines 128, 151, 183, 220, 285), and ideally include the offending value's actual type, e.g. f"...not a ctype, BitType, or Python primitive (got {type(unit).__name__})".

_Fairness-judge verified: Accurate and verified. bytemaker/_legacy_aggregate.py raises five TypeErrors whose text says the value is "not a CType, YType, or PyType" (lines 127, 150, 182, 219, 284; plus stale "YType" in docstrings at 157, 193 and the Args line 240). I confirmed "YType" appears nowhere in the codebase as a …_

---

## 27. NarrowingConfig/NarrowingWarning defined here but not exported from bittypes package

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/__init__.py:1,65-125`](../bytemaker/bittypes/__init__.py#L1)

**What.** NarrowingConfig and NarrowingWarning are defined in bittypes/bittype.py and their own docstrings instruct users to enable checked stores "via NarrowingConfig" and to escalate with warnings.simplefilter('error', NarrowingWarning). Yet neither symbol is re-exported by bittypes/__init__.py (not imported, not in __all__). `from bytemaker.bittypes import NarrowingConfig` raises ImportError, even though they live in that subpackage. They are only reachable from the top-level `bytemaker` package and from structs.py, which is a discoverability inconsistency: the knob is documented next to its definition but not importable from the package that defines it.

**Evidence.**

`from bytemaker.bittypes import NarrowingConfig` → "ImportError: cannot import name 'NarrowingConfig' from 'bytemaker.bittypes'". bittype.py docstring: "Enable via :class:`NarrowingConfig` ... warnings.simplefilter(\"error\", NarrowingWarning)". __init__.py imports from .bittype only "BitType, StructPackedBitType, bytes_to_bittype" and __all__ omits the narrowing symbols.

**Suggestion.** Add NarrowingConfig and NarrowingWarning to the `from bytemaker.bittypes.bittype import ...` line and to __all__ in bittypes/__init__.py, matching the top-level bytemaker package which already exports them.

_Fairness-judge verified: Verified against current code. In bytemaker/bittypes/bittype.py, NarrowingWarning (line 27) and NarrowingConfig (line 39) are defined, and their docstrings direct users to them by name: line 32 "Enable via :class:`NarrowingConfig`" and lines 33-35 "warnings.simplefilter(\"error\", …_

---

## 28. N * Cls array sugar fails with a cryptic Int.__mul__ arity error

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:79-80`](../bytemaker/bittypes/bittype.py#L79)

**What.** BitTypeMeta advertises array sugar ("cls * N -> Array", "UInt16 * 257"). The reflected form N * Cls (e.g. 257 * UInt16) is a natural thing to try, but __rmul__ delegates via cls.__mul__(count). On a class object, cls.__mul__ resolves to the INSTANCE numeric operator (Int.__mul__ from the value ops), not the metaclass array-sugar __mul__. So 4 * UInt8 raises "TypeError: Int.__mul__() missing 1 required positional argument: 'other'" instead of building an Array — a confusing, internals-leaking error for a documented-feeling operation.

**Evidence.**

Code: "def __rmul__(cls, count: int):\n        return cls.__mul__(count)". Runtime: `4 * UInt8` → "TypeError: Int.__mul__() missing 1 required positional argument: 'other'". `UInt8.__mul__` resolves to `<function Int.__mul__>`, not `BitTypeMeta.__mul__`.

**Suggestion.** Dispatch through the metaclass explicitly: `return type(cls).__mul__(cls, count)` (or inline `from bytemaker.structs import Array; return Array.of(cls, count)`). Add a test for `N * Cls`.

_Fairness-judge verified: Accurate and runtime-verified. bytemaker/bittypes/bittype.py:79-80: `def __rmul__(cls, count): return cls.__mul__(count)`. Testing `4 * UInt8` raises `TypeError: Int.__mul__() missing 1 required positional argument: 'other'`, exactly as claimed. Root cause confirmed: `UInt8.__mul__` resolves to …_

---

## 29. to_bits/from_bits are marked DEPRECATED in docstrings but emit no DeprecationWarning

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:350-372`](../bytemaker/bittypes/bittype.py#L350)

**What.** Both to_bits() and from_bits() open their docstrings with "DEPRECATED" and point to the replacement (the `bits` property / the constructor), but neither issues a runtime DeprecationWarning. A developer who never opens the source (the common case for deprecated helpers) gets no signal to migrate; the deprecation is invisible outside the docstring. This weakens the migration path the maintainer clearly intends (the methods are even tagged "# TODO remove").

**Evidence.**

Docstrings begin "DEPRECATED\n        Use the `bits` property instead." and "DEPRECATED\n        Use the constructor ... instead." Running both under -W all with a warnings recorder emits 0 warnings.

**Suggestion.** Emit `warnings.warn("BitType.to_bits() is deprecated; use the .bits property", DeprecationWarning, stacklevel=2)` (and the analog for from_bits) so the deprecation is discoverable at runtime, or remove the methods per the TODO.

_Fairness-judge verified: Accurate and fair. Verified in bytemaker/bittypes/bittype.py:350-372: to_bits() and from_bits() docstrings both open with "DEPRECATED" pointing to replacements ("Use the `bits` property instead." / "Use the constructor with a BitVector-like object instead."), sit under a "# TODO remove" comment …_

---

## 30. min_bit_length silently returns None for an unrecognized signed bin_format, causing a cryptic downstream TypeError

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/int.py:169-195`](../bytemaker/bittypes/int.py#L169)

**What.** In the signed branch of min_bit_length there is no final else that raises for an unknown bin_format: the if/elif chain covers only twos_complement, signed/sign_magnitude, and ones_complement, then the function falls off the end and returns None. Every sibling code path (the unsigned branch, to_bitstring, to_pyint) raises ValueError('Unsupported format: ...') on a bad format, so this one is inconsistent and, worse, the None it returns flows into to_bitstring as bit_length and blows up far from the mistake. Calling Int.to_bitstring(5, signed=True, rep_format='garbage') (bit_length left to default) raises 'TypeError: <= not supported between instances of NoneType and int' at the 'if bit_length <= 0' check instead of a clear format error. (Pre-existing: the ref_4wks min_bit_length also lacked the raise, so this is not new July regression, but it is a genuine DX footgun in this file.)

**Evidence.**

elif bin_format == "ones_complement":
    if n == 0:
        return 1  # ...
    return ceil(log2(abs(n) + 1)) + 1
# (no trailing `else: raise` — an unknown signed bin_format returns None)

# downstream effect, observed:
#   Int.to_bitstring(5, signed=True, rep_format='garbage')
#   -> TypeError: '<=' not supported between instances of 'NoneType' and 'int'

**Suggestion.** Add a final `else: raise ValueError(f"Unsupported format: {bin_format!r}. Expected one of 'twos_complement', 'signed_magnitude', 'ones_complement'.")` to the signed branch of min_bit_length so an unknown format fails immediately at the source with a clear, choice-listing message instead of returning None and surfacing as a NoneType TypeError later.

_Fairness-judge verified: Accurate and reproduced. In bytemaker/bittypes/int.py the signed branch of min_bit_length (lines 169-195) is an if/elif chain covering twos_complement, signed_magnitude/sign_magnitude, and ones_complement with no final `else: raise`, so an unrecognized bin_format falls off the end and returns None. …_

---

## 31. SInt docstring points users to a nonexistent `Config` class (the actual class is SignedConfig)

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/int.py:545, 561`](../bytemaker/bittypes/int.py#L545)

**What.** The SInt class docstring twice tells the reader to use 'the `Config` class' to change the signed integer format, but no class named Config exists in this module or (confirmed) as an importable name — the class is SignedConfig. A user following the docstring to discover the knob will fail to find it. This is a discoverability defect: the documented entry point does not exist. (Pre-existing: the same stale reference is in the ref_4wks pyc, so it predates the July rewrite.)

**Evidence.**

To change the signed integer format, use the `Config` class
    (or set the `int_format` parameter in the constructor).
...
    If this is left as `None`, the format will be taken from the `Config` class.

# but the actual class is `SignedConfig`; `import bytemaker.bittypes.int; 'Config' in dir(...)` is False

**Suggestion.** Replace both occurrences of `Config` with `SignedConfig` (and its `signed_int_format` attribute) so the docstring names the real, importable configuration point.

_Fairness-judge verified: Accurate and fair. bytemaker/bittypes/int.py:545 ("To change the signed integer format, use the `Config` class") and :561 ("the format will be taken from the `Config` class") both reference a `Config` class that does not exist in the module. The real class, defined at line 525 and exported in …_

---

## 32. Bogus encoding= name accepted at mint, fails late at first encode/decode

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/string.py:445-447, 473-474`](../bytemaker/bittypes/string.py#L445)

**What.** When encoding= is a str, of() stashes it as encoding_name with no validation. An unknown codec name (typo like 'utf-99') mints a working-looking type; the failure only appears at the first encode/decode as a bare `LookupError: unknown encoding: utf-99` with no reference to the field or String class. The rest of of() is careful to fail early with class-named messages, so this is an inconsistency and a discoverability trap for the common typo case.

**Evidence.**

`elif isinstance(encoding, str): base = StandardEncodingString; ns['encoding_name'] = encoding` (lines 445-447); `return BitVector(value.encode(cls.encoding_name))` (line 474). Reproduced: `String.of(nbytes=4, encoding='utf-99')` mints; `T('AB')` raises `LookupError: unknown encoding: utf-99`.

**Suggestion.** At mint time, validate the codec exists, e.g. `codecs.lookup(encoding)` (raising a TypeError that names the class and the bad codec) before building the type. This turns a late cryptic LookupError into an actionable error at the declaration.

_Fairness-judge verified: Accurate and fair. Verified against current code: bytemaker/bittypes/string.py:445-447 stashes a str encoding= as `encoding_name` with no validation (`elif isinstance(encoding, str): base = StandardEncodingString; ns["encoding_name"] = encoding`), and line 473-474 (`return …_

---

## 33. String/Buffer repr shows raw bits and an endianness that is meaningless for text/byte fields, not the round-trippable value

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/string.py:43`](../bytemaker/bittypes/string.py#L43)

**What.** String and Buffer inherit BitType.__str__/__repr__, which render `bits=FixedLengthBitVector('01101000 ...')` and an `[big]` endianness tag. For a text field the string value is what a developer needs to see; the bit soup is unreadable and the endianness label is misleading (a String's wire contract is bytes, not an endian-swappable integer). repr() is supposed to help debugging, and for these types it actively hides the useful value.

**Evidence.**

Inherited from BitType (bittype.py lines 237-264). Observed: `str(UTF8String.of(nbytes=8)('hello'))` -> `UTF8Stringx8[big](hello = 01101000...00000000)` and `repr(...)` -> `UTF8Stringx8(bits=FixedLengthBitVector('01101000 01100101 ...'), endianness=big)` -- the human-readable 'hello' appears only in str, never in repr, and the [big] tag has no meaning for text.

**Suggestion.** Override __repr__ on String (and consider Buffer) to lead with the decoded value, e.g. `UTF8Stringx8('hello')` or include the value alongside a hex byte dump, and drop the endianness tag for types whose wire form is a byte sequence rather than an endian-swapped scalar.

_Fairness-judge verified: Verified empirically. Running `repr(UTF8String.of(nbytes=8)('hello'))` yields `UTF8Stringx8(bits=FixedLengthBitVector('01101000 01100101 01101100 01101100 01101111 00000000 00000000 00000000'), endianness=big)` and `str(...)` yields `UTF8Stringx8[big](hello = 01101000...00000000)`. Both match the …_

---

## 34. pop() 'from empty' message is misleading for non-empty out-of-range indexes

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_native.py:1157-1160`](../bytemaker/bitvector/bitvector_native.py#L1157)

**What.** The guard fires for ANY out-of-bounds index (`index >= len(self) or index < 0`), but the raised message always says 'pop from empty BitVector'. Calling `BitVector('1111').pop(99)` on a non-empty 4-bit vector reports it as empty, which actively misleads the user about what went wrong (index too large vs. no bits). The offending index and the actual length are both known but omitted. The bitarray backend shares the same defect (bitvector_with_bitarray_speedup.py:1086-1089).

**Evidence.**

if index >= len(self) or index < 0:\n            if default is not None:\n                return default\n            raise IndexError("pop from empty BitVector")

**Suggestion.** Raise a message that reflects the real condition and includes context, e.g. `raise IndexError(f"pop index {index} out of range for BitVector of length {len(self)}")`, and only say 'empty' when len(self) == 0.

_Fairness-judge verified: Accurate and real. Verified in current code: bytemaker/bitvector/bitvector_native.py:1157-1160 guards `if index >= len(self) or index < 0:` and unconditionally raises `IndexError("pop from empty BitVector")`, and bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1086-1089 does the same with …_

---

## 35. pop(default=...) silently swallows out-of-range errors, a silent-wrong footgun

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_native.py:1134-1163`](../bytemaker/bitvector/bitvector_native.py#L1134)

**What.** pop() accepts a `default` and returns it whenever the index is out of bounds, so `bv.pop(500, default=0)` returns 0 instead of raising, even though the caller almost certainly has a bug. Worse, because default defaults to None but the guard tests `if default is not None`, the API can't distinguish 'no default given' from 'default is None'; the branch is only taken for non-None defaults. list.pop/bytearray.pop have no such signature, so this both surprises users familiar with the stdlib and can silently mask indexing bugs. The bitarray backend has the same signature (bitvector_with_bitarray_speedup.py:1063-1090).

**Evidence.**

if index >= len(self) or index < 0:\n            if default is not None:\n                return default\n            raise IndexError("pop from empty BitVector")

**Suggestion.** Either drop the non-standard `default` parameter to match list/bytearray semantics, or use a sentinel (`_MISSING`) so an explicit `default=None` is honored and 'no default' still raises; document that a default suppresses IndexError.

_Fairness-judge verified: Confirmed in current code. bitvector_native.py:1134-1163 has `pop(self, index=None, default: Optional[T] = None)` with guard `if default is not None: return default` else raise IndexError; the bitarray backend at bitvector_with_bitarray_speedup.py:1063-1090 is identical. The evidence quote matches …_

---

## 36. Equal-length bitwise error omits the two actual lengths

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:874-875`](../bytemaker/bitvector/bitvector_speedup.py#L874)

**What.** &, |, ^ on mismatched-length vectors raise ValueError("BitVectors of equal length expected") with no indication of what the two lengths actually were. For a bit-manipulation library where off-by-one widths are the common mistake, the user must go add prints to find the discrepancy.

**Evidence.**

if other._len != self._len:
    raise ValueError("BitVectors of equal length expected")

**Suggestion.** Include both lengths: raise ValueError(f"BitVectors of equal length expected, got {self._len} and {other._len}").

_Fairness-judge verified: Accurate and fair. bytemaker/bitvector/bitvector_speedup.py:874-875 matches the quoted text exactly, and all bitwise ops (&, |, ^ plus r/i variants at lines 881-906) route through _binary_bitwise_op, so this is the error users actually hit on a width mismatch. The message withholds both operand …_

---

## 37. Extended-slice assignment error leaks the internal byte representation instead of talking about bits

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:1064-1070`](../bytemaker/bitvector/bitvector_speedup.py#L1064)

**What.** For an extended-slice length mismatch, __setitem__ delegates to bytearray's own slice assignment on the internal '01' ASCII buffer, so the surfaced error is "attempt to assign bytes of size 3 to extended slice of size 2" (verified). To a BitVector user this is confusing: the counts are bit counts, not 'bytes', and 'extended slice' leaks an implementation choice. The value they passed was a BitVector, not bytes.

**Evidence.**

chars[key] = value.to01().encode("ascii")
self._reset01(chars)   # -> ValueError('attempt to assign bytes of size 3 to extended slice of size 2')

**Suggestion.** Pre-check the span vs len(value) and raise a bit-oriented message, e.g. raise ValueError(f"cannot assign {len(value)} bits to a slice of {span} positions") mirroring the index-sequence branch just below (lines 1079-1083).

_Fairness-judge verified: Verified in current code at bytemaker/bitvector/bitvector_speedup.py:1064-1070. The extended-slice branch does `chars[key] = value.to01().encode("ascii"); self._reset01(chars)`, delegating length validation to bytearray's slice assignment on the internal '01' ASCII buffer. Reproduced the exact …_

---

## 38. Invalid construction source raises ValueError (not TypeError) and omits the offending value

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:341`](../bytemaker/bitvector/bitvector_speedup.py#L341)

**What.** Constructing from an unsupported type (e.g. BitVector(3.5)) raises ValueError(f"Invalid source type: {type(source)}"). A wrong *type* is conventionally a TypeError, so `except TypeError` around a constructor will miss it. The message prints the class but not the value; for a mistyped literal the value is the more useful diagnostic.

**Evidence.**

raise ValueError(f"Invalid source type: {type(source)}")

**Suggestion.** Raise TypeError and include a hint at accepted forms, e.g. raise TypeError(f"cannot construct BitVector from {source!r} of type {type(source).__name__}; expected BitVector, bytes, str, an int size, an iterable of 0/1, or a BitsCastable").

_Fairness-judge verified: Confirmed at bytemaker/bitvector/bitvector_speedup.py:341: `raise ValueError(f"Invalid source type: {type(source)}")`. This fires when a source of an unsupported *type* is passed to the constructor (e.g. BitVector(3.5)), which is conventionally a TypeError; `except TypeError` around construction …_

---

## 39. IndexError from pop() leaks internal 'bitarray' backend name to users

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1089`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1089)

**What.** This is the ACTIVE backend whenever the `bitarray` package is installed (bitvector.py dispatches here). When pop() is called on an empty/out-of-range vector, the user sees an error naming 'bitarray', an implementation detail they never chose to use. Users constructed a `BitVector`; the message should say BitVector. The pure-Python sibling (bitvector_speedup.py:1274 and bitvector_native.py:1160) correctly says 'pop from empty BitVector', so the two backends give DIFFERENT error text for the identical operation.

**Evidence.**

raise IndexError("pop from empty bitarray")

**Suggestion.** Change to `raise IndexError("pop from empty BitVector")` to match bitvector_native.py / bitvector_speedup.py and hide the backend from users.

_Fairness-judge verified: Verified accurate. bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1089 raises IndexError("pop from empty bitarray"). bitvector.py dispatches to this file whenever the bitarray package is installed, so it IS the active BitVector.pop() message real users hit. Both sibling backends …_

---

## 40. ValueError from index()/rindex() leaks 'bitarray' backend name

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1392, 1425`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1392)

**What.** In the active bitarray backend, index() and rindex() raise ValueErrors that name 'bitarray' instead of 'BitVector'. A user who called `bv.index(x)` gets `"... is not in bitarray"`, exposing a backend they didn't reference and diverging from the pure-Python sibling, which says 'is not in BitVector' (bitvector_native.py:1417/1444, bitvector_speedup.py:1560/1585). Same public method, two different messages depending on whether bitarray is installed.

**Evidence.**

raise ValueError(f"{value} is not in bitarray")   (appears at both line 1392 and line 1425)

**Suggestion.** Use `f"{value!r} is not in BitVector"` in both places to match the sibling backend and avoid leaking the dependency name.

_Fairness-judge verified: Accurate and reproducible. bytemaker/bitvector/bitvector.py:3-8 selects the bitarray backend (bitvector_with_bitarray_speedup) whenever `bitarray` is installed, so it is the default-active backend when the optional dep is present. In that backend, index() (line 1392) and rindex() (line 1425) both …_

---

## 41. oct() docstring says the result is 'prefixed by 0x' (should be 0o)

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:535`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L535)

**What.** In the active backend, oct()'s docstring wrongly states the output is prefixed by 0x. The code actually returns `"0o" + ...`. The pure-Python sibling has the correct wording ('prefixed by 0o', bitvector_native.py:556). A developer reading the docstring for the octal method is told the wrong prefix.

**Evidence.**

"""\n        Convert the BitVector to an octal string prefixed by 0x."  (line 535, method returns "0o" + self.tobase(8, ...))

**Suggestion.** Fix the docstring to 'Convert the BitVector to an octal string prefixed by 0o.' to match the code and the native backend.

_Fairness-judge verified: Accurate and real. bytemaker/bitvector/bitvector_with_bitarray_speedup.py:535 reads "Convert the BitVector to an octal string prefixed by 0x." while the method returns `"0o" + self.tobase(8, ...)` (line 546). This is the active backend when bitarray is installed (confirmed at …_

---

## 42. startswith/endswith docstrings say 'Checks if the bitarray...' leaking backend name

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1166, 1254`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1166)

**What.** In the active backend, the startswith() and endswith() docstrings describe the receiver as 'the bitarray' rather than 'the BitVector'. The pure-Python sibling correctly says 'Checks if the BitVector starts with...' (bitvector_native.py:1236/1276). This is mechanical drift that exposes the backend in the public API docs and makes the two implementations' help() output inconsistent.

**Evidence.**

"Checks if the bitarray starts with the given substring." (line 1166) and "Checks if the bitarray ends with the given substring." (line 1254)

**Suggestion.** Replace 'bitarray' with 'BitVector' in both docstrings to match the native backend and keep the class's public documentation self-consistent.

_Fairness-judge verified: Verified in current code. bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1166 says "Checks if the bitarray starts with the given substring." and line 1254 says "Checks if the bitarray ends with the given substring." Both sibling backends instead say "BitVector": …_

---

## 43. __contains__ falls through to an implicit None return instead of a bool

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:864-884`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L864)

**What.** __contains__ is declared `-> bool` but its final branch is guarded by `if isinstance(item, bitarray):` with no `else`, so any path reaching line 882 where item is not a bitarray returns None. Python coerces the None to False for the `in` operator, so it happens to behave, but the method is fragile: any future edit that lets a non-bitarray reach the tail silently yields a wrong membership answer with no error. The native sibling instead ends with an `assert isinstance(item, BitVector)` then a plain `return first_index != -1` (bitvector_native.py:908-910), which is safer.

**Evidence.**

if isinstance(item, bitarray):\n            first_index = self.find(item)\n            return first_index != -1   (no final return; method falls off the end returning None)

**Suggestion.** Add an explicit `return False` after the block (or restructure to the native backend's assert-then-return form) so every path returns a genuine bool.

_Fairness-judge verified: Verified accurate. In bytemaker/bitvector/bitvector_with_bitarray_speedup.py, __contains__ is declared `-> bool` (line 864) and its tail is guarded by `if isinstance(item, bitarray):` (lines 882-884) with no else, so a path reaching line 882 with a non-bitarray item would fall off the end and …_

---

## 44. Legacy aggregate API only reachable via a deep import; conversions/__init__.py is empty

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/__init__.py:1`](../bytemaker/conversions/__init__.py#L1)

**What.** conversions/__init__.py is a 0-byte file, so the conversions package re-exports nothing and its __all__ is undefined. The documented legacy entry points (to_bytes_aggregate/from_bytes_aggregate/pytype_to_bytes/ctype_to_bytes) are only importable via the full deep path bytemaker.conversions.aggregate_types.X. The top-level bytemaker/__init__.py docstring points users to 'bytemaker.conversions.aggregate_types' but nothing surfaces these names at bytemaker.conversions, hurting discoverability for the still-supported legacy API.

**Evidence.**

conversions/__init__.py is 0 bytes. Verified: import bytemaker.conversions as c; [n for n in dir(c) if not n.startswith('__')] == []; c.__all__ is undefined. Working import is from bytemaker.conversions.aggregate_types import to_bytes_aggregate.

**Suggestion.** Re-export the public legacy functions from conversions/__init__.py (to_bytes_aggregate, from_bytes_aggregate, to_bits_aggregate, from_bits_aggregate, pytype/ctype helpers) with an __all__, so users can do from bytemaker.conversions import to_bytes_aggregate.

_Fairness-judge verified: Factually accurate and verified. bytemaker/conversions/__init__.py is genuinely 0 bytes, so the package re-exports nothing (import bytemaker.conversions yields no public names, no __all__). The two sibling subpackages both re-export their public API — bytemaker/bittypes/__init__.py and …_

---

## 45. Malformed Args entry in to_bytes_aggregate docstring (stray bracket, no type)

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/aggregate_types.py:185`](../bytemaker/conversions/aggregate_types.py#L185)

**What.** The units parameter's Args line is malformed: it opens with a space and a stray '[' and an unbalanced ')' where a '(type):' should be. It renders as broken text in help()/generated docs and is inconsistent with the sibling from_bytes_aggregate docstring which formats parameters correctly.

**Evidence.**

units [Iterable | DataClassType]): The objects to convert to bytes

**Suggestion.** Fix to the standard form, e.g. 'units (Iterable | DataClassType): The objects to convert to bytes'.

_Fairness-judge verified: Confirmed by reading the current file. bytemaker/conversions/aggregate_types.py:185 literally reads "        units [Iterable | DataClassType]): The objects to convert to bytes" — a stray '[' where a '(' belongs and an unbalanced ')' with no matching open paren, so the Google-style type annotation …_

---

## 46. bytes/bytearray/memoryview conversions look registered but are dead (registration commented out)

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:215-222`](../bytemaker/conversions/pytypes.py#L215)

**What.** The loop over [bytes, bytearray, memoryview] constructs a ConversionInfo each iteration but its ConversionConfig.set_conversion_info call is commented out, so none of these types are actually registered. The code reads as live (a for-loop building conversion_info), yet converting a bytes value fails with a generic 'No conversion found' error that gives no hint these types were deliberately excluded. A developer will reasonably expect bytes to be convertible and get a confusing late failure.

**Evidence.**

for bytesish in [bytes, bytearray, memoryview]:\n    conversion_info = ConversionInfo(...)\n    # ConversionConfig.set_conversion_info(conversion_info)  <-- commented. Verified: pytype_to_bytes(b'\x01\x02') raises TypeError: No conversion found for <class 'bytes'>; has_suitable_conversion(bytes) is False.

**Suggestion.** Either uncomment the registration (if these should convert) or delete the dead loop and, in get_conversion_info's failure, add a hint listing which pytypes are supported (str, bool, int, float) so the error is actionable instead of a bare 'No conversion found'.

_Fairness-judge verified: Accurate and verified. bytemaker/conversions/pytypes.py:215-222 has a live-looking for-loop over [bytes, bytearray, memoryview] that builds a ConversionInfo each iteration but never registers it (line 222: "# ConversionConfig.set_conversion_info(conversion_info)" commented out). Runtime confirms: …_

---

## 47. pytype conversion functions misname/mistype their instance parameter as `type`

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:260-283, 62-73`](../bytemaker/conversions/pytypes.py#L260)

**What.** pytype_to_bits/pytype_to_bytes take a value instance to serialize, but the parameter is named py_prim and annotated `type`, and the docstrings call it 'The python instance' while the signature says type. Similarly ConversionInfo.to_bytes names its parameter `pytype` though it receives an instance. The signature and docstring disagree with the actual contract, so autocomplete/type-checkers mislead callers (e.g. suggesting they pass `int` rather than an int value).

**Evidence.**

def pytype_to_bytes(py_prim: type, endianness=...) -> bytes with docstring 'py_prim: The python instance to convert to bytes'. ConversionInfo.to_bytes: @classmethod def to_bytes(cls, pytype) -> bytes with docstring 'pytype (type): The Python instance to convert to bytes'.

**Suggestion.** Rename to a value-suggesting name and correct the annotation, e.g. def pytype_to_bytes(value: Any, ...) and 'value: the Python instance to serialize'; likewise ConversionInfo.to_bytes(cls, value).

_Fairness-judge verified: Verified all three cited locations in bytemaker/conversions/pytypes.py; the finding is accurate and fair. (1) pytype_to_bytes (line 281-282): `def pytype_to_bytes(py_prim: type, ...)` annotates the param `type`, but the docstring (line 289) says "py_prim: The python instance to convert to bytes" …_

---

## 48. Float aliases have no lazy factory, so `import f8`/`f128` gives a context-free AttributeError despite the docstring discussing float widths

**Severity:** low · **Confidence:** high · [`bytemaker/fields.py:15-17, 83, 88-91`](../bytemaker/fields.py#L15)

**What.** The module docstring explicitly discusses float widths and explains why only f16/f32/f64 exist ('an arbitrary float width does not determine an exponent/mantissa split'). But the regex only matches (u|s), so any `fN` name — a natural thing for a user to try given uN/sN 'just work' — falls straight through to the generic `raise AttributeError(f"module {__name__!r} has no attribute {name!r}")`. The user gets no hint that floats are a fixed IEEE set or that f16/f32/f64 are the supported spellings. The knowledge to give a helpful message lives right there in the docstring but is not surfaced in the error.

**Evidence.**

raise AttributeError(f"module {__name__!r} has no attribute {name!r}")   # regex: r"(u|s)([1-9][0-9]*)" never matches an f-prefixed name

**Suggestion.** Detect an f-prefixed numeric name in __getattr__ (e.g. a second regex r"f([0-9]+)") and raise an AttributeError that says float aliases are the fixed IEEE set {f16, f32, f64} because an arbitrary float width has no defined exponent/mantissa split, pointing the user at those names or at Float.specialize for custom splits.

_Fairness-judge verified: Accurate and reachable. In bytemaker/fields.py the lazy factory `__getattr__` (lines 88-91) matches only `_ALIAS_PATTERN = re.compile(r"(u|s)([1-9][0-9]*)")` (line 83), so f-prefixed numeric names fall through to the generic `raise AttributeError(f"module {__name__!r} has no attribute {name!r}")` …_

---

## 49. struct-tier pack failure surfaces a field-less 'not an integer' error

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:244-248`](../bytemaker/plans.py#L244)

**What.** On the aligned tier, pack_tuple first tries struct_obj.pack(*values); on TypeError/struct.error it retries with C-narrowed values. But _wrap_values only touches int-typed entries, so a bad value (None, a str, a float in an int slot) survives the retry and the SECOND struct.pack raises a raw struct.error with no field name and no offending value. A user packing a record with one mistyped field gets 'required argument is not an integer' and no clue which of their fields is at fault. Plan already knows the field names (self.fields), so this context is available but discarded.

**Evidence.**

`try: return self.struct_obj.pack(*values) except (_struct.error, TypeError): return self.struct_obj.pack(*self._wrap_values(values))` (lines 245-248). Confirmed: plan.pack_tuple([5, None]) and plan.pack_tuple(['x', 3]) both raise struct.error 'required argument is not an integer' with no field identification.

**Suggestion.** On the retry's failure, catch and re-raise with per-field context, e.g. locate the first value whose type/range is wrong via self.fields/_wrap_specs and raise ValueError naming `f.name`, the value, and the expected kind/range (mirroring validate_tuple's message shape).

_Fairness-judge verified: Accurate and reproducible. plans.py:244-248 retries struct pack with _wrap_values (lines 261-270), which only narrows isinstance(v,int) entries, so None/str/float survive and the second struct.pack raises a raw struct.error 'required argument is not an integer' with no field name. Confirmed …_

---

## 50. Plan._find KeyError gives no available-field list or record name

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:313-329`](../bytemaker/plans.py#L313)

**What.** bit_offset/byte_offset are the documented way to ask a Plan where a field lives. On a typo they surface KeyError('no field named 'bb''), which (a) lists neither the valid field names nor which record the plan belongs to, and (b) as a KeyError renders with confusing double-quoting in tracebacks. For an introspection helper the caller almost always wants 'did you mean...' or at least the set of names to choose from.

**Evidence.**

`raise KeyError(f"no field named {name!r}")` (line 318). Confirmed: p.byte_offset('bb') raises KeyError with message "no field named 'bb'" and no list of the real names (['a','b']).

**Suggestion.** Raise a ValueError (better traceback rendering than KeyError for a message) that includes the available names, e.g. `raise ValueError(f"no field named {name!r}; fields are {[f.name for f in self.fields]}")`.

_Fairness-judge verified: Accurate and reproducible. bytemaker/plans.py:318 has `raise KeyError(f"no field named {name!r}")`, reached via the public introspection helpers `bit_offset` (line 320) and `byte_offset` (line 324). I reproduced it: `p.byte_offset('bb')` yields `KeyError -> "no field named 'bb'"` with no list of …_

---

## 51. Bytes/Buffer field length error omits the field name

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:251-257`](../bytemaker/structs.py#L251)

**What.** _BytesField.__set__ raises a length error that names neither the field nor the owning Struct, unlike the sibling descriptors _StructField (names the type + value) and _UIntField/_SIntField narrowing warnings (name the field). In a record with several Buffer fields, 'expected exactly 4 bytes, got 2' gives the user no clue which field was wrong. Verified live: `s.b = b'ab'` -> `ValueError: expected exactly 4 bytes, got 2`.

**Evidence.**

raise ValueError(
    f"expected exactly {self._nbytes} bytes, got {len(v)}"
)

**Suggestion.** Thread the field name into _BytesField (as _UIntField/_SIntField already do via self._slot.__name__[4:]) and include it: e.g. f"field {self._slot.__name__[4:]!r}: expected exactly {self._nbytes} bytes, got {len(v)}".

_Fairness-judge verified: Accurate and verified live. bytemaker/structs.py:254-256 raises `ValueError("expected exactly {self._nbytes} bytes, got {len(v)}")` naming neither the field nor the owning Struct. Reproduced: `s.b = b'ab'` -> `ValueError: expected exactly 4 bytes, got 2`. The sibling descriptors in the same file DO …_

---

## 52. Wrong-type store to an int field surfaces a raw operator.index TypeError with no field/struct context

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:170-176`](../bytemaker/structs.py#L170)

**What.** _UIntField/_SIntField.__set__ call operator.index(value) directly, so passing a str/float to an integer field (including through the generated __init__) raises Python's bare `'str' object cannot be interpreted as an integer` with no mention of the field name or the Struct. Verified live: `S('x')` and `S(3.5)` both yield `TypeError: 'str' object cannot be interpreted as an integer`, and the traceback points at codegen'd __init__, not the offending field. The string/struct/bytes descriptors all give contextual messages; the int path is the odd one out.

**Evidence.**

def __set__(self, obj, value):
    iv = operator.index(value)
    v = iv & self._mask

**Suggestion.** Wrap operator.index in try/except and re-raise with context, e.g. `raise TypeError(f"field {self._slot.__name__[4:]!r} expects an int, got {value!r}") from None`; do the same in _coerce_one for array elements.

_Fairness-judge verified: Core observation verified live. `_UIntField.__set__`/`_SIntField.__set__` (bytemaker/structs.py:171, 192) call `operator.index(value)` directly, and `Array._coerce_one` (structs.py:1417) mirrors it. Passing a str/float to an int field — including via the codegen'd `__init__`, whose body is just …_

---

## 53. Array-length error message never names the offending field

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:1394-1399`](../bytemaker/structs.py#L1394)

**What.** Array._coerce_seq raises a generic 'array field expects exactly N elements, got M' with no field name, so on a Struct with multiple array fields the user cannot tell which one was mis-sized. The descriptor (_ArrayField) has the field name available via its slot but does not pass it down. Verified live: `s.xs = [1,2]` on `array(UInt8, 3)` -> `ValueError: array field expects exactly 3 elements, got 2`.

**Evidence.**

raise ValueError(
    f"array field expects exactly {self._count} elements,"
    f" got {len(seq)}"
)

**Suggestion.** Pass the field name from _ArrayField.__set__ into _coerce_seq (or catch and re-raise there) so the message reads e.g. `field 'xs': array expects exactly 3 elements, got 2`.

_Fairness-judge verified: Accurate and fair. Verified live: on a Struct with two array fields (e.g. `xs: UInt8 * 3`, `ys: UInt8 * 2`), a wrong-length assignment `s.xs = [1, 2]` raises exactly `array field expects exactly 3 elements, got 2` (bytemaker/structs.py:1396-1399, inside Array._coerce_seq) with no field name. On a …_

---

## 54. Float field overflow raises a codec-internal OverflowError with no field context

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:213-217`](../bytemaker/structs.py#L213)

**What.** _FloatField.__set__ narrows via self._ftype(float(value)).value; storing a value too large for the field width raises `OverflowError: float too large to pack with f format` from deep inside bittypes/bittype.py, naming neither the field nor the Struct. Verified live: `S(1e300)` on a Float32 field yields that traceback pointing at bittype.py line 593, not the field. (Related to the already-reported float to_binstring crashes, but the distinct DX angle here is the missing field/struct context on the _FloatField store path.)

**Evidence.**

self._slot.__set__(obj, self._ftype(float(value)).value)

**Suggestion.** Catch OverflowError/ValueError from the codec cast and re-raise with the field name and the offending value, e.g. `raise ValueError(f"field {self._slot.__name__[4:]!r}: {value!r} does not fit a {self._ftype.__name__}") from exc`.

_Fairness-judge verified: Verified live and accurate on every checkable claim. bytemaker/structs.py:217 is exactly `self._slot.__set__(obj, self._ftype(float(value)).value)`. Reproducing `S(1e300)` on a Float32 field raises `OverflowError: float too large to pack with f format` originating at bittype.py:593 (the finding …_

---

## 55. array() has an endian parameter that its docstring never documents

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:648-657`](../bytemaker/structs.py#L648)

**What.** array() accepts keyword-only `endian` and `default`, but its one-line docstring documents neither -- it only describes the element/count and the list-checker sugar. A user reading help(array) has no way to learn that per-array byte order can be forced here (which matters: an unset array field inherits the record endianness, per the Array.__init__ note, so the override is non-obvious and undocumented). field()'s docstring likewise never mentions its `default` keyword.

**Evidence.**

def array(
    element: Any,
    count: int,
    *,
    endian: Any = None,
    default: Any = _MISSING,
) -> Any:
    """Declare a fixed-count array field: ``colors: list[int] = array(UInt16, 8)``.
    Sugar for ``field(element * count)`` with a plain-list checker type."""

**Suggestion.** Add a short param list to array()'s docstring covering `endian` (default: inherit the record's byte order) and `default`, and mention `default` in field()'s docstring.

_Fairness-judge verified: Accurate and fair. Verified in current code: bytemaker/structs.py array() (lines 648-657) declares keyword-only `endian` and `default`, but its two-line docstring ("Declare a fixed-count array field... Sugar for field(element * count)...") documents neither; field() (lines 631-645) likewise …_

---

## 56. Bitwise binary operators refuse silently with no hint, unlike __invert__

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/float.py:362-390`](../bytemaker/bittypes/float.py#L362)

**What.** The module deliberately disables value-plane bitwise ops and the code comment (lines 357-360) promises 'the bit-plane spelling is explicit: f.bits & other'. __invert__ delivers exactly that guidance in its TypeError. But the ten binary/shift dunders just return NotImplemented, so the user who types `f & 3` or `f << 2` gets Python's generic "unsupported operand type(s) for &: 'Float32' and 'int'" with no pointer to the f.bits spelling. The result is an inconsistent DX: unary ~ teaches the workaround, the far more commonly attempted binary & / | / ^ / << / >> do not, even though the whole point of overriding them was to steer users to the bit-plane spelling.

**Evidence.**

Lines 362-390 each 'return NotImplemented' (e.g. 'def __and__(self, other):\n        return NotImplemented'). Contrast __invert__ (lines 392-396): raise TypeError(... '(the bit-plane spelling is ~self.bits)'). Observed: `f & 3` -> TypeError "unsupported operand type(s) for &: 'Float32' and 'int'" (no hint); `~f` -> TypeError "... (the bit-plane spelling is ~self.bits)".

**Suggestion.** Either raise a TypeError from these ops with the same teaching hint (e.g. 'bitwise & is not defined on Float values; use f.bits & other for the bit plane'), consistent with __invert__, or add that guidance to the class docstring so at least one discoverable place documents the f.bits workaround.

_Fairness-judge verified: Accurate and reproducible. In bytemaker/bittypes/float.py, the ten binary/shift dunders (lines 362-390) each `return NotImplemented`, while `__invert__` (lines 392-396) raises `TypeError(... "(the bit-plane spelling is ~self.bits)")`. I confirmed the runtime behavior on a Float32 instance: `~f` -> …_

---

## 57. specialize() leaks trailing-underscore parameter names into the public signature

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/float.py:214-220`](../bytemaker/bittypes/float.py#L214)

**What.** specialize is a public, documented factory (referenced by the class docstring as the way to make custom widths), but every parameter carries an internal trailing underscore (num_exponent_bits_, num_mantissa_bits_, packing_format_letter_, name_) because the body reuses the bare names for the class-body assignments. A user calling it by keyword must write the ugly Float.specialize(num_exponent_bits_=5, num_mantissa_bits_=10), and inspect.signature / IDE autocomplete surface the underscored names. The prose in the docstring even refers to them without the underscore ('If `packing_format_letter` is provided', line 225), so the documented name and the real keyword disagree.

**Evidence.**

Signature (lines 214-220): 'def specialize(cls, num_exponent_bits_, num_mantissa_bits_, packing_format_letter_: Optional[str] = None, name_: Optional[str] = None,)'. inspect.signature(Float.specialize) -> '(num_exponent_bits_, num_mantissa_bits_, packing_format_letter_: 'Optional[str]' = None, name_: 'Optional[str]' = None)'. Docstring line 225 says '`packing_format_letter`' (no underscore).

**Suggestion.** Rename the public parameters to num_exponent_bits / num_mantissa_bits / packing_format_letter / name and assign them into locals for the nested class body (e.g. `_nexp = num_exponent_bits`), so the public keyword names are clean and match the prose.

_Fairness-judge verified: The finding's headline thesis is UNFAIR, but it contains one genuine, salvageable sub-defect. Verified in current code:  WHAT'S REAL (and float-specific): float.py:225 docstring says `packing_format_letter` (no underscore) while the actual parameter is `packing_format_letter_` (float.py:218). That …_

---

## 58. String base class has no docstring while every sibling BitType does; base String not exported as a mint entry point

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/string.py:43-44`](../bytemaker/bittypes/string.py#L43)

**What.** class String(BitType[str]) has no class docstring at all, unlike Buffer, Int, Float, StandardEncodingString, and TableString. String is the primary text base and holds the headline of() classmethod plus all the pad/terminator/strip/errors/bytes_per_char knobs (documented only in a code comment at lines 47-65, not a docstring), so `help(String)` and IDE hover show nothing. A user discovering the text API gets no orientation on where to start.

**Evidence.**

`class String(BitType[str]):\n    py_type = str` (lines 43-44) -- no docstring. The field-schema knobs are explained in a bare comment block (lines 47-65) beginning `# Field-schema knobs (active when num_bits is a whole number of bytes; ...` rather than in a class docstring.

**Suggestion.** Add a short class docstring to String summarizing it as the text-field base and pointing at String.of(...) / concrete subclasses (UTF8String, TableString). Promote the field-knob comment (pad/terminator/strip/errors/truncate/bytes_per_char) into the docstring so help() and tooltips surface it.

_Fairness-judge verified: Core claim verified. bytemaker/bittypes/string.py line 43 `class String(BitType[str]):` has no class docstring (line 44 is `py_type = str`, followed by a bare `# Field-schema knobs...` comment block at lines 46-65). Meanwhile every sibling BitType has a class docstring: Buffer (buffer.py:17), Int …_

---

## 59. Stale 'Bits object' terminology in from_int/to_int/from_bytes docstrings confuses the actual return type

**Severity:** low · **Confidence:** medium · [`bytemaker/bitvector/bitvector_speedup.py:1800-1835`](../bytemaker/bitvector/bitvector_speedup.py#L1800)

**What.** The transitional from_int/to_int/from_bytes docstrings describe the class as a "Bits object" ("Converts an integer to a Bits object", "Converts a Bits object to an integer", "casting the Bits to bytes") even though the class is BitVector and no 'Bits' type exists. Combined with the from_int ValueError which also says "...to Bits with size 4...", a user grepping for the type or reading the error is pointed at a non-existent name. This is a leftover from the pre-rename era.

**Evidence.**

"""
Converts an integer to a Bits object.
...
raise ValueError(
    f"Cannot convert {integer} to Bits with size {size},"

**Suggestion.** Replace 'Bits object'/'the Bits' with 'BitVector' in these docstrings and in the from_int error message so terminology matches the actual public type.

_Fairness-judge verified: Accurate and verified against current code. The class is BitVector (bytemaker/bitvector/bitvector_speedup.py:178) and no `Bits` type exists anywhere in the package (grep for `class Bits` returns nothing). The transitional methods still describe the type as a "Bits object": line 1802 "Converts an …_

---

## 60. Stub (.pyi) caps uN/sN at width 64 while the runtime supports any width, so checked code past 64 silently loses precise typing

**Severity:** low · **Confidence:** medium · [`bytemaker/fields.pyi:9-11, 28-156`](../bytemaker/fields.pyi#L9)

**What.** The runtime module mints uN/sN for arbitrary N (u128, u256, u1000), and canonical BitType classes exist up to 128/256. The stub only declares u1..u64 and s1..s64 as descriptor classes; everything else falls to `def __getattr__(name: str) -> Any: ...`. The stub itself admits this ('Widths past 64 resolve at runtime via the module __getattr__; they type as Any here'), but the effect is a silent DX cliff: `x: u128` type-checks as a bare descriptor/Any and the read/write channel typing (int on read, SupportsIndex on write) that u1..u64 get is lost exactly for the wide fields where a mistyped huge literal is most likely. The .py/.pyi 'must agree' expectation (unit hint) holds only up to 64.

**Evidence.**

"Widths past 64 resolve at runtime via the module __getattr__; they type as\nAny here."  ...  class u64(_UIntAlias): ...   (no u65+)   ...   def __getattr__(name: str) -> Any: ...

**Suggestion.** Either document the 64-bit typing cliff more prominently at the alias-usage site, or make the stub __getattr__ return a descriptor-typed alias (e.g. -> _UIntAlias) for u/s names so wide fields still type reads as int and writes as SupportsIndex instead of degrading to Any.

_Fairness-judge verified: Verified against current code. The runtime (bytemaker/fields.py:88-111, docstring line 8 "Any integer width works") genuinely mints uN/sN for arbitrary N — confirmed empirically: `bytemaker.fields.u128` -> `Annotated[int, UInt128]`, `s200` -> a minted SInt specialization. The stub …_

---

## 61. FixedLengthBitVector length-violation message does not name the attempted operation

**Severity:** low · **Confidence:** low · [`bytemaker/bitvector/fixed.py:33-38`](../bytemaker/bitvector/fixed.py#L33)

**What.** A single _length_violation() helper is reused across append, extend, insert, pop, remove, clear, __delitem__, __iadd__, __imul__, frombytes, fromfile, and __setitem__. The resulting ValueError always reads "width-changing mutation is not allowed" without naming which call triggered it, so in a stack of chained operations the user cannot tell whether it was e.g. `+=` vs `.append` vs a resizing slice assignment without inspecting the traceback frame.

**Evidence.**

return ValueError(
    f"length is invariant ({len(self)} bits): width-changing"
    f" mutation is not allowed on a FixedLengthBitVector; make a"
    f" resizable copy with BitVector(...) first"
)

**Suggestion.** Pass the operation name into the helper (def _length_violation(self, op): ...) and interpolate it, e.g. "append() would change the length ... FixedLengthBitVector length is invariant (N bits)".

_Fairness-judge verified: Accurate as to the code: bytemaker/bitvector/fixed.py:33-38 defines a single `_length_violation()` helper reused verbatim by append/extend/insert/pop/remove/clear/__delitem__/__iadd__/__imul__/frombytes/fromfile/__setitem__ (lines 40-88), and the ValueError message never names the triggering …_

---

## 62. classproperty getter/setter/deleter AttributeErrors omit the attribute name

**Severity:** low · **Confidence:** low · [`bytemaker/utils.py:40, 45, 51`](../bytemaker/utils.py#L40)

**What.** classproperty raises 'unreadable attribute', "can't set attribute", and "can't delete attribute" with no attribute name. Python's own built-in property was upgraded in 3.11 to include the attribute name (e.g. "property 'x' of 'C' object has no setter"). On a class with several classproperties, a bare "can't set attribute" forces the developer to hunt for which one they touched. Since __get__ already receives objtype, the class and attribute are available to name.

**Evidence.**

if self.fget is None:
            raise AttributeError("unreadable attribute")
...
        if self.fset is None:
            raise AttributeError("can't set attribute")
...
        if self.fdel is None:
            raise AttributeError("can't delete attribute")

**Suggestion.** Include context, e.g. raise AttributeError(f"unreadable classproperty on {objtype.__name__}") and f"can't set classproperty on {type(obj).__name__}", matching the informativeness of built-in property in 3.11+.

_Fairness-judge verified: The cited code is present verbatim in bytemaker/utils.py at lines 40 ("unreadable attribute"), 45 ("can't set attribute"), and 51 ("can't delete attribute"). The factual claims check out: classproperty is applied to multiple properties on a single class (e.g. ByteConvertibleString in …_

---
