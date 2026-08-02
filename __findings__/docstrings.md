# Docstrings

> **Status: verified discovery pass.** Single-pass sweep of this lens, each finding then checked by an independent fairness judge that read the cited code and dropped nitpicks / inaccuracies / flags of the intentional house style (26 of 137 candidates were rejected across the three lenses). Skews toward polish. See [README.md](README.md).

Sloppy or inaccurate docstrings and drift from the 4-weeks-ago house style: wrong/phantom parameters, stale references, copy-paste leftovers, Returns/Raises that misstate behavior, and format drift. The intentional narrative module-docstring style in structs/plans/fields is not itself flagged.

_39 findings — 0 high, 8 medium, 31 low._

---

## 1. __repr__ Returns line misstates the actual repr format

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/bittype.py:254-264`](../bytemaker/bittypes/bittype.py#L254)

**What.** The __repr__ docstring's Returns clause describes a format string that does not match what the method produces. It shows a spurious '(value)' after the class name and claims the bits slot renders the value ('bits={self.value}'), but the code renders 'bits={self.bits}' (a BitVector) with no '(value)' segment. Actual output: UInt6(bits=FixedLengthBitVector('101000'), endianness=big). A reader relying on the docstring would expect a different, non-round-trippable string. This is pre-existing (identical in the 4-weeks-ago reference; not on the already-reported list) and still present.

**Evidence.**

Docstring: "Returns:\n            str: ClassName(value)(bits={self.value}, {endianness=self.endianness})". Code: `return (f"{self.__class__.__name__}(bits={self.bits}, endianness={self.endianness})")`. Verified output: `UInt6(bits=FixedLengthBitVector('101000'), endianness=big)`.

**Suggestion.** Rewrite the Returns line to match the code, e.g. "str: ClassName(bits=<BitVector>, endianness=<endianness>)", dropping the '(value)' fragment and the '{self.value}' reference.

_Fairness-judge verified: Confirmed by reading bytemaker/bittypes/bittype.py:254-264 and by running the code. The __repr__ Returns clause (line 260) reads "str: ClassName(value)(bits={self.value}, {endianness=self.endianness})" but the body (lines 262-264) is `f"{self.__class__.__name__}(bits={self.bits}, …_

---

