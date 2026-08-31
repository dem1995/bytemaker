# bytemaker — proposed solutions

Reviewable fix proposals for the [audit findings](../README.md), one file per area. Every solution has a problem summary, the proposed approach, before/after code, the observable behavior change (with real repro output where **✓ verified**), suggested tests, and sync obligations. Each group was designed by a dedicated agent, then independently re-checked by an adversarial reviewer (verbatim snippet diffs, caller greps, empirical re-runs of the claimed repros and the full 854-test suite on patched copies); reviewer flags were resolved by revision before compilation. **Nothing has been applied to the source.**

**82 solutions** covering all 192 findings — 31 apply-now, 36 soon, 15 later; 75 empirically verified; 25 maintainer decisions pending (listed below).

The three `lows-*` files handle the 112 low-severity findings as sweep PATTERNS (rule + worked examples + per-finding checklist); findings already mooted by a bigger accepted fix are marked `MOOTED by <id>` in those checklists. Machine-readable pipeline state (per-group JSON + adversarial verdicts) lives in [_work/](_work/).

## Areas

| Area | Solutions | Apply-now | Verified | File |
|---|---|---|---|---|
| Float encode/decode (bittypes/float.py) | 5 | 3 | 5 | [float.md](float.md) |
| Narrowing warnings & int_format (bittype.py / int.py) | 6 | 3 | 6 | [narrowing.md](narrowing.md) |
| BitVector behavioral divergences (3 impls + fixed.py) | 8 | 4 | 8 | [bitvector-behavior.md](bitvector-behavior.md) |
| String bittypes (bittypes/string.py) | 6 | 2 | 6 | [string.md](string.md) |
| Struct system (structs.py) | 3 | 2 | 3 | [structs.md](structs.md) |
| ctypes conversions (conversions/ctypes_.py) | 3 | 3 | 3 | [ctypes.md](ctypes.md) |
| Legacy aggregate & utils (utils.py / _legacy_aggregate.py) | 5 | 3 | 5 | [aggregate-utils.md](aggregate-utils.md) |
| Plan engine validation (plans.py) | 2 | 2 | 2 | [plans.md](plans.md) |
| pytype conversions (conversions/pytypes.py) | 3 | 1 | 3 | [pytypes.md](pytypes.md) |
| Endianness validation (cross-cutting) | 2 | 2 | 2 | [endianness.md](endianness.md) |
| Buffer bittype (bittypes/buffer.py) | 2 | 1 | 2 | [buffer.md](buffer.md) |
| Docstring & API-surface fixes (misc mediums) | 5 | 3 | 5 | [docs-misc.md](docs-misc.md) |
| BitVector cleanup (non-behavioral) | 5 | 1 | 5 | [bitvector-polish.md](bitvector-polish.md) |
| Low-severity patterns: docstrings & AI-tone | 6 | 0 | 0 | [lows-docs.md](lows-docs.md) |
| Low-severity patterns: UX | 6 | 0 | 6 | [lows-ux.md](lows-ux.md) |
| Low-severity patterns: code nits | 15 | 1 | 14 | [lows-code.md](lows-code.md) |

## Recommended first pass (priority = now)

