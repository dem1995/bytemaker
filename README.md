# bytemaker
[![python-app](https://github.com/dem1995/bytemaker/actions/workflows/testing.yml/badge.svg)](https://github.com/dem1995/bytemaker/actions/workflows/testing.yml)
[![codecov](https://codecov.io/gh/dem1995/bytemaker/graph/badge.svg?token=O4MX7I0LQH)](https://codecov.io/gh/dem1995/bytemaker)
[![PyPI version](https://badge.fury.io/py/bytemaker.svg)](https://badge.fury.io/py/bytemaker)
[![PEP8](https://img.shields.io/badge/code%20style-pep8-orange.svg)](https://www.python.org/dev/peps/pep-0008/)
[![Licence - MIT](https://img.shields.io/badge/licence-MIT-750014)](https://github.com/dem1995/bytemaker/blob/main/LICENCE.md)
[![docs](https://readthedocs.org/projects/bytemaker/badge/?version=latest)](https://readthedocs.org/projects/bytemaker/)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/dem1995/bytemaker/main?labpath=binder%2Fbinder.ipynb)

## What is it?
bytemaker is a Python 3.8-compatible library for bit-manipulation and byte serialization/deserialization. It brings C bitfield functionality over to Python version 3.8+. To that end, it provides methods and types for converting @dataclass-decorated classes.

## What can you do with it?
- A `BitVector` class analogous to Python's `bytearray` class, but for sub-byte bit quantities. `BitVector` supports all the methods you'd expect to have in a bit-centric `bytearray` with a few extras, to boot.
- A set of `BitTypes` classes, including various-sized buffers, unsigned/signed ints, floats, and strings, that have underlying `BitVector` representations.
- Support for serializing/deserializing `@dataclass` annotated classes, where the annotations can be `ytypes`, Python `ctypes` (`c_uint8`, `ctypes.STRUCTURE`, etc.), or Python native types `pytypes` (`int`, `bool`, `char`, `float`). Nested types? No problem!
- Automagic support for handling any of the aforementioned objects via `aggregate_types.to_bits_aggregate` and `aggregate_types.from_bits_aggregate`.

## How do I install it?
Run `python -m pip install bytemaker`.

For faster, C-backed bit manipulation, install with the optional [bitarray](https://pypi.org/project/bitarray/) dependency by running `python -m pip install bytemaker[speedups]` instead. Without it, bytemaker uses a pure-Python `BitVector` implementation with identical behavior.

## Project intent
The main goal of the project is to ease development of projects working with compiled code (e.g. ROM hacking). As such, streaming features are currently deemphasized, although I may implement them at some later date.

## Changelog
### Version 0.13.0 (unreleased)
#### Breaking changes
- **BitType arithmetic now follows C integer promotion.** Binary operators on `Int` and `Float` boxes compute on plain values at full width and return **plain** `int`/`float` — no more wrap-at-operator (`UInt6(40) + 40` is `80`, not `UInt6(16)`; `Float16` arithmetic no longer re-encodes mid-expression). C never wraps mid-expression; narrowing happens only at stores and casts. The cast spelling is the constructor: `UInt8(a + b)` wraps exactly like `(uint8_t)(a + b)`. The bitwise family and shifts promote too (in C, even `~uint8_t` is an `int`); the width-preserving bit-plane spelling is on `.bits`. Compound assignment (`u += 1`) computes full-width and narrows back into the box's own width, preserving its type — exactly C's `a += b`. Floats refuse bitwise operators (as in C). Division on boxes now works (previously `TypeError`).
- **Bits handles are live and width-locked.** `bittype.bits` hands out live storage: index and length-preserving slice writes mutate the box in place; length-changing mutation (`append`, `del`, `+=`, resizing slice writes) raises `ValueError` instead of silently corrupting the box's width. Assigning `bittype.bits = bv` snapshots `bv` into locked storage (the caller's vector never becomes a hidden alias — including `bytes`/`bytearray` sources, which the bitarray backend would otherwise buffer-import in place). Struct-packed BitTypes previously had silently *read-only* bits storage on the bitarray backend; writes now work for every box. The assignment width check now measures the *constructed* bit width rather than `len(source)`, so byte and `"0x…"` string sources are measured in the bits they produce: `u16.bits = b"\x12\x34"` works (previously `ValueError`: `len` counted 2 bytes against 16 bits).
- Aggregate (de)serialization raises `ValueError`/`TypeError` instead of bare `Exception` for size/length mismatches and unsupported unit types.
- `Struct` field names that would shadow the Struct API (`pack`, `plan`, the `_bm_` prefix, …) are rejected at class definition with `PlanCompileError`; previously they silently broke serialization at use time. Leading-underscore padding fields (`_reserved`) remain legal.
- `Buffer.value` assignment now length-validates (previously it bypassed validation entirely).
- **`String` boxes with whole-byte widths now pad**: short content is padded to width on encode (class-configurable `pad` byte, default `0x00`) and trailing pad is stripped on decode, matching C's `char name[8] = "AB"` — previously any non-exact-width value raised. Set `pad=None` for the old exact-width behavior. Overflow still raises (opt into `truncate=True` for code-unit-safe clipping).
- Removed `Str1`–`Str7` and `Str9`–`Str15`: a UTF-8 encoding always produces whole bytes, so a non-whole-byte-width string class can never hold any encoded value; all were unusable by construction. (`Str8`, `Str16`, … remain.)

#### Major changes
- **Text and bytes fields in `Struct`** — the C `char name[N]` idiom, with codecs. `String.of(chars, encoding=..., pad=..., terminator=..., strip=..., truncate=..., errors=...)` mints a fixed-size text field type: `encoding` may be a Python codec name (`"ascii"`, `"shift-jis"`), a `.tbl`-style mapping (`{0x80: "A", 0xE1: "[PK]"}` — the new `TableString`, longest-match in both directions), or an `(encode, decode)` pair. Fields hold plain `str`; overflow raises at the store; on parse, the terminator cut and pad strip happen at the byte layer *before* decoding (garbage after a terminator is normal in ROM data; 0xFF pads aren't valid UTF-8). `Buffer` fields hold plain exact-length `bytes`. Both plan tiers support them (`struct`'s `Ns` when aligned; opaque bit runs in shift/mask records with sub-byte siblings), and `sizedview` works on them unchanged.
- **`Struct.sizedview`** — a live, width-carrying view of a record's fields. `t.sizedview.field` returns a `BoundField` handle with C lvalue semantics: reads promote to plain values, stores narrow, `f.bits` is a live write-through bits channel with width guards, `f.boxed()` detaches a snapshot. Handles compare by value and are unhashable; `__index__` and the bitwise operators are deliberately absent on handles (name the plane: `f.value & m` or `f.bits & bv`).
- New ordering comparisons (`<`, `<=`, `>`, `>=`) on `Int` and `Float` boxes (value-based, like `==`); previously they did not exist.
- `Int.__index__` — boxes work anywhere a plain int does (`hex()`, list indexing, `range()`), including assignment into `Struct` fields, which unwraps and narrows at the store.
- `BitType.__format__` — a format spec formats the value (`f"{UInt6(40):02x}"` → `'28'`); no spec keeps the sized display.
- `BitType.__Bits__` — `BitVector(bittype)` and every `BitsConstructible` site now accept boxes. The protocol result is live and width-locked; `BitVector(...)` casts are independent copies.
- **Opt-in checked stores**: `NarrowingConfig.warn = True` (or `BYTEMAKER_WARN_NARROWING`) emits `NarrowingWarning` whenever an integer store actually changes the assigned value — the `-Wconversion` analog. Default remains silent C-style narrowing.
- `FixedLengthBitVector` — a `BitVector` whose length is invariant (backs BitType storage; usable directly).
- The package now ships type information (`py.typed`; `bitvector.pyi` was previously missing from wheels).

#### Bugfixes
- `String.codepoint_changes` substitution regexes now match longest-first in both directions; previously a shorter table key (`"A"`) permanently shadowed longer ones (`"AB"`), silently corrupting multi-character table entries.
- Two aggregate error messages referenced a nonexistent `BitVector.num_bits` attribute, raising `AttributeError` before the intended error.

### Version 0.11.0
(11 June 2026)
#### Major changes
- bitarray is now an optional dependency. bytemaker includes a pure-Python `BitVector` implementation that is used automatically when bitarray is not installed; install `bytemaker[speedups]` to get the faster, C-backed bitarray implementation. Both implementations conform to the behavior specified in `bitvector.pyi` and are exercised by a shared, parametrized test suite.

#### Bugfixes
- Fixed `BitVector.from01` raising `AttributeError` for sequences of `"0"`/`"1"` characters rather than strings
- Fixed slice and index-list assignment raising `TypeError` for `str` (and other `BitsConstructible`) values
- Fixed `BitVector.replace` never terminating when `old` is empty
- Fixed construction from `BitsCastable` objects padding sub-byte `__Bits__` results up to whole bytes

### Version 0.10.2
(1 June 2026)
#### Bugfixes
- Fixed aggregate (de)serialization raising `NameError` for dataclasses defined under `from __future__ import annotations` (PEP 563). Field type annotations are now resolved with `typing.get_type_hints` in the defining module's namespace instead of a bare `eval` in bytemaker's namespace, so stringized annotations such as `"SInt16"` resolve correctly in `count_bits_in_aggregate_type`, `to_bits_aggregate`, `from_bits_aggregate`, `to_bytes_aggregate`, and `from_bytes_aggregate`.

### Version 0.10.1
(13 April 2026)
#### Breaking changes
- Replaced `reverse_endianness: bool` parameter with `endianness: Literal["big", "little"] = "big"` across all conversion functions (`to_bytes_individual`, `from_bytes_individual`, `to_bytes_aggregate`, `from_bytes_aggregate`, `bytes_to_bittype`, `bytes_to_pytype`, `ctype_to_bytes`, `bytes_to_ctype`, `ctype_to_bits`, `bits_to_ctype`, `pytype_to_bytes`). The old boolean was relative and had inconsistent defaults. The new parameter is absolute, self-documenting, and matches Python conventions (`int.from_bytes` byteorder).
- `StructPackedBitType` now stores bits in canonical big-endian order internally. Endianness is applied only at the bytes boundary by `BitType.__bytes__()`. This matches the stated design: "while the types have endianness, their underlying bit representations do not."
- For ctypes, endianness reversal now checks `endianness != sys.byteorder` instead of a hardcoded boolean, making it correct on both little-endian and big-endian platforms.

### Version 0.9.3
(12 April 2026)
#### Bugfixes
- Made the conversions subpackage exposed
- Fixed missing return statements in `String.codepoint_changes` and `String._reverse_codepoint_changes` properties (first call always returned None)
- Fixed `to_bytes_individual` calling nonexistent `BitType.to_bytes()` method
- Fixed `from_bytes_individual` passing unsupported `reverse_endianness` parameter to `bytes_to_bittype` and `bytes_to_pytype`
- Fixed double endianness reversal in `from_bytes_aggregate`
- Fixed `from_bytes_aggregate` using bit counts to slice byte objects (e.g. taking 32 bytes for a 32-bit field)
- Fixed missing `field_type` assignment in `from_bytes_aggregate` dataclass field loop
- Fixed `count_bytes_in_unit_type` using wrong ceiling division
- Fixed `StructPackedBitType.value` getter ignoring its own padding for non-multiple-of-8 bit types
- Fixed `StructPackedBitType.__bytes__` applying endianness reversal on top of struct packing, which already handles endianness
- Fixed `to_bytes_aggregate` crashing on certain nested dataclasses

#### Other
- Replaced debug `print()` statements in `BitVector.from_chararray` with `logging.debug()`

### Version 0.9.2
(29 August 2024)
#### Bugfixes
pyproject.toml did not include subpackages for PyPi, so importing from PyPi was failing to include bitvector or bittypes

#### Other
Relaxed typechecking of inputs in bitvector.py from Literal[0, 1] to int when in sequences.
This change allows users to use e.g. [0] * 5 without typecheckers having problems.

Removed some outdated references to BitArray in BitVector.pyi.

### Version 0.9.1
Added magic methods to BitTypes classes.
Removed BitTypes' `__hash__` functionality
Modified BitTypes' `__repr__` to include endianness

### Version 0.9.0
`Bits` is now `BitVector`. Its API has been changed to be much more similar to `bytearray`. To that end, inline methods and alternative syntaxes have been winnowed where possible.

`ytypes` are now `BitTypes`, and, rather than extending from `Bits`, now contain `BitVectors`. This change was made so that, in the long run, uint:UInt8 + sint:SInt8 wouldn't be the same as concatenation, and so that str24[1] would grab the second element.

`BitTypes` now have full support for endianness when casting to `bytes`. Note that while the types have endianness, their underlying bit representations do not (because that wouldn't make much sense!). ~~Usage of `ctypes` still assumes development is done on a little-endian machine.~~ As of v0.10.1, ctypes conversions use `sys.byteorder` to detect the platform endianness, so they work correctly on both little-endian and big-endian machines.

Upcoming deprecations:
(any BitType)`.to_bits()` and (any BitType)`.from_bits()`. This behavior should instead be replicated by (any BitType)`.bits` and (any BitType)`(bits)`
### Version 0.8.3
