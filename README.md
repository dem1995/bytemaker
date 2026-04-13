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

## Project intent
The main goal of the project is to ease development of projects working with compiled code (e.g. ROM hacking). As such, streaming features are currently deemphasized, although I may implement them at some later date.

## Changelog
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
