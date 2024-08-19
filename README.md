# bytemaker
[![python-app](https://github.com/dem1995/bytemaker/actions/workflows/ci.yml/badge.svg)](https://github.com/dem1995/bytemaker/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/bytemaker.svg)](https://badge.fury.io/py/bytemaker)
[![PEP8](https://img.shields.io/badge/code%20style-pep8-orange.svg)](https://www.python.org/dev/peps/pep-0008/)
[![Licence - MIT](https://img.shields.io/badge/licence-MIT-750014)](https://github.com/dem1995/bytemaker/blob/main/LICENCE.md)
[![docs](https://readthedocs.org/projects/bytemaker/badge/?version=latest)](https://readthedocs.org/projects/bytemaker/)

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
### Version 0.9.0
`Bits` is now `BitVector`. Its API has been changed to be much more similar to `bytearray`. To that end, inline methods and alternative syntaxes have been winnowed where possible.

`ytypes` are now `BitTypes`, and, rather than extending from `Bits`, now contain `BitVectors`. This change was made so that, in the long run, uint:UInt8 + sint:SInt8 wouldn't be the same as concatenation, and so that str24[1] would grab the second element.

`BitTypes` now have full support for endianness when casting to `bytes`. Note that while the types have endianness, their underlying bit representations do not (because that wouldn't make much sense!). Usage of `ctypes` still assumes development is done on a little-endian machine. This is the vast, vast, vast majority of consumer hardware today, unless you run a bi-endian machine and have set it to big-endian mode. This may not change; the remaining primary use of `ctypes` is for non-chararray array types (to be resolved in a near-future version).

Upcoming deprecations:
(any BitType)`.to_bits()` and (any BitType)`.from_bits()`. This behavior should instead be replicated by (any BitType)`.bits` and (any BitType)`(bits)`
### Version 0.8.3
