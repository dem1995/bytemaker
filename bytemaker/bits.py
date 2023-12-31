from __future__ import annotations
from math import ceil
import operator
import typing
from typing import Iterable, Protocol, runtime_checkable
from bytemaker.utils import ByteConvertible, twos_complement_bit_length


@runtime_checkable
class BitsCastable(Protocol):
    def __Bits__(self) -> "Bits":
        pass


BitsConstructorType = typing.Union[int, str, bytes, bytearray, memoryview, Iterable[int], "Bits", BitsCastable]


class Bits:
    """
    A class for storing and manipulating bits.
    """
    def __init__(self, initial_data: BitsConstructorType = None, size=None, deep=False):
        if initial_data is None:
            initial_data = list()

        bitlist: list[int] = None

        if isinstance(initial_data, Bits):
            self.bitlist = initial_data.bitlist

        else:
            if isinstance(initial_data, int):
                bitlist = self.from_int(initial_data, size).bitlist
            elif isinstance(initial_data, BitsCastable):
                if isinstance(initial_data, Bits):
                    bitlist = initial_data.bitlist
                elif hasattr(initial_data, '__Bits__'):
                    bitlist = initial_data.__Bits__().bitlist
            elif isinstance(initial_data, str):
                bitlist = Bits.from_string(initial_data).bitlist
            elif isinstance(initial_data, (bytes, bytearray, memoryview)):
                bitlist = [int(bit) for byte in initial_data for bit in format(byte, '08b')]
            elif isinstance(initial_data, Iterable):  # Iterable[int | bool] in more modern Python versions
                bitlist = [int(bit) for bit in initial_data]
            elif isinstance(initial_data, ByteConvertible):
                bitlist = [int(bit) for byte in bytes(initial_data) for bit in format(byte, '08b')]
            else:
                raise TypeError(f"Cannot convert {type(initial_data)} to Bits. Must be {BitsConstructorType}.")

            self.bitlist = bitlist

            if self.bitlist is None:
                raise ValueError(
                    f"Could not convert {type(initial_data)} to Bits despite the provided type being acceptable. "
                    "The resulting bit_list was none")

            assert all(bit in [0, 1] for bit in self.bitlist), \
                (f"Bits can only be 1 or 0. The provided data produced bits other than 0 or 1."
                 f"Final bitlist: {self.bitlist} Initial data: {initial_data}")

        if deep:
            self.bitlist = self.bitlist.copy()

    @property
    def bytes(self) -> list[int]:
        return bytes(self)

    @property
    def bytearray(self) -> bytearray:
        return bytearray(bytes(self))

    def __str__(self) -> str:
        return self.str_(format_spec='b')

    def str_(self, format_spec) -> str:
        return format(self, format_spec)

    def __repr__(self) -> str:
        return f"Bits({self.bitlist})"

    def __len__(self) -> int:
        return len(self.bitlist)

    def __getitem__(self, index) -> int:
        if isinstance(index, int):
            return self.bitlist[index]
        elif hasattr(index, '__index__'):
            return self.bitlist[index.__index__()]
        elif hasattr(index, '__int__'):
            return self.bitlist[index.__int__()]
        elif isinstance(index, slice):
            return Bits(self.bitlist[index])
        elif isinstance(index, Iterable):
            return Bits([self.bitlist[i] for i in index])
        else:
            raise TypeError(
                f"Index must be an int, slice, or iterable of ints, or have __index__ or __int__ method,"
                f" not {type(index)}"
            )

    def __setitem__(self, index, value):
        if not 0 <= value <= 1:
            raise ValueError('Bits can only be 1 or 0')
        self.bitlist[index] = value

    def binop(self, other: BitsConstructorType, op: "operator", expand=False) -> Bits:
        if not isinstance(other, Bits):
            try:
                other = Bits(other)
            except Exception as e:
                raise TypeError(
                    f"Can only perform bitwise operations on Bits objects, not {type(other)}"
                    f"Exception details {e}"
                )

        bitsleftlen = len(self)
        bitsrightlen = len(other)
        bitsleftiter = iter(self)
        bitsrightiter = iter(other)

        retbits = list()

        while bitsleftlen < bitsrightlen:
            if expand:
                retbits.append(next(bitsrightiter))
            bitsrightlen -= 1

        while bitsrightlen < bitsleftlen:
            if expand:
                retbits.append(next(bitsleftiter))
            bitsleftlen -= 1

        while bitsleftlen > 0:
            retbits.append(op(next(bitsleftiter), next(bitsrightiter)))
            bitsleftlen -= 1

        return Bits(retbits)

    def __invert__(self) -> Bits:
        return Bits([int(not bit) for bit in self.bitlist])

    def and_(self, other: Bits, expand=False) -> Bits:
        return self.binop(other, operator.and_, expand=expand)

    def or_(self, other: Bits, expand=False) -> Bits:
        return self.binop(other, operator.or_, expand=expand)

    def xor_(self, other: Bits, expand=False) -> Bits:
        return self.binop(other, operator.xor, expand=expand)

    def __and__(self, other: Bits) -> Bits:
        return self.and_(other)

    def __or__(self, other: Bits) -> Bits:
        return self.or_(other)

    def __xor__(self, other: Bits) -> Bits:
        return self.xor_(other)

    def lshift(self, other: int, expand=False) -> Bits:
        if expand:
            return Bits(self.bitlist + [0] * other)
        else:
            return Bits(self.bitlist[other:] + [0] * other)

    def __lshift__(self, other: int) -> Bits:
        return self.lshift(other)

    def rshift(self, other: int, expand=False) -> Bits:
        if expand:
            return Bits([0] * other + self.bitlist)
        else:
            return Bits([0] * other + self.bitlist[:-other])

    def __rshift__(self, other: int) -> Bits:
        return self.rshift(other)

    def __add__(self, other: Bits) -> Bits:
        return self.add_(other)

    def add_(self, other: Bits) -> Bits:
        return Bits(self.bitlist + other.bitlist)

    def __int__(self) -> int:
        return self.to_int()

    def __index__(self) -> int:
        return int(self)

    def __format__(self, format_spec) -> str:
        if format_spec == 'b':
            retstring = "0b"
            for i in range(len(self.bitlist)):
                if i % 8 == 0 and not i == 0:
                    retstring += "_"
                retstring += str(self.bitlist[i])
        elif format_spec == 'o':
            retstring = "0o"
            for i in range(0, len(self.bitlist), 3):
                if i % 8 == 0 and not i == 0:
                    retstring += "_"
                nibble = 0
                nibble_end_index = min(i + 3, len(self.bitlist))
                for bit in self.bitlist[i:nibble_end_index]:
                    nibble = (nibble << 1) | bit
                retstring += oct(nibble)[2:]
        elif format_spec == 'x':
            retstring = "0x"
            for i in range(0, len(self.bitlist), 4):
                if i % 8 == 0 and not i == 0:
                    retstring += "_"
                nibble = 0
                nibble_end_index = min(i + 4, len(self.bitlist))
                for bit in self.bitlist[i:nibble_end_index]:
                    nibble = (nibble << 1) | bit
                retstring += hex(nibble)[2:]
        return retstring

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    def __Bits__(self) -> Bits:
        return self

    def append(self, value: int, inplace=True):
        value = int(value)
        if value not in [0, 1]:
            raise ValueError('Bits can only be 1 or 0')
        if inplace:
            self.bitlist.append(value)
            return self
        else:
            return Bits(self.bitlist + [value])

    def padleft(self, *, up_to_size: int, padvalue: int = 0, inplace=True):
        num_bits_to_add = up_to_size - len(self)
        if num_bits_to_add < 0:
            return self

        bits_to_add = [padvalue] * num_bits_to_add
        if inplace:
            self.bitlist = bits_to_add + self.bitlist
            return self
        else:
            return Bits(bits_to_add + self.bitlist)

    def padright(self, *, up_to_size: int, padvalue: int = 0, inplace=True):
        num_bits_to_add = up_to_size - len(self)
        if num_bits_to_add < 0:
            return self

        bits_to_add = [padvalue] * num_bits_to_add
        if inplace:
            self.bitlist = self.bitlist + bits_to_add
            return self
        else:
            return Bits(self.bitlist + bits_to_add)

    def pop(self, index: int = -1, inplace=True) -> int:
        if not inplace:
            bits_obj_to_act_on = Bits(self.bitlist, deep=True)
        else:
            bits_obj_to_act_on = self

        return bits_obj_to_act_on.bitlist.pop(index)

    def to_bytes(self, reverse_endianness=False) -> bytes:
        byte_arr = bytearray()
        for i in range(0, len(self.bitlist), 8):
            byte = 0
            byte_end_index = min(i + 8, len(self.bitlist))
            for bit in self.bitlist[i:byte_end_index]:
                byte = (byte << 1) | bit
            byte_arr.append(byte)

        if reverse_endianness:
            byte_arr = reversed(byte_arr)
        return bytes(byte_arr)

    @classmethod
    def from_bytes(cls, byte_arr: bytes, reverse_endianness=False):
        if reverse_endianness:
            byte_arr = reversed(byte_arr)

        return cls(byte_arr)

    @classmethod
    def from_string(cls, string: str):
        """
        Converts a string to a Bits object.
        The string must be all binary or of the form '0b', '0o', or '0x' followed by digits.
        """
        if "_" in string:
            string = string.replace("_", "")
        if string.startswith('0b'):
            binstring = string[2:]
        elif string.startswith('0o'):
            nonzeros = string[2:].lstrip('0')
            nonzeros_as_bin = bin(int(nonzeros, 8))[2:]
            leading_zeros_as_bin = '0' * (len(string[2:]) * 3 - len(nonzeros_as_bin))
            binstring = leading_zeros_as_bin + nonzeros_as_bin
        elif string.startswith('0x'):
            nonzeros = string[2:].lstrip('0')
            nonzeros_as_bin = bin(int(nonzeros, 16))[2:]
            leading_zeros_as_bin = '0' * (len(string[2:]) * 4 - len(nonzeros_as_bin))
            binstring = leading_zeros_as_bin + nonzeros_as_bin
        elif all(char in '01' for char in string):
            pass
        else:
            raise ValueError(
                f"Cannot convert {string} to Bits."
                f"Strings passed should be all binary or of the form '0b', '0o', or '0x' followed by digits."
            )

        # print("binstring: ", binstring)
        bin_list = [int(bit) for bit in binstring]
        # print(bin_list)
        return cls(bin_list)

    @classmethod
    def from_int(cls, integer: int, size=None):
        """
        Converts an integer to a Bits object. The size parameter determines the number of bits to use.
        If size is not provided, the number of bits required to represent the integer is used.
        """
        if size is None:
            size = twos_complement_bit_length(integer)
        if integer.bit_length() > size:
            raise ValueError(
                f"Cannot convert {integer} to Bits with size {size},"
                f" because it requires {integer.bit_length()} bits to represent.")

        bitlist = list()
        for index in range(size):
            bitlist.insert(0, (integer >> index) & 1)

        return cls(bitlist)

    def to_int(self, endianness='big', signed=True) -> int:
        """
        Converts a Bits object to an integer. It does this
            by casting the Bits to bytes, and then converting the bytes to an integer
            using the provided endianness and signedness.
        """
        copy = Bits(self.bitlist, deep=True)
        if signed and len(copy) > 0 and copy[0] == 1:
            next_multiple_of_8 = ceil(len(self.bitlist) / 8) * 8
            copy.padleft(up_to_size=next_multiple_of_8, padvalue=1, inplace=True)

        return int.from_bytes(copy.to_bytes(), byteorder=endianness, signed=signed)

    def to_bin(self) -> str:
        return self.str_(format_spec='b')

    def to_oct(self) -> str:
        return self.str_(format_spec='o')

    def to_hex(self) -> str:
        return self.str_(format_spec='x')

    def shrinkequals(self, other_bits: Bits) -> bool:
        """
        Returns True if both Bits objects are equal after removing leading zeros from the longer Bits object.
        """
        return self | other_bits == self & other_bits

    def __eq__(self, other: Bits):
        if not isinstance(other, Bits):
            return False
        return self.bitlist == other.bitlist

    def join(self, bitobjs: Iterable[Bits]) -> Bits:
        """
        Joins multiple Bits objects together with self in between each.
        """

        if len(self) == 0:
            fin_bit_list = [bit for bitobj in bitobjs for bit in bitobj]
            return Bits(fin_bit_list)
        else:
            ret_bits = Bits()
            for bitobj in list(bitobjs)[0:-1]:
                ret_bits = ret_bits + bitobj + self
            ret_bits = ret_bits + bitobjs[-1]
            return ret_bits
