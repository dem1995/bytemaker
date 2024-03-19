import dataclasses
import typing
from typing import Any, ForwardRef
from math import log2, ceil

#  General Python functionality

class classproperty(property):
    """
    Class property decorator.
    """
    def __get__(self, cls, owner):
        return classmethod(self.fget).__get__(None, owner)()


def is_instance_of_union(obj, union_type: type):
    """
    Determines if an object is an instance of a union type (to support Python versions <3.10).

    Args:
        obj (object): The object to check
        union_type (type): The union type to check against

    Returns:
        bool: Whether the object is an instance of the union type
    """

    # # Correct for unresolved references
    # if isinstance(union_type, ForwardRef):
    #     union_type = union_type.__forward_arg__
    # if isinstance(union_type, str):
    #     try:
    #         union_type = eval(union_type, globals(), locals())
    #     except NameError:
    #         raise ValueError(f"String or forward reference {union_type} could not be resolved.")
    
    # Try the default isinstance method
    try:
        return isinstance(obj, union_type)
    
    # If that does not work, try to process the union type instance recursively or generic type instance
    except TypeError:

        type_origin = typing.get_origin(union_type)

        # If the type is non-generic and non-union
        #   use the default isinstance method with the type origin
        if type_origin is None:
            return isinstance(obj, union_type)
        
        type_args = typing.get_args(union_type)


        # If the type is a union type or its instances are iterable
        #   check if the object is an instance of any of the constituent types
        #   or if the object is an iterable and its first element is an instance of the first type argument
        if type_origin is typing.Union:
            return any(is_instance_of_union(obj, type_arg) for type_arg in type_args)
        elif isinstance(obj, type_origin):
            if len(type_args) == 1 and isinstance(obj, typing.Iterable):
                return bool(obj) or is_instance_of_union(next(iter(obj)), type_args[0])

            # If the type is a multi-arg, non-union, non-generic type
            else:
                raise ValueError(f"(Generic?) type {union_type} has origin {type_origin} and type args {type_args}."
                                    "non-union types with multiple subscripts are not supported.")
        else:
            return False


def is_subclass_of_union(subtype: type, supertype: type):
    """
    Determines if an object is a subclass of a union type (to support Python versions <3.10).

    Args:
        subtype (type): The object type to check
        supertype (type): The union type to check against

    Returns:
        bool: Whether the object is a subclass of the union type
    """

    # # Correct for unresolved references
    # if isinstance(subtype, ForwardRef):
    #     subtype = subtype.__forward_arg__
    # if isinstance(subtype, str):
    #     try:
    #         subtype = eval(subtype, globals(), locals())
    #     except NameError:
    #         raise ValueError(f"String or forward reference {subtype} could not be resolved.")
    
    # if isinstance(supertype, ForwardRef):
    #     supertype = supertype.__forward_arg__
    # if isinstance(supertype, str):
    #     try:
    #         supertype = eval(supertype, globals(), locals())
    #     except NameError:
    #         raise ValueError(f"String or forward reference {supertype} could not be resolved.")
    
    # Try the default issubclass method
    try:
        return issubclass(subtype, supertype)
    
    # If that does not work, try to process the union type recursively or generic type
    except TypeError:
        supertype_origin = typing.get_origin(supertype)

        # If the supertype is a single-arged, non-generic, non-union type
        if supertype_origin is None:
            return issubclass(subtype, supertype)
        
        supertype_args = typing.get_args(supertype)

        # If the supertype is a union type or an iterable generic
        if supertype_origin is typing.Union:
            return any(is_subclass_of_union(subtype, union_type_part) for union_type_part in supertype_args)
        elif issubclass(supertype_origin, typing.Iterable) and len(supertype_args) == 1:
            return issubclass(subtype, supertype_origin) and is_subclass_of_union(subtype, supertype_args[0])
        

        # If the supertype is a multi-arg, non-union, non-generic type
        raise ValueError(f"Supertype {supertype} has origin {supertype_origin} and type args {supertype_args}."
                        "non-union supertypes with multiple subscripts are not supported.")


# Byte-related operations

class _ByteConvertibleMeta(type):
    """
    This is used to create IsByteConvertible, a type to allow checking \
        whether an object or instances of a class can be converted to a bytes object using isinstance or issubclass.
    """
    def __instancecheck__(self, __instance: Any) -> bool:
        try:
            bytes(__instance)
            return True
        except Exception:
            return False

    def __subclasscheck__(self, __subclass: type) -> bool:
        return (
            hasattr(__subclass, '__bytes__') or
            is_subclass_of_union(__subclass, typing.Union[bytes, bytearray, memoryview]) or
            (hasattr(__subclass, '__getitem__') and hasattr(__subclass, 'format') and
                hasattr(__subclass, 'shape') and hasattr(__subclass, 'strides'))
        )


class ByteConvertible(metaclass=_ByteConvertibleMeta):
    """
    Has __instancecheck__ and __subclasscheck__ methods to allow checking whether an object can be converted to a bytes object
        using :class:`python:bytes`
    """
    pass


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
    Determines the number of bits required to represent a signed integer in two's complement.

    Args:
        n (int): The (signed) integer for which to determine the number of bits required

    Returns:
        int: The number of bits required to represent the integer in two's-complement notation
    """
    if n == 0:
        return 1  # Technically can represent 0 with 0 bits in two's complement, but this is not useful

    is_greq_than_zero = n >= 0
    abs_val = abs(n)
    is_power_of_two = (abs_val & (abs_val - 1)) == 0

    if is_greq_than_zero or not is_power_of_two:
        return ceil(log2(abs_val + 1)) + 1  # Account for extra at negative extreme
    else:
        return int(log2(abs_val)) + 1


def twos_complement(number, n_bits=32):
    """
    Convert an integer to its two's complement representation.

    :param number: The integer to convert.
    :param bits: The bit width for the two's complement representation.
    :return: A string representing the two's complement of the number.
    """
    if number < 0:
        number = (1 << n_bits) + number
    format_string = '{:0' + str(n_bits) + 'b}'
    return format_string.format(number)
