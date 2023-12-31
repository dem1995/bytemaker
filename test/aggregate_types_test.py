import pytest
import ctypes

from dataclasses import dataclass
from bytemaker.bits import Bits
from bytemaker.ytypes import UInt8, UInt16, UInt32, UInt64, SInt8, SInt16, SInt32, SInt64, Float16, Float32, Bit4
from bytemaker.aggregate_types import to_bits_aggregate, from_bits_aggregate, to_bits_individual, from_bits_individual


test_unit_data = [
    # Integers
    (1, "0b00000000_00000000_00000000_00000001"),
    (0, "0b00000000_00000000_00000000_00000000"),
    (-1, "0b11111111_11111111_11111111_11111111"),

    # Unsigned integers
    (UInt8(1), "0b00000001"),
    (UInt16(1), "0b00000000_00000001"),
    (UInt32(1), "0b00000000_00000000_00000000_00000001"),
    (UInt64(1), "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000001"),
    (UInt8(0), "0b00000000"),
    (UInt16(0), "0b00000000_00000000"),
    (UInt32(0), "0b00000000_00000000_00000000_00000000"),
    (UInt64(0), "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000"),
    (UInt8(255), "0b11111111"),
    (UInt16(255), "0b00000000_11111111"),
    (UInt32(255), "0b00000000_00000000_00000000_11111111"),
    (UInt64(255), "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_11111111"),

    # Signed integers
    (SInt8(1), "0b00000001"),
    (SInt16(1), "0b00000000_00000001"),
    (SInt32(1), "0b00000000_00000000_00000000_00000001"),
    (SInt64(1), "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000001"),
    (SInt8(0), "0b00000000"),
    (SInt16(0), "0b00000000_00000000"),
    (SInt32(0), "0b00000000_00000000_00000000_00000000"),
    (SInt64(0), "0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000"),
    (SInt8(-1), "0b11111111"),
    (SInt16(-1), "0b11111111_11111111"),
    (SInt32(-1), "0b11111111_11111111_11111111_11111111"),
    (SInt64(-1), "0b11111111_11111111_11111111_11111111_11111111_11111111_11111111_11111111"),
    (SInt8(-128), "0b10000000"),
    (SInt16(-32768), "0b10000000_00000000"),
    (SInt32(-2147483648), "0b10000000_00000000_00000000_00000000"),
    (SInt64(-9223372036854775808), "0b10000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000"),

    # Floats
    (Float16(1.0), "0b00111100_00000000"),
    (Float16(0.0), "0b00000000_00000000"),
    (Float16(-1.0), "0b10111100_00000000"),
    (Float16(3.140625), "0b01000010_01001000"),

]


@pytest.mark.parametrize("unitdata, expected_bitstring", test_unit_data)
def test_unit_types(unitdata, expected_bitstring):
    to_bits_obj_agg = to_bits_aggregate(unitdata)
    to_bits_obj_un = to_bits_individual(unitdata)
    assert to_bits_obj_agg == to_bits_obj_un
    assert str(to_bits_obj_agg) == expected_bitstring
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
class YTypeAggregate1:
    a: SInt32
    b: Float32
    c: Bit4


@dataclass
class MixedAggregate:
    pytype_aggregate: PyTypeAggregate1
    ctype_aggregate: CTypeAggregate1
    ytype_aggregate: YTypeAggregate1


@dataclass
class TestClass:
    b: float


# def test_basic():
#     print(Bits("0xFFFF").to_hex())
#     print(to_bits_aggregate(TestClass(3.1415927410125732421875)).to_hex())
#     assert False == True

@pytest.fixture
def aggregate_data_1_val():
    return PyTypeAggregate1(
        382,
        3.1415927410125732421875,
        "A"
    )


@pytest.fixture
def aggregate_data_1_rep():
    return Bits(
        "0x0000017E"  # 382
        "40490fdb"  # 3.1415927410125732421875
        "41"  # A
    )


