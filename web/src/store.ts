import { create } from "zustand";
import { apiGet, apiPost } from "./api";

export interface Entity {
  kind: string;
  category: string;
  id: string;
  nodeId: string;
  value: Record<string, unknown>;
  location: { path: string; pointer: string };
}

export interface CategoryInfo {
  name: string;
  kind: string;
  path: string;
  pointer: string;
  schema: any;
  annotation: any;
  entities: string[];
}

export interface Snapshot {
  root: string;
  schema: any;
  categories: CategoryInfo[];
  entities: Entity[];
  references: any[];
  diagnostics: any[];
  disabledRules: string[];
  hasErrors: boolean;
  files: Record<string, any>;
}

export interface LintReport {
  reportVersion: number;
  schema: any;
  disabledRules: string[];
  counts: {
    errors: number;
    warnings: number;
    hints: number;
    infos: number;
    unknowns: number;
  };
  diagnostics: any[];
}

export interface PlanPreview {
  token: string;
  previewRequired: boolean;
  files: { path: string; diff: string; byteMetadata: any; candidateHash: string }[];
  touchedKeys: { path: string; topKey: string }[];
  lint: LintReport;
  history?: { path: string; diff: string } | null;
}

interface EditorStore {
  folder: string | null;
  snapshot: Snapshot | null;
  lint: LintReport | null;
  model: Record<string, any> | null;
  dirty: boolean;
  selected: { kind: string; id: string } | null;
  plan: PlanPreview | null;
  error: string | null;
  status: string | null;
  positions: Record<string, { x: number; y: number }>;
  undoStack: Record<string, any>[];
  redoStack: Record<string, any>[];

  open: (folder: string) => Promise<void>;
  applyModel: (mutate: (world: any, files: Record<string, any>) => void) => void;
  undo: () => void;
  redo: () => void;
  select: (kind: string, id: string) => void;
  refresh: () => Promise<void>;
  runLint: () => Promise<void>;
  prepare: () => Promise<void>;
  commit: (acknowledgePreview: boolean) => Promise<void>;
  reload: () => Promise<void>;
  setPosition: (id: string, pos: { x: number; y: number }) => void;
  setStatus: (s: string | null) => void;
}

function primaryPath(snapshot: Snapshot): string {
  const mats = snapshot.categories.find((c) => c.kind === "materials");
  return mats ? mats.path : Object.keys(snapshot.files)[0] ?? "";
}

