from __future__ import annotations

import codecs
import re
from abc import abstractmethod
from collections.abc import Mapping

from bytemaker.bittypes.bittype import BitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Optional, Tuple, TypeVar
from bytemaker.utils import FrozenDict, HashableMapping, classproperty

#: See the note on ``BitSelf`` in bittypes/bittype.py: a bound TypeVar in
#: both planes, the always-failing typing_redirect import removed.
StrSelf = TypeVar("StrSelf", bound="String")


def _table_bytes_per_char(table) -> Tuple[Optional[int], Optional[str]]:
    """``(bytes_per_char, reason_if_undefined)`` for a ``.tbl`` mapping.

    Character count is well-defined only when every key is one wire-unit
    length and every value is a single character; control codes (``"[PK]"``)
    or mixed key widths make it undefined."""
    if not table:
        return None, "the table is empty"
    key_lens = set()
    for k, v in table.items():
        kb = bytes((k,)) if isinstance(k, int) else bytes(k)
        key_lens.add(len(kb))
        if not (isinstance(v, str) and len(v) == 1):
            return None, (f"{kb!r} maps to {v!r}, which is not a single character")
    if len(key_lens) > 1:
        return None, f"keys have mixed byte lengths {sorted(key_lens)}"
    return key_lens.pop(), None