## 2. Buffer class docstring duplicated as an orphaned bare string literal

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/buffer.py:40-45`](../bytemaker/bittypes/buffer.py#L40)

**What.** Immediately after the real class docstring (lines 17-38), a second bare triple-quoted string repeats the opening two paragraphs of that same docstring. It is not the class docstring (the first one already occupies that slot) and is not assigned to anything, so it is inert leftover text -- a copy-paste fragment that was never removed. It duplicates content verbatim and clutters the class body, and a reader/tool sees the same prose twice.

**Evidence.**

Real docstring at line 17 begins: '"""\n    A BitType that represents a buffer of bits.\n\n    Use the `specialize` method to create a subclass with the desired number of bits\n        or use one of the pre-defined subclasses.' ... then lines 40-45 repeat it as a dangling literal:
    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.
    """

**Suggestion.** Delete the orphaned string literal at lines 40-45; the class docstring at lines 17-38 already covers this.

_Fairness-judge verified: Verified in current code. bytemaker/bittypes/buffer.py lines 17-38 hold the real class docstring (first statement in the class body, so it becomes Buffer.__doc__). Lines 40-45 are a second, unassigned bare triple-quoted string literal that verbatim repeats the opening two paragraphs ("A BitType …_

---

## 3. Float class docstring says it 'represents an integer'

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:23-24`](../bytemaker/bittypes/float.py#L23)

**What.** The one-line summary of the Float class is wrong: Float represents a floating-point number, not an integer. This is a copy-paste leftover from the Int class docstring (bytemaker/bittypes/int.py:30 reads 'A `BitType` that represents an integer.'). The class defines py_type = float (line 56) and the whole file is about IEEE-754-style float encoding, so the summary line actively misleads a reader/API-doc consumer about what the type is. Present in the 4-weeks-ago reference (float.cpython-311.pyc) as well, so it is long-standing rather than new drift, but still a genuine misleading doc.

**Evidence.**

Lines 23-24:
"""
    A BitType that represents an integer.

while the class is `class Float(BitType[float])` with `py_type = float` (line 56).

**Suggestion.** Change the summary to e.g. 'A BitType that represents an IEEE-754-style floating-point number.' to match the actual type (mirroring how Int's docstring is phrased, but for float).

_Fairness-judge verified: Verified directly: bytemaker/bittypes/float.py:24 reads "A BitType that represents an integer." while the class is `class Float(BitType[float])` with `py_type = float` (line 56) and the rest of the docstring describes IEEE-754 sign/exponent/mantissa float encoding. int.py:30 has the identical …_

---

## 4. to_pyint documents a nonexistent `bitstring` parameter and omits its real params

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/int.py:76-89`](../bytemaker/bittypes/int.py#L76)

**What.** The Parameters section documents a leading `bitstring (str): The bitstring to convert.` argument, but the method signature is `to_pyint(self: BitType | BitsConstructible, signed=None, bin_format=...)` — there is no `bitstring` parameter. The bit source is passed as `self` (the method converts `self`, coercing a BitType/BitVector/BitsConstructible to a bitstring internally). A reader following the docstring would try to pass a `bitstring=` argument that does not exist. This is pre-existing (byte-identical to the 4-weeks-ago reference int.pyc), so it is not new drift, but it actively misdescribes the current signature.

**Evidence.**

Docstring: 'Parameters:\n        - bitstring (str): The bitstring to convert.\n        - signed (Optional[bool], optional) ...' vs signature `def to_pyint(self: BitType | BitsConstructible, signed: Optional[bool] = None, bin_format: Literal[...] = "twos_complement")` — no `bitstring` param exists; `self` is undocumented.

**Suggestion.** Replace the phantom `bitstring (str)` entry with documentation of the actual receiver (`self`: a BitType / BitVector / BitsConstructible whose bits are converted), keeping `signed` and `bin_format`.

_Fairness-judge verified: Verified against current code at bytemaker/bittypes/int.py:69-89. The signature is `def to_pyint(self: BitType | BitsConstructible, signed=None, bin_format=...)` — there is no `bitstring` parameter. Yet the docstring's Parameters section (line 80) leads with `- bitstring (str): The bitstring to …_

---

## 5. SInt docstring points readers at a `Config` class that does not exist (should be SignedConfig)

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/int.py:545-547, 561`](../bytemaker/bittypes/int.py#L545)

**What.** The SInt docstring twice tells the user to use "the `Config` class" to change the signed integer format, but the only such class in the module (and the one the constructor actually reads at line 582) is `SignedConfig`. There is no `Config` symbol anywhere in the package. A user searching for `Config` to set `signed_int_format` would fail. Pre-existing (matches the reference), not new drift, but it is a stale/wrong cross-reference in current code.

**Evidence.**

'To change the signed integer format, use the `Config` class (or set the `int_format` parameter in the constructor).' and 'If this is left as `None`, the format will be taken from the `Config` class.' — but the class is `class SignedConfig:` (line 525) and `__init__` reads `SignedConfig.signed_int_format` (line 582).

**Suggestion.** Rename `Config` to `SignedConfig` in both places, matching the actual class name and the constructor's `int_format = SignedConfig.signed_int_format` default.

_Fairness-judge verified: Verified directly in bytemaker/bittypes/int.py. The SInt docstring says "use the `Config` class" (line 545-546) and "the format will be taken from the `Config` class" (line 561), but no `class Config` exists anywhere in the package (grep for `class Config\b` across bytemaker/ returns zero matches). …_

---

## 6. String base class has no docstring though every peer BitType base documents itself

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/string.py:43`](../bytemaker/bittypes/string.py#L43)

**What.** class String(BitType[str]) -- the primary public abstract base of the string module and the entry point users subclass -- carries no class docstring, jumping straight to 'py_type = str'. Every sibling BitType base is documented: Int (int.py:29 'A `BitType` that represents an integer.'), SInt (int.py:539), UInt (int.py:767), Float (float.py:23), and even Buffer (buffer.py:17). The absence is conspicuous inconsistency on the headline public class of the file, and it leaves the whole padding/terminator/strip/codepoint-substitution contract discoverable only via a bare block comment on the class attributes.

**Evidence.**

class String(BitType[str]):
    py_type = str

    # Field-schema knobs (active when num_bits is a whole number of bytes; ... -- a comment, not a docstring. By contrast Buffer opens: 'class Buffer(BitType[BitVector]):\n    """\n    A BitType that represents a buffer of bits. ..."""'

**Suggestion.** Add a class docstring for String describing it as the text BitType base, the encode/decode contract, and pointing to of()/specialize(), consistent with the Int/Buffer bases.

_Fairness-judge verified: Verified accurate. bytemaker/bittypes/string.py:43 `class String(BitType[str]):` has no class docstring — line 44 jumps straight to `py_type = str`, followed only by a block comment (lines 46-55) on the class attributes. Every cited sibling base does document itself: Int (int.py:29 "A `BitType` …_

---

## 7. __Bits__ docstring promises a "deep" copy that the class docstring explicitly disclaims

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_speedup.py:65-70, 76-83`](../bytemaker/bitvector/bitvector_speedup.py#L65)

**What.** The BitsCastable class docstring was rewritten (since the 4-weeks-ago reference, where it was just the placeholder 'BitsCastable') to describe the live-.bits policy: it now says whether __Bits__ returns a copy or a live view is the implementor's choice, and gives BitType as an example that deliberately returns its bits *live* and width-locked. But the __Bits__ method docstring was left unchanged and still promises a *deep* representation. The two docstrings on the same protocol now directly contradict each other, and the method-level promise is the one that is wrong: an implementor is explicitly permitted (and BitType is documented) to return a live view, not a deep copy. This same stale 'deep' line is present identically in bitvector_native.py:76 and bitvector_with_bitarray_speedup.py:80, so the drift is consistent across all three backends.

**Evidence.**

Class docstring (lines 66-70): "Constructors copy-construct from the result... whether __Bits__ itself returns a copy or a live view is the implementor's ownership choice. (BitType returns its internal bits live and width-locked, per the live-.bits policy; construct a BitVector for a snapshot.)"  --- but the method docstring (line 77) still says: "Returns a deep BitVector representation of the object."  Confirmed against the 4-weeks-ago reference: the class docstring then was merely 'BitsCastable' while __Bits__ already read 'Returns a deep BitVector representation of the object.'

**Suggestion.** Reword the __Bits__ method docstring to match the class docstring, e.g. "Returns a BitVector representation of the object; may be a copy or a live view (implementor's choice)." Drop the word 'deep'. Apply the same fix to bitvector_native.py and bitvector_with_bitarray_speedup.py so all three backends agree.

_Fairness-judge verified: Verified against current code and the 4-weeks-ago reference. In all three backends (bitvector_speedup.py:65-83, bitvector_native.py:64-82, bitvector_with_bitarray_speedup.py:68-86) the BitsCastable *class* docstring now states "whether __Bits__ itself returns a copy or a live view is the …_

---

## 8. bits_to_pytype docstring documents nonexistent parameter names and wrong type

**Severity:** medium · **Confidence:** high · [`bytemaker/conversions/pytypes.py:302-314`](../bytemaker/conversions/pytypes.py#L302)

**What.** The Args block for bits_to_pytype names two parameters (`bytes_obj` and `py_prim_type`) that do not exist in the signature `def bits_to_pytype(bits_obj: BitVector, pytype: type)`. It also mislabels the first parameter's type as `(bytes)` when it is actually a BitVector. A reader following the docstring would pass the wrong keyword names and expect a bytes argument. This looks like a copy-paste from bytes_to_pytype (whose params really are `bytes_obj`/`pytype`) left unedited.

**Evidence.**

Signature: `def bits_to_pytype(bits_obj: BitVector, pytype: type):`  Docstring: "Args:\n        bytes_obj (bytes): The bits object to convert to a Python primitive\n        py_prim_type (type): The type of the Python primitive to convert to."

**Suggestion.** Rename the documented params to `bits_obj (BitVector)` and `pytype (type)` to match the signature; fix the type annotation from `bytes` to `BitVector`.

_Fairness-judge verified: Verified in current code at bytemaker/conversions/pytypes.py:302-314. Signature is `def bits_to_pytype(bits_obj: BitVector, pytype: type)`, but the Args block documents `bytes_obj (bytes)` and `py_prim_type (type)` — neither param name exists in the signature, and the type `bytes` is wrong (actual …_

---

## 9. StructPackedBitType class docstring says packing_format depends on endianness, contradicting the property

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:535-537`](../bytemaker/bittypes/bittype.py#L535)

**What.** The StructPackedBitType class-body docstring documents packing_format as "calculated based on the endianness", but the packing_format property's own docstring and code state it ALWAYS uses big-endian ('>') and applies endianness later at the bytes boundary. The two docstrings within the same class directly contradict each other. Pre-existing (present in the reference) but still present and misleading; not on the already-reported list.

**Evidence.**

Class docstring: "packing_format : str\n        The struct-packing format for the subclass that `struct` uses. It is calculated\n            based on the endianness". Property docstring: "Always uses big-endian format because bits are stored in canonical big-endian order internally. Endianness is applied at the bytes boundary by BitType.__bytes__()." Code: `return f">{cls.packing_format_letter}"` (always '>').

**Suggestion.** Change the class-attribute line to match reality, e.g. "The struct-packing format (always big-endian '>'); endianness is applied later at the bytes boundary."

_Fairness-judge verified: Verified in current code at bytemaker/bittypes/bittype.py. The StructPackedBitType class-body docstring (lines 535-537) documents "packing_format : str ... It is calculated based on the endianness", while the packing_format property's own docstring (lines 558-560) states "Always uses big-endian …_

---

## 10. New narrative-RST docstrings mixed into the field-list-style bittype.py module

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:27-46, 68-72, 266-274, 276-286, 414-445`](../bytemaker/bittypes/bittype.py#L27)

**What.** bittype.py is a reference-era mature file whose original docstrings use Google/field-list style (Args:/Returns:, :cvar:/:vartype:) - and the surviving reference docstrings (BitType, endianness, value, __eq__, bytes_to_bittype, etc.) still do. The July additions inject the narrative-RST style from the new structs/plans/fields files into this same module: '::' literal code blocks, ':class:`X`' roles, '**bold**', and em-dash-heavy prose. That narrative style is intentional in the new files, but here it produces mechanical format drift and a mixed-style module. Examples: NarrowingWarning/NarrowingConfig (::/:class:), BitTypeMeta, __format__, __Bits__, _promoted_value_op / _inplace_value_op (em-dash-heavy, no Args:/Returns:), sitting beside num_bits/value/bits which use 'Returns:' field lists.

**Evidence.**

Narrative (new): NarrowingWarning uses "escalate to an error with the stdlib warnings filters if desired::\n\n        warnings.simplefilter(...)" and ":class:`NarrowingConfig`"; _promoted_value_op: "returns the **plain** result — no re-boxing, no wrap-at-operator (C never wraps mid-expression; ...)". Field-list (reference-era, same file): num_bits: "Returns:\n            int: The number of bits in the BitType."; value setter: "Args:\n            value (T): The new value for the BitType."

**Suggestion.** Either accept the drift deliberately, or bring the new helper docstrings closer to the file's field-list norm (add Args:/Returns: where they document parameters/returns) so one module doesn't mix two docstring conventions.

_Fairness-judge verified: Accurate and fair, and it lands in a category the house style guide explicitly says to flag ("MECHANICAL format drift that creates inconsistency (mixing :param: field-lists and narrative within one module)"), not the forbidden "flag narrative merely for differing" category. Verified in current …_

---

## 11. __eq__/__ne__ docstring contains a broken, word-dropping sentence

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:288-317`](../bytemaker/bittypes/bittype.py#L288)

**What.** Both __eq__ and __ne__ carry the sentence 'Note that this means that they might have internal bit representations (-0 and +0 are still equal, though)', which is missing words (presumably 'differing internal bit representations') and does not parse as written. It documents the equality contract of two public dunder methods. Pre-existing (identical in the reference) and still present in both methods.

**Evidence.**

"Two bittypes are equal if their values are equal. Note that this means that they might have internal bit representations (-0 and +0 are still equal, though)" (verbatim in both __eq__ lines 289-300 and __ne__ lines 306-317).

**Suggestion.** Complete the sentence, e.g. "...this means two equal BitTypes may still have differing internal bit representations (e.g. -0 and +0 are equal)."

_Fairness-judge verified: Accurate and fair. Verified verbatim in current code: bytemaker/bittypes/bittype.py lines 292-293 (__eq__) and 309-310 (__ne__) both carry "Two bittypes are equal if their values are equal. Note that this means that they might have internal bit representations (-0 and +0 are still equal, though)". …_

---

## 12. Float class docstring's py_type entry references `Int` instead of Float

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/float.py:42`](../bytemaker/bittypes/float.py#L42)

**What.** Inside the Float class docstring, the py_type class-attribute description says 'The Pythonic type that this `Int` can be converted to/from.' The wrong class name `Int` is a copy-paste leftover from the Int class docstring (bytemaker/bittypes/int.py:41 reads 'The Pythonic type that this Int can be converted to/from. It is int.'). Here it is documenting a Float, so the reference to `Int` is stale/incorrect. The 'It is `float`' tail is correct, which makes the mixed-up class name more clearly a copy-paste artifact. Also present in the 4-weeks-ago reference .pyc, so pre-existing.

**Evidence.**

Line 42:
    py_type : Type[float]
        The Pythonic type that this `Int` can be converted to/from. It is `float`.

The symbol being documented is Float (class Float, line 22), not Int.

**Suggestion.** Replace `Int` with `Float`: 'The Pythonic type that this `Float` can be converted to/from. It is `float`.'

_Fairness-judge verified: Verified accurate. bytemaker/bittypes/float.py:42 reads "The Pythonic type that this `Int` can be converted to/from. It is `float`." while the class being documented is Float (line 22). This is a stale copy-paste from int.py:41 ("The Pythonic type that this Int can be converted to/from. It is …_

---

## 13. to_bitstring documents a nonexistent `integer` parameter

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/int.py:205-219`](../bytemaker/bittypes/int.py#L205)

**What.** The Parameters section leads with `integer (int): The integer to convert.`, but the signature is `to_bitstring(self: Int | int, signed=True, bit_length=None, rep_format=None)`. There is no `integer` parameter; the value comes from `self` (an Int or a plain int). The docstring documents an argument that does not exist and leaves the actual `self` receiver undocumented. Pre-existing (matches the reference int.pyc), not new drift, but still misdescribes the signature.

**Evidence.**

Docstring: 'Parameters:\n        - integer (int): The integer to convert.\n        - signed (bool, optional): ...' vs signature `def to_bitstring(self: Int | int, signed: bool = True, bit_length: Optional[int] = None, rep_format: Optional[...] = None) -> str`.

**Suggestion.** Drop the `integer (int)` entry and document that the value is taken from `self` (an Int or plain int); keep signed/bit_length/rep_format.

_Fairness-judge verified: Accurate and verified. In bytemaker/bittypes/int.py the signature is `def to_bitstring(self: Int | int, signed=True, bit_length=None, rep_format=None)` (lines 197-204), but the docstring's Parameters section (line 209) leads with `- integer (int): The integer to convert.` — a parameter that does …_

---

## 14. SInt int_format doc has a malformed default string literal

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/int.py:562`](../bytemaker/bittypes/int.py#L562)

**What.** The documented default for `int_format` is written `Default is "twos_complement.` — the closing quote is missing and the sentence terminator is stranded inside the string. Minor, but it reads as an unedited typo. Pre-existing (present in the reference too).

**Evidence.**

'            Default is "twos_complement.'  (opening quote, no closing quote, trailing period inside).

**Suggestion.** Fix to `Default is "twos_complement".`

_Fairness-judge verified: Verified directly. bytemaker/bittypes/int.py:562 reads `            Default is "twos_complement.` in the SInt class docstring's Instance Attributes section for `int_format` — the closing quote is missing and the period is stranded inside the open string literal. The other occurrences in the same …_

---

## 15. String.specialize missing docstring while every sibling specialize is documented

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/string.py:338-346`](../bytemaker/bittypes/string.py#L338)

**What.** String.specialize is a public classmethod (the bit-counted subclass door) with no docstring at all. Every peer specialize is documented: Buffer.specialize (buffer.py:60-71), SInt.specialize (int.py:622-641), Float.specialize (float.py:221-242). This is an inconsistent gap on public API -- the same method on the same tier of the class hierarchy documents its num_bits_/name_ params everywhere except here.

**Evidence.**

@classmethod
    def specialize(cls, num_bits_: int, name_: Optional[str] = None):
        class _String(cls):
            _num_bits = num_bits_

        if name_:
            _String.__name__ = name_

        return _String   -- no docstring. Compare Buffer.specialize: '"""\n        Returns a subclass of Buffer with the specified number of bits.\n\n        Args:\n            num_bits_ (int): ...\n            name_ (Optional[str], optional): ... Defaults to None, meaning the name will be _Buffer.\n\n        Returns:\n            Type[BufferSelf]: ...'

**Suggestion.** Add a docstring mirroring Buffer.specialize: state num_bits_ is a bit count (note this constructs a sub-byte-capable box, unlike of() which is byte-sized), name_ defaults to _String.

_Fairness-judge verified: Accurate and verifiable. String.specialize (bytemaker/bittypes/string.py:338-346) is a public classmethod on the public String class (line 43, `class String(BitType[str])`) with zero docstring, while all three cited siblings are documented: Buffer.specialize (buffer.py:60-71), SInt.specialize …_

---

## 16. oct() docstring says prefixed by 0x but returns 0o

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:533-535`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L533)

**What.** The oct() docstring in the bitarray backend claims the octal string is prefixed by 0x. The code returns '0o' + ... , and the summary line is a copy-paste from hex(). Both sibling implementations document this correctly ('0o'). This actively misdescribes the return value.

**Evidence.**

Line 535 docstring: "Convert the BitVector to an octal string prefixed by 0x." while the body is `retval = "0o" + self.tobase(8, sep, bytes_per_sep)` (line 546). Compare bitvector_native.py:556 "...octal string prefixed by 0o." and bitvector_speedup.py:711 "...octal string prefixed by 0o."

**Suggestion.** Change "prefixed by 0x" to "prefixed by 0o" to match the code and the other two backends.

_Fairness-judge verified: Accurate and fair. In bytemaker/bitvector/bitvector_with_bitarray_speedup.py, the oct() method's summary line (line 535) reads "Convert the BitVector to an octal string prefixed by 0x." while the body (line 546) returns `"0o" + self.tobase(8, sep, bytes_per_sep)`. The "0x" is a verbatim copy-paste …_

---

## 17. bin() docstring says prefixed by 0x but returns 0b

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:549-551`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L549)

