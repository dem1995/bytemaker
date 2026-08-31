"""
typing_redirect.py

Version-agnostic imports for ``typing`` and ``collections.abc``. Names come
from the Python standard library wherever the running version provides
them, and from ``typing_extensions`` otherwise.

``typing_extensions`` is a declared dependency below 3.13 (see pyproject),
so every pre-3.13 branch here imports it unconditionally. A missing name is
then an ImportError naming the missing distribution. The alternative would
be a shim that silently degrades the type to ``Any``, which would also
discard the checker's guarantees.

``ClassVar`` is deliberately absent. Import it from ``typing`` directly:
pyright's ``dataclass_transform`` field collection does not follow a
re-exported alias of it, so a redirected ``ClassVar`` on a Struct-like base
turns that base's class attributes into synthesized ``__init__`` parameters.
It needs no version agnosticism anyway.
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

    # get_origin/get_args/get_type_hints must come from typing_extensions
    # alongside Annotated itself: 3.8's typing predates Annotated, so its
    # get_origin returns None for the typing_extensions form and every
    # alias unwrap in structs/introspect fails at class creation.
    from typing_extensions import (
        Annotated,
        get_args,
        get_origin,
        get_type_hints,
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
    from typing import Annotated, get_args, get_origin, get_type_hints

if sys.version_info < (3, 10):
    UnionType = Any  # no typing_extensions equivalent; types.UnionType is 3.10+
    from typing_extensions import Concatenate, ParamSpec
else:
    from types import UnionType
    from typing import Concatenate, ParamSpec

from collections.abc import Hashable
from typing import (
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
    from typing import Self, dataclass_transform  # noqa: F401
else:
    from typing_extensions import Self, dataclass_transform  # noqa: F401

__all__ += ["Self", "dataclass_transform"]
