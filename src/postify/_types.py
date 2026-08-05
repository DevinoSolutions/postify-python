"""The ``NOT_GIVEN`` sentinel.

PATCH semantics need three states, not two: *set to a value*, *explicitly set to
``null``*, and *not mentioned at all*. ``None`` already means the second, so
optional parameters default to ``NOT_GIVEN`` and request bodies simply omit every
argument still holding it.
"""

from __future__ import annotations

from typing import Any, Optional, TypeVar, Union

__all__ = ["NOT_GIVEN", "NotGiven", "NotGivenOr", "given"]


class NotGiven:
    """Sentinel type for "the caller did not mention this field"."""

    _instance: Optional[NotGiven] = None

    def __new__(cls) -> NotGiven:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()

_T = TypeVar("_T")
NotGivenOr = Union[_T, NotGiven]


def given(value: Any) -> bool:
    """True when ``value`` is anything other than the :data:`NOT_GIVEN` sentinel."""
    return not isinstance(value, NotGiven)
