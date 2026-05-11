"""Complex types, annotations, validators."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Literal,
    NewType,
    TypeVar,
)

from pydantic import AfterValidator

# simple types
StrOrPath = str | Path
AnyByStrDict = dict[str, Any]
AnyByStrMutableMapping = MutableMapping[str, Any]

# sequences
IntSeq = Sequence[int]
PathSeq = Sequence[Path]

# optional types
OptBool = bool | None
OptStrOrPath = StrOrPath | None

# miscellaneous
T = TypeVar("T")
JSONSerializable = (dict, list, str, int, float, bool, type(None))
VCSTypes = Literal["git"]
Env = Mapping[str, str]
MissingType = NewType("MissingType", object)
MISSING = MissingType(object())
Operation = Literal["copy", "update"]


# Validators
def path_is_absolute(value: Path) -> Path:
    """Require absolute paths in an argument."""
    if not value.is_absolute():
        from .errors import PathNotAbsoluteError

        raise PathNotAbsoluteError(path=value)
    return value


def path_is_relative(value: Path) -> Path:
    """Require relative paths in an argument."""
    if value.is_absolute():
        from .errors import PathNotRelativeError

        raise PathNotRelativeError(path=value)
    return value


AbsolutePath = Annotated[Path, AfterValidator(path_is_absolute)]
RelativePath = Annotated[Path, AfterValidator(path_is_relative)]


_K = TypeVar("_K")
_V = TypeVar("_V")


# HACK https://github.com/copier-org/copier/pull/1880#discussion_r1887491497
class LazyDict(MutableMapping[_K, _V]):
    """A dict where values are functions that get evaluated only once when requested."""

    def __init__(self, mapping: Mapping[_K, Callable[[], _V]] | None = None):
        self._pending = dict(mapping or {})
        self._done: dict[_K, _V] = {}

    def __getitem__(self, key: _K) -> _V:
        if key not in self._done:
            self._done[key] = self._pending[key]()
        return self._done[key]

    def __setitem__(self, key: _K, value: _V) -> None:
        self._pending[key] = lambda: value
        self._done.pop(key, None)

    def __delitem__(self, key: _K) -> None:
        del self._pending[key]
        del self._done[key]

    def __iter__(self) -> Iterator[_K]:
        return iter(self._pending)

    def __len__(self) -> int:
        return len(self._pending)


class Phase(str, Enum):
    """The known execution phases."""

    PROMPT = "prompt"
    TASKS = "tasks"
    MIGRATE = "migrate"
    RENDER = "render"
    UNDEFINED = "undefined"

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    @contextmanager
    def use(cls, phase: Phase) -> Iterator[None]:
        """Set the current phase for the duration of a context."""
        token = _phase.set(phase)
        try:
            yield
        finally:
            _phase.reset(token)

    @classmethod
    def current(cls) -> Phase:
        """Get the current phase."""
        return _phase.get()


_phase: ContextVar[Phase] = ContextVar("phase", default=Phase.UNDEFINED)


class VcsRef(Enum):
    CURRENT = ":current:"
    """A special value to indicate that the current ref of the existing
    template should be used.
    """


ValidatorFn = Callable[[Any, str], str]
"""Validator function type: takes (value, question_name) and returns error message or empty string."""


_question_validators: dict[str, ValidatorFn] = {}


def register_validator(name: str, validator: ValidatorFn) -> None:
    """Register a custom question validator.
    
    Args:
        name: Name of the validator, used to reference it in question configs.
        validator: The validator function.
    """
    _question_validators[name] = validator


def get_validator(name: str) -> ValidatorFn | None:
    """Get a registered validator by name.
    
    Args:
        name: Name of the validator.
        
    Returns:
        The validator function, or None if not registered.
    """
    return _question_validators.get(name)


def get_all_validators() -> dict[str, ValidatorFn]:
    """Get all registered validators.
    
    Returns:
        A copy of the validators dictionary.
    """
    return dict(_question_validators)


def clear_validators() -> None:
    """Clear all registered validators. Useful for testing."""
    _question_validators.clear()