**What.** The bin() docstring in the bitarray backend claims the binary string is prefixed by 0x. The code returns '0b' + self.to01(...). This is a copy-paste from hex() left unedited. Both sibling implementations document this correctly ('0b').

**Evidence.**

Line 551 docstring: "Convert the BitVector to a binary string prefixed by 0x." while the body is `return "0b" + self.to01(sep, bytes_per_sep)` (line 562). Compare bitvector_native.py:572 "...binary string prefixed by 0b." and bitvector_speedup.py:724 "...binary string prefixed by 0b."

**Suggestion.** Change "prefixed by 0x" to "prefixed by 0b".

_Fairness-judge verified: Accurate and verified in current code. bytemaker/bitvector/bitvector_with_bitarray_speedup.py:551 says "Convert the BitVector to a binary string prefixed by 0x." while the body at line 562 is `return "0b" + self.to01(sep, bytes_per_sep)`. This is a clear copy-paste leak (the adjacent oct() at line …_

---

## 18. find() docstring omits subsequence search that the code performs

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1320-1321`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1320)

**What.** The bitarray backend's find() docstring describes only single-bit search ('the first occurrence of the given bit'), but the code accepts and searches for a whole subsequence (it constructs a BitVector from a non-int/non-bitarray value and passes it to super().find). Both sibling implementations document the subsequence case; the bitarray one drifted to an incomplete summary. rfind/index/rindex in the same file DO mention 'or of the subsequence of bits if provided', making find() internally inconsistent too.

**Evidence.**

Line 1320-1321: "Finds the first occurrence of the given bit in the BitVector.\n        If the bit is not found, -1 is returned." with code `if not isinstance(value, (bitarray, int)): value = BitVector(value)` then `return super().find(value, start, stop)`. Compare its own rfind() at line 1344 "...given bit in the BitVector,\n        or of the subsequence of bits if provided." and bitvector_native.py:1346-1347.

**Suggestion.** Add the "or of the subsequence of bits if provided" clause to match rfind/index/rindex and the sibling backends.

_Fairness-judge verified: Verified directly. bitvector_with_bitarray_speedup.py:1320-1321 find() docstring reads "Finds the first occurrence of the given bit in the BitVector. / If the bit is not found, -1 is returned." — no subsequence clause. But the code at lines 1333-1336 coerces a non-int/non-bitarray value into a …_

---

## 19. startswith/endswith docstrings say 'bitarray' instead of 'BitVector'

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1166, 1254`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1166)

