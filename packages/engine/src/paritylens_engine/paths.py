"""Paths into a JSON document, and the patterns that rules match them with.

A path names one place in one document: $.items[0].price
A pattern names a set of places:         $.items[*].price, $..price

The syntax is a small subset of JSONPath. It is implemented here instead of
pulled in from a library because the engine needs two things libraries do
not offer together: rendering a concrete path back to text (so a difference
shown on screen can be pasted into a rule), and matching without evaluating
the pattern against a document.
"""

import re
from dataclasses import dataclass
from functools import cache
from typing import Any

from paritylens_engine.jsonvalue import label

__all__ = [
    "KeyMatch",
    "Path",
    "PathSyntaxError",
    "Pattern",
    "generalize",
    "last_field_name",
    "parse_pattern",
    "render",
]


@dataclass(frozen=True)
class KeyMatch:
    """An array element identified by one of its fields instead of its position.

    Used for arrays compared as unordered with a key, where the same element
    sits at different indexes on the two sides. Rendered as [sku=A-100].
    """

    key: str
    value: str


type Segment = str | int | KeyMatch
type Path = tuple[Segment, ...]


@dataclass(frozen=True)
class _Key:
    name: str


@dataclass(frozen=True)
class _Index:
    index: int


@dataclass(frozen=True)
class _AnyElement:
    """[*]: any element of an array, whether addressed by index or by key."""


@dataclass(frozen=True)
class _AnyKey:
    """.*: any field of an object."""


@dataclass(frozen=True)
class _Descendant:
    """..name: a field called name at any depth below this point."""

    name: str


type _PatternSegment = _Key | _Index | _AnyElement | _AnyKey | _Descendant | KeyMatch


class PathSyntaxError(ValueError):
    """A rule's path pattern could not be parsed."""


# Names made only of these characters can be written as .name; anything
# else needs the quoted form ['name'].
_PLAIN_NAME = re.compile(r"[^\s.\[\]'*=]+")


def render(path: Path) -> str:
    """Write a path as text. parse_pattern(render(p)) matches exactly p."""
    parts = ["$"]
    for segment in path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        elif isinstance(segment, KeyMatch):
            if _PLAIN_NAME.fullmatch(segment.key) and _PLAIN_NAME.fullmatch(segment.value):
                parts.append(f"[{segment.key}={segment.value}]")
            else:
                parts.append(f"['{_escape(segment.key)}'='{_escape(segment.value)}']")
        elif _PLAIN_NAME.fullmatch(segment):
            parts.append(f".{segment}")
        else:
            parts.append(f"['{_escape(segment)}']")
    return "".join(parts)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text, flags=re.DOTALL)


def generalize(path: Path) -> str:
    """Render a path with every array position replaced by [*].

    Two differences at $.items[0].id and $.items[3].id are the same kind of
    difference; this gives them the same name.
    """
    parts = ["$"]
    for segment in path:
        if isinstance(segment, int | KeyMatch):
            parts.append("[*]")
        else:
            parts.append(render((segment,))[1:])
    return "".join(parts)


def last_field_name(path: Path) -> str | None:
    """The innermost object field a path goes through, skipping array positions."""
    for segment in reversed(path):
        if isinstance(segment, str):
            return segment
    return None


@dataclass(frozen=True)
class Pattern:
    """A parsed rule pattern."""

    source: str
    segments: tuple[_PatternSegment, ...]

    def matches(self, path: Path) -> bool:
        """True when the pattern names exactly this path."""
        return _match(self.segments, path)

    @property
    def is_concrete(self) -> bool:
        """True when the pattern names one place, with no wildcards."""
        return all(isinstance(segment, _Key | _Index | KeyMatch) for segment in self.segments)

    def find(self, document: Any) -> tuple[bool, Any]:
        """Look up the one place a concrete pattern names.

        Returns (found, value). The flag is separate because null is a
        value a document can hold.
        """
        current = document
        for segment in self.segments:
            match segment:
                case _Key(name) if isinstance(current, dict) and name in current:
                    current = current[name]
                case _Index(index) if isinstance(current, list) and index < len(current):
                    current = current[index]
                case KeyMatch(key, value) if isinstance(current, list):
                    for item in current:
                        if isinstance(item, dict) and _names(item.get(key), value):
                            current = item
                            break
                    else:
                        return False, None
                case _:
                    return False, None
        return True, current

    def covers(self, path: Path) -> bool:
        """True when the pattern names this path or anything it is inside of.

        Ignoring $.meta has to ignore $.meta.trace_id as well.
        """
        return any(self.matches(path[:length]) for length in range(len(path) + 1))


