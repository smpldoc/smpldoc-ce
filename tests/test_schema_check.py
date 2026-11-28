"""The small JSON Schema checker that bundle validation runs on: standard library only."""
import json
import unittest
from pathlib import Path

from smpldoc.domain.schema_check import SUPPORTED, SchemaError, check

SCHEMAS = Path(__file__).resolve().parent.parent / "smpldoc" / "domain" / "schemas"


class SchemaCheckTest(unittest.TestCase):
    def test_type_errors_name_the_path(self):
        schema = {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "integer"}}}}
        self.assertEqual(check({"a": [1, "2"]}, schema), ["/a/1: expected integer"])

    def test_booleans_are_not_numbers(self):
        self.assertEqual(check(True, {"type": "number"}), [": expected number"])
        self.assertEqual(check(True, {"type": "integer"}), [": expected integer"])
        self.assertEqual(check(1.5, {"type": "integer"}), [": expected integer"])

    def test_required_and_unknown_properties(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}},
                  "additionalProperties": False}
        self.assertEqual(check({"b": 1}, schema), ["/a: required", "/b: unknown property"])

    def test_lenient_mode_accepts_unknown_properties_and_enum_values(self):
        schema = {"type": "object", "properties": {"k": {"enum": ["x"]}}, "additionalProperties": False}
        self.assertEqual(check({"k": "y", "new": 1}, schema, lenient=True), [])
        self.assertEqual(check({"k": 5}, {"properties": {"k": {"type": "string", "enum": ["x"]}}}, lenient=True),
                         ["/k: expected string"])

    def test_additional_properties_can_be_a_schema(self):
        schema = {"type": "object", "properties": {"c": {"type": "string"}},
                  "additionalProperties": {"type": "string", "pattern": "^[0-9]+$"}}
        self.assertEqual(check({"c": "USD", "x": "12", "y": "a"}, schema), ["/y: does not match ^[0-9]+$"])

    def test_scalar_keywords(self):
        self.assertEqual(check("ab", {"minLength": 3}), [": shorter than 3"])
        self.assertEqual(check("abcd", {"maxLength": 3}), [": longer than 3"])
        self.assertEqual(check(5, {"minimum": 6}), [": below 6"])
        self.assertEqual(check(5, {"maximum": 4}), [": above 4"])
        self.assertEqual(check(5, {"exclusiveMinimum": 5}), [": not above 5"])
        self.assertEqual(check("b", {"const": "a"}), [": must be 'a'"])
        self.assertEqual(check("b", {"enum": ["a", "c"]}), [": must be one of 'a', 'c'"])
        self.assertEqual(check([], {"minItems": 1}), [": fewer than 1 items"])
        self.assertEqual(check([1, 2], {"maxItems": 1}), [": more than 1 items"])

    def test_pattern_must_match_the_whole_value(self):
        self.assertEqual(check("12a", {"pattern": "^[0-9]+$"}), [": does not match ^[0-9]+$"])
        self.assertEqual(check("12\n", {"pattern": "^[0-9]+$"}), [": does not match ^[0-9]+$"])

    def test_local_refs(self):
        schema = {"$defs": {"n": {"type": "integer"}}, "type": "array", "items": {"$ref": "#/$defs/n"}}
        self.assertEqual(check([1, "x"], schema), ["/1: expected integer"])

    def test_unsupported_keywords_and_remote_refs_are_refused(self):
        with self.assertRaises(SchemaError):
            check(1, {"oneOf": [{"type": "integer"}]})
        with self.assertRaises(SchemaError):
            check(1, {"$ref": "https://example.com/s.json"})

    def test_every_shipped_schema_uses_only_supported_keywords(self):
        files = sorted(SCHEMAS.rglob("*.json"))
        self.assertTrue(files)
        for path in files:
            schema = json.loads(path.read_text(encoding="utf-8"))
            check({}, schema, lenient=True)  # raises SchemaError on anything unsupported

            def walk(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in ("properties", "$defs"):
                            for sub in value.values():
                                walk(sub)
                            continue
                        self.assertIn(key, SUPPORTED, f"{path.name}: {key}")
                        walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)
            walk(schema)


if __name__ == "__main__":
    unittest.main()