**What.** The bitarray backend's startswith() and endswith() docstrings refer to the receiver as 'the bitarray' (leaking the internal base class name into user-facing docs), whereas every other public docstring in the class and both sibling implementations say 'the BitVector'. Mechanical inconsistency that leaks the implementation detail.

**Evidence.**

Line 1166: "Checks if the bitarray starts with the given substring." and line 1254: "Checks if the bitarray ends with the given substring." Compare bitvector_native.py:1236 "Checks if the BitVector starts with the given substring." and bitvector_speedup.py:1365 "Checks if the BitVector starts with the given substring(s)..."

**Suggestion.** Replace 'the bitarray' with 'the BitVector' in both summary lines (and in the inline comments 'within the bounds of the bitarray' at lines 1221/1293 for consistency).

_Fairness-judge verified: Accurate and fair. Verified verbatim: bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1166 "Checks if the bitarray starts with the given substring." and :1254 "Checks if the bitarray ends with the given substring." The two sibling implementations of the same public methods both say …_

---

## 20. __contains__ docstring promises 'False otherwise' but code can return None

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:864-884`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L864)

**What.** The __contains__ docstring states the method returns a bool ('or False otherwise'), and the signature is `-> bool`. But the final branch is guarded by `if isinstance(item, bitarray):` with no else, so when that guard is somehow false the function falls off the end and returns None. The docstring's stated contract (always bool, False when not containable) does not match the code, which has no unconditional bool return on all paths. The native and speedup backends end with `assert isinstance(item, BitVector)` then an unconditional `return first_index != -1`, honoring the docstring.

**Evidence.**

Docstring line 871: "or False otherwise." and signature `-> bool` (line 864), but the body ends `if isinstance(item, bitarray):\n            first_index = self.find(item)\n            return first_index != -1` (lines 882-884) with no trailing return. Compare bitvector_native.py:908-910 `assert isinstance(item, BitVector)\n        first_index = self.find(item)\n        return first_index != -1`.

**Suggestion.** Either make the docstring honest about the fall-through, or (better) match the sibling backends' unconditional final return so the '-> bool / False otherwise' contract holds.

_Fairness-judge verified: Accurate on the mechanical facts, verified in current code. In bytemaker/bitvector/bitvector_with_bitarray_speedup.py the signature is `-> bool` (line 864), the docstring says "or False otherwise." (line 871), and the method body ends with a guarded `if isinstance(item, bitarray):` returning …_

---

## 21. Stale commented-out from_bytes/frombytes docstring block left in bitarray backend

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:419-438`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L419)

