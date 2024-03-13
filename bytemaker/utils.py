import dataclasses
import typing
import warnings
from typing import Any
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

    type_origin = typing.get_origin(union_type)

    try:
        return isinstance(obj, union_type)
    except TypeError:
        type_args = typing.get_args(union_type)

        if type_origin is typing.Union:
            constituent_types = typing.get_args(union_type)
            return any(is_instance_of_union(obj, constituent_type) for constituent_type in constituent_types)
        elif type_origin is not None and isinstance(obj, type_origin):
                type_args = typing.get_args(union_type)
                if len(type_args) == 1 and isinstance(obj, typing.Iterable):
                    return all([is_instance_of_union(obj_el, type_args[0]) for obj_el in obj])
                else:
                    raise ValueError(f"(Generic?) type {union_type} has origin {type_origin} and type args {type_args}."
                                    "Types with multiple subscripts are not supported.")
        else:
            return False
                




    # if typing.get_origin(union_type) is not typing.Union:
    #     warnings.warn(
    #         f"Checking for instance of a union type with the non-union type {union_type}"
    #         f" with origin {typing.get_origin(union_type)}. Falling back on isinstance")
    #     return isinstance(obj, union_type)
    

    # for constituent_type in constituent_types:
    #     return any(is_instance_of_union(obj, constituent_type))



    # for union_component_type in gotten_type_args:
    #     if isinstance(obj, union_component_type):
    #         return True
    # return any(isinstance(obj, union_component_type) for union_component_type in typing.get_args(union_type))


def is_subclass_of_union(obj_type: type, union_type: type):
    """
    Determines if an object is a subclass of a union type (to support Python versions <3.10).

    Args:
        obj_type (type): The object type to check
        union_type (type): The union type to check against

    Returns:
        bool: Whether the object is a subclass of the union type
    """

    if typing.get_origin(union_type) is not typing.Union:
        warnings.warn(f"Checking for subclass of a union type with the non-union type {union_type}."
                      f"Falling back on issubclass.")
        return issubclass(obj_type, union_type)
    return any(issubclass(obj_type, union_type_part) for union_type_part in typing.get_args(union_type))

# General operations


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
