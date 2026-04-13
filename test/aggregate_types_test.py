import ctypes
from dataclasses import dataclass

import pytest

from bytemaker.bittypes import (
    Buffer4,
    Float16,
    Float32,
    SInt5,
    SInt8,
    SInt10,
    SInt16,
    SInt32,
    SInt64,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
)
from bytemaker.bitvector import BitVector
from bytemaker.conversions.aggregate_types import (
    count_bytes_in_unit_type,
    from_bits_aggregate,
    from_bits_individual,
    from_bytes_aggregate,
    from_bytes_individual,
    to_bits_aggregate,
    to_bits_individual,
    to_bytes_aggregate,
    to_bytes_individual,
)

test_unit_data = [
    # Integers
    (1, "0b00000000_00000000_00000000_00000001"),
    (0, "0b00000000_00000000_00000000_00000000"),
    (-1, "0b11111111_11111111_11111111_11111111"),
    # Unsigned integers
    (UInt8(1), "0b00000001"),
    (UInt16(1), "0b00000000_00000001"),
    (UInt32(1), "0b00000000_00000000_00000000_00000001"),
    (
        UInt64(1),
        "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000001",
    ),
    (UInt8(0), "0b00000000"),
    (UInt16(0), "0b00000000_00000000"),
    (UInt32(0), "0b00000000_00000000_00000000_00000000"),
    (
        UInt64(0),
        "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000",
    ),
    (UInt8(255), "0b11111111"),
    (UInt16(255), "0b00000000_11111111"),
    (UInt32(255), "0b00000000_00000000_00000000_11111111"),
    (
        UInt64(255),
        "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_11111111",
    ),
    # Signed integers
    (SInt8(1), "0b00000001"),
    (SInt16(1), "0b00000000_00000001"),
    (SInt32(1), "0b00000000_00000000_00000000_00000001"),
    (
        SInt64(1),
        "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000001",
    ),
    (SInt8(0), "0b00000000"),
    (SInt16(0), "0b00000000_00000000"),
    (SInt32(0), "0b00000000_00000000_00000000_00000000"),
    (
        SInt64(0),
        "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000",
    ),
    (SInt8(-1), "0b11111111"),
    (SInt16(-1), "0b11111111_11111111"),
    (SInt32(-1), "0b11111111_11111111_11111111_11111111"),
    (
        SInt64(-1),
        "0b11111111_11111111_11111111_11111111_11111111_11111111_11111111_11111111",
    ),
    (SInt8(-128), "0b10000000"),
    (SInt16(-32768), "0b10000000_00000000"),
    (SInt32(-2147483648), "0b10000000_00000000_00000000_00000000"),
    (
        SInt64(-9223372036854775808),
        "0b10000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000",
    ),
    # Floats
    (Float16(1.0), "0b00111100_00000000"),
    (Float16(0.0), "0b00000000_00000000"),
    (Float16(-1.0), "0b10111100_00000000"),
    (Float16(3.140625), "0b01000010_01001000"),
]


test_bittype_to_bytes_data = [
    (UInt8(1), b"\x01", b"\x01"),
    (UInt16(1), b"\x00\x01", b"\x01\x00"),
    (UInt32(1), b"\x00\x00\x00\x01", b"\x01\x00\x00\x00"),
    (SInt16(-1), b"\xff\xff", b"\xff\xff"),
    (SInt32(256), b"\x00\x00\x01\x00", b"\x00\x01\x00\x00"),
]


@pytest.mark.parametrize(
    "bittype_val, expected_bytes, expected_bytes_reversed", test_bittype_to_bytes_data
)
def test_to_bytes_individual_bittype(
    bittype_val, expected_bytes, expected_bytes_reversed
):
    assert to_bytes_individual(bittype_val) == expected_bytes
    assert (
        to_bytes_individual(bittype_val, endianness="little") == expected_bytes_reversed
    )


test_from_bytes_roundtrip_data = [
    (UInt8, UInt8(1)),
    (UInt16, UInt16(1)),
    (UInt32, UInt32(1)),
    (SInt16, SInt16(-1)),
    (SInt32, SInt32(256)),
]


@pytest.mark.parametrize("unittype, original", test_from_bytes_roundtrip_data)
def test_from_bytes_individual_roundtrip(unittype, original):
    """Round-trip: to_bytes_individual -> from_bytes_individual should recover
    the original value, both with and without endianness."""
    raw_bytes = to_bytes_individual(original)
    assert from_bytes_individual(raw_bytes, unittype) == original

    reversed_bytes = to_bytes_individual(original, endianness="little")
    assert (
        from_bytes_individual(reversed_bytes, unittype, endianness="little") == original
    )


