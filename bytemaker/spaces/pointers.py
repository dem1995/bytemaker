"""Typed addresses: :class:`Ptr`, :class:`PtrValue`, :class:`PtrAdapter`.

A pointer field decodes to a :class:`PtrValue`, an integer that retains the
adapter for its target. That adapter provides the value's ``.deref(space)``
method. It also tells a coverage audit what the address is supposed to
point at.

Nothing here is lazy. Dereferencing is always an explicit call, and records
stay detached values.
"""

import sys
from functools import partial
from typing import TYPE_CHECKING, cast

from bytemaker.adapters import Adapted, Adapter
from bytemaker.structs import Array, StructMeta, _structs_named
from bytemaker.typing_redirect import Any, Optional

if TYPE_CHECKING:
    from .spaces import Space


def _identity(value):
    return value


class PtrAdapter(Adapter):
    """The :class:`Adapter` half of a :class:`Ptr`.

    It stores the pointee's codec, so a record can be dereferenced without a
    lookup table.

    The codec has to live on the adapter rather than on the wire type.
    :class:`Adapted` codecs are split into a base and an adapter at class
    definition time, and the adapter is the half that survives into
    ``_bm_adapters`` and :func:`~bytemaker.introspect.fields_of`.
    """

    __slots__ = ("_target", "inner", "module")

    #: The target as GIVEN: a codec, a name or callable awaiting
    #: resolution, or None. Read it through :attr:`target`, which resolves
    #: the deferred forms and memoizes the result.
    _target: Any
    inner: Optional[Adapter]
    module: Optional[str]

    def __init__(self, target=None, inner=None, name=None, module=None):
        if inner is not None and not isinstance(inner, Adapter):
            raise TypeError(f"Ptr adapt= must be an Adapter, got {inner!r}")
        if not (
            target is None
            or _is_codec(target)
            or isinstance(target, str)
            or callable(target)
        ):
            raise TypeError(
                f"Ptr target must be a codec (Struct class, BitType class,"
                f" Array, fused adapter@BitType), a name to resolve later, a"
                f" zero-argument callable returning one, or None; got"
                f" {target!r}"
            )
        inner_load = inner.load if inner is not None else _identity
        store = inner.store if inner is not None else _identity
        label = name or _default_ptr_name(target)
        # Every read path goes through this load: record fields, array
        # elements, and Space.read of a bare Ptr. Wrapping HERE is what
        # makes value.deref(space) available everywhere from one seam.
        load = partial(_ptr_value_load, adapter=self, inner_load=inner_load)
        super().__init__(load, store, PtrValue, label)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "inner", inner)
        object.__setattr__(self, "module", module)

    @property
    def target(self):
        """The pointee's codec, resolving a deferred target on first use.

        A string or zero-argument callable is resolved once and then
        memoized, so a pointer can name a record that does not exist yet.
        Linked lists, tree nodes, and mutually-referencing tables all
        require that ordering.
        """
        target = self._target
        if target is None or _is_codec(target):
            return target
        resolved = self._resolve(target)
        if not _is_codec(resolved):
            raise TypeError(
                f"{self.name}: deferred target {target!r} resolved to"
                f" {resolved!r}, which is not a codec"
            )
        object.__setattr__(self, "_target", resolved)  # memoize
        return resolved

    def _resolve(self, target):
        if callable(target) and not isinstance(target, str):
            return target()
        namespace = getattr(sys.modules.get(self.module or ""), "__dict__", {})
        if target in namespace:
            return namespace[target]
        # Cross-module fallback. Every concrete Struct registers itself by
        # name, so a map split over several files can say Ptr("RoomHeader")
        # without importing the class into the declaring module. Only an
        # UNAMBIGUOUS match resolves, because two live records with the same
        # name pose a question only the author can answer with module=.
        candidates = _structs_named(target)
        # Prefer classes their own module still binds. That filters out
        # stale redefinitions left by a REPL or a reload, without guessing
        # between real duplicates.
        current = tuple(
            c
            for c in candidates
            if getattr(sys.modules.get(c.__module__ or ""), target, None) is c
        )
        pool = current or candidates
        if len(pool) == 1:
            return pool[0]
        if len(pool) > 1:
            mods = ", ".join(sorted(c.__module__ or "?" for c in pool))
            raise TypeError(
                f"{self.name}: deferred target {target!r} is ambiguous; a"
                f" concrete Struct by that name is alive in each of: {mods}."
                f" Pass Ptr(..., module=...) to pick one"
            )
        raise TypeError(
            f"{self.name}: cannot resolve the deferred target {target!r};"
            f" not in module {self.module!r}, and no concrete Struct class"
            f" by that name is alive anywhere. Deferred targets resolve"
            f" against the module the Ptr was built in, then against all"
            f" Struct classes by name; pass module= or a callable"
            f" (Ptr(lambda: {target})) to be explicit"
        )

    @property
    def deferred(self) -> bool:
        """True while the target is still an unresolved name/callable."""
        return not (self._target is None or _is_codec(self._target))

    def __reduce__(self):
        # Pickle the RAW target, so a deferred one stays deferred instead
        # of being resolved here. A deferred name is just a string, so it
        # pickles as it stands.
        return (PtrAdapter, (self._target, self.inner, self.name, self.module))


