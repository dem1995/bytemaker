"""
typing_redirect.py

This module allows for Python version-agnostic typing and collections.abc imports.
    It uses Python standard library batteries where possible.
    For older versions, this module will export from typing_extensions.

``typing_extensions`` is a DECLARED dependency below 3.13 (see pyproject), so
every pre-3.13 branch here imports it unconditionally: a missing name is an
ImportError naming the missing distribution, not a silently degraded shim that
turns a type into ``Any`` and takes the checker's guarantees with it.
"""

import sys
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
    from typing_extensions import Annotated
else:
    from collections.abc import (
        Callable,
        Iterable,
        Mapping,
        MutableMapping,
        MutableSequence,
        Sequence,
    )
    from typing import Annotated

if sys.version_info < (3, 10):
    UnionType = Any  # no typing_extensions equivalent; types.UnionType is 3.10+
    from typing_extensions import Concatenate, ParamSpec
else:
    from types import UnionType
    from typing import Concatenate, ParamSpec

from collections.abc import Hashable
from typing import (
    ClassVar,
    Dict,
    Final,
    ForwardRef,
    Generic,
    ItemsView,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Set,
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
    from typing_extensions import Buffer
else:
    from collections.abc import Buffer

if sys.version_info < (3, 13):
    from typing_extensions import TypeIs  # type: ignore[reportAssignmentType]
else:
    from typing import TypeIs


__all__ = [
    "Annotated",
    "Any",
    "Buffer",
    "Callable",
    "ClassVar",
    "Concatenate",
    "Dict",
    "Final",
    "ForwardRef",
    "Generic",
    "Hashable",
    "ItemsView",
    "Iterable",
    "Iterator",
    "List",
    "Literal",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "Optional",
    "ParamSpec",
    "Protocol",
    "Set",
    "Sequence",
    "Tuple",
    "Type",
    "TypeIs",
    "TypeVar",
    "Union",
    "UnionType",
    "get_args",
    "get_origin",
    "get_type_hints",
    "overload",
    "runtime_checkable",
]

if sys.version_info >= (3, 11):
    from typing import Self  # noqa: F401
else:
    from typing_extensions import Self  # noqa: F401

__all__.append("Self")
