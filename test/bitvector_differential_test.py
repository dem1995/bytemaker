# flake8: noqa
"""
Differential fuzz tests: the packed pure-Python BitVector implementation
(`bitvector_speedup`) is driven in lockstep with the byte-per-bit reference
implementation (`bitvector_native`) through seeded random operation
sequences. After every step the two must agree on state (to01), on return
values, and on the exception type raised, and the speedup implementation
must uphold its packed-representation invariants.
"""

import copy
import random

import pytest

from bytemaker.bitvector.bitvector_native import BitVector as NativeBitVector
from bytemaker.bitvector.bitvector_speedup import BitVector as SpeedupBitVector


# Marker resolved per-implementation so each side operates on its own class.
class SameImplBV:
    def __init__(self, s01):
        self.s01 = s01

    def resolve(self, cls):
        return cls(self.s01)


def _normalize(result, cls):
    """Reduces an operation result to an implementation-independent form."""
    if isinstance(result, cls):
        return ("BV", result.to01())
    if isinstance(result, tuple):
        return tuple(_normalize(item, cls) for item in result)
    if isinstance(result, (list, bytes, bytearray, str, int, bool)) or result is None:
        return result
    if result is NotImplemented:
        return "NotImplemented"
    return repr(result)


def _random01(rng, length):
    return "".join(rng.choice("01") for _ in range(length))


def _random_index(rng, n):
    """An index that is usually valid but occasionally out of bounds."""
    return rng.randint(-n - 2, n + 1) if n else rng.randint(-2, 1)


def _random_bit_value(rng):
    return rng.choice([0, 1, 1, 0, True, False, 2, "1", "0", 0.0, 1.0])


def _random_constructible(rng, length):
    s01 = _random01(rng, length)
    form = rng.randrange(4)
    if form == 0:
        return s01
    if form == 1:
        return [int(c) for c in s01]
    if form == 2:
        return SameImplBV(s01)
    return bytes(int(c) for c in s01)  # iterable of 0/1 byte values


def _resolve(value, cls):
    if isinstance(value, SameImplBV):
        return value.resolve(cls)
    return value


