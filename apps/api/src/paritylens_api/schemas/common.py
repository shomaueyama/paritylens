"""Shared pieces of the request and response models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class ApiModel(BaseModel):
    """Base for response models: can be built straight from an ORM row."""

    model_config = ConfigDict(from_attributes=True)


def reject_unstorable(value: Any, depth: int = 0) -> None:
    """Raise if a value holds something PostgreSQL cannot store.

    A NUL character cannot go into a text or JSON column, and a number
    that is not finite is not JSON. Left unchecked, either one surfaces
    as a database error, which the client sees as a 500.
    """
    if depth > 200:
        raise ValueError("the request is nested too deeply")
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("text must not contain NUL characters")
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("numbers must be finite")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_unstorable(key, depth + 1)
            reject_unstorable(item, depth + 1)
    elif isinstance(value, list | tuple):
        for item in value:
            reject_unstorable(item, depth + 1)


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are an error, not ignored.

    hide_input_in_errors keeps a rejected value (which may be a credential)
    out of the error response.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def _storable(cls, data: Any) -> Any:
        reject_unstorable(data)
        return data
