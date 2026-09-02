# bytemaker
[![python-app](https://github.com/dem1995/bytemaker/actions/workflows/testing.yml/badge.svg)](https://github.com/dem1995/bytemaker/actions/workflows/testing.yml)
[![codecov](https://codecov.io/gh/dem1995/bytemaker/graph/badge.svg?token=O4MX7I0LQH)](https://codecov.io/gh/dem1995/bytemaker)
[![PyPI version](https://badge.fury.io/py/bytemaker.svg)](https://badge.fury.io/py/bytemaker)
[![PEP8](https://img.shields.io/badge/code%20style-pep8-orange.svg)](https://www.python.org/dev/peps/pep-0008/)
[![Licence - MIT](https://img.shields.io/badge/licence-MIT-750014)](https://github.com/dem1995/bytemaker/blob/main/LICENCE.md)
[![docs](https://readthedocs.org/projects/bytemaker/badge/?version=latest)](https://readthedocs.org/projects/bytemaker/)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/dem1995/bytemaker/main?labpath=binder%2Fbinder.ipynb)

## What is it?
bytemaker is a Python 3.8+ library for C-style binary records and bit manipulation, built for working with compiled-code data — ROM hacking, firmware, save files, wire formats. Declare a record's layout once, C-bitfield style, and get validated plain-value fields, packing/parsing, game-text codecs, and bulk decoding.

## Quickstart

```python
from bytemaker import Struct, String, u4, u6, u8, u16

# char name[4] with a game text table; the terminator cut and pad strip
# happen at the byte layer, before decoding
MonName = String.of(
    nbytes=4,

    encoding={0x80: "A", 0x81: "B", 0xE1: "[PK]"},

    pad=0x50,

    terminator=0x50,
)

class Monster(Struct, endian="little"):
    name:    MonName

    species: u8

    hp:      u16

m = Monster(name="A[PK]", species=25, hp=35)
m.pack()                   # b'\x80\xe1PP\x19#\x00'
Monster.parse(m.pack())    # Monster(name='A[PK]', species=25, hp=35)

class TileAttr(Struct, endian="big"):   # sub-byte fields, C-bitfield style
    palette:  u4

    priority: u6

    bank:     u6

t = TileAttr(palette=3, priority=40, bank=12)
t.priority + 40            # 80 -- fields are plain ints; C integer promotion
t.priority = 200           # narrows AT THE STORE, like a C bitfield: 200 & 0x3F -> 8
f = t.sizedview.priority   # live width-carrying handle: f.num_bits == 6,
                           # f.bits is a write-through view, f.boxed() detaches a UInt6
```

- **Fields hold plain Python values** (`int`, `float`, `str`, `bytes`) — hashable, printable, `json`-able. Stores narrow (ints), validate (text/bytes), or coerce (floats), C-style; opt into `-Wconversion`-style checked stores with `NarrowingConfig.warn = True`.
- **Any width works**: `from bytemaker import u31` mints a 31-bit unsigned field alias on the fly. The package ships type information (`py.typed`); fields read as `int` to type checkers.
- **Text fields** speak Python codecs (`"shift-jis"`), `.tbl`-style game tables (`TableString`: longest-match, multi-byte control codes like `"[PK]"`), or custom `(encode, decode)` pairs — sized in bytes (`nbytes=`) or characters (`nchars=`, when the codec has a fixed bytes-per-char).
- **Bulk decoding**: `Monster.plan.iter_tuples(buf)` streams records as plain tuples with no per-field object materialization — `struct`-module speed on byte-aligned layouts.

## What else is in the box?
- `BitVector` — a `bytearray` analog for bit quantities, with slicing, searching, and bitwise operations. Pure-Python by default; installs a C-backed implementation with the `[speedups]` extra. `FixedLengthBitVector` is its width-locked sibling (it backs the live `.bits` views).
- `BitTypes` boxes — `UInt8`…`UInt64`, `SInt8`…`SInt64`, `Float16/32/64`, the `String` family, and `Buffer` — value+bits pairs with C promotion arithmetic and live, width-locked `.bits` handles. Any bit width via `specialize`.
- `bytemaker.spaces` — the address-space layer. A `Space` maps a buffer at a base address and owns its byte order, so scalar reads never guess and no declaration repeats it. A `Space` can also describe an address plane with no bytes behind it, which is what you need when the image does not exist yet, or when its bytes are arriving from a running game. An `Entry` declares one mapped thing: an address, a codec, and how far it runs. Entries derive further entries, so `enemies.item(54).field("soul_rate")` addresses one field of one row through the compiled layout rather than a hand-counted `+0x12`. A `Patch` holds edits as a value. You can verify a patch against the bytes it was built from, invert it, compose it with another feature's edits, or export it as IPS. A write can state the value it expects to replace, record without mutating, or update the buffer and record at the same time. `space.coverage(...)` reports what a map claims, what it double-claims, and what it leaves unaccounted for. Typed `Ptr` fields provide `deref()`, and the audit checks where each pointer lands.
- The legacy `@dataclass` aggregate API (`bytemaker.conversions.aggregate_types`: `to_bytes_aggregate`, `from_bytes_aggregate`, …) serializes dataclasses annotated with BitTypes, Python `ctypes` (`c_uint8`, `ctypes.Structure`, …), or native types (`int`, `float`, `str`), including nested ones. It predates `Struct` and remains supported.

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
- **The `bit_order` default now follows `endian`.** A `Struct` declared `endian="big"` allocates bitfields MSB-first by default (little-endian stays LSB-first), matching C bitfield allocation on a target of the same endianness — so a big-endian format's natural declaration (`length: u4` then `disp: u12` for a GBA LZ77 token) parses right without stating `bit_order="msb"`. Explicit `bit_order` is unchanged and wins; a big-endian sub-byte record that relied on the old implicit LSB-first default must now say `bit_order="lsb"`. Found porting cvaos's LZ77 codec, where the old default parsed the token wrong silently.
- `Struct` field names that would shadow the Struct API (`pack`, `plan`, the `_bm_` prefix, …) are rejected at class definition with `PlanCompileError`; previously they silently broke serialization at use time. Leading-underscore padding fields (`_reserved`) remain legal.
- `Buffer.value` assignment now length-validates (previously it bypassed validation entirely).
- **`String` boxes with whole-byte widths now pad**: short content is padded to width on encode (class-configurable `pad` byte, default `0x00`) and trailing pad is stripped on decode, matching C's `char name[8] = "AB"` — previously any non-exact-width value raised. Set `pad=None` for the old exact-width behavior. Overflow still raises (opt into `truncate=True` for code-unit-safe clipping).
- **`BitVector` construction always copies byte-like sources.** `BitVector(bytes | bytearray | memoryview)` now yields an independent, writable, resizable vector on every backend. Previously the bitarray-backed (default) backend zero-copy imported them — `bytes` gave a silently *read-only* vector (writes raised far from the construction site), `bytearray` gave a *live two-way alias* that also resize-locked the caller's object, and either way the vector itself could not be resized; the pure-Python backends copied all along, so behavior depended on whether an optional dependency was installed. This also matches `bitarray`'s own positional-source behavior. `memoryview` sources were previously consumed as *iterables of bit values* (each byte one bit; bytes > 1 raised) — they are now byte sources like `bytes`/`bytearray`. The explicit **`buffer=`** keyword remains the one sharing spelling, with *may-share* semantics: the bitarray backend genuinely shares (read-only for immutable sources; live for `bytearray`/`mmap`, resize-locking the source), the pure backends copy — never rely on independence through `buffer=`.
- **`Array` decodes scalars to plain values** — the one decoded-scalar rule, completing what `Struct` fields started: `(UInt16 * 3).parse(b)` returns `[1, 2, 65535]` (plain `int`s), not boxed `UInt16` instances; String elements decode to `str`, Buffer elements to `bytes`. Width lives in the schema (`arr.element`); re-box on demand with the constructor cast, `arr.element(v)`. `pack` accepted plain values all along. Scalar arrays now decode through the same aligned fast path design as `Plan` (whole-array `struct` call — ~195× faster than the old boxed parse for a 1024-element table), with a config-aware fallback for exotic `SignedConfig` formats.
- **String/Buffer array elements are no longer byte-swapped** under `endian="little"` (in either direction): text/bytes have no byte order — stream order, as in the plan engine and C `char[]`. `endian` governs numeric elements only.
- **Removed the bit-numbered named-width zoos**: all `StrN` (`Str1`–`Str512`) and all `BufferN` (`Buffer1`–`Buffer1024`) classes are gone. The non-whole-byte `StrN` were unusable by construction (UTF-8 output is whole bytes), and the rest were standing misreads — `Str16`/`Buffer16` read as 16 *bytes* (the C `char name[16]` / `uint8_t buf[16]` count) but meant 16 *bits*. Declare text/bytes fields with the byte-counted factories instead: `String.of(N)` / `UTF8String.of(N)` / `Buffer.of(N)`; sub-byte and odd-width Buffers stay available via the bit-counted `Buffer.specialize(num_bits)`.

#### Major changes
- **`bytemaker.spaces` — mapping a binary, not just describing a record.** A `Struct` says what a record looks like and nothing about where it lives. Every project that maps a ROM, a save file, or a firmware image therefore rewrites the same three things: subtract the base address, slice, and decide how the table ends. That code now lives here.

  A `Space` is a buffer at a base address, and it owns the byte order so scalar reads never guess. Passing `None` with `size=` instead of bytes gives the same address plane with nothing behind it, which is what building writes for an image you do not have yet requires, and what describing a running game's memory requires. Extents are values rather than conventions — `count(n)`, `until(sentinel)`, `through(last)`, `unknown(note)` — so "how long is it" stops being a comment.

  An `Entry` is a declaration you can write with no buffer in hand, which keeps a map module importable without the binary. Entries derive further entries: `table.item(54)` is a row, and `.field("soul_rate")` is one field of it, addressed through the compiled layout so a magic offset cannot go stale.

  `Patch` turns edits into a value you can verify, invert, and export as IPS. Composing two patches with `|` raises `PatchConflict` when they disagree about a byte, instead of silently letting the later one win. Writes come in three shapes because builds do: edit an image you have; build blind edits for one you do not, where `old` is optional and the patch refuses to invert rather than guessing; or record alongside the mutation with `space.recording(patch)`, so later steps read what earlier ones wrote. A write may also state `expect=`, the value it means to replace, checked immediately against bytes in hand or carried into the patch and checked at apply time.

  `space.coverage(...)` reports what a map claims, what it double-claims, what it leaves unaccounted for, and where its typed `Ptr` fields land, verifying record type and alignment wherever a pointer declares its pointee.

  For a live target the library never performs I/O and never becomes async. `entry.request()` returns the `(offset, nbytes)` pair a transport needs, `entry.parse(data)` decodes the bytes it returns, and `patch.guards()` yields the `(offset, expected, new)` triples a compare-and-swap needs.
- **`introspect.offset_of` / `span_of`** answer where a field sits inside its record and how far it runs, from the same compiled layout the codec uses, which is the typed replacement for a hand-counted `+0x0A`. The compiled `Plan` is deliberately not exported from the package root: it is the compiler's output, reachable as `cls.plan` when you want it, and `introspect` answers the questions callers actually have.
- **Type-checker-friendly field declarations, two styles.** Every field kind can be spelled so a type checker (mypy/pyright) sees the plain value type it reads as. *Annotation-carried:* `hp: u8` (→ `int`), bare `child: RGB` for nested Structs, `colors: Annotated[list[int], UInt16 * 8]` for arrays, `name: Annotated[str, String.of(...)]` for text. *Field-specifier* (new, pydantic/msgspec-style, via `dataclass_transform`): the annotation is the plain type and the bytemaker type rides the RHS — `hp: int = field(UInt8)`, `name: str = field(String.of(nbytes=4, encoding=MON_TABLE))`, `data: bytes = field(Buffer.of(nbytes=8))`, `colors: list[int] = array(UInt16, 8)`, with defaults via `field(..., default=…)`. Both produce identical runtime and identical checker types, and coexist in one record. A field-specifier's plain annotation is checked against its wire type at class definition (`hp: str = field(UInt8)` is a `PlanCompileError`, not a silent checker lie; `Any` opts out). The terse runtime shortcuts (`name: MonName`, `colors: UInt16 * 8`) still work but aren't valid *types* to a checker — an expression or a call in annotation position can't be, by language design. `test/_typing_repro.py` is the durable mypy contract.
- **Top-level public API.** `from bytemaker import Struct, String, u8, BitVector, …` — the package root was previously empty. It now exports the curated `Struct`-first surface (records, the standard-width boxes, the text machinery, `BitVector`/`FixedLengthBitVector`, `NarrowingConfig`/`NarrowingWarning`, `PlanCompileError`), resolves any-width `uN`/`sN` field aliases lazily (`from bytemaker import u31`), and carries `__version__`. Submodule imports are unchanged; the legacy aggregate API stays at `bytemaker.conversions.aggregate_types`.
- **Text and bytes fields in `Struct`** — the C `char name[N]` idiom, with codecs. `String.of(nbytes=..., encoding=..., pad=..., terminator=..., strip=..., truncate=..., errors=...)` mints a fixed-size text field type: `encoding` may be a Python codec name (`"ascii"`, `"shift-jis"`), a `.tbl`-style mapping (`{0x80: "A", 0xE1: "[PK]"}` — the new `TableString`, longest-match in both directions), or an `(encode, decode)` pair. Fields hold plain `str`; overflow raises at the store; on parse, the terminator cut and pad strip happen at the byte layer *before* decoding (garbage after a terminator is normal in ROM data; 0xFF pads aren't valid UTF-8). `Buffer` fields hold plain exact-length `bytes`. Both plan tiers support them (`struct`'s `Ns` when aligned; opaque bit runs in shift/mask records with sub-byte siblings), and `sizedview` works on them unchanged.
- **Array fields — the C `uint16_t vals[N]` idiom.** An `Array` may now be a `Struct` field: `colors: UInt16 * 8` (or `Array.of(UInt16, 8)`). Elements are numeric (`Int`/`Float`) or nested `Struct`; the field reads as a plain list. The slot is a live, fixed-length narrowing list, so `s.colors[0] = 70000` narrows C-style to `4464` in place (a read never returns a value `pack()` would not serialize) and length-changing mutation (`append`, `del`, resizing slice) raises. Whole assignment snapshots (the caller's list is never aliased). An array field inherits the record's byte order (like a C array); an explicitly-endianed `Array.of(..., endian=...)` keeps its own, like a nested `Struct`. (Text/bytes-element and 2-D array fields are deferred — they raise a clear `PlanCompileError` naming the fallback.) For type-checker visibility, spell the field `Annotated[list[int], UInt16 * 8]` or `colors: list[int] = array(UInt16, 8)` (see "Type-checker-friendly field declarations" above); the terse `UInt16 * 8` works at runtime but isn't a valid type to a checker.
- **`Struct.sizedview`** — a live, width-carrying view of a record's fields. `t.sizedview.field` returns a `BoundField` handle with C lvalue semantics: reads promote to plain values, stores narrow, `f.bits` is a live write-through bits channel with width guards, `f.boxed()` detaches a snapshot. Handles compare by value and are unhashable; `__index__` and the bitwise operators are deliberately absent on handles (name the plane: `f.value & m` or `f.bits & bv`).
- **Byte-counted declaration layer for the array-like family.** Numeric widths stay bit-counted (`UInt4`, `u31` — C's `uintN_t`); text/bytes field sizes are byte-counted (C's `char name[N]` / `uint8_t buf[N]`), with one rule: `.of()` is the field door and counts **bytes**, `specialize()` is the box door and counts **bits**. `String.of` accepts exactly one of `nbytes=` (the wire ground truth) or `nchars=` — twin names, both **keyword-only**, so every declaration names its unit and knowing one spelling gives you the other (a bare `of(16)` would be the same misread the zoos had). `nchars=` is sugar for `nchars × bytes_per_char`, legal only when the codec has a fixed, known bytes-per-char: derived for table codecs (every key one wire-unit length, every value one character), declared via `bytes_per_char=` (or an inherited class attribute) otherwise, and refused loudly at mint time for variable-width codecs (UTF-8, Shift-JIS, tables with control codes). `bytes_per_char` is sizing metadata, never a safety invariant — the wire contract and the store-time length check stay byte-based. When known, it also makes decode-side terminator/pad handling work in whole character units (a NUL-padded UTF-16 field strips `b"\x00\x00"` pairs and never splits a code unit). `Buffer.of(nbytes=N)` is the matching bytes-payload door (`nbytes` keyword-required there too).
- New ordering comparisons (`<`, `<=`, `>`, `>=`) on `Int` and `Float` boxes (value-based, like `==`); previously they did not exist.
- `Int.__index__` — boxes work anywhere a plain int does (`hex()`, list indexing, `range()`), including assignment into `Struct` fields, which unwraps and narrows at the store.
- `BitType.__format__` — a format spec formats the value (`f"{UInt6(40):02x}"` → `'28'`); no spec keeps the sized display.
- `BitType.__Bits__` — `BitVector(bittype)` and every `BitsConstructible` site now accept boxes. The protocol result is live and width-locked; `BitVector(...)` casts are independent copies.
- **Opt-in checked stores**: `NarrowingConfig.warn = True` (or `BYTEMAKER_WARN_NARROWING`) emits `NarrowingWarning` whenever an integer store actually changes the assigned value — the `-Wconversion` analog. Default remains silent C-style narrowing.
- `FixedLengthBitVector` — a `BitVector` whose length is invariant (backs BitType storage; usable directly).
- The package now ships type information (`py.typed`; `bitvector.pyi` was previously missing from wheels), and the box operator families carry inline annotations matching the C-promotion semantics: type checkers see `UInt8(1) + 2` as `int`, `u + 2.5` as `float`, `u / 2` as `float`, bitwise as int-only, ordering as `bool`, and `u += 1` as type-preserving — and reject `u + "x"` like the runtime does. `BoundField` is `Generic[V]` for explicitly-annotated handles.

#### Bugfixes
- **Every `Struct` field reported a type error in VS Code.** `ClassVar` reached `structs.py` through the internal `typing_redirect` module, and pyright's `dataclass_transform` field collection does not follow a re-exported alias of it — so `Struct`'s own class attributes (`plan`, `num_bits`, `_bm_fields`, …) were collected as fields, the synthesized `__init__` grew eight phantom parameters ahead of the real ones, and each declared field reported *"fields without default values cannot appear after fields with default values"*. `ClassVar` now comes straight from `typing` (and `typing_redirect` no longer offers it). mypy always read this correctly, which is why the mypy gate never saw it.
- **The new `Struct`/`Plan`/`Array` system is now uniformly two's-complement and ignores the legacy `SignedConfig` global.** Previously a standalone `Array` of a signed type honored `SignedConfig.signed_int_format` (signed-magnitude/ones-complement) while the same schema used as a `Struct` field silently stayed two's complement — the identical `SInt16` decoding `0x8005` as `-5` standalone but `-32763` as a field under a non-default global. The new system now never consults `SignedConfig` (it governs only the legacy aggregate/BitType layer), so standalone and field decoding agree byte-for-byte. Two's complement is the universal default, so this is observable only if you had explicitly set the exotic global.
- **`Float` fields did not narrow at the store.** A `Float32` field stored the full-precision Python double, so `s.v = 0.1` read back `0.1` while `pack()` serialized (and `parse()` read back) the 32-bit `0.10000000149011612` — a read that lied about the wire value. Float fields now narrow through their codec at assignment, like every other field (`Float64` is a no-op at native width).
- **Non-IEEE / non-standard-width floats were silently mis-coded.** A `BFloat16` field packed 1.5 as `3e00` (IEEE half) instead of its own `3fc0`, because the width-keyed struct letter was used regardless of the type's actual codec; a 24-bit `FP24` array element decoded its float bytes as a raw integer, corrupting parse/pack round-trips. Only IEEE `Float16`/`Float32`/`Float64` ride a struct codec; every other `Float` (mismatched letter *or* no letter at all) is now rejected loudly at class definition (`PlanCompileError`) in both Struct fields and Array elements, and the legacy aggregate shortcut routes them through the type's own codec instead of the struct fast path.
- `BitVector.from_bytes` and `BitVector.from_chararray` returned read-only, non-resizable vectors on the bitarray backend (they constructed through the internal buffer-import path); both now return normal vectors on every backend.
- `String.codepoint_changes` substitution regexes now match longest-first in both directions; previously a shorter table key (`"A"`) permanently shadowed longer ones (`"AB"`), silently corrupting multi-character table entries.
- Two aggregate error messages referenced a nonexistent `BitVector.num_bits` attribute, raising `AttributeError` before the intended error.
- **`__version__` could report a different installation's version.** The package resolved its version through `importlib.metadata` by distribution name, which says nothing about which files were imported, so a source checkout imported ahead of an older installed release reported that release's version. The literal version is now the default, and a distribution's version replaces it only when that distribution locates its `bytemaker` package at the imported copy's directory.

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
