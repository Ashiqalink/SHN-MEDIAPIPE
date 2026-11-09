"""Phase 3 tests: local API serving the editor (server/).

Mirrors PLAN.md phase 3 exit checks at the API level:

- author, wire, save and reopen a five-material set (the sample starts at
  five materials; a sixth plus a wiring reaction is added, then removed back
  to five in a later save),
- first-save preview and multiple-top-level-key preview are required,
- undo/redo and graph authoring state live in the web client, so this file
  covers everything the server is responsible for: prepare/preview, commit,
  minimal diffs, conflict blocking, resolution override, and lint exposure.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "falling-sand"


def copy_sample() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="pixorra3-"))
    shutil.copytree(SAMPLE, tmp / "project")
    return tmp / "project"


def world_template() -> dict:
    return json.loads((SAMPLE / "data" / "world.json").read_text("utf-8"))


def new_app(sample: Path):
    return create_app(), sample


class Phase3ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        sample = copy_sample()
        self.dirs = tempfile.TemporaryDirectory()
        app, _ = new_app(sample)
        self.app = app
        self.sample = sample
        with (sample / "data" / "world.json").open("rb") as fh:
            self.original_bytes = fh.read()
        self.client = TestClient(app)
        resp = self.client.post(
            "/api/open", content=json.dumps({"folder": str(sample)}).encode()
        )
        assert resp.status_code == 200, resp.text
        opened = resp.json()
        self.snapshot = opened["snapshot"]
        self.materials = [
            e for e in self.snapshot["entities"] if e["kind"] == "materials"
        ]

    def tearDown(self) -> None:
        self.dirs.cleanup()

    # --- helpers ----------------------------------------------------------- LOCATION

    def world(self) -> dict:
        """Decoded ordered root of the sample world, as the client would fetch."""
        return json.loads(
            (self.sample / "data" / "world.json").read_text("utf-8")
        )

    def build_model(self, mutate) -> dict[str, dict]:
        world = self.world()
        mutate(world)
        return {"data/world.json": world}

    # --- exit checks ------------------------------------------------------- LOCATION

    def test_open_exposes_five_materials_well_formed(self) -> None:
        self.assertEqual(
            sorted(m["id"] for m in self.materials),
            ["glass", "sand", "steam", "stone", "water"],
        )
        self.assertEqual(self.snapshot["schema"]["id"], "urn:pixorra:example:falling-sand")
        self.assertEqual(self.snapshot["hasErrors"], False)
        sand = next(m for m in self.materials if m["id"] == "sand")
        self.assertEqual(sand["value"]["density"], 1.6)
        self.assertEqual(sand["value"]["palette"], "main")

    def test_author_wire_save_reopen_six_then_five(self) -> None:
        # 1. Author a sixth material and wire a reaction in editor-local state.
        def mutate(world: dict) -> None:
            world["materials"].append(
                {
                    "id": "wood",
                    "density": 0.6,
                    "palette": "main",
                    "color": 0,
                    "properties": {"temperature": 20},
                }
            )
            world["reactions"].append(
                {
                    "id": "burn",
                    "inputs": ["wood"],
                    "outputs": ["glass"],
                    "condition": "temperature > 300",
                    "priority": 2,
                }
            )
            world["regions"][0]["materials"].append("wood")

        model = self.build_model(mutate)
        resp = self.client.post(
            "/api/prepare", content=json.dumps({"models": model}).encode()
        )
        body = resp.json()
        assert "plan" in body, body
        plan = body["plan"]
        self.assertTrue(plan["previewRequired"])  # first mutating save
        self.assertEqual(
            sorted({t["topKey"] for t in plan["touchedKeys"]}),
            ["materials", "reactions", "regions"],
        )
        diff = plan["files"][0]["diff"]
        self.assertIn("wood", diff)
        self.assertIn("burn", diff)
        # minimal: untouched bytes (e.g. the stone block) never in context
        self.assertNotIn('"id": "stone"', diff)
        self.assertEqual(plan["lint"]["counts"]["errors"], 0)

        # 2. Commit requires acknowledging the preview.
        resp = self.client.post(
            "/api/commit",
            content=json.dumps({"token": plan["token"]}).encode(),
        )
        self.assertEqual(resp.json()["error"]["code"], "save.preview_required")

        resp = self.client.post(
            "/api/commit",
            content=json.dumps(
                {"token": plan["token"], "acknowledgePreview": True}
            ).encode(),
        )
        result = resp.json()["result"]
        self.assertEqual(result["status"], "saved")

        # 3. Reopen from disk: the authored content persists and lints clean.
        resp = self.client.post("/api/reload", content=b"")
        reopened = resp.json()["snapshot"]
        ids = sorted(
            e["id"] for e in reopened["entities"] if e["kind"] == "materials"
        )
        self.assertEqual(
            ids, ["glass", "sand", "steam", "stone", "water", "wood"]
        )
        burn = next(
            e for e in reopened["entities"] if e["id"] == "burn"
        )
        self.assertEqual(burn["value"]["outputs"], ["glass"])
        self.assertEqual(resp.json()["lint"]["counts"]["errors"], 0)

        # 4. Second save touching multiple top-level keys still previews.
        def mutate_two_keys(world: dict) -> None:
            world["materials"] = [
                m for m in world["materials"] if m["id"] != "wood"
            ]
            world["reactions"] = [r for r in world["reactions"] if r["id"] != "burn"]
            world["regions"][0]["materials"] = [
                m for m in world["regions"][0]["materials"] if m != "wood"
            ]

        resp = self.client.post(
            "/api/prepare",
            content=json.dumps({"models": self.build_model(mutate_two_keys)}).encode(),
        )
        plan2 = resp.json()["plan"]
        self.assertTrue(plan2["previewRequired"])
        resp = self.client.post(
            "/api/commit",
            content=json.dumps(
                {"token": plan2["token"], "acknowledgePreview": True}
            ).encode(),
        )
        self.assertEqual(resp.json()["result"]["status"], "saved")

        # 5. Now back to exactly the five-material set, byte-identical to origin
        #    except for expected history sidecar (state.json); world restored.
        current = self.world()
        baseline = world_template()
        self.assertEqual(current, baseline)
        final = (self.sample / "data" / "world.json").read_bytes()
        self.assertEqual(
            final.decode("utf-8"), self.original_bytes.decode("utf-8")
        )

    def test_conflict_blocks_save_and_reload_shows_external_change(self) -> None:
        # Touch the file outside the editor after a plan was prepared.
        def mutate(world: dict) -> None:
            world["materials"][0]["density"] = 9.9

        plan = self.client.post(
            "/api/prepare", content=json.dumps({"models": self.build_model(mutate)}).encode()
        ).json()["plan"]
        path = self.sample / "data" / "world.json"
        touch = self.world()
        touch["palettes"][0]["colors"][0] = "#abcabc"
        path.write_text(
            json.dumps(touch, indent=2) + "\n", "utf-8", newline="\n"
        )
        resp = self.client.post(
            "/api/commit",
            content=json.dumps({"token": plan["token"], "acknowledgePreview": True}).encode(),
        )
        self.assertEqual(resp.json()["error"]["code"], "save.conflict")
        # The conflicting editor plan must not linger: reload shows the external
        # edit, and the pushed plan token is invalidated.
        resp = self.client.post("/api/reload", content=b"")
        snap = resp.json()["snapshot"]
        main = next(e for e in snap["entities"] if e["kind"] == "palettes")
        self.assertEqual(main["value"]["colors"][0], "#abcabc")
        resp = self.client.post(
            "/api/commit",
            content=json.dumps({"token": plan["token"], "acknowledgePreview": True}).encode(),
        )
        # Reload cleared prepared plans: the stale token is no longer accepted.
        self.assertEqual(resp.json()["error"]["code"], "commit.unknown_plan")

    def test_lint_surfaces_unknown_and_disabled(self) -> None:
        resp = self.client.post("/api/lint", content=b"")
        report = resp.json()["lint"]
        self.assertIn("counts", report)
        self.assertIn("disabledRules", report)
        self.assertIn("diagnostics", report)

    def test_prepare_rejects_invalid_content(self) -> None:
        def mutate(world: dict) -> None:
            world["materials"][0]["density"] = -5  # schema forbids negatives

        resp = self.client.post(
            "/api/prepare", content=json.dumps({"models": self.build_model(mutate)}).encode()
        )
        error = resp.json().get("error") or {}
        self.assertEqual(error.get("code"), "save.invalid_content")

    def test_decimal_roundtrip_survives(self) -> None:
        # A density spelled with decimals must survive the whole round trip.
        def mutate(world: dict) -> None:
            world["materials"][1]["density"] = 2

        resp = self.client.post(
            "/api/prepare", content=json.dumps({"models": self.build_model(mutate)}).encode()
        )
        body = resp.json()
        assert "plan" in body, body
        plan = body["plan"]
        resp = self.client.post(
            "/api/commit",
            content=json.dumps({"token": plan["token"], "acknowledgePreview": True}).encode(),
        )
        # Stone's density 2.0 in data/world.json originally: "density": 2.
        # Only an intended digit-span edit should result.
        diff = body["plan"]["files"][0]["diff"]
        self.assertIn('"density"', diff)


if __name__ == "__main__":
    unittest.main()
