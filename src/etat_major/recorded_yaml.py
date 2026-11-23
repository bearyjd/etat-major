"""Bound the shape of a recorded YAML mapping before constructing it."""

from pathlib import Path

import yaml

from etat_major.taskfile import TaskFileError, parse_yaml_mapping


def parse_bounded_yaml_mapping(
    text: str, path: Path, *, field: str, label: str, max_depth: int = 32
) -> dict:
    depth = 0
    try:
        for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader), 1):
            if count > 20_000:
                raise TaskFileError(path, field, "YAML exceeds the 20000-event limit")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > max_depth:
                    raise TaskFileError(
                        path, field, f"YAML exceeds the {max_depth}-level depth limit"
                    )
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.AliasEvent):
                raise TaskFileError(path, field, "YAML aliases are not allowed")
    except TaskFileError:
        raise
    except (yaml.YAMLError, ValueError, OverflowError, RecursionError):
        raise TaskFileError(path, field, f"invalid {label} YAML") from None
    return parse_yaml_mapping(text, path, field=field)
