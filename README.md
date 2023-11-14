[![python-app](https://github.com/dem1995/bytemaker/actions/workflows/python-app.yml/badge.svg)](https://github.com/dem1995/bytemaker/actions/workflows/python-app.yml)
[![PyPI version](https://badge.fury.io/py/bytemaker.svg)](https://badge.fury.io/py/bytemaker)
[![PEP8](https://img.shields.io/badge/code%20style-pep8-orange.svg)](https://www.python.org/dev/peps/pep-0008/)
[![docs](https://readthedocs.org/projects/bytemaker/badge/?version=latest)](https://readthedocs.org/projects/bytemaker/)

# bytemaker
## What is it?
`bytemaker` is a Python 3.8-compatible zero-dependency package for byte serialization/deserialization. It ports C bitfield functionality over to Python in version 3.8 through `dataclass`-decorated class annotations and provides a convenient `Bits` class.

## What can you do with it?
`bytemaker` gives you the following:
- A `Bits` class analogous to Python's `bytes` and `bytearray` classes, but for sub-byte bit quantities. `Bits` readily supports conversion from and to both, as well as lists and bit/octet/hex strings.
- A set of `ytypes` classes, including various-sized Bit classes, various-sized Byte classes, common C types (U8, U16, U32, U64, S8, S16..., and Float16, Float32, Float64), and factories to create these and chararrays to arbitrary bitcounts. All of these can be instantiated from their respective types, derive from `Bits` (and thus can be instantiated in the same way `Bits` objects can), and can be cast into each other in additional ways as needed.
- Support for serializing/deserializing `@dataclass` annotated classes, where the annotations can be `ytypes`, Python `ctypes` (`c_uint8`, `ctypes.STRUCTURE`, etc.), or Python native types `pytypes` (`int`, `bool`, `char`, `float`). Nested types? No problem!
- Automagic support for handling any of the aforementioned objects via `aggregate_types.to_bits_aggregate` and `aggregate_types.from_bits_aggregate`.

## How do I install it?
Run `python -m pip install bytemaker`.

## Project intent
The main goal of the project is to ease development of projects working with compiled code (e.g. ROM hacking). As such, streaming features are currently deemphasized, although I may implement them at some later date. 

## Errata
At present, bytemaker assumes big-endianness (à la N64). Full support for reading from and writing to little-endian ROMs will come very soon.
`ctypes` support currently assumes development is done on a little-endian machine. This is the vast, vast, vast majority of consumer hardware today, unless you run a bi-endian machine and have set it to big-endian mode.