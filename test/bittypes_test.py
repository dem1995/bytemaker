import pytest

from bytemaker.bittypes import (
    Buffer,
    Float,
    Float32,
    Float64,
    SInt8,
    SInt10,
    SInt16,
    SInt32,
    SInt64,
    UInt8,
    UInt10,
    UInt16,
    UInt32,
    UInt64,
    UTF8String,
)
from bytemaker.bittypes.bittype import StructPackedBitType
from bytemaker.bitvector import BitVector

# Named-width String/Buffer zoos are gone; mint what these tests need.
# (.of counts bytes — the field door; specialize counts bits — the box door.)
Str8 = UTF8String.of(1, name="Str8")
Str16 = UTF8String.of(2, name="Str16")
Buffer4 = Buffer.specialize(4, "Buffer4")
Buffer8 = Buffer.specialize(8, "Buffer8")
Buffer16 = Buffer.specialize(16, "Buffer16")
Buffer32 = Buffer.specialize(32, "Buffer32")
Buffer64 = Buffer.specialize(64, "Buffer64")


@pytest.mark.parametrize(
    "bittype_class, constructor_arg, update_arg",
    [
        (UInt16, 2**16 - 1, 2**8),
        (SInt16, -(2**15), 2**8),
        (Float32, 3.1415926535, 2.7182818284),
        (Str8, "a", "b"),
        (
            Buffer8,
            BitVector([0, 1, 1, 1, 0, 1, 0, 1]),
            BitVector([1, 0, 1, 0, 1, 1, 1, 0]),
        ),
    ],
)
def test_cru_bittype(bittype_class, constructor_arg, update_arg):
    bittype_instance = bittype_class(constructor_arg)
    bittype_instance.value = update_arg
    if isinstance(bittype_instance, Float):
        assert abs(bittype_instance.value - update_arg) < 1e-6
    else:
        assert bittype_instance.value == update_arg


# Test cases for Unsigned Integers
@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits",
    [
        (UInt8, 255, BitVector([1] * 8)),
        (UInt16, 65535, BitVector([1] * 16)),
        (UInt32, 2**32 - 1, BitVector([1] * 32)),
        (UInt64, 2**64 - 1, BitVector([1] * 64)),
    ],
)
def test_uint_serialization(bittype_class, input_value, expected_bits):
    bittype_instance = bittype_class(input_value)
    assert bittype_instance.to_bits() == expected_bits


@pytest.mark.parametrize(
    "bittype_class, input_bits, expected_value",
    [
        (UInt8, BitVector([1] * 8), 255),
        (UInt16, BitVector([1] * 16), 65535),
        (UInt32, BitVector([1] * 32), 2**32 - 1),
        (UInt64, BitVector([1] * 64), 2**64 - 1),
    ],
)
def test_uint_deserialization(bittype_class, input_bits, expected_value):
    bittype_instance = bittype_class.from_bits(input_bits)
    assert bittype_instance.value == expected_value


# Test cases for Signed Integers
@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits_length",
    [
        (SInt8, -128, 8),
        (SInt16, -32768, 16),
        (SInt32, -2147483648, 32),
        (SInt64, -9223372036854775808, 64),
    ],
)
def test_sint_serialization(bittype_class, input_value, expected_bits_length):
    bittype_instance = bittype_class(input_value)
    assert len(bittype_instance.to_bits()) == expected_bits_length


# Test cases for Floats
@pytest.mark.parametrize(
    "bittype_class, input_value",
    [
        (Float32, 1.0),
        (Float64, 1.0),
        (Float32, -1.0),
        (Float64, -1.0),
        (Float32, 3.1415926535),
        (Float64, 3.1415926535),
    ],
)
def test_float_serialization_and_deserialization(bittype_class, input_value):
    bittype_instance = bittype_class(input_value)
    deserialized_value = bittype_class.from_bits(bittype_instance.to_bits()).value
    assert abs(deserialized_value - input_value) < 1e-6


