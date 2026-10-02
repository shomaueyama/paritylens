"""Rules in the form the comparison code uses: patterns already parsed."""

from dataclasses import dataclass
from datetime import timedelta

from paritylens_engine.model import RuleSet
from paritylens_engine.paths import Path, Pattern, parse_pattern


@dataclass(frozen=True)
class CompiledUnordered:
    pattern: Pattern
    key: str | None


@dataclass(frozen=True)
class CompiledRules:
    ignore: tuple[Pattern, ...]
    critical: tuple[Pattern, ...]
    unordered: tuple[CompiledUnordered, ...]
    compare_headers: tuple[str, ...]
    critical_field_names: bool
    clock_tolerance: timedelta

    def ignores(self, path: Path) -> bool:
        return any(pattern.covers(path) for pattern in self.ignore)

    def marks_critical(self, path: Path) -> bool:
        return any(pattern.covers(path) for pattern in self.critical)

    def unordered_at(self, path: Path) -> CompiledUnordered | None:
        """The unordered rule for the array at exactly this path, if there is one."""
        for rule in self.unordered:
            if rule.pattern.matches(path):
                return rule
        return None


def compile_rules(rules: RuleSet) -> CompiledRules:
    return CompiledRules(
        ignore=tuple(parse_pattern(source) for source in rules.ignore),
        critical=tuple(parse_pattern(source) for source in rules.critical),
        unordered=tuple(
            CompiledUnordered(pattern=parse_pattern(rule.path), key=rule.key)
            for rule in rules.unordered
        ),
        compare_headers=rules.compare_headers,
        critical_field_names=rules.critical_field_names,
        clock_tolerance=timedelta(seconds=rules.clock_tolerance_seconds),
    )
