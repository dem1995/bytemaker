# Solutions — String bittypes (bittypes/string.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

Six solutions over seven findings (the two errors= findings — codec divergence and late/silent policy failures — share one root cause and get one coordinated fix). Strategy: make the codepoint-substitution machinery internally consistent (string-1 aligns the None-vs-falsy guards; string-2 rejects the only inputs with undefined semantics at a chokepoint all assignment paths flow through), and move every declaration-shaped failure from decode-time to mint-time in of() (string-3 divisibility, string-4 errors vocabulary, string-5 pad/terminator range), following the precedent of the existing bytes_per_char check. string-4 also closes the behavioral divergence by giving TableString a real 'ignore' branch so strict/replace/ignore mean the same thing under every codec. Apply order: string-1 and string-2 first (independent of of()); then string-5, string-3, string-4 inside of() (their insertions are at disjoint sites and stack cleanly in any order, but string-4 must precede or accompany string-6 because the new String docstring documents the unified errors vocabulary); string-6 last. All six were applied together to a work-dir copy: every repro flips as described, and the repo's full test suite passes against the patched copy (854 passed) with the patched package confirmed first on sys.path. No sync obligations: _legacy_aggregate.py contains no String code (only docstring mentions), and nothing here touches the three BitVector backends. TESTING CAVEAT (from adversarial review): test/__init__.py makes pytest prepend the repo root to sys.path, so validating any of these patches requires copying the test suite beside the patched package - running the in-repo test dir silently tests the pristine tree regardless of PYTHONPATH.

_6 solutions — 2 apply-now, 6 empirically verified on a patched copy._

---

## 1. Treat an empty codepoint_changes mapping as a no-op in the substitute helpers