**What.** A commented-out from_bytes classmethod carries a full docstring documenting an `endianness` parameter and a frombytes stub raising 'Use from_bytes instead.' Neither exists as live code (the live from_bytes at line 1713 takes reverse_endianness, not endianness). This dead docstring documents an API signature the class does not provide and contradicts the actual from_bytes. Neither sibling backend carries this block.

**Evidence.**

Lines 419-434 commented block includes "endianness (Literal[\"little\", \"big\"]): The endianness of the BitVector" and lines 436-438 "# def frombytes(*args, **kwargs):\n    #     raise Warning(\"frombytes is not implemented. Use from_bytes instead.\")"; the live method at line 1713 is `def from_bytes(cls, byte_arr: bytes, reverse_endianness=False):`.

**Suggestion.** Delete the stale commented-out from_bytes/frombytes block; it documents a nonexistent endianness-based signature that conflicts with the real from_bytes.

_Fairness-judge verified: Verified all claims against current code. bytemaker/bitvector/bitvector_with_bitarray_speedup.py lines 419-438 hold a commented-out `from_bytes` classmethod whose docstring documents an `endianness: Literal["little","big"] = "big"` parameter ("# endianness (Literal[\"little\", \"big\"]): The …_

---

## 22. FixedLengthBitVector class docstring omits frombytes/fromfile from its list of length-changing methods that raise

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/fixed.py:22-24`](../bytemaker/bitvector/fixed.py#L22)

**What.** The class docstring enumerates exactly which mutations raise ValueError (append, extend, insert, pop, remove, clear, del b[i], +=, *=, and length-changing slice assignment). The class in fact also overrides frombytes and fromfile to raise the same length violation (lines 69-73), and these are precisely growth operations. Because the docstring presents an explicit closed list, the reader is led to believe frombytes/fromfile are not intercepted. The inline code comment at lines 67-68 acknowledges these are bitarray-backend growth extras, so the omission from the docstring list is an oversight, not intentional.

**Evidence.**

Docstring: "``append``, ``extend``, ``insert``, ``pop``, ``remove``, ``clear``, ``del b[i]``, ``+=``, ``*=``, and length-changing slice assignment raise :class:`ValueError`."  --- but the class also defines: "def frombytes(self, data): raise self._length_violation()" and "def fromfile(self, f, n=-1): raise self._length_violation()" (lines 69-73).

**Suggestion.** Add frombytes/fromfile to the enumerated list of raising methods (noting they are the bitarray-backend growth extras), or generalize the sentence to "...and the bitarray-backend in-place growers frombytes/fromfile raise :class:`ValueError`."

_Fairness-judge verified: Accurate and verified against current code. The class docstring at bytemaker/bitvector/fixed.py:20-24 presents a CLOSED enumeration of methods that raise ValueError ("``append``, ``extend``, ``insert``, ``pop``, ``remove``, ``clear``, ``del b[i]``, ``+=``, ``*=``, and length-changing slice …_

---

## 23. Malformed Args line for `units` in to_bytes_aggregate docstring

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/aggregate_types.py:185-186`](../bytemaker/conversions/aggregate_types.py#L185)

**What.** The Args entry for `units` is syntactically broken: `units [Iterable | DataClassType]):` has no opening paren before the type and a stray trailing `):`. It neither parses as a Google-style `name (type):` entry nor as anything a doc tool would render cleanly. The parameter is annotated `AggregateTypeByteConvertible` (Union[DataClassType, BitType, CType, PyType, Iterable]), so the type shown is also incomplete. This docstring was copied into the new aggregate_types.py wrapper (it duplicates _legacy_aggregate.py's text) with the malformed line carried along.

**Evidence.**

Lines 185-186: "Args:\n        units [Iterable | DataClassType]): The objects to convert to bytes"

**Suggestion.** Fix to `units (AggregateTypeByteConvertible): The objects to convert to bytes` (or at minimum add the missing opening paren and remove the stray `):`).

_Fairness-judge verified: Verified directly. bytemaker/conversions/aggregate_types.py:185 reads `units [Iterable | DataClassType]): The objects to convert to bytes` — genuinely malformed: no opening paren before the type and a stray trailing `):`, so it renders as neither a valid Google-style `name (type):` entry nor clean …_

---

## 24. Stale reference to nonexistent PyTypeWithDefaultBytes in two docstrings

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:309, 333`](../bytemaker/conversions/pytypes.py#L309)

**What.** Both bits_to_pytype and bytes_to_pytype tell the caller the target type "Must be a member of PyTypeWithDefaultBytes", but no symbol named PyTypeWithDefaultBytes exists anywhere in the codebase (grep finds only these two docstrings). The actual constraint is that the type has a registered conversion in ConversionConfig (i.e. is a PyType). The reference misleads about what to pass.

**Evidence.**

Line 309 and 333: "pytype (type): The type of the Python primitive to convert to.\n            Must be a member of PyTypeWithDefaultBytes"

**Suggestion.** Replace "Must be a member of PyTypeWithDefaultBytes" with "Must be a type with a registered conversion in ConversionConfig (a PyType)."

_Fairness-judge verified: Verified directly against current code. bytemaker/conversions/pytypes.py line 309 (bits_to_pytype) and line 333 (bytes_to_pytype) both literally read "Must be a member of PyTypeWithDefaultBytes" — quoted text matches exactly. A repo-wide grep confirms PyTypeWithDefaultBytes exists nowhere in the …_

---

## 25. Typo 'thee' in bits_to_pytype Returns description

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:312`](../bytemaker/conversions/pytypes.py#L312)

**What.** Minor spelling error in the Returns block of bits_to_pytype: 'thee provided Python type'. The parallel function bytes_to_pytype (line 338) spells the same phrase correctly as 'the provided Python type', so this is an inconsistent typo.

**Evidence.**

Line 312: "pytype: The instance of thee provided Python type represented by the\n            bits"

**Suggestion.** Change 'thee' to 'the' to match bytes_to_pytype at line 338.

_Fairness-judge verified: Verified in current code. bytemaker/conversions/pytypes.py:312 reads "pytype: The instance of thee provided Python type represented by the / bits" — the typo "thee" is genuinely present. The parallel function bytes_to_pytype at line 338 spells the identical phrase correctly as "the provided Python …_

---

## 26. pytype_to_bits / pytype_to_bytes / ConversionInfo.to_bytes describe an instance argument as a type

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/pytypes.py:62-73, 260-283`](../bytemaker/conversions/pytypes.py#L62)

**What.** These functions take a Python value (instance) to serialize, and the docstrings even say so ('The python instance to convert'), yet the parameter is annotated `: type` and ConversionInfo.to_bytes documents `pytype (type): The Python instance to convert to bytes`, conflating 'type' and 'instance'. The prose ('instance') and the type label ('type') contradict each other, which is misleading about whether to pass a class or a value.

**Evidence.**

pytypes.py:281-289 `def pytype_to_bytes(py_prim: type, ...)` with "py_prim: The python instance to convert to bytes"; pytypes.py:63-69 `def to_bytes(cls, pytype)` with "pytype (type): The Python instance to convert to bytes".

**Suggestion.** Make the docstring type match the prose: label the argument as an instance (drop the `(type)` annotation or change the hint), e.g. `py_prim (Any): the Python instance to convert`.

_Fairness-judge verified: Accurate and present in current code. bytemaker/conversions/pytypes.py:63 `def to_bytes(cls, pytype)` documents `pytype (type): The Python instance to convert to bytes`; :260 `def pytype_to_bits(py_prim: type)` and :281 `def pytype_to_bytes(py_prim: type, ...)` both say `py_prim: The python …_

---

## 27. .py module docstring under-describes float box path ('via __index__' only)

**Severity:** low · **Confidence:** high · [`bytemaker/fields.py:19-22`](../bytemaker/fields.py#L19)

**What.** The runtime module docstring makes the same too-narrow claim as the stub: it explicitly says reads are 'int/float' (so it spans the float aliases) yet says writes accept 'BitType boxes via __index__'. Float boxes are consumed via __float__/SupportsFloat, not __index__ (Float has no __index__). The paired fields.pyi correctly types this as `SupportsFloat | SupportsIndex` on _FloatAlias, so the prose here is inconsistent with the stub it points to.

**Evidence.**

"reads are ``int``/``float``, writes (and the synthesized ``__init__`` parameters, per dataclass_transform) accept anything the narrowing store accepts, including BitType boxes via ``__index__``."

**Suggestion.** Qualify the box path per kind (int boxes via __index__, float boxes via __float__), or generalize to 'via __index__/__float__', to match _FloatAlias.__set__ in fields.pyi.

_Fairness-judge verified: Accurate and fair. The fields.py module docstring (lines 19-22) says reads are "int/float" (spanning both int and float aliases) but attributes the box write path solely to "BitType boxes via __index__". This is wrong for float boxes. Verified in code: the float store descriptor _FloatField.__set__ …_

---

## 28. .pyi docstring says float boxes satisfy SupportsIndex, but Float has no __index__

**Severity:** low · **Confidence:** high · [`bytemaker/fields.pyi:4-7`](../bytemaker/fields.pyi#L4)

**What.** The stub's module docstring covers all three alias kinds (it names int/float reads) and states that write/__init__ values may be 'BitType boxes (which satisfy SupportsIndex via Int.__index__).' That is only true for the integer aliases. The very same stub declares `_FloatAlias.__set__(self, obj, value: SupportsFloat | SupportsIndex)` (line 26), i.e. a float field accepts a box via SupportsFloat. A boxed Float has __float__ but NO __index__ (bittypes/float.py defines __float__ at line 67; there is no __index__ on Float or its bases), so a Float box does NOT satisfy SupportsIndex. The docstring omits the SupportsFloat/__float__ channel that the stub itself encodes, misdescribing how float fields accept boxes.

**Evidence.**

Docstring: "reads are plain int/float, writes and the synthesized __init__ parameters accept anything the narrowing store accepts - plain ints and, post-D2, BitType boxes (which satisfy SupportsIndex via Int.__index__)."  vs the stub it documents: `class _FloatAlias: ... def __set__(self, obj: Any, value: SupportsFloat | SupportsIndex) -> None: ...`  (Float in bittypes/float.py has `def __float__` but no `__index__`.)

**Suggestion.** Mention both channels, e.g. '... BitType boxes: integer boxes via SupportsIndex (Int.__index__), float boxes via SupportsFloat (Float.__float__)', matching the _FloatAlias.__set__ signature.

_Fairness-judge verified: Accurate and verified. The .pyi module docstring (bytemaker/fields.pyi:4-7) states writes/__init__ accept "BitType boxes (which satisfy SupportsIndex via Int.__index__)" as the sole box-acceptance mechanism, while covering all three alias kinds ("reads are plain int/float", line 5). That mechanism …_

---

## 29. Undefined internal shorthand 'post-D2' leaked into public .pyi docstring

**Severity:** low · **Confidence:** high · [`bytemaker/fields.pyi:7`](../bytemaker/fields.pyi#L7)

**What.** The module docstring qualifies box acceptance with 'post-D2', an internal task/milestone label that is never defined and appears nowhere else in the codebase (grep of bytemaker/ finds this one occurrence only). To any reader of the stub it is meaningless noise dating the doc to an internal work item rather than describing behavior.

**Evidence.**

"plain ints and, post-D2, BitType boxes (which satisfy SupportsIndex via Int.__index__)."

**Suggestion.** Drop 'post-D2,' (the behavior is simply current) or replace with a concrete version/behavior reference readers can act on.

_Fairness-judge verified: Verified in bytemaker/fields.pyi:6-7: the module docstring reads "writes ... accept anything the narrowing store accepts - plain ints and, post-D2, BitType boxes (which satisfy SupportsIndex via Int.__index__)." A grep of bytemaker/ confirms "post-D2" occurs exactly once and is defined nowhere. It …_

---

## 30. LegacyRecordPlan public methods parse/pack lack docstrings

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:499-522`](../bytemaker/plans.py#L499)

**What.** LegacyRecordPlan is exported in __all__, and parse() and pack() are its two public methods (the actual parse/serialize entry points of the legacy fast path). Neither has a docstring, while the class itself and the sibling Plan methods (unpack_tuple, pack_tuple, iter_tuples, validate_tuple) are all documented. The reference-era house style documents public API surface; these two methods are the record-facing API of an exported class, so the omission is real house-style drift rather than an internal helper being left bare.

**Evidence.**

def parse(self, data: bytes, endianness: Literal["big", "little"]):
        if len(data) * 8 != self.total * 8:
            ...

    def pack(self, obj, endianness: Literal["big", "little"]) -> bytes:
        parts = []

**Suggestion.** Add one-line narrative docstrings, e.g. parse: 'Box `data` back into an instance of the dataclass, one field per byte slice.' and pack: 'Serialize `obj`'s fields to bytes in `endianness` order, coercing non-BitType values C-style.'

_Fairness-judge verified: Verified in bytemaker/plans.py. LegacyRecordPlan is exported in __all__ (line 65) and its class docstring exists (479-486), but its two public methods parse (line 499) and pack (line 514) go straight from signature to body with no docstring. This is real in-file house-style drift, not just a …_

---

## 31. FieldSpec docstring omits Array-element dotted naming, only mentions nested Structs

**Severity:** low · **Confidence:** high · [`bytemaker/plans.py:84-92`](../bytemaker/plans.py#L84)

**What.** The FieldSpec docstring says dotted `name` arises only from nested Structs ("name is dotted (\"child.x\") for their leaves"), but compile_plan also produces dotted names for Array fields, where the leaf name is the field plus a numeric index (add(f"{full}.", str(i), ...)), yielding names like "arr.0", "arr.1". A reader consulting FieldSpec to understand the name format would not learn that array leaves use ".<index>" suffixes. The docstring describes only one of the two flattening sources.

**Evidence.**

docstring: "Nested Structs are flattened away\n    before FieldSpecs are made; ``name`` is dotted (``\"child.x\"``) for\n    their leaves."
code (compile_plan add()): "for i in range(ftype.count):\n                add(f\"{full}.\", str(i), elem, eff_endian)"

**Suggestion.** Extend the sentence to cover array leaves, e.g. '... `name` is dotted for their leaves (`"child.x"`), and for Array elements it is the field name plus a numeric index (`"arr.0"`).'

_Fairness-judge verified: Accurate and fair. The FieldSpec docstring in bytemaker/plans.py (lines 89-91) states: "Nested Structs are flattened away before FieldSpecs are made; ``name`` is dotted (``\"child.x\"``) for their leaves." This frames nested Structs as the source of dotted names. But compile_plan's add() also …_

---

## 32. `sizedview` property docstring claims `.<field>` always returns a BoundField, but nested-Struct fields return a _SizedView and Array fields raise

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:848-854`](../bytemaker/structs.py#L848)

**What.** The public `sizedview` property docstring states unconditionally that `t.sizedview.<field>` returns a BoundField. In fact _SizedView.__getattr__ (lines 1221-1230) returns the child's own `.sizedview` (a _SizedView, not a BoundField) for a nested-Struct field, and raises AttributeError for an Array field. So the blanket claim is wrong for two of the three field kinds. The internal _SizedView docstring gets this right, but the user-facing property docstring does not, and `<field>` reads as a universal placeholder.

**Evidence.**

property docstring (lines 850-851): "``t.sizedview.<field>`` returns a :class:`BoundField` -- a live lvalue\n        handle."  --- vs code (lines 1221-1229): `if isinstance(ftype, StructMeta): return getattr(owner, name).sizedview` and `if isinstance(ftype, Array): ... raise AttributeError(...)`.

**Suggestion.** Qualify the claim, e.g. 'For a scalar field, `t.sizedview.<field>` returns a BoundField; a nested-Struct field returns the child's own sizedview, and an array field raises (access its live list via the field directly).'

_Fairness-judge verified: Accurate and verified. The public `sizedview` property docstring (bytemaker/structs.py:850-851) states unconditionally: "``t.sizedview.<field>`` returns a :class:`BoundField` — a live lvalue handle." But `_SizedView.__getattr__` (lines 1221-1230) branches: a nested-Struct field (`isinstance(ftype, …_

---

## 33. `array()` docstring 'Sugar for `field(element * count)`' omits the endian parameter the function actually accepts

**Severity:** low · **Confidence:** high · [`bytemaker/structs.py:655-657`](../bytemaker/structs.py#L655)

**What.** array() has signature `array(element, count, *, endian=None, default=_MISSING)` and builds `Array.of(element, count, endian)`. Its docstring describes it only as 'Sugar for `field(element * count)`', but `element * count` resolves to `Array.of(element, count)` with no endian (see BitTypeMeta.__mul__ at bittype.py:74 and Array.__mul__ at structs.py:1509, neither of which takes endian). The docstring never mentions the `endian` (or `default`) keyword, so a reader cannot tell array() can set per-array byte order -- the one thing it offers over the `field(element * count)` spelling it claims full equivalence to.

**Evidence.**

docstring (lines 655-656): "Declare a fixed-count array field: ``colors: list[int] = array(UInt16, 8)``.\n    Sugar for ``field(element * count)`` with a plain-list checker type."  --- vs signature (lines 648-654) which includes `endian: Any = None` and passes it through: `return _FieldSpec(Array.of(element, count, endian), default)`.

**Suggestion.** Add a sentence documenting the `endian` keyword (and note `default`), or soften the 'sugar for field(element * count)' claim to note array() additionally lets you set the array's byte order and a default.

_Fairness-judge verified: Verified accurate against current code. bytemaker/structs.py:648-657: array(element, count, *, endian=None, default=_MISSING) forwards endian into Array.of(element, count, endian). Its docstring (lines 655-656) says only "Sugar for ``field(element * count)``". But element * count resolves to …_

---

## 34. twos_complement docstring documents a nonexistent parameter 'bits' (actual: n_bits)

**Severity:** low · **Confidence:** high · [`bytemaker/utils.py:314-325`](../bytemaker/utils.py#L314)

**What.** The public module-level function twos_complement(number, n_bits=32) has a reStructuredText field-list docstring whose second :param: names 'bits', but the function has no parameter called 'bits' — the width argument is n_bits. A reader (or a tooling/doc build) is told to pass 'bits', which does not exist. This is a wrong-parameter-name doc on a public function. It predates the 4-weeks-ago reference (utils.py is byte-identical to commit 1a894a2), so it is long-standing rather than new drift, but it is still a genuine, unambiguous docstring error and utils.py is exactly the mature RST-field-list-style file where the house norm is precise :param: names.

**Evidence.**

Docstring:
    :param number: The integer to convert.
    :param bits: The bit width for the two's complement representation.
    :return: A string representing the two's complement of the number.
Signature:
    def twos_complement(number, n_bits=32):

**Suggestion.** Rename the field to match the parameter: ':param n_bits: The bit width for the two's complement representation.' (Default is 32.)

_Fairness-judge verified: Verified in current code: bytemaker/utils.py line 314 declares `def twos_complement(number, n_bits=32):`, but the field-list docstring at line 319 reads `:param bits: The bit width for the two's complement representation.` The width parameter is `n_bits`, not `bits`, so the docstring documents a …_

---

## 35. specialize docstring prose spells packing_format_letter without its trailing underscore

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/float.py:225`](../bytemaker/bittypes/float.py#L225)

**What.** The narrative sentence in specialize's docstring refers to `packing_format_letter` (no trailing underscore), but the actual parameter is `packing_format_letter_` (declared at line 218 and correctly documented under Args at line 235). This mechanical mismatch between the prose backtick-name and the real parameter name is a minor inconsistency; a reader searching for the argument by the name in the sentence will not find it. Matches the reference, so pre-existing.

**Evidence.**

Line 225 prose: 'If `packing_format_letter` is provided, the subclass will also be a `StructPackedBitType`...'
Actual parameter (lines 218, 235): `packing_format_letter_` (with trailing underscore).

**Suggestion.** Use the real parameter name `packing_format_letter_` in the prose to match the signature and the Args entry, or drop the backticks and refer to it descriptively.

_Fairness-judge verified: Verified against current code and the reference bytecode. At bytemaker/bittypes/float.py:225 the specialize() docstring prose reads: "If `packing_format_letter` is provided, the subclass will also be a `StructPackedBitType`..." while the actual parameter (float.py:218) and its Args entry …_

---

## 36. Int class docstring: inconsistent heading underlines and a dangling sentence

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/int.py:32-46`](../bytemaker/bittypes/int.py#L32)

**What.** Within the single Int class docstring the two section headings are formatted inconsistently: `Class Attributes:` has a trailing colon and a 15-dash underline, while `Instance Attributes` has no colon and a 19-dash underline. This RST-underline heading style also clashes with the Google-style `Args:` / `Returns:` used by every method docstring in the same file (to_pyint, to_bitstring, specialize). Additionally the opening sentence dangles: 'Is further subclassed into `SInt` and `UInt` for signed and unsigned integers,' ends on a comma with no continuation. Mechanical format inconsistency plus an unedited sentence; pre-existing (matches the reference).

**Evidence.**

'Class Attributes:\n    ---------------\n' vs 'Instance Attributes\n    -------------------\n' (colon present/absent, dash counts differ); and 'Is further subclassed into `SInt` and `UInt` for signed and unsigned integers,' (trailing comma, no continuation).

**Suggestion.** Make the two headings consistent (both with colon, matching underline length, or convert to the file's Google-style `Class Attributes:` / `Instance Attributes:` without underlines) and finish the dangling sentence (e.g. '... for signed and unsigned integers respectively.').

_Fairness-judge verified: Verified against current bytemaker/bittypes/int.py (lines 32-53). All three claims are accurate: (1) the opening sentence dangles — line 32 "Is further subclassed into `SInt` and `UInt` for signed and unsigned integers," ends on a comma with no continuation; (2) the two headings are inconsistent — …_

---

## 37. __init__ buffer docstring drifts from __new__ on copy-vs-share (native backend)

**Severity:** low · **Confidence:** medium · [`bytemaker/bitvector/bitvector_native.py:264-266`](../bytemaker/bitvector/bitvector_native.py#L264)

**What.** The native backend's __new__ docstring is careful to state that `buffer=` copies on this reference backend ('this reference backend copies', lines 176-178). The __init__ docstring for the same param just says 'the BitVector's bits are read from the provided buffer object' with no copy note, so a reader of __init__ alone gets the may-share impression the __new__ docstring deliberately corrects. bitvector_speedup.py avoids this by having __init__ defer entirely to __new__ ('See __new__ for construction semantics').

**Evidence.**

bitvector_native.py:264-266 "If `buffer` is not None, the BitVector's bits are read from the\n            provided buffer object." vs its own __new__ at lines 176-178 "(`buffer=` is *may-share*: this reference backend copies; the\n            bitarray backend genuinely shares memory.)". Contrast bitvector_speedup.py:350-360 which points __init__ at __new__.

**Suggestion.** Have the native __init__ docstring defer to __new__ (as the speedup backend does) or repeat the 'this backend copies' note, so the two docstrings don't disagree about buffer semantics.

_Fairness-judge verified: Verified all three cited passages verbatim. Native __new__ (bitvector_native.py:175-178) deliberately clarifies "`buffer=` is *may-share*: this reference backend copies; the bitarray backend genuinely shares memory." The native __init__ docstring (lines 264-266) says only "If `buffer` is not None, …_

---

## 38. Plan.num_bytes property has no docstring on an exported class

**Severity:** low · **Confidence:** medium · [`bytemaker/plans.py:215-217`](../bytemaker/plans.py#L215)

**What.** num_bytes is a public property on Plan (an __all__-exported class). Every other public accessor on Plan (bit_offset, byte_offset) carries a one-line docstring; num_bytes is undocumented. Minor, but it is the odd one out in an otherwise consistently documented public surface.

**Evidence.**

@property
    def num_bytes(self) -> int:
        return self.num_bits // 8

**Suggestion.** Add a one-line docstring, e.g. '"""Record size in whole bytes (num_bits // 8)."""' to match the documented bit_offset/byte_offset accessors.

_Fairness-judge verified: Accurate and present in current code. bytemaker/plans.py:215-217 defines a public @property `num_bytes` (`return self.num_bits // 8`) with no docstring, on the class `Plan` which is exported via __all__ (plans.py:64). The two nearest sibling public accessors do carry one-line docstrings: bit_offset …_

---

## 39. count_bits_in_unit_type wrapper docstring uses awkward escaped line-continuation and omits Returns

**Severity:** low · **Confidence:** low · [`bytemaker/conversions/aggregate_types.py:100-116`](../bytemaker/conversions/aggregate_types.py#L100)

**What.** The caching-wrapper docstring reuses the legacy one-liner with a mid-sentence backslash line continuation ('a UnitType-\\' then indented continuation) that renders as run-together text, and unlike the sibling wrappers/functions it documents no Returns despite returning int. It reads as a mechanically copied fragment rather than a wrapper doc; the peer function resolve_field_types just above it does supply a proper Returns block, so the inconsistency is visible within the same file.

**Evidence.**

Lines 101-106: "Function to count the number of bits in a UnitType-\\\n        a Python, type, ctype, or BitType (bytemaker type).\n\n    Cached per type."

**Suggestion.** Rewrite as a plain sentence without the escaped continuation and add `Returns:\n    int: number of bits`, matching resolve_field_types' style in the same module.

_Fairness-judge verified: Verified against current code (bytemaker/conversions/aggregate_types.py:100-116) and the source it was copied from (_legacy_aggregate.py:68-72). The core facts are accurate: the wrapper docstring reuses the legacy one-liner verbatim, including a mid-sentence backslash line-continuation "in a …_

---
