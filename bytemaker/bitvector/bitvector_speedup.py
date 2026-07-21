from __future__ import annotations

import copy
import logging
import math
import operator
import sys
from typing import TYPE_CHECKING, overload

logger = logging.getLogger(__name__)

try:
    from bytemaker.typing_redirect import (
        Buffer,
        Iterable,
        Iterator,
        Literal,
        MutableSequence,
        Optional,
        Protocol,
        Sequence,
        TypeVar,
        Union,
        runtime_checkable,
    )
    from bytemaker.utils import is_instance_of_union, twos_complement_bit_length
except ImportError:
    from typing_redirect import (  # type: ignore
        Buffer,
        Iterable,
        Iterator,
        Literal,
        MutableSequence,
        Optional,
        Protocol,
        Sequence,
        TypeVar,
        Union,
        runtime_checkable,
    )
    from utils import is_instance_of_union, twos_complement_bit_length

LaxLiteral01 = Union[Literal[0, 1], int]
LaxLiteral01Str = Union[Sequence[Literal["0", "1"]], str]

if TYPE_CHECKING:
    Self = TypeVar("Self", bound="BitVector")
else:
    try:
        from typing_redirect import Self
    except ImportError:
        Self = TypeVar("Self", bound="BitVector")
T = TypeVar("T")


@runtime_checkable
class BitsCastable(Protocol):
    """
    Protocol for objects that can be cast to a BitVector.

    If provided object is not itself a BitVector, this protocol will be
       prioritized when BitVectorSubtype(object) is called
       over any other possible behavior.

    __Bits__ returns a BitVector representation of the object
        that should not be a shallow copy (unless you want)
        the cast object to share memory with the original object).
    """

    def __Bits__(
        self,
    ) -> BitVector:
        """
        Returns a deep BitVector representation of the object.

        This method is prioritized when BitVectorSubtype(object) is called.

        Returns:
            BitVector: The BitVector representation of the object
        """
        ...


_SEPARATOR_TABLE = str.maketrans("", "", "_- :")
_DELETE_01_TABLE = str.maketrans("", "", "01")
_VALBITS_TO_CHARS = bytes.maketrans(b"\x00\x01", b"01")
_CHARS_TO_VALBITS = bytes.maketrans(b"01", b"\x00\x01")

_BITS_PER_CHAR = {2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6}
_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

# Per-base mapping of each digit character to its bits as a 0/1 string.
_DIGIT_TO_BITS = {
    4: {digit: format(value, "02b") for value, digit in enumerate("0123")},
    8: {digit: format(value, "03b") for value, digit in enumerate("01234567")},
    16: {digit: format(value, "04b") for value, digit in enumerate("0123456789abcdef")},
    32: {digit: format(value, "05b") for value, digit in enumerate(_BASE32_ALPHABET)},
    64: {digit: format(value, "06b") for value, digit in enumerate(_BASE64_ALPHABET)},
}
# Reverse mapping (canonical digits only) for the bases format() cannot render.
_CHUNK_TO_DIGIT = {
    base: {bits: digit for digit, bits in _DIGIT_TO_BITS[base].items()}
    for base in (4, 32, 64)
}
_DIGIT_TO_BITS[16].update(
    {digit.upper(): bits for digit, bits in _DIGIT_TO_BITS[16].items() if digit.isalpha()}
)

if hasattr(int, "bit_count"):  # Python >= 3.10

    def _popcount(value: int) -> int:
        return value.bit_count()

else:

    def _popcount(value: int) -> int:
        return bin(value).count("1")


def _coerce_bit(value: LaxLiteral01) -> int:
    """Validates that `value` is a 0 or 1 (or equal to one of them,
    e.g. booleans) and returns it as a plain int."""
    if value == 0:
        return 0
    if value == 1:
        return 1
    raise ValueError(f"bit must be 0 or 1, got {value!r}")


def _pack_int(value: int, nbits: int) -> bytearray:
    """Packs the low `nbits` bits of `value` (two's complement for negatives)
    into a bytearray, most-significant bit first, zero-padded on the right
    to a whole number of bytes."""
    if nbits <= 0:
        return bytearray()
    value &= (1 << nbits) - 1
    pad = -nbits & 7
    if pad:
        value <<= pad
    return bytearray(value.to_bytes((nbits + 7) >> 3, "big"))


def _valbits_from_iterable(source: Iterable[LaxLiteral01]) -> bytearray:
    """Converts an iterable of lax 0/1 values into a validated bytearray of
    0/1 byte values. Bulk-validates sized sources with C-level primitives and
    falls back to per-element coercion for exotic element types."""
    if hasattr(source, "__len__"):
        try:
            raw = bytearray(source)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return bytearray(_coerce_bit(bit) for bit in source)
        if raw.translate(None, b"\x00\x01"):
            for bit in raw:
                _coerce_bit(bit)
        return raw
    # Unsized iterables (e.g. generators) cannot be safely re-iterated after
    # a failed bulk attempt, so they are always coerced element by element.
    return bytearray(_coerce_bit(bit) for bit in source)


def _pack_valbits(valbits: bytearray) -> "tuple[bytearray, int]":
    """Packs a bytearray of 0/1 byte values into (packed buffer, bit length)."""
    nbits = len(valbits)
    if nbits == 0:
        return bytearray(), 0
    chars = bytes(valbits).translate(_VALBITS_TO_CHARS)
    return _pack_int(int(chars, 2), nbits), nbits


