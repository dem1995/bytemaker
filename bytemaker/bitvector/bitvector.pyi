# noqa: E301, E704, E701
"""
BitVector.pyi

This file contains specification documentation for the BitVector class.
That is, the BitVector class is guaranteed to meet the below behavior,
   with the exception of "extra" behavior (e.g., implementations of this
   class may extend another class or have additional methods).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, overload

try:
    from bytemaker.typing_redirect import (
        Buffer,
        Iterable,
        Iterator,
        Literal,
        MutableSequence,
        Optional,
        Protocol,
        Sequence,
        Tuple,
        TypeVar,
        Union,
        runtime_checkable,
    )
except ImportError:
    from typing_redirect import (  # type: ignore
        Buffer,
        Iterable,
        Iterator,
        Literal,
        MutableSequence,
        Optional,
        Protocol,
        Sequence,
        Tuple,
        TypeVar,
        Union,
        runtime_checkable,
    )

_LaxLiteral01 = Union[Literal[0, 1], int]
_LaxLiteral01Str = Union[Sequence[Literal["0", "1"]], str]

if TYPE_CHECKING:
    _Self = TypeVar("_Self", bound="BitVector")
else:
    try:
        from typing_redirect import Self as _Self
    except ImportError:
        _Self = TypeVar("Self", bound="BitVector")
_T = TypeVar("_T")

@runtime_checkable
class BitsCastable(Protocol):
    def __Bits__(self) -> BitVector: ...

BitsConstructible = Union[
    "BitVector", bytes, str, Iterable[_LaxLiteral01], BitsCastable
]

class BitVector(MutableSequence[Literal[0, 1]], BitsCastable):
    def __new__(
        cls,
        source: Optional[Union[BitsConstructible, int]] = None,
        buffer: Optional[Buffer] = None,
        *args,
        **kwargs,
    ): ...
    def __init__(
        self,
        source: Optional[Union[BitsConstructible, int]] = None,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        buffer: Optional[Buffer] = None,
    ) -> None: ...

    # Conversions
    @classmethod
    def frombin(cls: type[_Self], string: str) -> _Self: ...
    @classmethod
    def fromhex(cls: type[_Self], string: str) -> _Self: ...
    @classmethod
    def fromoct(cls: type[_Self], string: str) -> _Self: ...
    @classmethod
    def fromsize(
        cls: type[_Self],
        size: int,
        /,  # We do not know what the name
        # in PEP 467 will be
    ) -> _Self: ...
    @classmethod
    def from01(
        cls: type[_Self],
        string: _LaxLiteral01Str,
    ) -> _Self: ...
    @classmethod
    def frombase(
        cls: type[_Self],
        string: str,
        base: int,
    ) -> _Self: ...
    # @classmethod  # TODO
    # def from_int(cls, value: int, length: int, signed: bool = True) -> Self: ...
    # This is complicated by PEP 467, which is slightly different functionality
    # @classmethod
    # def from_bytes(
    #     cls: type[Self], bytes: bytes,
    #     endianness: Literal["little", "big"] = "big") -> Self: ...
    @classmethod
    def from_chararray(
        cls: type[_Self],
        char_array: str,
        encoding: Union[str, dict[str, BitsConstructible]] = "utf-8",
    ) -> _Self: ...
    def bin(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str: ...
    def hex(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str: ...
    def oct(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str: ...
    def to01(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str: ...
    def tobase(
        self, base: int, sep: Optional[str] = None, bytes_per_sep: int = 1
    ) -> str: ...
    # def to_int(self, signed: bool = True) -> int: ...  # TODO
    def to_chararray(
        self, encoding: Union[str, dict[BitsConstructible, str]] = "utf-8"
    ) -> str: ...

    # Magic Methods and Overloads
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __lt__(self: _Self, other: _Self) -> bool: ...
    def __le__(self: _Self, other: _Self) -> bool: ...
    def __gt__(self: _Self, other: _Self) -> bool: ...
    def __ge__(self: _Self, other: _Self) -> bool: ...
    def __add__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __radd__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __iadd__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __mul__(self: _Self, count: int) -> _Self: ...
    def __imul__(self: _Self, count: int) -> _Self: ...
    def __rmul__(self: _Self, count: int) -> _Self: ...
    def __and__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __rand__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __iand__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __or__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __ror__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __ior__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __xor__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __rxor__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __ixor__(self: _Self, other: BitsConstructible) -> _Self: ...
    def __lshift__(self: _Self, count: int) -> _Self: ...
    def __ilshift__(self: _Self, count: int) -> _Self: ...
    def __rshift__(self: _Self, count: int) -> _Self: ...
    def __irshift__(self: _Self, count: int) -> _Self: ...
    def __invert__(self: _Self) -> _Self: ...
    # def __neg__(self: Self) -> Self: ...
    def __iter__(self) -> Iterator[Literal[0, 1]]: ...
    def __format__(self, format_spec: str) -> str: ...
    @overload
    def __contains__(self, item: Union[BitsConstructible, Literal[0, 1]]) -> bool: ...
    @overload
    def __contains__(self, item: object) -> bool: ...
    @overload
    def __getitem__(self, key: int) -> Literal[0, 1]: ...
    @overload
    def __getitem__(self: _Self, key: Union[slice, Iterable[int]]) -> _Self: ...
    @overload
    def __setitem__(self, key: int, value: Literal[0, 1]) -> None: ...
    @overload
    def __setitem__(
        self,
        key: Union[slice, Iterable[int]],
        value: Union[BitsConstructible, Literal[0, 1]],
    ) -> None: ...
    def __delitem__(self, key: Union[int, slice, Iterable[int]]) -> None: ...
    def __len__(self) -> int: ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...
    def __bytes__(self) -> bytes: ...
    # def __Bits__(self: Self, endianness: str = "big") -> Self: ...
    #     preserve=True default arg
    def __copy__(self: _Self) -> _Self: ...
    def __deepcopy__(self: _Self, memo: dict[int, object]) -> _Self: ...
    #     constructor deepcopy default
    # def __reduce__(self
    #   ) -> Tuple[Type[Self], Tuple[Union[bytes, str], str, str, str]]: ... # TODO
    # def __reduce_ex__(self, protocol: int
    #   ) -> Tuple[Type[Self], Tuple[Union[bytes, str], str, str, str]]: ... # TODO
    # def __getnewargs_ex__(self) -> Tuple[Union[bytes, str], str, str, str]: ... # TODO
    # def __getnewargs__(self) -> Tuple[Union[bytes, str], str, str, str]: ... # TODO
    # def __getstate__(self) -> Tuple[Union[bytes, str], str, str, str]: ... # TODO
    # def __setstate__(self, state: Tuple[Union[bytes, str], str, str, str]
    #   ) -> None: ... # TODO
    def __sizeof__(self) -> int: ...

    # Basic Operations
    def append(self, value: _LaxLiteral01) -> None: ...
    def extend(self, values: BitsConstructible) -> None: ...
    def insert(self, index: int, value: int) -> None: ...
    @overload
    def pop(
        self, index: Optional[int] = None, default: None = None
    ) -> Literal[0, 1]: ...
    @overload
    def pop(
        self, index: Optional[int] = None, default: _T = ...
    ) -> Union[Literal[0, 1], _T]: ...
    def remove(self, value: int) -> None: ...
    def clear(self) -> None: ...
    def copy(self: _Self) -> _Self: ...
    def reverse(self) -> None: ...
    # def swap_endianness(self) -> None: ...

    # Search and Analysis
    def count(
        self,
        value: Union[BitsConstructible, int],
        start: int = 0,
        end: Optional[int] = None,
    ) -> int: ...
    def endswith(
        self, substrings: bytes, start: int = 0, stop: Optional[int] = None
    ) -> bool: ...
    def startswith(
        self, substrings: bytes, start: int = 0, stop: Optional[int] = None
    ) -> bool: ...
    def find(
        self,
        value: Union[BitsConstructible, Literal[0, 1]],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int: ...
    def rfind(
        self,
        value: Union[BitsConstructible, Literal[0, 1]],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int: ...
    def index(
        self,
        value: Union[BitsConstructible, Literal[0, 1]],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int: ...
    def rindex(
        self,
        value: Union[BitsConstructible, Literal[0, 1]],
        start: int = 0,
        stop: Optional[int] = None,
    ) -> int: ...

    # Modification and Translation
    def replace(
        self: _Self,
        old: BitsConstructible,
        new: BitsConstructible,
        count: Optional[int] = None,
    ) -> _Self: ...
    # def translate(self,
    #   table: List[BitVector] | bytes, delete: Optional[List[BitVector]] = None
    #   ) -> Self: ... # TODO
    # def maketrans(self, x, y=None, z=None) -> list[BitVector]: ...  # TODO
    def join(self: _Self, iterable: Iterable[BitsConstructible]) -> _Self: ...
    # def split(self, sep: Optional[bytes] = None, maxsplit: int = -1
    #   ) -> List[bytes]: ... # TODO
    # def rsplit(
    #     self, sep: Optional[bytes] = None, maxsplit: int = -1
    # ) -> List[bytes]: ... #TODO
    def partition(self, sep: BitVector) -> Tuple[_Self, _Self, _Self]: ...
    def rpartition(self, sep: BitVector) -> Tuple[_Self, _Self, _Self]: ...
    def lstrip(self: _Self, bits: Optional[_LaxLiteral01] = None) -> _Self: ...
    def rstrip(self: _Self, bits: Optional[_LaxLiteral01] = None) -> _Self: ...
    def strip(self: _Self, bits: Optional[_LaxLiteral01] = None) -> _Self: ...

    # Text and Alignment Methods # TODO
    # def decode(self, encoding: str = "utf-8", errors: str = "strict") -> str: ...
    # def expandtabs(self, tabsize: int = 8) -> Self: ...
    def lpad(self: _Self, width: int, fillbit: Literal[0, 1] = 0) -> _Self: ...
    def rpad(self: _Self, width: int, fillbit: Literal[0, 1] = 0) -> _Self: ...
    # def center(self, width: int, fillbyte: bytes = b" ") -> Self: ...
    # def zfill(self, width: int) -> Self: ...
    # def capitalize(self) -> Self: ...
    # def lower(self) -> Self: ...
    # def swapcase(self) -> Self: ...
    # def title(self) -> Self: ...
    # def upper(self) -> Self: ...
    # def isalnum(self) -> bool: ...
    # def isalpha(self) -> bool: ...
    # def isdigit(self) -> bool: ...
    # def islower(self) -> bool: ...
    # def isspace(self) -> bool: ...s
    # def istitle(self) -> bool: ...
    # def isupper(self) -> bool: ...

    @classmethod
    def cast_if_not_bitvector(  # this should be shallow
        cls: type[_Self], obj: BitsConstructible
    ) -> Union[_Self, BitVector]: ...

    # TODO remove these methods
    @classmethod
    def from_int(cls, integer: int, size: Optional[int] = None): ...
    @classmethod
    def from_bytes(cls, byte_arr: bytes, reverse_endianness: bool = False): ...
    def to_bytes(self, reverse_endianness: bool = False) -> bytes: ...
    def to_int(
        self, endianness: Literal["big", "little"] = "big", signed=True
    ) -> int: ...

# class FrozenBitVector(frozenbitarray): # TODO
#     def __hash__(self) -> int: ...
