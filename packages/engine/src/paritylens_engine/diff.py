"""The deterministic diff: what is different between two responses.

Nothing here judges whether a difference matters. This module only reports
what differs and where; severity.py decides how serious each one is.
"""

from collections import Counter
from collections.abc import Hashable
from dataclasses import dataclass

from paritylens_engine.jsonvalue import Json, json_type, label
from paritylens_engine.model import DiffKind, Note, ResponseSnapshot
from paritylens_engine.normalize import EmptyBody, JsonBody, TextBody, media_type, read_body
from paritylens_engine.paths import KeyMatch, Path, render
from paritylens_engine.rules import CompiledRules


@dataclass(frozen=True)
class RawDifference:
    """A difference before it has been given a severity."""

    kind: DiffKind
    # Where it is, as text: "status", "header.<name>", "body", or a JSON path.
    location: str
    # Set only for differences inside a JSON body, where path rules apply.
    path: Path | None = None
    old: Json = None
    new: Json = None
    detail: str | None = None


def diff_responses(
    old: ResponseSnapshot, new: ResponseSnapshot, rules: CompiledRules
) -> tuple[list[RawDifference], list[Note]]:
    differences: list[RawDifference] = []
    notes: list[Note] = []

    if old.status != new.status:
        differences.append(
            RawDifference(DiffKind.STATUS_CHANGED, "status", old=old.status, new=new.status)
        )

    for name in rules.compare_headers:
        old_value, new_value = old.headers.get(name), new.headers.get(name)
        if old_value != new_value:
            differences.append(
                RawDifference(
                    DiffKind.HEADER_CHANGED, f"header.{name}", old=old_value, new=new_value
                )
            )

    # A success and an error response have nothing meaningful in common.
    # Comparing them field by field would bury the one fact that matters,
    # the status change, under a pile of removed and added fields.
    if old.status // 100 != new.status // 100:
        notes.append(Note.BODY_NOT_COMPARED_STATUS_CLASS)
        return differences, notes

    # Half a body cannot be compared: a difference past the cut would be missed.
    if old.body_truncated or new.body_truncated:
        notes.append(Note.BODY_NOT_COMPARED_TRUNCATED)
        return differences, notes

    old_body, new_body = read_body(old), read_body(new)
    old_media, new_media = media_type(old), media_type(new)
    if old_body.label != new_body.label:
        differences.append(
            RawDifference(
                DiffKind.BODY_FORMAT_CHANGED, "body", old=old_body.label, new=new_body.label
            )
        )
    elif old_media != new_media and not isinstance(old_body, EmptyBody):
        # With no body on either side there is no format to have changed.
        differences.append(
            RawDifference(DiffKind.BODY_FORMAT_CHANGED, "body", old=old_media, new=new_media)
        )

    if isinstance(old_body, JsonBody) and isinstance(new_body, JsonBody):
        differences.extend(_diff_values(old_body.value, new_body.value, (), rules))
    elif (
        isinstance(old_body, TextBody)
        and isinstance(new_body, TextBody)
        and old_body.text != new_body.text
    ):
        differences.append(
            RawDifference(DiffKind.VALUE_CHANGED, "body", old=old_body.text, new=new_body.text)
        )
    return differences, notes


def diff_json(old: Json, new: Json, rules: CompiledRules) -> list[RawDifference]:
    """Compare two JSON documents."""
    return _diff_values(old, new, (), rules)


def _at(
    kind: DiffKind, path: Path, *, old: Json = None, new: Json = None, detail: str | None = None
) -> RawDifference:
    return RawDifference(kind, render(path), path, old, new, detail)


def _diff_values(old: Json, new: Json, path: Path, rules: CompiledRules) -> list[RawDifference]:
    old_type, new_type = json_type(old), json_type(new)
    if old_type != new_type:
        return [
            _at(DiffKind.TYPE_CHANGED, path, old=old, new=new, detail=f"{old_type} → {new_type}")
        ]
    if isinstance(old, dict) and isinstance(new, dict):
        return _diff_objects(old, new, path, rules)
    if isinstance(old, list) and isinstance(new, list):
        return _diff_arrays(old, new, path, rules)
    # Scalars. Python compares int and Decimal by value, so 100 == 100.0.
    if old != new:
        return [_at(DiffKind.VALUE_CHANGED, path, old=old, new=new)]
    return []


def _diff_objects(
    old: dict[str, Json], new: dict[str, Json], path: Path, rules: CompiledRules
) -> list[RawDifference]:
    differences: list[RawDifference] = []
    # Walk in document order so the output reads like the response does.
    for name, old_value in old.items():
        child = (*path, name)
        if name in new:
            differences.extend(_diff_values(old_value, new[name], child, rules))
        else:
            differences.append(_at(DiffKind.FIELD_REMOVED, child, old=old_value))
    for name, new_value in new.items():
        if name not in old:
            differences.append(_at(DiffKind.FIELD_ADDED, (*path, name), new=new_value))
    return differences


