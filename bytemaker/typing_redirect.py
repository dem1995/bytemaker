"""
typing_redirect.py

This module allows for Python version-agnostic typing and collections.abc imports.
    It uses Python standard library batteries where possible.
    For older versions, this module will export from typing_extensions.
"""
import sys

if sys.version_info < (3, 9):
    from typing import (
        Callable,
        Iterable,
        Mapping,
        MutableMapping,
        MutableSequence,
        Sequence
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
    Any,
    ClassVar,
    Dict,
    Final,
    ForwardRef,
    Iterator,
    List,
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

__all__ = [
    "Any",
    "Callable",
    "ClassVar",
    "Dict",
    "Final",
    "ForwardRef",
    "Iterable",
    "Iterator",
    "List",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "Optional",
    "Protocol",
    "Sequence",
    "Tuple",
    "Type",
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
