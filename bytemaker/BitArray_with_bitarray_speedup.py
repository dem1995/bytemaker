from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING

from bitarray import bitarray
from bitarray.util import ba2base, base2ba

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
    from bytemaker.utils import Trie, is_instance_of_union
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
    from utils import Trie, is_instance_of_union

if TYPE_CHECKING:
    Self = TypeVar("Self", bound="BitArray")
else:
    try:
        from typing_redirect import Self
    except ImportError:
        Self = TypeVar("Self", bound="BitArray")
T = TypeVar("T")


@runtime_checkable
class BitsCastable(Protocol):
    """
    Protocol for objects that can be cast to a BitArray.

    If provided object is not itself a BitArray, this protocol will be
       prioritized when BitArraySubtype(object) is called
       over any other possible behavior.

    __Bits__ returns a BitArray representation of the object
        that should not be a shallow copy (unless you want)
        the cast object to share memory with the original object).
    """

    def __Bits__(
        self,
    ) -> BitArray:
        """
        Returns a deep BitArray representation of the object.

        This method is prioritized when BitArraySubtype(object) is called.

        Returns:
            BitArray: The BitArray representation of the object
        """
        ...


__annotations__ = {
    "BitsConstructible": 'Union["BitArray", bytes, str, Iterable[Literal[0, 1]]'
    ", BitsCastable, bitarray.bitarray]"
}  # Warning! Long-term support for bitarray is not guaranteed
"""The Union of types that can be used to construct a BitArray."""


