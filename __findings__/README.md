# bytemaker — findings

Code-audit findings for the `bytemaker/` package across six lenses: correctness bugs, inconsistencies, sloppy code, docstrings, UX/DX, and AI-tone. Produced by an iterative multi-agent sweep benchmarked against the repo state four weeks ago.

## Status

All six lenses are now covered. The first run got through the **bug** and **inconsistency** lenses (across 11 file-units) before hitting a session limit; those findings were recovered from the run journal. A **sloppy-code** pass was then done by hand, and a second run covered **docstring**, **ux**, and **ai-tone** with an independent fairness judge on every finding (26 of 137 candidates rejected).

Verification status: **13 of the high-severity bug/inconsistency findings were independently re-verified this session** — most with a runnable repro (**✓ Reproduced**), the rest by inspection. The docstring/ux/ai-tone findings were each fairness-judged against the actual code. The remaining bug/inconsistency items are the finder's discovery pass — strong, often repro-backed leads to confirm before changing code.

## Environment note

The active BitVector backend here is `bitvector_with_bitarray_speedup.py` (bitarray is installed), so the cross-implementation divergences found on that file affect the **default runtime**, not just a fallback path.

## How this was produced

- Target: the `bytemaker/` package (23 files, ~12.4k lines), read-only.
- Each finder read its file-unit in full, primed with the 4-weeks-ago reference (`1a894a2` / v0.11.0) and the maintainer's `observations/` notes, to surface *new* issues.
- Extra weight on the ~2-week-old Struct/plans/fields code and on divergence between the three near-duplicate BitVector implementations.

## Totals

| Severity | Count |
|---|---|
| high | 17 |
| medium | 63 |
| low | 112 |
| **total** | **192** |

| Dimension | Count | Report |
|---|---|---|
| Correctness bugs | 28 | [bugs.md](bugs.md) |
| Inconsistencies | 44 | [inconsistencies.md](inconsistencies.md) |
| Sloppy code | 9 | [sloppy-code.md](sloppy-code.md) |
| Docstrings | 39 | [docstrings.md](docstrings.md) |
| UX / DX | 62 | [ux.md](ux.md) |
| AI-tone / unnatural prose | 10 | [ai-tone.md](ai-tone.md) |

## High-severity findings (re-verified where marked ✓)

- **[ai-tone]** Float class docstring copy-pasted from Int: "represents an integer" — [`bytemaker/bittypes/float.py:24`](../bytemaker/bittypes/float.py#L24)
- **[bug]** **✓** NarrowingWarning never fires for struct-packed widths (UInt/SInt 8/16/32/64) — [`bytemaker/bittypes/bittype.py:578-594`](../bytemaker/bittypes/bittype.py#L578)
- **[bug]** **✓** value getter never decodes zero/inf/NaN exponent encodings (round-trip broken) — [`bytemaker/bittypes/float.py:81-111`](../bytemaker/bittypes/float.py#L81)
- **[bug]** **✓** to_binstring(NaN) raises ValueError instead of encoding NaN — [`bytemaker/bittypes/float.py:147`](../bytemaker/bittypes/float.py#L147)
- **[bug]** **✓** to_binstring overflows the field width for large magnitudes (produces oversized bitstring) — [`bytemaker/bittypes/float.py:175-186, 200`](../bytemaker/bittypes/float.py#L175)
- **[bug]** **✓** to_binstring crashes on subnormal/underflow magnitudes ('substring not found') — [`bytemaker/bittypes/float.py:165-167, 195-197`](../bytemaker/bittypes/float.py#L165)
- **[bug]** Empty (non-None) codepoint_changes crashes every encode and decode with AttributeError — [`bytemaker/bittypes/string.py:248-264`](../bytemaker/bittypes/string.py#L248)
- **[bug]** bitarray backend rejects float bit values (1.0/0.0) in append/insert/remove/extend that both reference impls accept — [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1036, 1049, 1061, 1101`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1036)
- **[bug]** **✓** FixedLengthBitVector slice-setitem guard uses len(value) instead of bit-length, both false-blocking valid writes and false-allowing width changes — [`bytemaker/bitvector/fixed.py:79-88`](../bytemaker/bitvector/fixed.py#L79)
- **[bug]** **✓** ctype_to_bytes mutates the caller's ctypes Structure in place, silently corrupting it — [`bytemaker/conversions/ctypes_.py:63-69, 96-97`](../bytemaker/conversions/ctypes_.py#L63)
- **[bug]** BoundBits width-preserving mutators (setall/invert/sort) silently no-op instead of writing through — [`bytemaker/structs.py:1069-1073`](../bytemaker/structs.py#L1069)
- **[bug]** **✓** is_instance_of_union crashes on empty iterables and mis-matches non-empty ones — [`bytemaker/utils.py:133-135`](../bytemaker/utils.py#L133)
- **[inconsistency]** Float.specialize lists bases in reverse of Int.specialize and the concrete Float subclasses, so the struct packing path never wins — [`bytemaker/bittypes/float.py:243-248`](../bytemaker/bittypes/float.py#L243)
- **[inconsistency]** **✓** Zero/inf/special values round-trip correctly on struct-packed Floats but are decoded wrong on non-struct Float subclasses — [`bytemaker/bittypes/float.py:81-111`](../bytemaker/bittypes/float.py#L81)
- **[inconsistency]** `int_format` constructor arg is silently ignored on SInt8/16/32/64 (skip_struct_packing keys off the global, not the instance) — [`bytemaker/bittypes/int.py:698-700, 735-737, 744-746, 753-755 (vs specialize 648-650)`](../bytemaker/bittypes/int.py#L698)
- **[inconsistency]** Empty value on an extended slice silently deletes bits (packed) but raises ValueError (bitarray backend) — [`bytemaker/bitvector/bitvector_speedup.py:1057-1070`](../bytemaker/bitvector/bitvector_speedup.py#L1057)
- **[inconsistency]** __eq__ equates BitVector to a plain bitarray only on the default (bitarray) backend — [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:633-638`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L633)

_The docstring and ux lenses skew low-severity (polish); see their files for the full lists. The single new high — the `Float` class docstring reading "represents an integer" — was caught independently by both the ai-tone and inconsistency lenses._

## Files

- [bugs.md](bugs.md) — correctness bugs
- [inconsistencies.md](inconsistencies.md) — API / cross-impl / doc-vs-code inconsistencies
- [sloppy-code.md](sloppy-code.md) — dead code, debug scaffolding, stale TODOs, stray files
- [docstrings.md](docstrings.md) — sloppy/inaccurate docstrings and style drift
- [ux.md](ux.md) — user/developer-experience problems
- [ai-tone.md](ai-tone.md) — AI-generated / unnatural prose
- [_raw-findings.json](_raw-findings.json) — machine-readable dump of all passes
