"""The one thing the rest of the code knows about a language model.

Business logic depends on this small interface, never on a vendor's SDK.
Swapping the model, or the company behind it, means writing one class.
"""

from typing import Any, Protocol


class LLMError(Exception):
    """The model could not produce a usable answer. The message is safe to store and show."""


class LLMRefusedError(LLMError):
    """The model, or a safety classifier in front of it, declined the request."""


class LLMProvider(Protocol):
    """Something that answers a prompt with JSON matching a schema.

    A Protocol is satisfied by any class with these members; there is
    nothing to inherit from. (C#: an interface that classes implement
    without declaring that they do.)
    """

    name: str
    model: str

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the model's answer as parsed JSON, or raise LLMError."""
        ...
