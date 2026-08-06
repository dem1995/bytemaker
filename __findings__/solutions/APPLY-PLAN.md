# bytemaker — apply plan

A staged, test-green sequence for landing the [proposed solutions](README.md) under the rulings in
[DECISIONS.md](DECISIONS.md). This is the *"in what order"* companion to DECISIONS.md's *"what/why."*

> **This plan encodes the [DECISIONS.md](DECISIONS.md) rulings, which in several places deliberately
> *override* the proposed patches.** Where a step is marked ⚠, the source solution's code does
> something *different* on purpose — e.g. ctypes-1's patch passes Union bytes through but the ruling
> says raise; pytypes-3's patch encodes UTF-8 but the ruling says latin-1; float-1's patch leaves the
> struct-packed floats untouched but the "Yes" ruling says catch the overflow. Those are intentional,
> not mistakes; the source patch will *look* like it contradicts the step. The plan also
> **presupposes the ▶ "confirm-the-patch" recommendations in DECISIONS.md are accepted** — ratify
> those before applying.

## How to use this

- **Commit liberally — one commit per solution** (or per logical sub-change), so every change is
  findable later via `git log` / `git blame` / `git bisect`. Put the solution id first in the message,
  e.g. `narrowing-1: attribute NarrowingWarning to the first non-bytemaker frame`. **Do not squash a
  whole stage into one commit.** Give the ⚠ modify-the-patch and 🔨 net-new changes their *own*
  clearly-labelled commits (e.g. `float-1 [DEVIATION]: struct-packed overflow -> ±inf + warning`) so
  the departures from the proposed patches are easy to locate afterward.
- **Each stage is a test checkpoint.** Run the full suite (854 baseline) at the end of each stage;
  never carry a red suite forward. Tests gate at stage boundaries; commits stay per-solution.
- **Subsystems are mostly file-disjoint**, so the stage *order* is flexible except for the handful of
  **cross-stage rules** listed below. Within a stage, follow the stated order.
- **Per-solution sync details live in each solution's own "Risks / sync obligations."** The stage
  list flags only cross-cutting points (↔ oracle, "all three backends"); consult the source solution
  for the specific test files, multi-site edits, and fuzz-harness updates it names.
- **Markers:** ⚠ = the ruling *modifies* the proposed patch (see DECISIONS.md); 🔨 = *net-new* code
  not in any verified patch (needs writing + testing); ↔ = *affects the frozen-oracle path* — either
  edits `_legacy_aggregate.py` **or** edits a function it re-exports — so re-run the parity/differential
  tests in that same commit (an ↔ step does not always edit the oracle file itself).

## Cross-stage rules (the only hard inter-subsystem constraints)

1. **narrowing before float** — float-1's overflow warning reuses narrowing-1's `_warn_narrowing`
   emitter and `NarrowingConfig`. Land Stage 1 before Stage 2.
2. **pytypes-3 + lows-code-7 in the same stage** — pytypes-3 turns the latent string divergence into a
   hard break; lows-code-7's carve-out must be present with (or before) it. (Stage 10.)
3. **narrowing-3 present when docs-misc-5 lands** — docs-misc-5 is a *no-op* only because narrowing-3
   makes its documented claim true. (Stage 1 before Stage 12.)
4. **bitvector-behavior-8 before the pop-sentinel low items** — lows-ux pattern-6 edits the same
   `pop()` prologue bb-8 rewrites. (Stage 3 before Stage 13.)
5. **lows-code-4 with lows-ux-2**, and **lows-ux-5 with float-5** — same lines / same docstring.
6. **buffer-2 before buffer-1** — buffer-1's docstring assumes buffer-2's snapshot semantics.

7. **Stage 3 before Stage 3b** — bitvector-polish deletes ~132 lines and shifts line numbers;
   bitvector-behavior's verified anchors must land first.
8. **lows-docs (Stage 12b) after all medium/high stages** — its live fixes sit in regions those
   solutions shift, and its moot ledger assumes they landed.