- [Rewrite the Float encode/decode pair as a correct IEEE-754 codec (signed zero, subnormals, inf, NaN, overflow-to-inf, round-to-nearest-even)](float.md#1-rewrite-the-float-encode-decode-pair-as-a-correct-ieee-754-codec-signed-zero-subnormals-inf-nan-overflow-to-inf-round-to-nearest-even) ✓
- [Swap Float.specialize's base order so the struct-packed value path wins the MRO](float.md#2-swap-float-specialize-s-base-order-so-the-struct-packed-value-path-wins-the-mro) ✓
- [Fix the Int copy-paste leftovers in the Float class docstring](float.md#5-fix-the-int-copy-paste-leftovers-in-the-float-class-docstring) ✓
- [Attribute NarrowingWarning to the first frame outside bytemaker instead of a fixed stacklevel](narrowing.md#1-attribute-narrowingwarning-to-the-first-frame-outside-bytemaker-instead-of-a-fixed-stacklevel) ✓
- [Route all integer box stores through a shared _narrow_int helper so struct-packed widths warn too](narrowing.md#2-route-all-integer-box-stores-through-a-shared-narrow-int-helper-so-struct-packed-widths-warn-too) ✓
- [Gate SInt8/16/32/64 struct packing on the instance's int_format via a shared _StructPackedSInt base](narrowing.md#3-gate-sint8-16-32-64-struct-packing-on-the-instance-s-int-format-via-a-shared-structpackedsint-base) ✓
- [Compare the coerced bit length, not the raw element count, in FixedLengthBitVector.__setitem__](bitvector-behavior.md#1-compare-the-coerced-bit-length-not-the-raw-element-count-in-fixedlengthbitvector-setitem) ✓
- [Route append/insert/remove/extend through _coerce_bit in the bitarray backend](bitvector-behavior.md#3-route-append-insert-remove-extend-through-coerce-bit-in-the-bitarray-backend) ✓
- [Restrict bitarray-backend __eq__/__ne__ to BitVector operands, matching the other backends](bitvector-behavior.md#6-restrict-bitarray-backend-eq-ne-to-bitvector-operands-matching-the-other-backends) ✓
- [Make to_bytes() whole-vector right-aligned (integer bytes), documented against left-aligned tobytes()](bitvector-behavior.md#7-make-to-bytes-whole-vector-right-aligned-integer-bytes-documented-against-left-aligned-tobytes) ✓
- [Treat an empty codepoint_changes mapping as a no-op in the substitute helpers](string.md#1-treat-an-empty-codepoint-changes-mapping-as-a-no-op-in-the-substitute-helpers) ✓
- [Reject empty-string keys and values in codepoint_changes instead of compiling a match-everywhere regex](string.md#2-reject-empty-string-keys-and-values-in-codepoint-changes-instead-of-compiling-a-match-everywhere-regex) ✓
- [Write BoundBits delegated mutators through the width-validating store](structs.md#1-write-boundbits-delegated-mutators-through-the-width-validating-store) ✓
- [Detach-copy Struct-valued field defaults per instance at __init__ bind time](structs.md#2-detach-copy-struct-valued-field-defaults-per-instance-at-init-bind-time) ✓
- [Make ctypes endianness reversal pure: compute reversed bytes from a snapshot, never mutate the caller's object](ctypes.md#1-make-ctypes-endianness-reversal-pure-compute-reversed-bytes-from-a-snapshot-never-mutate-the-caller-s-object) ✓
- [Check every _fields_ entry (including nested structures') for bitfields and name the offending field in the error](ctypes.md#2-check-every-fields-entry-including-nested-structures-for-bitfields-and-name-the-offending-field-in-the-error) ✓
- [Fix run-together words in the ctype_to_bytes / bytes_to_ctype TypeError messages](ctypes.md#3-fix-run-together-words-in-the-ctype-to-bytes-bytes-to-ctype-typeerror-messages) ✓
- [Make is_instance_of_union element checks real: handle empty iterables, check all elements, support Literal](aggregate-utils.md#1-make-is-instance-of-union-element-checks-real-handle-empty-iterables-check-all-elements-support-literal) ✓
- [Raise TypeError from count_bits_in_unit_type for unsupported types instead of returning None](aggregate-utils.md#2-raise-typeerror-from-count-bits-in-unit-type-for-unsupported-types-instead-of-returning-none) ✓
- [Make to_bytes_aggregate raise on unconvertible input like its to_bits_aggregate dual](aggregate-utils.md#3-make-to-bytes-aggregate-raise-on-unconvertible-input-like-its-to-bits-aggregate-dual) ✓
- [Validate buffer length at the top of Plan.unpack_tuple so both tiers reject wrong-length input with a uniform ValueError](plans.md#1-validate-buffer-length-at-the-top-of-plan-unpack-tuple-so-both-tiers-reject-wrong-length-input-with-a-uniform-valueerror) ✓
- [Validate value count at the top of Plan.pack_tuple so both tiers reject wrong-arity sequences with a uniform ValueError](plans.md#2-validate-value-count-at-the-top-of-plan-pack-tuple-so-both-tiers-reject-wrong-arity-sequences-with-a-uniform-valueerror) ✓
- [Make the registered str conversion a strict one-byte char: reject strings whose UTF-8 encoding is not exactly 8 bits](pytypes.md#3-make-the-registered-str-conversion-a-strict-one-byte-char-reject-strings-whose-utf-8-encoding-is-not-exactly-8-bits) ✓
- [Add a validate_endianness helper and reject typo'd endianness at BitType construction and bytes_to_bittype](endianness.md#1-add-a-validate-endianness-helper-and-reject-typo-d-endianness-at-bittype-construction-and-bytes-to-bittype) ✓
- [Validate endianness at every conversion, aggregate, oracle, and schema intake (pytypes, ctypes, legacy aggregate, wrappers, Array)](endianness.md#2-validate-endianness-at-every-conversion-aggregate-oracle-and-schema-intake-pytypes-ctypes-legacy-aggregate-wrappers-array) ✓
- [Make Buffer.value return an independent BitVector snapshot instead of the live width-locked bits handle](buffer.md#2-make-buffer-value-return-an-independent-bitvector-snapshot-instead-of-the-live-width-locked-bits-handle) ✓
- [Document to_pyint's real receiver instead of a phantom `bitstring` parameter](docs-misc.md#2-document-to-pyint-s-real-receiver-instead-of-a-phantom-bitstring-parameter) ✓
- [Point the SInt docstring at SignedConfig, the class that actually exists](docs-misc.md#3-point-the-sint-docstring-at-signedconfig-the-class-that-actually-exists) ✓
- [Add __all__ to fields.pyi so the checker's star-import surface matches runtime](docs-misc.md#4-add-all-to-fields-pyi-so-the-checker-s-star-import-surface-matches-runtime) ✓
- [Replace the to_chararray length assert with an explicit ValueError in all three backends](bitvector-polish.md#5-replace-the-to-chararray-length-assert-with-an-explicit-valueerror-in-all-three-backends) ✓
- [Oracle sync: give to_bytes_aggregate the same multi-char-str carve-out as to_bits_aggregate (required once pytypes-3 lands); drop the commented scaffolding](lows-code.md#7-oracle-sync-give-to-bytes-aggregate-the-same-multi-char-str-carve-out-as-to-bits-aggregate-required-once-pytypes-3-lands-drop-the-commented-scaffolding) ✓

## Decisions needed from you

- **[Rewrite the Float encode/decode pair as a correct IEEE-754 codec (signed zero, subnormals, inf, NaN, overflow-to-inf, round-to-nearest-even)](float.md#1-rewrite-the-float-encode-decode-pair-as-a-correct-ieee-754-codec-signed-zero-subnormals-inf-nan-overflow-to-inf-round-to-nearest-even)** — to_binstring now overflows to signed infinity (IEEE/C conversion semantics), but the struct-packed siblings still raise struct's OverflowError on an out-of-range store (e.g. Float32(1e300)). Should StructPackedBitType's float path catch OverflowError and store +/-inf so the whole Float family overflows uniformly, or is raise-on-overflow the preferred contract for the struct-packed types?
Yes
- **[Coerce Float.value setter input with float() instead of isinstance-rejecting non-floats](float.md#3-coerce-float-value-setter-input-with-float-instead-of-isinstance-rejecting-non-floats)** — Accept the float() contract wholesale (numeric strings included, matching the constructor), or add an explicit isinstance(value, str) rejection so the setter takes real numbers only, matching struct.pack? The patch as written chooses the former for symmetry with the constructor.
Reject strings.
- **[Route all integer box stores through a shared _narrow_int helper so struct-packed widths warn too](narrowing.md#2-route-all-integer-box-stores-through-a-shared-narrow-int-helper-so-struct-packed-widths-warn-too)** — The legacy fast-path guard means NarrowingConfig.warn=True routes legacy dataclass packing through the slower boxed path so warnings fire consistently there too. OK to trade fast-path speed for diagnostic consistency in the (debug-only) warn mode, or would you rather keep the fast path silent and scope the warning contract to stores only?
Yes.
- **[Validate int_format at SInt construction and name the parameter and choices in the error](narrowing.md#4-validate-int-format-at-sint-construction-and-name-the-parameter-and-choices-in-the-error)** — The 'sign_magnitude' alias is normalized-and-accepted here because to_pyint/to_bitstring already accept it. Would you rather reject it at the constructor and drop the alias branches in to_pyint/to_bitstring/min_bit_length too (sole-user, no compat pressure)?
Yes, reject.
- **[Raise ValueError for length-mismatched extended-slice assignment (including empty) on native and speedup](bitvector-behavior.md#4-raise-valueerror-for-length-mismatched-extended-slice-assignment-including-empty-on-native-and-speedup)** — Extended-slice-with-empty-value policy: adopt list/bitarray semantics (raise ValueError) everywhere, rather than replicating bytearray's silent delete in the bitarray backend. Confirm raising is the intended semantics (it matches the docstring and the active backend).
Yes, with a note that as of 3 August 2026, bytearray was unique in that other interpretation
- **[Make to_bytes() whole-vector right-aligned (integer bytes), documented against left-aligned tobytes()](bitvector-behavior.md#7-make-to-bytes-whole-vector-right-aligned-integer-bytes-documented-against-left-aligned-tobytes)** — to_bytes partial-byte policy: whole-vector RIGHT alignment (integer semantics, chosen here because to_int and its pinned tests depend on it and it fixes to_int for multi-byte partial widths) versus the finding's alternative of left-aligning to match tobytes (which would break BitVector('101').to_int(signed=False)==5 and require a to_int rewrite). Confirm the right-aligned choice.
Choose whole-vector right alignment for to_bytes().

Your reasoning is sound:

tobytes() / bytes(bv) represents a bit stream, so trailing partial bytes are padded on the right.
to_bytes() represents the vector’s integer value, so the complete vector is padded on the left.
This preserves BitVector('101').to_int(signed=False) == 5.
It fixes multi-byte, non-byte-aligned vectors such as 10-bit 0100000011, which should serialize as b'\x01\x03'.
Making to_bytes() left-aligned would merely duplicate tobytes() and force to_int() to compensate elsewhere.

I would confirm it with wording like:

Confirm whole-vector right alignment. to_bytes() should serialize the vector as a big-endian integer, equivalent to:

int(bits, 2).to_bytes((len(bits) + 7) // 8, "big")

By contrast, tobytes() and bytes() serialize a bit stream and right-pad the final partial byte. This preserves the established unsigned to_int() semantics and fixes incorrect values for vectors wider than one byte whose width is not divisible by eight.

One important caveat: verify signed conversion separately. For a 3-bit two’s-complement vector such as 101, right-aligned bytes are 0x05; a naive int.from_bytes(..., signed=True) reads that as +5, not -3, because the vector’s sign bit is not the byte’s high bit. Signed conversion should use the vector width directly rather than relying only on the padded byte representation.

Tests should pin at least:

BitVector("101").to_bytes() == b"\x05"
BitVector("0100000011").to_bytes() == b"\x01\x03"
BitVector("0100000011").to_int(signed=False) == 259
bytes(BitVector("101")) == b"\xa0"

So: sign off on the right-aligned patch, while making sure signed-width semantics are not accidentally coupled to byte-level sign interpretation.
- **[Give pop() Python-style negative indexing and honest out-of-range errors on all three backends](bitvector-behavior.md#8-give-pop-python-style-negative-indexing-and-honest-out-of-range-errors-on-all-three-backends)** — pop(-1) semantics: switch from the documented 'negative indices are out of bounds' quirk to Python-standard from-the-end indexing (list.pop parity). This edits a pinned parity test — confirm the quirk was not load-bearing for anything outside the repo.
Make pop(-1) return give the last element, pop(-2) the second to last, and so on, up to the point of an out of range error (which should throw and index error)
- **[Reject empty-string keys and values in codepoint_changes instead of compiling a match-everywhere regex](string.md#2-reject-empty-string-keys-and-values-in-codepoint-changes-instead-of-compiling-a-match-everywhere-regex)** — Rejection assumes you never want one-way deletion rules ({'X': ''}, e.g. dropping a control char on decode). If you do want that, the right design is an explicit one-way substitution knob rather than an invertible mapping with empty values — say the word and this becomes a follow-up feature instead.
Sure.
- **[Unify the errors= vocabulary: TableString honors 'ignore', and of() validates the policy at mint time](string.md#4-unify-the-errors-vocabulary-tablestring-honors-ignore-and-of-validates-the-policy-at-mint-time)** — TableString now ACCEPTS 'ignore' (matching standard codecs) rather than rejecting everything but strict/replace at mint — confirm you want table codecs to gain the policy rather than shrink the shared vocabulary to {'strict','replace'}.
Sure, widen.
- **[Detach-copy Struct-valued field defaults per instance at __init__ bind time](structs.md#2-detach-copy-struct-valued-field-defaults-per-instance-at-init-bind-time)** — Struct-valued defaults are now silently detach-copied per instance (dataclass-like semantics with an auto-copy instead of dataclasses' default_factory refusal) -- reversing behavior you explicitly pinned in test_array_of_struct_element_aliases_like_nested_struct. Confirm you want auto-copy rather than the alternative: keep by-reference defaults and add a default_factory= parameter to field()/array() (more API, no silent copying).
We need to revisit this after the other decisions. This will depend on whether the BitTypes continue to be allowed to be mutable or not. In the meantime, go ahead.
- **[Make the Codec protocol docstring state the real membership and pack convention](structs.md#3-make-the-codec-protocol-docstring-state-the-real-membership-and-pack-convention)** — Doc-truth was chosen over making scalar BitTypes real Codecs (thin parse/pack shims on BitType would flip isinstance(UInt16, Codec) to True and match the observations/09 architecture direction, but touches bittypes/bittype.py, which the narrowing-1 fix from another group is already editing). Want the BitType shims as a follow-up?
Make this a "TODO". We probably do want the scalar BitType classes to be Codecs, just aren't doing it right now because we don't want to touch too many things at once.
- **[Make ctypes endianness reversal pure: compute reversed bytes from a snapshot, never mutate the caller's object](ctypes.md#1-make-ctypes-endianness-reversal-pure-compute-reversed-bytes-from-a-snapshot-never-mutate-the-caller-s-object)** — Union policy: reversal currently passes Union bytes through unchanged (the historical behavior, now documented). Since the active member is unknowable, a silent passthrough can produce wrong-endianness output without warning -- should Unions (and structs containing them) instead raise NotImplementedError when a byte-order swap is actually required (endianness != sys.byteorder)? Passthrough keeps the existing test-visible behavior; raising is stricter and more honest.
Sure, raise.
- **[Make is_instance_of_union element checks real: handle empty iterables, check all elements, support Literal](aggregate-utils.md#1-make-is-instance-of-union-element-checks-real-handle-empty-iterables-check-all-elements-support-literal)** — Empty-iterable policy: proposed True ([] IS an Iterable[int]; also keeps '[] in bv' == True, consistent with '"" in "abc"'). And one-shot iterators are accepted unchecked rather than consumed or rejected. Confirm both policies.
Policy A: Sure.
Policy B: Do (accept unchecked - iterator passes the gate untouched; caller iterates it intact), sure.
- **[Sync the is_array=True list-return fix into the frozen oracle's from_bytes_aggregate](aggregate-utils.md#4-sync-the-is-array-true-list-return-fix-into-the-frozen-oracle-s-from-bytes-aggregate)** — The full sync also fixes oracle scalar+is_array (previously ValueError). Alternative was a minimal one-line sync (retval = arr_entry_list) that would leave scalar arrays diverged; confirm the full sync is preferred.
Yes.
- **[Validate buffer length at the top of Plan.unpack_tuple so both tiers reject wrong-length input with a uniform ValueError](plans.md#1-validate-buffer-length-at-the-top-of-plan-unpack-tuple-so-both-tiers-reject-wrong-length-input-with-a-uniform-valueerror)** — Wrong-length input on the ALIGNED tier now raises ValueError instead of struct.error, and iter_tuples with an over-large explicit count on the shiftmask tier now raises instead of fabricating zero records -- confirm uniform ValueError is the wanted policy (the alternative is raising struct.error to keep the aligned tier's historical type).
Yes.
- **[Convert ConversionInfo.num_bytes/to_bytes/from_bytes from broken classmethods to working instance methods](pytypes.md#1-convert-conversioninfo-num-bytes-to-bytes-from-bytes-from-broken-classmethods-to-working-instance-methods)** — Repair (proposed) vs delete: these helpers have zero callers in the package — if you would rather shrink the API surface, deleting the three methods is equally safe.
Delete
- **[Make the registered str conversion a strict one-byte char: reject strings whose UTF-8 encoding is not exactly 8 bits](pytypes.md#3-make-the-registered-str-conversion-a-strict-one-byte-char-reject-strings-whose-utf-8-encoding-is-not-exactly-8-bits)** — Should the char codec stay UTF-8 (proposed; rejects non-ASCII one-char strings like '\u00e9' since they need 2+ bytes) or switch to latin-1 so all 256 one-byte values round-trip? UTF-8 keeps today's decode side and byte values < 0x80 identical; latin-1 would widen the accepted alphabet but change the meaning of decoded bytes >= 0x80. ALSO: Should the one-byte-char enforcement be extended to the bits path too (to_bits_aggregate raising the same ValueError for len!=1 strings, syncing the duals per the oracle procedure), or is the bytes-path-only change acceptable?
Part 1 — switch to latin-1, keep it fixed-width.

Change the registered str ConversionInfo to latin-1 on both sides — encode s.encode('latin-1') and decode b.to_bytes().decode('latin-1') — keeping num_bits=8 and the strict "exactly one character" gate. Rationale: for a byte library the one-byte-char primitive should cover all 256 byte values losslessly (256/256 round-trip, no UnicodeDecodeError class), and latin-1 is the canonical byte↔char bijection. Bytes < 0x80 stay identical to today; bytes ≥ 0x80 change from "decode error" to their Latin-1 character, which is a strict improvement over crashing.

Constraints for the implementation:

Keep it strict single-char / fixed-width. Do not uncomment the variable-width _string_conversion_info — a codec that reports num_bits=8 but emits variable width is the exact incoherence this fix exists to remove (and it returns 0 for the '' placeholder the layout engine sizes from).
Alternative single-byte codepages stay configurable via ConversionConfig.set_conversion_info(...) (already works) — latin-1 is just the new default.
UTF-8 / multi-byte / variable-width text belongs in the String bittypes (String.of(encoding='utf-8', ...)), which already handle variable width, padding, and terminators. Do not try to fold UTF-8 into the fixed-num_bits registry conversion.
Part 2 — extend enforcement to the bits path, but as a width check (not a blanket rejection).

Yes, sync the bits path so it can't silently overflow — but adopt option (c), not a blanket len != 1 reject:

A bare/top-level string with no declared width (to_bits_aggregate('ABC')) keeps its per-char behavior — that's a legitimate "serialize the string as its characters" use, and blanket rejection would break it.
A string in a declared-width field that doesn't fit (to_bits_aggregate(Rec('ABC', 5)), 24 bits into an 8-bit field) must raise ValueError at serialize time, at the point of misuse — closing the silent 56-vs-40-bit overflow.
A blanket len!=1 rejection everywhere (option a) is too aggressive and is not what I want.

Note — coupled decisions, and re-verification. This settles lows-code-7 too: it's the same question from the aggregate side, so apply option (c) there as well (per-char until it overflows a declared width, then a loud ValueError). Don't resolve lows-code-7 independently — both the bits and bytes paths must land on the one rule. And be aware this reshapes pytypes-3: latin-1 now touches the decode side (not encode-only), plus the bits-path width check is new. The original empirical pass was UTF-8-encode-only, so re-verify the three changes together — latin-1 encode and decode, the bits-path width check, and lows-code-7's width check — rather than trusting the prior verification.
- **[Add a validate_endianness helper and reject typo'd endianness at BitType construction and bytes_to_bittype](endianness.md#1-add-a-validate-endianness-helper-and-reject-typo-d-endianness-at-bittype-construction-and-bytes-to-bittype)** — Vocabulary: strict-exact {'big','little'} (proposed), matching structs.py's existing check and the int.from_bytes contract BitVector.to_int already exposes -- or should the helper lowercase-normalize (accept 'Big'/'LITTLE') and/or accept aliases ('le'/'be'/'<'/'>')? Strict-exact keeps every intake in the package and the stdlib delegate accepting the identical vocabulary; normalizing only the helper-guarded sites would make UInt8(1, endianness='BIG') legal while BitVector.to_int('BIG') and struct-compile stay illegal.
Strict {'big', 'little'}, yeah.
- **[Make Buffer.value return an independent BitVector snapshot instead of the live width-locked bits handle](buffer.md#2-make-buffer-value-return-an-independent-bitvector-snapshot-instead-of-the-live-width-locked-bits-handle)** — Confirm the value-plane policy: Buffer.value now returns a resizable BitVector snapshot (chosen — matches every other BitType's safe .value read and the documented 'BitVector(bits) for a snapshot' idiom), rather than keeping the live alias and merely documenting the hazard. If you prefer the returned snapshot to stay width-locked (FixedLengthBitVector copy) instead of resizable, say so — resizable was chosen because py_type is plain BitVector and the .bits docstring calls BitVector(bits) 'a resizable snapshot'.
Snapshot, not the live alias. Buffer.value should return an independent copy, as proposed — don't keep the live handle and merely document the hazard. This restores the library-wide two-plane contract (.value = safe plain-value read, .bits = deliberate live handle) that every other BitType already honors, and it's the escape hatch BitType.bits's own docstring prescribes (BitVector(bits)). Grep confirmed no caller relies on the write-through alias, so this is reject-only with zero blast radius — the right call under the no-compat-pressure policy.

Resizable BitVector, not a width-locked FixedLengthBitVector copy. Once the snapshot is detached, the width-lock protects nothing — the buffer is already safe because you handed back a copy; locking the copy would only restrict the caller's freedom to work with their own value, for no benefit. Resizable also matches Buffer.py_type (plain BitVector) and the documented "resizable snapshot" idiom. Keep the getter returning BitVector(self.bits).

Apply with buffer-1. buffer-1's rewritten Instance Attributes block already describes value as an independent, resizable snapshot, so land the two together (or buffer-2 first). No separate decision needed on buffer-1 — this settles its docstring direction.
- **[Make __repr__ actually round-trippable (kwargs form, quoted values) instead of documenting a format it never produced](docs-misc.md#1-make-repr-actually-round-trippable-kwargs-form-quoted-values-instead-of-documenting-a-format-it-never-produced)** — Chose to fix the code to match the docstring's promise (truthful eval-able repr) rather than weaken the docstring - and bits-form over value-form (UInt8(40, ...)) because bits are exact for every subclass while str() already shows the value. Confirm you prefer bits-form; switching to value-form is a two-line variant but loses NaN-payload/odd-pattern fidelity and needs per-family thought.
Round-trip is definitely useful. Bits form.
- **[SInt.value setter's 'reject out-of-range' claim: resolved by narrowing-3's per-instance gate (no new edit)](docs-misc.md#5-sint-value-setter-s-reject-out-of-range-claim-resolved-by-narrowing-3-s-per-instance-gate-no-new-edit)** — Confirm the deferral: this finding produces no edit because narrowing-3 makes the documented behavior real (empirically verified). Apply the fallback comment only if narrowing-3 is dropped.
Yeah.
- **[Validate at the source: mint/entry-point checks instead of deep, late failures](lows-ux.md#3-validate-at-the-source-mint-entry-point-checks-instead-of-deep-late-failures)** — pytypes dead loop: DELETE (recommended, keeps the legacy conversion surface frozen) vs uncomment the registration to actually support bytes/bytearray/memoryview in legacy aggregates - flag if bytes support is actually wanted.
Sure, delete.
- **[Discoverability: package re-exports, undocumented params, the stub's 64-bit cliff, and runtime deprecation signals](lows-ux.md#5-discoverability-package-re-exports-undocumented-params-the-stub-s-64-bit-cliff-and-runtime-deprecation-signals)** — to_bits/from_bits: warn now + migrate callers (recommended), or delete outright per the '# TODO remove' since the sole user can absorb it in one commit? Warning first is proposed because the methods still appear in 11 test sites and possibly downstream scripts.
Delete
- **[from_int: size the overflow check with the two's-complement width so positive values keep their sign bit (all three backends)](lows-code.md#4-from-int-size-the-overflow-check-with-the-two-s-complement-width-so-positive-values-keep-their-sign-bit-all-three-backends)** — from_int could instead grow a signed: bool = True parameter (signed=False keeping the old bit_length check) — wider API for a method slated for removal; default proposal is the strict signed check only.
Strict, yes.
- **[Oracle sync: give to_bytes_aggregate the same multi-char-str carve-out as to_bits_aggregate (required once pytypes-3 lands); drop the commented scaffolding](lows-code.md#7-oracle-sync-give-to-bytes-aggregate-the-same-multi-char-str-carve-out-as-to-bits-aggregate-required-once-pytypes-3-lands-drop-the-commented-scaffolding)** — String policy for the legacy aggregate path - pick one: (a) strict one-char everywhere (pytypes-3 as-is, no carve-out): multi-char strings fail loudly on both paths; simplest and most honest, but breaks to_bytes_aggregate('hi') uses; (b) this carve-out as proposed: per-char semantics restored on both paths, but structured records with multi-char str fields silently emit more bytes than the declared width (the Rec regression above); (c) carve-out PLUS a declared-width check at serialize time: per-char when the encoded length matches the declared bits, loud ValueError when it does not - restores both behaviors at the cost of a few extra lines in both paths (recommended).
lows-code-7: Option (c) — carve-out plus declared-width check. Per-char for bare strings (keeps to_bytes_aggregate('hi') working), loud ValueError when a declared-width str field overflows (keeps pytypes-3's Rec('ABC', 5) fix). This is the aggregate-side of the same rule I chose for pytypes-3; land the two together (this must land with or before pytypes-3). Drop the commented scaffolding as proposed