# Each op: name, param generator (rng, current01) -> params,
#          application (bv, cls, params) -> result
OPS = [
    (
        "getitem_int",
        lambda rng, s: (_random_index(rng, len(s)),),
        lambda bv, cls, p: bv[p[0]],
    ),
    (
        "getitem_slice",
        lambda rng, s: (
            rng.randint(-len(s) - 2, len(s) + 2),
            rng.randint(-len(s) - 2, len(s) + 2),
            rng.choice([None, 1, 2, 3, -1, -2]),
        ),
        lambda bv, cls, p: bv[p[0] : p[1] : p[2]],
    ),
    (
        "getitem_iterable",
        lambda rng, s: ([_random_index(rng, len(s)) for _ in range(rng.randrange(4))],),
        lambda bv, cls, p: bv[p[0]],
    ),
    (
        "setitem_int",
        lambda rng, s: (_random_index(rng, len(s)), _random_bit_value(rng)),
        lambda bv, cls, p: bv.__setitem__(p[0], p[1]),
    ),
    (
        "setitem_slice",
        lambda rng, s: (
            rng.randint(-len(s) - 1, len(s) + 1),
            rng.randint(-len(s) - 1, len(s) + 1),
            rng.choice([None, 1, 2, -1]),
            rng.choice(
                [
                    rng.choice([0, 1]),
                    _random01(rng, rng.randrange(6)),
                    SameImplBV(_random01(rng, rng.randrange(6))),
                ]
            ),
        ),
        lambda bv, cls, p: bv.__setitem__(slice(p[0], p[1], p[2]), _resolve(p[3], cls)),
    ),
    (
        "setitem_iterable",
        lambda rng, s: (
            [_random_index(rng, len(s)) for _ in range(rng.randrange(4))],
            rng.choice([0, 1, "0", "1"]),
        ),
        lambda bv, cls, p: bv.__setitem__(
            p[0], p[1] if isinstance(p[1], int) else p[1] * len(p[0])
        ),
    ),
    (
        "delitem_int",
        lambda rng, s: (_random_index(rng, len(s)),),
        lambda bv, cls, p: bv.__delitem__(p[0]),
    ),
    (
        "delitem_slice",
        lambda rng, s: (
            rng.randint(-len(s) - 1, len(s) + 1),
            rng.randint(-len(s) - 1, len(s) + 1),
            rng.choice([None, 1, 2, -1]),
        ),
        lambda bv, cls, p: bv.__delitem__(slice(p[0], p[1], p[2])),
    ),
    (
        "delitem_iterable",
        lambda rng, s: (
            (
                [rng.randrange(-len(s), len(s)) for _ in range(rng.randrange(3))]
                if s
                else []
            ),
        ),
        lambda bv, cls, p: bv.__delitem__(p[0]),
    ),
    (
        "append",
        lambda rng, s: (_random_bit_value(rng),),
        lambda bv, cls, p: bv.append(p[0]),
    ),
    (
        "extend",
        lambda rng, s: (
            rng.choice(
                [
                    _random_constructible(rng, rng.randrange(12)),
                    rng.randrange(4),  # int -> constructor -> zeros
                ]
            ),
        ),
        lambda bv, cls, p: bv.extend(_resolve(p[0], cls)),
    ),
    (
        "insert",
        lambda rng, s: (_random_index(rng, len(s)), _random_bit_value(rng)),
        lambda bv, cls, p: bv.insert(p[0], p[1]),
    ),
    (
        "pop",
        lambda rng, s: (
            rng.choice([None, _random_index(rng, len(s))]),
            rng.choice([None, "sentinel"]),
        ),
        lambda bv, cls, p: bv.pop(p[0], p[1]),
    ),
    (
        "remove",
        lambda rng, s: (rng.choice([0, 1]),),
        lambda bv, cls, p: bv.remove(p[0]),
    ),
    (
        "add",
        lambda rng, s: (_random_constructible(rng, rng.randrange(10)),),
        lambda bv, cls, p: bv + _resolve(p[0], cls),
    ),
    (
        "radd",
        lambda rng, s: (_random01(rng, rng.randrange(8)),),
        lambda bv, cls, p: p[0] + bv,
    ),
    (
        "iadd",
        lambda rng, s: (_random_constructible(rng, rng.randrange(10)),),
        lambda bv, cls, p: bv.__iadd__(_resolve(p[0], cls)),
    ),
    (
        "mul",
        lambda rng, s: (rng.randint(-1, 3),),
        lambda bv, cls, p: bv * p[0],
    ),
    (
        "imul",
        lambda rng, s: (rng.randint(-1, 3),),
        lambda bv, cls, p: bv.__imul__(p[0]),
    ),
    (
        "bitwise",
        lambda rng, s: (
            rng.choice(["__and__", "__or__", "__xor__"]),
            SameImplBV(_random01(rng, len(s) if rng.random() < 0.8 else len(s) + 1)),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(_resolve(p[1], cls)),
    ),
    (
        "shift",
        lambda rng, s: (
            rng.choice(["__lshift__", "__rshift__"]),
            rng.choice([rng.randint(-1, len(s) + 2), "1"]),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(p[1]),
    ),
    (
        "invert",
        lambda rng, s: (),
        lambda bv, cls, p: ~bv,
    ),
    (
        "reverse",
        lambda rng, s: (),
        lambda bv, cls, p: bv.reverse(),
    ),
    (
        "find_family",
        lambda rng, s: (
            rng.choice(["find", "rfind", "index", "rindex", "count"]),
            rng.choice([0, 1, 2, _random01(rng, rng.randrange(4))]),
            rng.choice([0, 0, rng.randint(-len(s) - 1, len(s) + 1)]),
            rng.choice([None, None, rng.randint(-len(s) - 1, len(s) + 1)]),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(p[1], p[2], p[3]),
    ),
    (
        "with_ends",
        lambda rng, s: (
            rng.choice(["startswith", "endswith"]),
            rng.choice(
                [
                    _random01(rng, rng.randrange(4)),
                    rng.choice([0, 1]),
                    [int(c) for c in _random01(rng, rng.randrange(3))],
                    tuple(_random01(rng, rng.randrange(3)) for _ in range(2)),
                ]
            ),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(p[1]),
    ),
    (
        "replace",
        lambda rng, s: (
            _random01(rng, rng.randrange(4)),
            _random01(rng, rng.randrange(4)),
            rng.choice([None, 0, 1, 2, -1]),
        ),
        lambda bv, cls, p: bv.replace(p[0], p[1], p[2]),
    ),
    (
        "join",
        lambda rng, s: (
            [_random01(rng, rng.randrange(5)) for _ in range(rng.randrange(4))],
        ),
        lambda bv, cls, p: bv.join(p[0]),
    ),
    (
        "partition",
        lambda rng, s: (
            rng.choice(["partition", "rpartition"]),
            SameImplBV(_random01(rng, rng.randrange(1, 4))),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(_resolve(p[1], cls)),
    ),
    (
        "strips",
        lambda rng, s: (
            rng.choice(["lstrip", "rstrip", "strip"]),
            rng.choice([None, 0, 1, 0.0, 1.0]),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(p[1]),
    ),
    (
        "pads",
        lambda rng, s: (
            rng.choice(["lpad", "rpad"]),
            rng.randint(0, len(s) + 9),
            rng.choice([0, 1, 2]),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(p[1], p[2]),
    ),
    (
        "contains",
        lambda rng, s: (
            rng.choice([0, 1, 2, 3.5, _random01(rng, rng.randrange(3)), b"\x01"]),
        ),
        lambda bv, cls, p: p[0] in bv,
    ),
    (
        "iterate",
        lambda rng, s: (),
        lambda bv, cls, p: list(bv),
    ),
    (
        "compare",
        lambda rng, s: (
            rng.choice(["__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"]),
            SameImplBV(
                _random01(rng, len(s) if rng.random() < 0.5 else rng.randrange(9))
            ),
        ),
        lambda bv, cls, p: getattr(bv, p[0])(_resolve(p[1], cls)),
    ),
    (
        "copy_forms",
        lambda rng, s: (rng.choice(["copy", "__copy__", "__Bits__"]),),
        lambda bv, cls, p: getattr(bv, p[0])(),
    ),
    (
        "deepcopy",
        lambda rng, s: (),
        lambda bv, cls, p: copy.deepcopy(bv),
    ),
    (
        "stringify",
        lambda rng, s: (rng.choice(["", "b", "o", "x", "q"]),),
        lambda bv, cls, p: format(bv, p[0]),
    ),
    (
        "to01_sep",
        lambda rng, s: (rng.choice([None, "_", " "]), rng.choice([1, 2])),
        lambda bv, cls, p: bv.to01(p[0], p[1]),
    ),
    (
        "tobase",
        lambda rng, s: (rng.choice([2, 4, 8, 10, 16, 32, 64]),),
        lambda bv, cls, p: bv.tobase(p[0]),
    ),
    (
        "tobytes_forms",
        lambda rng, s: (rng.choice([False, True]),),
        lambda bv, cls, p: (bytes(bv), bv.tobytes(), bv.to_bytes(p[0])),
    ),
    (
        "to_int",
        lambda rng, s: (rng.choice(["big", "little"]), rng.choice([True, False])),
        lambda bv, cls, p: bv.to_int(endianness=p[0], signed=p[1]),
    ),
    (
        "len_str_repr",
        lambda rng, s: (),
        lambda bv, cls, p: (len(bv), str(bv), repr(bv)),
    ),
]

CLASSMETHOD_OPS = [
    (
        "from_int",
        lambda rng: (
            rng.randint(-(2**16), 2**16),
            rng.choice([None, rng.randint(0, 40)]),
        ),
        lambda cls, p: cls.from_int(p[0], p[1]),
    ),
    (
        "from_bytes",
        lambda rng: (
            bytes(rng.randrange(256) for _ in range(rng.randrange(6))),
            rng.choice([False, True]),
        ),
        lambda cls, p: cls.from_bytes(p[0], p[1]),
    ),
    (
        "from01",
        lambda rng: ("".join(rng.choice("01_- :2") for _ in range(rng.randrange(10))),),
        lambda cls, p: cls.from01(p[0]),
    ),
    (
        "frombase",
        lambda rng: (
            "".join(
                rng.choice("0123456789abcdefABCDEFG+/") for _ in range(rng.randrange(6))
            ),
            rng.choice([2, 4, 8, 16, 32, 64, 10]),
        ),
        lambda cls, p: cls.frombase(p[0], p[1]),
    ),
    (
        "constructor",
        lambda rng: (
            rng.choice(
                [
                    None,
                    rng.randint(-2, 20),
                    "".join(rng.choice("01") for _ in range(rng.randrange(9))),
                    "0b" + "".join(rng.choice("01") for _ in range(4)),
                    "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(3)),
                    bytes(rng.randrange(256) for _ in range(rng.randrange(4))),
                    [rng.choice([0, 1]) for _ in range(rng.randrange(9))],
                    3.5,
                ]
            ),
        ),
        lambda cls, p: cls(p[0]),
    ),
]


def _apply(op_apply, bv, cls, params):
    try:
        result = op_apply(bv, cls, params)
        return (_normalize(result, cls), None)
    except Exception as exc:  # noqa: BLE001 - differential comparison
        return (None, type(exc).__name__)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_differential_random_operations(seed):
    rng = random.Random(seed)
    state01 = _random01(rng, rng.choice([0, 1, 7, 8, 9, 63, 64, 65, 200]))
    native = NativeBitVector(state01)
    speedup = SpeedupBitVector(state01)

    for step in range(600):
        # Occasionally restart from a fresh state (and keep sizes bounded).
        if len(native) > 2000 or rng.random() < 0.01:
            state01 = _random01(rng, rng.choice([0, 1, 7, 8, 9, 63, 64, 65, 200]))
            native = NativeBitVector(state01)
            speedup = SpeedupBitVector(state01)

        op_name, op_params, op_apply = rng.choice(OPS)
        # Draw parameters once, from the shared pre-op state.
        params = op_params(rng, native.to01())

        native_result, native_exc = _apply(op_apply, native, NativeBitVector, params)
        speedup_result, speedup_exc = _apply(
            op_apply, speedup, SpeedupBitVector, params
        )

        context = (
            f"seed={seed} step={step} op={op_name} params={params!r}\n"
            f"native: result={native_result!r} exc={native_exc}\n"
            f"speedup: result={speedup_result!r} exc={speedup_exc}"
        )
        assert native_exc == speedup_exc, context
        assert native_result == speedup_result, context
        assert native.to01() == speedup.to01(), context
        assert len(native) == len(speedup), context
        assert speedup._check_invariants()


@pytest.mark.parametrize("seed", [11, 12])
def test_differential_classmethods(seed):
    rng = random.Random(seed)
    for step in range(400):
        op_name, op_params, op_apply = rng.choice(CLASSMETHOD_OPS)
        params = op_params(rng)

        def run(cls):
            try:
                return (_normalize(op_apply(cls, params), cls), None)
            except Exception as exc:  # noqa: BLE001 - differential comparison
                return (None, type(exc).__name__)

        native_result, native_exc = run(NativeBitVector)
        speedup_result, speedup_exc = run(SpeedupBitVector)

        context = (
            f"seed={seed} step={step} op={op_name} params={params!r}\n"
            f"native: result={native_result!r} exc={native_exc}\n"
            f"speedup: result={speedup_result!r} exc={speedup_exc}"
        )
        assert native_exc == speedup_exc, context
        assert native_result == speedup_result, context


@pytest.mark.parametrize("length", [0, 1, 7, 8, 9, 15, 16, 17, 63, 64, 65, 1000])
def test_differential_boundary_lengths(length):
    """Serialization agreement at byte-boundary-straddling lengths."""
    rng = random.Random(length)
    s01 = "".join(rng.choice("01") for _ in range(length))
    native = NativeBitVector(s01)
    speedup = SpeedupBitVector(s01)

    assert bytes(native) == bytes(speedup)
    assert native.tobytes() == speedup.tobytes()
    assert native.to_bytes() == speedup.to_bytes()
    assert native.to_bytes(True) == speedup.to_bytes(True)
    for signed in (True, False):
        for endianness in ("big", "little"):
            assert native.to_int(endianness, signed) == speedup.to_int(
                endianness, signed
            ), (length, endianness, signed)
    assert native.to01() == speedup.to01()
    assert list(native) == list(speedup)
    assert speedup._check_invariants()