class BitVector(MutableSequence[LaxLiteral01], BitsCastable):
    """
    A mutable sequence of bits.

    This class's behavior is largely a superset of that of bytearray,
       excepting certain methods that are not applicable to bits.

    This particular implementation is pure Python with packed storage:
        the bits are stored 8 per byte in a bytearray (`_buf`), most
        significant bit first, together with an explicit bit length
        (`_len`). Unused padding bits in the final byte are always zero.
        Bulk operations route through Python's arbitrary-precision int
        engine (int.from_bytes -> C-level op -> int.to_bytes) instead of
        per-bit Python loops.

    Performance
    -----------
    n = len(self) in bits; m = the other operand's or pattern's length;
    k = the number of bits read or produced.
    
    Bulk operations run as a single C-level pass
    (int.from_bytes -> op -> int.to_bytes, or a bytearray memcpy).

    Two shorthands appear below:
    - *01 string* is to01()
    - *big-int* is the packed bits read as one
       arbitrary-precision Python int (via int.from_bytes).

    ```
    operation                   cost    mechanism
    --------------------------  ------  -----------------------------
    len, clear                  O(1)    length field
    get/set one bit             O(1)    byte shift + mask
    append, pop from the end    O(1)*   only the last byte
    bytes(), tobytes()          O(n)    buffer copy (memcpy)
    construct from bytes, copy  O(n)    buffer copy (memcpy)
    &, |, ^, ~, <<, >>          O(n)    one big-int op
    from_int, to_int            O(n)    int <-> bytes
    insert, del a[i]            O(n)    splice via big-int shift
    to01/hex/oct, from01        O(n)    int <-> digit string
    ==, !=                      O(n)    C bytearray compare
    <, <=, >, >=                O(n)    compares 01 strings
    slice a[i:j], +, *, extend  O(k)    memcpy or big-int shift
    setitem/delitem by slice    O(n)    rebuilds via 01 string
    reverse, replace            O(n)    rebuilds via 01 string
    find/rfind/count (bit)      O(n)    popcount / set-bit scan
    find/count (subsequence)    O(n*m)  substring search on 01 string
    startswith, endswith        O(m)    extracts an m-bit window

    (*) amortized.
    ```

    Do note that the structural behavior documented in bitvector.pyi
        is what is guaranteed.
    """

    _buf: bytearray
    _len: int

    def __new__(
        cls: type[Self],
        source: Optional[Union[BitsConstructible, int]] = None,
        buffer: Optional[Buffer] = None,
        *args,
        **kwargs,
    ) -> Self:
        """
        Constructs a BitVector.
        * The bits are drawn from `buffer`, else `source`.

        If `buffer` is set, the BitVector's bits are read from the provided
            object. The buffer object must support the buffer protocol
            (https://docs.python.org/3/c-api/buffer.html).

        Otherwise, `source` determines the BitVector's bits.
        * If `source` is None, the BitVector is empty.
        * If `source` is a str, the bits are obtained by prefix-determined\
           classmethods that allow `source` to be interspersed with "_", "-",\
           " ", or ":" characters ("" invokes `from01`, "0b" `frombin`,\
           "0o" `fromoct`, "0x" `fromhex`).
        * If `source` is an int, the BitVector is created with that many bits\
            (set to 0).

        Args:
            source (Optional[Union[BitsConstructible, int]]): The bits of the BitVector
            buffer (Buffer): The buffer to use
        """
        # Buffer constructor
        if buffer is not None:
            self: Self = super().__new__(cls)
            raw = bytes(memoryview(buffer))
            self._buf = bytearray(raw)
            self._len = 8 * len(raw)
            return self
        # Default constructor
        elif source is None:
            self: Self = super().__new__(cls)
            self._buf = bytearray()
            self._len = 0
            return self

        # Exact-type fast paths. These cannot carry a __Bits__ method, so
        # checking them before the BitsCastable protocol preserves the
        # protocol's documented priority while skipping its cost.
        source_type = type(source)
        if source_type is str:
            return cls._from_str(source)
        if source_type is bytes or source_type is bytearray:
            self: Self = super().__new__(cls)
            self._buf = bytearray(source)
            self._len = 8 * len(source)
            return self
        if source_type is int:
            return cls.fromsize(source)

        # Copy constructor
        if isinstance(source, BitVector):
            self: Self = super().__new__(cls)
            self._buf = bytearray(source._buf)
            self._len = source._len
            return self
        # BitsCastable constructor
        if getattr(source, "__Bits__", None) is not None:
            curinstance = source.__Bits__()
            self: Self = super().__new__(cls)
            if isinstance(curinstance, BitVector):
                self._buf = bytearray(curinstance._buf)
                self._len = curinstance._len
            else:
                # A foreign BitVector implementation; convert via its 01 form.
                converted = cls.from01(curinstance.to01())
                self._buf = converted._buf
                self._len = converted._len
            return self

        # Subclass-of-builtin constructors
        if isinstance(source, str):
            return cls._from_str(source)
        if isinstance(source, int):
            return cls.fromsize(source)
        if isinstance(source, (bytes, bytearray)):
            self: Self = super().__new__(cls)
            raw = bytes(source)
            self._buf = bytearray(raw)
            self._len = 8 * len(raw)
            return self

        if isinstance(source, Iterable):
            self: Self = super().__new__(cls)
            self._buf, self._len = _pack_valbits(_valbits_from_iterable(source))
            return self

        raise ValueError(f"Invalid source type: {type(source)}")

    def __init__(
        self,
        source: Optional[Union[BitsConstructible, int]] = None,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,  # TODO
        buffer: Buffer = None,  # type: ignore
    ) -> None:
        """
        See __new__ for construction semantics. `encoding` and `errors`
        are accepted for signature parity but not implemented.

        Args:
            source (Optional[Union[BitsConstructible, int]]): The bits of the
                BitVector (see __new__).
            encoding (Optional[str]): The encoding to use (not implemented).
            errors (Optional[str]): The error handling to use (not implemented).
            buffer (Buffer): The buffer to read bits from.
        """
        super().__init__()

    # Internal representation helpers

    @classmethod
    def _with_buf(cls: type[Self], buf: bytearray, nbits: int) -> Self:
        """
        Creates a BitVector around an already-packed buffer without
        re-parsing or re-validating. The buffer must satisfy the class
        invariants: len(buf) == ceil(nbits / 8) and zero padding bits.
        """
        instance: Self = super().__new__(cls)
        instance._buf = buf
        instance._len = nbits
        return instance

    @classmethod
    def _from_str(cls: type[Self], string: str) -> Self:
        """
        Dispatches string construction on the "0b"/"0o"/"0x" prefix.
        """
        if string.startswith("0b"):
            return cls.frombin(string)
        if string.startswith("0o"):
            return cls.fromoct(string)
        if string.startswith("0x"):
            return cls.fromhex(string)
        return cls.from01(string)

    @classmethod
    def _pack01chars(cls: type[Self], chars: Union[str, bytes, bytearray]) -> Self:
        """
        Packs a pre-validated string (or ASCII buffer) of '0'/'1'
        characters into a BitVector.
        """
        nbits = len(chars)
        if nbits == 0:
            return cls._with_buf(bytearray(), 0)
        return cls._with_buf(_pack_int(int(chars, 2), nbits), nbits)

    def _as_int(self) -> int:
        """
        Returns the bits as a single unsigned int (empty -> 0).
        """
        value = int.from_bytes(self._buf, "big")
        pad = -self._len & 7
        return value >> pad if pad else value

    def _extract_int(self, start: int, length: int) -> int:
        """
        Returns bits [start, start+length) as an unsigned int, touching
        only the bytes that overlap the range.

        Cost is O(length), not O(len(self)): only the ceil(length / 8) + 1
        covering bytes are sliced and converted, so pulling a fixed-width
        field out of a multi-megabyte buffer stays cheap. This is why
        ranged count/startswith/endswith and unaligned slicing go through
        here instead of building the whole vector's int via _as_int().

        `first`/`last` bracket the smallest whole-byte run covering the
        range; `chunk` therefore carries up to 7 unwanted bits above `start`
        (high-order, cleared by the mask) and up to 7 below the range
        (low-order, shifted out by `drop`, which counts the trailing junk
        bits as chunk_bits - (start + length)).
        """
        if length <= 0:
            return 0
        first = start >> 3
        last = (start + length + 7) >> 3
        chunk = int.from_bytes(self._buf[first:last], "big")
        drop = (last << 3) - (start + length)
        return (chunk >> drop) & ((1 << length) - 1)

    def _slice_packed(self, start: int, length: int) -> bytearray:
        """
        Returns bits [start, start+length) as a packed buffer.
        """
        if length <= 0:
            return bytearray()
        if start & 7 == 0:
            out = bytearray(self._buf[start >> 3 : (start + length + 7) >> 3])
            tail = length & 7
            if tail:
                out[-1] &= (0xFF << (8 - tail)) & 0xFF
            return out
        return _pack_int(self._extract_int(start, length), length)

    def _to01_bytearray(self) -> bytearray:
        """Returns the bits as a bytearray of ASCII '0'/'1' characters."""
        return bytearray(self.to01(), "ascii")

    def _reset01(self, chars: Union[str, bytes, bytearray]) -> None:
        """Replaces this BitVector's contents from a pre-validated string
        (or ASCII buffer) of '0'/'1' characters."""
        nbits = len(chars)
        self._buf = _pack_int(int(chars, 2), nbits) if nbits else bytearray()
        self._len = nbits

    def _iconcat(self, other: BitVector) -> None:
        """Appends another BitVector's bits in place."""
        if self._len & 7 == 0:
            self._buf += other._buf
            self._len += other._len
        else:
            nbits = self._len + other._len
            value = (self._as_int() << other._len) | other._as_int()
            self._buf = _pack_int(value, nbits)
            self._len = nbits

    def _check_invariants(self) -> bool:
        """Asserts the packed-representation invariants (test helper)."""
        assert len(self._buf) == (self._len + 7) >> 3
        tail = self._len & 7
        if tail:
            assert self._buf[-1] & (0xFF >> tail) == 0
        return True

    # Transformations

    @classmethod
    def _from_digits(cls: type[Self], string: str, base: int) -> Self:
        """Converts a separator-free digit string in `base` to a BitVector."""
        table = _DIGIT_TO_BITS[base]
        try:
            bits01 = "".join(map(table.__getitem__, string))
        except KeyError as exc:
            raise ValueError(
                f"invalid digit for base {base}: {exc.args[0]!r}"
            ) from None
        return cls._pack01chars(bits01)

    @classmethod
    def fromhex(cls: type[Self], string: str) -> Self:
        """
        Create a BitVector from a hexadecimal string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string may start with "0x".

        Args:
            string (str): The hexadecimal string to convert

        Returns:
            BitVector: The BitVector created from the hexadecimal string
        """
        string = string.translate(_SEPARATOR_TABLE)
        if string.startswith("0x"):
            string = string[2:]
        return cls._from_digits(string, 16)

    @classmethod
    def fromoct(cls: type[Self], string: str) -> Self:
        """
        Create a BitVector from an octal string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string may start with "0o".

        Args:
            string (str): The octal string to convert

        Returns:
            BitVector: The BitVector created from the octal string
        """
        string = string.translate(_SEPARATOR_TABLE)
        if string.startswith("0o"):
            string = string[2:]
        return cls._from_digits(string, 8)

    @classmethod
    def frombin(cls: type[Self], string: str) -> Self:
        """
        Create a BitVector from a binary string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string may start with "0b".

        Args:
            string (str): The binary string to convert

        Returns:
            BitVector: The BitVector created from the binary string
        """
        if string.startswith("0b"):
            string = string[2:]
        return cls.from01(string)

    @classmethod
    def from01(cls: type[Self], string: LaxLiteral01Str) -> Self:
        """
        Create a BitVector from a binary string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string must contain only 0s and 1s other than these.

        Args:
            string (str): The binary string to convert

        Returns:
            BitVector: The BitVector created from the binary string
        """
        if not isinstance(string, str):
            string = "".join(string)
        string = string.translate(_SEPARATOR_TABLE)
        invalid = string.translate(_DELETE_01_TABLE)
        if invalid:
            raise ValueError(f"expected only '0's and '1's, got {invalid[0]!r}")
        return cls._pack01chars(string)

    @classmethod
    def fromsize(cls: type[Self], size: int, /) -> Self:
        """
        Create a BitVector with `size` bits, all set to 0.

        Args:
            size (int): The size of the BitVector to create

        Returns:
            BitVector: The BitVector created with the given size
        """
        size = max(size, 0)
        return cls._with_buf(bytearray((size + 7) >> 3), size)

    @classmethod
    def frombase(cls: type[Self], string: str, base: int) -> Self:
        """
        Create a BitVector from a string in a given base.
        The string may contain any of '_', '-', ' ', or ':'.
        In the case of bases 2, 8, and 16,
            the string may start with "0b", "0o", or "0x" respectively.

        Args:
            string (str): The string to convert
            base (int): The base of the string

        Returns:
            BitVector: The BitVector created from the string
        """
        if base == 2:
            return cls.frombin(string)
        elif base == 8:
            return cls.fromoct(string)
        elif base == 16:
            return cls.fromhex(string)

        if base not in _BITS_PER_CHAR:
            raise ValueError(f"Invalid base: {base}")
        string = string.translate(_SEPARATOR_TABLE)
        return cls._from_digits(string, base)

    @classmethod
    def from_chararray(
        cls: type[Self],
        char_array: str,
        encoding: Union[str, dict[str, BitsConstructible]] = "utf-8",
    ) -> Self:
        """
        Create a BitVector from a `char_array` string where each character is
        a byte (for standard str encodings), or from the concatenation of the
        per-substring BitVectors described by an encoding mapping.

        Args:
            char_array (str): The string to convert
            encoding (Union[str, dict[str, BitsConstructible]]): The encoding to use

        Returns:
            BitVector: The BitVector created from the string
        """
        if isinstance(encoding, str):
            char_array_as_bytes: bytes = char_array.encode(encoding)
            retval = cls(buffer=char_array_as_bytes)
            logger.debug("using standard encoding...")
            logger.debug("retval %s", retval)
            return retval
        else:
            parts: list[str] = []
            substring = ""
            for char in char_array:
                substring += char
                if substring in encoding:
                    parts.append(cls(encoding[substring]).to01())
                    substring = ""
            return cls._pack01chars("".join(parts))

    def _to_base_str(self, base: int) -> str:
        """Converts the bits to a string of digits in the given base
        (a power of two no greater than 64). The number of bits must be
        a multiple of the number of bits per digit."""
        bits_per_char = _BITS_PER_CHAR[base]
        if self._len % bits_per_char != 0:
            raise ValueError(
                f"BitVector length {self._len} not multiple of {bits_per_char}"
            )
        if self._len == 0:
            return ""
        value = self._as_int()
        if base == 2:
            return format(value, "0%db" % self._len)
        if base == 8:
            return format(value, "0%do" % (self._len // 3))
        if base == 16:
            return format(value, "0%dx" % (self._len // 4))
        chunk_table = _CHUNK_TO_DIGIT[base]
        bits01 = format(value, "0%db" % self._len)
        return "".join(
            chunk_table[bits01[i : i + bits_per_char]]
            for i in range(0, self._len, bits_per_char)
        )

    def tobase(
        self, base: int, sep: Optional[str] = None, bytes_per_sep: int = 1
    ) -> str:
        """
        Convert the BitVector to a string in a given base.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.

        Args:
            base (int): The base to convert to (a power of 2, at most 64).
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitVector converted to a string in the given base
        """
        if base not in {2, 4, 8, 16, 32, 64}:
            raise ValueError(f"Invalid base: {base}")
        retstring = self._to_base_str(base)
        bits_per_char = math.log2(base)
        chars_per_byte = int(8 / bits_per_char + 0.999999999)
        if sep is not None:
            chars_per_sep = int(chars_per_byte * bytes_per_sep)
            retstring = sep.join(
                retstring[i : i + chars_per_sep]
                for i in range(0, len(retstring), chars_per_sep)
            )
        return retstring

    def hex(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to a hexadecimal string prefixed by 0x.

        Args:
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitVector converted to a hexadecimal string
        """
        return "0x" + self.tobase(16, sep, bytes_per_sep)

    def oct(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to an octal string prefixed by 0o.

        Args:
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitVector converted to an octal string
        """
        return "0o" + self.tobase(8, sep, bytes_per_sep)

    def bin(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to a binary string prefixed by 0b.

        Args:
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitVector converted to a binary string
        """
        return "0b" + self.to01(sep, bytes_per_sep)

    def to01(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitVector to an unprefixed binary string.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.
        """
        if self._len == 0:
            plain = ""
        else:
            plain = format(self._as_int(), "0%db" % self._len)
        if sep is not None:
            bits_per_sep = 8 * bytes_per_sep
            return sep.join(
                plain[i : i + bits_per_sep] for i in range(0, len(plain), bits_per_sep)
            )
        return plain

    def to_chararray(
        self, encoding: Union[str, dict[BitsConstructible, str]] = "utf-8"
    ) -> str:
        """
        Convert the BitVector to a string where each byte is a character
        (for standard str encodings), or via greedy longest-prefix matching
        against an encoding mapping.

        Args:
            encoding (Union[str, dict[BitsConstructible, str]]): The encoding to use

        Returns:
            str: The BitVector converted to a string
        """
        cls = type(self)
        if isinstance(encoding, str):
            assert len(self) % 8 == 0, "BitVector length must be a multiple of 8\
                to use a standard encoding"
            return bytes(self).decode(encoding)
        else:
            encoding = {
                cls(bits_constructible).to01(): valstr
                for bits_constructible, valstr in encoding.items()
            }
            str_list = []
            subbitarray = ""
            for bit in self.to01():
                subbitarray += bit
                if subbitarray in encoding:
                    str_list.append(encoding[subbitarray])
                    subbitarray = ""
            return "".join(str_list)

    # Magic Methods and Overloads

    def __eq__(self, other: object) -> bool:
        """
        Returns whether this BitVector's bits are equal to another object's bits.
        This will only really be true if both objects are BitVectors.
        """
        if isinstance(other, BitVector):
            return self._len == other._len and self._buf == other._buf
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __lt__(self, other: BitVector) -> bool:
        """
        Returns True if, proceeding left-to-right, the first bit that differs
            is 0 in this BitVector and 1 in the other BitVector.
        """
        if isinstance(other, BitVector):
            return self.to01() < other.to01()
        return NotImplemented

    def __le__(self, other: BitVector) -> bool:
        if isinstance(other, BitVector):
            return self.to01() <= other.to01()
        return NotImplemented

    def __gt__(self, other: BitVector) -> bool:
        if isinstance(other, BitVector):
            return self.to01() > other.to01()
        return NotImplemented

    def __ge__(self, other: BitVector) -> bool:
        if isinstance(other, BitVector):
            return self.to01() >= other.to01()
        return NotImplemented

    def __add__(self: Self, other: BitsConstructible) -> Self:
        """
        Concatenation of a BitVector and something constructible to a BitVector.
           Non-commutative.
        """
        other = self.cast_if_not_bitvector(other)
        if self._len & 7 == 0:
            return type(self)._with_buf(
                self._buf + other._buf, self._len + other._len
            )
        nbits = self._len + other._len
        value = (self._as_int() << other._len) | other._as_int()
        return type(self)._with_buf(_pack_int(value, nbits), nbits)

    def __radd__(self: Self, other: BitsConstructible) -> Self:
        return type(self)(other) + self

    def __iadd__(self: Self, other: BitsConstructible) -> Self:
        if not isinstance(other, BitVector):
            other = BitVector(other)
        self._iconcat(other)
        return self

    def __mul__(self: Self, count: int) -> Self:
        """Concatenation of `count` copies of the BitVector."""
        if not isinstance(count, int):
            return NotImplemented
        if count <= 0 or self._len == 0:
            return type(self)._with_buf(bytearray(), 0)
        if self._len & 7 == 0:
            return type(self)._with_buf(self._buf * count, self._len * count)
        return type(self)._pack01chars(self.to01() * count)

    def __rmul__(self: Self, count: int) -> Self:
        return self.__mul__(count)

    def __imul__(self: Self, count: int) -> Self:
        if not isinstance(count, int):
            return NotImplemented
        product = self.__mul__(count)
        self._buf = product._buf
        self._len = product._len
        return self

    def _binary_bitwise_op(self: Self, other: BitsConstructible, op) -> Self:
        """Applies an equal-length elementwise binary operation
        against another BitsConstructible. `op` operates on whole ints,
        so the bit work happens in one C-level bignum operation."""
        if not isinstance(other, BitVector):
            other = type(self)(other)
        if other._len != self._len:
            raise ValueError("BitVectors of equal length expected")
        result = op(
            int.from_bytes(self._buf, "big"), int.from_bytes(other._buf, "big")
        )
        return type(self)._with_buf(
            bytearray(result.to_bytes(len(self._buf), "big")), self._len
        )

    def __and__(self: Self, other: BitsConstructible) -> Self:
        return self._binary_bitwise_op(other, operator.and_)

    def __rand__(self: Self, other: BitsConstructible) -> Self:
        return self & other

    def __iand__(self: Self, other: BitsConstructible) -> Self:
        return self & other

    def __or__(self: Self, other: BitsConstructible) -> Self:
        return self._binary_bitwise_op(other, operator.or_)

    def __ror__(self: Self, other: BitsConstructible) -> Self:
        return self | other

    def __ior__(self: Self, other: BitsConstructible) -> Self:
        return self | other

    def __xor__(self: Self, other: BitsConstructible) -> Self:
        return self._binary_bitwise_op(other, operator.xor)

    def __rxor__(self: Self, other: BitsConstructible) -> Self:
        return self ^ other

    def __ixor__(self: Self, other: BitsConstructible) -> Self:
        return self ^ other

    def __lshift__(self: Self, count: int) -> Self:
        """
        Left shift of the bits of a BitVector by `count` bits.
        The length is preserved; vacated positions on the right are
            filled with 0s.
        """
        if not isinstance(count, int):
            raise TypeError(f"count must be an int, not {type(count)}")
        if count < 0:
            raise ValueError("negative shift count")
        nbits = self._len
        if count >= nbits:
            return type(self)._with_buf(bytearray((nbits + 7) >> 3), nbits)
        return type(self)._with_buf(_pack_int(self._as_int() << count, nbits), nbits)

    def __ilshift__(self: Self, count: int) -> Self:
        return self << count

    def __rshift__(self: Self, count: int) -> Self:
        """
        Right shift of the bits of a BitVector by `count` bits.
        The length is preserved; vacated positions on the left are
            filled with 0s.
        """
        if not isinstance(count, int):
            raise TypeError(f"count must be an int, not {type(count)}")
        if count < 0:
            raise ValueError("negative shift count")
        nbits = self._len
        if count >= nbits:
            return type(self)._with_buf(bytearray((nbits + 7) >> 3), nbits)
        return type(self)._with_buf(_pack_int(self._as_int() >> count, nbits), nbits)

    def __irshift__(self: Self, count: int) -> Self:
        return self >> count

    def __invert__(self: Self) -> Self:
        """Bitwise inversion of the bits of the BitVector."""
        nbits = self._len
        if nbits == 0:
            return type(self)._with_buf(bytearray(), 0)
        return type(self)._with_buf(
            _pack_int(self._as_int() ^ ((1 << nbits) - 1), nbits), nbits
        )

    def _unpack_valbits(self) -> bytes:
        """Returns the bits as a bytes object of 0/1 byte values."""
        return self.to01().encode("ascii").translate(_CHARS_TO_VALBITS)

    def __iter__(self) -> Iterator[Literal[0, 1]]:
        """Iterate over the bits of the BitVector."""
        return iter(self._unpack_valbits())  # type: ignore

    def __format__(self, format_spec: str) -> str:
        """
        Format the BitVector as a binary ("b"), octal ("o"), or
        hexadecimal ("x") string, or as str(self) for the empty spec.
        """
        if format_spec == "b":
            return self.bin()
        elif format_spec == "o":
            return self.oct()
        elif format_spec == "x":
            return self.hex()
        elif format_spec == "":
            return str(self)
        else:
            raise ValueError(f"Invalid format specifier: {format_spec}")

    def __contains__(self, item: object) -> bool:
        """
        Returns whether the BitVector contains
            a given bit (int), subsequence (BitVector), or subsequence
            constructed from a non-int BitsConstructible; False otherwise.
        """
        if isinstance(item, int):
            if item not in {0, 1}:
                return False
            item = BitVector([item])  # type: ignore
        elif not isinstance(item, BitVector):
            if is_instance_of_union(item, BitsConstructible):
                item = BitVector(item)  # type: ignore
            else:
                return False
        assert isinstance(item, BitVector)
        first_index = self.find(item)
        return first_index != -1

    @overload
    def __getitem__(self, key: int) -> Literal[0, 1]: ...

    @overload
    def __getitem__(self: Self, key: slice) -> Self: ...

    @overload
    def __getitem__(self: Self, key: Iterable[int]) -> Self: ...

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, int):
            nbits = self._len
            if key < 0:
                key += nbits
            if not 0 <= key < nbits:
                raise IndexError("BitVector index out of range")
            return (self._buf[key >> 3] >> (7 - (key & 7))) & 1
        elif isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            if step == 1:
                length = max(stop - start, 0)
                return type(self)._with_buf(self._slice_packed(start, length), length)
            return type(self)._pack01chars(self.to01()[key])
        elif isinstance(key, Iterable):
            return type(self)([self[i] for i in key])
        else:
            raise TypeError(f"Invalid key type: {type(key)}")

    def _set_bit(self, key: int, bit: int) -> None:
        """Sets one bit, normalizing negative indices and bounds-checking."""
        nbits = self._len
        if key < 0:
            key += nbits
        if not 0 <= key < nbits:
            raise IndexError("BitVector index out of range")
        position = 7 - (key & 7)
        if bit:
            self._buf[key >> 3] |= 1 << position
        else:
            self._buf[key >> 3] &= ~(1 << position) & 0xFF

    def __setitem__(  # type: ignore[override]
        self,
        key: Union[int, slice, Sequence[int]],
        value: Union[Literal[0, 1], BitsConstructible],
    ) -> None:
        """
        Set the bit at a given index
           or the bits across the indices given in slice or Sequence form.

        An individual bit can be set with a BitsConstructible of length 1.

        A slice or sequence of indices can be set either with a single bit
           (setting every indexed position to that bit) or with a
           BitsConstructible (matching positions elementwise; for non-unit
           slice steps and index sequences, the lengths must agree).
        """
        if isinstance(key, int):
            if not isinstance(value, int):
                value = BitVector(value)[0]
            self._set_bit(key, _coerce_bit(value))
        elif isinstance(key, slice):
            if isinstance(value, int):
                bit = _coerce_bit(value)
                fill_length = len(range(*key.indices(self._len)))
                chars = self._to01_bytearray()
                chars[key] = (b"1" if bit else b"0") * fill_length
                self._reset01(chars)
            else:
                value = self.cast_if_not_bitvector(value)
                chars = self._to01_bytearray()
                # bytearray handles resizing for unit-step slices and
                # enforces matching lengths for extended slices
                chars[key] = value.to01().encode("ascii")
                self._reset01(chars)
        elif isinstance(key, Iterable):
            indices = list(key)
            if isinstance(value, int):
                bit = _coerce_bit(value)
                for index in indices:
                    self._set_bit(index, bit)
            else:
                value = self.cast_if_not_bitvector(value)
                if len(value) != len(indices):
                    raise ValueError(
                        f"attempt to assign sequence of size {len(value)}"
                        f" to {len(indices)} indices"
                    )
                for index, bit in zip(indices, value):
                    self._set_bit(index, bit)
        else:
            raise TypeError(f"Invalid key type: {type(key)}")

    def __delitem__(self, key: Union[int, slice, Iterable[int]]) -> None:
        """
        Delete the bit at a given index
           or the bits across the indices given in slice or Iterable form.

        Args:
            key (Union[int, slice, Iterable[int]]): The index/indices of
                the bit(s) to delete.
        """
        if isinstance(key, int):
            nbits = self._len
            if key < 0:
                key += nbits
            if not 0 <= key < nbits:
                raise IndexError("BitVector index out of range")
            tail = nbits - key - 1
            value = self._as_int()
            spliced = ((value >> (tail + 1)) << tail) | (value & ((1 << tail) - 1))
            self._buf = _pack_int(spliced, nbits - 1)
            self._len = nbits - 1
        elif isinstance(key, slice):
            chars = self._to01_bytearray()
            del chars[key]
            self._reset01(chars)
        elif isinstance(key, Iterable):
            length = self._len
            indices = {index if index >= 0 else index + length for index in key}
            chars = self._to01_bytearray()
            for index in sorted(indices, reverse=True):
                del chars[index]
            self._reset01(chars)
        else:
            raise TypeError(f"Invalid key type: {type(key)}")

    def __len__(self) -> int:
        """Get the number of bits in the BitVector."""
        return self._len

    def __str__(self) -> str:
        """
        Get a string representation of the BitVector.
            This is e.g. "type(self)('010.....')".
        """
        zerosandones = self.to01()
        zeroesandoneslist = [
            zerosandones[i : i + 8] for i in range(0, len(zerosandones), 8)
        ]
        return f"{type(self).__name__}" f"('{' '.join(zeroesandoneslist)}')"

    def __repr__(self) -> str:
        """
        Get a reconstructible representation of the BitVector.
            This is e.g. "type(self)('010.....')".
        """
        zerosandones = self.to01()
        zeroesandoneslist = [
            zerosandones[i : i + 8] for i in range(0, len(zerosandones), 8)
        ]
        return f"{type(self).__name__}" f"('{' '.join(zeroesandoneslist)}'" f")"

    def __bytes__(self) -> bytes:
        """
        Convert the BitVector to a bytes object.
        If the length of the BitVector is not a multiple of 8,
            the BitVector is padded with 0s until the length is a multiple of 8.
        """
        return self.tobytes()

    def tobytes(self) -> bytes:
        """
        Convert the BitVector to a bytes object, with each group of 8 bits
            (most-significant first) becoming a byte.
        If the length of the BitVector is not a multiple of 8,
            the BitVector is padded with 0s until the length is a multiple of 8.
        """
        # The zero-padding invariant makes this a straight buffer copy.
        return bytes(self._buf)

    def __Bits__(self: Self) -> Self:
        """
        Implementation of the BitsCastable protocol.
        Returns a BitVector version of the object.
        """
        return copy.copy(self)

    def __copy__(self: Self) -> Self:
        """Returns a shallow copy of the object with the same bits."""
        return type(self)._with_buf(bytearray(self._buf), self._len)

    def __deepcopy__(self: Self, memo: dict[int, object]) -> Self:
        """Returns a deep copy of the object with the same bits."""
        retval = type(self)._with_buf(bytearray(self._buf), self._len)
        memo[id(self)] = retval
        return retval

    def __sizeof__(self) -> int:
        """
        Get the size of the BitVector in bytes, including the packed
        internal buffer (which stores 8 bits per byte).
        """
        return super().__sizeof__() + sys.getsizeof(self._buf)

    # Basic Operations

    def append(self, value: LaxLiteral01) -> None:
        """
        Appends the provided bit to end (right) of the BitVector.

        Args:
            value (int): The bit to append
        """
        bit = _coerce_bit(value)
        offset = self._len & 7
        if offset == 0:
            self._buf.append(bit << 7)
        elif bit:
            self._buf[-1] |= 1 << (7 - offset)
        self._len += 1

    def extend(  # type: ignore[reportIncompatibleMethodOverride]
        self, values: BitsConstructible
    ) -> None:
        """Extends the BitVector with the provided bits (appends them
        on the right).

        Args:
            values (BitsConstructible): The bits to append
        """
        if not isinstance(values, Iterable) or isinstance(values, str):
            values = BitVector(values)
        if isinstance(values, BitVector):
            self._iconcat(values)
        else:
            buf, nbits = _pack_valbits(_valbits_from_iterable(values))
            self._iconcat(BitVector._with_buf(buf, nbits))

    def insert(  # type: ignore[reportIncompatibleMethodOverride]
        self, index: int, value: LaxLiteral01
    ) -> None:
        """Inserts the provided bit at the given index (zero-indexed).
        All bits at or to the right of the index are shifted right.

        Args:
            index (int): The index at which to insert the bit
            value (int): The bit to insert
        """
        bit = _coerce_bit(value)
        nbits = self._len
        if index < 0:
            index += nbits
        index = 0 if index < 0 else (nbits if index > nbits else index)
        tail = nbits - index
        value_int = self._as_int()
        spliced = ((((value_int >> tail) << 1) | bit) << tail) | (
            value_int & ((1 << tail) - 1)
        )
        self._buf = _pack_int(spliced, nbits + 1)
        self._len = nbits + 1

    def pop(  # type: ignore[reportIncompatibleMethodOverride]
        self, index: Optional[int] = None, default: Optional[T] = None
    ) -> Union[int, T]:
        """Removes and returns the bit at the given index (zero-indexed).
        If the provided index is None, the rightmost bit is popped.
        If a default is provided and the index is out of bounds,
        the default is returned; negative indices are treated as
        out of bounds.

        Args:
            index (Optional[int], optional): The position of the bit to pop.
                Defaults to None.
            default (Optional[T], optional): The default value to return if the
                index is out of bounds. Defaults to None.

        Raises:
            IndexError: If the index is out of bounds and no default is provided.

        Returns:
            Union[int, T]: The bit at the given index or the default value
        """
        if index is None:
            index = len(self) - 1
        if index >= len(self) or index < 0:
            if default is not None:
                return default
            raise IndexError("pop from empty BitVector")
        value = self[index]
        if index == self._len - 1:
            self._len -= 1
            needed = (self._len + 7) >> 3
            if len(self._buf) > needed:
                del self._buf[-1]
            else:
                tail = self._len & 7
                if tail:
                    self._buf[-1] &= (0xFF << (8 - tail)) & 0xFF
        else:
            del self[index]
        return value

    def remove(self, value: LaxLiteral01) -> None:
        """Removes the first occurrence of the provided bit from the BitVector.

        Args:
            value (int): The bit to remove

        Raises:
            ValueError: If the bit is not found in the BitVector
        """
        index = self.find(_coerce_bit(value))
        if index == -1:
            raise ValueError(f"{value} is not in BitVector")
        del self[index]

    def clear(self) -> None:
        """Removes all bits from the BitVector."""
        self._buf.clear()
        self._len = 0

    def copy(self: Self) -> Self:
        """Returns a shallow copy of the BitVector."""
        return self.__copy__()

    def reverse(self) -> None:
        """Reverses the bits in the BitVector."""
        if self._len:
            self._reset01(self.to01()[::-1])

    # Search and Analysis

    def count(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        end: Optional[int] = None,
    ) -> int:
        """
        Counts the occurrences of the given bit (or non-overlapping
        subsequence) in the BitVector between the given start (inclusive)
        and end (exclusive) indices.

        Args:
            value (Union[BitsConstructible, int]): The bit or subsequence to count
            start (int, optional): The start index. Defaults to 0.
            end (Optional[int], optional): The end index. Defaults to None.

        Returns:
            int: The number of occurrences of the bit or subsequence
                (within the provided index range, if any)
        """
        if end is None:
            end = len(self)
        if isinstance(value, int):
            bit = _coerce_bit(value)
            start_n, end_n, _ = slice(start, end).indices(self._len)
            length = end_n - start_n
            if length <= 0:
                return 0
            ones = _popcount(self._extract_int(start_n, length))
            return ones if bit else length - ones
        if not isinstance(value, BitVector):
            value = BitVector(value)
        return self.to01().count(value.to01(), start, end)

    def startswith(
        self,
        substrings: Union[
            BitsConstructible,
            BitVector,
            Literal[0, 1],
            Iterable[Union[BitsConstructible, BitVector]],
        ],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> bool:
        """
        Checks if the BitVector starts with the given substring(s),
        optionally restricted to the [start, stop) bit range.

        Args:
            substrings: The substring(s) to check (a single BitsConstructible
                or bit, or an iterable of them).
            start (int, optional): The start index. Defaults to 0.
            stop (Optional[int], optional): The stop index. Defaults to None.
        """
        conv_substrings = self._normalize_substrings(substrings)

        if stop is None:
            stop = len(self)
        start, stop = max(0, start), min(len(self), stop)

        if any(len(conv_substring) == 0 for conv_substring in conv_substrings):
            return True

        return any(
            len(conv_substring) <= stop - start
            and self._extract_int(start, conv_substring._len)
            == conv_substring._as_int()
            for conv_substring in conv_substrings
        )

    def endswith(
        self,
        substrings: Union[
            BitsConstructible,
            BitVector,
            Literal[0, 1],
            Iterable[Union[BitsConstructible, BitVector]],
        ],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> bool:
        """
        Checks if the BitVector ends with the given substring(s),
        optionally restricted to the [start, stop) bit range.

        Args:
            substrings: The substring(s) to check (a single BitsConstructible
                or bit, or an iterable of them).
            start (int, optional): The start index. Defaults to 0.
            stop (Optional[int], optional): The stop index. Defaults to None.
        """
        conv_substrings = self._normalize_substrings(substrings)

        if stop is None:
            stop = len(self)
        start, stop = max(0, start), min(len(self), stop)

        if any(len(conv_substring) == 0 for conv_substring in conv_substrings):
            return True

        return any(
            len(conv_substring) <= stop - start
            and self._extract_int(stop - conv_substring._len, conv_substring._len)
            == conv_substring._as_int()
            for conv_substring in conv_substrings
        )

    @staticmethod
    def _normalize_substrings(
        substrings: Union[
            BitsConstructible,
            BitVector,
            Literal[0, 1],
            Iterable[Union[BitsConstructible, BitVector]],
        ],
    ) -> list[BitVector]:
        """Converts the substring(s) accepted by startswith/endswith into
        a list of BitVectors. A bare iterable of ints is interpreted as a
        single substring; other iterables are interpreted as collections
        of substrings."""
        if isinstance(substrings, BitVector):
            return [substrings]
        elif isinstance(substrings, int):
            return [BitVector([substrings])]
        elif isinstance(substrings, (str, bytes, BitsCastable)):
            return [BitVector(substrings)]
        elif isinstance(substrings, Iterable):
            list_of_substrings = list(substrings)
            if all(isinstance(substring, int) for substring in list_of_substrings):
                return [BitVector(list_of_substrings)]  # type: ignore
            elif all(
                is_instance_of_union(substring, BitsConstructible)
                for substring in list_of_substrings
            ):
                return [
                    BitVector(substring)  # type: ignore
                    for substring in list_of_substrings
                ]
            else:
                raise ValueError("Invalid type in provided iterable")
        else:
            raise TypeError(f"Invalid substrings type: {type(substrings)}")

    def find(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        """Finds the first occurrence of the given bit (or subsequence of
        bits) in the BitVector, returning -1 when absent.

        Args:
            value (Union[BitsConstructible, int]): The bit or subsequence to find
            start (int, optional): The initial index to search. Defaults to 0.
            stop (Optional[int], optional): The index to give up on.
                Defaults to None.

        Returns:
            int: The index of the first occurrence, or -1 if not found
        """
        if stop is None:
            stop = self._len
        if isinstance(value, int):
            bit = _coerce_bit(value)
            if start == 0 and stop == self._len:
                nbits = self._len
                if nbits == 0:
                    return -1
                value_int = self._as_int()
                if bit == 0:
                    value_int ^= (1 << nbits) - 1
                if value_int == 0:
                    return -1
                return nbits - value_int.bit_length()
            return self.to01().find("1" if bit else "0", start, stop)
        if not isinstance(value, BitVector):
            value = BitVector(value)
        return self.to01().find(value.to01(), start, stop)

    def rfind(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        """Finds the last occurrence of the given bit (or subsequence of
        bits) in the BitVector, returning -1 when absent.

        Args:
            value (Union[BitsConstructible, int]): The bit or subsequence to find
            start (int, optional): The initial index to search. Defaults to 0.
            stop (Optional[int], optional): The index to give up on.
                Defaults to None.

        Returns:
            int: The index of the last occurrence, or -1 if not found
        """
        if stop is None:
            stop = self._len
        if isinstance(value, int):
            bit = _coerce_bit(value)
            if start == 0 and stop == self._len:
                nbits = self._len
                if nbits == 0:
                    return -1
                value_int = self._as_int()
                if bit == 0:
                    value_int ^= (1 << nbits) - 1
                if value_int == 0:
                    return -1
                trailing_zeros = (value_int & -value_int).bit_length() - 1
                return nbits - 1 - trailing_zeros
            return self.to01().rfind("1" if bit else "0", start, stop)
        if not isinstance(value, BitVector):
            value = BitVector(value)
        return self.to01().rfind(value.to01(), start, stop)

    def index(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        """Like find, but raises ValueError when the bit(s) are absent.

        Args:
            value (Union[BitsConstructible, int]): The bit or subsequence to find
            start (int, optional): The initial index to search. Defaults to 0.
            stop (Optional[int], optional): The index to give up on.
                Defaults to None.

        Raises:
            ValueError: If the bit or subsequence is not found

        Returns:
            int: The index of the first occurrence
        """
        index = self.find(value, start, stop)
        if index == -1:
            raise ValueError(f"{value} is not in BitVector")
        return index

    def rindex(
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        """Like rfind, but raises ValueError when the bit(s) are absent.

        Args:
            value (Union[BitsConstructible, int]): The bit or subsequence to find
            start (int, optional): The initial index to search. Defaults to 0.
            stop (Optional[int], optional): The index to give up on.
                Defaults to None.

        Raises:
            ValueError: If the bit or subsequence is not found

        Returns:
            int: The index of the last occurrence
        """
        index = self.rfind(value, start, stop)
        if index == -1:
            raise ValueError(f"{value} is not in BitVector")
        return index

    # Modification and Translation

    def replace(
        self: Self,
        old: BitsConstructible,
        new: BitsConstructible,
        count: Optional[int] = None,
    ) -> Self:
        """
        Generates a new BitVector with occurrences of the sequences of
            old bits replaced by the new bits.
        If count is provided, only the first `count` occurrences are replaced.

        Args:
            old (BitsConstructible): The bits to replace
            new (BitsConstructible): The bits to replace with
            count (Optional[int], optional): The maximum number of replacements.
                Defaults to None (maximal replacement).

        Returns:
            Self: The new BitVector with the replacements made
        """
        if not isinstance(old, type(self)):
            old = type(self)(old)
        if not isinstance(new, type(self)):
            new = type(self)(new)

        if len(old) == 0:
            return self.copy()

        chars = self.to01()
        if count is None:
            replaced = chars.replace(old.to01(), new.to01())
        elif count <= 0:
            replaced = chars
        else:
            replaced = chars.replace(old.to01(), new.to01(), count)
        return type(self)._pack01chars(replaced)

    def join(self: Self, iterable: Iterable[BitsConstructible]) -> Self:
        """Concatenates the BitVectors in the iterable
        with self as the separator.

        Args:
            iterable (Iterable[BitsConstructible]): The BitVectors to concatenate.

        Returns:
            Self: A concatenation of the BitVectors in the iterable with
                self between them.
        """
        items = [
            item if isinstance(item, type(self)) else type(self)(item)
            for item in iterable
        ]
        joined = self.to01().join(item.to01() for item in items)
        return type(self)._pack01chars(joined)

    def partition(self: Self, sep: BitVector) -> tuple[Self, Self, Self]:
        """
        Partitions the BitVector into (before, separator, after) around the
        first occurrence of the separator; (self, empty, empty) when absent.

        Args:
            sep (BitVector): The separator BitVector

        Returns:
            tuple[Self, Self, Self]: The three parts of the partition
        """
        index = self.find(sep)
        if index == -1:
            return self, type(self)(), type(self)()

        self_to_index = self[:index]
        sep = type(self)(sep)
        self_after_offset = self[index + len(sep) :]
        return self_to_index, sep, self_after_offset

    def rpartition(self: Self, sep: BitVector) -> tuple[Self, Self, Self]:
        """
        Partitions the BitVector into (before, separator, after) around the
        last occurrence of the separator; (empty, empty, self) when absent.

        Args:
            sep (BitVector): The separator BitVector

        Returns:
            tuple[Self, Self, Self]: The three parts of the partition
        """
        index = self.rfind(sep)
        if index == -1:
            return type(self)(), type(self)(), self

        self_to_index = self[:index]
        sep = type(self)(sep)
        self_after_offset = self[index + len(sep) :]
        return self_to_index, sep, self_after_offset

    @staticmethod
    def _normalize_strip_bit(
        bits: Optional[Union[Literal[0], Literal[1]]],
    ) -> Optional[int]:
        """Reduces the `bits` argument of lstrip/rstrip/strip to
        None or a single int."""
        if not (bits is None or isinstance(bits, int)):
            if hasattr(bits, "__int__"):
                bits = int(bits)  # type: ignore
            elif isinstance(bits, Iterable):
                bits = int(next(iter(bits)))  # type: ignore
            else:
                bits = int(bits)  # type: ignore
        return bits

    def lstrip(
        self: Self, bits: Optional[Union[Literal[0], Literal[1]]] = None
    ) -> Self:
        """
        Returns a new BitVector with contiguous leading instances of the
            provided bit removed. Defaults to removing leading 0s.

        Args:
            bits (Optional[Union[Literal[0], Literal[1]]], optional):
                The bit to remove. Defaults to None, removing leading 0s.

        Returns:
            Self: The BitVector with the leading bits removed.
        """
        bits = self._normalize_strip_bit(bits)

        if bits is None or bits == 0:
            retvalindex = self.find(1)
        else:
            retvalindex = self.find(0)

        if retvalindex == -1:
            return type(self)()

        return self[retvalindex:]

    def rstrip(
        self: Self, bits: Optional[Union[Literal[0], Literal[1]]] = None
    ) -> Self:
        """
        Returns a new BitVector with contiguous trailing instances of the
            provided bit removed. Defaults to removing trailing 0s.

        Args:
            bits (Optional[Union[Literal[0], Literal[1]]], optional): The
                bit to remove. Defaults to None, removing trailing 0s.

        Returns:
            Self: The BitVector with the trailing bits removed.
        """
        bits = self._normalize_strip_bit(bits)

        if bits is None or bits == 0:
            retvalindex = self.rfind(1)
        else:
            retvalindex = self.rfind(0)

        if retvalindex == -1:
            return type(self)()

        return self[: retvalindex + 1]

    def strip(self: Self, bits: Optional[Union[Literal[0], Literal[1]]] = None) -> Self:
        """
        Returns a new BitVector with contiguous leading and trailing
            instances of the provided bit removed. Defaults to 0s.

        Args:
            bits (Optional[Union[Literal[0], Literal[1]]], optional): The
                bit to remove. Defaults to None, removing leading and trailing 0s.

        Returns:
            Self: A BitVector with the leading and trailing bits removed.
        """
        return self.lstrip(bits).rstrip(bits)

    def lpad(self: Self, width: int, fillbit: Literal[0, 1] = 0) -> Self:
        if len(self) >= width:
            return self
        bit = _coerce_bit(fillbit)
        pad = width - self._len
        fill_value = ((1 << pad) - 1) if bit else 0
        value = (fill_value << self._len) | self._as_int()
        return type(self)._with_buf(_pack_int(value, width), width)

    def rpad(self: Self, width: int, fillbit: Literal[0, 1] = 0) -> Self:
        if len(self) >= width:
            return self
        bit = _coerce_bit(fillbit)
        pad = width - self._len
        fill_value = ((1 << pad) - 1) if bit else 0
        value = (self._as_int() << pad) | fill_value
        return type(self)._with_buf(_pack_int(value, width), width)

    @classmethod
    def cast_if_not_bitvector(
        cls: type[Self], obj: BitsConstructible
    ) -> Union[Self, BitVector]:
        """Casts the object to a BitVector if it is not already a BitVector.

        Args:
            obj (BitsConstructible): The object to cast

        Returns:
            Union[Self, BitVector]: The object as a BitVector
        """
        return cls(obj) if not isinstance(obj, BitVector) else obj

    # Temporary methods. For transition from bits to bitarray only
    @classmethod
    def from_int(cls, integer: int, size: Optional[int] = None):
        """
        Converts an integer to a Bits object.
         The size parameter determines the number of bits to use.\
         If size is not provided, the number of bits required to \
         represent the integer is used.
        """
        if size is None:
            size = twos_complement_bit_length(integer)
        if integer.bit_length() > size:
            raise ValueError(
                f"Cannot convert {integer} to Bits with size {size},"
                f" because it requires {integer.bit_length()} bits to represent."
            )

        return cls._with_buf(_pack_int(integer, size), size)

    @classmethod
    def from_bytes(cls, byte_arr: bytes, reverse_endianness=False):
        if reverse_endianness:
            byte_arr = bytes(reversed(byte_arr))

        return cls(byte_arr)

    def to_int(self, endianness: Literal["big", "little"] = "big", signed=True) -> int:
        """
        Converts a Bits object to an integer. It does this
            by casting the Bits to bytes, and then converting the bytes to an integer
            using the provided endianness and signedness.
        """
        source = self
        if signed and self._len > 0 and self[0] == 1:
            next_multiple_of_8 = math.ceil(len(self) / 8) * 8
            source = self.lpad(width=next_multiple_of_8, fillbit=1)

        return int.from_bytes(source.to_bytes(), byteorder=endianness, signed=signed)

    def to_bytes(self, reverse_endianness=False) -> bytes:
        full_bytes, tail = divmod(self._len, 8)
        byte_arr = bytearray(self._buf[:full_bytes])
        if tail:
            # A trailing partial byte is right-aligned within its byte,
            # matching the historical accumulate-without-final-shift behavior.
            byte_arr.append(self._buf[full_bytes] >> (8 - tail))

        if reverse_endianness:
            byte_arr.reverse()
        return bytes(byte_arr)


BitsConstructible = Union[BitVector, bytes, str, Iterable[LaxLiteral01], BitsCastable]
"""
The types that can be used to construct a BitVector.
These include the BitVector class itself, bytes, str, iterables of 0s and 1s,
and objects that can be cast to a BitVector.

Please note that you can also use an int to construct a BitVector of that many
zeroes, but this is not included in the type hint because it is less implicitly
a series of bits.
"""