**Priority:** **now** · [`bytemaker/bittypes/string.py:248-264`](../../bytemaker/bittypes/string.py#L248) · **✓ verified on a patched copy**

**Problem.** Setting codepoint_changes to an empty (non-None) mapping makes the field completely unusable: every encode and every decode crashes with AttributeError: 'NoneType' object has no attribute 'sub', because the substitute helpers gate on `is not None` while the regex builders gate on truthiness and return None for an empty dict.

**Fix.** Change the guards in _substitute_forward and _substitute_reverse from identity (`is not None`) to truthiness (`if codepoint_changes:` / `if reverse_changes:`), matching the guards already used by _codepoint_change_regex and _reverse_codepoint_change_regex (lines 165/190). An empty mapping then means "no substitutions" on both sides, which is the only sensible reading. A short comment records why truthiness is load-bearing so the mismatch is not reintroduced.

**Before:**

```python
    @classmethod
    def _substitute_forward(cls, value):
        codepoint_changes = cls.codepoint_changes
        if codepoint_changes is not None:
            value = cls.perform_codepoint_substitution(
                value, codepoint_changes, cls._codepoint_change_regex
            )
        return value

    @classmethod
    def _substitute_reverse(cls, value):
        reverse_changes = cls._reverse_codepoint_changes
        if reverse_changes is not None:
            value = cls.perform_codepoint_substitution(
                value, reverse_changes, cls._reverse_codepoint_change_regex
            )
        return value
```

**After:**

```python
    @classmethod
    def _substitute_forward(cls, value):
        # Truthiness, not identity: the regex builders treat an empty
        # mapping as "no substitutions" (no regex), so this must too.
        codepoint_changes = cls.codepoint_changes
        if codepoint_changes:
            value = cls.perform_codepoint_substitution(
                value, codepoint_changes, cls._codepoint_change_regex
            )
        return value

    @classmethod
    def _substitute_reverse(cls, value):
        # Truthiness, not identity — see _substitute_forward.
        reverse_changes = cls._reverse_codepoint_changes
        if reverse_changes:
            value = cls.perform_codepoint_substitution(
                value, reverse_changes, cls._reverse_codepoint_change_regex
            )
        return value
```

**Behavior change.** S1 = String.of(nbytes=4, encoding='ascii', pad=0x00); S1._codepoint_changes = FrozenDict({})
BEFORE (pristine repo):
  encode 'ab': AttributeError: 'NoneType' object has no attribute 'sub'
  decode round-trip: AttributeError: 'NoneType' object has no attribute 'sub'
  decode from bits: AttributeError: 'NoneType' object has no attribute 'sub'
AFTER (patched copy):
  encode 'ab': OK -> b'ab\x00\x00'
  decode round-trip: OK -> 'ab'
  decode from bits (b'cd\x00\x00'): OK -> 'cd'

**Tests to add.** def test_empty_codepoint_changes_is_noop():
    S = String.of(nbytes=4, encoding='ascii', pad=0x00, name='EmptyCC')
    S._codepoint_changes = FrozenDict({})
    s = S(value='ab')
    assert bytes(s.bits) == b'ab\x00\x00'   # encode path
    assert s.value == 'ab'                    # decode path, round-trip
    assert S(bits=BitVector(b'cd\x00\x00')).value == 'cd'
Also cover the sub-byte path: a Str-style class with num_bits % 8 != 0 and _codepoint_changes = FrozenDict({}) must encode/decode without substitution.

**Risks / sync obligations / review notes.** Minimal: `if m:` differs from `if m is not None:` only for empty mappings, which previously always crashed, so no working behavior changes. Confined to bytemaker/bittypes/string.py — no copy of this logic exists in _legacy_aggregate.py (it contains no String implementation) or in the three BitVector backends. Re-run test/bittypes_test.py::test_str_codepoint_changes_longest_match and test/text_fields_test.py (full suite: 854 passed against the patched copy).

<sub>covers: `bug|bytemaker/bittypes/string.py|248-264`</sub>

---

## 2. Reject empty-string keys and values in codepoint_changes instead of compiling a match-everywhere regex

**Priority:** **now** · [`bytemaker/bittypes/string.py:103-140 (getter), 212-223 (setter); new helper inserted immediately before the codepoint_changes classproperty`](../../bytemaker/bittypes/string.py#L103) · **✓ verified on a patched copy**

**Problem.** A codepoint change with an empty value ({'A': ''}) puts '' into the reverse mapping, so the reverse regex compiles an empty alternative that matches the zero-width position between every character: _substitute_reverse('xy') silently returns 'AxAyA' and the encoded wire bytes are corrupted. An empty KEY corrupts the forward (decode) direction symmetrically.

**Fix.** Add a _check_codepoint_changes classmethod that raises ValueError (naming the class and the offending entry) if any key or value is an empty string, and call it from two places: (1) the codepoint_changes classproperty getter, right after BitVector->str normalization and before caching — this is the chokepoint every consumer (_substitute_forward/_reverse, both regex builders via cls.codepoint_changes) reads through, so it also catches class-body assignments (`_codepoint_changes = FrozenDict(...)`, the pattern the existing test uses) and direct `_codepoint_changes` attribute writes, which bypass the descriptor setter entirely (classproperty.__set__ only fires on instance assignment; there is no __init_subclass__ hook in BitType to catch class bodies earlier); (2) the descriptor setter, for immediate feedback on the instance-assignment path. Rejection is the right semantics rather than supporting deletion rules: codepoint_changes is a bidirectional mapping (applied forward on decode, reversed on encode), and {'X': ''} has no inverse — the data would be unrecoverable on round-trip. Validation runs only on cache misses (mapping unchanged => one check per mapping), and an invalid mapping is never cached, so it raises on every use.

**Before:**

```python
        codepoint_changes_field = cls._codepoint_changes
        if len(codepoint_changes_field) > 0:
            if isinstance(
                codepoint_changes_field.items().__iter__().__next__()[0], BitVector
            ):
                codepoint_changes_field = FrozenDict(
                    {
                        cls.decoding(k): cls.decoding(v)
                        for k, v in codepoint_changes_field.items()
                    }
                )

        cls._codepoint_changes_cache = (
            hash(cls._codepoint_changes),
            codepoint_changes_field,
        )  # type: ignore[reportAttributeAccessIssue]
        return cls._codepoint_changes_cache[1]

...

    @codepoint_changes.setter
    @classmethod
    def codepoint_changes(
        cls, value: HashableMapping[BitVector, BitVector] | HashableMapping[str, str]
    ):
        if len(value) > 0:
            if isinstance(value.items().__iter__().__next__()[0], BitVector):
                value = FrozenDict(
                    {cls.decoding(k): cls.decoding(v) for k, v in value.items()}
                )

        cls._codepoint_changes = value
```

**After:**

```python
    @classmethod
    def _check_codepoint_changes(cls, mapping) -> None:
        """Reject zero-length substitution keys and values.

        An empty string compiles to a zero-width regex alternative that
        matches between every pair of characters, so substitution would
        silently insert text at every position; and a deletion rule
        (``{"X": ""}``) cannot be reversed on encode. Neither direction
        has well-defined semantics, so both are rejected here.

        Args:
            mapping (HashableMapping[str, str]): The str->str codepoint
                changes mapping to validate

        Raises:
            ValueError: If any key or value is an empty string
        """
        for k, v in mapping.items():
            if not k or not v:
                raise ValueError(
                    f"{cls.__name__}: codepoint_changes entries must map"
                    f" non-empty strings to non-empty strings,"
                    f" got {k!r} -> {v!r}"
                )

    # ... in the codepoint_changes classproperty getter, after the
    # BitVector->str normalization block:

        codepoint_changes_field = cls._codepoint_changes
        if len(codepoint_changes_field) > 0:
            if isinstance(
                codepoint_changes_field.items().__iter__().__next__()[0], BitVector
            ):
                codepoint_changes_field = FrozenDict(
                    {
                        cls.decoding(k): cls.decoding(v)
                        for k, v in codepoint_changes_field.items()
                    }
                )

        # Validate here rather than only in the setter: class-body and
        # direct ``_codepoint_changes`` assignments bypass the descriptor,
        # but every consumer reads through this property.
        cls._check_codepoint_changes(codepoint_changes_field)

        cls._codepoint_changes_cache = (
            hash(cls._codepoint_changes),
            codepoint_changes_field,
        )  # type: ignore[reportAttributeAccessIssue]
        return cls._codepoint_changes_cache[1]

    # ... and in the setter:

    @codepoint_changes.setter
    @classmethod
    def codepoint_changes(
        cls, value: HashableMapping[BitVector, BitVector] | HashableMapping[str, str]
    ):
        if len(value) > 0:
            if isinstance(value.items().__iter__().__next__()[0], BitVector):
                value = FrozenDict(
                    {cls.decoding(k): cls.decoding(v) for k, v in value.items()}
                )

        cls._check_codepoint_changes(value)
        cls._codepoint_changes = value
```

**Behavior change.** S2 = String.of(nbytes=8, encoding='ascii', pad=0x00); S2._codepoint_changes = FrozenDict({'A': ''})
BEFORE (pristine repo):
  _substitute_reverse('xy'): OK -> 'AxAyA'          (silent corruption)
  encode 'xy' wire bytes: OK -> b'AxAyA\x00\x00\x00'
  decode with empty KEY ({'': 'A'}): OK -> 'AxAyA'
AFTER (patched copy):
  _substitute_reverse('xy'): ValueError: S2: codepoint_changes entries must map non-empty strings to non-empty strings, got 'A' -> ''
  encode 'xy': same ValueError
  decode with empty key: ValueError: S2b: ... got '' -> 'A'
  normal mapping ({'A': '1', 'AB': '12'}) still round-trips: decode b'AB..' -> '12', encode '12' -> b'AB\x00\x00'

**Tests to add.** def test_empty_codepoint_change_entries_rejected():
    S = String.of(nbytes=8, encoding='ascii', pad=0x00, name='CCVal')
    S._codepoint_changes = FrozenDict({'A': ''})
    with pytest.raises(ValueError, match='non-empty'):
        S(value='xy')                      # encode path
    S2 = String.of(nbytes=8, encoding='ascii', pad=0x00, name='CCVal2')
    S2._codepoint_changes = FrozenDict({'': 'A'})
    with pytest.raises(ValueError, match='non-empty'):
        S2(bits=BitVector(b'xy' + b'\x00' * 6)).value   # decode path
    inst = String.of(nbytes=4, encoding='ascii', name='CCVal3')(value='B')
    with pytest.raises(ValueError, match='non-empty'):
        inst.codepoint_changes = FrozenDict({'B': ''})   # setter path fails immediately
Plus a positive control: a valid mapping still substitutes both directions (existing test_str_codepoint_changes_longest_match covers this).

**Risks / sync obligations / review notes.** For class-body / direct-attribute assignment the error surfaces at first encode/decode rather than at assignment (no earlier hook exists without adding a metaclass); the instance-setter path fails immediately. Anyone previously relying on the corrupt every-position insertion would break — that behavior was never useful. Sequence with string-1: string-1 makes empty MAPPINGS a no-op; this fix rejects empty ENTRIES — they do not conflict. No _legacy_aggregate.py or BitVector-backend sync needed. Full suite re-run against the patched copy: 854 passed. REVIEWER NOTE: a class-level write to the public name (S.codepoint_changes = ...) shadows the classproperty descriptor and bypasses all validation (pre-existing hole, empirically confirmed); closing it would require a metaclass __setattr__ hook - out of scope here but worth knowing.

> ⚖️ **Decision needed:** Rejection assumes you never want one-way deletion rules ({'X': ''}, e.g. dropping a control char on decode). If you do want that, the right design is an explicit one-way substitution knob rather than an invertible mapping with empty values — say the word and this becomes a follow-up feature instead.

<sub>covers: `bug|bytemaker/bittypes/string.py|187-210, 257-264`</sub>

---

## 3. Require nbytes to be a whole number of bytes_per_char units in String.of()

**Priority:** soon · [`bytemaker/bittypes/string.py:423-427 (check inserted after the field-size validation)`](../../bytemaker/bittypes/string.py#L423) · **✓ verified on a patched copy**

**Problem.** of() accepts a byte width that is not a multiple of the codec's character width (e.g. nbytes=5 with utf-16-le/bytes_per_char=2, or nbytes=1 with a 2-byte table). The field packs fine but cannot decode its own output: unit-wise pad stripping leaves a partial trailing code unit (UnicodeDecodeError), and truncate=True can produce wire bytes that raise on read-back — breaking the pack/parse round-trip invariant.

**Fix.** After nbytes is fully resolved and validated as a positive int, add: if the resolved bpc (explicit bytes_per_char= > derived from a uniform table > inherited class attribute) is known, require nbytes % bpc == 0 and raise ValueError naming the class, both numbers, and why (decode works in bytes_per_char units). ValueError matches the adjacent field-size check's error type and message style. nchars= sizing already guarantees divisibility by construction; this closes the explicit nbytes= gap. Codecs with no fixed bpc (UTF-8, tables with control codes) are unaffected — for them, byte sizing is the only well-defined quantity.

**Before:**

```python
        if not isinstance(nbytes, int) or nbytes < 1:
            raise ValueError(
                f"{cls.__name__}.of(): field size must be a positive int,"
                f" got {nbytes!r}"
            )
```

**After:**

```python
        if not isinstance(nbytes, int) or nbytes < 1:
            raise ValueError(
                f"{cls.__name__}.of(): field size must be a positive int,"
                f" got {nbytes!r}"
            )
        if bpc is not None and nbytes % bpc:
            raise ValueError(
                f"{cls.__name__}.of(): nbytes={nbytes} is not a whole"
                f" number of {bpc}-byte characters; decode-side"
                f" pad/terminator handling works in bytes_per_char units,"
                f" so a partial trailing unit could never decode"
            )
```

**Behavior change.** BEFORE (pristine repo):
  String.of(nbytes=5, encoding='utf-16-le', bytes_per_char=2) mints OK; S3('hi') packs 68 00 69 00 00;
  read-back: UnicodeDecodeError: 'utf-16-le' codec can't decode byte 0x69 in position 2: truncated data
  String.of(nbytes=1, encoding={b'\x02\x03':'X', b'\x04\x05':'Y'}, truncate=True, pad=0x00) mints OK;
  S3b('XY') read-back: ValueError: S3b: no table entry decodes byte 0x00 (position 0)
AFTER (patched copy):
  both mints refused: ValueError: String.of(): nbytes=5 is not a whole number of 2-byte characters; decode-side pad/terminator handling works in bytes_per_char units, so a partial trailing unit could never decode
  (and nbytes=1 / 2-byte table analogously)
  whole-multiple widths unaffected: nbytes=6 bpc=2 round-trips 'ab'; nchars=3 bpc=2 round-trips 'abc'

**Tests to add.** def test_of_rejects_partial_character_widths():
    with pytest.raises(ValueError, match='whole number'):
        String.of(nbytes=5, encoding='utf-16-le', bytes_per_char=2)
    with pytest.raises(ValueError, match='whole number'):
        String.of(nbytes=1, encoding={b'\x02\x03': 'X'}, truncate=True)  # derived bpc=2
    U16 = String.of(nchars=3, encoding='utf-16-le', bytes_per_char=2)   # still fine
    with pytest.raises(ValueError, match='whole number'):
        U16.of(nbytes=5)   # inherited class-attr bpc also enforced
    ok = String.of(nbytes=6, encoding='utf-16-le', bytes_per_char=2, name='Ok6')
    assert ok('ab').value == 'ab'   # round-trip control

**Risks / sync obligations / review notes.** Any existing declaration with a mis-sized field now fails at mint instead of read-back — those fields were latent data bugs (grep confirms none exist in the repo/tests). Note the inherited-bpc case: SubClass.of(nbytes=...) on a class that already declares bytes_per_char is now checked too, which is intended. No oracle/backend sync. Full suite re-run: 854 passed. REVIEWER NOTE: utf-16 without an explicit bytes_per_char= still mints mis-sized fields (bpc is unknown for standard codecs by design), so this guard covers table codecs and explicit-bpc mints only.

<sub>covers: `bug|bytemaker/bittypes/string.py|399-437`</sub>

---

## 4. Unify the errors= vocabulary: TableString honors 'ignore', and of() validates the policy at mint time

**Priority:** soon · [`bytemaker/bittypes/string.py:3 (import), 451-457 (of() tail), 481-491 (TableString docstring), 544-552 (TableString.decoding)`](../../bytemaker/bittypes/string.py#L3) · **✓ verified on a patched copy**

**Problem.** The single errors= knob behaves differently per codec: StandardEncodingString forwards it to str.decode (full stdlib vocabulary), while TableString special-cases only 'replace' — so errors='ignore' silently drops bad bytes under one codec and hard-raises under the other, and errors='backslashreplace' on a table is silently treated as strict. Separately, a typo like errors='stricct' mints fine and only fails at the first BAD byte with a bare LookupError that names neither the class nor the parameter (valid bytes decode fine, so the trap can stay latent for a long time).

**Fix.** Two coordinated changes. (1) TableString.decoding gains an 'ignore' branch (advance one byte, emit nothing), so the three policies every codec can meaningfully support — strict/replace/ignore — behave identically across codecs; the TableString docstring is updated to say so. (2) of() validates errors at mint time, keyed off the resolved base: table codecs accept exactly {'strict','replace','ignore'} (anything else raises ValueError listing the supported set), standard codecs are checked against the codec-error registry via codecs.lookup_error (catching LookupError and TypeError, re-raised as a ValueError naming the class and parameter). Callable-pair codecs are exempt — a custom codec decides for itself what errors means. Validating at the base-dispatch site also covers the encoding=None inherit-from-cls path (issubclass checks). Requires adding `import codecs` to the module imports.

**Before:**

```python
from __future__ import annotations

import re

...

    ``table`` maps wire units to text: keys are ints (single bytes) or
    ``bytes`` (multi-byte sequences); values are strings (single characters
    or control codes like ``"[PK]"``). Both directions match
    **longest-first**. Decoding an unmapped byte follows ``errors``
    ("strict" raises; "replace" yields U+FFFD and advances one byte);
    encoding an unmapped character always raises (there is no meaningful
    replacement byte).
    """

...

            else:
                if cls.errors == "replace":
                    out.append("�")
                    pos += 1
                else:
                    raise ValueError(
                        f"{cls.__name__}: no table entry decodes byte"
                        f" 0x{raw[pos]:02x} (position {pos})"
                    )

...

        else:
            enc, dec = encoding
            base = String
            ns["encoding"] = classmethod(lambda c, v, _e=enc: BitVector(_e(v)))
            ns["decoding"] = classmethod(lambda c, b, _d=dec: _d(bytes(b)))
        typename = name or f"{base.__name__}x{nbytes}"
        return type(base)(typename, (base,), ns)
```

**After:**

```python
from __future__ import annotations

import codecs
import re

...

    ``table`` maps wire units to text: keys are ints (single bytes) or
    ``bytes`` (multi-byte sequences); values are strings (single characters
    or control codes like ``"[PK]"``). Both directions match
    **longest-first**. Decoding an unmapped byte follows ``errors``
    ("strict" raises; "replace" yields U+FFFD and advances one byte;
    "ignore" advances one byte and emits nothing); encoding an unmapped
    character always raises (there is no meaningful replacement byte).
    """

...

            else:
                if cls.errors == "replace":
                    out.append("�")
                    pos += 1
                elif cls.errors == "ignore":
                    pos += 1
                else:
                    raise ValueError(
                        f"{cls.__name__}: no table entry decodes byte"
                        f" 0x{raw[pos]:02x} (position {pos})"
                    )

...

        else:
            enc, dec = encoding
            base = String
            ns["encoding"] = classmethod(lambda c, v, _e=enc: BitVector(_e(v)))
            ns["decoding"] = classmethod(lambda c, b, _d=dec: _d(bytes(b)))
        # Fail a typo'd or codec-unsupported errors= at the declaration,
        # not at the first unlucky byte. Callable-pair codecs are exempt:
        # they decide for themselves what (if anything) errors means.
        if issubclass(base, TableString):
            if errors not in ("strict", "replace", "ignore"):
                raise ValueError(
                    f"{cls.__name__}.of(): table codecs support errors="
                    f" 'strict', 'replace', or 'ignore', got {errors!r}"
                )
        elif issubclass(base, StandardEncodingString):
            try:
                codecs.lookup_error(errors)
            except (LookupError, TypeError):
                raise ValueError(
                    f"{cls.__name__}.of(): errors={errors!r} is not a"
                    f" registered codec error handler (see"
                    f" codecs.lookup_error)"
                ) from None
        typename = name or f"{base.__name__}x{nbytes}"
        return type(base)(typename, (base,), ns)
```

**Behavior change.** BEFORE (pristine repo):
  TableString errors='ignore' decode of b'A\x99B\x00': ValueError: TI: no table entry decodes byte 0x99 (position 1)
  StandardEncodingString errors='ignore' decode of same: OK -> 'AB\x00'   (divergent)
  mint ascii errors='stricct': OK; decode of bad byte later: LookupError: unknown error handler name 'stricct'
  mint table errors='backslashreplace': OK (policy silently treated as strict)
AFTER (patched copy):
  TableString errors='ignore' decode of b'A\x99B\x00': OK -> 'AB'   (matches standard codec)
  TableString errors='ignore' encode round-trip 'AB': OK -> (b'AB\x00\x00', 'AB')
  mint ascii errors='stricct': ValueError: String.of(): errors='stricct' is not a registered codec error handler (see codecs.lookup_error)
  mint table errors='backslashreplace': ValueError: String.of(): table codecs support errors= 'strict', 'replace', or 'ignore', got 'backslashreplace'
  controls unaffected: table errors='replace' mints, ascii errors='backslashreplace' mints, callable-pair codec with errors='whatever' still round-trips 'hi'

**Tests to add.** def test_errors_vocabulary_unified():
    TI = String.of(nbytes=4, encoding={0x41: 'A', 0x42: 'B'}, errors='ignore', pad=0x00, name='TI')
    assert TI(bits=BitVector(b'A\x99B\x00')).value == 'AB'   # ignore skips unmapped byte
    t = TI(value='AB'); assert bytes(t.bits) == b'AB\x00\x00' and t.value == 'AB'  # round-trip
    with pytest.raises(ValueError, match='stricct'):
        String.of(nbytes=4, encoding='ascii', errors='stricct')          # typo fails at mint
    with pytest.raises(ValueError, match='table codecs support'):
        String.of(nbytes=4, encoding={0x41: 'A'}, errors='backslashreplace')
    String.of(nbytes=4, encoding='ascii', errors='backslashreplace')     # still fine
    String.of(nbytes=4, encoding={0x41: 'A'}, errors='replace')          # still fine
    Pair = String.of(nbytes=4, encoding=(lambda v: v.encode(), lambda b: b.decode()), errors='custom')  # exempt

**Risks / sync obligations / review notes.** Table fields minted with a bogus errors= now fail at mint instead of silently acting strict — intended, and no such declaration exists in repo/tests. codecs.lookup_error checks the global handler registry, not what a SPECIFIC codec supports, so a registered-but-inapplicable handler still fails at decode time — the check targets the typo class of bug. The existing errors='replace' test (test_table_string_longest_match_and_errors) still passes; full suite: 854 passed. Interaction: string-6's new String docstring describes the post-fix vocabulary ('strict/replace/ignore for tables'), so apply this before or together with string-6. No oracle/backend sync.

> ⚖️ **Decision needed:** TableString now ACCEPTS 'ignore' (matching standard codecs) rather than rejecting everything but strict/replace at mint — confirm you want table codecs to gain the policy rather than shrink the shared vocabulary to {'strict','replace'}.

<sub>covers: `inconsistency|bytemaker/bittypes/string.py|478, 545-552`, `ux|bytemaker/bittypes/string.py|359, 478, 545`</sub>

---

## 5. Validate pad and terminator as byte values (0-255 or None) at mint time in String.of()

**Priority:** soon · [`bytemaker/bittypes/string.py:399-405 (check inserted after the bytes_per_char validation)`](../../bytemaker/bittypes/string.py#L399) · **✓ verified on a patched copy**

**Problem.** of() accepts any pad/terminator value (pad=0x100, terminator=999, even pad='x') and only fails much later, during encode or decode, with a bare 'ValueError: bytes must be in range(0, 256)' that names neither the class nor the parameter — far from the declaration that is actually wrong.

**Fix.** Add a small loop over (('pad', pad), ('terminator', terminator)) right after the existing bytes_per_char check: each must be None or an int in 0..0xFF, else raise ValueError naming the class, the parameter, and the value — the same shape and placement as the neighboring bytes_per_char validation, so the error surfaces at the declaration site.

**Before:**

```python
        if bytes_per_char is not None and (
            not isinstance(bytes_per_char, int) or bytes_per_char < 1
        ):
            raise ValueError(
                f"{cls.__name__}.of(): bytes_per_char must be a positive"
                f" int, got {bytes_per_char!r}"
            )
```

**After:**

```python
        if bytes_per_char is not None and (
            not isinstance(bytes_per_char, int) or bytes_per_char < 1
        ):
            raise ValueError(
                f"{cls.__name__}.of(): bytes_per_char must be a positive"
                f" int, got {bytes_per_char!r}"
            )
        for byte_param, byte_value in (("pad", pad), ("terminator", terminator)):
            if byte_value is not None and (
                not isinstance(byte_value, int) or not 0 <= byte_value <= 0xFF
            ):
                raise ValueError(
                    f"{cls.__name__}.of(): {byte_param} must be a byte"
                    f" value 0-255 or None, got {byte_value!r}"
                )
```

**Behavior change.** BEFORE (pristine repo):
  UTF8String.of(nbytes=8, pad=0x100) mints OK; encode 'hi': ValueError: bytes must be in range(0, 256)
  UTF8String.of(nbytes=8, terminator=999) mints OK; decode: ValueError: bytes must be in range(0, 256)
  UTF8String.of(nbytes=8, pad='x') mints OK (fails later)
AFTER (patched copy):
  mint pad=0x100: ValueError: UTF8String.of(): pad must be a byte value 0-255 or None, got 256
  mint terminator=999: ValueError: UTF8String.of(): terminator must be a byte value 0-255 or None, got 999
  mint pad='x': ValueError: UTF8String.of(): pad must be a byte value 0-255 or None, got 'x'
  controls unaffected: pad=None still round-trips exact-width 'ab'; pad=0xFF still round-trips 'ab'

**Tests to add.** def test_of_validates_pad_and_terminator_bytes():
    for bad in (0x100, -1, 999, 'x', 1.5):
        with pytest.raises(ValueError, match='pad must be a byte'):
            UTF8String.of(nbytes=8, pad=bad)
    with pytest.raises(ValueError, match='terminator must be a byte'):
        UTF8String.of(nbytes=8, terminator=999)
    assert UTF8String.of(nbytes=2, pad=None, name='Ex')('ab').value == 'ab'   # None still means exact-width
    assert UTF8String.of(nbytes=4, pad=0xFF, name='Pf')('ab').value == 'ab'   # boundary value fine

**Risks / sync obligations / review notes.** Only declarations that were already broken at runtime now fail earlier. bool sneaks through (isinstance(True, int) is True; pad=True == pad=1) — harmless, matches the bytes_per_char check's leniency. Class-attribute assignment after minting (T.pad = 0x100) is still unchecked; the mint path is the only declaration API. No oracle/backend sync. Full suite: 854 passed.

<sub>covers: `ux|bytemaker/bittypes/string.py|300, 314, 356-357`</sub>

---

## 6. Add the missing String class docstring, folding the field-schema knob comment into it

**Priority:** later · [`bytemaker/bittypes/string.py:43-56`](../../bytemaker/bittypes/string.py#L43) · **✓ verified on a patched copy**

**Problem.** class String(BitType[str]) — the module's headline public abstract base — has no docstring (String.__doc__ is None), while every peer base (Int, SInt, UInt, Float, Buffer) documents itself; the padding/terminator/strip/truncate/errors contract is discoverable only via a block comment on the class attributes.

**Fix.** Add a narrative-RST class docstring (matching the style of of() and TableString in this file, not the older Args:/Returns: style) that covers: what the class is, the codec contract (encoding/decoding classmethod pair) with pointers to StandardEncodingString/TableString and of(), the wire-protocol knobs, the byte-layer cut/strip rationale, and codepoint_changes. The existing block comment's content is folded into the docstring rather than duplicated, so the comment is removed. The errors sentence states the post-string-4 vocabulary (any registered handler for standard codecs; strict/replace/ignore for tables) — apply string-4 first or together.

**Before:**

```python
class String(BitType[str]):
    py_type = str

    # Field-schema knobs (active when num_bits is a whole number of bytes;
    # sub-byte-width String classes keep the historical exact-width
    # behavior). ``pad`` is the fill byte written after content on encode
    # (None = exact width required); ``terminator`` cuts the *decode* at its
    # first occurrence; ``strip`` drops trailing pad bytes on decode;
    # ``truncate`` opts into code-unit-safe truncation on overflow instead
    # of raising; ``errors`` is the decode error policy where the codec
    # supports one. Cut and strip happen at the BYTE layer, before decoding
    # (a 0xFF pad region is not valid UTF-8; garbage after a terminator is
    # normal in ROM data).
    pad: Optional[int] = 0x00
```

**After:**

```python
class String(BitType[str]):
    """A ``BitType`` whose value is text (the C ``char name[N]`` field).

    Concrete subclasses supply the codec as a classmethod pair —
    :meth:`encoding` (``str -> BitVector``) and :meth:`decoding`
    (``BitVector -> str``): :class:`StandardEncodingString` wraps a Python
    codec name, :class:`TableString` a ``.tbl``-style byte table. Mint
    fixed-size field types with :meth:`of`, which also selects the codec.

    When ``num_bits`` is a whole number of bytes, the value round-trips
    through the field-schema knobs below; sub-byte-width String classes
    keep the historical exact-width behavior. ``pad`` is the fill byte
    written after content on encode (None = exact width required);
    ``terminator`` cuts the *decode* at its first occurrence; ``strip``
    drops trailing pad bytes on decode; ``truncate`` opts into
    code-unit-safe truncation on overflow instead of raising; ``errors``
    is the decode error policy (any registered codec error handler for
    standard encodings; "strict", "replace", or "ignore" for tables).
    Cut and strip happen at the BYTE layer, before decoding (a 0xFF pad
    region is not valid UTF-8; garbage after a terminator is normal in
    ROM data), in whole character units when ``bytes_per_char`` is known.

    Optional :attr:`codepoint_changes` substitutions are applied to the
    text after decoding and reversed before encoding.
    """

    py_type = str

    pad: Optional[int] = 0x00
```

**Behavior change.** String.__doc__ is None: True -> False (verified on the patched copy; content renders as the class's help()/Sphinx documentation). No runtime behavior change.

**Tests to add.** assert String.__doc__ and 'pad' in String.__doc__ and 'terminator' in String.__doc__ — or simply rely on doc tooling; no behavioral test needed.

**Risks / sync obligations / review notes.** None at runtime (docstring only; full suite still 854 passed with it applied). The errors sentence documents the post-string-4 vocabulary — if string-4 is NOT applied, change that parenthetical back to 'where the codec supports one'. The block comment is removed because its content moved into the docstring; the #: comment on bytes_per_char stays.

<sub>covers: `docstring|bytemaker/bittypes/string.py|43`</sub>

---
