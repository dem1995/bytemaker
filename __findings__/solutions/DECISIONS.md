# bytemaker — maintainer decisions on the open questions

Hand-off record for whoever applies the [proposed solutions](README.md). It resolves every
**"Decisions needed from you"** bullet in the README, plus the cross-cutting strategy calls.

## How to read this

Each entry has a **status**:

- ✅ **DECIDED** — the maintainer has committed to this.
- ▶ **RECOMMENDED** — the working recommendation, pending the maintainer's final nod. Where a
  recommendation is contingent ("delete *unless* …"), the condition is stated.
- ⚠ **CHANGES THE PROPOSED PATCH** — this ruling is **not** "apply the solution as written." The
  applier must **modify** the patch (or add an edit beyond it). Watch these five: **float-1** and
  **structs-2** *extend* the patch with an edit it doesn't include; **ctypes-1**, **pytypes-3**
  (Part 1), and **float-3** *change* the patch's chosen option. Every other entry confirms the patch (or defers to it).

Most entries are ▶: they were worked through with the maintainer as recommendations. The ✅ items
were settled explicitly. Nothing here has been applied to the source.

---

## Strategic decisions (read first)

### S1 — Sequencing vs. the immutability question · ▶ RECOMMENDED
**Apply the solutions first; treat scalar-BitType immutability as a separate later project.**
The value/container split (scalars = values, containers = storage) is the seam: containers
(`Struct`, `Array`, `Buffer`, `BitVector`) stay mutable; only the *scalar* boxes (`UInt8`,
`Float32`, …) are immutability candidates. Rationale: (1) the 82 solutions are verified against the
current codebase — reordering invalidates that; (2) most solutions are orthogonal to mutability;
(3) the solutions build the test net that de-risks any later immutability work.
**If** immutability is later committed: skip **float-3** (it deletes the `.value` setter it patches)
and treat **narrowing-2** as "keep the `_narrow_int` helper, expect its call sites to move from
setters to construction." Prototype on one type (`UInt8`) first.

### S2 — What immutability would delete/rework (for planning only)
Under scalar-immutability: **float-3** disappears entirely; **narrowing-2**'s helper survives but its
call sites move; everything else is orthogonal. The commented-out `__hash__` (bittype.py) and the
promotion-to-plain-int arithmetic are evidence the design already half-treats scalars as values.

---

## Quick reference

