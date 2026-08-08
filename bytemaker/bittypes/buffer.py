from typing import TYPE_CHECKING

from bytemaker.bittypes.bittype import BitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Optional, Type, TypeVar

if TYPE_CHECKING:
    BufferSelf = TypeVar("BufferSelf", bound="Buffer")
else:
    try:
        from typing_redirect import Self as BufferSelf
    except ImportError:
        BufferSelf = TypeVar("BufferSelf", bound="Buffer")


class Buffer(BitType[BitVector]):
    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.

    Class Attributes:
    -----------------
    num_bits : int
        The number of bits in instances of this `Buffer` subclass.
    base_bit_type : Type[Buffer]
        The base `BitType` this class derives from. It will be `Buffer`.
    py_type : Type[BitVector]
        The type that this `BitType` represents. It is `BitVector`.

    Instance Attributes
    -------------------
    bits : BitVector
       The underlying sequence of bits of this `Buffer` object. Identical to `value`.
    value : BitVector
       The `BitVector` value of this `Buffer` object. Identical to `bits`.
    """

    """
    A BitType that represents a buffer of bits.

    Use the `specialize` method to create a subclass with the desired number of bits
        or use one of the pre-defined subclasses.
    """

    py_type = BitVector

    @property
    def value(self):
        """
        The `BitVector` value of this `Buffer`.

        The getter hands out an independent, resizable snapshot — the safe
        read every other BitType's `value` provides. Mutating the returned
        vector does not touch this buffer; use the `bits` property for the
        live, width-locked handle.

        Returns:
            BitVector: A copy of this buffer's bits.
        """
        return BitVector(self.bits)

    @value.setter
    def value(self, value):
        # Route through the bits setter: length-validates and stores into
        # width-locked storage (previously this bypassed both).
        self.bits = value

    @classmethod
    def specialize(cls: Type[BufferSelf], num_bits_: int, name_: Optional[str] = None):
        """
        Returns a subclass of Buffer with the specified number of bits.

        Args:
            num_bits_ (int): The number of bits the buffer should have.
            name_ (Optional[str], optional): The name of the subclass. Defaults to None,
                meaning the name will be _Buffer.

        Returns:
            Type[BufferSelf]: A subclass of Buffer with the specified number of bits.
        """

        class _Buffer(cls):
            _num_bits = num_bits_

        if name_:
            _Buffer.__name__ = name_

        return _Buffer

    @classmethod
    def of(
        cls: Type[BufferSelf], *, nbytes: int, name: Optional[str] = None
    ) -> Type[BufferSelf]:
        """Mint a Buffer type sized in **bytes** — the C ``uint8_t buf[N]``
        count, and the Struct-field door (Struct byte fields hold plain
        ``bytes`` and need whole-byte widths anyway). ``specialize`` is the
        bit-counted box door; sub-byte Buffers stay legal standalone and in
        legacy aggregates. ``nbytes`` is keyword-only so the declaration
        names its unit — this class's history includes a ``Buffer16`` that
        read as 16 bytes but meant 16 bits."""
        if not isinstance(nbytes, int) or nbytes < 1:
            raise ValueError(
                f"{cls.__name__}.of(): nbytes must be a positive int,"
                f" got {nbytes!r}"
            )
        return cls.specialize(nbytes * 8, name or f"{cls.__name__}x{nbytes}")


Buffer.base_bit_type = Buffer


__all__ = [
    'Buffer',
]
