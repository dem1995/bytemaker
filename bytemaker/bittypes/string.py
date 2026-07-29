from __future__ import annotations

import re
from abc import abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING

from bytemaker.bittypes.bittype import BitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Optional, Tuple, TypeVar
from bytemaker.utils import FrozenDict, HashableMapping, classproperty

if TYPE_CHECKING:
    StrSelf = TypeVar("StrSelf", bound="String")
else:
    try:
        from typing_redirect import Self as StrSelf
    except ImportError:
        StrSelf = TypeVar("StrSelf", bound="String")


class String(BitType[str]):
    py_type = str

    # Field-schema knobs (active when num_bits is a whole number of bytes;
    # sub-byte-width String classes keep the historical exact-width
    # behavior). ``pad`` is the fill byte written after content on encode
    # (None = exact width required); ``terminator`` cuts the *decode* at its
    # first occurrence; ``strip`` drops trailing pad bytes on decode;
    # ``truncate`` opts into code-unit-safe truncation on overflow instead
    # of raising; ``errors`` is the decode error policy where the codec
    # supports one. Cut and strip happen at the BYTE layer, before decoding
    # (a 0xFF pad region is not valid UTF-8; garbage after a terminator is
    # normal in ROM data).
    pad: Optional[int] = 0x00
    terminator: Optional[int] = None
    strip: bool = True
    errors: str = "strict"
    truncate: bool = False

    _codepoint_changes: Optional[
        HashableMapping[BitVector, BitVector] | HashableMapping[str, str]
    ] = None
    _codepoint_changes_cache: Optional[Tuple[int, HashableMapping[str, str]]] = None
    _reverse_codepoint_changes_cache: Optional[
        Tuple[int, HashableMapping[str, str]]
    ] = None
    _codepoint_change_regex_cache: Optional[Tuple[int, re.Pattern[str]]] = None
    _reverse_codepoint_changes_regex_cache: Optional[Tuple[int, re.Pattern[str]]] = None

    @classmethod
    @abstractmethod
    def encoding(cls, value: str) -> BitVector:
        """
        The method used to encode a string into a BitVector.

        Args:
            value (str): The string to encode into a BitVector

        Returns:
            BitVector: The encoded BitVector representation of the input string
        """

    @classmethod
    @abstractmethod
    def decoding(cls, bits: BitVector) -> str:
        """
        The method used to decode a BitVector into a string.

        Args:
            bits (BitVector): The BitVector to decode into a string

        Returns:
            str: The decoded string representation of the input BitVector
        """

    @classproperty
    @classmethod
    def codepoint_changes(cls) -> Optional[HashableMapping[str, str]]:
        """
        A classproperty that gives this class's optional codepoint changes.
        Set this with a str->str mapping or a BitVector -> BitVector mapping
        to have substitutions applied when converting between the
        underlying BitVector bits and str value representations of this class.

        TODO: Add support for sub-byte codepoint changes

        Returns:
            Optional[HashableMapping[str, str]]: The codepoint changes mapping
        """
        if cls._codepoint_changes is None:
            return None
        if cls._codepoint_changes_cache and cls._codepoint_changes_cache[0] == hash(
            cls._codepoint_changes
        ):
            return cls._codepoint_changes_cache[1]

        codepoint_changes_field = cls._codepoint_changes
        if len(codepoint_changes_field) > 0:
            if isinstance(
                codepoint_changes_field.items().__iter__().__next__()[0], BitVector
            ):
                codepoint_changes_field = FrozenDict(
                    {
                        cls.decoding(k): cls.decoding(v)
                        for k, v in codepoint_changes_field.items()
                    }
                )

        cls._codepoint_changes_cache = (
            hash(cls._codepoint_changes),
            codepoint_changes_field,
        )  # type: ignore[reportAttributeAccessIssue]
        return cls._codepoint_changes_cache[1]

    @classproperty
    @classmethod
    def _reverse_codepoint_changes(cls) -> Optional[HashableMapping[str, str]]:
        if cls._codepoint_changes is None:
            return None
        if cls._reverse_codepoint_changes_cache and (
            cls._reverse_codepoint_changes_cache[0] == hash(cls._codepoint_changes)
        ):
            return cls._reverse_codepoint_changes_cache[1]

        codepoint_changes = cls.codepoint_changes
        reverse_codepoint_changes = FrozenDict(
            {v: k for k, v in codepoint_changes.items()}
        )
        cls._reverse_codepoint_changes_cache = (
            hash(cls._codepoint_changes),
            reverse_codepoint_changes,
        )
        return cls._reverse_codepoint_changes_cache[1]

    @classproperty
    @classmethod
    def _codepoint_change_regex(cls) -> Optional[re.Pattern]:
        if cls.codepoint_changes:
            if cls._codepoint_change_regex_cache and cls._codepoint_change_regex_cache[
                0
            ] == hash(cls.codepoint_changes):
                return cls._codepoint_change_regex_cache[1]
            else:
                # Longest alternative first: re alternation is leftmost-first,
                # so "A|AB" would shadow "AB" entirely.
                cls._codepoint_change_regex_cache = (
                    hash(cls.codepoint_changes),
                    re.compile(
                        "|".join(
                            re.escape(key)
                            for key in sorted(
                                cls.codepoint_changes.keys(), key=len, reverse=True
                            )
                        )
                    ),
                )
            return cls._codepoint_change_regex_cache[1]
        return None

    @classproperty
    @classmethod
    def _reverse_codepoint_change_regex(cls) -> Optional[re.Pattern]:
        if cls.codepoint_changes:
            if cls._reverse_codepoint_changes_regex_cache and (
                cls._reverse_codepoint_changes_regex_cache[0]
                == hash(cls.codepoint_changes)
            ):
                return cls._reverse_codepoint_changes_regex_cache[1]
            else:
                # Longest alternative first — see _codepoint_change_regex.
                cls._reverse_codepoint_changes_regex_cache = (
                    hash(cls.codepoint_changes),
                    re.compile(
                        "|".join(
                            re.escape(key)
                            for key in sorted(
                                cls.codepoint_changes.values(), key=len, reverse=True
                            )
                        )
                    ),
                )
            return cls._reverse_codepoint_changes_regex_cache[1]
        return None

    @codepoint_changes.setter
    @classmethod
    def codepoint_changes(
        cls, value: HashableMapping[BitVector, BitVector] | HashableMapping[str, str]
    ):
        if len(value) > 0:
            if isinstance(value.items().__iter__().__next__()[0], BitVector):
                value = FrozenDict(
                    {cls.decoding(k): cls.decoding(v) for k, v in value.items()}
                )

        cls._codepoint_changes = value

    @classmethod
    def perform_codepoint_substitution(
        cls,
        input_string,
        codepoint_changes: HashableMapping[str, str],
        changes_regex: re.Pattern[str],
    ):
        """
        Performs codepoint substitutions on the input string.

        Args:
            input_string (str): The input string to perform substitutions on
            codepoint_changes (HashableMapping[str, str]): The codepoint changes mapping
            changes_regex (re.Pattern[str]): The compiled
                regex pattern for the codepoint changes

        Returns:
            str: The input string with codepoint substitutions applied
        """
        return changes_regex.sub(
            lambda match: codepoint_changes[match.group(0)], input_string
        )

    @classmethod
    def _substitute_forward(cls, value):
        codepoint_changes = cls.codepoint_changes
        if codepoint_changes is not None:
            value = cls.perform_codepoint_substitution(
                value, codepoint_changes, cls._codepoint_change_regex
            )
        return value

    @classmethod
    def _substitute_reverse(cls, value):
        reverse_changes = cls._reverse_codepoint_changes
        if reverse_changes is not None:
            value = cls.perform_codepoint_substitution(
                value, reverse_changes, cls._reverse_codepoint_change_regex
            )
        return value

    @classmethod
    def _encode_padded(cls, value) -> bytes:
        """Encode ``value`` to exactly ``num_bits // 8`` wire bytes:
        substitute, encode, then pad — or, on overflow, truncate whole
        characters (if ``truncate``) or raise."""
        nbytes = cls.num_bits // 8
        substituted = cls._substitute_reverse(value)
        raw = bytes(cls.encoding(substituted))
        if len(raw) > nbytes:
            if not cls.truncate:
                raise ValueError(
                    f"{cls.__name__}: {value!r} encodes to {len(raw)} bytes;"
                    f" the field holds {nbytes} (set truncate=True to clip)"
                )
            # Clip whole characters until it fits: correct at code-unit
            # boundaries for ANY codec, including multi-byte tables.
            while substituted and len(raw) > nbytes:
                substituted = substituted[:-1]
                raw = bytes(cls.encoding(substituted))
        if len(raw) < nbytes:
            if cls.pad is None:
                raise ValueError(
                    f"{cls.__name__}: {value!r} encodes to {len(raw)} bytes;"
                    f" the field holds exactly {nbytes} and padding is"
                    f" disabled (pad=None)"
                )
            raw += bytes((cls.pad,)) * (nbytes - len(raw))
        return raw

    @classmethod
    def _decode_wire(cls, raw) -> str:
        """Decode wire bytes: cut at the terminator, strip trailing pad —
        both at the byte layer, *before* decoding — then decode and
        substitute."""
        raw = bytes(raw)
        if cls.terminator is not None:
            cut = raw.find(bytes((cls.terminator,)))
            if cut >= 0:
                raw = raw[:cut]
        if cls.strip and cls.pad is not None:
            raw = raw.rstrip(bytes((cls.pad,)))
        return cls._substitute_forward(cls.decoding(BitVector(raw)))

    @property
    def value(self):
        if self.num_bits % 8:
            return self._substitute_forward(self.decoding(self.bits))
        return self._decode_wire(bytes(self.bits))

    @value.setter
    def value(self, value):
        if self.num_bits % 8:
            self.bits = self.encoding(self._substitute_reverse(value))
        else:
            self.bits = BitVector(self._encode_padded(value))

    @classmethod
    def specialize(cls, num_bits_: int, name_: Optional[str] = None):
        class _String(cls):
            _num_bits = num_bits_

        if name_:
            _String.__name__ = name_

        return _String

    @classmethod
    def of(
        cls,
        chars: int,
        *,
        encoding=None,
        pad: Optional[int] = 0x00,
        terminator: Optional[int] = None,
        strip: bool = True,
        errors: str = "strict",
        truncate: bool = False,
        name: Optional[str] = None,
    ):
        """Mint a fixed-size text field type.

        ``chars`` is the field size in **bytes** (the C ``char name[N]``
        count; multi-byte codecs fit fewer characters). ``encoding`` may be
        a Python codec name (``"ascii"``, ``"shift-jis"``, …), a
        ``.tbl``-style mapping (``{0x80: "A", 0xE1: "[PK]", …}`` — see
        :class:`TableString`), an ``(encode, decode)`` callable pair
        (``str -> bytes``, ``bytes -> str``), or None to inherit ``cls``'s
        codec (call it on a concrete class such as ``UTF8String``).

        Note (PEP 563): under ``from __future__ import annotations``, field
        types must be bound to module-level names for annotation resolution.
        """
        ns = {
            "_num_bits": chars * 8,
            "pad": pad,
            "terminator": terminator,
            "strip": strip,
            "errors": errors,
            "truncate": truncate,
        }
        if encoding is None:
            if "encoding" in getattr(cls, "__abstractmethods__", ()):
                raise TypeError(
                    f"{cls.__name__}.of(): pass encoding=..., or call of()"
                    f" on a concrete String subclass"
                )
            base = cls
        elif isinstance(encoding, str):
            base = StandardEncodingString
            ns["encoding_name"] = encoding
        elif isinstance(encoding, Mapping):
            base = TableString
            ns["table"] = dict(encoding)
        else:
            enc, dec = encoding
            base = String
            ns["encoding"] = classmethod(lambda c, v, _e=enc: BitVector(_e(v)))
            ns["decoding"] = classmethod(lambda c, b, _d=dec: _d(bytes(b)))
        typename = name or f"{base.__name__}x{chars}"
        return type(base)(typename, (base,), ns)