| # | Decision | Ruling | Status |
|---|---|---|---|
| float-1 | Float overflow | ⚠ **Store ±inf (C behavior) + emit a warning** — two edits beyond the base patch | ✅ |
| float-3 | `Float.value` setter coercion | ⚠ **Reject strings** (add `isinstance(value, str)` guard) — per the README answer; changes the patch | ▶ |
| narrowing-2 | Legacy fast-path in warn mode | **Reroute** through boxed path (diagnostic consistency > debug-mode speed) | ▶ |
| narrowing-4 | `'sign_magnitude'` alias | **Keep the patch** (normalize-and-accept; harmless — no purge) | ✅ |
| bitvector-behavior-4 | Extended-slice empty value | **Raise `ValueError`** (list/bitarray semantics) | ▶ |
| bitvector-behavior-7 | `to_bytes()` partial-byte align | **Whole-vector right-align** (integer semantics; fixes `to_int`) | ▶ |
| bitvector-behavior-8 | `pop(-1)` semantics | **Python list-parity** (negatives from the end) | ▶ |
| string-2 | Empty `codepoint_changes` entries | **Reject**; one-way-deletion feature deferred | ▶ |
| string-4 | `TableString` `errors=` vocabulary | **Widen** — tables gain `'ignore'` | ▶ |
| structs-2 | Struct-valued defaults | ⚠ **Auto-copy** per instance (patch) **+ add the `_MISSING` sentinel** (not in patch) | ▶ |
| structs-3 | `Codec` protocol | **Doc-truth now**; BitType Codec shims deferred | ▶ |
| ctypes-1 | Union endianness reversal | ⚠ **Raise `NotImplementedError`** for multi-byte unions (patch passes through — change it) | ✅ |
| aggregate-utils-1 | `is_instance_of_union` policies | **Confirm both** (empty→True; iterators unchecked) | ▶ |
| aggregate-utils-4 | Oracle `is_array` sync | **Full sync** (fixes dataclass + scalar) | ▶ |
| plans-1 | Wrong-length `unpack_tuple` | **Uniform `ValueError`** both tiers (plans-2 is the independent dual, same choice) | ▶ |
| pytypes-1 | Dead `ConversionInfo` byte helpers | **Optional** — patch repairs (fine); delete only to shrink surface | ▶ |
| pytypes-3 | char codec charset + bits-path sync | ⚠ **latin-1** — **patch proposes UTF-8** — + UTF-8 via `String`; **option (c)** width-check | ✅ |
| endianness-1 | endianness vocabulary | **Strict-exact `{'big','little'}`** | ▶ |
| buffer-2 | `Buffer.value` plane | **Independent resizable `BitVector` snapshot** | ✅ |
| docs-misc-1 | `__repr__` | **Fix the code** (eval-able) + **bits-form** | ▶ |
| docs-misc-5 | SInt setter reject-claim | **Confirm deferral** (narrowing-3 makes it true) | ▶ |
| lows-ux-3 | pytypes dead loop | **Delete** — no bytes support in the legacy registry | ▶ |
| lows-ux-5 | `to_bits`/`from_bits` | **Warn-first** (keep the patch's cautious default) + migrate callers | ✅ |
| lows-code-4 | `from_int` overflow check | **Strict signed check** (no `signed=` param) | ▶ |
| lows-code-7 | Legacy aggregate string policy | **Option (c)** — carve-out + declared-width check | ✅ |

---

## Decisions in detail

### float-1 — Float overflow · ✅ DECIDED · ⚠ extends the patch
**Overflow follows C/IEEE behavior — store ±inf, not an error — AND emits a warning when warn-mode is
on.** Both float paths saturate a too-large magnitude to signed infinity (uniform across the whole
Float family, matching a C `double`→`float` conversion). The saturation is silent by default but
routes through the same warning mechanism as integer narrowing, so it is *reportable*.
⚠ **Two edits beyond the base patch:**
1. float-1 as written only rewrites the *pure-Python* codec. Add the same overflow-to-±inf to
   `StructPackedBitType.value`'s float path (catch `struct`'s `OverflowError`, store ±inf) so the
   struct-packed types (`Float16/32/64`) stop raising and join the uniform contract.
2. **New (from the review discussion):** make float overflow-to-inf emit a `NarrowingWarning` when
   `NarrowingConfig.warn` is enabled, reusing narrowing-1's `_warn_narrowing` emitter (e.g.
   `"narrowing store to Float32: 1e+300 became inf"`). This closes the int/float asymmetry — integer
   overflow warns under warn-mode, so float overflow should too. **This is a synthesized requirement
   not present in any verified patch — it needs implementing and testing**, and it couples float-1 to
   narrowing-1 (the warning emitter) and `NarrowingConfig`.

### float-3 — `Float.value` setter coercion · ▶ RECOMMENDED · ⚠ changes the patch
⚠ **Reject strings** — the README answer ("Reject strings.") chooses the alternative the patch did
*not* take. The patch coerces via `value = float(value)`, which accepts ints, bools, **and numeric
strings** (constructor symmetry). This ruling instead adds an explicit `isinstance(value, str)` guard
raising `TypeError` **before** the coercion, so the setter takes real numbers only — matching the
struct-packed siblings (which reject strings via `struct.error`), at the cost of that symmetry.
**This changes the patch.** **Low-stakes** and **likely mooted** if scalars go immutable (no setter to
argue about). Apply after float-1 (adjacent regions; float-1 leaves this setter untouched).
*(Correction: an earlier version of this record recommended accept-strings, which contradicted the
README answer; corrected to reject on 2026-08-06.)*

### narrowing-2 — Legacy fast-path guard in warn mode · ▶ RECOMMENDED
Keep the guard: when `NarrowingConfig.warn=True`, route legacy dataclass packing through the boxed
coercion path so warnings fire consistently. `warn` defaults **off**, so production packing is
untouched; the speed cost is paid only in the debug mode you deliberately enabled, in exchange for a
`-Wconversion` knob that's actually exhaustive. Byte output is identical either way.
**Apply after (or with) narrowing-1** — the shared `_narrow_int` helper adds a stack frame the fixed
`stacklevel=3` could not tolerate.

