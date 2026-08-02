# AI-tone / unnatural prose

> **Status: verified discovery pass.** Single-pass sweep of this lens, each finding then checked by an independent fairness judge that read the cited code and dropped nitpicks / inaccuracies / flags of the intentional house style (26 of 137 candidates were rejected across the three lenses). Skews toward polish. See [README.md](README.md).

Prose that reads as AI-generated or unnatural against the terse reference voice: copy-paste leftovers, inflated wording, filler hedges, comments that restate the code. Kept deliberately conservative.

_10 findings — 1 high, 1 medium, 8 low._

---

## 1. Float class docstring copy-pasted from Int: "represents an integer"

**Severity:** high · **Confidence:** high · [`bytemaker/bittypes/float.py:24`](../bytemaker/bittypes/float.py#L24)

**What.** The Float class summary line is copy-pasted verbatim from Int's docstring and never edited. Int (bytemaker/bittypes/int.py:30) opens with the identical sentence "A `BitType` that represents an integer." Float manifestly represents a floating-point value, not an integer, so this actively misleads any reader or generated doc. Classic unedited copy-paste docstring left over from another symbol.

**Evidence.**

Line 24: "    A BitType that represents an integer."  (cf. int.py:30 "A `BitType` that represents an integer.")

**Suggestion.** Rewrite to describe a float, matching the terse reference voice, e.g. "A BitType that represents an IEEE-754-style floating-point number."

_Fairness-judge verified: Verified in current code. bytemaker/bittypes/float.py:24 opens the public Float class docstring with "A BitType that represents an integer." — the literal opposite of what Float is — while Int at bytemaker/bittypes/int.py:30 has the near-identical "A `BitType` that represents an integer." This is a …_

---

## 2. Float docstring's py_type line still names `Int`, not Float

**Severity:** medium · **Confidence:** high · [`bytemaker/bittypes/float.py:41-42`](../bytemaker/bittypes/float.py#L41)

**What.** The py_type class-attribute description is the Int docstring's line with only the type name swapped: it still says "this `Int` can be converted to/from" inside the Float class. Another unedited copy-paste fragment (Int py_type line reads "The Pythonic type that this Int can be converted to/from. It is int."). Refers to the wrong class in Float's own reference documentation.

**Evidence.**

Lines 41-42: "    py_type : Type[float]\n        The Pythonic type that this `Int` can be converted to/from. It is `float`."

**Suggestion.** Change "this `Int`" to "this `Float`".

_Fairness-judge verified: Verified in current code. bytemaker/bittypes/float.py:41-42, inside the `Float` class docstring, reads: "py_type : Type[float]\n        The Pythonic type that this `Int` can be converted to/from. It is `float`." The class name `Int` is wrong here — this is the `Float` class's own reference …_

---

## 3. Orphaned duplicate docstring fragment in Buffer class body

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/buffer.py:40-45`](../bytemaker/bittypes/buffer.py#L40)

**What.** Immediately after the real Buffer class docstring (lines 17-38) sits a second, orphaned string literal that duplicates the docstring's opening two paragraphs. Only the first literal is the docstring; this second one is dead prose that Python evaluates and discards. It merely restates text already present above it. The reference-era buffer.py (commit 1a894a2) contained exactly ONE such docstring (verified by decompiling the ref bittypes/buffer.cpython-311.pyc) -- this truncated copy is a new copy-paste leftover, the kind of duplicated-restatement artifact typical of AI-assisted edits.

**Evidence.**

Line 38 closes the real docstring, then lines 40-45:
    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.
    """
(identical to lines 18-21 of the actual docstring immediately above).

**Suggestion.** Delete lines 40-45 entirely; the class docstring at 17-38 already covers this.

_Fairness-judge verified: Verified directly. bytemaker/bittypes/buffer.py line 38 closes the real class docstring (lines 17-38, with "Class Attributes"/"Instance Attributes" sections), then lines 40-45 contain a second orphaned triple-quoted string literal that duplicates only the opening two paragraphs verbatim:      """   …_

---

## 4. Comment restates the immediately-following line ('# Replace old bits with new bits')

**Severity:** low · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1478`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1478)

**What.** This comment merely narrates the assignment on the next line (self[found_index : found_index + len(new)] = new / accumulated_bits += ... + new), adding no information beyond what the code already states — a low-grade instance of the 'comment that restates the code' red flag. It appears only in this backend's replace(); the native backend's replace() does not carry it, which weakens the claim that it is shared original boilerplate. The nearby comments in the same method (empty-pattern guard at 1457-1458, equal-length copy at 1469-1470) are genuinely explanatory and should stay.

**Evidence.**

# Replace old bits with new bits
            if accumulated_bits is None:
                self[found_index : found_index + len(new)] = new

**Suggestion.** Delete the comment; the code is self-evident. If a comment is wanted here, make it explain the branch (why an in-place slice patch vs. accumulation) rather than restate the operation.

_Fairness-judge verified: Verified directly in bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1478. The comment "# Replace old bits with new bits" sits immediately above the replacement operation (self[found_index : found_index + len(new)] = new / accumulated_bits += self[index:found_index] + new) and adds nothing …_

---

## 5. Buffer.of() docstring leans on a repeated "door" metaphor

**Severity:** low · **Confidence:** medium · [`bytemaker/bittypes/buffer.py:85-91`](../bytemaker/bittypes/buffer.py#L85)

**What.** This new docstring twice recasts a plain constructor as a "door" -- "the Struct-field door" and "the bit-counted box door" -- a cute metaphor that adds no precision over saying of() is the byte-sized entry point and specialize is the bit-sized one. It is mild inflation/over-styling relative to the terse reference voice (compare the neighboring specialize() docstring, lines 61-71, which just states "Returns a subclass of Buffer with the specified number of bits"). The real content (keyword-only rationale, the Buffer16 history) is worth keeping; only the metaphor reads as unnatural.

**Evidence.**

"count, and the Struct-field door (Struct byte fields hold plain ``bytes`` and need whole-byte widths anyway). ``specialize`` is the bit-counted box door; sub-byte Buffers stay legal standalone and in legacy aggregates."

**Suggestion.** Drop the "door" framing, e.g.: "``of()`` sizes in bytes (whole-byte widths, as Struct byte fields require); ``specialize`` sizes in bits and still allows sub-byte Buffers standalone and in legacy aggregates."

_Fairness-judge verified: Verified against current bytemaker/bittypes/buffer.py lines 85-91. The quoted text is present exactly: of() is twice recast via a "door" metaphor — "the Struct-field door" and "the bit-counted box door." This is a genuine over-styling flourish, distinct from the intentional narrative-RST house …_

---

## 6. Chatty "Please note that" plus awkward "less implicitly a series of bits" in BitsConstructible docstring

**Severity:** low · **Confidence:** medium · [`bytemaker/bitvector/bitvector_speedup.py:1856-1858`](../bytemaker/bitvector/bitvector_speedup.py#L1856)

**What.** The module-level BitsConstructible type-alias docstring uses a conversational "Please note that ..." opener and the strained phrase "less implicitly a series of bits," which reads as generated over-explanation rather than the reference voice's plain declarative sentences.

**Evidence.**

"Please note that you can also use an int to construct a BitVector of that many\nzeroes, but this is not included in the type hint because it is less implicitly\na series of bits."

**Suggestion.** Tighten to a plain statement, e.g. "An int also constructs a BitVector of that many zero bits, but it is omitted from the type hint because an int does not read as a sequence of bits."

_Fairness-judge verified: Verified verbatim at bytemaker/bitvector/bitvector_speedup.py:1856-1858: "Please note that you can also use an int to construct a BitVector of that many\nzeroes, but this is not included in the type hint because it is less implicitly\na series of bits." The finding is accurate and not merely …_

---

## 7. Em-dash + triadic-rhythm prose padding the expanded __new__ buffer docstring

**Severity:** low · **Confidence:** medium · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:125-135`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L125)

**What.** The buffer/source paragraph of __new__ was expanded well past the terse reference-era version, and the added prose carries two AI-tone tells the reference voice avoids: (1) em-dashes used as connective punctuation (the only two em-dashes in the entire bitvector directory both live in this newly-added block, lines 134 and 190; the native and other speedup impls use periods/parentheticals throughout), and (2) a triadic, rhythm-for-its-own-sake clause 'an immutable source gives a read-only vector; a mutable one a live two-way view that also resize-locks the source while the vector lives; either way the vector itself cannot be resized'. The recovered reference docstring for this same method stopped after the buffer-protocol URL with no such elaboration. The real content (may-share vs copy, the 13 #16 ruling) is worth keeping; the phrasing is the issue. The parallel native backend conveys the identical ruling in a tighter parenthetical (bitvector_native.py:175-178).

**Evidence.**

`buffer=` is the ONLY sharing spelling, and it is *may-share*:
            this backend genuinely shares (an immutable source gives a
            read-only vector; a mutable one a live two-way view that also
            resize-locks the source while the vector lives; either way the
            vector itself cannot be resized), while the pure-Python
            backends copy. Do not rely on independence through buffer=.

        Otherwise, `source` determines the BitVector's bits. Byte-like
        sources (`bytes`, `bytearray`, `memoryview`) are always **copied**
        into an independent, writable, resizable vector — on every backend
        (13 #16 ruling; matches bitarray's own positional-source behavior).

**Suggestion.** Tighten to the reference's declarative voice, dropping the em-dash and the three-clause parenthetical, e.g.: 'buffer= is may-share and the only sharing spelling: this backend shares memory (read-only for an immutable source; a live, resize-locking view for a mutable one; never resizable), whereas the pure-Python backends copy. Byte-like sources (bytes, bytearray, memoryview) are always copied into an independent, resizable vector on every backend (13 #16).' Match bitvector_native.py:175-178's compact framing.

_Fairness-judge verified: Verified in current code. The bitvector directory contains exactly two em-dashes, both in bitvector_with_bitarray_speedup.py (docstring line 134 and comment line 190); the native backend, the pure-Python speedup backend, and every other file in the directory use zero — a genuine local tone drift, …_

---

## 8. "just works" marketing reassurance in top-level module docstring

**Severity:** low · **Confidence:** low · [`bytemaker/__init__.py:18-20`](../bytemaker/__init__.py#L18)

**What.** The package docstring closes the alias explanation with the casual reassurance "just works", a phrase in the marketing/hand-wave family flagged as an AI/tone red flag ("simply"/"just works"). The sentence already conveys the real information (any-width u/s aliases, resolved lazily via bytemaker.fields); "just works" adds only promotional tone and clashes with the library's otherwise terse, declarative reference voice. This is the very first prose a reader sees for the package, so the chattiness is prominent.

**Evidence.**

``uN``/``sN`` field aliases exist
for any width — ``from bytemaker import u31`` just works (resolved lazily
via :mod:`bytemaker.fields`).

**Suggestion.** Drop the reassurance and state the fact plainly, e.g. "``uN``/``sN`` field aliases exist for any width (e.g. ``from bytemaker import u31``), resolved lazily via :mod:`bytemaker.fields`."

_Fairness-judge verified: Accurate as to location and text: bytemaker/__init__.py:18-20 reads "``from bytemaker import u31`` just works (resolved lazily via :mod:`bytemaker.fields`)." "just works" is in the flagged marketing/hand-wave family ("simply"/"just works"), carries no technical content beyond the parenthetical that …_

---

## 9. Filler "only really be true" in __eq__ docstring

**Severity:** low · **Confidence:** low · [`bytemaker/bitvector/bitvector_speedup.py:789-791`](../bytemaker/bitvector/bitvector_speedup.py#L789)

**What.** The __eq__ docstring's second sentence uses the filler intensifier "really" ("only really be true"), a conversational tic absent from the terse reference-era docstrings. It also states the near-obvious in a chatty way rather than plainly noting the type constraint.

**Evidence.**

"Returns whether this BitVector's bits are equal to another object's bits.\n        This will only really be true if both objects are BitVectors."

**Suggestion.** Drop the filler: "Equality holds only when both operands are BitVectors with the same bits; otherwise returns NotImplemented."

_Fairness-judge verified: Accurately quoted at bytemaker/bitvector/bitvector_speedup.py:789-791: "Returns whether this BitVector's bits are equal to another object's bits. This will only really be true if both objects are BitVectors." The word "really" is filler and is the only occurrence in the entire 156-docstring file; …_

---

## 10. Editorializing 'unusable' in module docstring behavior note

**Severity:** low · **Confidence:** low · [`bytemaker/conversions/aggregate_types.py:15-18`](../bytemaker/conversions/aggregate_types.py#L15)

**What.** The parenthetical describing the prior is_array bug editorializes with 'which was unusable' rather than stating the mechanical fact. The reference-era docstrings describe behavior plainly without value-judging the old code. 'unusable' is a soft inflation; the concrete facts (it called aggregate_type(*entries) and ignored is_array for scalars) already convey the problem.

**Evidence.**

(Previously it attempted ``aggregate_type(*entries)``, which was unusable, and ignored ``is_array`` entirely for scalar types.)

**Suggestion.** Drop 'which was unusable' and let the two concrete facts stand, e.g. '(Previously it attempted ``aggregate_type(*entries)`` and ignored ``is_array`` for scalar types.)'

_Fairness-judge verified: Verified in current code at bytemaker/conversions/aggregate_types.py:15-18: "(Previously it attempted ``aggregate_type(*entries)``, which was unusable, and ignored ``is_array`` entirely for scalar types.)" Both concrete claims are accurate against the legacy impl: _legacy_aggregate.py:446 calls …_

---