def _names(candidate: Any, wanted: str) -> bool:
    """Whether a field's value is the one a [key=value] segment asks for."""
    if candidate is None or isinstance(candidate, list | dict):
        return False
    return label(candidate) == wanted


def _segment_matches(pattern: _PatternSegment, segment: Segment) -> bool:
    match pattern:
        case _Key(name):
            return isinstance(segment, str) and segment == name
        case _Index(index):
            return isinstance(segment, int) and segment == index
        case _AnyElement():
            return isinstance(segment, int | KeyMatch)
        case _AnyKey():
            return isinstance(segment, str)
        case KeyMatch():
            return segment == pattern
        case _Descendant():
            raise AssertionError("descendant segments are handled by _match")


def _match(pattern: tuple[_PatternSegment, ...], path: Path) -> bool:
    # Each (i, j) pair is answered once. Without the cache a pattern with
    # several ".." segments retries the same suffixes over and over, and
    # the time doubles with every segment.
    @cache
    def from_(i: int, j: int) -> bool:
        if i == len(pattern):
            return j == len(path)
        head = pattern[i]
        if isinstance(head, _Descendant):
            # Skip any number of segments, then require a field with this name.
            return any(
                isinstance(path[k], str) and path[k] == head.name and from_(i + 1, k + 1)
                for k in range(j, len(path))
            )
        if j == len(path):
            return False
        return _segment_matches(head, path[j]) and from_(i + 1, j + 1)

    return from_(0, 0)


_QUOTED_TEXT = r"((?:[^'\\]|\\.)*)"
_QUOTED = re.compile(rf"\['{_QUOTED_TEXT}'\]", re.DOTALL)
_QUOTED_KEY_MATCH = re.compile(rf"\['{_QUOTED_TEXT}'='{_QUOTED_TEXT}'\]", re.DOTALL)
_BRACKET = re.compile(r"\[([^\]]*)\]")


def parse_pattern(source: str) -> Pattern:
    """Parse a rule pattern.

    Accepted forms:
        $                    the whole body
        $.a.b   $['a b']     fields
        $.items[0]           an array index
        $.items[*]           every element of an array
        $.items[sku=A-100]   the element whose sku is A-100
        $.items['sku'='A 1'] the same, for keys or values with special characters
        $.a.*                every field of an object
        $..name              a field called name, at any depth
        name                 shorthand for $..name
    """
    text = source.strip()
    if not text:
        raise PathSyntaxError("path pattern is empty")
    if not text.startswith("$"):
        if not _PLAIN_NAME.fullmatch(text):
            raise PathSyntaxError(
                f"{source!r}: a pattern must start with $ or be a bare field name"
            )
        return Pattern(source=source, segments=(_Descendant(text),))

    segments: list[_PatternSegment] = []
    position = 1
    while position < len(text):
        rest = text[position:]
        if rest.startswith(".."):
            name = _PLAIN_NAME.match(rest, 2)
            if name is None:
                raise PathSyntaxError(f"{source!r}: expected a field name after '..'")
            segments.append(_Descendant(name.group()))
            position += name.end()
        elif rest.startswith(".*"):
            segments.append(_AnyKey())
            position += 2
        elif rest.startswith("."):
            name = _PLAIN_NAME.match(rest, 1)
            if name is None:
                raise PathSyntaxError(f"{source!r}: expected a field name after '.'")
            segments.append(_Key(name.group()))
            position += name.end()
        elif keyed := _QUOTED_KEY_MATCH.match(rest):
            segments.append(KeyMatch(_unescape(keyed.group(1)), _unescape(keyed.group(2))))
            position += keyed.end()
        elif quoted := _QUOTED.match(rest):
            segments.append(_Key(_unescape(quoted.group(1))))
            position += quoted.end()
        elif bracket := _BRACKET.match(rest):
            segments.append(_parse_bracket(bracket.group(1), source))
            position += bracket.end()
        else:
            raise PathSyntaxError(f"{source!r}: unexpected {rest[0]!r} at position {position}")
    return Pattern(source=source, segments=tuple(segments))


def _parse_bracket(inner: str, source: str) -> _PatternSegment:
    if inner == "*":
        return _AnyElement()
    if inner.isdecimal():
        return _Index(int(inner))
    key, separator, value = inner.partition("=")
    if separator and _PLAIN_NAME.fullmatch(key) and _PLAIN_NAME.fullmatch(value):
        return KeyMatch(key=key, value=value)
    raise PathSyntaxError(f"{source!r}: [{inner}] is not an index, [*], or [key=value]")