def _ptr_value_load(wire, adapter, inner_load):
    return PtrValue(inner_load(wire), adapter)


class PtrValue(int):
    """An integer pointer value that retains the adapter for its target.

    Every read through a :class:`Ptr` returns a ``PtrValue``, whether the
    pointer is a record field, an element of a pointer table, or a bare
    ``space.read``.

    A ``PtrValue`` behaves like an ordinary integer for equality, hashing,
    formatting, and truthiness. Two things are added. Its repr is
    hexadecimal, since addresses are read that way. It also stores the
    :class:`PtrAdapter` that ``deref`` and ``space.coverage`` consult.

    The value is not a proxy, and it reads nothing on its own. Calling
    ``deref(space)`` performs the actual read; creating a ``PtrValue`` does
    not. The ``Space`` remains an explicit argument because records are
    detached from their source buffer.

    Arithmetic returns a plain ``int`` rather than a ``PtrValue``, which is
    deliberate. ``ptr + 4`` is an offset address, so it no longer retains
    the adapter that said what ``ptr`` pointed at.

    For example::

        room = warp.room_ptr.deref(rom)
        while node.next:                     # PtrValue(0) is falsy, like 0
            node = node.next.deref(rom)
    """

    _adapter: PtrAdapter

    def __new__(cls, value, adapter):
        if not isinstance(adapter, PtrAdapter):
            raise TypeError(f"PtrValue needs the pointer's PtrAdapter, got {adapter!r}")
        self = super().__new__(cls, value)
        self._adapter = adapter
        return self

    @property
    def adapter(self) -> PtrAdapter:
        return self._adapter

    @property
    def target(self):
        """The pointee's codec, or None when the target is unmodelled.

        A deferred name or callable resolves on first access.
        """
        return self._adapter.target

    def deref(self, space: "Space", extent: Any = 1) -> Any:
        """Read what this address points at in ``space``, decoding it with
        the target the schema declared.
        """
        return space._deref_value(self, self._adapter, extent)

    def __repr__(self):
        return hex(self)

    def __reduce__(self):
        return (PtrValue, (int(self), self._adapter))