export const useStore = create<EditorStore>((set, get) => ({
  folder: null,
  snapshot: null,
  lint: null,
  model: null,
  dirty: false,
  selected: null,
  plan: null,
  error: null,
  status: null,
  positions: {},
  undoStack: [],
  redoStack: [],

  open: async (folder) => {
    set({ status: `Opening ${folder}…`, error: null, plan: null });
    const data = await apiPost<{ snapshot: Snapshot; lint: LintReport; error?: any }>(
      "/api/open",
      { folder }
    );
    if (data.error) {
      set({ error: JSON.stringify(data.error), status: "Open failed" });
      return;
    }
    const entityPos: Record<string, { x: number; y: number }> = {};
    const materials = data.snapshot.entities.filter((e) => e.kind === "materials");
    const reactions = data.snapshot.entities.filter((e) => e.kind === "reactions");
    materials.forEach((e, i) => (entityPos[e.id] = { x: 40, y: 40 + i * 110 }));
    reactions.forEach((e, i) => (entityPos[e.id] = { x: 420, y: 60 + i * 140 }));
    set({
      folder,
      snapshot: data.snapshot,
      lint: data.lint,
      model: deepCopy(data.snapshot.files),
      dirty: false,
      selected: null,
      plan: null,
      positions: entityPos,
      undoStack: [],
      redoStack: [],
      status: `Opened ${folder}`,
    });
  },

  applyModel: (mutate) => {
    const { model, snapshot, undoStack } = get();
    if (!model) return;
    pushUndo(set, undoStack, model);
    const next = deepCopy(model);
    mutate(next, snapshot ?? { files: {} } as unknown as Snapshot);
    set({ model: next, dirty: true, plan: null });
  },

  undo: () => {
    const { undoStack, redoStack, model } = get();
    const prev = undoStack.pop();
    if (!prev || !model) return;
    set({
      model: prev.value,
      undoStack: [...undoStack],
      redoStack: [...redoStack, { value: model }],
      dirty: true,
      selected: null,
      plan: null,
    });
  },

  redo: () => {
    const { undoStack, redoStack, model } = get();
    const next = redoStack.pop();
    if (!next || !model) return;
    set({
      model: next.value,
      undoStack: [...undoStack, { value: model }],
      redoStack: [...redoStack],
      dirty: true,
      selected: null,
      plan: null,
    });
  },

  select: (kind, id) => set({ selected: { kind, id } }),

  refresh: async () => {
    const data = await apiGet<{ snapshot: Snapshot; lint: LintReport; code?: string }>(
      "/api/project"
    );
    if (data.code === "project.not_open") {
      set({ status: "No project open — use Open" });
      return;
    }
    const { model } = get();
    const entityPos: Record<string, { x: number; y: number }> = {};
    data.snapshot.entities
      .filter((e) => e.kind === "materials" || e.kind === "reactions")
      .forEach((e, i) => (entityPos[e.id] = { x: e.kind === "materials" ? 40 : 420, y: 40 + i * 110 }));
    set({ snapshot: data.snapshot, lint: data.lint, positions: entityPos });
    if (!get().dirty || !model) set({ model: deepCopy(data.snapshot.files), dirty: false });
  },

  runLint: async () => {
    const data = await apiPost<{ lint: LintReport }>("/api/lint");
    set({ lint: data.lint, status: "Lint refreshed (lint is on demand or at save)" });
  },

  prepare: async () => {
    const { model } = get();
    if (!model) return;
    set({ status: "Preparing save preview…", error: null });
    const data = await apiPost<{ plan?: PlanPreview; error?: any }>("/api/prepare", {
      models: model,
    });
    if (data.error) {
      if (data.error.code === "save.schema_acknowledgment_required") {
        // Retry once with schema acknowledgment (editor surfaces it).
        const retry = await apiPost<{ plan?: PlanPreview; error?: any }>(
          "/api/prepare",
          { models: model, acknowledgeSchema: true }
        );
        if (retry.plan) {
          set({ plan: retry.plan, status: "Schema/history reset acknowledged; preview ready" });
          return;
        }
        set({ error: JSON.stringify(retry.error), status: "Prepare failed" });
        return;
      }
      set({ error: JSON.stringify(data.error), status: "Prepare failed" });
      return;
    }
    set({ plan: data.plan ?? null, status: "Preview ready" });
  },

  commit: async (acknowledgePreview) => {
    const { plan } = get();
    if (!plan) return;
    set({ status: "Saving…", error: null });
    const data = await apiPost<{ result?: any; error?: any; snapshot?: Snapshot; lint?: LintReport }>(
      "/api/commit",
      { token: plan.token, acknowledgePreview }
    );
    if (data.error) {
      set({ error: JSON.stringify(data.error), status: "Save blocked" });
      return;
    }
    const result = data.result;
    set({
      plan: null,
      lint: data.lint ?? get().lint,
      snapshot: data.snapshot ?? get().snapshot,
      model: data.snapshot ? deepCopy(data.snapshot.files) : get().model,
      dirty: false,
      undoStack: [],
      redoStack: [],
      status: `Save ${result?.status ?? "done"}`,
    });
  },

  reload: async () => {
    const data = await apiPost<{ snapshot?: Snapshot; lint?: LintReport; error?: any }>(
      "/api/reload"
    );
    if (data.error) {
      set({ error: JSON.stringify(data.error), status: "Reload failed" });
      return;
    }
    set({
      snapshot: data.snapshot ?? null,
      lint: data.lint ?? null,
      model: data.snapshot ? deepCopy(data.snapshot.files) : null,
      dirty: false,
      undoStack: [],
      redoStack: [],
      plan: null,
      status: "Reloaded from disk",
    });
  },

  setPosition: (id, pos) =>
    set((s) => ({ positions: { ...s.positions, [id]: pos } })),

  setStatus: (status) => set({ status }),
}));

function pushUndo(
  set: any,
  undoStack: Record<string, any>[],
  model: Record<string, any> | null
) {
  if (model) set({ undoStack: [...undoStack.slice(-25), { value: deepCopy(model) }], redoStack: [] });
}

export function deepCopy<T>(value: T): T {
  return value === undefined ? value : JSON.parse(JSON.stringify(value));
}