# Test cases for Strings
@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits_length",
    [
        (Str8, "a", 8),
        (Str16, "ef", 16),
    ],
)
def test_str_serialization_and_deserialization(
    bittype_class, input_value, expected_bits_length
):
    bittype_instance = bittype_class(input_value)
    assert len(bittype_instance.to_bits()) == expected_bits_length
    deserialized_value = bittype_class.from_bits(bittype_instance.to_bits()).value
    assert deserialized_value == input_value


@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits",
    [
        (Str8, "a", BitVector([0, 1, 1, 0, 0, 0, 0, 1])),
        (Str16, "ef", BitVector([0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0])),
    ],
)
def test_str_endianess(bittype_class, input_value, expected_bits):
    bittype_instance = bittype_class(input_value)
    assert bittype_instance.to_bits() == expected_bits

    # little endian
    bittype_instance = bittype_class(input_value, endianness="little")
    reversed_chunks = bytes(reversed(bytes(expected_bits)))

    assert bytes(bittype_instance) == reversed_chunks


def test_str_codepoint_changes_longest_match():
    """Substitutions must prefer the longest table entry (regression: the
    alternation regex was built unsorted, so a shorter key like "A"
    permanently shadowed a longer one like "AB" in both directions)."""
    from bytemaker.utils import FrozenDict

    class TableStr16(Str16):
        _codepoint_changes = FrozenDict({"A": "1", "AB": "12"})

    # decode side: raw "AB" must map through the longer key ("12", not "1B")
    assert TableStr16(bits=BitVector(b"AB")).value == "12"

    # encode side: reverse substitution must yield "AB", not "A" + stray "2"
    assert bytes(TableStr16("12").bits) == b"AB"


def test_int_index_protocol():
    """__index__ makes boxes usable anywhere a plain int is: hex(), list
    indexing, range(), and the Struct descriptors' operator.index() store."""
    import operator

    assert operator.index(UInt8(40)) == 40
    assert hex(UInt8(40)) == "0x28"
    assert [10, 20, 30][UInt8(1)] == 20
    assert len(range(UInt8(3))) == 3
    assert operator.index(SInt8(-3)) == -3


def test_bittype_format_spec_formats_value():
    """A format spec formats the value; no spec keeps the sized display."""
    u = UInt8(40)
    assert f"{u:02x}" == "28"
    assert f"{u:d}" == "40"
    assert f"{u}" == str(u)
    assert f"{Float32(1.5):.1f}" == "1.5"


def test_int_promotion_c_semantics():
    """D5: binary ops promote to plain int at full width - no
    wrap-at-operator (C never wraps mid-expression; narrowing happens only
    at stores/casts)."""
    r = UInt8(200) + 100
    assert r == 300 and type(r) is int  # previously UInt8(44), silently
    assert 100 + UInt8(200) == 300  # reflected
    assert UInt8(200) + UInt8(100) == 300  # box + box
    assert SInt8(-3) + UInt8(40) == 37  # no signed/unsigned coercion trap
    assert UInt8(40) / 7 == 40 / 7  # previously TypeError (py_type check)
    assert type(UInt8(40) / 7) is float
    assert UInt8(UInt8(255) + 1) == 0  # the C cast spelling wraps
    with pytest.raises(TypeError):
        UInt8(1) + "x"


def test_int_bitwise_promotes():
    u = UInt8(40)
    assert u & 0xFF == 40 and type(u & 0xFF) is int
    assert u | 0x80 == 168
    assert u ^ 0xFF == 215
    assert u << 8 == 40 << 8  # no width loss at the operator
    assert 1 << UInt8(3) == 8  # reflected shift
    assert ~UInt8(0) == -1  # the C gotcha, faithfully; ~u.bits is bit-plane


def test_int_ordering_comparisons():
    """New in D5 - ordering previously did not exist on any BitType."""
    assert UInt8(40) > 3 and UInt8(40) >= 40 and UInt8(40) <= 40
    assert SInt8(-3) < 0 and SInt8(-3) < UInt8(1)
    assert sorted([UInt8(3), UInt8(1), UInt8(2)]) == [1, 2, 3]
    with pytest.raises(TypeError):
        UInt8(1) < "x"