def _diff_arrays(
    old: list[Json], new: list[Json], path: Path, rules: CompiledRules
) -> list[RawDifference]:
    rule = rules.unordered_at(path)
    # An ignored array is walked in order so that every difference inside
    # it is still listed (at severity NONE) instead of matched away.
    if rule is None or rules.ignores(path):
        return _diff_ordered(old, new, path, rules)
    if rule.key is not None:
        old_by_key, new_by_key = _index_by(old, rule.key), _index_by(new, rule.key)
        if old_by_key is not None and new_by_key is not None:
            return _diff_keyed(old_by_key, new_by_key, rule.key, path, rules)
        # The key is missing or repeated somewhere, so it cannot pair
        # elements up. Whole-element matching still can.
    return _diff_multiset(old, new, path, rules)


def _diff_ordered(
    old: list[Json], new: list[Json], path: Path, rules: CompiledRules
) -> list[RawDifference]:
    differences: list[RawDifference] = []
    shared = min(len(old), len(new))
    for index in range(shared):
        differences.extend(_diff_values(old[index], new[index], (*path, index), rules))
    if len(old) != len(new):
        differences.append(
            _at(
                DiffKind.ARRAY_CHANGED,
                path,
                old=old[shared:],
                new=new[shared:],
                detail=f"length {len(old)} → {len(new)}",
            )
        )
    return differences


def _index_by(items: list[Json], key: str) -> dict[str, Json] | None:
    """Map each element by its key field, or None if the key cannot identify them."""
    indexed: dict[str, Json] = {}
    for item in items:
        if not isinstance(item, dict) or key not in item:
            return None
        value = item[key]
        if isinstance(value, list | dict) or value is None:
            return None
        name = label(value)
        if name in indexed:
            return None
        indexed[name] = item
    return indexed


def _diff_keyed(
    old: dict[str, Json], new: dict[str, Json], key: str, path: Path, rules: CompiledRules
) -> list[RawDifference]:
    differences: list[RawDifference] = []
    for name, old_item in old.items():
        if name in new:
            child = (*path, KeyMatch(key, name))
            differences.extend(_diff_values(old_item, new[name], child, rules))
    only_old = [item for name, item in old.items() if name not in new]
    only_new = [item for name, item in new.items() if name not in old]
    if only_old or only_new:
        differences.append(_unmatched(path, only_old, only_new))
    return differences


def _diff_multiset(
    old: list[Json], new: list[Json], path: Path, rules: CompiledRules
) -> list[RawDifference]:
    """Pair up elements that are entirely equal, ignoring order."""
    element = (*path, _NO_POSITION)
    old_frozen = [_freeze(item, element, rules) for item in old]
    new_frozen = [_freeze(item, element, rules) for item in new]
    spare_new = Counter(new_frozen)
    spare_old = Counter(old_frozen)

    only_old: list[Json] = []
    for item, frozen in zip(old, old_frozen, strict=True):
        if spare_new[frozen] > 0:
            spare_new[frozen] -= 1
        else:
            only_old.append(item)
    only_new: list[Json] = []
    for item, frozen in zip(new, new_frozen, strict=True):
        if spare_old[frozen] > 0:
            spare_old[frozen] -= 1
        else:
            only_new.append(item)

    if only_old or only_new:
        return [_unmatched(path, only_old, only_new)]
    return []


def _unmatched(path: Path, only_old: list[Json], only_new: list[Json]) -> RawDifference:
    return _at(
        DiffKind.ARRAY_CHANGED,
        path,
        old=only_old,
        new=only_new,
        detail=f"{len(only_old)} element(s) only in old, {len(only_new)} only in new",
    )


# Elements of an unordered array have no position. Paths built for them
# carry this in place of an index: [*] matches it, and [0] never does.
_NO_POSITION = -1


def _freeze(value: Json, path: Path, rules: CompiledRules) -> Hashable:
    """A hashable stand-in for a value, equal exactly when the values are equal
    under the rules.

    It has to agree with _diff_values on what "equal" means: ignored places
    are left out, and arrays that a rule declares unordered are compared
    without order here too. Each value is tagged with its JSON type because
    Python would otherwise treat True and 1 as the same.
    """
    if isinstance(value, dict):
        return (
            "object",
            frozenset(
                (name, _freeze(item, (*path, name), rules))
                for name, item in value.items()
                if not rules.ignores((*path, name))
            ),
        )
    if isinstance(value, list):
        unordered = rules.unordered_at(path) is not None
        frozen: list[Hashable] = []
        for index, item in enumerate(value):
            child = (*path, _NO_POSITION if unordered else index)
            frozen.append(("ignored",) if rules.ignores(child) else _freeze(item, child, rules))
        if unordered:
            return ("unordered array", frozenset(Counter(frozen).items()))
        return ("array", tuple(frozen))
    return (json_type(value), value)
