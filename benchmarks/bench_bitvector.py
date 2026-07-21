# flake8: noqa
"""
Benchmarks the pure-Python BitVector implementations against each other:
the byte-per-bit reference (`bitvector_native`) versus the packed
implementation (`bitvector_speedup`).

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
    print(f"{'operation':34s} {'native':>11s} {'speedup':>11s} {'ratio':>9s}")

    for name, make_op, cap in [
        ("construct from bytes", lambda cls: (lambda: cls(data)), None),
        ("construct from 01-string", lambda cls: (lambda: cls(s01)), None),
        (
            "construct from int list",
            lambda cls, bits=[int(c) for c in s01]: (lambda: cls(bits)),
            None,
        ),
        ("from_int", lambda cls: (lambda: cls.from_int(int_value, nbits)), quadratic_cap),
        ("bytes(bv) / tobytes", lambda cls, bv=None: (lambda: bytes(cls(data))), None),
        ("to_bytes", lambda cls: (lambda bv=cls(data): bv.to_bytes()), None),
        ("to_int", lambda cls: (lambda bv=cls(data): bv.to_int()), None),
        ("to01", lambda cls: (lambda bv=cls(data): bv.to01()), None),
        ("hex", lambda cls: (lambda bv=cls(data): bv.hex()), None),
        ("xor equal-length", lambda cls: (
            lambda a=cls(data), b=cls(data): a ^ b
        ), None),
        ("invert", lambda cls: (lambda bv=cls(data): ~bv), None),
        ("lshift 3", lambda cls: (lambda bv=cls(data): bv << 3), None),
        ("slice half (unaligned)", lambda cls: (
            lambda bv=cls(data): bv[1 : nbits // 2 + 1]
        ), None),
        ("concat", lambda cls: (lambda a=cls(data), b=cls(data): a + b), None),
        ("equality", lambda cls: (lambda a=cls(data), b=cls(data): a == b), None),
        ("count(1)", lambda cls: (lambda bv=cls(data): bv.count(1)), None),
        ("find subsequence", lambda cls: (
            lambda bv=cls(data), pat="0" * 24 + "1": bv.find(pat)
        ), None),
        ("get bit (middle)", lambda cls: (
            lambda bv=cls(data): bv[nbits // 2]
        ), None),
        ("set bit (middle)", lambda cls: (
            lambda bv=cls(data): bv.__setitem__(nbits // 2, 1)
        ), None),
        ("append x100", lambda cls: (
            lambda bv=cls(data): [bv.append(1) for _ in range(100)]
        ), None),
        ("reverse", lambda cls: (lambda bv=cls(data): bv.reverse()), None),
        ("replace('101','010')", lambda cls: (
            lambda bv=cls(data): bv.replace("101", "010")
        ), None),
    ]:
        if cap is not None and nbits > cap:
            print(f"{name:34s} {'(skipped: quadratic in native)':>33s}")
            continue
        native_time = _time(make_op(NativeBitVector))
        speedup_time = _time(make_op(SpeedupBitVector))
        ratio = native_time / speedup_time if speedup_time else float("inf")
        print(
            f"{name:34s} {_fmt(native_time)} {_fmt(speedup_time)} {ratio:8.1f}x"
        )


_E2E_WORKER = """
import sys, time
from dataclasses import dataclass

sys.path.insert(0, {repo_path!r})

# Wire the requested implementation in before the rest of the library
# imports it (bytemaker/__init__.py is empty, so nothing has bound it yet).
import importlib
import bytemaker.bitvector as pkg

impl = importlib.import_module({impl_module!r})
for name in ("BitVector", "BitsCastable", "BitsConstructible"):
    setattr(pkg, name, getattr(impl, name))
    setattr(sys.modules["bytemaker.bitvector.bitvector"], name, getattr(impl, name))

from bytemaker.bittypes import Float32, SInt32, UInt8, UInt16
from bytemaker.conversions.aggregate_types import (
    from_bytes_aggregate,
    to_bytes_aggregate,
)

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
    results = {}
    for label, impl_module in [
        ("native", "bytemaker.bitvector.bitvector_native"),
        ("speedup", "bytemaker.bitvector.bitvector_speedup"),
    ]:
        code = _E2E_WORKER.format(repo_path=repo_path, impl_module=impl_module)
        output = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        results[label] = float(output.stdout.strip())
        print(f"{label:>8s}: {_fmt(results[label])} per round trip")

    baseline = _time(
        lambda: struct.unpack(">BHif", struct.pack(">BHif", 7, 1234, -56789, 3.25)),
        min_duration=0.1,
    )
    print(f"{'struct':>8s}: {_fmt(baseline)} per round trip (reference floor)")
    print(
        f"speedup vs native: {results['native'] / results['speedup']:.1f}x;"
        f" gap to raw struct: {results['speedup'] / baseline:.0f}x"
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
