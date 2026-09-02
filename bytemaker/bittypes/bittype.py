from __future__ import annotations

import math
import operator
import os
import struct
import sys
import warnings
from abc import ABC, ABCMeta, abstractmethod

from bytemaker.bitvector import BitVector, FixedLengthBitVector
from bytemaker.typing_redirect import (
    Any,
    Callable,
    Final,
    Generic,
    Literal,
    Optional,
    Type,
    TypeVar,
)
from bytemaker.utils import classproperty, validate_endianness

T = TypeVar("T")
S = TypeVar("S")


class NarrowingWarning(UserWarning):
    """A store's C-style narrowing actually changed the value.

    The silent wrap/mask behavior is the deliberate default (it is what a C
    assignment does); this warning is the opt-in analog of a C compiler's
    ``-Wconversion``. Enable via :class:`NarrowingConfig` and escalate to an
    error with the stdlib warnings filters if desired::

        warnings.simplefilter("error", NarrowingWarning)
    """


class NarrowingConfig:
    """Opt-in checked stores (the ``-Wconversion`` knob).

    When ``warn`` is True, integer stores that change the assigned value
    (Struct field descriptors and Int/UInt/SInt value setters) emit a
    :class:`NarrowingWarning`. Default off (silent C semantics). Also
    seedable via the ``BYTEMAKER_WARN_NARROWING`` environment variable.
    """

    warn: bool = bool(os.environ.get("BYTEMAKER_WARN_NARROWING"))


def _warn_narrowing(original, stored, target):
    # Attribute the warning to the first frame outside bytemaker, however
    # deep the internal chain is (field descriptor, array coercion, box
    # setter, __init__): a fixed stacklevel is right for exactly one of
    # those chains and blames library internals for all the others.
    level = 1
    frame = sys._getframe()
    while frame is not None:
        # A non-string __name__ (possible under exec with custom globals)
        # marks user code just as surely as a foreign module name does.
        mod = frame.f_globals.get("__name__")
        if not (isinstance(mod, str) and mod.partition(".")[0] == "bytemaker"):
            break
        frame = frame.f_back
        level += 1
    warnings.warn(
        f"narrowing store to {target}: {original!r} became {stored!r}",
        NarrowingWarning,
        stacklevel=level,
    )


def _narrow_int(value: int, num_bits: int, signed: bool, target: str) -> int:
    """Narrow ``value`` to ``num_bits`` the way C does.

    Signed targets wrap and unsigned targets mask. When the narrowing
    actually changed the value, this also emits the opt-in
    :class:`NarrowingWarning`. Every integer value setter routes through
    here, so the truncation and the diagnostic cannot drift apart.
    """
    if signed:
        half = 1 << (num_bits - 1)
        narrowed = ((value + half) % (half << 1)) - half
    else:
        narrowed = value & ((1 << num_bits) - 1)
    if NarrowingConfig.warn and narrowed != value:
        _warn_narrowing(value, narrowed, target)
    return narrowed


#: Stands in for ``Self`` on the methods below. A bound TypeVar, in both
#: planes: the runtime once tried ``from typing_redirect import Self`` first,
#: but that spelling is missing the ``bytemaker.`` prefix, so it always
#: raised and always fell back to this identical TypeVar -- while promising a
#: reader the two planes might differ.
BitSelf = TypeVar("BitSelf", bound="BitType")


class BitTypeMeta(ABCMeta):
    """Metaclass of BitType: adds ``cls * N`` -> ``bytemaker.structs.Array``
    codec sugar (``UInt16 * 257`` is a 257-element little/big-endian-agnostic
    array codec; pick the byte order with ``Array.of(UInt16, 257, endian)``).
    """

    def __mul__(cls, count: int):
        from bytemaker.structs import Array

        return Array.of(cls, count)

    def __rmul__(cls, count: int):
        # Class-object attribute lookup finds the instance operator
        # (e.g. Int.__mul__) first, so dispatch through the metaclass
        # explicitly to get the `N * Cls` array sugar (== `Cls * N`).
        return type(cls).__mul__(cls, count)


