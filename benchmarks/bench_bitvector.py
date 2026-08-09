# flake8: noqa
"""
Benchmarks the BitVector implementations against each other: the
byte-per-bit reference (`bitvector_native`), the packed pure-Python
implementation (`bitvector_speedup`), and — when bitarray is installed —
the bitarray-backed implementation that actually ships
(`bitvector_with_bitarray_speedup`).

Usage: python benchmarks/bench_bitvector.py [--sizes 1024,65536,1048576]

Each operation is timed with an auto-calibrated repeat count (best of 3).
Operations known to be quadratic in the native implementation are capped
to keep total runtime reasonable.
"""

import argparse
import random
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bytemaker.bitvector.bitvector_native import BitVector as NativeBitVector
from bytemaker.bitvector.bitvector_speedup import BitVector as SpeedupBitVector

try:
    from bytemaker.bitvector.bitvector_with_bitarray_speedup import (
        BitVector as BitarrayBitVector,
    )
except ImportError:  # bitarray not installed
    BitarrayBitVector = None

IMPLS = [("native", NativeBitVector), ("speedup", SpeedupBitVector)]
if BitarrayBitVector is not None:
    IMPLS.append(("bitarray", BitarrayBitVector))


def _time(fn, min_duration=0.05):
    """Best-of-3 auto-calibrated timing; returns seconds per call."""
    reps = 1
    while True:
        start = time.perf_counter()
        for _ in range(reps):
            fn()
        elapsed = time.perf_counter() - start
        if elapsed >= min_duration or reps >= 1_000_000:
            break
        reps *= 4
    best = elapsed
    for _ in range(2):
        start = time.perf_counter()
        for _ in range(reps):
            fn()
        best = min(best, time.perf_counter() - start)
    return best / reps


def _fmt(seconds):
    if seconds >= 1:
        return f"{seconds:8.2f} s "
    if seconds >= 1e-3:
        return f"{seconds * 1e3:8.2f} ms"
    if seconds >= 1e-6:
        return f"{seconds * 1e6:8.2f} us"
    return f"{seconds * 1e9:8.2f} ns"