@dataclass
class SingleFieldDataclass:
    a: UInt8


def test_from_bytes_aggregate_field_type_assignment():
    """Regression test: from_bytes_aggregate must assign field_type = field.type
    before checking isinstance(field.type, str). Previously field_type was
    undefined on the first iteration when the type was not a string annotation,
    causing a NameError."""
    result = from_bytes_aggregate(b"\x2a", SingleFieldDataclass)
    assert result.a.value == 42


@dataclass
class TwoFieldDataclass:
    a: UInt16
    b: UInt16


test_count_bytes_data = [
    (UInt8, 1),  # 8 bits -> 1 byte
    (UInt16, 2),  # 16 bits -> 2 bytes
    (UInt32, 4),  # 32 bits -> 4 bytes
    (SInt5, 1),  # 5 bits -> 1 byte (ceiling)
    (SInt10, 2),  # 10 bits -> 2 bytes (ceiling)
]


@pytest.mark.parametrize("unittype, expected_bytes", test_count_bytes_data)
def test_count_bytes_in_unit_type(unittype, expected_bytes):
    """Regression test: count_bytes_in_unit_type must use ceiling division
    ((bits + 7) // 8). Previously it used (bits + 1) // 8, which returned
    1 byte for a 10-bit type instead of 2."""
    assert count_bytes_in_unit_type(unittype) == expected_bytes


def test_from_bytes_aggregate_byte_slicing():
    """Regression test: from_bytes_aggregate must slice bytes_obj by byte count,
    not bit count. Previously count_bits_in_unit_type (returning bits) was used
    directly to index a bytes object, so a 16-bit field would consume 16 bytes
    instead of 2."""
    raw_bytes = b"\x00\x01\x00\x02"  # UInt16(1) followed by UInt16(2)
    result = from_bytes_aggregate(raw_bytes, TwoFieldDataclass)
    assert result.a.value == 1
    assert result.b.value == 2


def test_from_bytes_aggregate_roundtrip_with_endianness():
    """Regression test: from_bytes_aggregate must not reverse the entire byte
    stream before splitting into fields. Previously it reversed the whole
    bytes_obj at the top level and then passed endianness="little" to each
    field, causing double reversal. Endianness reversal should only happen at
    the leaf level (per-field)."""
    original = TwoFieldDataclass(UInt16(0x0102), UInt16(0x0304))
    serialized = to_bytes_aggregate(original, endianness="little")
    result = from_bytes_aggregate(serialized, TwoFieldDataclass, endianness="little")
    assert result.a.value == 0x0102
    assert result.b.value == 0x0304


@pytest.mark.parametrize("unitdata, expected_bitstring", test_unit_data)
def test_unit_types(unitdata, expected_bitstring):
    to_bits_obj_agg = to_bits_aggregate(unitdata)
    to_bits_obj_un = to_bits_individual(unitdata)
    assert to_bits_obj_agg == to_bits_obj_un
    assert to_bits_obj_agg.bin() == expected_bitstring.replace("_", "")
    print(len(to_bits_obj_agg))
    from_bits_obj_agg = from_bits_aggregate(to_bits_obj_agg, type(unitdata))
    from_bits_obj_un = from_bits_individual(to_bits_obj_un, type(unitdata))
    assert from_bits_obj_agg == from_bits_obj_un
    assert from_bits_obj_agg == unitdata


@dataclass
class PyTypeAggregate1:
    a: int
    b: float
    c: str  # Char


@dataclass
class CTypeAggregate1:
    a: ctypes.c_int32
    # b: ctypes.c_float
    c: ctypes.c_char


@dataclass
class BitTypeAggregate1:
    a: SInt32
    b: Float32
    c: Buffer4


@dataclass
class MixedAggregate:
    pytype_aggregate: PyTypeAggregate1
    ctype_aggregate: CTypeAggregate1
    bittype_aggregate: BitTypeAggregate1


@dataclass
class TestClass:
    b: float


# def test_basic():
#     print(BitVector("0xFFFF").to_hex())
#     print(to_bits_aggregate(TestClass(3.1415927410125732421875)).to_hex())
#     assert False == True


@pytest.fixture
def aggregate_data_1_val():
    return PyTypeAggregate1(382, 3.1415927410125732421875, "A")


@pytest.fixture
def aggregate_data_1_rep():
    return BitVector(
        "0x0000017E"  # 382
        "40490fdb"  # 3.1415927410125732421875
        "41"  # A
    )


