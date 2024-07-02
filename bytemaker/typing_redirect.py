"""
typing_redirect.py

This module allows for Python version-agnostic typing and collections.abc imports.
    It uses Python standard library batteries where possible.
    For older versions, this module will export from typing_extensions.
"""
import sys
from importlib.util import find_spec
from typing import Any

if sys.version_info < (3, 9):
    from typing import (
        Callable,
        Iterable,
        Mapping,
        MutableMapping,
        MutableSequence,
        Sequence,
    )
else:
    from collections.abc import (
        Callable,
        Iterable,
        Mapping,
        MutableMapping,
        MutableSequence,
        Sequence,
    )

from typing import (
    ClassVar,
    Dict,
    Final,
    ForwardRef,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    overload,
    runtime_checkable,
)

if sys.version_info < (3, 12):
    if find_spec("typing_extensions"):
        from typing_extensions import Buffer
    else:
        Buffer = TypeVar("Buffer")  # Fall back to TypeVar
else:
    from collections.abc import Buffer

if sys.version_info < (3, 13):
    if find_spec("typing_extensions"):
        if find_spec("typing_extensions"):
            from typing_extensions import TypeIs
        else:
            T = TypeVar("T")
            from typing import Generic

            class TypeIs(Generic[T]):
                def __class_getitem__(cls, item):
                    return cls

else:
    from typing import TypeIs


__all__ = [
    "Any",
    "Buffer",
    "Callable",
    "ClassVar",
    "Dict",
    "Final",
    "ForwardRef",
    "Iterable",
    "Iterator",
    "List",
    "Literal",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "Optional",
    "Protocol",
    "Sequence",
    "Tuple",
    "Type",
    "TypeIs",
    "TypeVar",
    "Union",
    "get_args",
    "get_origin",
    "get_type_hints",
    "overload",
    "runtime_checkable",
]

if sys.version_info >= (3, 11):
    from typing import Self  # noqa: F401

    __all__.append("Self")
