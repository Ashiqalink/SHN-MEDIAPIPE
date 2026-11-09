"""Behavior checks for phase 0 fixtures and the phase 1 read-only core."""

from copy import deepcopy
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from core import LoadError, load_project, parse_document
from core.source import segments


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/falling-sand"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def edit(value, pointer, replacement):
    parts = segments(pointer)
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    key = int(parts[-1]) if isinstance(value, list) else parts[-1]
    value[key] = replacement


class FixtureTests(unittest.TestCase):
    def test_fixture_envelopes_and_phase_zero_exit_links(self):
        meta = json.loads((ROOT / "spec/fixture.schema.json").read_text())
        Draft202012Validator.check_schema(meta)
        validator = Draft202012Validator(meta)
        for path in (ROOT / "spec/fixtures").rglob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict) or "fixtureVersion" not in value:
                continue  # Raw byte sources are not fixture manifests.
            with self.subTest(path=path):
                validator.validate(value)
                ids = [case["id"] for case in value["cases"]]
                self.assertEqual(len(ids), len(set(ids)))
                for case in value["cases"]:
                    contract = case["expect"].get("contract")
                    if contract:
                        self.assertTrue((ROOT / contract).is_file())

    def test_schema_sample_copies_match(self):
        self.assertEqual((ROOT / "schemas/example-falling-sand.schema.json").read_bytes(),
                         (SAMPLE / "project.schema.json").read_bytes())


