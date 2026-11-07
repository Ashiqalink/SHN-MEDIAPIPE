<<<<<<< HEAD
# Pixorra

A standalone, local authoring and linting tool for game JSON. Product scope is
in [the PRD](docs/PRD.md); delivery order is in [PLAN.md](PLAN.md).

Phases 0, 1 and 2 are complete: contracts, a headless project loader, verified
minimal-diff saves and the MVP lint rules are available. The graph editor,
remaining lint rules and simulator arrive in later phases.

- [Decisions and compatibility policy](docs/decisions.md)
- [Schema and project contract](docs/schema-contract.md)
- [Ordered model, references, and diagnostics](docs/model-contract.md)
- [Expressions, randomness, and shared transitions](docs/evaluation-contract.md)
- [Verified saves and conflict handling](docs/save-contract.md)
- [Save API and failure handling](docs/saving.md)
- [MVP lint rules and examples](docs/lint.md)
- [Fixture format and acceptance matrix](spec/README.md)
- [Current progress](PROGRESS.md)

No dependency on any surrounding game project is permitted. Python 3.11+ is the
first implementation target; later backends must pass the same shared fixtures.

Install from this directory with `python -m pip install -e .`. The only runtime
dependency is `jsonschema` 4.x; no FastAPI or frontend packages are needed.

```text
python -m core examples/falling-sand
python -m core examples/falling-sand --lint
python -m unittest discover -s tests -v
```

The installed `pixorra <folder> [--schema relative/path.schema.json]` command
prints deterministic JSON containing schema identity/hash, files, entities,
resolved/missing/ambiguous references, diagnostics, and schema acknowledgment
state. Add `--lint` for L-1, L-3, L-5 and L-14 with separate severity/unknown
counts and disabled rules. It exits 1 on structural or enabled lint errors,
0 otherwise. Inspection and lint write no files. New projects report
informational `schema.history_missing` until their first mutating save.

For scripts:

```python
from core import load_project

project = load_project("examples/falling-sand")
material = project.resolve("materials", "water")[0]
source = project.documents[material.location.path]
print(material.id, source.hash, material.location.span)
```

Invalid schemas/configuration raise `LoadError` with portable diagnostics. Invalid
content returns an inspectable snapshot with `has_errors`, diagnostics, and
original `raw_files`, including bytes that failed parsing. Treat snapshots as
read-only. Call `lint_project(project)` for semantic lint; loading alone retains
the structural diagnostics and reference index. `SaveSession(project)` prepares
frozen, verified edits, exposes required previews and commits approved plans.
See [the save API](docs/saving.md) for acknowledgment and conflict handling.
=======
# SHN-MEDIAPIPE
![Project Cover](assets/cover.jpeg)
#  Pixorra

### 💡 What's the idea?
Pixorra is a local tool for authoring and checking the JSON behind voxel-and-pixel games. Materials, reactions, spawn rules, regions, and quests are edited as visual node graphs and saved in the game’s own JSON files.

Its linter catches broken references, such as misspelled material IDs and out-of-range palette indices, before the game runs. It also flags orphaned materials, reaction cycles, and dead-end quest stages.

The tool is schema-driven. Saves preserve unchanged content byte-for-byte, and the core runs headlessly for scripts, CI, and seeded batch simulations.

### 🌐 Check it out!
- **Live Website:** [Drop your link here / N/A]
- **GitHub Repo:** https://github.com/Ashiqalink/SHN-MEDIAPIPE

### 🛠️ What did you use?
[Tech stack, tools, frameworks, libraries, etc.]

### 👥 The Humans Behind It
- Ashiq Ali N K

### ⚙️ Hardware Corner
[What hardware did you use? / N/A]

### 📸 Show Us What You Built!
[Add screenshots, photos, GIFs or demo video links here.]

### ✨ Cool Things It Does
- [Feature 1]
- [Feature 2]
- [Feature 3]

---

**Built with curiosity at Saturday Hack Night 💜**# 🚀 [Your Project Name]

### 💡 What's the idea?
[Tell us what you built and what it does. Keep it short!]

### 🌐 Check it out!
- **Live Website:** [Drop your link here / N/A]
- **GitHub Repo:** [Drop your repository link here]

### 🛠️ What did you use?
[Tech stack, tools, frameworks, libraries, etc.]

### 👥 The Humans Behind It
- [Name – GitHub Username]
- [Name – GitHub Username]

### ⚙️ Hardware Corner
[What hardware did you use? / N/A]

### 📸 Show Us What You Built!
[Add screenshots, photos, GIFs or demo video links here.]

### ✨ Cool Things It Does
- [Feature 1]
- [Feature 2]
- [Feature 3]

---

**Built with curiosity at Saturday Hack Night 💜**
>>>>>>> 1f6475faefb95ce03dcf3af4fd05c2c2ecd6f446