def test_int_compound_assignment_narrows_in_place():
    """C compound assignment: full-width compute, narrow at the store,
    type preserved."""
    u = UInt8(255)
    u += 1
    assert isinstance(u, UInt8) and u.value == 0
    u += 10
    u <<= 4  # 10 << 4 = 160
    assert u.value == 160
    u //= 3
    assert u.value == 53
    u /= 2  # float result: converts at the store, C-style (truncates)
    assert isinstance(u, UInt8) and u.value == 26
    s = SInt8(127)
    s += 1
    assert s.value == -128  # two's-complement wrap at the store


def test_float_promotion_and_bitwise_refusal():
    f = Float32(1.5)
    assert f + 0.5 == 2.0 and type(f + 0.5) is float
    assert 0.5 + f == 2.0
    assert f > 1 and f <= 1.5
    f2 = Float32(1.5)
    f2 += 0.25
    assert isinstance(f2, Float32) and f2.value == 1.75
    with pytest.raises(TypeError):
        f & 1  # no value-plane bitwise on floats (as in C)
    with pytest.raises(TypeError):
        ~f
    assert -f == -1.5 and abs(Float32(-2.0)) == 2.0


def test_bittype_bits_live_and_width_locked():
    """Bits handles are live; width is invariant; width-preserving mutation
    writes through; width-changing mutation raises. Assignment snapshots."""
    u = UInt8(40)  # 00101000
    b = u.bits
    b[3] = 1  # live handout: 00111000
    assert u.value == 56
    with pytest.raises(ValueError):
        b.append(1)  # width-changing: raises instead of corrupting
    with pytest.raises(ValueError):
        del b[0]
    with pytest.raises(ValueError):
        b += BitVector("1")
    assert u.value == 56 and len(u.bits) == 8  # box untouched by failures

    src = BitVector("11110000")
    u.bits = src  # assignment snapshots into locked storage...
    src.append(1)  # ...so the caller's vector is no hidden alias
    assert len(u.bits) == 8 and u.value == 0xF0

    u.bits[0:4] = "0000"  # length-preserving slice write: goes through
    assert u.value == 0
    with pytest.raises(ValueError):
        u.bits[0:4] = "00000"  # length-changing slice write: refused


def test_bits_assignment_from_byte_sources():
    """Byte sources measure by constructed bit width (not len(source)), and
    are copied - never aliased, never read-only - whatever their type."""
    u = UInt16(0)
    u.bits = b"\x12\x34"  # 2 bytes -> 16 bits: accepted
    assert u.value == 0x1234
    with pytest.raises(ValueError):
        u.bits = b"\x12"  # 8 bits into a 16-bit box

    ba = bytearray(b"\xf0\x0f")
    u.bits = ba  # bytearray zero-copy imports live in BitVector...
    ba[0] = 0x00  # ...so assignment must have copied it
    assert u.value == 0xF00F
    u.bits[0] = 0  # and the copied storage stays writable
    assert len(u.bits) == 16


def test_bittype_Bits_cast_protocol():
    """BitVector(bittype) works via __Bits__; the cast is an independent
    copy, while the protocol result itself is live and width-locked."""
    u = UInt8(40)
    bv = BitVector(u)
    assert bv == u.bits and bv is not u.bits
    bv.append(1)  # resizable copy: box unaffected
    assert len(bv) == 9 and len(u.bits) == 8

    live = u.__Bits__()
    live[3] = 1  # live view: mutates the box
    assert u.value == 56
    with pytest.raises(ValueError):
        live.append(1)  # and width-locked


@pytest.mark.parametrize(
    "bittype_class, input_value, expected_bits_length",
    [
        (Buffer4, BitVector([0, 1, 1, 1]), BitVector([0, 1, 1, 1])),
        (
            Buffer8,
            BitVector([0, 1, 1, 1, 0, 1, 0, 1]),
            BitVector([0, 1, 1, 1, 0, 1, 0, 1]),
        ),
        (
            Buffer16,
            BitVector([0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1]),
            BitVector([0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1]),
        ),
        (
            Buffer32,
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
            # fmt: on
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
        ),
        (
            Buffer64,
            # fmt: on
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
            # fmt: on
            # fmt: off
            BitVector(
                [0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,
                 0, 1, 1, 1, 0, 1, 0, 1,]
            ),
            # fmt: on
        ),
    ],
)
def test_bit_serialization_and_deserialization(
    bittype_class, input_value, expected_bits_length
):
    bittype_instance = bittype_class(input_value)
    bittype_instance_type = type(bittype_instance)
    print("BitType instance is:", bittype_instance)
    print("BitType instance type is:", bittype_instance_type)
    assert bittype_instance.to_bits() == expected_bits_length
    deserialized_value = bittype_class.from_bits(bittype_instance.to_bits()).value
    assert deserialized_value == input_value


