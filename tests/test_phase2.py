"""Save acceptance: raw bytes, preview gates, races, failure and partial commits."""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import SaveError, SaveSession, edit_document, lint_project, load_project, parse_document
from core.editing import VerificationError, verify_edit
from core import saving
from test_core import ROOT, SAMPLE, edit, write_json


class EditingTests(unittest.TestCase):
    def test_shared_roundtrip_fixtures(self):
        folder = ROOT / "spec/fixtures/roundtrip"
        cases = json.loads((folder / "cases.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                raw = (folder / case["input"]["source"]).read_bytes()
                document = parse_document(raw, "test.json")
                no_op = edit_document(document, deepcopy(document.root.value))
                self.assertEqual(no_op.candidate, raw)
                self.assertEqual(no_op.patches, ())
                model = deepcopy(document.root.value)
                change = case["input"]["edit"]
                edit(model, change["pointer"], change["value"])
                result = edit_document(document, model)
                self.assertEqual(len(result.patches), 1)
                item = result.patches[0]
                self.assertEqual(item.pointer, case["expect"]["changedPointer"])
                self.assertEqual(item.replacement.decode(), case["expect"]["replacement"])
                self.assertEqual(result.candidate, raw[:item.start] + item.replacement + raw[item.end:])

    def test_offset_map_multiple_lengths_and_mixed_styles(self):
        raw = b'{\r\n\t"x": 1e0,\n  "label": "old", "keep": -0.00\r\n}\r\n'
        doc = parse_document(raw, "x.json")
        result = edit_document(doc, {"x": Decimal("1000.1250"), "label": "\u6c34\U0001f600", "keep": 0})
        self.assertEqual(result.candidate, raw.replace(b"1e0", b"1000.125").replace(b'"old"', '"\u6c34\U0001f600"'.encode()))
        with self.assertRaises(VerificationError):
            verify_edit(replace(result, candidate=result.candidate.replace(b"-0.00", b"0.000")),
                        parse_document(result.candidate, "x").root.value)

    def test_container_insert_delete_preserves_children_keys_and_local_style(self):
        raw = b'{\n  "mixed": {\r\n\t"n": 1.2300,\r\n\t"\\u006b": "\\u0061"\r\n},\n  "keep": -0.0\n}'
        doc = parse_document(raw, "x.json")
        model = deepcopy(doc.root.value)
        model["mixed"]["new"] = Decimal("0.12500")
        result = edit_document(doc, model)
        self.assertEqual([p.pointer for p in result.patches], ["/mixed"])
        self.assertIn(b'\r\n\t"new": 0.125\r\n', result.candidate)
        self.assertIn(b'"n": 1.2300', result.candidate)
        self.assertIn(b'"\\u006b": "\\u0061"', result.candidate)
        self.assertTrue(result.candidate.endswith(b'"keep": -0.0\n}'))
        del model["mixed"]["n"]
        self.assertIn(b'"\\u006b": "\\u0061"', edit_document(doc, model).candidate)

    def test_shifted_array_children_and_empty_containers(self):
        doc = parse_document(b'{"a":[1e0,{"n":2.000},-0.0],"b":true}', "x")
        model = deepcopy(doc.root.value)
        model["a"].insert(0, "new")
        result = edit_document(doc, model)
        self.assertIn(b'1e0', result.candidate)
        self.assertIn(b'{"n":2.000}', result.candidate)
        self.assertIn(b'-0.0', result.candidate)
        model["a"] = []
        self.assertEqual(edit_document(doc, model).candidate, b'{"a":[],"b":true}')

    def test_exact_numbers_escapes_and_invalid_models(self):
        doc = parse_document(b'{"n":0,"s":""}', "x")
        with localcontext() as ctx:
            ctx.prec = 2
            result = edit_document(doc, {"n": Decimal("0.123456789012345678900"), "s": '/\n\t\x01"\\'})
        self.assertIn(b'0.1234567890123456789', result.candidate)
        self.assertIn(b'/\\n\\t\\u0001\\"\\\\', result.candidate)
        for model in ({"n": 0.1, "s": ""}, {1: "a"}, {"n": Decimal("NaN")}, {"n": "\ud800"}):
            with self.subTest(model=repr(model)), self.assertRaises((ValueError, UnicodeError)):
                edit_document(doc, model)

    def test_verifier_refuses_semantic_order_and_ownership_corruption(self):
        doc = parse_document(b'{"a":1,"b":2}', "x")
        result = edit_document(doc, {"a": 3, "b": 2})
        with self.assertRaises(VerificationError):
            verify_edit(replace(result, candidate=b'{"b":2,"a":3}'), {"a": 3, "b": 2})
        with self.assertRaises(VerificationError):
            verify_edit(replace(result, patches=(replace(result.patches[0], start=0),)), {"a": 3, "b": 2})


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(SAMPLE, self.root)
        self.path = "data/world.json"
        self.target = self.root / self.path
        self.session = SaveSession(load_project(self.root))

    def model(self):
        return deepcopy(self.session.project.documents[self.path].root.value)

    def changed(self, density=3):
        model = self.model()
        model["materials"][0]["density"] = density
        return {self.path: model}

    def prepare(self, **kwargs):
        return self.session.prepare(self.changed(), **kwargs)

    def assert_code(self, expected, operation):
        with self.assertRaises(SaveError) as caught:
            operation()
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def temp_files(self):
        return list(self.root.rglob(".pixorra-*.tmp"))


class SaveTests(ProjectCase):
    def test_shared_save_fixtures(self):
        cases = json.loads((ROOT / "spec/fixtures/save/mvp.json").read_bytes())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                folder = self.root / case["id"]
                shutil.copytree(SAMPLE, folder)
                target = folder / self.path
                before = target.read_bytes()
                session = SaveSession(load_project(folder))
                model = deepcopy(session.project.documents[self.path].root.value)
                model["materials"][0]["density"] = 3
                inputs = case["input"]
                plan = session.prepare({self.path: model} if inputs["mutation"] else {})
                fault = inputs.get("fault")
                if fault == "conflict":
                    target.write_bytes(before + b" ")
                targets = {"replace": "core.saving.os.replace", "fsync": "core.saving.os.fsync",
                           "directory-sync": "core.saving._sync_directory"}
                context = patch(targets[fault], side_effect=OSError("injected")) if fault in targets else nullcontext()
                statuses = []
                with context:
                    try:
                        result = session.commit(plan, acknowledge_preview=plan.token if inputs.get("acknowledge") else None)
                        status = result.status
                        statuses = [item["status"] for item in result.files]
                    except SaveError as exc:
                        status = exc.code
                disk = target.read_bytes()
                disk_state = "original" if disk == before else "candidate" if disk == plan.files[0].candidate else "external"
                self.assertEqual({"status": status, "previewRequired": plan.preview_required,
                    "diskState": disk_state, "historyExists": (folder / ".pixorra/state.json").exists(),
                    "tempFiles": len(list(folder.rglob(".pixorra-*.tmp"))), "fileStatuses": statuses}, case["expect"])

    def test_noop_has_no_write_handles_no_metadata_no_mtime_change(self):
        before = self.target.stat().st_mtime_ns
        with patch("core.saving.tempfile.mkstemp", side_effect=AssertionError("no temp")), patch(
                "core.saving.os.replace", side_effect=AssertionError("no replace")):
            plan = self.session.prepare({self.path: self.model()})
            self.assertFalse(plan.preview_required)
            self.assertEqual(self.session.commit(plan).status, "unchanged")
        self.assertEqual(before, self.target.stat().st_mtime_ns)
        self.assertFalse((self.root / ".pixorra").exists())
        self.assertTrue(self.prepare().preview_required)

    def test_preview_exact_bytes_commit_history_reopen_and_stale_plan(self):
        before = self.target.read_bytes()
        plan = self.prepare()
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse((self.root / ".pixorra").exists())
        error = self.assert_code("save.preview_required", lambda: self.session.commit(plan))
        self.assertEqual(error.details["preview"]["token"], plan.token)
        self.assertIn('"contentHash"', error.details["preview"]["history"]["diff"])
        self.assert_code("save.preview_required", lambda: self.session.commit(plan, acknowledge_preview="wrong"))
        result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.status, "saved")
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(self.target.read_bytes(), before.replace(b'"density": 1.6', b'"density": 3'))
        history = json.loads((self.root / ".pixorra/state.json").read_bytes())
        self.assertEqual(history["files"][self.path]["contentHash"], sha256(self.target.read_bytes()).hexdigest())
        self.assertFalse(load_project(self.root).acknowledgment_required)
        self.assert_code("save.stale_plan", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.assertFalse(self.session.prepare(self.changed(4)).preview_required)
        self.assertTrue(SaveSession(load_project(self.root)).prepare(self.changed(4)).preview_required)
        self.assertEqual(self.temp_files(), [])

    def test_multiple_top_level_keys_and_frozen_caller_edits(self):
        first = self.prepare()
        self.session.commit(first, acknowledge_preview=first.token)
        model = self.model()
        model["materials"][0]["density"] = 7
        model["palettes"][0]["colors"][0] = "red"
        plan = self.session.prepare({self.path: model})
        self.assertTrue(plan.preview_required)
        self.assertEqual(plan.touched_keys, ((self.path, "materials"), (self.path, "palettes")))
        model["materials"][0]["density"] = 9
        self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(load_project(self.root).resolve("materials", "sand")[0].value["density"], 7)
        self.assertTrue(self.session.prepare({self.path: model}).files)

    def test_conflict_before_temp_and_override_is_hash_scoped(self):
        plan = self.prepare()
        external = self.target.read_bytes() + b" "
        self.target.write_bytes(external)
        observed = sha256(external).hexdigest()
        with patch("core.saving.tempfile.mkstemp", side_effect=AssertionError("no temp")):
            error = self.assert_code("save.conflict", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.assertEqual(error.details["observedHash"], observed)
        self.assertIn("diff", error.details)
        fresh = self.session.prepare(self.changed(), override_hashes={self.path: observed})
        self.assertTrue(fresh.preview_required)
        self.assertEqual(fresh.files[0].original, external)
        self.assertNotEqual(fresh.token, plan.token)
        self.assert_code("save.preview_required", lambda: self.session.commit(fresh, acknowledge_preview=plan.token))
        self.target.write_bytes(external + b"\n")
        self.assert_code("save.conflict", lambda: self.session.commit(fresh, acknowledge_preview=fresh.token))
        self.assertEqual(self.target.read_bytes(), external + b"\n")

    def test_override_success_and_reload_invalidates_plans(self):
        plan = self.prepare()
        self.target.write_bytes(self.target.read_bytes().replace(b'"density": 1.6', b'"density": 88'))
        observed = sha256(self.target.read_bytes()).hexdigest()
        override = self.session.prepare(self.changed(6), override_hashes={self.path: observed})
        self.assertIn('88', override.files[0].diff)
        result = self.session.commit(override, acknowledge_preview=override.token)
        self.assertEqual(result.status, "saved")
        second = self.session.prepare(self.changed(7))
        self.session.reload()
        self.assert_code("save.stale_plan", lambda: self.session.commit(second))
        self.assertEqual(self.model()["materials"][0]["density"], 6)

    def test_structural_errors_block_but_semantic_errors_do_not(self):
        model = self.model()
        model["materials"][0]["density"] = "bad"
        self.assert_code("save.invalid_content", lambda: self.session.prepare({self.path: model}))
        model = self.model()
        model["regions"][0]["materials"][0] = "missing"
        plan = self.session.prepare({self.path: model})
        self.assertEqual(plan.lint.counts["errors"], 1)
        self.assertEqual(self.session.commit(plan, acknowledge_preview=plan.token).status, "saved")

    def test_verification_failure_leaves_original_and_no_temp(self):
        before = self.target.read_bytes()
        with patch("core.saving.verify_edit", side_effect=VerificationError("injected corruption")):
            self.assert_code("save.verification_failed", self.prepare)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.temp_files(), [])

    def test_replace_and_fsync_failure_cleanup_leave_original(self):
        before = self.target.read_bytes()
        for target, code in (("core.saving.os.replace", "save.replace_failed"),
                             ("core.saving.os.fsync", "save.write_failed")):
            with self.subTest(target=target):
                plan = self.prepare()
                with patch(target, side_effect=OSError("injected")):
                    result = self.session.commit(plan, acknowledge_preview=plan.token)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.files[0]["status"], code)
                self.assertEqual(self.target.read_bytes(), before)
                self.assertEqual(self.temp_files(), [])

    def test_final_hash_check_and_temp_verification(self):
        original_mkstemp = saving.tempfile.mkstemp
        external = self.target.read_bytes() + b"\n"

        def race(*args, **kwargs):
            self.target.write_bytes(external)
            return original_mkstemp(*args, **kwargs)

        plan = self.prepare()
        with patch("core.saving.tempfile.mkstemp", side_effect=race):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.files[0]["status"], "save.conflict")
        self.assertEqual(self.target.read_bytes(), external)
        self.assertEqual(self.temp_files(), [])

    def test_corrupt_temp_is_never_replaced(self):
        before = self.target.read_bytes()
        plan = self.prepare()
        read_bytes = Path.read_bytes

        def corrupt_temp(path):
            raw = read_bytes(path)
            return raw + b"corrupt" if path.suffix == ".tmp" else raw

        with patch.object(Path, "read_bytes", corrupt_temp):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.files[0]["status"], "save.verification_failed")
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.temp_files(), [])

    def test_schema_changed_during_temp_write_and_history_conflict(self):
        before = self.target.read_bytes()
        plan = self.prepare()
        mkstemp = saving.tempfile.mkstemp
        schema = self.root / "project.schema.json"

        def race(*args, **kwargs):
            schema.write_bytes(schema.read_bytes() + b" ")
            return mkstemp(*args, **kwargs)

        with patch("core.saving.tempfile.mkstemp", side_effect=race):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.files[0]["status"], "save.schema_changed")
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.temp_files(), [])
        self.session.reload()
        plan = self.prepare()
        state = self.root / ".pixorra/state.json"
        state.parent.mkdir()
        state.write_bytes(b"external")
        self.assert_code("save.conflict", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.assertEqual(self.target.read_bytes(), before)

    def test_new_preparation_invalidates_previous_approval(self):
        first = self.prepare()
        second = self.session.prepare(self.changed(7))
        self.assertNotEqual(first.revision, second.revision)
        self.assert_code("save.stale_plan", lambda: self.session.commit(first, acknowledge_preview=first.token))
        self.assert_code("save.preview_required", lambda: self.session.commit(second, acknowledge_preview=first.token))

    def test_schema_change_and_corrupt_history_acknowledgment(self):
        plan = self.prepare()
        schema = self.root / "project.schema.json"
        schema.write_bytes(schema.read_bytes() + b" ")
        self.assert_code("save.schema_changed", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.session.reload()
        state = self.root / ".pixorra/state.json"
        state.parent.mkdir()
        state.write_bytes(b"broken")
        self.session.reload()
        self.assert_code("save.schema_acknowledgment_required", self.prepare)
        plan = self.prepare(acknowledge_schema=True)
        self.assertEqual(self.session.commit(plan, acknowledge_preview=plan.token).status, "saved")
        self.assertFalse(load_project(self.root).acknowledgment_required)

    def test_history_failure_reports_saved_content_and_retains_baseline(self):
        plan = self.prepare()
        original_replace = saving.os.replace

        def fail_history(source, target):
            if Path(target).name == "state.json":
                raise OSError("history locked")
            return original_replace(source, target)

        with patch("core.saving.os.replace", side_effect=fail_history):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.status, "saved")
        self.assertEqual(result.diagnostics[0]["code"], "save.history_failed")
        self.assertEqual(self.target.read_bytes(), plan.files[0].candidate)
        self.assertEqual(self.session.project.documents[self.path].original, plan.files[0].candidate)
        self.assertEqual(self.temp_files(), [])

    def test_schema_change_after_replace_requires_explicit_reload(self):
        plan = self.prepare()
        original_replace = saving.os.replace
        schema = self.root / "project.schema.json"
        old_schema_hash = self.session.project.schema.document.hash

        def race_after_replace(source, target):
            result = original_replace(source, target)
            if Path(target) == self.target:
                schema.write_bytes(schema.read_bytes() + b" ")
            return result

        with patch("core.saving.os.replace", side_effect=race_after_replace):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.status, "saved")
        self.assertIn("save.reload_required", [d["code"] for d in result.diagnostics])
        self.assertEqual(self.session.project.schema.document.hash, old_schema_hash)
        self.assertEqual(self.session.project.documents[self.path].hash, plan.files[0].candidate_hash)
        self.assert_code("save.reload_required", lambda: self.session.prepare(self.changed(7)))
        self.session.reload()
        self.assertNotEqual(self.session.project.schema.document.hash, old_schema_hash)

    def test_post_replace_sync_failure_is_not_reported_as_rollback(self):
        plan = self.prepare()
        with patch("core.saving._sync_directory", side_effect=OSError("durability uncertain")):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.status, "saved_durability_unknown")
        self.assertEqual(self.target.read_bytes(), plan.files[0].candidate)
        self.assertEqual(self.session.project.documents[self.path].hash, plan.files[0].candidate_hash)

    def test_new_file_and_newly_appeared_destination(self):
        model = self.model()
        self.target.unlink()
        self.session.reload()
        plan = self.session.prepare({self.path: model})
        self.assertIsNone(plan.files[0].source_hash)
        self.target.write_bytes(b"{}")
        self.assert_code("save.conflict", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.target.unlink()
        self.assertEqual(self.session.commit(plan, acknowledge_preview=plan.token).status, "saved")
        self.assertTrue(self.target.read_bytes().endswith(b"\n"))
        self.assertFalse(self.target.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_deleted_loaded_file_blocks(self):
        plan = self.prepare()
        self.target.unlink()
        self.assert_code("save.conflict", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.assertFalse(self.target.exists())

    def test_symlink_destination_refused(self):
        alternate = self.root / "alternate.json"
        alternate.write_bytes(self.target.read_bytes())
        self.target.unlink()
        try:
            self.target.symlink_to(alternate)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        self.assert_code("save.path_invalid", self.prepare)


class BatchTests(ProjectCase):
    def split_files(self):
        schema_path = self.root / "project.schema.json"
        schema = json.loads(schema_path.read_bytes())
        model = json.loads(self.target.read_bytes())
        for name, binding in schema["x-pixorra"]["bindings"].items():
            binding["path"] = f"data/{name}.json"
            write_json(self.root / binding["path"], {name: model[name]})
        write_json(schema_path, schema)
        self.session = SaveSession(load_project(self.root))
        targets = {p: deepcopy(d.root.value) for p, d in self.session.project.documents.items()}
        targets["data/materials.json"]["materials"][0]["density"] = 5
        targets["data/palettes.json"]["palettes"][0]["colors"][0] = "red"
        return targets

    def test_batch_preflight_stops_all_writes(self):
        targets = self.split_files()
        plan = self.session.prepare(targets)
        before = (self.root / "data/materials.json").read_bytes()
        (self.root / "data/palettes.json").write_bytes(b"external")
        self.assert_code("save.conflict", lambda: self.session.commit(plan, acknowledge_preview=plan.token))
        self.assertEqual((self.root / "data/materials.json").read_bytes(), before)

    def test_partial_batch_history_only_records_committed_files(self):
        targets = self.split_files()
        plan = self.session.prepare(targets)
        original_replace = saving.os.replace
        unchanged = (self.root / "data/palettes.json").read_bytes()

        def fail_second(source, target):
            if Path(target).name == "palettes.json":
                raise OSError("locked")
            return original_replace(source, target)

        with patch("core.saving.os.replace", side_effect=fail_second):
            result = self.session.commit(plan, acknowledge_preview=plan.token)
        self.assertEqual(result.status, "partial")
        self.assertEqual([r["status"] for r in result.files], ["saved", "save.replace_failed"])
        history = json.loads((self.root / ".pixorra/state.json").read_bytes())
        self.assertEqual(list(history["files"]), ["data/materials.json"])
        self.assertEqual((self.root / "data/palettes.json").read_bytes(), unchanged)
        pending = self.session.prepare(targets)
        self.assertEqual([f.path for f in pending.files], ["data/palettes.json"])
        self.assertEqual(self.temp_files(), [])


class LintTests(ProjectCase):
    def test_large_palette_index_reports_without_integer_string_limits(self):
        self.target.write_bytes(self.target.read_bytes().replace(b'"color": 0', b'"color": 1e5000'))
        report = lint_project(load_project(self.root)).to_dict()
        self.assertEqual(report["diagnostics"][0]["details"]["index"], "1E+5000")
        json.dumps(report)

    def test_shared_golden_reports(self):
        cases = json.loads((ROOT / "spec/fixtures/lint/mvp.json").read_bytes())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                schema = json.loads((SAMPLE / "project.schema.json").read_bytes())
                content = json.loads((SAMPLE / self.path).read_bytes())
                for change in case["input"].get("schemaEdits", []):
                    edit(schema, change["pointer"], change["value"])
                for change in case["input"].get("contentEdits", []):
                    edit(content, change["pointer"], change["value"])
                # Fixture text is explicitly LF on every host; hashes/spans are portable.
                (self.root / "project.schema.json").write_bytes((json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode())
                self.target.write_bytes((json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode())
                write_json(self.root / ".pixorra/project.json", {"configVersion": 1,
                           "disabledRules": case["input"].get("disabledRules", [])})
                report = lint_project(load_project(self.root)).to_dict()
                self.assertEqual(report, case["expect"])

    def test_disabling_l14_does_not_disable_save_validation(self):
        write_json(self.root / ".pixorra/project.json", {"configVersion": 1, "disabledRules": ["L-14"]})
        self.session.reload()
        model = self.model()
        model["materials"][0]["density"] = False
        self.assert_code("save.invalid_content", lambda: self.session.prepare({self.path: model}))

    def test_cli_lint_is_readonly_and_reports_counts(self):
        before = self.target.read_bytes()
        result = subprocess.run([sys.executable, "-m", "core", str(self.root), "--lint"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["lint"]["counts"]["errors"], 0)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse((self.root / ".pixorra/state.json").exists())


if __name__ == "__main__":
    unittest.main()