class Ptr(Adapted):
    """A typed address: a wire integer plus the record type it points at.

    The first argument, ``target``, is that record type.

    A ``Ptr`` is an :class:`~bytemaker.adapters.Adapted` codec, so it works
    everywhere a scalar wire type does: as an annotation, in ``field()``, as
    an array element, and in ``space.read``.

    Reads produce a :class:`PtrValue`, an ``int`` subclass that retains this
    adapter and therefore provides ``deref``. A pointer field is neither a
    proxy nor a lazy record. Nothing is read until ``deref`` is called, and
    the Space stays an explicit argument::

        class WarpPoint(Struct, endian="little"):
            sector: u8
            room_ptr: Annotated[int, Ptr(RoomHeader)]

        w = rom.read(0x08525FBC, WarpPoint)
        w.room_ptr                         # 0x08520B08 -- just an int
        rom.deref(w, "room_ptr")           # the RoomHeader it points at

    ``adapt=`` composes a value convention on top of the address. For
    instance ``Ptr(Anim, adapt=THUMB_PTR)`` is a function pointer whose bit 0
    selects the THUMB instruction set, so the decoded address is the real,
    even one.

    ``Ptr(None)`` declares an address whose pointee is not modelled yet.
    :meth:`Space.coverage` still audits such a pointer, while
    :meth:`Space.deref` raises and names it.

    **Deferred targets.** Pass the class itself whenever it is already bound
    at the declaration, since that is the normal form. A typo then fails at
    import time, an IDE can follow the reference, and nothing has to resolve
    at runtime.

    A *string* or a zero-argument callable covers the declarations that
    evaluation order forbids. Those are a self-referential node, mutually
    referencing records, and a cross-module cycle. Either form resolves on
    first deref::

        NextNode = Annotated[int, Ptr("Node")]   # resolved later, by name

        class Node(Struct, endian="little"):
            value: u16
            _pad:  u16
            next:  NextNode                      # points at its own type

        n = rom.read(addr, Node)
        while n.next:
            n = rom.deref(n, "next")             # walk the list

    A bare forward name cannot work, because ``Ptr(Node)`` inside ``Node``'s
    own body is evaluated before the class exists. That holds even under
    ``from __future__ import annotations``, since the metaclass resolves
    hints during class creation. The string defers resolution past that
    point.

    Resolution looks in two places, in order. It starts with the module the
    ``Ptr`` was built in. If the name is not bound there, it falls back to
    all live concrete Struct classes, and accepts a match only when exactly
    ONE class has that name. A map split across several files can therefore
    say ``Ptr("RoomHeader")`` without importing the class into the declaring
    module. Two live records with the same name raise instead, and the error
    lists their modules. Pass ``module=__name__``, or a callable, to be
    explicit when it matters.
    """

    __slots__ = ()

    def __init__(self, target=None, *, base=None, adapt=None, name=None, module=None):
        if base is None:
            from bytemaker.bittypes import UInt32

            base = UInt32
        if module is None and isinstance(target, str):
            # A deferred name resolves against the module this Ptr was built
            # in, which is the one the reader expects it to mean. Capture
            # it here rather than at resolution time, because by then the
            # frame is gone.
            frame = sys._getframe(1)
            module = frame.f_globals.get("__name__")
        super().__init__(base, PtrAdapter(target, adapt, name, module))

    @property
    def _ptr_adapter(self) -> PtrAdapter:
        """The adapter, narrowed to :class:`PtrAdapter` for the type checker.

        ``__init__`` and ``_rebuild_ptr`` are the only two Ptr constructors,
        and both install a ``PtrAdapter``. The cast therefore states an
        invariant rather than hiding a doubt.
        """
        return cast(PtrAdapter, self.adapter)

    @property
    def target(self):
        """The codec this address points at, or None when unmodelled.

        A deferred target, given as a name or a callable, resolves on
        first access.
        """
        return self._ptr_adapter.target

    @property
    def deferred(self) -> bool:
        """True while the target is still an unresolved name/callable."""
        return self._ptr_adapter.deferred

    def __repr__(self):
        # Use the RAW target throughout. A repr must never trigger
        # resolution, and it must not fail because a deferred name is not
        # importable yet.
        raw = self._ptr_adapter._target
        head = f"Ptr({_codec_name(raw)}->{self.base.__name__}"
        # Show a composed value convention. Two pointer tables that differ
        # only in whether bit 0 is an instruction-set selector must not read
        # identically in a map listing.
        if self.adapter.inner is not None or self.adapter.name != _default_ptr_name(
            raw
        ):
            head += f", {self.adapter.name}"
        return head + ")"

    def __reduce__(self):
        return (_rebuild_ptr, (self.base, self.adapter))


def _rebuild_ptr(base, adapter) -> Ptr:
    """Unpickle a Ptr without re-running ``__init__``, which would rebuild
    the adapter and lose its identity."""
    ptr = object.__new__(Ptr)
    object.__setattr__(ptr, "base", base)
    object.__setattr__(ptr, "adapter", adapter)
    return ptr


def _is_codec(obj) -> bool:
    """True for anything that can decode bytes at an address.

    The test is the presence of ``num_bits``, the same duck test
    :mod:`bytemaker.introspect` uses. It is what distinguishes a real codec
    from a deferred name or callable.
    """
    return isinstance(getattr(obj, "num_bits", None), int)


def _default_ptr_name(target) -> str:
    return f"ptr({_codec_name(target)})"


def _codec_name(codec) -> str:
    if codec is None:
        return "?"
    if isinstance(codec, str):
        return codec  # a deferred target names itself
    return getattr(codec, "__name__", None) or repr(codec)


def _checkable_target(adapter) -> Optional[StructMeta]:
    """The adapter's declared record type, when there is one to check.

    There is one when the adapter is a :class:`PtrAdapter` whose target
    either is a concrete Struct class or resolves to one. Anything else
    returns None.

    Resolution failure is NOT an audit failure. An unresolvable name only
    means the target is unverifiable, while the address classification
    stands on its own.
    """
    if not isinstance(adapter, PtrAdapter):
        return None
    try:
        target = adapter.target
    except TypeError:
        return None
    return target if isinstance(target, StructMeta) else None


def _ptr_adapter_of(obj) -> Optional[PtrAdapter]:
    """The :class:`PtrAdapter` behind a Ptr codec, an adapter, or an Array
    of pointers, or None when there is no PtrAdapter behind it."""
    if isinstance(obj, PtrAdapter):
        return obj
    if isinstance(obj, Adapted):
        return obj.adapter if isinstance(obj.adapter, PtrAdapter) else None
    if isinstance(obj, Array):
        return obj._adapter if isinstance(obj._adapter, PtrAdapter) else None
    return None
