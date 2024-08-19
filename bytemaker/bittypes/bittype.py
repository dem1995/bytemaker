from __future__ import annotations

import struct
from abc import ABC, abstractmethod

from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Final, Generic, Literal, Optional, Type, TypeVar
from bytemaker.utils import classproperty

T = TypeVar("T")


class BitType(ABC, Generic[T]):
    """A type representable by a sequence of bits.
    Allows for editing the value of the type pythonically through the `value` property
       or through the underlying sequence of bits through the `bits` property.

    Also allows treating the BitType as the underlying (Pythonic) value
        for regular operations.

    Class Attributes:
    ---------------
    num_bits : int
       The number of bits in the BitType.
    base_bit_type : Type[BitType]
       The base BitType this class derives from (e.g. UInt for UInt8)
    py_type : Type[T]
       The Pythonic type that this BitType can be converted to/from

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this BitType object.
    value : py_type
       The (Pythonic) value of this BitType object.
    endianness : Literal["big", "little"]
       The endianness of this BitType object.
    """

    _num_bits: Final[int]
    base_bit_type: Final[Type[BitType]]
    py_type: Final[Type[T]]  # type: ignore[reportGeneralTypeIssue]

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
        return self._endianness

    @classproperty
    @classmethod
    def num_bits(cls) -> int:
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
        The (readonly) getter for the underlying sequence of bits of the BitType.

        To set the bits directly, use the `bits` setter.

        Returns:
            BitVector: _description_
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
        if len(self.bits) < 17:
            bitstring = self.bits.to01(sep=" ")
        else:
            bitstring = self.bits[:8].to01() + "..." + self.bits[-8:].to01()

        return (
            f"{self.__class__.__name__}[{self.endianness}]"
            f"({self.value} = {bitstring})"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}({self.value})"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.value == other.value
        return self.value == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __bytes__(self):
        temp_bytes = bytes(self.bits)
        if self.endianness == "big":
            return temp_bytes
        else:
            return temp_bytes[::-1]

    def __hash__(self):
        return hash(frozenset([self.__class__, self.value]))

    # Temporary methods
    # TODO remove
    def to_bits(self):
        return self.bits

    @classmethod
    def from_bits(cls, bits: BitVector):
        return cls(bits=bits)


class StructPackedBitType(BitType[T]):
    """
    Abstract base class for all BitType objects that use struct for packing/unpacking.
    """

    packing_format_letter: Final[str]

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
    return unittype(bits=BitVector(unitbytes))
