"""A small JSON Schema checker, standard library only.

It understands the subset of JSON Schema 2020-12 that the bundle schemas use, and refuses any
other keyword, so a schema can never silently mean more than this code checks.

`lenient=True` is for reading a bundle written by a newer minor version: unknown properties and
unknown enum values are accepted, because a minor version may only add them.
"""
import re

SUPPORTED = frozenset({
    "$schema", "$id", "$defs", "$ref", "title", "description",
    "type", "properties", "required", "additionalProperties", "items",
    "enum", "const", "pattern", "minLength", "maxLength",
    "minimum", "maximum", "exclusiveMinimum", "minItems", "maxItems",
})

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaError(Exception):
    """The schema itself uses something this checker does not understand."""


def check(value, schema, *, lenient=False) -> list[str]:
    audit(schema)
    errors: list[str] = []
    _check(value, schema, schema, "", lenient, errors)
    return errors


def audit(schema, root=None, where="/") -> None:
    """Raise SchemaError if any part of the schema, used or not, says something we do not check."""
    root = schema if root is None else root
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: a schema must be an object")
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise SchemaError(f"{where}: unsupported keyword {sorted(unknown)[0]}")
    if "type" in schema and schema["type"] not in _TYPES:
        raise SchemaError(f"{where}: unknown type {schema['type']}")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref[8:] not in root.get("$defs", {}):
            raise SchemaError(f"{where}: only references to this schema's own #/$defs/ are supported")
    for key in ("properties", "$defs"):
        for name, sub in schema.get(key, {}).items():
            audit(sub, root, f"{where}{key}/{name}/")
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            audit(schema[key], root, f"{where}{key}/")


def _check(value, schema, root, path, lenient, errors):
    if "$ref" in schema:
        _check(value, root["$defs"][schema["$ref"][8:]], root, path, lenient, errors)

    kind = schema.get("type")
    if kind is not None and not _TYPES[kind](value):
        errors.append(f"{path}: expected {kind}")
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"] and not lenient:
        errors.append(f"{path}: must be one of " + ", ".join(repr(v) for v in schema["enum"]))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")

    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above {schema['exclusiveMinimum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], root, f"{path}/{i}", lenient, errors)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in value:
                errors.append(f"{path}/{name}: required")
        extra = schema.get("additionalProperties", True)
        for name in sorted(value):
            sub = f"{path}/{name}"
            if name in props:
                _check(value[name], props[name], root, sub, lenient, errors)
            elif extra is False and not lenient:
                errors.append(f"{sub}: unknown property")
            elif isinstance(extra, dict):
                _check(value[name], extra, root, sub, lenient, errors)
