from __future__ import annotations

import struct
from abc import ABC, abstractmethod

from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Final, Generic, Literal, Optional, Type, TypeVar
from bytemaker.utils import classproperty

T = TypeVar("T")


class BitType(ABC, Generic[T]):
    """
    A type representable by a sequence of bits.

    Allows for editing the value of the type pythonically through the `value` property
    or through the underlying sequence of bits through the `bits` property.

    Also allows treating the BitType as the underlying (Pythonic) value
    for regular operations.

    :cvar num_bits: The number of bits in the BitType.
    :vartype num_bits: int
    :cvar base_bit_type: The base BitType this class derives from (e.g. UInt for UInt8).
    :vartype base_bit_type: Type[BitType]
    :cvar py_type: The Pythonic type that this BitType can be converted to/from.
    :vartype py_type: Type[T]

    :ivar bits: The underlying sequence of bits of this BitType object.
    :vartype bits: BitVector
    :ivar value: The (Pythonic) value of this BitType object.
    :vartype value: py_type
    :ivar endianness: The endianness of this BitType object.
    :vartype endianness: Literal["big", "little"]
    """

    _num_bits: Final[int]
    base_bit_type: Final[Type[BitType]]
    """The base BitType this class derives from (e.g. UInt for UInt8)."""
    py_type: Final[Type[T]]  # type: ignore[reportGeneralTypeIssue]
    """The Pythonic type that this BitType can be converted to/from."""

    _bits: BitVector
    _endianness: Literal["big", "little"]

    def __init__(
        self,
        source: Optional[(T | BitVector | BitType)] = None,
        value: Optional[T] = None,
        bits: Optional[BitVector] = None,
        endianness: Literal["big", "little", "source_else_big"] = "source_else_big",
    ):
        if source is not None:
            if isinstance(source, BitType):
                try:
                    value = self.py_type(source.value)  # type: ignore[reportCallIssue]
                    assert isinstance(value, self.py_type)
                except Exception as e:
                    raise ValueError(
                        f"Could not convert source value to (Pythonic) value"
                        f" due to error: {e}"
                    )
                if endianness == "source_else_big":
                    endianness = source.endianness

            elif isinstance(source, BitVector):
                bits = source
            else:
                try:
                    value = self.py_type(source)  # type: ignore[reportCallIssue]
                except Exception as e:
                    raise ValueError(
                        f"Could not convert source value to (Pythonic) value"
                        f" due to error: {e}"
                    )

        if endianness == "source_else_big":
            endianness = "big"
        endianness: Literal["big", "little"]
        self._endianness = endianness

        if value is None and bits is None:
            raise ValueError("Either value or bits must be provided")
        elif value is not None and bits is not None:
            raise ValueError("Only one of value or bits should be provided")
        if value is not None:
            self.value = value
        elif bits is not None:
            self.bits = bits

    @property
    def endianness(self) -> Literal["big", "little"]:
        """
        A readonly property holding the endianness of the BitType.

        Returns:
            Literal["big", "little"]: The endianness of the BitType.
        """
        return self._endianness

    @classproperty
    @classmethod
    def num_bits(cls) -> int:
        """
        A readonly classproperty holding the number of bits in the BitType.

        Returns:
            int: The number of bits in the BitType.
        """
        return cls._num_bits

    @property
    @abstractmethod
    def value(self) -> T:
        """
        The (readonly) getter for the (Pythonic) value of the BitType.

        To set the value directly, use the `value` setter.
        To directly adjust the value more complicatedly,
            use operations available directly on BitType object
            rather than on the value returned by this property.

        Returns:
            T: The (Pythonic) value of the BitType.
        """

    @value.setter
    @abstractmethod
    def value(self, value: T):
        """
        The setter for the (Pythonic) value of the BitType.

        Args:
            value (T): The new value for the BitType.
        """

    @property
    def bits(self) -> BitVector:
        """
        Getter/setter for the sequence of bits
        the BitType uses to represent its value.

        Returns:
            BitVector: The sequence of bits the BitType uses to represent its value.
        """
        return self._bits

    @bits.setter
    def bits(self, bits: BitVector):
        if len(bits) != self.num_bits:
            raise ValueError(f"Expected {self.num_bits} bits, got {len(bits)}")

        # if self._endianness != bits.endianness:
        #     raise ValueError(
        #         f"Endianness mismatch:"
        #         f" expected {self._endianness}, got {bits.endianness}")

        self._bits = bits

    def __str__(self):
        """
        Returns a string representation of the BitType.

        Returns:
            str: ClassName[self.endianness]({self.value} = {self.bitstring})
        """
        if len(self.bits) < 17:
            bitstring = self.bits.to01(sep=" ")
        else:
            bitstring = self.bits[:8].to01() + "..." + self.bits[-8:].to01()

        return (
            f"{self.__class__.__name__}[{self.endianness}]"
            f"({self.value} = {bitstring})"
        )

    def __repr__(self):
        """
        Returns a string representation of the BitType.
        That can be used to recreate the object.

        Returns:
            str: ClassName(value)(bits={self.value}, {endianness=self.endianness})
        """
        return (
            f"{self.__class__.__name__}(bits={self.bits}, endianness={self.endianness})"
        )

    def __eq__(self, other):
        """
        Compares the BitType to another object.

        Two bittypes are equal if their values are equal. Note that this means that
        they might have internal bit representations (-0 and +0 are still equal, though)

        Args:
            other (Any): The object to compare to.

        Returns:
            bool: True if the objects are equal, False otherwise
        """
        if isinstance(other, self.__class__):
            return self.value == other.value
        return self.value == other

    def __ne__(self, other):
        """
        Compares the BitType to another object.

        Two bittypes are equal if their values are equal. Note that this means that
        they might have internal bit representations (-0 and +0 are still equal, though)

        Args:
            other (Any): The object to compare to.

        Returns:
            bool: True if the objects are not equal, False otherwise
        """

        return not self.__eq__(other)

    def __bytes__(self):
        """
        Returns the bytes representation of the BitType.
        This is the same as the bytes representation of the underlying BitVector
        unless the endianness is little, in which case the bytes are reversed.

        Note that bytearray will use the buffer protocol instead of this method.

        Returns:
            bytes: The bytes representation of the BitType.
        """
        temp_bytes = bytes(self.bits)
        if self.endianness == "big":
            return temp_bytes
        else:
            return temp_bytes[::-1]

    # def __hash__(self):
    #     """
    #     Returns the hash of the BitType.

    #     Because the only thing that matters is that the value for __eq__,
    #     the hash is based on just the BitType value.
    #     """
    #     # return hash(frozenset([self.__class__, self.value]))
    #     return hash(frozenset([self.value]))

    # Temporary methods
    # TODO remove
    def to_bits(self) -> BitVector:
        """DEPRECATED
        Use the `bits` property instead.

        Obtains the bit representation of the BitType.

        Returns:
            BitVector: The sequence of bits of the BitType.
        """
        return self.bits

    @classmethod
    def from_bits(cls, bits: BitVector):
        """DEPRECATED
        Use the constructor with a BitVector-like object instead.

        Creates a new BitType object from a sequence of bits.


        Args:
            bits (BitVector): The sequence of bits to create the BitType from.
        """
        return cls(bits=bits)


