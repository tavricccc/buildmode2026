"""Contract validation (domain/schema.py)."""

import unittest

from ..domain.observation import GeminiObservation
from ..domain.schema import Field, Schema, SchemaError, json_skeleton
from ..jsonio import JsonExtractionError, extract_json


class Sample(Schema):
    schema_version = "sample.v1"
    fields = {
        "count": Field(int, minimum=0),
        "label": Field(str, default="none"),
        "score": Field(float, minimum=0.0, maximum=1.0, default=0.0),
        "tags": Field(list, default=list, item=str, max_items=2),
    }


class TestSchema(unittest.TestCase):
    def test_defaults_fill_absent_fields(self):
        parsed = Sample.parse({"count": 3})
        self.assertEqual(parsed.to_dict(), {"count": 3, "label": "none", "score": 0.0, "tags": []})

    def test_bool_never_satisfies_int(self):
        # True == 1 in Python; a model answering `true` for a count is an
        # error, not a 1.
        with self.assertRaises(SchemaError) as caught:
            Sample.parse({"count": True})
        self.assertEqual(caught.exception.code, "type")

    def test_out_of_range_is_distinguishable_from_missing(self):
        with self.assertRaises(SchemaError) as high:
            Sample.parse({"count": 1, "score": 1.4})
        with self.assertRaises(SchemaError) as absent:
            Sample.parse({})
        self.assertEqual(high.exception.code, "range")
        self.assertEqual(absent.exception.code, "missing")

    def test_undeclared_keys_are_rejected(self):
        with self.assertRaises(SchemaError) as caught:
            Sample.parse({"count": 1, "invented": True})
        self.assertEqual(caught.exception.code, "extra")

    def test_int_widens_to_float_but_not_the_reverse(self):
        self.assertEqual(Sample.parse({"count": 1, "score": 1}).score, 1.0)
        with self.assertRaises(SchemaError):
            Sample.parse({"count": 1.5})

    def test_prompt_skeleton_lists_every_declared_field(self):
        skeleton = json_skeleton(GeminiObservation)
        for name in GeminiObservation.fields:
            self.assertIn(f'"{name}"', skeleton)
        for nested, cls in GeminiObservation.nested.items():
            self.assertIn(f'"{nested}"', skeleton)
            for name in cls.fields:
                self.assertIn(f'"{name}"', skeleton)


class TestObservation(unittest.TestCase):
    def test_escalation_defaults_to_not_required(self):
        parsed = GeminiObservation.parse({"person_visible": False, "confidence": 0.5})
        self.assertFalse(parsed.needs_escalation())
        self.assertEqual(parsed.escalation.reason_codes, [])

    def test_invented_reason_codes_are_dropped(self):
        parsed = GeminiObservation.parse({
            "person_visible": True, "confidence": 0.9,
            "escalation": {"required": True, "reason_codes": ["possible_fall", "call_911_now"]},
        })
        self.assertEqual(parsed.escalation.normalised_reasons(), ["possible_fall"])

    def test_required_escalation_without_a_valid_reason_becomes_other(self):
        parsed = GeminiObservation.parse({
            "person_visible": True, "confidence": 0.9,
            "escalation": {"required": True, "reason_codes": ["nonsense"]},
        })
        self.assertEqual(parsed.escalation.normalised_reasons(), ["other"])

    def test_fall_needs_floor_proximity_and_confidence(self):
        lying_high = GeminiObservation.parse({
            "person_visible": True, "confidence": 0.9,
            "fall": {"posture": "lying", "near_floor": True, "confidence": 0.9}})
        lying_low = GeminiObservation.parse({
            "person_visible": True, "confidence": 0.9,
            "fall": {"posture": "lying", "near_floor": True, "confidence": 0.2}})
        on_sofa = GeminiObservation.parse({
            "person_visible": True, "confidence": 0.9,
            "fall": {"posture": "lying", "near_floor": False, "confidence": 0.9}})
        self.assertTrue(lying_high.fall.indicates_fall(0.5))
        self.assertFalse(lying_low.fall.indicates_fall(0.5))
        self.assertFalse(on_sofa.fall.indicates_fall(0.5))


class TestJsonExtraction(unittest.TestCase):
    def test_recovers_a_markdown_fence(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_recovers_prose_preamble_and_trailing_comma(self):
        self.assertEqual(extract_json('Sure, here you go: {"a": 1,}'), {"a": 1})

    def test_brace_inside_a_string_does_not_truncate(self):
        parsed = extract_json('{"scene_summary": "a chair } and a cup", "n": 2}')
        self.assertEqual(parsed["n"], 2)

    def test_no_object_raises(self):
        with self.assertRaises(JsonExtractionError):
            extract_json("I could not analyse that clip.")


if __name__ == "__main__":
    unittest.main()
