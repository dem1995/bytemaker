"""Public conversion API: the aggregate serializers plus the ctypes/pytype
helpers, re-exported so ``from bytemaker.conversions import to_bytes_aggregate``
works (mirroring the bittypes/ and bitvector/ subpackages).

The re-export is lazy (PEP 562 module ``__getattr__``): eagerly importing
``aggregate_types`` here would close an import cycle, because
``_legacy_aggregate`` imports ``conversions.ctypes_`` (running this package
init) while ``aggregate_types`` imports back from ``_legacy_aggregate``. So
``from bytemaker import _legacy_aggregate`` as a first import — and running the
parity test files in isolation — would fail at collection. Lazy resolution
keeps the convenient names without loading those modules at package-init time.
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