class BitArray(bitarray, MutableSequence[Literal[0, 1]]):
    """
    A mutable sequence of bits.

    This class's behavior is largely a superset of that of bytearray.
       excepting certain methods that are not applicable to bits.

    This particular implementation is currently a
        subclass of bitarray, which provides C-level performance for bit manipulation.

    However, only the behavior documented here (that is, that does not stem
        from the bitarray superclass) is guaranteed
    """

    def __new__(
        cls: type[Self],
        source: Optional[Union[BitsConstructible, int]] = None,
        buffer: Optional[Buffer] = None,
        *args,
        **kwargs,
    ) -> Self:
        """
        Constructs a BitArray.
        * The bits are drawn from `buffer`, else `source`.

        If `buffer` is set, the BitArray bit memory is shared with provided
            object. The buffer object must support the buffer protocol
            (https://docs.python.org/3/c-api/buffer.html).

        Otherwise, `source` determines the BitArray's bits.
        * If `source` is  None, the BitArray is empty.
        * If `source` is a str, the bits are obtained by prefix-determined classmethod\
           that allow `source` to be interspersed with "_", "-", " ", or ":" characters.
           * "" invokes `from01`
           * "0b" invokes `frombin`
           * "0o" invokes `fromoct`
           * "0x" invokes `fromhex`
        * If `source` is an int, the BitArray is created with that many bits (set to 0).

        Args:
            source (Optional[Union[BitsConstructible, int]]): The bits of the bitarray
            * If None, a BitArray with no bits is created.
            * If a string, uses the prefix (none, 0b, 0o, or 0x) to call\
                    (`from01`, `frombin`, `fromoct`, `fromhex`).\
            * If an int, a BitArray with that many bits (set to 0) is created.\
            encoding (Optional[str]): The encoding to use (NOT IMPLEMENTED)
            errors (Optional[str]): The error handling to use for encoding \
                (not implemented)
            buffer (Buffer): The buffer to use

        """

        # Buffer constructor
        # If buffer is not none, then this BitArray
        # shares its memory with the object given in the buffer
        # Buffer objects must support the buffer protocol
        #   (https://docs.python.org/3/c-api/buffer.html)
        if buffer is not None:
            self: Self = super().__new__(
                cls,
                buffer=memoryview(buffer),  # type: ignore[reportCallIssue]
            )
            return self
        # Default constructor
        # If source is None, then this BitArray is empty
        elif source is None:
            self: Self = super().__new__(
                cls,
                [],  # type: ignore[reportCallIssue]
            )
            return self
        # Copy constructor
        elif isinstance(source, bitarray):
            self: Self = super().__new__(cls, source)  # type: ignore[reportCallIssue]
            return self
        # BitsCastable constructor
        elif isinstance(source, BitsCastable):
            curinstance = source.__Bits__()
            self: Self = super().__new__(
                cls, buffer=curinstance  # type: ignore[reportCallIssue]
            )
            return self

        # String constructor
        if isinstance(source, str):
            if source.startswith("0b"):
                self: Self = cls.frombin(source)
            elif source.startswith("0o"):
                self: Self = cls.fromoct(source)
            elif source.startswith("0x"):
                self: Self = cls.fromhex(source)
            else:
                self: Self = cls.from01(source)
            return self

        # Int constructor
        if isinstance(source, int):
            self: Self = cls.fromsize(source)
            return self

        if isinstance(source, (bytes, bytearray)):
            self: Self = cls(buffer=source)
            return self

        if isinstance(source, Iterable):
            self: Self = super().__new__(
                cls,
                source,  # type: ignore[reportCallIssue]
            )
            assert isinstance(self, cls)
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
        If `buffer` is not None, the BitArray bit memory is shared with provided
            buffer object. The buffer object must support the buffer protocol
            (https://docs.python.org/3/c-api/buffer.html).

        Otherwise, `source` determines the BitArray's bits.
        * If `source` is None, the BitArray is empty.
        * If `source` is a str, the bits are obtained by prefix-determined classmethod
           * "" invokes `from01`
           * "0b" invokes `frombin`
           * "0o" invokes `fromoct`
           * "0x" invokes `fromhex`
        * If `source` is an int, the BitArray is created with that many bits set to 0.

        Args:
            source (Optional[Union[BitsConstructible, int]]): The bits of the bitarray
               If None, a BitArray with no bits is created.\
               If a string, uses the prefix (none, 0b, 0o, or 0x) to call\
                    (`from01`, `frombin`, `fromoct`, `fromhex`).\
                If an int, a BitArray with that many bits (set to 0) is created.\
            encoding (Optional[str]): The encoding to use
            errors (Optional[str]): The error handling to use. TODO
            buffer (Buffer): The buffer to use

        """
        super().__init__()

    # Transformations
    @classmethod
    def fromhex(
        cls: type[Self],
        string: str,
    ) -> Self:
        """
        Create a BitArray from a hexadecimal string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string may start with "0x".

        Args:
            string (str): The hexadecimal string to convert

        Returns:
            BitArray: The BitArray created from the hexadecimal string
        """
        string = string.translate(str.maketrans("", "", "_- :"))
        if string.startswith("0x"):
            string = string[2:]
        bit_array = base2ba(16, string)[: 4 * len(string)]
        return cls(bit_array)

    @classmethod
    def fromoct(
        cls: type[Self],
        string: str,
    ) -> Self:
        """
        Create a BitArray from an octal string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string may start with "0o".

        Args:
            string (str): The octal string to convert

        Returns:
            BitArray: The BitArray created from the octal string
        """
        string = string.translate(str.maketrans("", "", "_- :"))
        if string.startswith("0o"):
            string = string[2:]
        bit_array = base2ba(8, string)[: 3 * len(string)]
        return cls(bit_array)

    @classmethod
    def frombin(
        cls: type[Self],
        string: str,
    ) -> Self:
        """
        Create a BitArray from a binary string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string may start with "0b".

        Args:
            string (str): The binary string to convert

        Returns:
            BitArray: The BitArray created from the binary string
        """
        if string.startswith("0b"):
            string = string[2:]
        return cls.from01(string)

    @classmethod
    def from01(
        cls: type[Self],
        string: str,
    ) -> Self:
        """
        Create a BitArray from a binary string.
        The string may contain any of '_', '-', ' ', or ':'.
        The string must contain only 0s and 1s other than these.

        Args:
            string (str): The binary string to convert

        Returns:
            BitArray: The BitArray created from the binary string
        """
        string = string.translate(str.maketrans("", "", "_- :"))
        bit_array = bitarray(string)
        return cls(bit_array)

    @classmethod
    def fromsize(
        cls: type[Self],
        size: int,
        /,  # We do not know what the name in PEP 467 will be
    ) -> Self:
        """
        Create a BitArray with `size` bits, all set to 0.

        Args:
            size (int): The size of the BitArray to create

        Returns:
            BitArray: The BitArray created with the given size
        """
        source: list[Literal[0, 1]] = [0] * size
        return cls(source)

    @classmethod
    def frombase(
        cls: type[Self],
        string: str,
        base: int,
    ) -> Self:
        """
        Create a BitArray from a string in a given base.
        The string may contain any of '_', '-', ' ', or ':'.
        In the case of bases 2, 8, and 16,
            the string may start with "0b", "0o", or "0x" respectively.

        Args:
            string (str): The string to convert
            base (int): The base of the string

        Returns:
            BitArray: The BitArray created from the string
        """
        if base == 2:
            return cls.frombin(string)

        elif base == 8:
            return cls.fromoct(string)

        elif base == 16:
            return cls.fromhex(string)

        string = string.translate(str.maketrans("", "", "_- :"))
        bit_array = base2ba(base, string)
        return cls(bit_array)

    # @classmethod
    # def from_bytes(
    #         cls: type[Self],
    #         bytes: bytes,
    #         endianness: Literal["little", "big"] = "big") -> Self:
    #     """
    #     Create a BitArray from a bytes object.

    #     Args:
    #         bytes (bytes): The bytes object to convert
    #         endianness (Literal["little", "big"]): The endianness of the BitArray

    #     Returns:
    #         BitArray: The BitArray created from the bytes object
    #     """
    #     return cls(bytes, endianness=endianness)

    # @classmethod
    # def frombytes(*args, **kwargs):
    #     raise Warning("frombytes is not implemented. Use from_bytes instead.")

    @classmethod
    def from_chararray(
        cls: type[Self],
        char_array: str,
        encoding: Union[str, dict[str, BitsConstructible]] = "utf-8",
    ) -> Self:
        """
        Create a BitArray from a `char_array` string where each character is a byte.
        The string is encoded using the given `encoding`. If this is a standard
           byte encoding, str.encode is used to convert the string to bytes.
        Otherwise, the string is converted to bytes using the given mapping,
            iterating over the `char_array` and building up substrings
            until a substring is found in the encoding mapping to convert to
            a BitArray. These converted BitArrays are concatenated together
            to form the final returned BitArray.

        Args:
            char_array (str): The string to convert
            encoding (Union[str, dict[str, BitsConstructible]]): The encoding to use

        Returns:
            BitArray: The BitArray created from the string
        """
        if isinstance(encoding, str):
            char_array_as_bytes: bytes = char_array.encode(encoding)

            retval = cls(buffer=char_array_as_bytes)

            # retval.frombytes()
            print("using standard encoding...")
            # print(char_array.encode(encoding))
            print("retval", retval)
            return retval
        else:
            bitarray_list: list[cls] = []
            substring = ""
            for char in char_array:
                substring += char
                if substring in encoding:
                    bitarray_list.append(cls(encoding[substring]))
                    substring = ""
            bitarray_catted = cls()
            for bitarray_single in bitarray_list:
                bitarray_catted += bitarray_single
            return bitarray_catted

    def tobase(
        self, base: int, sep: Optional[str] = None, bytes_per_sep: int = 1
    ) -> str:
        """
        Convert the BitArray to a string in a given base.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.

        Args:
            base (int): The base to convert to. Currently must be a power of 2 (< 64).
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitArray converted to a string in the given base
        """
        # TODO support non-multiple-of-two bases
        if base not in {2, 4, 8, 16, 32, 64}:
            raise ValueError(f"Invalid base: {base}")
        retstring = ba2base(base, self)
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
        Convert the BitArray to a hexadecimal string prefixed by 0x.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.

        Args:
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitArray converted to a hexadecimal string
        """

        retval = "0x" + self.tobase(16, sep, bytes_per_sep)
        return retval

    def oct(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitArray to an octal string prefixed by 0x.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.

        Args:
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitArray converted to an octal string
        """
        retval = "0o" + self.tobase(8, sep, bytes_per_sep)
        return retval

    def bin(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitArray to a binary string prefixed by 0x.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.

        Args:
            sep (Optional[str]): The separator to use
            bytes_per_sep (int): The number of bytes per separator

        Returns:
            str: The BitArray converted to a binary string
        """
        return "0b" + self.to01(sep, bytes_per_sep)

    def to01(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
        """
        Convert the BitArray to an unprefixed binary string.
        If `sep` is not None, the string is split into chunks of `bytes_per_sep` bytes
           punctuated by `sep`.
        """

        to01_without_sep = super().to01()
        bits_per_sep = 8 * bytes_per_sep
        if sep is not None:
            return sep.join(
                to01_without_sep[i : i + bits_per_sep]
                for i in range(0, len(to01_without_sep), bits_per_sep)
            )
        return to01_without_sep

    def to_chararray(
        self, encoding: Union[str, dict[BitsConstructible, str]] = "utf-8"
    ) -> str:
        """
        Convert the BitArray to a string where each byte is a character.
        The string is decoded using the given `encoding`. If this is a standard
           byte encoding, bytes.decode is used to convert the bytes to a string.
        Otherwise, the bytes are converted to strings using the given mapping.

        Args:
            encoding (Union[str, dict[BitsConstructible, str]]): The encoding to use

        Returns:
            str: The BitArray converted to a string
        """
        cls = type(self)
        if isinstance(encoding, str):
            assert (
                len(self) % 8 == 0
            ), "BitArray length must be a multiple of 8\
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

    # def hex(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
    #     retstring = ba2base(16, self)
    #     if sep is not None:
    #         retstring = sep.join(
    #             retstring[i: i + bytes_per_sep]
    #             for i in range(0, len(retstring), bytes_per_sep)
    #         )
    #     return retstring

    # def oct(self) -> str:
    #     return ba2base(8, self)

    # def bin(self) -> str:
    #     return ba2base(2, self)

    # def to_base(self, base: int) -> str:
    #     return ba2base(base, self)

    # Magic Methods and Overloads
    def __eq__(self, other: object) -> bool:
        """
        Returns whether this BitArray's bits are equal to another object's bits.
        This will only really true if both objects are BitArrays.
        """
        return super().__eq__(other)

    def __ne__(self, other: object) -> bool:
        """
        Returns whether this BitArray's bits are not equal to another object's bits.
        This will only really be false if both objects are BitArrays.
        """
        return super().__ne__(other)

    def __lt__(self, other: bitarray) -> bool:
        """
        Returns True if, proceeding left-to-right, the first bit that differs
            is 0 in this BitArray and 1 in the other BitArray.
        """
        return super().__lt__(other)

    def __le__(self, other: bitarray) -> bool:
        """
        Returns True if, proceeding left-to-right, the first bit that differs
            is 0 in this BitArray and 1 in the other BitArray.
            or no bits differ.
        """
        return super().__le__(other)

    def __gt__(self, other: bitarray) -> bool:
        """
        Returns True if, proceeding left-to-right, the first bit that differs
            is 1 in this BitArray and 0 in the other BitArray.
        """
        return super().__gt__(other)

    def __ge__(self, other: bitarray) -> bool:
        """
        Returns True if, proceeding left-to-right, the first bit that differs
            is 1 in this BitArray and 0 in the other BitArray.
            or no bits differ.
        """
        return super().__ge__(other)

    def __add__(self: Self, other: BitsConstructible) -> Self:
        """
        Concatenation of a BitArray and something constructible to a BitArray.
           Non-commutative.
        """
        if not isinstance(other, bitarray):
            other: Union[BitArray, Self] = self.cast_if_not_bitarray(other)
        summation = super().__add__(other)
        assert isinstance(summation, type(self))
        return summation

    def __radd__(self: Self, other: BitsConstructible) -> Self:
        """
        Concatenation of something constructible to a BitArray and a BitArray.
           Non-commutative.
        """
        return type(self)(other) + self

    def __iadd__(self: Self, other: BitsConstructible) -> Self:
        """
        In-place concatenation of a BitArray and something constructible to a BitArray.
        """
        if not isinstance(other, bitarray):
            other = BitArray(other)
        summation = super().__iadd__(other)
        assert isinstance(summation, type(self))
        return summation

    def __mul__(self: Self, count: int) -> Self:
        """
        Concatenation of `count` copies of the BitArray.
        """
        product = super().__mul__(count)
        assert isinstance(product, type(self))
        return product

    def __rmul__(self: Self, count: int) -> Self:
        """
        Concatenation of `count` copies of the BitArray.
        """
        product = self.__mul__(count)
        return product

    def __imul__(self: Self, count: int) -> Self:
        """
        In-place assignment of the concatenation of `count` copies of the BitArray.
        """
        product = super().__imul__(count)
        assert isinstance(product, type(self))
        return product

    def __and__(self: Self, other: BitsConstructible) -> Self:
        """
        Bitwise AND of the bits of a BitArray and something constructible to a BitArray.
        """
        conjunction = super().__and__(type(self)(other))
        assert isinstance(conjunction, type(self))
        return conjunction

    def __rand__(self: Self, other: BitsConstructible) -> Self:
        """
        Bitwise AND of the bits of something constructible to a BitArray and a BitArray.
        """
        return self & other

    def __iand__(self: Self, other: BitsConstructible) -> Self:
        """
        In-place assignment of
           the bitwise AND of the bits of a BitArray
           and something constructible to a BitArray.
        """
        return self & other

    def __or__(self: Self, other: BitsConstructible) -> Self:
        """
        Bitwise OR of the bits of a BitArray and something constructible to a BitArray.
        """
        disjunction = super().__or__(type(self)(other))
        assert isinstance(disjunction, type(self))
        return disjunction

    def __ror__(self: Self, other: BitsConstructible) -> Self:
        """
        Bitwise OR of the bits of something constructible to a BitArray and a BitArray.
        """
        return self | other

    def __ior__(self: Self, other: BitsConstructible) -> Self:
        """
        In-place assignment of
           the bitwise OR of the bits of a BitArray
           and something constructible to a BitArray.
        """
        return self | other

    def __xor__(self: Self, other: BitsConstructible) -> Self:
        """
        Bitwise XOR of the bits of a BitArray and something constructible to a BitArray.
        """
        exclusive_disjunction = super().__xor__(type(self)(other))
        assert isinstance(exclusive_disjunction, type(self))
        return exclusive_disjunction

    def __rxor__(self: Self, other: BitsConstructible) -> Self:
        """
        Bitwise XOR of the bits of something constructible to a BitArray and a BitArray.
        """
        return self ^ other

    def __ixor__(self: Self, other: BitsConstructible) -> Self:
        """
        In-place assignment of
           the bitwise XOR of the bits of a BitArray
           and something constructible to a BitArray.
        """
        return self ^ other

    def __lshift__(self: Self, count: int) -> Self:
        """
        Left shift of the bits of a BitArray by `count` bits.
        """
        left_shift = super().__lshift__(count)
        assert isinstance(left_shift, type(self))
        return left_shift

    def __ilshift__(self: Self, count: int) -> Self:
        """
        In-place assignment of
           the left shift of the bits of a BitArray by `count` bits.
        """
        return self << count

    def __rshift__(self: Self, count: int) -> Self:
        """
        Right shift of the bits of a BitArray by `count` bits.
        """
        right_shift = super().__rshift__(count)
        assert isinstance(right_shift, type(self))
        return right_shift

    def __irshift__(self: Self, count: int) -> Self:
        """
        In-place assignment of
           the right shift of the bits of a BitArray by `count` bits.
        """
        return self >> count

    def __invert__(self: Self) -> Self:
        """
        Bitwise inversion of the bits of the BitArray.
        """
        inversion = super().__invert__()
        assert isinstance(inversion, type(self))
        return inversion

    def __iter__(self) -> Iterator[Literal[0, 1]]:
        """
        Iterate over the bits of the BitArray.
        """
        retiter = super().__iter__()
        return retiter  # type: ignore

    def __format__(self, format_spec: str) -> str:
        """
        Format the BitArray as a binary, octal, or hexadecimal string.
           "b" returns a binary string prefixed with "0b".
           "o" returns an octal string prefixed with "0o".
           "x" returns a hexadecimal string prefixed with "0x".
        Any other format specifier raises a ValueError.
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
        Returns whether the BitArray contains
            a given bit, if the item is an int,
            a given BitArray, if the item is a BitArray,
            a given BitArray constructed from item, if the item is a non-int
               BitsConstructible,
            or False otherwise.
        """
        if isinstance(item, int):
            if item not in {0, 1}:
                return False
            item = BitArray([item])  # type: ignore
        elif not isinstance(item, bitarray):
            if is_instance_of_union(item, Union[BitsConstructible, bitarray]):
                item = BitArray(item)  # type: ignore
            else:
                return False
        if isinstance(item, bitarray):
            first_index = self.find(item)
            return first_index != -1

    def __getitem__(  # type: ignore[reportIncompatibleMethodOverride]
        self: Self, key: Union[int, slice, Iterable[int]]
    ) -> Union[Literal[0, 1], Self]:
        """
        Get the bit at a given index or a BitArray of the bits
           across the indices given in slice or Iterable form.
        """
        # if isinstance(key, Iterable):
        #     key = list(key)
        # elif isinstance(key, slice):
        #     key = list(range(*key.indices(len(self))))
        return super().__getitem__(key)  # type: ignore[reportReturnType]

    def __setitem__(  # type: ignore[override]
        self,
        key: Union[int, slice, Sequence[int]],
        value: Union[Literal[0, 1], BitsConstructible],
    ) -> None:
        """
        Set the bit at a given index
           or the bits across the indices given in slice or Sequence form.

        An individual bit can be set with a BitsConstructible of length 1.
        """
        if isinstance(key, int):
            if not isinstance(value, int):
                value = BitArray(value)[0]
        # if isinstance(key, Iterable):
        #     key = list(key)
        # elif isinstance(key, slice):
        #     pass
        super().__setitem__(key, value)  # type: ignore[reportCallIssue]

    def __delitem__(self, key: Union[int, slice, Sequence[int]]) -> None:
        """
        Delete the bit at a given index
           or the bits across the indices given in slice or Iterable form.

        Args:
            key (Union[int, slice, Iterable[int]]): _description_
        """
        # if isinstance(key, Iterable):
        #     key = list(key)
        # if isinstance(key, Iterable) and not isinstance(key, Sequence):
        #     key = list(key)
        super().__delitem__(key)

    def __len__(self) -> int:
        """
        Get the number of bits in the BitArray.
        """
        return super().__len__()

    def __str__(self) -> str:
        """
        Get a string representation of the BitArray.
            This is e.g. "type(self)('010.....')".
        """
        zerosandones = self.to01()
        # chunk the list into 8-bit chunks
        zeroesandoneslist = [
            zerosandones[i : i + 8] for i in range(0, len(zerosandones), 8)
        ]
        # join the chunks with spaces
        return f"{type(self).__name__}" f"('{' '.join(zeroesandoneslist)}')"

    def __repr__(self) -> str:
        """
        Get a reconstructible representation of the BitArray.
            This is e.g. "type(self)('010.....')".
        """
        zerosandones = self.to01()
        # chunk the list into 8-bit chunks
        zeroesandoneslist = [
            zerosandones[i : i + 8] for i in range(0, len(zerosandones), 8)
        ]
        # join the chunks with spaces
        return f"{type(self).__name__}" f"('{' '.join(zeroesandoneslist)}'" f")"

    def __bytes__(self) -> bytes:
        """
        Convert the BitArray to a bytes object.
        If the length of the BitArray is not a multiple of 8,
            the BitArray is padded with 0s until the length is a multiple of 8.
        """
        return self.tobytes()

    def __Bits__(
        self: Self,
    ) -> Self:
        """
        Implementation of the BitsCastable protocol.

        See the `BitsCastable` protocol for more information.

        Returns a BitArray version of the object.
        """
        self = super().__new__(type(self), self)
        return self

    def __copy__(self: Self) -> Self:
        """
        Returns a shallow copy of the object
            with the same bits.
        """
        self = super().__new__(type(self), self)
        return self

    # def __reverse__(self) -> Self:

    def __deepcopy__(self: Self, memo: dict[int, object]) -> Self:
        """
        Returns a deep copy of the object
            with the same bits.
        """
        # Todo: Verify memoization procedure
        retval = type(self)()
        memo[id(self)] = retval
        retval.extend(copy.deepcopy(super(), (memo)))
        return retval

    def __sizeof__(self) -> int:
        """
        Get the size of the BitArray in bytes.
        This will not be the same as the number of bits in the BitArray
           divided by 8 (and, in fact, will be larger). This is because
           the BitArray object itself has some overhead (and also
           incidentally because of internal byte-padding).
        """
        return super().__sizeof__()

    # Basic Operations
    def append(self, value: int) -> None:
        super().append(value)

    def extend(  # type: ignore[reportIncompatibleMethodOverride]
        self, values: BitsConstructible
    ) -> None:
        if not isinstance(values, (Iterable)) or isinstance(values, str):
            values = BitArray(values)
        super().extend(values)

    def insert(  # type: ignore[reportIncompatibleMethodOverride]
        self, index: int, value: int
    ) -> None:
        super().insert(index, value)

    def pop(  # type: ignore[reportINcompatibleMethodOverride]
        self, index: Optional[int] = None, default: Optional[T] = None
    ) -> Union[int, T]:
        if index is None:
            index = len(self) - 1
        if len(self) == 0:
            if default is not None:
                return default
            raise IndexError("pop from empty bitarray")
        if (index < 0 or index >= len(self)) and default is not None:
            return default
        return super().pop(index)

    def remove(self, value: int) -> None:
        super().remove(value)

    def clear(self) -> None:
        super().clear()

    def copy(self: Self) -> Self:
        a_copy = super().copy()
        assert isinstance(a_copy, type(self))
        return a_copy

    def reverse(self) -> None:
        super().reverse()

    # def swap_endianness(self) -> None:
    #     self._endianness = "big" if self._endianness == "little" else "little"

    # Search and Analysis
    def count(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        end: Optional[int] = None,
    ) -> int:
        if not is_instance_of_union(value, Union[int, BitArray]):
            assert not isinstance(value, BitArray)
            assert not isinstance(value, int)
            value = BitArray(value)
        if end is None:
            end = len(self)

        assert isinstance(value, int) or isinstance(value, bitarray)
        return super().count(value, start, end)

    def startswith(
        self,
        substrings: Union[
            BitsConstructible,
            BitArray,
            Literal[0, 1],
            Iterable[Union[BitsConstructible, BitArray]],
        ],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> bool:
        """
        Check if the bitarray starts with the given substring.
        """
        conv_substrings = list()

        if isinstance(substrings, bitarray):
            conv_substrings = [substrings]
        elif isinstance(substrings, int):
            conv_substrings = [BitArray([substrings])]
        elif isinstance(substrings, (str, bytes, BitsCastable)):
            conv_substrings = [BitArray(substrings)]
        elif isinstance(substrings, Iterable):
            list_of_substrings = list(substrings)
            conv_substrings = list()
            if all(isinstance(substring, int) for substring in list_of_substrings):
                conv_substrings = [BitArray(list_of_substrings)]  # type: ignore
            elif all(
                is_instance_of_union(substring, BitsConstructible)
                for substring in list_of_substrings
            ):
                conv_substrings = [
                    BitArray(substring)  # type: ignore
                    for substring in list_of_substrings
                ]
            else:
                raise ValueError("Invalid type in provided iterable")

        # if isinstance(substrings, (bitarray, int, str)):
        #     conv_substrings = [substrings]
        # elif isinstance(substrings, Iterable):
        #     conv_substrings = list(substrings)
        # else:
        #     try:
        #         conv_substrings = [BitArray(substrings)]
        #     except TypeError:
        #         pass

        # if isinstance(substrings, Iterable):
        #     for substring in substrings:
        #         if isinstance(substring, bitarray):
        #             conv_substrings.append(substring)
        #         else:
        #             conv_substrings.append(BitArray(substring))

        if stop is None:
            stop = len(self)

        # Ensure the start and stop indices are within the bounds of the bitarray
        start, stop = max(0, start), min(len(self), stop)

        if any(len(conv_substring) == 0 for conv_substring in conv_substrings):
            return True

        # Build a trie from the substrings
        trie = Trie.build_prefix_trie(conv_substrings)

        # Traverse the trie to find a matching prefix
        current = trie
        for i in range(start, stop):
            if self[i] not in current.children:
                return False
            current = current.children[self[i]]

            if current.is_start_of_prefix:
                return True

        return False

    def endswith(
        self,
        substrings: Union[
            BitsConstructible,
            BitArray,
            Literal[0, 1],
            Iterable[Union[BitsConstructible, BitArray]],
        ],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> bool:
        """
        Check if the bitarray ends with the given substring.
        """

        if isinstance(substrings, BitArray):
            conv_substrings = [substrings]
        elif isinstance(substrings, bitarray):
            conv_substrings = [BitArray(substrings)]
        elif isinstance(substrings, int):
            conv_substrings = [BitArray([substrings])]
        elif isinstance(substrings, (str, bytes, BitsCastable)):
            conv_substrings = [BitArray(substrings)]
        elif isinstance(substrings, Iterable):
            list_of_substrings = list(substrings)
            conv_substrings = list()
            if all(isinstance(substring, int) for substring in list_of_substrings):
                conv_substrings = [BitArray(list_of_substrings)]  # type: ignore
            elif all(
                is_instance_of_union(substring, BitsConstructible)
                for substring in list_of_substrings
            ):
                conv_substrings = [
                    BitArray(substring)  # type: ignore
                    for substring in list_of_substrings
                ]
            else:
                raise ValueError("Invalid type in provided iterable")

        if stop is None:
            stop = len(self)

        # Ensure the start and stop indices are within the bounds of the bitarray
        start, stop = max(0, start), min(len(self), stop)

        if any(len(conv_substring) == 0 for conv_substring in conv_substrings):
            return True

        # Build a trie from the reversed substrings
        trie = Trie.build_suffix_trie(conv_substrings)

        # Traverse the trie to find a matching suffix
        current = trie
        for i in range(stop - 1, start - 1, -1):
            if self[i] not in current.children:
                return False
            current = current.children[self[i]]

            if current.is_end_of_suffix:
                return True

        return False

    def find(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        if stop is None:
            stop = len(self)
        if not isinstance(value, (bitarray, int)):
            value = BitArray(value)

        return super().find(value, start, stop)

    def rfind(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        if stop is None:
            stop = len(self)
        if not isinstance(value, (bitarray, int)):
            value = BitArray(value)
        return super().find(value, start, stop, right=True)

    def index(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        if stop is None:
            stop = len(self)
        if not isinstance(value, (bitarray, int)):
            value = BitArray(value)

        index = super().index(value, start, stop)
        if index == -1:
            raise ValueError(f"{value} is not in bitarray")
        return index

    def rindex(
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int:
        if stop is None:
            stop = len(self)
        if not isinstance(value, (bitarray, int)):
            value = BitArray(value)

        index = super().index(value, start, stop, right=True)

        if index == -1:
            raise ValueError(f"{value} is not in bitarray")
        return index

    # Modification and Translation
    def replace(
        self: Self,
        old: BitsConstructible,
        new: BitsConstructible,
        count: Optional[int] = None,
    ) -> Self:
        if not isinstance(old, type(self)):
            old = type(self)(old)
        if not isinstance(new, type(self)):
            new = type(self)(new)
        assert isinstance(old, type(self))
        assert isinstance(new, type(self))

        max_replacements = float("inf") if count is None else count
        num_replacements = 0

        index = 0
        accumulated_bits: Optional[Self] = None
        if len(old) != len(new):
            accumulated_bits: Optional[Self] = type(self)()

        while float(num_replacements) < max_replacements:
            found_index = self.find(old, index)
            if found_index == -1:
                break

            # Replace old bits with new bits
            if accumulated_bits is None:
                self[found_index : found_index + len(new)] = new
            else:
                accumulated_bits += self[index:found_index] + new  # type: ignore
                assert isinstance(accumulated_bits, type(self))
            index = found_index + len(old)  # Move index past the newly inserted bits
            num_replacements += 1

        if accumulated_bits is not None:
            self_range = self[index:]
            assert isinstance(self_range, type(self))
            accumulated_bits += self_range
            self = accumulated_bits

        return self

    # def translate(self,
    #   table: List[BitArray] | bytes, delete: Optional[List[BitArray] | bytes] = None
    #   ) -> Self: ... # todo

    # def maketrans(self, fromstr: List[BitArray]|bytes, tostr: List[BitArray]|bytes
    #   ) -> list[BitArray]: ...  # todo

    def join(self: Self, iterable: Iterable[BitsConstructible]) -> Self:
        self_as_str_bitlist = self.to01()
        iterable = [
            item if isinstance(item, type(self)) else type(self)(item)
            for item in iterable
        ]
        joined_bits = self_as_str_bitlist.join(another.to01() for another in iterable)
        return type(self)(joined_bits)

    def partition(self: Self, sep: BitArray) -> tuple[Self, Self, Self]:
        index = self.find(sep)
        if index == -1:
            return self, type(self)(), type(self)()

        self_to_index = self[:index]
        sep = type(self)(sep)
        self_after_offset = self[index + len(sep) :]
        assert isinstance(self_to_index, type(self))
        assert isinstance(sep, type(self))
        assert isinstance(self_after_offset, type(self))
        return self_to_index, sep, self_after_offset

    def rpartition(self: Self, sep: BitArray) -> tuple[Self, Self, Self]:
        index = self.rfind(sep)
        if index == -1:
            return type(self)(), type(self)(), self

        self_to_index = self[:index]
        sep = type(self)(sep)
        self_after_offset = self[index + len(sep) :]
        assert isinstance(self_to_index, type(self))
        assert isinstance(sep, type(self))
        assert isinstance(self_after_offset, type(self))
        return self_to_index, sep, self_after_offset

    def lstrip(
        self: Self, bits: Optional[Union[Literal[0], Literal[1]]] = None
    ) -> Self:
        if not (bits is None or isinstance(bits, int)):
            if hasattr(bits, "__int__"):
                bits = int(bits)  # type: ignore
            elif isinstance(bits, Iterable):
                bits = int(next(iter(bits)))  # type: ignore
            else:
                bits = int(bits)  # type: ignore

        if bits is None or bits == 0:
            retvalindex = self.find(1)
        else:
            retvalindex = self.find(0)

        if retvalindex == -1:
            return type(self)()

        retval = self[retvalindex:]
        assert isinstance(retval, type(self))
        return retval

    def rstrip(
        self: Self, bits: Optional[Union[Literal[0], Literal[1]]] = None
    ) -> Self:
        if not (bits is None or isinstance(bits, int)):
            if hasattr(bits, "__int__"):
                bits = int(bits)  # type: ignore
            elif isinstance(bits, Iterable):
                bits = int(next(iter(bits)))  # type: ignore
            else:
                bits = int(bits)  # type: ignore

        if bits is None or bits == 0:
            retvalindex = self.rfind(1)
        else:
            retvalindex = self.rfind(0)

        if retvalindex == -1:
            return type(self)()

        retval = self[: retvalindex + 1]
        assert isinstance(retval, type(self))
        return retval

    def strip(self: Self, bits: Optional[Union[Literal[0], Literal[1]]] = None) -> Self:
        return self.lstrip(bits).rstrip(bits)

    def lpad(self: Self, width: int, fillbit: Literal[0, 1] = 0) -> Self:
        if len(self) >= width:
            return self
        return type(self)([fillbit] * (width - len(self))) + self

    def rpad(self: Self, width: int, fillbit: Literal[0, 1] = 0) -> Self:
        if len(self) >= width:
            return self
        return self + type(self)([fillbit] * (width - len(self)))

    @classmethod
    def cast_if_not_bitarray(
        cls: type[Self], obj: BitsConstructible
    ) -> Union[Self, BitArray]:
        return cls(obj) if not isinstance(obj, BitArray) else obj


BitsConstructible = Union[
    BitArray, bytes, str, Iterable[Literal[0, 1]], BitsCastable, bitarray
]

if __name__ == "__main__":
    print("-------------------------------")
    print(issubclass(BitArray, bitarray))

    a_bitarray = BitArray("0o1011")
    a_bitarray_2 = bitarray("1011")
    bitArray2 = BitArray(a_bitarray_2)
    a_bitarray += a_bitarray_2
    bitArray3 = BitArray(a_bitarray)
    print("----------")
    print(a_bitarray.to01())

    print(type(a_bitarray + a_bitarray_2))
    print(type(a_bitarray_2))
    print(type(bitArray2))

    print(a_bitarray)
    print(a_bitarray_2)
    print(bitArray2)
    print(bitArray3)
    print(isinstance(a_bitarray, BitsCastable))

    print(bitArray3[5:8])

    a_bitarray += "10"
    print(a_bitarray)
    print("a_bitarray", type(bitarray("0101") + a_bitarray))
    print(a_bitarray_2)
    print(bitArray2)
    print(bitArray3)

    # print(bytes(bitarray("00000000 11110000", endian="little")))
    # print(bytes(BitArray("00000000 11110000", endianness="little")))
    # print(BitArray("00000000 11110000 11100111", endianness="little").oct(sep="_"))
    print(bytes(bitarray("00000000 11110000")))
    print(bytes(BitArray("00000000 11110000")))
    print(BitArray("00000000 11110000 11100111").oct(sep="_"))
    print("---------------")
    print("-------------")
    print(bitArray2.__repr__())
    print("bitArray2", type(bitArray2))

    print(a_bitarray)
    print(BitArray("00000000 11110011").replace("0011", "1010"))

    print(BitArray("0000").join([BitArray("111"), BitArray("101")]))

    print(a_bitarray.endswith(("101", "11")))

    print(a_bitarray.startswith(("101", "0")))

    test_bitarray = BitArray("00011000 11110011")
    print(test_bitarray.find("0001"))
    # print(test_bitarray.split("11"))
    # print(test_bitarray.split())

    print(base2ba(16, "0f"))
    print(BitArray(base2ba(16, "0ff")).oct())
    print(a_bitarray.oct())
    # print(hex(int(a_bitaarray)))
    # print(ba2int(base2ba(16, "0f", endian="little")))

    print(a_bitarray.bin())
    print("0x83" in a_bitarray)

    print(type(a_bitarray * 3))
