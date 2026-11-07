# Phase 0 decisions

Status: accepted for contract version `1.0.0`, 2026-11-07. These decisions resolve
PRD Section 14. Changing observable behavior requires changing the contract and
its fixtures together; no runtime implementation is implied by this document.

| ID | Decision | Reason and consequence |
|---|---|---|
| D-01 | Pixorra is the product name. | Package registries and trademark availability have **not** been checked. Check before release; do not claim availability. |
| D-02 | Use JSON Schema Draft 2020-12 plus a closed, versioned `x-pixorra` annotation namespace. | Reuse standard data validators and editor tooling; Pixorra separately validates its annotations. A generic validator alone cannot certify a Pixorra schema. |
| D-03 | Python 3.11+ is the authoritative first backend. | Core imports no server/UI/game modules. Do not build a second backend, engine port, or WebAssembly target in v1. A future port must pass the shared fixtures before claiming compatibility. |
| D-04 | `random(p)` is legal in declared reaction and quest expression fields, including those linted statically. | Static analysis never consumes a seed. Nonconstant probability yields unknown; simulation evaluates with explicit RNG state. See the endpoint exceptions in the evaluation contract. |
| D-05 | Use PCG32 XSH-RR, 64-bit state, 32-bit output, explicit stream and seed. | Host-language RNGs are forbidden. Exact integer sampling, traversal order, and branch snapshots are part of the contract. |
| D-06 | JSON and expression numbers are exact finite base-10 values. | No implicit binary float rounding, coercion, NaN, infinity, or host truthiness. Preserve original number spellings independently from semantic values. |
| D-07 | Static reachability and simulation call the same pure transition kernel. | Static mode supplies abstract values and branches on unknown guards. Simulation supplies concrete values and RNG state. There is no second graph-only reaction evaluator. |
| D-08 | Keep schema save history outside game JSON in `.pixorra/state.json`. | Games retain their own format. Sidecar state is optional editor metadata, never a requirement for loading game content. Hash it and save it safely too. |
| D-09 | Saves are verified, per-file atomic, hash guarded, and preview gated. | There is no portable multi-file atomic rename. Report partial batch success explicitly; never claim a transaction across files. |
| D-10 | The quest reference project includes a small material/reaction module. | L-7 remains a material/reaction cycle check. Quest loops alone do not trigger it. The sample includes two looping reactions, a guarded exit, and unknown-guard variants, alongside L-8–L-11 quest cases. |

JSON Schema annotations are a deliberate extension profile, not a claim that a
formal required `$vocabulary` has been registered. Ordinary validators may ignore
extension keywords; Pixorra must reject unknown annotations and unsupported
contract versions before opening an editable project. This follows the
[Draft 2020-12 core specification](https://json-schema.org/draft/2020-12/json-schema-core).
The exact supported profile is in [schema-contract.md](schema-contract.md).

The PCG choice follows the author's
[minimal generator API and test sequence](https://www.pcg-random.org/using-pcg-c-basic.html)
and [reference implementation](https://github.com/imneme/pcg-c-basic/blob/master/pcg_basic.c).
The algorithm and project-specific draw rules are in
[evaluation-contract.md](evaluation-contract.md). These links are references,
not dependencies fetched while loading a project.

Phase 0 completion means specifications, golden contract data, and acceptance
criteria have been recorded and checked for consistency. Runtime acceptance,
cross-platform determinism, and all product success metrics remain future work.