Everything else can be reordered. A safe linear order is Stages 1 → 14 as written (including 3b/12b).
The plan covers all 16 solution files: 14 numbered stages plus 3b (bitvector-polish) and 12b (lows-docs).

---

## Stage 1 — Narrowing (foundational: provides the warning + `_narrow_int` machinery)

`bittype.py`, `int.py`, `aggregate_types.py`.

1. **narrowing-1** — dynamic `stacklevel` walk in `_warn_narrowing` (introduces the emitter others reuse).
2. **narrowing-2** — route all integer stores through the shared `_narrow_int`; legacy fast-path reroutes in warn mode. ↔
3. **narrowing-3** — per-instance `skip_struct_packing` gate via `_StructPackedSInt`.
4. **narrowing-4** — validate `int_format` at construction. **Keep the patch as written** (normalize-and-accept the `'sign_magnitude'` alias — *no purge*, per the ruling). Lands with narrowing-3 in this stage (either order — both verified together).
5. **narrowing-5** — re-export `NarrowingConfig`/`NarrowingWarning` from `bytemaker.bittypes`.
6. **narrowing-6** — document the C-promotion / store-narrowing contract.

## Stage 2 — Float

`float.py`, `int.py`.

1. **float-1** — rewrite the IEEE-754 codec (pure-Python path). ⚠🔨 **Two edits beyond the base patch:**
   (a) add the same overflow-to-±inf to `StructPackedBitType.value`'s float path (catch `struct`'s
   `OverflowError`, store ±inf) so `Float16/32/64` join the uniform contract; (b) make float
   overflow-to-inf emit a `NarrowingWarning` under `NarrowingConfig.warn`, reusing narrowing-1's
   emitter. Both need writing + a warn-mode test mirroring the integer-narrowing tests.
