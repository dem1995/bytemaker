from bytemaker.bittypes.bittype import BitType
from bytemaker.bitvector import BitVector
from bytemaker.typing_redirect import Optional, Type, TypeVar

#: See the note on ``BitSelf`` in bittypes/bittype.py: a bound TypeVar in
#: both planes, the always-failing typing_redirect import removed.
BufferSelf = TypeVar("BufferSelf", bound="Buffer")


class Buffer(BitType[BitVector]):
    """
    A BitType that represents a buffer of bits.

    Two classmethods create sized subclasses. `of` sizes the buffer in
    whole bytes and is the entry point Struct fields use. `specialize`
    sizes it in an exact number of bits.

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
       The underlying sequence of bits of this `Buffer` object. The vector
       returned is live and width-locked; see `BitType.bits`.
    value : BitVector
       An independent, resizable snapshot of this `Buffer` object's bits. It
       equals `bits` by value, but mutating it does not affect the buffer.
    """

    py_type = BitVector

    @property
    def value(self):
        """
        The `BitVector` value of this `Buffer`.

        The getter returns an independent, resizable snapshot, which is the
        safe read that every other BitType's `value` provides. Mutating the
        returned vector does not affect this buffer. Use the `bits` property
        instead when you want the live, width-locked handle.

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
        """Create a Buffer subclass sized in bytes, like ``uint8_t buf[N]``.

        Struct byte fields hold plain ``bytes`` and therefore need
        whole-byte widths, so this is the constructor Struct fields use.
        Use ``specialize`` when you need a size in bits. Sub-byte Buffers
        remain legal both standalone and inside legacy aggregates.

        ``nbytes`` is keyword-only so that every declaration names its unit.
        This class's history includes a ``Buffer16`` that read as 16 bytes
        but meant 16 bits.
        """
        if not isinstance(nbytes, int) or nbytes < 1:
            raise ValueError(
                f"{cls.__name__}.of(): nbytes must be a positive int,"
                f" got {nbytes!r}"
            )
        return cls.specialize(nbytes * 8, name or f"{cls.__name__}x{nbytes}")


Buffer.base_bit_type = Buffer


__all__ = [
    "Buffer",
]
