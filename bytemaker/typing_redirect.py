"""
typing_redirect.py

This module allows for Python version-agnostic typing and collections.abc imports.
    It uses Python standard library batteries for verions >=3.9.
    For versions <3.9, it uses the typing_extensions module.
"""
import sys

if sys.version_info < (3, 9):
    from typing import ClassVar, Final, Protocol, Type, runtime_checkable

    from typing_extensions import (
        Annotated,
        Any,
        Callable,
        Dict,
        ForwardRef,
        Iterable,
        Iterator,
        List,
        Mapping,
        MutableMapping,
        MutableSequence,
        Optional,
        Self,
        Sequence,
        Tuple,
        TypeVar,
        Union,
        get_args,
        get_origin,
        get_type_hints,
        overload,
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
        Annotated,
        Any,
        ClassVar,
        Dict,
        Final,
        ForwardRef,
        Iterator,
        List,
        Optional,
        Protocol,
        Self,
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
    "Annotated",
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
    "Self",
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