2. **float-3** — coerce the `Float.value` setter via `float()` (accept-strings; confirms the patch).
3. **float-2** — swap `Float.specialize`'s base order so the struct path wins the MRO.
4. **float-5** — fix the Int copy-paste leftovers in the Float docstring. *(Fold in lows-ux-5's Float
   bitwise-docstring paragraph and lows-code-9's `to_binstring→to_bitstring` rename here.)*
5. **float-4** — add promoted unary `__neg__`/`__pos__`/`__abs__` to Int (int.py; disjoint from narrowing-2's import block — merge imports if needed).

## Stage 3 — BitVector behavioral divergences

Three backends + `fixed.py`.

Order: **1** (fixed.py `__setitem__` length guard) → **3** (`_coerce_bit` in bitarray backend — also
introduces the `_coerce_bit` helper that lows-code-5 reuses) → **6** (`__eq__`/`__ne__` restrict) →
**7** (`to_bytes` right-align — sync all three backends **+ the differential test's `to_bytes`
comparison**) → **4** (extended-slice raise) → **2** (bytearray/memoryview substrings) → **5**
(runtime `BitsConstructible` union) → **8** (`pop()` list-parity — sync all three backends **+
`test/bitvector_implementations_test.py`** **+ the `BoundBits.pop` comment in structs.py:1180-1186**).

## Stage 3b — BitVector polish (non-behavioral cleanup)

`bitvector-polish-1..5` (three backends). **Must follow Stage 3** — the source says so explicitly:
this group deletes ~132 lines (stale commented blocks, the `__main__` scratch block), which shifts
every subsequent line number; landing bitvector-behavior first keeps its verified line references
meaningful. Contents: oct()/bin() docstring prefix fixes (bitarray backend), the `__Bits__` docstring
contradiction, stale commented-block deletions, and **polish-5** (the `to_chararray` assert →
explicit `ValueError`, all three backends — the group's one apply-now item). Stages 13/14's
moot ledgers cite polish-1 and polish-3, so this must land before them.

## Stage 4 — Structs

`structs.py`.

1. **structs-1** — BoundBits delegated mutators write through the validating store.
2. **structs-2** — detach-copy Struct-valued defaults. ⚠ **Extend the patch with the `_MISSING`
   sentinel** (the patch triggers on object identity; the sentinel closes the "pass the exact default
   object" corner). **Ships with the `test_array_of_struct_element_aliases_like_nested_struct`
   rewrite** in the same commit.
3. **structs-3** — Codec protocol docstring truth (BitType Codec shims deferred).

## Stage 5 — String bittypes

`string.py`.

Order: **string-1** (empty mapping → no-op) → **string-2** (reject empty codepoint entries) → then
**string-3 / string-4 / string-5 in any order** (of() mint-time checks; string-4 widens `TableString`
to accept `'ignore'`) → **string-6** last (String class docstring — documents string-4's vocabulary).
*(lows-ux-3's encoding mint-check slots next to string-4's `errors=` validation, sharing `import codecs`.)*

## Stage 6 — ctypes conversions

`ctypes_.py`. One coherent single-file edit.

1. **ctypes-1** — pure byte-level endianness reversal. ⚠🔨 **Change the Union branch to raise
   `NotImplementedError`** for multi-byte unions needing a swap (gate on `sizeof > 1`), instead of the
   patch's passthrough (per the ruling; repo has zero cross-endian union usage) — this raise branch is
   net-new. ↔ (edits `ctypes_.py`, whose functions the oracle re-exports — re-test parity; no
   `_legacy_aggregate.py` edit).
2. **ctypes-2** — bitfield guard (lives *inside* ctypes-1's new Structure branch).
3. **ctypes-3** — fix run-together words in the two TypeError messages.

## Stage 7 — Legacy aggregate & utils

`utils.py`, `_legacy_aggregate.py`. ↔ (oracle file — parity tests each commit).

Order: **aggregate-utils-1** first (real `is_instance_of_union` element checks — foundational; confirm
the empty→True + iterators-unchecked policies), then **au-2 / au-3 / au-4 / au-5 in any order**. au-1
edits `utils.py`, the *single shared definition* used by both the oracle and the dispatcher (no
separate oracle pairing, but it affects the oracle path → re-test parity); au-2/au-3/au-4 edit
`_legacy_aggregate.py` directly (↔). au-4 = **full** is_array sync, with the extended parity test.
*(lows-code-6 layers range validation onto au-5's `twos_complement` — apply as the combined final form.)*

## Stage 8 — Plans

`plans.py`.

1. **plans-1** — validate buffer length at the top of `unpack_tuple`; **uniform `ValueError`** both tiers.
2. **plans-2** — validate value count at the top of `pack_tuple`; same uniform `ValueError` (independent dual — file order).

## Stage 9 — Endianness

`utils.py` + intake sites.

1. **endianness-1** — add the `validate_endianness` helper (**strict-exact `{'big','little'}`**) and guard the bittypes intakes.
2. **endianness-2** — apply it at every remaining conversion/aggregate/oracle/schema intake. ↔

## Stage 10 — String-policy (pytypes-3 + lows-code-7, coupled)

`pytypes.py`, `_legacy_aggregate.py`. **Land together.** ⚠🔨↔

1. **pytypes-3** — strict one-byte char codec. ⚠ **Use `latin-1` on *both* encode and decode**
   (the decode-side edit is beyond the proposed UTF-8 patch) + **option (c)** on the bits path:
   encode a string per-character, but **raise `ValueError` when a declared-width `str` field's encoding
   overflows its width** (from lows-code-7 / DECISIONS.md — *not* a blanket `len!=1` reject, which
   would break bare `to_bits_aggregate('hi')`).
2. **lows-code-7** — give `to_bytes_aggregate` the same multi-char carve-out **plus** the option-(c)
   declared-width check; drop the commented scaffolding.
3. **Re-verify the pair together** (latin-1 encode+decode + both width checks) — the original pass was
   UTF-8-encode-only.
4. Also in `pytypes.py`: **pytypes-2** (bits_to_pytype docstring) anytime; **pytypes-1** *optional* —
   defer to the patch (repair) unless shrinking the surface; if repaired, add **lows-code-10**
   (`endianness=` on the ConversionInfo methods).

## Stage 11 — Buffer

`buffer.py`.

1. **buffer-2** — `Buffer.value` returns an independent **resizable `BitVector` snapshot**.
2. **buffer-1** — rewrite the Buffer docstring (assumes buffer-2's semantics).

## Stage 12 — Docs & API surface (misc)

Order: **docs-misc-2 / docs-misc-3 / docs-misc-4** (pure docs/stub — safe anytime) → **docs-misc-1**
(eval-able `__repr__`, **bits-form**; SInt override appends `int_format`) → **docs-misc-5** (**no edit**
— confirmed by narrowing-3 from Stage 1; apply the fallback comment *only* if narrowing-3 were dropped).

## Stage 12b — Low-severity docstring & AI-tone patterns (lows-docs)

`lows-docs-1..6` — the 39-finding docstring/tone sweep. **Deliberately late:** its own strategy says
*"apply AFTER the medium/high solutions land, since several live fixes sit in regions those solutions
shift"* (narrowing-6 rewrites the Int class docstring; bitvector-behavior-5 rewrites the
`BitsConstructible` docstring head whose tail lows-docs-5 trims; buffer-1's accepted text reuses the
"door" phrase lows-docs-5 removes — **one wording call needed** there). Note lows-docs-3 includes one
small **code** fix (the bitarray backend's `__contains__` implicit-None fall-through), not just text.
Its moot ledger marks 9 refs already fixed by earlier stages — tick those off rather than re-fixing.

## Stage 13 — Low-severity UX patterns

> **These low-severity patterns are cross-cutting** — several items belong *with* an earlier stage,
> not saved for last: lows-ux-3's encoding mint-check lands with **string-4** (Stage 5); its
> `min_bit_length` trailing-else (int.py) is standalone; its `pack_tuple` error translation lands after
> **plans-2** (Stage 8); pattern-6's pop `_MISSING` sentinel goes on top of **bb-8** (Stage 3). What
> genuinely remains here is standalone
> text/UX polish. Patterns 1–5 are independent; pattern-6 must follow bb-8.

Notable: **lows-ux-5** = **warn-first** deprecation (add the `DeprecationWarning`, migrate the 2 oracle
callers + 11 test sites, keep a `deprecated_call()` test each; removal is later). **lows-ux-2** reworks
BitVector error text across three backends **and edits the frozen oracle's `YType` message text** (↔ —
message-only, but re-run parity). ↔

## Stage 14 — Low-severity code nits

`lows-code-1..15`. Mostly independent one-liners. Coordinate: **lows-code-4** (from_int strict signed
check, three backends) merges its `ValueError` wording with **lows-ux-2**; **lows-code-5** reuses the
`_coerce_bit` from Stage 3; **lows-code-12** deletes the commented `__hash__`/`int_format` stubs
(BitType stays intentionally unhashable). lows-code-1 is a bookkeeping ledger (no edits).

> **Distributed items (applied with their coordinating stage, not here):** lows-code-6 with au-5
> (Stage 7), lows-code-9's `to_binstring→to_bitstring` rename with float-5 (Stage 2, on top of
> float-1), lows-code-7 with pytypes-3 (Stage 10), lows-code-10 with pytypes-1 (Stage 10, only if
> pytypes-1 is repaired). Everything else is standalone nits.

---

## Net-new work (not in any verified patch — build + test)

- **float-1 (a)** struct-packed `OverflowError`→±inf, and **(b)** the float-overflow `NarrowingWarning`
  under warn-mode. *(Stage 2.)*
- **structs-2** `_MISSING` sentinel in the codegen. *(Stage 4.)*
- **ctypes-1** the raise-on-multi-byte-union branch (+ `sizeof > 1` gate). *(Stage 6.)*
- **pytypes-3** the latin-1 *decode*-side edit + the bits-path option-(c) width check;
  **lows-code-7** the option-(c) width check on the bytes path. *(Stage 10.)*

## Deferred (not in this plan)

- Scalar-BitType immutability — a separate project *after* this whole plan lands (the plan builds the
  test net that de-risks it). See DECISIONS.md § S1.
- BitType Codec shims (structs-3) — bundle with the immutability rework, not standalone.