class UInt12Packed(StructPackedBitType, UInt16.__mro__[2]):
    """A 12-bit unsigned int that uses struct packing with 'H' (unsigned short).
    Used to test StructPackedBitType.value padding for non-multiple-of-8 bit counts."""

    _num_bits = 12
    base_bit_type = UInt16.__mro__[2]
    py_type = int
    packing_format_letter = "H"


def test_struct_packed_bittype_non_byte_aligned_value():
    """Regression test: StructPackedBitType.value must pad bits to a byte
    boundary before calling struct.unpack. Previously it computed the
    padded bits into a local variable but then passed the unpadded
    self.bits to struct.unpack instead."""
    from bytemaker.bitvector import BitVector

    # 12 bits representing the value 42: 000000101010
    bits_42 = BitVector("0b000000101010")
    instance = UInt12Packed(bits=bits_42)
    assert instance.value == 42


def test_uint_non_struct_value_setter_zero_pads():
    """Regression test: the non-struct UInt.value setter must produce exactly
    num_bits, zero-padded, through the validating bits property. Previously it
    assigned BitVector(bin(value)[2:]) straight to self._bits, yielding
    minimal-width bits (UInt10(1).bits had length 1, not 10) and breaking
    aggregate serialization."""
    u = UInt10(1)
    assert len(u.bits) == UInt10.num_bits == 10
    assert u.bits.to01() == "0000000001"
    assert u.value == 1
    assert len(u.to_bits()) == 10

    # zero and the maximum stay full-width and round-trip through the bits
    assert len(UInt10(0).bits) == 10
    hi = UInt10(2**10 - 1)
    assert len(hi.bits) == 10 and hi.value == 2**10 - 1
    assert UInt10.from_bits(hi.to_bits()).value == 2**10 - 1

    # out-of-range values wrap modulo 2**num_bits, like a C (uint10_t) cast
    u.value = 2**10  # 1024 -> 0
    assert u.value == 0 and len(u.bits) == 10
    u.value = 2**10 + 5  # 1029 -> 5
    assert u.value == 5
    u.value = -1  # -> 1023 (all ones), like (uint10_t)(-1)
    assert u.value == 2**10 - 1


def test_sint_non_struct_value_setter_wraps_like_c():
    """The non-struct (two's-complement) SInt.value setter narrows an
    out-of-range value by truncation, matching a C (int10_t) cast, rather
    than raising."""
    s = SInt10(0, int_format="twos_complement")
    assert len(s.bits) == 10

    s.value = 2**9  # 512 overflows the top of [-512, 511] -> -512
    assert s.value == -(2**9)
    s.value = -(2**9) - 1  # -513 underflows -> 511
    assert s.value == 2**9 - 1
    assert len(s.bits) == 10


def test_struct_packed_int_value_wraps_like_c():
    """Struct-packed integer types narrow out-of-range values by truncation
    (C (uintN_t)/(intN_t) semantics) instead of raising struct.error. Floats
    are unaffected."""
    u = UInt8(0)
    u.value = 256  # -> 0
    assert u.value == 0 and len(u.bits) == 8
    u.value = 257  # -> 1
    assert u.value == 1
    u.value = -1  # -> 255
    assert u.value == 255

    s = SInt8(0)
    s.value = 128  # overflows [-128, 127] -> -128
    assert s.value == -128
    s.value = -129  # underflows -> 127
    assert s.value == 127

    w = UInt16(0)
    w.value = 2**16 + 3  # -> 3
    assert w.value == 3

    # floats still round-trip (and reject non-representable magnitudes as before)
    f = Float32(1.5)
    f.value = 2.5
    assert f.value == 2.5
