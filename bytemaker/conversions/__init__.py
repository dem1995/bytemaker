"""Public conversion API: the aggregate serializers plus the ctypes/pytype
helpers, re-exported so ``from bytemaker.conversions import to_bytes_aggregate``
works (mirroring the bittypes/ and bitvector/ subpackages).

The re-export is lazy (PEP 562 module ``__getattr__``) as a deliberate
lightweight-init choice: sibling modules (``_legacy_aggregate``,
``aggregate_types``) import each other through this package, and lazy
resolution keeps the convenient names without loading the whole conversion
stack at package-init time or caring about which sibling imports first.
(Historically this laziness was load-bearing — ``_legacy_aggregate`` lived
at the package root and eager re-export here closed a real import cycle;
since its move into conversions/ the laziness is a preference, not a fix.)
"""

import importlib

_EXPORTS = {
    # conversions.aggregate_types
    "from_bits_aggregate": "bytemaker.conversions.aggregate_types",
    "from_bits_individual": "bytemaker.conversions.aggregate_types",
    "from_bytes_aggregate": "bytemaker.conversions.aggregate_types",
    "from_bytes_individual": "bytemaker.conversions.aggregate_types",
    "to_bits_aggregate": "bytemaker.conversions.aggregate_types",
    "to_bits_individual": "bytemaker.conversions.aggregate_types",
    "to_bytes_aggregate": "bytemaker.conversions.aggregate_types",
    "to_bytes_individual": "bytemaker.conversions.aggregate_types",
    # conversions.ctypes_
    "ctype_to_bytes": "bytemaker.conversions.ctypes_",
    "bytes_to_ctype": "bytemaker.conversions.ctypes_",
    "ctype_to_bits": "bytemaker.conversions.ctypes_",
    "bits_to_ctype": "bytemaker.conversions.ctypes_",
    # conversions.pytypes
    "pytype_to_bits": "bytemaker.conversions.pytypes",
    "bits_to_pytype": "bytemaker.conversions.pytypes",
    "pytype_to_bytes": "bytemaker.conversions.pytypes",
    "bytes_to_pytype": "bytemaker.conversions.pytypes",
    "ConversionConfig": "bytemaker.conversions.pytypes",
    "ConversionInfo": "bytemaker.conversions.pytypes",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value  # cache so subsequent lookups skip __getattr__
    return value


def __dir__():
    return sorted(__all__)
