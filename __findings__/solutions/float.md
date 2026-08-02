# Solutions — Float encode/decode (bittypes/float.py)

> Proposed fixes for the [findings](../README.md) in this area — every solution independently re-checked by an adversarial reviewer; no flags. **Nothing has been applied to the source; these are proposals for review.**

## Strategy

The five fixes form one coherent story: make the pure-Python Float codec a real IEEE-754 encoder/decoder, then remove the remaining axes along which the Float family disagrees with itself. float-1 is the core: to_binstring and the value getter are rewritten as exact inverses (signed zero, subnormals, inf, NaN, overflow-to-inf, round-to-nearest-ties-to-even), verified exhaustively against struct's half-precision codec over all 65536 bit patterns plus 200k random rounding cases. float-2 flips Float.specialize's base order so specialize-with-letter classes actually use struct, like Float32 and Int.specialize; after float-1 the two paths agree except that struct still raises OverflowError where the pure path now returns inf (flagged as the group's one open policy decision). float-3 makes the pure-Python value setter coerce via float() so ints/bools are accepted uniformly across the family; float-4 adds the missing unary -/+/abs to Int for symmetry with Float; float-5 fixes the two Int copy-paste leftovers in the Float docstring. Suggested apply order: float-1, float-3 (adjacent regions in float.py), float-2, float-5, float-4 (int.py) - though all five edits are textually disjoint and independently applicable. All were applied together to a scratch copy: the full 854-test suite passes and the patched files are flake8-clean at the repo's 88-column limit. No _legacy_aggregate.py sync is needed (the oracle has no Float usage) and no BitVector implementation is touched.

_5 solutions — 3 apply-now, 5 empirically verified on a patched copy._

---

## 1. Rewrite the Float encode/decode pair as a correct IEEE-754 codec (signed zero, subnormals, inf, NaN, overflow-to-inf, round-to-nearest-even)

**Priority:** **now** · [`bytemaker/bittypes/float.py:1-8 (imports), 81-111 (value getter), 123-211 (to_binstring)`](../../bytemaker/bittypes/float.py#L1) · **✓ verified on a patched copy**

**Problem.** The pure-Python Float codec (used by BFloat16, TF19, FP24 and any specialize() without a packing letter) is broken at every IEEE-754 edge: the value getter decodes the all-zero pattern as a tiny denormal instead of 0.0 and the inf/NaN patterns as finite numbers; to_binstring crashes on NaN (dead NaN==NaN guard), crashes on subnormal magnitudes ('substring not found'), emits an oversized bitstring on overflow (so the box raises 'Expected 16 bits, got 17'), and drops the sign of -0.0. Round-tripping data through any non-struct Float corrupts or crashes on these values, while the struct-packed siblings (Float16/32/64) handle them all correctly.

**Fix.** Rewrite the encode/decode pair as one coherent sign|exponent|mantissa codec so the getter is the exact inverse of to_binstring. Decoder: after computing the biased exponent and fractional mantissa exactly as before, branch on the two reserved exponent encodings - all-ones returns signed inf (zero mantissa) or NaN, all-zeros returns sign * mantissa * 2**(1-bias) (no implicit leading 1), which yields correctly signed zeros (-1 * 0.0 == -0.0) and subnormals; the normal formula is untouched. Encoder: replaced the string-walking normalize() pipeline with an exact math.frexp/math.ldexp construction - Python floats are IEEE-754 doubles, so scaling by powers of two is exact and the single round() call gives round-to-nearest-ties-to-even, the IEEE default (the old code truncated, so even normal values like BFloat16(0.1) were off by one ulp vs a correctly rounded conversion). Special cases mirror the decoder: NaN detected with math.isnan (sign preserved, canonical quiet-NaN mantissa), inf with math.isinf, signed zero via math.copysign; a too-large biased exponent (including one produced by mantissa-rounding carry) overflows to signed infinity like a C double->float conversion; a biased exponent <= 0 encodes a subnormal, rounding to zero (signed) on deep underflow and up to the smallest normal when the rounded mantissa overflows the field. Also adds 'import math', drops the now-unused Tuple import, and fixes the getter's wrong 'mantissa: int' annotation to float. Elision markers in the before/after snippets separate the three verbatim regions (imports / getter / to_binstring); the value setter between them is changed only by float-3.

**Before:**

```python
from __future__ import annotations

import operator
from typing import TYPE_CHECKING, NoReturn

from bytemaker.bittypes.bittype import BitType, StructPackedBitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Any, Final, Optional, Tuple, TypeVar

# --- [lines 9-80 unchanged, elided] ---

    @property
    def value(self) -> float:
        # the first bit is the sign bit
        # "0" means positive, "1" means negative
        sign: int = -1 if self.bits[0] else 1
        # The exponent is not stored as a two's-
        # complement signed integer, but is still
        # signed. This is achieved by biasing the
        # stored unsigned binary integer with
        # an eventual offset. The biased exponent
        # is then just the unsigned int
        exponent: int = sum(
            2 ** (self.num_exponent_bits - i - 1) * self.bits[1 + i]
            for i in range(self.num_exponent_bits)
        )

        # The bias is 2^(num_exponent_bits_ - 1) - 1
        # To ensure that about half of the values
        # are negative and half are positive
        unbiased_exponent: int = exponent - (2 ** (self.num_exponent_bits - 1) - 1)

        mantissa: int = sum(
            (self.bits[1 + self.num_exponent_bits + i] * 2 ** -(i + 1))
            for i in range(self.num_mantissa_bits)
        )

        magnitude: float = 2**unbiased_exponent * (1 + mantissa)

        result = sign * magnitude

        return result

# --- [value setter, lines 113-121, unchanged by this solution (see float-3)] ---

    def to_binstring(
        self: Float | float, num_exponent_bits=8, num_mantissa_bits=23
    ) -> str:
        """
        Convert a `float` (or a `Float`) to a binary string.

        Args:
            num_exponent_bits (int): The number of bits to use for the exponent.
            num_mantissa_bits (int): The number of bits to use for the mantissa.

        Returns:
            str: The unprefixed binary string representation of the `float`.
        """
        if isinstance(self, Float):
            num = self.value
        else:
            num = self

        if num == 0:
            return "0" + "0" * (num_exponent_bits + num_mantissa_bits)
        if num == float("inf"):
            return "0" + "1" * (num_exponent_bits) + "0" * num_mantissa_bits
        if num == -float("inf"):
            return "1" + "1" * (num_exponent_bits) + "0" * num_mantissa_bits
        if num == float("NaN"):
            return "0" + "1" * (num_exponent_bits + 1) + "0" * (num_mantissa_bits - 1)

        def get_sign_bit(value) -> int:
            return 0 if value >= 0 else 1

        def int_to_bin(integer) -> str:
            return bin(integer)[2:]

        def frac_to_bin(fraction, bits) -> str:
            result = []
            while fraction and len(result) < bits:
                fraction *= 2
                bit = int(fraction)
                result.append(bit)
                fraction -= bit
            return "".join(map(str, result))

        def normalize(binary_int: str, binary_frac: str) -> Tuple[str, int]:
            combined = binary_int + binary_frac
            first_one = combined.index("1")
            normalized = "1." + combined[first_one + 1 :]
            exponent = len(binary_int) - first_one - 1
            return normalized, exponent

        def get_exponent_bias(num_exponent_bits: int) -> int:
            return (2 ** (num_exponent_bits - 1)) - 1

        def int_to_binary(integer: int, bits: int) -> str:
            binary = bin(integer).replace("0b", "")
            return binary.zfill(bits)

        def assemble_bits(
            sign, biased_exponent, mantissa, num_exponent_bits, num_mantissa_bits
        ) -> str:
            return (
                f"{sign}"
                f"{int_to_binary(biased_exponent, num_exponent_bits)}"
                f"{mantissa[:num_mantissa_bits].ljust(num_mantissa_bits, '0')}"
            )

        sign_bit = get_sign_bit(num)
        abs_num = abs(num)

        integral_part = int(abs_num)
        fractional_part = abs_num - integral_part

        integral_bin = int_to_bin(integral_part)
        fractional_bin = frac_to_bin(fractional_part, num_mantissa_bits + 1)

        normalized, exponent = normalize(integral_bin, fractional_bin)

        exponent_bias = get_exponent_bias(num_exponent_bits)
        biased_exponent = exponent + exponent_bias

        mantissa_bits = normalized.split(".")[1]

        final_binary = assemble_bits(
            sign_bit,
            biased_exponent,
            mantissa_bits,
            num_exponent_bits,
            num_mantissa_bits,
        )
        return final_binary
```

**After:**

```python
from __future__ import annotations

import math
import operator
from typing import TYPE_CHECKING, NoReturn

from bytemaker.bittypes.bittype import BitType, StructPackedBitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Any, Final, Optional, TypeVar

# --- [lines 9-80 unchanged, elided] ---

    @property
    def value(self) -> float:
        # the first bit is the sign bit
        # "0" means positive, "1" means negative
        sign: int = -1 if self.bits[0] else 1
        # The exponent is not stored as a two's-
        # complement signed integer, but is still
        # signed. This is achieved by biasing the
        # stored unsigned binary integer with
        # an eventual offset. The biased exponent
        # is then just the unsigned int
        exponent: int = sum(
            2 ** (self.num_exponent_bits - i - 1) * self.bits[1 + i]
            for i in range(self.num_exponent_bits)
        )

        # The bias is 2^(num_exponent_bits_ - 1) - 1
        # To ensure that about half of the values
        # are negative and half are positive
        bias: int = 2 ** (self.num_exponent_bits - 1) - 1

        mantissa: float = sum(
            (self.bits[1 + self.num_exponent_bits + i] * 2 ** -(i + 1))
            for i in range(self.num_mantissa_bits)
        )

        # The all-ones exponent encoding is reserved for
        # infinities (zero mantissa) and NaNs (nonzero mantissa)
        if exponent == 2**self.num_exponent_bits - 1:
            if mantissa == 0:
                return sign * float("inf")
            return float("nan")

        # The all-zeros exponent encoding is reserved for signed
        # zeros and subnormals: there is no implicit leading 1,
        # and the exponent is fixed at 1 - bias
        if exponent == 0:
            return sign * mantissa * 2.0 ** (1 - bias)

        unbiased_exponent: int = exponent - bias

        magnitude: float = 2**unbiased_exponent * (1 + mantissa)

        result = sign * magnitude

        return result

# --- [value setter, lines 113-121, unchanged by this solution (see float-3)] ---

    def to_binstring(
        self: Float | float, num_exponent_bits=8, num_mantissa_bits=23
    ) -> str:
        """
        Convert a `float` (or a `Float`) to a binary string.

        Follows IEEE-754 conversion conventions: zeros keep their sign,
            rounding is to nearest (ties to even),
            magnitudes below the normal range become subnormals
            (or signed zero once even the subnormal range is exceeded),
            magnitudes above the normal range become signed infinity,
            and NaN encodes as a quiet NaN.

        Args:
            num_exponent_bits (int): The number of bits to use for the exponent.
            num_mantissa_bits (int): The number of bits to use for the mantissa.

        Returns:
            str: The unprefixed binary string representation of the `float`.
        """
        if isinstance(self, Float):
            num = self.value
        else:
            num = self

        sign_bit = "1" if math.copysign(1.0, num) < 0 else "0"
        exponent_all_ones = "1" * num_exponent_bits

        if math.isnan(num):
            # Canonical quiet NaN: all-ones exponent, most significant
            # mantissa bit set, zero payload
            return sign_bit + exponent_all_ones + "1" + "0" * (num_mantissa_bits - 1)
        if math.isinf(num):
            return sign_bit + exponent_all_ones + "0" * num_mantissa_bits
        if num == 0:
            return sign_bit + "0" * (num_exponent_bits + num_mantissa_bits)

        # The bias is 2^(num_exponent_bits - 1) - 1, and the all-ones
        # biased exponent is reserved for infinities and NaNs
        exponent_bias = (2 ** (num_exponent_bits - 1)) - 1
        max_biased_exponent = 2**num_exponent_bits - 1

        # abs(num) == fraction * 2**exponent with fraction in [0.5, 1),
        # i.e. 1.xxx... * 2**(exponent - 1). frexp/ldexp are exact
        # (Python floats are IEEE-754 doubles; scaling by powers of two
        # loses no precision), so all rounding below happens in round(),
        # which rounds to nearest with ties to even -- the IEEE default.
        fraction, exponent = math.frexp(abs(num))
        biased_exponent = exponent - 1 + exponent_bias

        if biased_exponent >= 1:
            # Normal candidate: scale so the implicit leading 1 plus the
            # mantissa form an integer, then round
            significand = round(math.ldexp(fraction, num_mantissa_bits + 1))
            if significand == 2 ** (num_mantissa_bits + 1):
                # Rounding carried into the next binade
                # (1.11...1 rounded up to 10.00...0)
                significand //= 2
                biased_exponent += 1
            if biased_exponent >= max_biased_exponent:
                # Magnitude too large for the exponent field:
                # overflow to signed infinity
                return sign_bit + exponent_all_ones + "0" * num_mantissa_bits
            mantissa_field = significand - 2**num_mantissa_bits
            return (
                sign_bit
                + format(biased_exponent, f"0{num_exponent_bits}b")
                + format(mantissa_field, f"0{num_mantissa_bits}b")
            )

        # Subnormal candidate: all-zeros exponent field, no implicit
        # leading 1, value == mantissa_field * 2**(1 - bias - num_mantissa_bits).
        # Rounding to 0 flushes to signed zero
        mantissa_field = round(
            math.ldexp(fraction, biased_exponent + num_mantissa_bits)
        )
        if mantissa_field >= 2**num_mantissa_bits:
            # Rounded up to the smallest normal number
            return (
                sign_bit
                + format(1, f"0{num_exponent_bits}b")
                + "0" * num_mantissa_bits
            )
        return (
            sign_bit
            + "0" * num_exponent_bits
            + format(mantissa_field, f"0{num_mantissa_bits}b")
        )
```

**Behavior change.** BEFORE (pristine source): BFloat16(0.0).value -> 5.877471754111438e-39; BFloat16(-0.0).bits -> '0000000000000000' (sign dropped); BFloat16(inf).value -> 3.402823669209385e+38 (finite); all-ones-exponent NaN pattern decodes to -3.429408229125083e+38; BFloat16(float('nan')) -> ValueError: cannot convert float NaN to integer; Float.to_binstring(1e40, 8, 7) -> '01000000111101011' (17 bits) and BFloat16(1e40) -> ValueError: Expected 16 bits, got 17; Float.to_binstring(1e-40, 8, 7) -> ValueError: substring not found; Float.to_binstring(-0.0, 8, 7) -> '0000000000000000'.  AFTER (patched copy): BFloat16(0.0).value -> 0.0; BFloat16(-0.0).bits -> '1000000000000000' (copysign -1.0); BFloat16(inf).value -> inf; the NaN pattern decodes to nan; BFloat16(float('nan')).bits -> '0111111111000000'; Float.to_binstring(1e40, 8, 7) -> '0111111110000000' and BFloat16(1e40).value -> inf; Float.to_binstring(1e-40, 8, 7) -> '0000000000000001' (smallest subnormal); BFloat16(1e-39).value -> 1.0101904577379033e-39 (== 11 * 2**-133, the correctly rounded bfloat16 subnormal); Float.to_binstring(-0.0, 8, 7) -> '1000000000000000'. Oracle run against struct's IEEE-754 half codec using Float.specialize(5, 10) (pure-Python path): decode of all 65536 bit patterns matches struct.unpack('>e') exactly (0 failures incl. -0.0/inf/NaN signs); encode of every representable half round-trips bit-exactly (0 failures); 199,999 random doubles encode bit-identically to struct.pack('>e') (0 failures, verifying ties-to-even rounding); decode->encode round-trip of every finite pattern is the identity (0 failures); boundary cases 65520.0 -> inf and 2**-25 tie -> 0 match IEEE; BFloat16(0.1).bits == '0011110111001101' (correctly rounded; old code produced the truncated '...11001100' pattern for such cases). Full existing suite: 854 passed.

**Tests to add.** Add to test/bittypes_test.py: (1) exhaustive parity - PyHalf = Float.specialize(5, 10): for every pattern in range(2**16), PyHalf(bits=format(p, '016b')).value == struct.unpack('>e', p.to_bytes(2, 'big'))[0] (NaN via math.isnan, zero sign via math.copysign), and for every non-NaN value the re-encode returns the same 16 bits; (2) specials on BFloat16: BFloat16(0.0).bits.to01() == '0'*16 and value == 0.0; BFloat16(-0.0).bits.to01() == '1' + '0'*15 and math.copysign(1.0, value) == -1.0; BFloat16(float('inf')).value == inf, BFloat16(float('-inf')).value == -inf; math.isnan(BFloat16(float('nan')).value) and bits == '0111111111000000'; (3) overflow: BFloat16(1e40).value == inf, BFloat16(-1e40).value == -inf; (4) subnormals: BFloat16(1e-39).value == 1.0101904577379033e-39; Float.to_binstring(1e-40, 8, 7) == '0'*15 + '1'; BFloat16(1e-50).value == 0.0 (deep underflow flushes, keeping sign for -1e-50); (5) rounding: BFloat16(0.1).bits.to01() == '0011110111001101' and Float.to_binstring(65520.0, 5, 10) == '0' + '1'*5 + '0'*10 (tie rounds to inf); (6) round-trip: for v in [0.0, -0.0, 1.5, -2.25, 1e-39, float('inf')]: TF19(TF19(v).value).bits == TF19(v).bits.

**Risks / sync obligations / review notes.** Only the pure-Python path changes; struct-packed Float16/32/64 resolve value from StructPackedBitType and are untouched (854-test suite passes). Behavior changes to be aware of: (a) storing an out-of-range magnitude into a non-struct Float now yields +/-inf instead of raising - callers relying on the old 'Expected N bits' ValueError as an overflow guard would need NarrowingConfig-style checking instead; (b) NaN payloads canonicalize on encode (sign preserved, payload dropped) - the decoder returns float('nan') for every payload anyway; (c) the quiet-NaN encoding needs num_mantissa_bits >= 1, same as the old dead guard. bytemaker/_legacy_aggregate.py has no Float usage, so no oracle sync is needed; no BitVector implementation is touched. Re-run the full test suite plus the exhaustive struct-'>e' parity script after applying. Note the import line also drops Tuple (now unused) - if another pending fix re-uses Tuple in this file, keep it.

> ⚖️ **Decision needed:** to_binstring now overflows to signed infinity (IEEE/C conversion semantics), but the struct-packed siblings still raise struct's OverflowError on an out-of-range store (e.g. Float32(1e300)). Should StructPackedBitType's float path catch OverflowError and store +/-inf so the whole Float family overflows uniformly, or is raise-on-overflow the preferred contract for the struct-packed types?

<sub>covers: `bug|bytemaker/bittypes/float.py|81-111`, `inconsistency|bytemaker/bittypes/float.py|81-111`, `bug|bytemaker/bittypes/float.py|147`, `bug|bytemaker/bittypes/float.py|175-186, 200`, `bug|bytemaker/bittypes/float.py|165-167, 195-197`, `bug|bytemaker/bittypes/float.py|141-142`</sub>

---

## 2. Swap Float.specialize's base order so the struct-packed value path wins the MRO

**Priority:** **now** · [`bytemaker/bittypes/float.py:243-248`](../../bytemaker/bittypes/float.py#L243) · **✓ verified on a patched copy**

**Problem.** Float.specialize with a packing_format_letter builds _Float(cls, StructPackedBitType[float]) - Float first - so Float's pure-Python value getter/setter wins the MRO and struct is never used, contradicting the docstring and diverging from both the hand-written Float16/32/64 (StructPackedBitType first) and Int.specialize. Float.specialize(8, 23, 'f') therefore produced different bits than Float32 for the same value.

**Fix.** List StructPackedBitType[float] first, matching SInt.specialize/UInt.specialize and the concrete Float subclasses, so the struct-based value property shadows Float's pure-Python one whenever a packing letter is supplied. A short comment records why the order matters.

**Before:**

```python
        if packing_format_letter_ is not None:

            class _Float(cls, StructPackedBitType[float]):
                num_exponent_bits = num_exponent_bits_
                num_mantissa_bits = num_mantissa_bits_
                packing_format_letter = packing_format_letter_
```

**After:**

```python
        if packing_format_letter_ is not None:
            # StructPackedBitType comes first so its struct-based value
            # getter/setter wins the MRO, matching the hand-written
            # Float16/Float32/Float64 and Int.specialize
            class _Float(StructPackedBitType[float], cls):
                num_exponent_bits = num_exponent_bits_
                num_mantissa_bits = num_mantissa_bits_
                packing_format_letter = packing_format_letter_
```

**Behavior change.** BEFORE: SpecF32 = Float.specialize(8, 23, 'f'); SpecF32(0.1).bits -> '00111101110011001100110011001000' (value property resolved from class 'Float'), while Float32(0.1).bits and struct.pack('>f', 0.1) are both '00111101110011001100110011001101'. AFTER: SpecF32(0.1).bits -> '00111101110011001100110011001101', identical to Float32 and struct, and the value property resolves from 'StructPackedBitType'. Full suite: 854 passed.

**Tests to add.** SpecF32 = Float.specialize(8, 23, 'f', 'SpecF32'): assert issubclass(SpecF32, StructPackedBitType); assert SpecF32(0.1).bits.to01() == Float32(0.1).bits.to01() == format(int.from_bytes(struct.pack('>f', 0.1), 'big'), '032b'); assert SpecF32(0.0).value == 0.0 and SpecF32(value=5).value == 5.0 (struct path accepts ints); and an MRO probe: next(k for k in SpecF32.__mro__ if 'value' in vars(k)) is StructPackedBitType.

**Risks / sync obligations / review notes.** Classes produced by specialize-with-letter change bit-level behavior (from the buggy truncating pure-Python codec to struct's correct one) - that is the point, and with float-1 applied the two paths agree except for out-of-range stores (struct raises OverflowError, pure path returns inf; see float-1's decision). Order of application relative to float-1 does not matter (disjoint regions). No repo callers of Float.specialize with a letter exist outside tests; _legacy_aggregate.py does not use Float. Re-run the full suite.

<sub>covers: `inconsistency|bytemaker/bittypes/float.py|243-248`</sub>

---

## 3. Coerce Float.value setter input with float() instead of isinstance-rejecting non-floats

**Priority:** soon · [`bytemaker/bittypes/float.py:113-121`](../../bytemaker/bittypes/float.py#L113) · **✓ verified on a patched copy**

**Problem.** The pure-Python setter demands isinstance(value, float), so BFloat16(value=1), b.value = 3, and even bools raise ValueError, while the positional-constructor path (BFloat16(1)) coerces via py_type() and succeeds and the struct-packed siblings (Float32(value=5)) accept ints via struct.pack. The same assignment succeeds or fails depending on which Float subclass and which spelling is used, and the error message ('Expected a float, got <class 'int'>') names no field and gives no hint. It also breaks the _inplace_value_op contract (bittype.py:444 does self.value = self.py_type(result), which assumes the setter accepts py_type-coercible values).

**Fix.** Replace the isinstance gate with value = float(value), mirroring the constructor's py_type() coercion, the struct-packed setter, and the Int setters (which never isinstance-gate). Genuinely non-numeric input now raises TypeError from float() itself ("float() argument must be a string or a real number, not 'object'"), which is the better design per the no-compat-pressure rule - note the exception type changes from ValueError to TypeError.

**Before:**

```python
    @value.setter
    def value(self, value):
        if not isinstance(value, float):
            raise ValueError(f"Expected a float, got {type(value)}")
        self.bits = BitVector(
            self.__class__.to_binstring(
                value, self.num_exponent_bits, self.num_mantissa_bits
            )
        )
```

**After:**

```python
    @value.setter
    def value(self, value):
        # Coerce like the constructor's py_type() path and the struct-packed
        # siblings do, so ints (and other real numbers) are accepted
        # uniformly across the Float family. Non-numeric values raise
        # TypeError from float().
        value = float(value)
        self.bits = BitVector(
            self.__class__.to_binstring(
                value, self.num_exponent_bits, self.num_mantissa_bits
            )
        )
```

**Behavior change.** BEFORE: BFloat16(value=5) -> ValueError: Expected a float, got <class 'int'>; b = BFloat16(1.0); b.value = 3 -> same ValueError; Float32(value=5) -> 5.0 (struct path, inconsistent). AFTER: BFloat16(value=5) -> 5.0; b.value = 3 -> 3.0; BFloat16(value=True) -> 1.0; Float32(value=5) -> 5.0 unchanged; BFloat16(value=object()) -> TypeError: float() argument must be a string or a real number, not 'object'. Also observed: BFloat16(value='1.5') -> 1.5, matching the existing constructor behavior (BFloat16('1.5') -> 1.5 already worked before this change). Full suite: 854 passed.

**Tests to add.** BFloat16(value=1).value == 1.0; t = TF19(1.0); t.value = 3; t.value == 3.0; FP24(value=True).value == 1.0; t += 1 (exercises _inplace_value_op through the coercing setter) keeps type TF19 with value 4.0; pytest.raises(TypeError): BFloat16(value=object()); and parity: BFloat16(value=2).bits == BFloat16(2.0).bits.

**Risks / sync obligations / review notes.** Exception type for bad input changes from ValueError to TypeError (better semantics, but any except ValueError caller would change - none exist in-repo). float() also accepts numeric strings, so BFloat16(value='1.5') now stores 1.5 instead of raising; this matches the positional constructor (py_type coercion) but diverges from struct-packed siblings, where struct.pack rejects strings (struct.error). Apply after float-1 (adjacent regions in the same file; float-1's snippet explicitly leaves this setter untouched).

> ⚖️ **Decision needed:** Accept the float() contract wholesale (numeric strings included, matching the constructor), or add an explicit isinstance(value, str) rejection so the setter takes real numbers only, matching struct.pack? The patch as written chooses the former for symmetry with the constructor.

<sub>covers: `inconsistency|bytemaker/bittypes/float.py|113-121`, `ux|bytemaker/bittypes/float.py|114-116`</sub>

---

## 4. Add promoted unary __neg__/__pos__/__abs__ to Int, matching Float

**Priority:** soon · [`bytemaker/bittypes/int.py:int.py 450-453 (insert directly after Int.__invert__)`](../../bytemaker/bittypes/int.py#L450) · **✓ verified on a patched copy**

**Problem.** Float defines __neg__/__pos__/__abs__ (promoted plain-float results) but Int defines none, so -Float32(5.0) works while -UInt8(5) raises TypeError. Under the stated C-promotion model, unary minus on an integer box should promote and compute in plain int exactly as it does for floats (in C, -uint8_t computes in int).

**Fix.** Add the three unary operators to Int right after __invert__ (which already documents the same promotion rule), each returning the plain promoted int. The comment mirrors the file's existing promotion-model commentary and points to the narrowing-cast spelling (UInt8(-u)) for the width-preserving form.

**Before:**

```python
    def __invert__(self) -> int:  # type: ignore[override]
        # The classic C gotcha, faithfully: ~ promotes, so the result is
        # plain -(value + 1). The width-preserving spelling is ~self.bits.
        return ~self.value
```

**After:**

```python
    def __invert__(self) -> int:  # type: ignore[override]
        # The classic C gotcha, faithfully: ~ promotes, so the result is
        # plain -(value + 1). The width-preserving spelling is ~self.bits.
        return ~self.value

    # Unary arithmetic promotes like the binary ops (in C, -uint8_t
    # computes in int): the result is the plain promoted value, and the
    # narrowing cast spelling is the constructor, e.g. UInt8(-u).
    # Mirrors Float.__neg__/__pos__/__abs__.

    def __neg__(self) -> int:
        return -self.value

    def __pos__(self) -> int:
        return +self.value

    def __abs__(self) -> int:
        return abs(self.value)
```

**Behavior change.** BEFORE: -UInt8(5) -> TypeError: bad operand type for unary -: 'UInt8'; +SInt8(-3) -> TypeError; abs(SInt8(-3)) -> TypeError. AFTER: -UInt8(5) -> -5 (plain int); +SInt8(-3) -> -3; abs(SInt8(-3)) -> 3. Full suite: 854 passed.

**Tests to add.** -UInt8(5) == -5 and type(-UInt8(5)) is int; UInt8(-UInt8(5)).value == 251 (narrowing cast spelling wraps like C); +SInt8(-3) == -3; abs(SInt8(-3)) == 3 and type is int; abs(UInt16(7)) == 7; -SInt8(-128) == 128 (promotes, no overflow, unlike C UB).

**Risks / sync obligations / review notes.** Purely additive; no existing dunder is overridden and the suite passes. abs()/unary results are plain ints, consistent with the promoted binary ops. Note round()/math.floor() etc. still go through __index__/__int__, unaffected. No _legacy_aggregate or BitVector sync needed.

<sub>covers: `inconsistency|bytemaker/bittypes/float.py|348-355`</sub>

---

## 5. Fix the Int copy-paste leftovers in the Float class docstring

**Priority:** **now** · [`bytemaker/bittypes/float.py:24, 42`](../../bytemaker/bittypes/float.py#L24) · **✓ verified on a patched copy**

**Problem.** The Float class docstring's summary line is copy-pasted from Int and says 'A BitType that represents an integer.' - the literal opposite of what Float is - and the py_type entry still says 'this `Int`' inside Float's own reference documentation. Both surface in help(), IDE hovers, and generated API docs for the headline float type.

**Fix.** Two one-line docstring edits: the summary becomes 'A BitType that represents an IEEE-754-style floating-point number.' (terse reference voice, mirroring Int's phrasing but accurate; this file uses the reference-era field-list style, which is kept), and 'this `Int`' becomes 'this `Float`' in the py_type entry. The elision marker in the snippets separates the two verbatim one-line regions.

**Before:**

```python
class Float(BitType[float]):
    """
    A BitType that represents an integer.

# --- [lines 25-40 unchanged, elided] ---

    py_type : Type[float]
        The Pythonic type that this `Int` can be converted to/from. It is `float`.
```

**After:**

```python
class Float(BitType[float]):
    """
    A BitType that represents an IEEE-754-style floating-point number.

# --- [lines 25-40 unchanged, elided] ---

    py_type : Type[float]
        The Pythonic type that this `Float` can be converted to/from. It is `float`.
```

**Behavior change.** Documentation-only: help(Float)/help(BFloat16) and generated docs now describe a floating-point number and reference the Float class in the py_type entry. No runtime behavior change (suite: 854 passed with the edit applied).

**Tests to add.** Optional doc smoke test: assert 'floating-point' in Float.__doc__ and 'represents an integer' not in Float.__doc__ and 'this `Int`' not in Float.__doc__.

**Risks / sync obligations / review notes.** None; docstring-only. The rest of the docstring already correctly describes the sign/exponent/mantissa layout, so no further edits are needed.

<sub>covers: `ai-tone|bytemaker/bittypes/float.py|24`, `docstring|bytemaker/bittypes/float.py|23-24`, `ux|bytemaker/bittypes/float.py|24`, `ai-tone|bytemaker/bittypes/float.py|41-42`</sub>

---
