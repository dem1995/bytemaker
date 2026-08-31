from __future__ import annotations

import dataclasses

from bytemaker.typing_redirect import (
    Annotated,
    Any,
    Dict,
    Hashable,
    ItemsView,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    Optional,
    Sequence,
    TypeVar,
    Union,
    get_args,
    get_origin,
)


def unwrap_alias(obj):
    """Unwrap a ``u16``/``s5`` field alias to the codec inside it, so that
    ``Annotated[int, UInt16]`` becomes ``UInt16``.

    Anything else passes through untouched.

    The aliases exist so record declarations read like C, and people then
    reach for the same name anywhere a codec is wanted. That is a natural
    move, but it used to fail three layers down with a compile error about
    ``Annotated``. Any codec-accepting boundary should run its argument
    through here first, so that both spellings of a scalar mean the scalar.
    """
    if get_origin(obj) is Annotated:
        for meta in get_args(obj)[1:]:
            if isinstance(getattr(meta, "num_bits", None), int):
                return meta
    return obj


#  General Python functionality


class classproperty:
    "Emulate class-level property similar to instance-level property"

    def __init__(self, fget=None, fset=None, fdel=None, doc=None):
        self.fget = fget
        self.fset = fset
        self.fdel = fdel
        if doc is None and fget is not None:
            doc = fget.__doc__
        self.__doc__ = doc

    def __get__(self, obj, objtype=None):
        if objtype is None:
            objtype = type(obj)
        if self.fget is None:
            raise AttributeError("unreadable attribute")
        return self.fget.__get__(None, objtype)()

    def __set__(self, obj, value):
        if self.fset is None:
            raise AttributeError("can't set attribute")
        objtype = type(obj)
        return self.fset.__get__(None, objtype)(value)

    def __delete__(self, obj):
        if self.fdel is None:
            raise AttributeError("can't delete attribute")
        objtype = type(obj)
        return self.fdel.__get__(None, objtype)()

    def getter(self, fget):
        return type(self)(fget, self.fset, self.fdel, self.__doc__)

    def setter(self, fset):
        return type(self)(self.fget, fset, self.fdel, self.__doc__)

    def deleter(self, fdel):
        return type(self)(self.fget, self.fset, fdel, self.__doc__)


class Trie:
    def __init__(self):
        self.children = {}
        self.is_end_of_suffix = False
        self.is_start_of_prefix = False

    @staticmethod
    def build_suffix_trie(suffixes: Iterable[Sequence[int]]) -> Trie:
        root = Trie()
        for suffix in suffixes:
            current = root
            # Insert reversed suffix into trie
            for bit in reversed(suffix):
                if bit not in current.children:
                    current.children[bit] = Trie()
                current = current.children[bit]
            current.is_end_of_suffix = True
        return root

    @staticmethod
    def build_prefix_trie(prefixes: Iterable[Iterable[int]]) -> Trie:
        root = Trie()
        for prefix in prefixes:
            current = root
            for bit in prefix:
                if bit not in current.children:
                    current.children[bit] = Trie()
                current = current.children[bit]
            current.is_start_of_prefix = True
        return root


def validate_endianness(
    endianness: Any, name: str = "endianness", exc: type = ValueError
) -> Literal["big", "little"]:
    """
    Validates a byte-order argument at an API intake point.

    Every bytemaker parameter that selects a byte order accepts exactly
    "big" or "little". Historically any other string fell through into
    whichever branch a call site's equality test happened to pick (a typo
    like "bigg" serialized little-endian through BitType.__bytes__ but
    big-endian through pytype_to_bytes), so the check lives here and runs
    at intake, not at use.

    Args:
        endianness: The value to validate.
        name (str): The parameter name to blame in the error message.
            Defaults to "endianness".
        exc (type): The exception class to raise. Defaults to ValueError;
            schema-compile intake points pass PlanCompileError.

    Returns:
        Literal["big", "little"]: ``endianness``, unchanged.

    Raises:
        exc: If ``endianness`` is not exactly "big" or "little".
    """
    if endianness not in ("big", "little"):
        raise exc(f"{name} must be 'big' or 'little'; got {endianness!r}")
    return endianness


def is_instance_of_union(obj, union_type: type):
    """
    Determines if an object is an instance of a union type
     (to support Python versions <3.10).

    Args:
        obj (object): The object to check
        union_type (type): The union type to check against

    Returns:
        bool: Whether the object is an instance of the union type
    """

    # Try the default isinstance method
    try:
        return isinstance(obj, union_type)

    # If that does not work, try to process the union type
    # instance recursively or as generic type instance
    except TypeError:
        type_origin = get_origin(union_type)

        # If the type is non-generic and non-union
        #   use the default isinstance method with the type origin
        if type_origin is None:
            return isinstance(obj, union_type)

        type_args = get_args(union_type)

        # If the type is a Literal type
        #   check if the object equals one of the literal values
        if type_origin is Literal:
            return obj in type_args

        # If the type is a union type or its instances are iterable
        #   check if the object is an instance of any
        #       of the constituent types
        #   or if the object is an iterable and all of its elements
        #       are instances of the single type argument
        if type_origin is Union:
            return any(is_instance_of_union(obj, type_arg) for type_arg in type_args)
        elif isinstance(obj, type_origin):
            if len(type_args) == 1 and isinstance(obj, Iterable):
                # One-shot iterators cannot be inspected without consuming
                #   them; accept and let the consumer validate the elements
                if isinstance(obj, Iterator):
                    return True
                return all(
                    is_instance_of_union(element, type_args[0]) for element in obj
                )

            # If the type is a multi-arg, non-union, non-generic type
            else:
                raise ValueError(
                    f"(Generic?) type {union_type} has origin {type_origin}"
                    f" and type args {type_args}."
                    f" Non-union types with multiple subscripts are not"
                    f" supported."
                )
        else:
            return False