class SourceTests(unittest.TestCase):
    def test_byte_spans_bom_unicode_order_and_literals(self):
        raw = b'\xef\xbb\xbf{\r\n\t"label": "\xe6\xb0\xb4\xf0\x9f\x98\x80", "n": 1e+02, "z": -0.00\r\n}\r\n'
        doc = parse_document(raw, "test.json")
        self.assertEqual(doc.original, raw)
        self.assertEqual(doc.hash, sha256(raw).hexdigest())
        self.assertEqual(list(doc.root.value), ["label", "n", "z"])
        self.assertEqual(doc.token("/n"), b"1e+02")
        self.assertEqual(doc.token("/z"), b"-0.00")
        self.assertEqual(doc.root.value["n"], Decimal(100))
        self.assertTrue(doc.root.value["z"].is_signed())
        self.assertEqual(doc.line_column(doc.nodes["/n"].span.start), (2, 22))
        self.assertEqual(doc.newline, "\r\n")
        self.assertEqual(doc.indent, "\t")
        self.assertEqual(doc.trailing_newline, "\r\n")
        self.assertEqual(doc.nodes["/label"].parent_id, doc.root.node_id)

    def test_escaped_pointers_and_exact_decimal_independent_of_context(self):
        with localcontext() as context:
            context.prec = 3
            doc = parse_document(b'{"a/b~c":0.100000000000000000001,"items":[1.0]}', "x.json")
        self.assertEqual(doc.token("/a~1b~0c"), b"0.100000000000000000001")
        self.assertEqual(doc.root.value["a/b~c"], Decimal("0.100000000000000000001"))
        self.assertEqual(doc.nodes["/items/0"].kind, "number")

    def test_strict_json_rejections(self):
        for raw in (b'{"id":1,"id":2}', b'[1,]', b'{"x":1,}', b'NaN', b'Infinity',
                    b'01', b'1.', b'// comment\n[]', b'"\\ud800"', b'"\xff"', b'{} {}',
                    b'[true false]', b'{"x" 1}', b'"unterminated', b'{', b''):
            with self.subTest(raw=raw), self.assertRaises(LoadError):
                parse_document(raw, "bad.json")

    def test_portable_numeric_limits(self):
        for raw in (b"1e6145", b"1e-6145", b"9" * 1025):
            with self.subTest(raw=raw[:20]), self.assertRaises(LoadError) as raised:
                parse_document(raw, "number.json")
            self.assertEqual(raised.exception.diagnostics[0].code, "content.number_limit")
        self.assertEqual(parse_document(b"1e6144", "number.json").root.value, Decimal("1e6144"))
        self.assertEqual(parse_document(b"1e" + b"0" * 5000, "number.json").root.value, 1)

    def test_roundtrip_seed_sources_retain_every_token(self):
        directory = ROOT / "spec/fixtures/roundtrip"
        fixture = json.loads((directory / "cases.json").read_text())
        for case in fixture["cases"]:
            raw = (directory / case["input"]["source"]).read_bytes()
            with self.subTest(case=case["id"]):
                doc = parse_document(raw, case["input"]["source"])
                self.assertEqual(doc.original, raw)
                if case["id"] == "unicode":
                    self.assertEqual(doc.root.value["label"], "水😀")
                for node in doc.nodes.values():
                    self.assertEqual(doc.token(node.pointer), raw[node.span.start:node.span.end])


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        shutil.copytree(SAMPLE, self.project, dirs_exist_ok=True)
        self.schema_path = self.project / "project.schema.json"
        self.content_path = self.project / "data/world.json"

    def schema(self):
        return json.loads(self.schema_path.read_text())

    def content(self):
        return json.loads(self.content_path.read_text())

    def assert_schema_error(self, schema, code=None):
        write_json(self.schema_path, schema)
        with self.assertRaises(LoadError) as raised:
            load_project(self.project)
        if code:
            self.assertIn(code, [d.code for d in raised.exception.diagnostics])

    def test_shared_loading_cases(self):
        fixture = json.loads((ROOT / "spec/fixtures/schema/loading.json").read_text())
        baseline_schema, baseline_content = self.schema(), self.content()
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                schema, content = deepcopy(baseline_schema), deepcopy(baseline_content)
                for operation in case["input"].get("schemaEdits", []):
                    edit(schema, operation["pointer"], operation["value"])
                for operation in case["input"].get("contentEdits", []):
                    edit(content, operation["pointer"], operation["value"])
                write_json(self.schema_path, schema)
                write_json(self.content_path, content)
                try:
                    result = load_project(self.project)
                except LoadError as exc:
                    self.assertTrue(case["expect"]["raises"])
                    diagnostics = exc.diagnostics
                else:
                    self.assertFalse(case["expect"]["raises"])
                    diagnostics = result.diagnostics
                    if "materials" in case["expect"]:
                        self.assertEqual([e.id for e in result.entities if e.kind == "materials"], case["expect"]["materials"])
                self.assertEqual([d.code for d in diagnostics], case["expect"]["codes"])

    def test_references_and_no_writes(self):
        before = {p.relative_to(self.project): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.project.rglob("*") if p.is_file()}
        project = load_project(self.project)
        self.assertFalse(project.has_errors)
        self.assertEqual(project.resolve("palettes", "main")[0].value["colors"][0], "#d2b46c")
        self.assertTrue(all(r.resolution == "resolved" for r in project.references))
        after = {p.relative_to(self.project): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(project.raw_files["data/world.json"], self.content_path.read_bytes())

    def test_missing_and_ambiguous_references(self):
        content = self.content()
        content["materials"][1]["id"] = "sand"
        content["reactions"][0]["inputs"] = ["typo"]
        write_json(self.content_path, content)
        project = load_project(self.project)
        self.assertTrue(any(r.value == "sand" and r.resolution == "ambiguous" for r in project.references))
        self.assertTrue(any(r.value == "typo" and r.resolution == "missing" for r in project.references))
        # L-1 is phase 2; phase 1 only resolves and indexes references.
        self.assertNotIn("L-1", [d.rule for d in project.diagnostics])

    def test_bad_json_retains_original_bytes_and_missing_file_is_not_empty(self):
        raw = b'[{"id":"sand","id":"water"}]'
        self.content_path.write_bytes(raw)
        project = load_project(self.project)
        self.assertEqual(project.raw_files["data/world.json"], raw)
        self.assertIn("content.duplicate_key", [d.code for d in project.diagnostics])
        self.content_path.unlink()
        project = load_project(self.project)
        self.assertIn("content.read_failed", [d.code for d in project.diagnostics])

    def test_schema_refs_closed_annotations_and_bounds(self):
        cases = []
        schema = self.schema(); schema["properties"]["materials"]["items"]["properties"]["density"] = {"$ref":"https://invalid.example/schema"}; cases.append(schema)
        schema = self.schema(); schema["$defs"] = {"loop":{"$ref":"#/$defs/loop"}}; cases.append(schema)
        schema = self.schema(); schema["$defs"] = {"loop":{"type":"array","items":{"$ref":"#/$defs/loop"}}}; cases.append(schema)
        schema = self.schema(); schema["properties"]["materials"]["items"]["properties"]["density"] = {"$ref":"#/$defs/missing"}; cases.append(schema)
        schema = self.schema(); schema["x-pixorra"]["unknown"] = True; cases.append(schema)
        schema = self.schema(); schema["properties"]["materials"]["items"]["additionalProperties"] = True; cases.append(schema)
        schema = self.schema(); schema["properties"]["materials"]["items"]["properties"]["density"]["maximum"] = -1; cases.append(schema)
        schema = self.schema(); schema["properties"]["materials"]["items"]["properties"]["density"]["default"] = "dense"; cases.append(schema)
        schema = self.schema(); schema["x-pixorra"]["bindings"]["palettes"]["pointer"] = "/materials"; cases.append(schema)
        schema = self.schema(); schema["x-pixorra"]["bindings"]["palettes"]["path"] = "data/WORLD.json"; cases.append(schema)
        schema = self.schema(); schema["properties"]["materials"]["items"]["properties"]["color"]["x-pixorra"]["paletteIndex"]["paletteField"] = "/density"; cases.append(schema)
        for i, schema in enumerate(cases):
            with self.subTest(case=i):
                self.assert_schema_error(schema)

    def test_valid_local_ref_and_integral_decimal(self):
        schema = self.schema()
        schema["$defs"] = {"density%":{"type":"number","minimum":0}}
        schema["properties"]["materials"]["items"]["properties"]["density"] = {"$ref":"#/$defs/density%25"}
        write_json(self.schema_path, schema)
        raw = self.content_path.read_bytes().replace(b'"color": 0', b'"color": 0.0')
        self.content_path.write_bytes(raw)
        project = load_project(self.project)
        self.assertFalse(project.has_errors)
        self.assertEqual(project.documents["data/world.json"].token("/materials/0/color"), b"0.0")

    def test_version_history_and_schema_hash_changes(self):
        current = load_project(self.project)
        entry = {"contentHash":current.documents["data/world.json"].hash,
                 "schemaId":current.schema.identity["id"], "schemaVersion":"0.9.0",
                 "schemaHash":current.schema.identity["hash"]}
        history = {"stateVersion":1,"files":{"data/world.json":entry}}
        write_json(self.project / ".pixorra/state.json", history)
        project = load_project(self.project)
        self.assertIn("schema.version_mismatch", [d.code for d in project.diagnostics])
        self.assertTrue(project.acknowledgment_required)
        entry["schemaVersion"] = "1.0.0"; entry["schemaHash"] = "0" * 64
        write_json(self.project / ".pixorra/state.json", history)
        self.assertIn("schema.content_changed", [d.code for d in load_project(self.project).diagnostics])
        entry["contentHash"] = "0" * 64
        write_json(self.project / ".pixorra/state.json", history)
        self.assertIn("schema.history_stale", [d.code for d in load_project(self.project).diagnostics])
        write_json(self.project / ".pixorra/state.json", {"stateVersion":99})
        self.assertIn("schema.history_invalid", [d.code for d in load_project(self.project).diagnostics])

    def test_config_rule_union_explicit_schema_and_invalid_config(self):
        schema = self.schema(); schema["x-pixorra"]["rules"] = {"L-5":{"enabled":False}}
        write_json(self.schema_path, schema)
        write_json(self.project / ".pixorra/project.json", {"configVersion":1,"schemaPath":"missing.schema.json","disabledRules":["L-14","L-1"]})
        project = load_project(self.project, "project.schema.json")
        self.assertEqual(project.disabled_rules, ("L-1", "L-5", "L-14"))
        content = self.content(); content["materials"][0]["density"] = True
        write_json(self.content_path, content)
        self.assertIn("type.mismatch", [d.code for d in load_project(self.project, "project.schema.json").diagnostics])
        write_json(self.project / ".pixorra/project.json", {"configVersion":1,"disabledRules":["L-99"]})
        with self.assertRaises(LoadError):
            load_project(self.project)

    def test_materials_only_custom_field_names_and_nested_binding(self):
        schema = self.schema()
        materials = schema["properties"]["materials"]
        materials["items"] = {"type":"object","properties":{"key":{"type":"string","minLength":1},"mass":{"type":"number"}},"required":["key","mass"],"additionalProperties":False}
        materials["x-pixorra"] = {"kind":"materials","idField":"/key","roles":{}}
        schema["properties"] = {"powders":materials}; schema["required"] = ["powders"]
        schema["x-pixorra"]["bindings"] = {"powders":{"path":"third-party.json","pointer":"/game/powders"}}
        write_json(self.schema_path, schema)
        write_json(self.project / "third-party.json", {"game":{"powders":[{"key":"ash","mass":0.2}]}})
        project = load_project(self.project)
        self.assertFalse(project.has_errors)
        self.assertEqual(project.resolve("materials", "ash")[0].location.pointer, "/game/powders/0")
        self.assertEqual(set(project.documents), {"third-party.json"})

    def test_quest_shaped_schema_uses_mapped_stage_and_transition_fields(self):
        def obj(properties):
            return {"type":"object", "properties":properties, "required":list(properties), "additionalProperties":False}
        name = {"type":"string", "minLength":1}
        transition = obj({"next":name, "when":{"type":"string", "x-pixorra":{"expression":True}}})
        stage = obj({"key":name, "done":{"type":"boolean"}, "links":{"type":"array", "items":transition}})
        quest = obj({"name":name, "start":name, "steps":{"type":"array", "items":stage}})
        category = {"type":"array", "items":quest, "x-pixorra":{
            "kind":"quests", "idField":"/name", "roles":{
                "stages":"/steps", "initialStage":"/start", "stageId":"/key", "terminal":"/done",
                "transitions":"/links", "target":"/next", "condition":"/when"}}}
        schema = self.schema(); schema["properties"] = {"stories":category}; schema["required"] = ["stories"]
        schema["x-pixorra"]["bindings"] = {"stories":{"path":"story.json", "pointer":""}}
        write_json(self.schema_path, schema)
        write_json(self.project / "story.json", [{"name":"rescue", "start":"new", "steps":[
            {"key":"new", "done":False, "links":[{"next":"complete", "when":"true"}]},
            {"key":"complete", "done":True, "links":[]}]}])
        project = load_project(self.project)
        self.assertFalse(project.has_errors)
        self.assertEqual(project.resolve("quests", "rescue")[0].category, "stories")

    def test_malformed_extension_shapes_always_produce_diagnostics(self):
        cases = (
            ("/x-pixorra", []),
            ("/properties/materials/x-pixorra/kind", []),
            ("/properties/materials/x-pixorra/roles", None),
            ("/properties/materials/x-pixorra/idField", 3),
            ("/properties/materials/items/properties/palette/x-pixorra/reference", []),
            ("/properties/materials/items/properties/palette/x-pixorra/reference/kind", {}),
            ("/properties/materials/items/properties/color/x-pixorra/paletteIndex", False),
            ("/x-pixorra/expressionContext", []),
            ("/x-pixorra/rules", None),
            ("/x-pixorra/bindings/materials/pointer", None),
        )
        baseline = self.schema()
        for pointer, value in cases:
            with self.subTest(pointer=pointer):
                schema = deepcopy(baseline)
                edit(schema, pointer, value)
                self.assert_schema_error(schema)

    def test_remote_ref_refused_without_opening_a_socket(self):
        schema = self.schema()
        schema["properties"]["materials"]["items"]["properties"]["density"] = {"$ref":"https://invalid.example/data"}
        with patch("socket.socket", side_effect=AssertionError("Network access attempted")):
            self.assert_schema_error(schema, "schema.reference_invalid")

    def test_missing_wrapper_and_wrong_category_type_remain_inspectable(self):
        content = self.content(); del content["materials"]
        write_json(self.content_path, content)
        project = load_project(self.project)
        self.assertIn("content.required", [d.code for d in project.diagnostics])
        content["materials"] = False
        write_json(self.content_path, content)
        project = load_project(self.project)
        diagnostic = next(d for d in project.diagnostics if d.code == "type.mismatch")
        self.assertEqual(diagnostic.location.pointer, "/materials")
        self.assertEqual(diagnostic.rule, "L-14")

    def test_cli_and_core_have_no_ui_or_server_dependencies(self):
        run = subprocess.run([sys.executable, "-m", "core", str(self.project)], cwd=ROOT,
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["schema"]["version"], "1.0.0")
        # The core subprocess itself must not import UI/server machinery, even
        # when unrelated test modules (server tests) share this process.
        child = subprocess.run(
            [sys.executable, "-c",
             "import sys, core.__main__; "
             "print(sorted(n for n in sys.modules "
             "if n.split('.')[0] in ('fastapi', 'server', 'web', 'zustand')))"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout), [])
        self.content_path.write_bytes(b"not json")
        run = subprocess.run([sys.executable, "-m", "core", str(self.project)], cwd=ROOT,
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads(run.stdout)["diagnostics"][-1]["code"], "content.json_invalid")


if __name__ == "__main__":
    unittest.main()