@pytest.fixture
def aggregate_data_1_c_val():
    return CTypeAggregate1(
        382,
        # 3.1415927410125732421875,
        ctypes.c_char('A'.encode('utf-8'))
    )


@pytest.fixture
def aggregate_data_1_c_rep():
    return Bits(
        "0x0000017E"  # 382
        # "40490fdb"  # 3.1415927410125732421875
        "41"  # A
    )


@pytest.fixture
def aggregate_data_1_y_val():
    return YTypeAggregate1(
        SInt32(382),
        Float32(3.1415927410125732421875),
        Bit4([0, 1, 0, 0])
    )


@pytest.fixture
def aggregate_data_1_y_rep():
    return Bits(
        "0x0000017E"  # 382
        "40490fdb"  # 3.1415927410125732421875
        "4"
    )


def test_pytype_dataclass(aggregate_data_1_rep):
    assert to_bits_aggregate(PyTypeAggregate1(
        382,
        3.1415927410125732421875,
        "A"
    )).to_hex() == aggregate_data_1_rep.to_hex()
    left = from_bits_aggregate(aggregate_data_1_rep, PyTypeAggregate1)
    right = PyTypeAggregate1(382, 3.141592653589793, "A")
    assert left.a == right.a
    assert left.c == right.c
    assert left.b == pytest.approx(right.b)
    assert type(from_bits_aggregate(aggregate_data_1_rep, PyTypeAggregate1)) == PyTypeAggregate1


def test_ctype_dataclass(aggregate_data_1_c_rep):
    assert to_bits_aggregate(
        CTypeAggregate1(
            382,
            # 3.1415927410125732421875,
            ctypes.c_char('A'.encode('utf-8'))
        )).to_hex() == aggregate_data_1_c_rep.to_hex()

    from_bits_agg_gotten = from_bits_aggregate(aggregate_data_1_c_rep, CTypeAggregate1)
    assert from_bits_agg_gotten.a.value == 382
    assert from_bits_agg_gotten.c.value == b'A'
    assert type(from_bits_aggregate(aggregate_data_1_c_rep, CTypeAggregate1)) == CTypeAggregate1


def test_ytype_dataclass(aggregate_data_1_y_rep):
    assert to_bits_aggregate(
        YTypeAggregate1(
            SInt32(382),
            Float32(3.1415927410125732421875),
            Bit4([0, 1, 0, 0])
        )).to_hex() == aggregate_data_1_y_rep.to_hex()

    from_bits_agg_gotten = from_bits_aggregate(aggregate_data_1_y_rep, YTypeAggregate1)
    assert from_bits_agg_gotten.a.value == 382
    assert from_bits_agg_gotten.b.value == 3.1415927410125732421875
    assert from_bits_agg_gotten.c == Bits([0, 1, 0, 0])


def test_mixed_dataclass(
        aggregate_data_1_rep,
        aggregate_data_1_val,
        aggregate_data_1_c_rep,
        aggregate_data_1_c_val,
        aggregate_data_1_y_rep,
        aggregate_data_1_y_val):

    mixed_aggregate = MixedAggregate(
        aggregate_data_1_val,
        aggregate_data_1_c_val,
        aggregate_data_1_y_val
    )

    def mixed_aggregate_data_1_rep():
        return Bits([]).join([aggregate_data_1_rep, aggregate_data_1_c_rep, aggregate_data_1_y_rep])

    assert to_bits_aggregate(mixed_aggregate).to_hex() == mixed_aggregate_data_1_rep().to_hex()

    from_bits_agg_gotten = from_bits_aggregate(mixed_aggregate_data_1_rep(), MixedAggregate)
    assert from_bits_agg_gotten.pytype_aggregate == aggregate_data_1_val
    assert from_bits_agg_gotten.ctype_aggregate.a.value == 382
    assert from_bits_agg_gotten.ctype_aggregate.c.value == b'A'
    assert from_bits_agg_gotten.ytype_aggregate == aggregate_data_1_y_val
