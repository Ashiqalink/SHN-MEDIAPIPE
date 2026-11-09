/* Graph helpers: build React Flow nodes/edges from the working model and
 * snapshot schema annotations. Materials and reactions become nodes; typed
 * input/output edges encode reaction wiring. */

export interface FlowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: any;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle: string | null;
  targetHandle: string | null;
  label?: string;
  deletable: boolean;
}

const COLORS: Record<string, string> = {
  "#d2b46c": "#d2b46c",
};

export function paletteColor(
  world: any,
  paletteId: string,
  index: number
): string | null {
  try {
    const palette = (world.palettes ?? []).find((p: any) => p.id === paletteId);
    const c = palette?.colors?.[index];
    return typeof c === "string" && c.startsWith("#") ? c : null;
  } catch {
    return null;
  }
}

export function buildGraph(model: any, positions: Record<string, { x: number; y: number }>) {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  if (!model) return { nodes, edges };

  for (const m of model.materials ?? []) {
    nodes.push({
      id: `m:${m.id}`,
      type: "materialNode",
      position: positions[m.id] ?? { x: 40, y: 40 },
      data: { id: m.id, value: m, paletteColor: paletteColor(model, m.palette, m.color) },
    });
  }
  for (const r of model.reactions ?? []) {
    nodes.push({
      id: `r:${r.id}`,
      type: "reactionNode",
      position: positions[r.id] ?? { x: 420, y: 40 },
      data: { id: r.id, value: r },
    });
  }
  for (const r of model.reactions ?? []) {
    for (const input of r.inputs ?? []) {
      if (nodes.some((n) => n.id === `m:${input}`)) {
        edges.push({
          id: `i:${r.id}:${input}`,
          source: `m:${input}`,
          target: `r:${r.id}`,
          sourceHandle: "out",
          targetHandle: "in",
          label: "input",
          deletable: false,
        });
      }
    }
    for (const output of r.outputs ?? []) {
      if (nodes.some((n) => n.id === `m:${output}`)) {
        edges.push({
          id: `o:${r.id}:${output}`,
          source: `r:${r.id}`,
          target: `m:${output}`,
          sourceHandle: "out",
          targetHandle: "in",
          label: "output",
          deletable: false,
        });
      }
    }
  }
  return { nodes, edges };
}

export function connect(
  model: any,
  source: string,
  target: string
): boolean {
  // material -> reaction records the reaction's input; reaction -> material
  // records an output. Self-links and duplicate links are ignored.
  if (source === target) return false;
  const sid = source.slice(2);
  const tid = target.slice(2);
  if (source.startsWith("m:") && target.startsWith("r:")) {
    const r = (model.reactions ?? []).find((x: any) => x.id === tid);
    if (!r) return false;
    r.inputs = r.inputs ?? [];
    if (!r.inputs.includes(sid)) r.inputs.push(sid);
    return true;
  }
  if (source.startsWith("r:") && target.startsWith("m:")) {
    const r = (model.reactions ?? []).find((x: any) => x.id === sid);
    if (!r) return false;
    r.outputs = r.outputs ?? [];
    if (!r.outputs.includes(tid)) r.outputs.push(tid);
    return true;
  }
  return false;
}