def is_subclass_of_union(subtype: type, supertype):
    """
    Determines if an object is a subclass of a union type
        (to support Python versions <3.10).

    Args:
        subtype (type): The object type to check
        supertype (type): The union type to check against

    Returns:
        bool: Whether the object is a subclass of the union type
    """

    # Try the default issubclass method
    try:
        return issubclass(subtype, supertype)

    # If that does not work, try to process the union type recursively
    # or as a generic type
    except TypeError:
        supertype_origin = get_origin(supertype)

        # If the supertype is a single-arged, non-generic, non-union type
        if supertype_origin is None:
            return issubclass(subtype, supertype)

        supertype_args = get_args(supertype)

        # If the supertype is a union type or an iterable generic
        if supertype_origin is Union:
            return any(
                is_subclass_of_union(subtype, union_type_part)
                for union_type_part in supertype_args
            )
        elif issubclass(supertype_origin, Iterable) and len(supertype_args) == 1:
            return issubclass(subtype, supertype_origin) and is_subclass_of_union(
                subtype, supertype_args[0]
            )

        # If the supertype is a multi-arg, non-union, non-generic type
        raise ValueError(
            f"Supertype {supertype} has origin {supertype_origin}"
            f" and type args {supertype_args}."
            "Non-union supertypes with multiple subscripts are not supported."
        )


K = TypeVar("K")
V = TypeVar("V")


class HashableMapping(Mapping[K, V], Hashable):
    pass


class FrozenDict(HashableMapping[K, V]):
    def __init__(self, input_dict: Dict[K, V]):
        self._data = dict(input_dict)
        self._hash: Optional[int] = None

    def __getitem__(self, key: K) -> V:
        return self._data[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def items(self) -> ItemsView[K, V]:
        return self._data.items()

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(tuple(sorted(self.items())))
        return self._hash

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._data})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return False


# Byte-related operations


class _ByteConvertibleMeta(type):
    """
    This is used to create IsByteConvertible, a type to allow checking\
        whether an object or instances of a class can be converted to a\
        bytes object using isinstance or issubclass.
    """

    def __instancecheck__(self, __instance: Any) -> bool:
        try:
            bytes(__instance)
            return True
        except Exception:
            # Deliberately broad: this is an isinstance() probe. A foreign
            # __bytes__ raising anything means "not byte-convertible";
            # propagating would make isinstance() itself throw.
            return False

    def __subclasscheck__(self, __subclass: Any) -> bool:
        return (
            hasattr(__subclass, "__bytes__")
            or is_subclass_of_union(__subclass, Union[bytes, bytearray, memoryview])
            or (
                hasattr(__subclass, "__getitem__")
                and hasattr(__subclass, "format")
                and hasattr(__subclass, "shape")
                and hasattr(__subclass, "strides")
            )
        )


class ByteConvertible(metaclass=_ByteConvertibleMeta):
    """
    Has __instancecheck__ and __subclasscheck__ methods\
        to allow checking whether an object can be converted to a bytes\
        object using :class:`python:bytes`
    """


# Aggregate type to bytes
class DataClassTypeMeta(type):
    def __instancecheck__(cls, instance):
        return dataclasses.is_dataclass(instance)

    def __subclasscheck__(cls, subclass):
        return dataclasses.is_dataclass(subclass)


class DataClassType(metaclass=DataClassTypeMeta):
    pass


def twos_complement_bit_length(n: int):
    """
    Determines the number of bits required to represent a signed\
        integer in two's complement.

    Args:
        n (int): The (signed) integer for which to determine the number\
            of bits required

    Returns:
        int: The number of bits required to represent the integer in\
            two's-complement notation
    """
    if n == 0:
        return 1  # Technically can represent 0 with 0 bits in
        # two's complement, but this is not useful

    # Exact integer arithmetic (float log2 loses precision for n >= 2**49:
    # 2**k + 1 is indistinguishable from 2**k, so a positive power of two
    # would be under-sized by one bit and lose its sign bit).
    if n > 0:
        # magnitude bits plus a leading 0 sign bit
        return n.bit_length() + 1
    # negative: ~n == -n - 1; its magnitude width plus the sign bit
    return (~n).bit_length() + 1


def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    Args:
        number (int): The integer to convert. Must fit in ``n_bits`` bits:
            ``-(2**(n_bits-1)) <= number < 2**(n_bits-1)``.
        n_bits (int, optional): The bit width for the two's complement
            representation. Defaults to 32.

    Returns:
        str: A string of exactly ``n_bits`` binary digits.

    Raises:
        ValueError: If ``number`` does not fit in ``n_bits`` bits.
    """
    if not -(1 << (n_bits - 1)) <= number < (1 << (n_bits - 1)):
        raise ValueError(f"{number} does not fit in {n_bits} bits in two's complement")
    if number < 0:
        number = (1 << n_bits) + number
    format_string = "{:0" + str(n_bits) + "b}"
    return format_string.format(number)