@pytest.fixture
def aggregate_data_1_c_val():
    return CTypeAggregate1(
        382,
        # 3.1415927410125732421875,
        ctypes.c_char(b"A"),
    )


@pytest.fixture
def aggregate_data_1_c_rep():
    return BitVector(
        "0x0000017E"  # 382
        # "40490fdb"  # 3.1415927410125732421875
        "41"  # A
    )


@pytest.fixture
def aggregate_data_1_bittype_val():
    return BitTypeAggregate1(
        SInt32(382), Float32(3.1415927410125732421875), Buffer4([0, 1, 0, 0])
    )


@pytest.fixture
def aggregate_data_1_bittype_rep():
    return BitVector(
        "0x0000017E"  # 382
        "40490fdb"  # 3.1415927410125732421875
        "4"
    )


def test_pytype_dataclass(aggregate_data_1_rep):
    assert (
        to_bits_aggregate(PyTypeAggregate1(382, 3.1415927410125732421875, "A")).hex()
        == aggregate_data_1_rep.hex()
    )
    left = from_bits_aggregate(aggregate_data_1_rep, PyTypeAggregate1)
    right = PyTypeAggregate1(382, 3.141592653589793, "A")
    assert left.a == right.a
    assert left.c == right.c
    assert left.b == pytest.approx(right.b)
    assert (
        type(from_bits_aggregate(aggregate_data_1_rep, PyTypeAggregate1))
        == PyTypeAggregate1
    )


def test_ctype_dataclass(aggregate_data_1_c_rep):
    assert (
        to_bits_aggregate(
            CTypeAggregate1(
                382,
                # 3.1415927410125732421875,
                ctypes.c_char(b"A"),
            )
        ).hex()
        == aggregate_data_1_c_rep.hex()
    )

    from_bits_agg_gotten = from_bits_aggregate(aggregate_data_1_c_rep, CTypeAggregate1)
    assert from_bits_agg_gotten.a.value == 382
    assert from_bits_agg_gotten.c.value == b"A"
    assert (
        type(from_bits_aggregate(aggregate_data_1_c_rep, CTypeAggregate1))
        == CTypeAggregate1
    )


def test_bittype_dataclass(aggregate_data_1_bittype_rep):
    print("Sint 382 conversion:", SInt32(382))
    # print(BitTypeAggregate1(SInt32(382)))
    assert (
        to_bits_aggregate(
            BitTypeAggregate1(
                SInt32(382), Float32(3.1415927410125732421875), Buffer4([0, 1, 0, 0])
            )
        ).hex()
        == aggregate_data_1_bittype_rep.hex()
    )

    from_bits_agg_gotten = from_bits_aggregate(
        aggregate_data_1_bittype_rep, BitTypeAggregate1
    )
    assert from_bits_agg_gotten.a.value == 382
    assert from_bits_agg_gotten.b.value == 3.1415927410125732421875
    assert from_bits_agg_gotten.c == BitVector([0, 1, 0, 0])


def test_mixed_dataclass(
    aggregate_data_1_rep,
    aggregate_data_1_val,
    aggregate_data_1_c_rep,
    aggregate_data_1_c_val,
    aggregate_data_1_bittype_rep,
    aggregate_data_1_bittype_val,
):
    """
    Tests whether converting an aggregated dataclass to bits and
    back to the dataclass results in the same data
    """

    mixed_aggregate = MixedAggregate(
        aggregate_data_1_val, aggregate_data_1_c_val, aggregate_data_1_bittype_val
    )

    def mixed_aggregate_data_1_rep():
        return BitVector([]).join(
            [aggregate_data_1_rep, aggregate_data_1_c_rep, aggregate_data_1_bittype_rep]
        )

    print(mixed_aggregate)
    gottenattr = getattr(mixed_aggregate, "pytype_aggregate")
    print("getattr", gottenattr)
    bits_aggregate = to_bits_aggregate(mixed_aggregate)
    print(bits_aggregate)
    assert to_bits_aggregate(mixed_aggregate) == mixed_aggregate_data_1_rep()

    from_bits_agg_gotten = from_bits_aggregate(
        mixed_aggregate_data_1_rep(), MixedAggregate
    )
    assert from_bits_agg_gotten.pytype_aggregate == aggregate_data_1_val
    assert from_bits_agg_gotten.ctype_aggregate.a.value == 382
    assert from_bits_agg_gotten.ctype_aggregate.c.value == b"A"
    assert from_bits_agg_gotten.bittype_aggregate == aggregate_data_1_bittype_val