class String(BitType[str]):
    """A ``BitType`` whose value is text (the C ``char name[N]`` field).

    Concrete subclasses supply the codec as a classmethod pair:
    :meth:`encoding` maps ``str -> BitVector``, and :meth:`decoding` maps
    ``BitVector -> str``. :class:`StandardEncodingString` wraps a Python
    codec name, and :class:`TableString` wraps a ``.tbl``-style byte table.
    Mint fixed-size field types with :meth:`of`, which also selects the
    codec.

    When ``num_bits`` is a whole number of bytes, the value round-trips
    through the field-schema knobs below. A sub-byte-width String class
    keeps the historical exact-width behavior instead.

    ``pad`` is the fill byte written after the content on encode. Setting
    it to None requires an exact width.

    ``terminator`` is written after the content on encode whenever it fits.
    A max-length value fills the field with no terminator, which is the C
    ``strncpy`` convention. On decode the terminator cuts the text at its
    first occurrence, so parse -> pack round-trips the wire bytes.

    ``strip`` drops trailing pad bytes on decode. ``truncate`` opts into
    code-unit-safe truncation on overflow instead of raising. ``errors`` is
    the decode error policy: any registered codec error handler for
    standard encodings, or "strict", "replace" or "ignore" for tables.

    Cut and strip both happen at the byte layer, before decoding, because a
    0xFF pad region is not valid UTF-8 and garbage after a terminator is
    normal in ROM data. Both work in whole character units when
    ``bytes_per_char`` is known.

    Optional :attr:`codepoint_changes` substitutions are applied to the
    text after decoding and reversed before encoding.
    """

    py_type = str

    pad: Optional[int] = 0x00
    terminator: Optional[int] = None
    strip: bool = True
    errors: str = "strict"
    truncate: bool = False
    #: Fixed wire bytes per character, when the codec has one (single-byte
    #: tables derive 1; pass explicitly for e.g. UTF-16). Sizing metadata
    #: only (the wire contract stays bytes), but when known, terminator/pad
    #: handling works on whole character units.
    bytes_per_char: Optional[int] = None

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

    @classmethod
    def _check_codepoint_changes(cls, mapping) -> None:
        """Reject zero-length substitution keys and values.

        An empty key compiles to a zero-width regex alternative that
        matches between every pair of characters, so substitution would
        silently insert text at every position. An empty value makes the
        rule a deletion, such as ``{"X": ""}``, which cannot be reversed on
        encode. Neither direction has well-defined semantics, so both are
        rejected here.

        Args:
            mapping (HashableMapping[str, str]): The str->str codepoint
                changes mapping to validate

        Raises:
            ValueError: If any key or value is an empty string
        """
        for k, v in mapping.items():
            if not k or not v:
                raise ValueError(
                    f"{cls.__name__}: codepoint_changes entries must map"
                    f" non-empty strings to non-empty strings,"
                    f" got {k!r} -> {v!r}"
                )

    @classproperty
    @classmethod
    def codepoint_changes(cls) -> Optional[HashableMapping[str, str]]:
        """
        This class's optional codepoint changes, as a classproperty.

        Set it to a str->str mapping or a BitVector -> BitVector mapping to
        have substitutions applied when converting between this class's
        underlying BitVector bits and its str value.

        Sub-byte codepoint changes are not supported.

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

        # Validate here rather than only in the setter: class-body and
        # direct ``_codepoint_changes`` assignments bypass the descriptor,
        # but every consumer reads through this property.
        cls._check_codepoint_changes(codepoint_changes_field)

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
                # Longest alternative first; see _codepoint_change_regex.
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

        cls._check_codepoint_changes(value)
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
        # Truthiness, not identity: the regex builders treat an empty
        # mapping as "no substitutions" (no regex), so this must too.
        codepoint_changes = cls.codepoint_changes
        if codepoint_changes:
            value = cls.perform_codepoint_substitution(
                value, codepoint_changes, cls._codepoint_change_regex
            )
        return value

    @classmethod
    def _substitute_reverse(cls, value):
        # Truthiness, not identity; see _substitute_forward.
        reverse_changes = cls._reverse_codepoint_changes
        if reverse_changes:
            value = cls.perform_codepoint_substitution(
                value, reverse_changes, cls._reverse_codepoint_change_regex
            )
        return value

    @classmethod
    def _encode_padded(cls, value) -> bytes:
        """Encode ``value`` to exactly ``num_bits // 8`` wire bytes.

        The steps are substitute, encode, write the terminator when one is
        set and it fits, then pad. On overflow, truncate whole characters
        when ``truncate`` is set, and raise otherwise.
        """
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
            # boundaries for ANY codec, including multi-byte tables. A clip
            # can land mid-token for table codecs ("A[PK]" -> "A[PK"), where
            # encoding raises: keep clipping past the broken token.
            while len(raw) > nbytes:
                if not substituted:
                    raw = b""
                    break
                substituted = substituted[:-1]
                try:
                    raw = bytes(cls.encoding(substituted))
                except ValueError:
                    pass
        # Mirror the decode cut: the terminator is part of the wire format,
        # so write it back whenever a whole character unit of room exists
        # (a max-length value fills the field with no terminator, the C
        # strncpy convention). Without this, parse -> pack rewrote the
        # terminator byte as pad, silently corrupting read-modify-write
        # workflows whenever pad != terminator.
        if cls.terminator is not None:
            unit = cls.bytes_per_char or 1
            if len(raw) + unit <= nbytes:
                raw += bytes((cls.terminator,)) * unit
        if len(raw) < nbytes:
            if cls.pad is None:
                including = (
                    " (terminator included)" if cls.terminator is not None else ""
                )
                raise ValueError(
                    f"{cls.__name__}: {value!r} encodes to {len(raw)} wire"
                    f" bytes{including}; the field holds exactly {nbytes}"
                    f" and padding is disabled (pad=None)"
                )
            raw += bytes((cls.pad,)) * (nbytes - len(raw))
        return raw

    @classmethod
    def _decode_wire(cls, raw) -> str:
        """Decode wire bytes: cut at the terminator, strip trailing pad
        (both at the byte layer, *before* decoding), then decode and
        substitute. Cut and strip work in whole character units when
        ``bytes_per_char`` is known (a NUL-padded UTF-16 field must strip
        ``b"\\x00\\x00"`` pairs; byte-wise stripping would eat the high
        byte of a final ``"b"`` and split the code unit)."""
        raw = bytes(raw)
        unit = cls.bytes_per_char or 1
        if cls.terminator is not None:
            term = bytes((cls.terminator,)) * unit
            for pos in range(0, len(raw) - unit + 1, unit):
                if raw[pos : pos + unit] == term:
                    raw = raw[:pos]
                    break
        if cls.strip and cls.pad is not None:
            pad_unit = bytes((cls.pad,)) * unit
            while raw.endswith(pad_unit):
                raw = raw[:-unit]
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
            self.bits = self._encode_padded(value)

    @classmethod
    def specialize(cls, num_bits_: int, name_: Optional[str] = None):
        """
        Returns a subclass of String with the specified number of bits.

        `specialize` takes a raw bit count. `of` instead sizes in whole
        ``bytes_per_char`` units, for use as a Struct field type.

        Args:
            num_bits_ (int): The number of bits in the subclass.
            name_ (Optional[str], optional): The name of the subclass.
                Defaults to None, meaning the name will be _String.

        Returns:
            Type[String]: The subclass with the specified number of bits.
        """

        class _String(cls):
            _num_bits = num_bits_

        if name_:
            _String.__name__ = name_

        return _String

    @classmethod
    def of(
        cls,
        *,
        nbytes: Optional[int] = None,
        nchars: Optional[int] = None,
        bytes_per_char: Optional[int] = None,
        encoding=None,
        pad: Optional[int] = 0x00,
        terminator: Optional[int] = None,
        strip: bool = True,
        errors: str = "strict",
        truncate: bool = False,
        name: Optional[str] = None,
    ):
        """Mint a fixed-size text field type.

        Size the field with exactly one of (both keyword-only, so every
        declaration names its unit):

        * ``nbytes`` is wire bytes, the C ``char name[N]`` count; multi-byte
          codecs fit fewer characters.
        * ``nchars`` is a character count: sugar for ``nchars * bytes_per_char``
          wire bytes, so it needs a fixed, known bytes-per-char. That is
          derived for mapping codecs (defined iff every key is one wire-unit
          length and every value one character) and taken from
          ``bytes_per_char=`` (or an inherited class attribute) otherwise.
          Codecs without one (UTF-8, Shift-JIS, tables with control codes
          like ``"[PK]"``) refuse ``nchars=`` at mint time: size those in
          bytes, which is the only quantity they fix.

        The wire contract is always bytes; ``bytes_per_char`` is sizing
        metadata, never a safety invariant (the store-time length check is
        byte-based regardless). When known it also makes decode-side
        terminator/pad handling work on whole character units.

        ``encoding`` may be a Python codec name (``"ascii"``,
        ``"shift-jis"``, ...), a ``.tbl``-style mapping (``{0x80: "A",
        0xE1: "[PK]", ...}}``; see :class:`TableString`), an
        ``(encode, decode)`` callable pair (``str -> bytes``,
        ``bytes -> str``), or None to inherit ``cls``'s codec (call it on a
        concrete class such as ``UTF8String``).

        Note (PEP 563): under ``from __future__ import annotations``, field
        types must be bound to module-level names for annotation resolution.
        """
        if (nbytes is None) == (nchars is None):
            raise TypeError(
                f"{cls.__name__}.of(): size the field with exactly one of"
                f" nbytes= (wire bytes, the C char name[N] count) or nchars="
            )
        if bytes_per_char is not None and (
            not isinstance(bytes_per_char, int) or bytes_per_char < 1
        ):
            raise ValueError(
                f"{cls.__name__}.of(): bytes_per_char must be a positive"
                f" int, got {bytes_per_char!r}"
            )
        for byte_param, byte_value in (("pad", pad), ("terminator", terminator)):
            if byte_value is not None and (
                not isinstance(byte_value, int) or not 0 <= byte_value <= 0xFF
            ):
                raise ValueError(
                    f"{cls.__name__}.of(): {byte_param} must be a byte"
                    f" value 0-255 or None, got {byte_value!r}"
                )
        bpc = bytes_per_char
        bpc_reason = None
        if bpc is None:
            if isinstance(encoding, Mapping):
                bpc, bpc_reason = _table_bytes_per_char(encoding)
            elif encoding is None:
                bpc = cls.bytes_per_char
        if nchars is not None:
            if bpc is None:
                detail = f" ({bpc_reason})" if bpc_reason else ""
                raise TypeError(
                    f"{cls.__name__}.of(): nchars= needs a fixed"
                    f" bytes-per-char, which this codec does not"
                    f" declare{detail}; size the field in bytes (nbytes=)"
                    f" or pass bytes_per_char="
                )
            nbytes = nchars * bpc
        if not isinstance(nbytes, int) or nbytes < 1:
            raise ValueError(
                f"{cls.__name__}.of(): field size must be a positive int,"
                f" got {nbytes!r}"
            )
        if bpc is not None and nbytes % bpc:
            raise ValueError(
                f"{cls.__name__}.of(): nbytes={nbytes} is not a whole"
                f" number of {bpc}-byte characters; decode-side"
                f" pad/terminator handling works in bytes_per_char units,"
                f" so a partial trailing unit could never decode"
            )
        ns = {
            "_num_bits": nbytes * 8,
            "pad": pad,
            "terminator": terminator,
            "strip": strip,
            "errors": errors,
            "truncate": truncate,
        }
        if bpc is not None:
            ns["bytes_per_char"] = bpc
        if encoding is None:
            if "encoding" in getattr(cls, "__abstractmethods__", ()):
                raise TypeError(
                    f"{cls.__name__}.of(): pass encoding=..., or call of()"
                    f" on a concrete String subclass"
                )
            base = cls
        elif isinstance(encoding, str):
            try:
                codecs.lookup(encoding)
            except LookupError:
                raise ValueError(
                    f"{cls.__name__}.of(): unknown encoding {encoding!r}"
                ) from None
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
        # Fail a typo'd or codec-unsupported errors= at the declaration,
        # not at the first unlucky byte. Callable-pair codecs are exempt:
        # they decide for themselves what (if anything) errors means.
        if issubclass(base, TableString):
            if errors not in ("strict", "replace", "ignore"):
                raise ValueError(
                    f"{cls.__name__}.of(): table codecs support errors="
                    f" 'strict', 'replace', or 'ignore', got {errors!r}"
                )
        elif issubclass(base, StandardEncodingString):
            try:
                codecs.lookup_error(errors)
            except (LookupError, TypeError):
                raise ValueError(
                    f"{cls.__name__}.of(): errors={errors!r} is not a"
                    f" registered codec error handler (see"
                    f" codecs.lookup_error)"
                ) from None
        typename = name or f"{base.__name__}x{nbytes}"
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
    """A String whose codec is a ``.tbl``-style character table.

    ``table`` maps wire units to text. Keys are ints for single bytes, or
    ``bytes`` for multi-byte sequences. Values are strings, either single
    characters or control codes such as ``"[PK]"``. Both directions match
    longest-first.

    Decoding an unmapped byte follows ``errors``. "strict" raises,
    "replace" yields U+FFFD and advances one byte, and "ignore" advances
    one byte and emits nothing. Encoding an unmapped character always
    raises, because there is no meaningful replacement byte.
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
                elif cls.errors == "ignore":
                    pos += 1
                else:
                    raise ValueError(
                        f"{cls.__name__}: no table entry decodes byte"
                        f" 0x{raw[pos]:02x} (position {pos})"
                    )
        return "".join(out)


class UTF8String(StandardEncodingString):
    encoding_name = "utf-8"


__all__ = [
    "String",
    "StandardEncodingString",
    "TableString",
    "UTF8String",
]