String.base_bit_type = String


class StandardEncodingString(String):
    """
    A class for strings that use a standard Python encoding (str.encode/decode)
    """

    py_type = str
    encoding_name: str
    """The name of the Python-supported encoding to use for encoding/decoding."""

    @classmethod
    def encoding(cls, value: str) -> BitVector:
        return BitVector(value.encode(cls.encoding_name))

    @classmethod
    def decoding(cls, bits: BitVector) -> str:
        return bytes(bits).decode(cls.encoding_name, cls.errors)


class TableString(String):
    """A String whose codec *is* a character table (``.tbl``-style).

    ``table`` maps wire units to text: keys are ints (single bytes) or
    ``bytes`` (multi-byte sequences); values are strings (single characters
    or control codes like ``"[PK]"``). Both directions match
    **longest-first**. Decoding an unmapped byte follows ``errors``
    ("strict" raises; "replace" yields U+FFFD and advances one byte);
    encoding an unmapped character always raises (there is no meaningful
    replacement byte).
    """

    table: Mapping = {}
    _tbl_cache = None

    @classmethod
    def _maps(cls):
        cache = cls.__dict__.get("_tbl_cache")
        if cache is None:
            dec = {}
            for k, v in cls.table.items():
                kb = bytes((k,)) if isinstance(k, int) else bytes(k)
                dec[kb] = v
            enc = {v: kb for kb, v in dec.items()}
            cache = (
                dec,
                sorted(dec, key=len, reverse=True),
                enc,
                sorted(enc, key=len, reverse=True),
            )
            cls._tbl_cache = cache
        return cache

    @classmethod
    def encoding(cls, value: str) -> BitVector:
        _, _, enc, enc_keys = cls._maps()
        out = bytearray()
        pos = 0
        while pos < len(value):
            for key in enc_keys:
                if key and value.startswith(key, pos):
                    out += enc[key]
                    pos += len(key)
                    break
            else:
                raise ValueError(
                    f"{cls.__name__}: no table entry encodes"
                    f" {value[pos]!r} (position {pos})"
                )
        return BitVector(bytes(out))

    @classmethod
    def decoding(cls, bits: BitVector) -> str:
        dec, dec_keys, _, _ = cls._maps()
        raw = bytes(bits)
        out = []
        pos = 0
        while pos < len(raw):
            for key in dec_keys:
                if key and raw.startswith(key, pos):
                    out.append(dec[key])
                    pos += len(key)
                    break
            else:
                if cls.errors == "replace":
                    out.append("�")
                    pos += 1
                else:
                    raise ValueError(
                        f"{cls.__name__}: no table entry decodes byte"
                        f" 0x{raw[pos]:02x} (position {pos})"
                    )
        return "".join(out)


class UTF8String(StandardEncodingString):
    encoding_name = "utf-8"


class Str8(UTF8String):
    _num_bits = 8


class Str9(UTF8String):
    _num_bits = 9


class Str10(UTF8String):
    _num_bits = 10


class Str11(UTF8String):
    _num_bits = 11


class Str12(UTF8String):
    _num_bits = 12


class Str13(UTF8String):
    _num_bits = 13


class Str14(UTF8String):
    _num_bits = 14


class Str15(UTF8String):
    _num_bits = 15


class Str16(UTF8String):
    _num_bits = 16


class Str32(UTF8String):
    _num_bits = 32


class Str64(UTF8String):
    _num_bits = 64


class Str128(UTF8String):
    _num_bits = 128


class Str256(UTF8String):
    _num_bits = 256


class Str512(UTF8String):
    _num_bits = 512


__all__ = [
    "String",
    "StandardEncodingString",
    "TableString",
    "UTF8String",
    "Str8",
    "Str9",
    "Str10",
    "Str11",
    "Str12",
    "Str13",
    "Str14",
    "Str15",
    "Str16",
    "Str32",
    "Str64",
    "Str128",
    "Str256",
    "Str512",
]