class StructPackedBitType(BitType[T]):
    """
    Abstract base class for all BitType objects that use struct for packing/unpacking.

    Class Attributes:
    -----------------
    packing_format_letter : str
        The packing format letter for the subclass.

    Instance Attributes
    -------------------
    skip_struct_packing : bool
        If true, the struct packing/unpacking will be skipped and the value will be
            be calculated using other methods on the MRO.

    packing_format : str
        The struct-packing format for the subclass that `struct` uses. It is calculated
            based on the endianness
    """

    packing_format_letter: Final[str]
    """The packing format letter for struct to use for converting to/from bytes."""

    @property
    def skip_struct_packing(self) -> bool:
        """
        If true, the struct packing/unpacking will be skipped and the value will be
            be calculated using parent methods.

        Most of the time this will be false
        """
        return False

    @property
    def packing_format(self) -> str:
        """
        Returns the packing format for the class.

        Args:
            endianness (str): the endianness of the packing format. Defaults to little

        Returns:
            str: the struct packing format for the subclass.
        """
        cls = self.__class__
        if self.endianness == "little":
            return f"<{cls.packing_format_letter}"
        elif self.endianness == "big":
            return f">{cls.packing_format_letter}"
        else:
            raise ValueError(
                f"Endianness must be either 'little' or 'big', not {self.endianness}"
            )

    @property
    def value(self) -> T:
        if not self.skip_struct_packing:
            the_bits = self.bits
            if not len(the_bits) % 8 == 0:
                the_bits = BitVector(8 - len(the_bits) % 8) + the_bits
            return struct.unpack(self.packing_format, bytes(self.bits))[0]
        else:
            return super().value

    @value.setter
    def value(self, value: T):
        if not self.skip_struct_packing:
            self._bits = BitVector(struct.pack(self.packing_format, value))
        else:
            super().value = value


def bytes_to_bittype(unitbytes: bytes, unittype: type[BitType]) -> BitType:
    """
    Converts a bytes object to an instance of the provided BitType object.

    Args:
        unitbytes (bytes): The bytes object to convert.
        unittype (type[BitType]): The BitType object to convert to.

    Returns:
        BitType: The BitType object created from the bytes object.
    """
    return unittype(bits=BitVector(unitbytes))
