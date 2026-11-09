import { useEffect, useState } from "react";
import { useStore } from "./store";
import Graph from "./graphview";
import Inspector from "./inspector";

function LintPanel() {
  const { lint, snapshot, select } = useStore();
  const [open, setOpen] = useState(true);
  const counts = lint?.counts ?? { errors: 0, warnings: 0, hints: 0, infos: 0, unknowns: 0 };
  const diagnostics = lint?.diagnostics ?? [];
  const disabled = lint?.disabledRules ?? [];

  const focus = (path: string, pointer: string) => {
    // Jump to the node: resolve the pointer id and select it if it is authored.
    try {
      const id = String(pointer).split("/").pop() ?? "";
      const snapshotData = useStore.getState().snapshot;
      const entity = snapshotData?.entities.find(
        (e) => e.id === id
      );
      if (entity) select(entity.kind, entity.id);
    } catch {
      void path;
    }
  };

  return (
    <div className="lint">
      <div className="counts">
        <strong style={{ color: "var(--err)" }}>Lint (on demand / on save)</strong>
        <span>{counts.errors} errors</span>
        <span>{counts.warnings} warnings</span>
        <span>{counts.hints} hints</span>
        <span>{counts.infos} infos</span>
        <span style={{ color: "var(--muted)" }}>{counts.unknowns} unknown</span>
        <button style={{ padding: "1px 8px", fontSize: 11 }} onClick={() => setOpen(!open)}>
          {open ? "hide" : "show"}
        </button>
      </div>
      {open && (
        <>
          {disabled.length > 0 && (
            <div className="d sev-unknown">
              Disabled rules: {disabled.join(", ")}
            </div>
          )}
          {snapshot?.diagnostics?.length ? (
            snapshot.diagnostics.map((d: any, i: number) => (
              <div key={`ld${i}`} className={`d sev-${d.severity}`}>
                schema {d.rule ?? "-"} {d.code} @ {d.location?.path}
                {d.location?.pointer} — {d.message}
              </div>
            ))
          ) : null}
          {diagnostics.length === 0 && counts.errors === 0 && counts.warnings === 0 && counts.hints === 0 && counts.unknowns === 0 && (
            <div className="d sev-info">No lint outcomes.</div>
          )}
          {diagnostics.map((d: any, i: number) => (
            <div
              key={i}
              className={`d sev-${d.outcome === "unknown" ? "unknown" : d.severity}`}
              style={{ cursor: "pointer" }}
              onClick={() => focus(d.location?.path ?? "", d.location?.pointer ?? "")}
              title="Click to focus the related node"
            >
              [{d.rule ?? "-"}] {d.severity}
              {d.outcome === "unknown" ? "/unknown" : ""} {d.code} @ {d.location?.path}
              {d.location?.pointer} — {d.message}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function SavePreviewModal() {
  const { plan, commit } = useStore();
  if (!plan) return null;
  return (
    <div className="modal">
      <div className="panel">
        <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>Save preview (required)</h3>
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
          {plan.previewRequired
            ? "This save touches multiple top-level keys (or a first/override save) — reviewing the diff is mandatory."
            : "Minimal single-key change; committing without preview."}
        </div>
        {plan.files.map((f) => (
          <pre key={f.path}>
            <b>{f.path}</b>
            {"\n"}
            {f.diff}
          </pre>
        ))}
        {plan.history && (
          <pre style={{ color: "var(--warn)" }}>
            <b>{plan.history.path} (history)</b>
            {"\n"}
            {plan.history.diff}
          </pre>
        )}
        <div style={{ fontSize: 11, color: "var(--muted)" }}>
          Lint at save: {plan.lint.counts.errors} errors, {plan.lint.counts.warnings} warnings,{" "}
          {plan.lint.counts.hints} hints, {plan.lint.counts.unknowns} unknown.
        </div>
        <div className="row">
          <button
            onClick={() => useStore.setState({ plan: null, status: "Save cancelled" })}
          >
            Cancel
          </button>
          <button
            onClick={() => commit(plan.previewRequired)}
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            {plan.previewRequired ? "Accept and save" : "Commit"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const {
    folder,
    snapshot,
    dirty,
    status,
    error,
    plan,
    open,
    undo,
    redo,
    prepare,
    runLint,
    reload,
    refresh,
  } = useStore();
  const [folderInput, setFolderInput] = useState("");

  useEffect(() => {
    void refresh().catch(() => undefined);
  }, []);

  const canUndo = useStore.getState().undoStack.length > 0;
  void canUndo;

  return (
    <div className="app">
      <div className="topbar">
        <strong style={{ marginRight: 8 }}>Pixorra</strong>
        <input
          placeholder="Project folder, e.g. D:\\ambient\\craa\\pixorra\\examples\\falling-sand"
          value={folderInput}
          onChange={(e) => setFolderInput(e.target.value)}
        />
        <button onClick={() => open(folderInput.trim())}>Open</button>
        <span className={`dirty ${dirty ? "on" : ""}`}>
          {dirty ? "● unsaved changes" : "no changes"}
        </span>
        <button disabled={!dirty} onClick={() => prepare()}>
          Save…
        </button>
        <button onClick={() => runLint()}>Lint</button>
        <button onClick={() => reload()}>Reload disk</button>
        <button style={{ marginLeft: 4 }} onClick={undo}>
          Undo
        </button>
        <button onClick={redo}>Redo</button>
        {error ? <span className="errorbanner">{error}</span> : null}
        <span className="status">{status ?? ""}</span>
      </div>

      <div className="browser">
        {snapshot?.categories.map((cat) => (
          <div key={cat.kind}>
            <h4>{cat.name}</h4>
            {snapshot.entities
              .filter((e) => e.kind === cat.kind)
              .map((e) => (
                <div
                  key={e.id}
                  className="item"
                  onClick={() => useStore.getState().select(cat.kind, e.id)}
                >
                  {cat.kind === "materials" ? (
                    <NodeSwatch entity={e} />
                  ) : null}
                  {e.id}
                </div>
              ))}
          </div>
        ))}
        {!snapshot && (
          <p style={{ fontSize: 12, color: "var(--muted)" }}>
            Open a Pixorra project folder to browse materials, palettes,
            reactions, spawn rules and regions.
          </p>
        )}
      </div>

      <Graph />

      <Inspector />

      <LintPanel />

      <SavePreviewModal />
    </div>
  );
}

function NodeSwatch({ entity }: { entity: any }) {
  const color = useStore((s) => {
    const cat = (s.snapshot?.categories ?? []).find((c) => c.kind === "materials");
    const key = cat?.path ?? "";
    const model = s.model?.[key];
    if (!Array.isArray(model)) return null;
    const material = model.find((m: any) => m.id === entity.id);
    if (!material) return null;
    const palettes = s.model?.[(s.snapshot?.categories ?? []).find((c) => c.kind === "palettes")?.path ?? ""];
    const palette = (Array.isArray(palettes) ? palettes : []).find(
      (p: any) => p.id === material.palette
    );
    return palette?.colors?.[material.color ?? 0] ?? null;
  });
  return color ? <span className="sw" style={{ background: color, display: "inline-block", width: 10, height: 10, borderRadius: 2, marginRight: 6 }} /> : null;
}