### narrowing-4 — `'sign_magnitude'` alias · ✅ DECIDED (confirms the patch)
**Keep the patch as written: normalize-and-accept the alias.** The constructor accepts the
undocumented `'sign_magnitude'` spelling and immediately rewrites it to the canonical
`'signed_magnitude'`, so internally `int_format` is always one of the three literals. An earlier
recommendation was to purge the alias entirely; on reflection that's over-engineering —
accept-and-normalize is harmless (nothing downstream ever sees the odd spelling), whereas purging
means a whole-tree grep, three deletions, and re-verification for a cosmetic gain. Leave the harmless
version. *(The rest of narrowing-4 — validating `int_format` at construction and naming the valid
choices in the error — is uncontested and stands.)*

### bitvector-behavior-4 — Extended-slice length-mismatch (incl. empty) · ▶ RECOMMENDED
**Confirm raise.** Adopt list/bitarray semantics (`ValueError`) on native + speedup, matching the
active bitarray backend and the method's own docstring. The silent-delete on native/speedup is an
inherited `bytearray` quirk, not intent. Also changes the error *message* on native/speedup to match
bitarray's wording — update any test pinning the old `"bytes"` text (suite reports none).

### bitvector-behavior-7 — `to_bytes()` partial-byte alignment · ▶ RECOMMENDED
**Confirm whole-vector right-alignment** (bits as a big-endian integer, left-padded). It keeps every
byte-aligned and sub-byte result identical, **fixes** a latent `to_int` wrong-value bug for multi-byte
partial widths, and preserves the pinned `to_int` cases. The finding's left-align alternative would
break `BitVector('101').to_int(signed=False)==5` and make `to_bytes` redundant with `tobytes`.
**Sync obligation:** all three backends **plus** the differential test's `to_bytes` comparison move
together.

### bitvector-behavior-8 — `pop(-1)` semantics · ▶ RECOMMENDED
**Confirm Python list-parity** (negatives count from the end; honest out-of-range messages). Verified:
`list`/`bytearray`/`array`/`bitarray` all normalize negatives from the end — the old "negatives are
out of bounds" quirk matches nothing in the stdlib, and is imposed by BitVector's own wrapper, not
the backends. Edits a pinned parity test (rewritten in the same change) and updates
`BoundBits.pop`'s stale comment. **Caveat:** grep your own out-of-repo scripts for `pop(-1, …)` used
as an is-empty probe (the `default` param is a BitVector-only extension).

### string-2 — Empty `codepoint_changes` entries · ▶ RECOMMENDED
**Confirm reject.** Empty keys/values corrupt silently (an empty value compiles to a zero-width regex
that inserts at every position; a deletion rule has no inverse in a bidirectional map). Rejection is
correct regardless. **Do not** build the one-way-deletion feature speculatively — the existing
`terminator`/`strip`/`errors='ignore'` knobs cover the common cases; add an explicit decode-only
substitution knob later *only if* a concrete format needs per-character deletion.
Composes with string-1 (empty *mapping* → no-op); apply string-1/string-2 first.

### string-4 — `TableString` `errors=` vocabulary · ▶ RECOMMENDED
**Confirm widen.** Teach `TableString` a real `'ignore'` branch so `strict`/`replace`/`ignore` mean
the same across every codec — `ignore` is the trivial twin of the `replace` tables already support,
and it's the exact set of policies with coherent table semantics (escape-style handlers stay
standard-codec-only). Purely additive; no existing table uses `errors='ignore'`.
**Apply before or with string-6** (its new `String` docstring documents this vocabulary).

### structs-2 — Struct-valued field defaults · ▶ RECOMMENDED · ⚠ extend the patch
**Auto-copy per instance** (detach-copy at `__init__`) — this *is* the patch — **and additionally
apply the `_MISSING` sentinel fix, which the patch does *not* include.** The patch as written
triggers the copy on object identity (`if n is _d_n`), so explicitly passing the exact default
object still copies it (the corner the reviewer flagged). The sentinel (parameter default =
`_MISSING`, not the object) is a small codegen addition that closes that corner, making "explicit
assignment keeps the live reference" true without exception. bytemaker *can* safely deep-copy a
Struct (`detach_copy`) — the capability `dataclasses` lacks — so the naive `a: Inner = Inner(3)`
spelling works, rather than importing `default_factory`.
**Ships with the rewrite of `test_array_of_struct_element_aliases_like_nested_struct`** (same commit).