def bench_ops(nbits, quadratic_cap=100_000):
    rng = random.Random(nbits)
    data = bytes(rng.randrange(256) for _ in range(nbits // 8))
    s01 = "".join(rng.choice("01") for _ in range(nbits))
    int_value = rng.getrandbits(nbits - 1) if nbits > 1 else 0

    print(f"\n=== {nbits:,} bits ===")
    header = f"{'operation':34s}" + "".join(f" {label:>11s}" for label, _ in IMPLS)
    header += "".join(f" {'nat/' + label[:3]:>9s}" for label, _ in IMPLS[1:])
    print(header)

    for name, make_op, cap in [
        ("construct from bytes", lambda cls: (lambda: cls(data)), None),
        ("construct from 01-string", lambda cls: (lambda: cls(s01)), None),
        (
            "construct from int list",
            lambda cls, bits=[int(c) for c in s01]: (lambda: cls(bits)),
            None,
        ),
        (
            "from_int",
            lambda cls: (lambda: cls.from_int(int_value, nbits)),
            quadratic_cap,
        ),
        ("bytes(bv) / tobytes", lambda cls, bv=None: (lambda: bytes(cls(data))), None),
        ("to_bytes", lambda cls: (lambda bv=cls(data): bv.to_bytes()), None),
        ("to_int", lambda cls: (lambda bv=cls(data): bv.to_int()), None),
        ("to01", lambda cls: (lambda bv=cls(data): bv.to01()), None),
        ("hex", lambda cls: (lambda bv=cls(data): bv.hex()), None),
        (
            "xor equal-length",
            lambda cls: (lambda a=cls(data), b=cls(data): a ^ b),
            None,
        ),
        ("invert", lambda cls: (lambda bv=cls(data): ~bv), None),
        ("lshift 3", lambda cls: (lambda bv=cls(data): bv << 3), None),
        (
            "slice half (unaligned)",
            lambda cls: (lambda bv=cls(data): bv[1 : nbits // 2 + 1]),
            None,
        ),
        ("concat", lambda cls: (lambda a=cls(data), b=cls(data): a + b), None),
        ("equality", lambda cls: (lambda a=cls(data), b=cls(data): a == b), None),
        ("count(1)", lambda cls: (lambda bv=cls(data): bv.count(1)), None),
        (
            "find subsequence",
            lambda cls: (lambda bv=cls(data), pat="0" * 24 + "1": bv.find(pat)),
            None,
        ),
        ("get bit (middle)", lambda cls: (lambda bv=cls(data): bv[nbits // 2]), None),
        (
            "set bit (middle)",
            lambda cls: (lambda bv=cls(data): bv.__setitem__(nbits // 2, 1)),
            None,
        ),
        (
            "append x100",
            lambda cls: (lambda bv=cls(data): [bv.append(1) for _ in range(100)]),
            None,
        ),
        ("reverse", lambda cls: (lambda bv=cls(data): bv.reverse()), None),
        (
            "replace('101','010')",
            lambda cls: (lambda bv=cls(data): bv.replace("101", "010")),
            None,
        ),
    ]:
        if cap is not None and nbits > cap:
            print(f"{name:34s} {'(skipped: quadratic in native)':>33s}")
            continue
        times = [_time(make_op(cls)) for _, cls in IMPLS]
        row = f"{name:34s}" + "".join(f" {_fmt(t)}" for t in times)
        for t in times[1:]:
            ratio = times[0] / t if t else float("inf")
            row += f" {ratio:8.1f}x"
        print(row)


_E2E_WORKER = """
import importlib
import sys, time, types
from dataclasses import dataclass

sys.path.insert(0, {repo_path!r})

# Wire the requested implementation in BEFORE anything imports bytemaker:
# bytemaker/__init__.py eagerly imports bittypes, which binds BitVector at
# module level, so patching after the fact is too late. Pre-seeding the
# backend-selection module (bytemaker.bitvector.bitvector) with a lazy
# stub makes every consumer -- including FixedLengthBitVector's base
# class -- resolve to the requested implementation from the start.
_stub = types.ModuleType("bytemaker.bitvector.bitvector")
_stub.__getattr__ = lambda name: getattr(
    importlib.import_module({impl_module!r}), name
)
sys.modules["bytemaker.bitvector.bitvector"] = _stub

from bytemaker.bittypes import Float32, SInt32, UInt8, UInt16
from bytemaker.conversions.aggregate_types import (
    from_bytes_aggregate,
    to_bytes_aggregate,
)

impl = importlib.import_module({impl_module!r})
assert sys.modules["bytemaker.bittypes.bittype"].BitVector is impl.BitVector

@dataclass
class Packet:
    a: UInt8
    b: UInt16
    c: SInt32
    d: Float32

packet = Packet(UInt8(7), UInt16(1234), SInt32(-56789), Float32(3.25))
blob = to_bytes_aggregate(packet)
assert from_bytes_aggregate(blob, Packet).b.value == 1234

reps = 1
while True:
    start = time.perf_counter()
    for _ in range(reps):
        from_bytes_aggregate(to_bytes_aggregate(packet), Packet)
    elapsed = time.perf_counter() - start
    if elapsed >= 0.4:
        break
    reps *= 4
print(elapsed / reps)
"""


def bench_library_e2e():
    """End-to-end pack/unpack through the bittypes/aggregate layer, with
    each implementation wired in inside a fresh subprocess."""
    print("\n=== library end-to-end (pack+unpack of a 4-field struct) ===")

    import subprocess

    repo_path = str(Path(__file__).resolve().parent.parent)
    impl_modules = [
        ("native", "bytemaker.bitvector.bitvector_native"),
        ("speedup", "bytemaker.bitvector.bitvector_speedup"),
    ]
    if BitarrayBitVector is not None:
        impl_modules.append(
            ("bitarray", "bytemaker.bitvector.bitvector_with_bitarray_speedup")
        )
    results = {}
    for label, impl_module in impl_modules:
        code = _E2E_WORKER.format(repo_path=repo_path, impl_module=impl_module)
        output = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        if output.returncode != 0:
            print(f"{label:>8s}: worker FAILED\n{output.stderr}")
            continue
        results[label] = float(output.stdout.strip())
        print(f"{label:>8s}: {_fmt(results[label])} per round trip")

    baseline = _time(
        lambda: struct.unpack(">BHif", struct.pack(">BHif", 7, 1234, -56789, 3.25)),
        min_duration=0.1,
    )
    print(f"{'struct':>8s}: {_fmt(baseline)} per round trip (reference floor)")
    for label in results:
        if label == "native":
            continue
        print(
            f"{label} vs native: {results['native'] / results[label]:.1f}x;"
            f" gap to raw struct: {results[label] / baseline:.0f}x"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sizes",
        default="1024,65536,1048576",
        help="comma-separated bit sizes to benchmark",
    )
    parser.add_argument("--skip-e2e", action="store_true")
    args = parser.parse_args()

    for size in (int(s) for s in args.sizes.split(",")):
        bench_ops(size)
    if not args.skip_e2e:
        bench_library_e2e()