class BitType(ABC, Generic[T], metaclass=BitTypeMeta):
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
        self._endianness = validate_endianness(endianness)

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

    @classproperty
    @classmethod
    def num_bytes(cls) -> int:
        """
        The whole bytes this type's serialized form occupies.

        Sub-byte widths round up, so this always matches
        ``len(bytes(instance))``. The name is symmetric with
        ``Plan.num_bytes``, ``Array.num_bytes``, and ``Struct.num_bytes``.

        Returns:
            int: The number of bytes in the BitType's serialized form.
        """
        return (cls._num_bits + 7) // 8

    @property
    @abstractmethod
    def value(self) -> T:
        """
        The (readonly) getter for the (Pythonic) value of the BitType.

        To set the value directly, use the `value` setter.
        To directly adjust the value more complicatedly, use operations
        available directly on the BitType object rather than on the value
        returned by this property.

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

        The handout is **live and width-locked**: index and
        length-preserving slice writes mutate this BitType in place;
        length-changing mutation raises ValueError. Take ``BitVector(bits)``
        for a resizable snapshot.

        Returns:
            BitVector: The sequence of bits the BitType uses to represent its value.
        """
        return self._bits

    @bits.setter
    def bits(self, bits: BitVector):
        # Assignment snapshots into width-locked storage; the handout above
        # is live. (A caller's vector never becomes a hidden alias of the
        # box, and no aliased mutation can change the box's width.)
        # Validate the *constructed* width, not len(source): for byte
        # sources len() counts bytes, for "0x.." strings it counts
        # characters, both unrelated to the bit width they construct.
        new = FixedLengthBitVector(bits)
        if len(new) != self.num_bits:
            raise ValueError(f"Expected {self.num_bits} bits, got {len(new)}")
        self._bits = new

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
        Return a string that recreates this BitType when evaluated with the
        class name in scope.

        The repr carries the exact bits rather than the value. Bit patterns
        that the value setter would normalize, such as float NaN payloads,
        therefore survive the round trip. Subclasses with extra constructor
        state append it as further keyword arguments, as `SInt` does with
        `int_format=...`.

        Returns:
            str: ClassName(bits='<01 string>', endianness=<'big' or 'little'>)
        """
        return (
            f"{self.__class__.__name__}"
            f"(bits={self.bits.to01()!r}, endianness={self.endianness!r})"
        )

    def __format__(self, format_spec):
        """
        No spec formats the box for display (same as ``str``: the sized,
        self-describing form). Any spec formats the *value*, so numeric specs
        work exactly as on the plain value: ``f"{UInt6(40):02x}" == '28'``.
        """
        if format_spec == "":
            return str(self)
        return format(self.value, format_spec)

    def __Bits__(self) -> BitVector:
        """
        BitsCastable protocol hook: makes ``BitVector(bittype)`` (and every
        BitsConstructible site) accept boxes.

        Returns the internal bits **live and width-locked**, consistent
        with the live ``.bits`` policy, and safe because ``BitVector(...)``
        copy-constructs from the result. Construct a ``BitVector`` when you
        need an independent, resizable snapshot.
        """
        return self._bits

    def __eq__(self, other):
        """
        Compare this BitType to another object.

        Two BitTypes are equal when their values are equal. Equal BitTypes
        may still have differing internal bit representations: -0 and +0 are
        stored as different bits but compare equal.

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
        Compare this BitType to another object for inequality.

        Two BitTypes are equal when their values are equal. Equal BitTypes
        may still have differing internal bit representations: -0 and +0 are
        stored as different bits but compare equal.

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

    # Temporary methods
    # TODO remove
    def to_bits(self) -> BitVector:
        """DEPRECATED
        Use the `bits` property instead.

        Obtains the bit representation of the BitType.

        Returns:
            BitVector: The sequence of bits of the BitType.
        """
        warnings.warn(
            "BitType.to_bits() is deprecated; use the .bits property",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.bits

    @classmethod
    def from_bits(cls, bits: BitVector):
        """DEPRECATED
        Use the constructor with a BitVector-like object instead.

        Creates a new BitType object from a sequence of bits.


        Args:
            bits (BitVector): The sequence of bits to create the BitType from.
        """
        warnings.warn(
            f"{cls.__name__}.from_bits() is deprecated;"
            f" use the constructor: {cls.__name__}(bits=...)",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls(bits=bits)

    def _binary_value_op(
        self: BitSelf, other: Any, operation: Callable[[BitSelf, Any], BitSelf]
    ):
        """
        Performs a binary operation on the BitType object's value and another object.
        If the other object is a BitType object, it attempts to use the other object's
            value as the multiplicand.
        Otherwise, it first attempts to use other directly as the multiplicand,
            then falls back to trying to use other.value.

        Args:
            other (Any): The other object to perform the operation with.
            operation (Callable[[BitSelf, Any], BitSelf]): The operation to perform.

        Returns:
            BitSelf: The BitType result of the operation., or
                NotImplemented if the operation could not be performed.
        """

        def attempt_operation(other_value: Any):
            try:
                product = operation(self.value, other_value)

                if not isinstance(product, type(self).py_type):
                    return NotImplemented
                return type(self)(product)
            except TypeError:
                return NotImplemented

        if isinstance(other, BitType):
            return attempt_operation(other.value)

        try:
            return attempt_operation(other)
        except TypeError:
            try:
                return attempt_operation(other.value)
            except TypeError:
                return NotImplemented

    def _promoted_value_op(self, other, operation):
        """
        Apply a binary operator under the C promotion model.

        Both operands are unboxed to plain values, the operator runs at full
        width, and the plain result is returned. Nothing is re-boxed and
        nothing wraps at the operator, because C never wraps mid-expression:
        the integer promotions convert the operands first.

        Width re-attaches only at stores. The narrowing cast is spelled as
        the constructor, so ``UInt8(a + b)`` means ``(uint8_t)(a + b)``.

        Used by the numeric BitTypes, `Int` and `Float`.

        Args:
            other (Any): The other operand. A BitType is unboxed to its value.
            operation (Callable): The binary operator to apply.

        Returns:
            Any: The plain (unboxed) result, or NotImplemented.
        """
        if isinstance(other, BitType):
            other = other.value
        try:
            return operation(self.value, other)
        except TypeError:
            return NotImplemented

    def _inplace_value_op(self, other, operation):
        """
        Apply a compound assignment operator the way C does.

        The operator runs at full width on the unboxed values, then the
        result is converted back to this box's type at the store. The value
        setter is the narrowing cast, so ``u += 1`` keeps ``u``'s type and
        wraps at ``u``'s own width.

        The conversion goes through ``py_type``, which truncates a
        non-integral result toward zero, matching C's float-to-int
        conversion.

        Args:
            other (Any): The other operand. A BitType is unboxed to its value.
            operation (Callable): The binary operator to apply.

        Returns:
            BitSelf: ``self``, after narrowing the result into this box, or
                NotImplemented.
        """
        if isinstance(other, BitType):
            other = other.value
        try:
            result = operation(self.value, other)
        except TypeError:
            return NotImplemented
        self.value = self.py_type(result)
        return self

    def _binary_bits_op(
        self: BitSelf, other: Any, operation: Callable[[BitSelf, Any], BitSelf]
    ):
        """
        Performs a binary operation on the BitType object's bits and another object.
        If the other object is a BitType object, it attempts to use the other object's
            bits as the multiplicand.
        Otherwise, it first attempts to use other directly as the multiplicand,
            then falls back to trying to use other.bits.

        Args:
            other (Any): The other object to perform the operation with.
            operation (Callable[[BitSelf, Any], BitSelf]): The operation to perform.

        Returns:
            BitSelf: The BitType result of the operation.

        Raises:
            TypeError: If the operation could not be performed.
        """

        def attempt_operation(other_bits: Any):
            try:
                product = operation(self.bits, other_bits)

                try:
                    return type(self)(product)
                except Exception:
                    return NotImplemented
            except TypeError:
                return NotImplemented

        if isinstance(other, BitType):
            return attempt_operation(other.bits)

        try:
            return attempt_operation(other)
        except TypeError:
            try:
                return attempt_operation(other.bits)
            except TypeError:
                return NotImplemented

    # Magic bits operations

    def __lshift__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, operator.lshift)

    def __rshift__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, operator.rshift)

    def __and__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, operator.and_)

    def __rand__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, lambda x, y: y & x)

    def __or__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, operator.or_)

    def __ror__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, lambda x, y: y | x)

    def __xor__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, operator.xor)

    def __rxor__(self: BitSelf, other: Any) -> BitSelf:
        return self._binary_bits_op(other, lambda x, y: y ^ x)

    def __invert__(self: BitSelf) -> BitSelf:
        return type(self)(bits=~self.bits)


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
        If true, struct packing and unpacking are skipped, and the value is
        calculated using other methods on the MRO instead.

    packing_format : str
        The struct-packing format. It is always big-endian (">") because
        endianness is applied later, at the bytes boundary, by
        BitType.__bytes__().
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
        Returns the struct packing format for the class.

        Always uses big-endian format because bits are stored in canonical
        big-endian order internally. Endianness is applied at the bytes
        boundary by BitType.__bytes__().

        Returns:
            str: the struct packing format for the subclass.
        """
        cls = self.__class__
        return f">{cls.packing_format_letter}"

    @property
    def value(self) -> T:
        if not self.skip_struct_packing:
            the_bits = self.bits
            if not len(the_bits) % 8 == 0:
                the_bits = BitVector(8 - len(the_bits) % 8) + the_bits
            return struct.unpack(self.packing_format, bytes(the_bits))[0]
        else:
            return super().value

    @value.setter
    def value(self, value: T):
        if not self.skip_struct_packing:
            if self.py_type is int and isinstance(value, int):
                # C-style narrowing: wrap an out-of-range integer to the low
                # num_bits bits instead of letting struct.pack raise, matching
                # (uintN_t)/(intN_t) truncation. Floats are packed unchanged.
                # struct's integer format letters are lowercase for signed
                # types (b/h/i/q) and uppercase for unsigned (B/H/I/Q).
                value = _narrow_int(
                    value,
                    self.num_bits,
                    signed=self.packing_format_letter.islower(),
                    target=type(self).__name__,
                )
            try:
                packed = struct.pack(self.packing_format, value)
            except OverflowError:
                # IEEE-754/C conversion semantics for the float widths: a
                # finite magnitude too large for this type saturates to
                # signed infinity (matching the pure-Python Float codec)
                # instead of raising. Report it under warn mode, like the
                # integer-narrowing path does.
                if self.py_type is not float:
                    raise
                saturated = math.copysign(float("inf"), value)
                if NarrowingConfig.warn:
                    _warn_narrowing(value, saturated, type(self).__name__)
                packed = struct.pack(self.packing_format, saturated)
            self._bits = FixedLengthBitVector(packed)
        else:
            # ``super().value = value`` does not work: super() proxies do not
            # support attribute assignment, so it raised AttributeError
            # whenever skip_struct_packing was true (e.g. any SInt8/16/32/64
            # with a non-two's-complement int_format). Invoke the next
            # value setter in the MRO explicitly instead.
            super(StructPackedBitType, type(self)).value.fset(self, value)


def bytes_to_bittype(
    unitbytes: bytes,
    unittype: type[BitType],
    endianness: Literal["big", "little"] = "big",
) -> BitType:
    """
    Converts a bytes object to an instance of the provided BitType object.

    Args:
        unitbytes (bytes): The bytes object to convert.
        unittype (type[BitType]): The BitType object to convert to.
        endianness: The byte order of the input bytes.
            Defaults to "big".

    Returns:
        BitType: The BitType object created from the bytes object.
    """
    if validate_endianness(endianness) == "little":
        unitbytes = unitbytes[::-1]
    # bytes go straight to the bits setter, which snapshots into locked
    # storage; a BitVector(...) wrap here would just be a second copy.
    return unittype(bits=unitbytes)