### structs-3 — `Codec` protocol · ▶ RECOMMENDED
**Take the doc-truth fix now** (rewrite the docstring to state that Struct classes and Array instances
are the codecs; scalar BitTypes are not). **Defer the BitType Codec shims** — they're a legitimate
direction (`observations/09`), but they touch `bittype.py`, which is exactly the file an
immutability refactor would rewrite. Add Codec membership to scalars *when `bittype.py` is next opened
structurally* (bundle with immutability), not as an isolated re-churn.

### ctypes-1 — Union endianness reversal · ✅ DECIDED · ⚠ changes the patch
⚠ **This changes the patch.** ctypes-1 as written **passes Union bytes through unchanged** (the
historical behavior, now merely documented). This recommendation is to instead **raise
`NotImplementedError`** when a byte-order swap is actually required (`endianness != sys.byteorder`)
for a **multi-byte** union — plus a `sizeof > 1` gate (single-byte unions need no reversal and pass
through), which is a refinement **this record adds** on top of the finding's raise/passthrough
options. **Repo evidence (checked):** the only ctypes union in the codebase is `TestUnion` in
`test/ctypes_test.py`, and it is **never serialized cross-endian** — the endianness-reversal test
exercises only `c_int` and `TestStructure`. So adopting the raise breaks **no existing test or code
path**; the only exposure is out-of-repo scripts, and for those the current passthrough is *already*
producing silently-wrong bytes on multi-byte unions, so raising surfaces a latent bug rather than
breaking correct behavior. It is also reversible (relax to passthrough later if it ever fires).
**Status: DECIDED — raise** (repo shows zero cross-endian union usage, so it's low-risk).
A union's active member is unknowable, so neither passthrough nor whole-reversal is
correct — refusing is the honest choice, and it's consistent with the bitfield `NotImplementedError`
this same patch adds. Passthrough is the last silent-wrong path in the module; close it.
*(The rest of ctypes-1/2/3 — the pure byte-level reversal, the nested-bitfield guard, the message
spacing — carry no open question.)*

### aggregate-utils-1 — `is_instance_of_union` policies · ▶ RECOMMENDED
**Confirm both.** (A) Empty iterable → `True` is vacuous truth (`all([])==True`), consistent with
`"" in "abc"`. (B) One-shot iterators accepted unchecked is the only non-destructive option
(consuming corrupts the caller; rejecting breaks working generator inputs). **Document** two
consequences: the list-vs-iterator asymmetry (a list of bad elements returns `False`; an iterator of
the same returns `True` then fails downstream), and that containment over a large plain list is now
O(n) (no in-package hot path hits it, but user code with big-list `in` will feel it).

### aggregate-utils-4 — Oracle `is_array` sync · ▶ RECOMMENDED
**Full sync**, not the minimal one-liner. The minimal `retval = arr_entry_list` fixes only the
dataclass case and leaves scalar `is_array` diverged (oracle raises, dispatcher returns a list) —
i.e. it disturbs the frozen oracle without achieving parity, which defeats the sync procedure.
The full sync makes oracle == dispatcher for both cases; non-array paths are byte-identical (146
plan_fastpath differentials green). **Land with the extended `test_from_bytes_is_array_returns_list`**
asserting both the dataclass and scalar cases through the oracle.

### plans-1 — Wrong-length `unpack_tuple` · ▶ RECOMMENDED
**Uniform `ValueError`** on both tiers (not `struct.error`). Both tiers must raise the *same* type to
fix the bug; `ValueError` is the semantically correct one for a wrong-length buffer, matches
`Struct.parse`/`validate_tuple`, and avoids leaking `struct.error` out of the non-struct shiftmask
tier. **plans-2 is the independent dual** — same `struct.error → ValueError` choice on wrong arity; apply
plans-1 then plans-2 (file order), both choosing `ValueError` (they don't depend on each other). The
`iter_tuples` over-count raise is a good honest-failure improvement, but note it only closes the
**shiftmask** half — the struct tier's silent truncation is owned by bugs.md #26; coordinate so #26's
policy supersedes this incidental raise.

### pytypes-1 — Dead `ConversionInfo` byte helpers · ▶ OPTIONAL (defer to the patch)
**No strong preference — a coin flip.** These three helper methods have been broken since inception
(they crash on every call — a `@classmethod`/instance-data mistake) with zero callers. The patch
**repairs** them (drops `@classmethod`, dispatches through `self`); deletion is equally safe. Either
is fine — repair keeps a symmetric codec surface, delete shrinks it. **Default to the patch (repair)
unless you specifically want a smaller surface**, in which case delete (and drop lows-code-10, which
layers an `endianness=` parameter onto the repaired methods). Originally I leaned delete; downgraded
to "no push."

### pytypes-3 — char codec charset + bits-path enforcement · ✅ DECIDED · ⚠ changes the patch
**Part 1 — latin-1, fixed-width.** ⚠ pytypes-3 as written proposes **UTF-8** (encode-side only); this
maintainer decision **changes it to `latin-1` on *both* sides** — the decode-side edit
(`.decode('latin-1')`) is **beyond the proposed patch** — keeping `num_bits=8` and the strict
one-char gate. Do **not**
uncomment the variable-width `_string_conversion_info`. Alternative *single-byte* codepages stay
configurable via `ConversionConfig.set_conversion_info(...)`; **UTF-8 / multi-byte / variable-width
text goes through the `String` bittypes** (`String.of(encoding='utf-8', …)`), not the fixed-width
registry conversion.
**Part 2 — option (c).** Extend the one-byte enforcement to the bits path as a **declared-width
check**, not a blanket `len!=1` rejection: per-char when there's no declared width (bare
`to_bits_aggregate('ABC')` still works), loud `ValueError` when a declared-width field overflows.
**Re-verification:** this reshapes pytypes-3 (latin-1 now touches the *decode* side; the original
pass was UTF-8-encode-only) and couples it to lows-code-7 — re-verify the three changes together
(latin-1 encode+decode, bits-path width check, lows-code-7's width check).

### endianness-1 — endianness vocabulary · ▶ RECOMMENDED
**Strict-exact `{'big','little'}`** (the proposal). It's the only option that keeps the *whole*
surface — every bytemaker intake **and** the stdlib delegate (`int.from_bytes` via `BitVector.to_int`,
`struct` compile) — speaking one identical vocabulary. Partial normalization re-creates the
split-brain bug (`UInt8('BIG')` legal, `to_int('BIG')` not); full normalization means wrapping the
stdlib to fight its own convention. If you ever want case-insensitivity it must be all-or-nothing,
never partial. Apply endianness-1 (the helper) before endianness-2.

### buffer-2 — `Buffer.value` plane · ✅ DECIDED
**Return an independent, resizable `BitVector` snapshot** (`BitVector(self.bits)`), not the live
handle and not a width-locked `FixedLengthBitVector` copy. This restores the library-wide two-plane
contract (`.value` = safe read, `.bits` = live handle); the width-lock protects the *buffer*, which a
detached copy no longer is, so locking the copy would restrict the caller for no benefit. Matches
`py_type` (plain `BitVector`) and the documented "resizable snapshot" idiom.
**Apply with buffer-1** (its docstring describes these snapshot semantics).

### docs-misc-1 — `__repr__` · ▶ RECOMMENDED
**Fix the code** to be genuinely eval-able (honor Python's `__repr__` convention; `str()` already
gives the friendly display), using **bits-form** (`ClassName(bits='…', endianness='…')`). Bits-form is
lossless (survives NaN payloads, signed negative zero, non-canonical patterns) and universal across
every family, whereas value-form is silently lossy on exactly those and needs per-family thought. The
`SInt.__repr__` companion (appending `int_format=`) is load-bearing — without it signed reprs
round-trip to the wrong value. Anonymous `specialize()` classes need a manual name binding to eval;
the docstring keeps that honest. (String/Buffer *display* value-form is a separate `str()` concern.)

### docs-misc-5 — SInt setter "reject out-of-range" claim · ▶ RECOMMENDED
**Confirm the deferral: no edit.** narrowing-3 (apply-now, uncontested) makes the documented claim
true at all widths by giving SInt8/16/32/64 a per-instance `skip_struct_packing` gate. **Hard
dependency:** docs-misc-5's "no edit" is only correct if narrowing-3 is in the same release — land
them together. Apply the contingent one-comment fallback *only* if narrowing-3 is dropped.

### lows-ux-3 — pytypes dead loop · ▶ RECOMMENDED
**Delete** the dead `bytes`/`bytearray`/`memoryview` conversion loop (registration is commented out →
never wired up). Deleting is behavior-neutral; uncommenting would silently change the frozen legacy
surface, reintroduce the variable-width incoherence, and duplicate what `Buffer` does. If you ever
need byte fields, use a `Buffer`, not this loop. *(The other three lows-ux-3 items — string encoding
mint-check, `min_bit_length` else, `pack_tuple` field-naming — apply regardless.)*

### lows-ux-5 — `to_bits`/`from_bits` deprecation · ✅ DECIDED (confirms the patch)
**Warn-first, as the patch proposes.** Add a runtime `DeprecationWarning` to `to_bits()`/`from_bits()`
now, redirect the 2 oracle callers, migrate the 11 test sites, and keep one `deprecated_call()` test
each; the actual removal stays a later, separate step. An earlier recommendation was to delete them
outright, but the cautious two-step is the safer call given the methods may appear in your own scripts
outside this repo — a runtime warning nudges those instead of breaking them at next run.
*(The rest of lows-ux-5 — `conversions/__init__` re-exports, `array()`/`field()` docstrings,
`fields.pyi` wide-width ladder, Float bitwise docstring — are additive wins that land either way.)*

### lows-code-4 — `from_int` overflow check · ▶ RECOMMENDED
**Strict signed check** (size the overflow guard with `twos_complement_bit_length`), **no `signed=`
parameter.** `from_int` is already signed by contract (`size=None` default + `to_int(signed=True)`);
the fix just aligns the guard with that, closing silent round-trip corruption (`from_int(127,7)` →
`-1`). Unsigned tight-width packing already lives in `UInt`/`Int.to_bitstring`, so nothing is lost,
and widening a `# TODO remove` method isn't worth it. **Three-backend sync** (all change identically);
**merge the `ValueError` wording with lows-ux-2**.

### lows-code-7 — Legacy aggregate string policy · ✅ DECIDED
**Option (c)** — carve-out **plus** a declared-width check at serialize time. Per-char for bare
strings (`to_bytes_aggregate('hi')` keeps working), loud `ValueError` when a declared-width `str`
field overflows (preserves pytypes-3's `Rec('ABC', 5)` fix). This is the aggregate-side of the same
rule chosen in pytypes-3 Part 2. Option (a) breaks bare-string use; option (b) silently undoes
pytypes-3's record-overflow fix. **Must land with or before pytypes-3** (severity upgraded low→medium
because pytypes-3 turns the divergence into a hard break). Also drop the commented scaffolding. One
byte-changing input to eyeball: `to_bytes_aggregate('hi', endianness='little')` → `b'hi'` (the
intended unification).

---

## Consolidated apply-order & coupling graph

> **Companion solutions (no open decision — listed only for ordering):** narrowing-1, narrowing-3,
> string-1, string-3, string-5, string-6, ctypes-2, ctypes-3, buffer-1, endianness-2, and float-1's
> base patch. These carry no maintainer decision but are prerequisites/companions referenced below.

**Hard "land together / before" constraints:**
- **narrowing-1 → narrowing-2** (helper adds a stack frame the fixed `stacklevel=3` can't absorb).
- **narrowing-1 → float-1** (float-1's new overflow warning reuses narrowing-1's `_warn_narrowing` emitter and reads `NarrowingConfig.warn` — narrowing lands first).
- **narrowing-4 with narrowing-3** (land together, either order — narrowing-4 validates the `int_format` narrowing-3's per-instance gate reads; both verified together).
- **narrowing-3 ⇔ docs-misc-5** (docs-misc-5 is "no edit" *only* if narrowing-3 ships; else use its fallback comment).
- **pytypes-3 ⇔ lows-code-7** — must land together, **lows-code-7 with or before pytypes-3** (else pytypes-3 turns the latent str divergence into a hard break).
- **buffer-2 → buffer-1** (buffer-1's docstring assumes buffer-2's snapshot semantics).
- **string-1 / string-2 first**; then **string-3, string-4, string-5 in any order** (disjoint sites); **string-4 before or with string-6**; **string-6 last**.
- **endianness-1 → endianness-2** (endianness-1 introduces the shared helper). endianness-2's one-line intake inserts are order-independent w.r.t. the ctypes-1/2/3 rewrite and the pytypes body edits — but merge the shared import lines if both land.
- **ctypes-1 first**, ctypes-2 lives inside it, ctypes-3 touches only messages.
- **float-1 → float-3** (adjacent regions; float-1 leaves the setter untouched). **lows-code-9** renames `to_binstring→to_bitstring` on top of float-1's after-text.
- **plans-1 + plans-2** are **independent duals** (not "governs"); apply plans-1 then plans-2 (file order); both must choose the uniform `ValueError`.
- **aggregate-utils-1 → aggregate-utils-4** (au-1 makes `is_instance_of_union` honest; au-3/au-4 paths depend on that — apply au-1 first).
- **pytypes-1 → lows-code-10** (only if pytypes-1 is *repaired*, not deleted).
- **lows-code-4** merges its `ValueError` wording with **lows-ux-2** (both touch the same `from_int`/index lines).
- **lows-ux-5 + float-5** — lows-ux-5's Float bitwise-docstring paragraph folds into float-5's rewrite of the same class docstring.
- **structs-2** ships with its pinned-test rewrite. **docs-misc-1**'s `SInt.__repr__` anchor sits inside narrowing-2's rewritten setter (disjoint — either order).

**Three-backend / multi-file sync obligations (change identical copies together):**
- **bitvector-behavior-4** — native + speedup; keep the two "bytearray handles resizing" comments in sync.
- **bitvector-behavior-7** — all three backends **plus** the differential test's `to_bytes` comparison.
- **bitvector-behavior-8** — all three backends **plus** `test/bitvector_implementations_test.py` **plus** the `BoundBits.pop` comment in structs.py:1180-1186.
- **lows-code-4** — all three backends change identically (keeps the differential fuzz green).
- **narrowing-2** — rewrites int.py's import block (drops `NarrowingConfig`/`_warn_narrowing`, adds `_narrow_int`); coordinate with any other int.py import edit (e.g. float-4's dunders near `__invert__`).

**Re-verification triggers (empirical pass must be re-run):**
- **pytypes-3 + lows-code-7** — reshaped (latin-1 now touches the *decode* side + the option-(c) width checks on both paths); the original pass was UTF-8-encode-only.
- **float-1 (overflow behavior)** — the struct-packed `OverflowError`→±inf edit **and** the new float-overflow `NarrowingWarning` are not in any verified patch; implement and test both (a unit test for the ±inf store on `Float16/32/64`, and a warn-mode test mirroring the integer-narrowing warning tests).

**Contingent items (recorded — apply only if the trigger flips):**
- docs-misc-5 fallback comment — only if narrowing-3 is dropped.
- lows-ux-5 delete-outright (instead of warn-first) — only if you're confident no out-of-repo script calls `to_bits`/`from_bits`.
- pytypes-1 delete + drop lows-code-10 — only if you want to shrink the surface (default is the patch's repair).
- ctypes-1 keep passthrough (instead of raise) — only if you actually serialize union-bearing ctypes structs cross-endian (repo shows none).
- float-3 — skip entirely if scalar-immutability is committed.

---

## Still needs your explicit sign-off

The ✅ items are settled — including the review-round decisions: float-1's overflow-warning refinement
(store ±inf, C behavior, **but reportable** under warn-mode), narrowing-4 keep-normalize, lows-ux-5
warn-first, and **ctypes-1 raise** (repo shows zero cross-endian union usage → low-risk). Still open:
- **pytypes-1** — genuinely optional; defer to the patch (repair) unless you want a smaller surface.
- Everything else marked ▶ (bitvector-behavior confirms, endianness-1, docs-misc-1, etc.) is a
  recommendation not yet ratified — none carries an embedded condition; they just need your nod.
