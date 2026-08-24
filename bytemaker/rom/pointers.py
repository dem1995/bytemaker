"""Typed addresses: :class:`Ptr`, :class:`PtrValue`, :class:`PtrAdapter`.

A pointer field decodes to a :class:`PtrValue` — an ``int`` that knows what
it points at, so it can ``.deref(space)`` itself and a coverage audit can
check where it lands. Nothing is lazy: dereferencing is always an explicit
call, and records stay detached values.
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
    """The :class:`Adapter` half of a :class:`Ptr`: it carries the pointee's
    codec so a record can be dereferenced without a lookup table.

    Living on the adapter (rather than on the wire type) is what makes this
    work: :class:`Adapted` codecs are split into base + adapter at class
    definition time, so the adapter is the half that survives into
    ``_bm_adapters`` and :func:`~bytemaker.introspect.fields_of`.
    """

    __slots__ = ("_target", "inner", "module")

    #: The target as GIVEN: a codec, a name/callable awaiting resolution, or
    #: None. Read it through :attr:`target`, which resolves and memoizes.
    _target: Any
    inner: Optional[Adapter]
    module: Optional[str]

    def __init__(self, target=None, inner=None, name=None, module=None):
        if inner is not None and not isinstance(inner, Adapter):
            raise TypeError(f"Ptr adapt= must be an Adapter, got {inner!r}")
        if not (target is None or _is_codec(target) or isinstance(target, str)
                or callable(target)):
            raise TypeError(
                f"Ptr target must be a codec (Struct class, BitType class,"
                f" Array, fused adapter@BitType), a name to resolve later, a"
                f" zero-argument callable returning one, or None — got"
                f" {target!r}"
            )
        inner_load = inner.load if inner is not None else _identity
        store = inner.store if inner is not None else _identity
        label = name or _default_ptr_name(target)
        # Every read path — record fields, array elements, Space.read of a
        # bare Ptr — goes through this load, so wrapping HERE is what makes
        # value.deref(space) available everywhere with one seam.
        load = partial(_ptr_value_load, adapter=self, inner_load=inner_load)
        super().__init__(load, store, PtrValue, label)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "inner", inner)
        object.__setattr__(self, "module", module)

    @property
    def target(self):
        """The pointee's codec, resolving a deferred target on first use.

        A string or zero-argument callable is resolved once and memoized, so
        a pointer can name a record that does not exist yet — the shape a
        linked list, a tree node, or any pair of mutually-referencing tables
        forces.
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
        # Cross-module fallback: every concrete Struct registers itself by
        # name, so a map split over several files can say Ptr("RoomHeader")
        # without importing the class into the declaring module. Only an
        # UNAMBIGUOUS match resolves — two live same-named records is a
        # question only the author can answer (module=).
        candidates = _structs_named(target)
        # Prefer classes their own module still binds: filters out stale
        # redefinitions (REPL / reload) without guessing between real
        # duplicates.
        current = tuple(
            c for c in candidates
            if getattr(sys.modules.get(c.__module__ or ""), target, None) is c
        )
        pool = current or candidates
        if len(pool) == 1:
            return pool[0]
        if len(pool) > 1:
            mods = ", ".join(sorted(c.__module__ or "?" for c in pool))
            raise TypeError(
                f"{self.name}: deferred target {target!r} is ambiguous — a"
                f" concrete Struct by that name is alive in each of: {mods}."
                f" Pass Ptr(..., module=...) to pick one"
            )
        raise TypeError(
            f"{self.name}: cannot resolve the deferred target {target!r} —"
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
        # Pickle the RAW target: a deferred one stays deferred (and picklable,
        # since it is just a string) instead of forcing resolution here.
        return (PtrAdapter, (self._target, self.inner, self.name, self.module))


def _ptr_value_load(wire, adapter, inner_load):
    return PtrValue(inner_load(wire), adapter)


class PtrValue(int):
    """A decoded pointer: an ``int`` that knows what it points at.

    Every read through a :class:`Ptr` mints one, so the address a record
    field (or a pointer-table element) hands you can follow itself::

        room = warp.room_ptr.deref(rom)
        while node.next:                     # PtrValue(0) is falsy, like 0
            node = node.next.deref(rom)

    It behaves exactly like the address it is — equality, hashing,
    formatting, truthiness all match ``int`` — with two additions: it reprs
    in hex (this is a ROM library), and it carries the :class:`PtrAdapter`
    that ``deref``/``space.coverage`` consult. Still no proxy and no
    laziness: nothing is read until ``deref`` is called, and the Space stays
    an explicit argument because records are detached from their buffer.

    Arithmetic collapses to a plain ``int`` on purpose: ``ptr + 4`` is an
    offset address, and no longer carries the original claim about what
    lives there.
    """

    _adapter: PtrAdapter

    def __new__(cls, value, adapter):
        if not isinstance(adapter, PtrAdapter):
            raise TypeError(
                f"PtrValue needs the pointer's PtrAdapter, got {adapter!r}"
            )
        self = super().__new__(cls, value)
        self._adapter = adapter
        return self

    @property
    def adapter(self) -> PtrAdapter:
        return self._adapter

    @property
    def target(self):
        """The pointee's codec (resolving a deferred name), or None."""
        return self._adapter.target

    def deref(self, space: "Space", extent: Any = 1) -> Any:
        """Follow this address in ``space`` — sugar for
        ``space.deref_value(self, ...)``, with the target from the schema."""
        return space.deref_value(self, self._adapter, extent)

    def __repr__(self):
        return hex(self)

    def __reduce__(self):
        return (PtrValue, (int(self), self._adapter))


class Ptr(Adapted):
    """A typed address: a wire integer that points at ``target``.

    The decoded value is a :class:`PtrValue` — an ``int`` subclass that
    carries its adapter, so it can follow itself. Still no proxy and not a
    lazy record: nothing is read until you ask, and the Space stays an
    explicit argument::

        class WarpPoint(Struct, endian="little"):
            sector: UInt8
            room_ptr: Annotated[int, Ptr(RoomHeader)]

        w = rom.read(0x08525FBC, WarpPoint)
        w.room_ptr                         # 0x08520B08 -- just an int
        rom.deref(w, "room_ptr")           # the RoomHeader it points at

    A pointer is an :class:`~bytemaker.adapters.Adapted` codec, so it works
    everywhere a scalar wire type does (annotation, ``field()``, array
    element, ``space.read``) with no extra plumbing.

    ``adapt=`` composes a value convention on top — ``Ptr(Anim,
    adapt=THUMB_PTR)`` is a function pointer whose bit 0 selects the THUMB
    instruction set, so the decoded address is the real (even) one.

    ``Ptr(None)`` means "this is an address, but the pointee is not modelled
    yet": :meth:`Space.coverage` still audits it, and :meth:`Space.deref`
    refuses it by name.

    **Deferred targets.** Pass the class itself whenever it is bound at the
    declaration — that is the normal form: a typo fails at import time, the
    IDE can follow it, and nothing resolves at runtime. A *string* (or a
    zero-argument callable) exists for the declarations evaluation order
    forbids — a self-referential node, mutually-referencing records, a
    cross-module cycle — and is resolved on first deref::

        NextNode = Annotated[int, Ptr("Node")]   # resolved later, by name

        class Node(Struct, endian="little"):
            value: u16
            _pad:  u16
            next:  NextNode                      # points at its own type

        n = rom.read(addr, Node)
        while n.next:
            n = rom.deref(n, "next")             # walk the list

    A bare forward name cannot work — ``Ptr(Node)`` inside ``Node``'s own body
    is evaluated before the class exists, even under
    ``from __future__ import annotations``, because the metaclass resolves
    hints during class creation. The string defers past that point.

    Resolution looks in two places, in order: the module the ``Ptr`` was
    built in, then — if the name is not bound there — the set of all live
    concrete Struct classes, when exactly ONE bears that name. So a map
    split across several files can say ``Ptr("RoomHeader")`` without
    importing the class into the declaring module; two live records with
    the same name refuse with the modules listed. Use ``module=__name__``
    (or a callable) to be explicit when it matters.
    """

    __slots__ = ()

    def __init__(self, target=None, *, base=None, adapt=None, name=None,
                 module=None):
        if base is None:
            from bytemaker.bittypes import UInt32

            base = UInt32
        if module is None and isinstance(target, str):
            # A deferred name resolves against the module this Ptr was built
            # in, which is the one the reader expects it to mean. Captured
            # here (not at resolution time) because by then the frame is gone.
            frame = sys._getframe(1)
            module = frame.f_globals.get("__name__")
        super().__init__(base, PtrAdapter(target, adapt, name, module))

    @property
    def _ptr_adapter(self) -> PtrAdapter:
        """The adapter, narrowed. Every Ptr constructor installs a PtrAdapter
        (``__init__`` and ``_rebuild_ptr`` are the only two), so this states
        an invariant for the checker rather than hiding a doubt."""
        return cast(PtrAdapter, self.adapter)

    @property
    def target(self):
        """The codec this address points at, or None when unmodelled.

        Resolves a deferred target (a name or callable) on first access.
        """
        return self._ptr_adapter.target

    @property
    def deferred(self) -> bool:
        """True while the target is still an unresolved name/callable."""
        return self._ptr_adapter.deferred

    def __repr__(self):
        # The RAW target throughout: a repr must never trigger resolution, nor
        # fail because a deferred name is not importable yet.
        raw = self._ptr_adapter._target
        head = f"Ptr({_codec_name(raw)}->{self.base.__name__}"
        # Show a composed value convention: two pointer tables that differ
        # only in whether bit 0 is an instruction-set selector must not read
        # identically in a map listing.
        if (
            self.adapter.inner is not None
            or self.adapter.name != _default_ptr_name(raw)
        ):
            head += f", {self.adapter.name}"
        return head + ")"

    def __reduce__(self):
        return (_rebuild_ptr, (self.base, self.adapter))


def _rebuild_ptr(base, adapter) -> Ptr:
    """Unpickle a Ptr without re-running __init__ (which would rebuild the
    adapter and lose its identity)."""
    ptr = object.__new__(Ptr)
    object.__setattr__(ptr, "base", base)
    object.__setattr__(ptr, "adapter", adapter)
    return ptr


def _is_codec(obj) -> bool:
    """True for anything that can decode bytes at an address. The duck test
    (``num_bits``) is the same one :mod:`bytemaker.introspect` uses, and it
    is what distinguishes a real codec from a deferred name or callable."""
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
    """The adapter's declared record type, when there is one to check: a
    PtrAdapter whose target is (or resolves to) a concrete Struct class.
    Resolution failure is NOT an audit failure — an unresolvable name just
    means unverifiable, and the address classification stands on its own."""
    if not isinstance(adapter, PtrAdapter):
        return None
    try:
        target = adapter.target
    except TypeError:
        return None
    return target if isinstance(target, StructMeta) else None


def _ptr_adapter_of(obj) -> Optional[PtrAdapter]:
    """The :class:`PtrAdapter` behind a Ptr codec, an adapter, or an Array of
    pointers — else None."""
    if isinstance(obj, PtrAdapter):
        return obj
    if isinstance(obj, Adapted):
        return obj.adapter if isinstance(obj.adapter, PtrAdapter) else None
    if isinstance(obj, Array):
        return obj._adapter if isinstance(obj._adapter, PtrAdapter) else None
    return None
