import { useCallback, useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useReactFlow,
} from "@xyflow/react";
import { useStore } from "./store";
import { buildGraph, connect } from "./graph";

// --- custom nodes ---------------------------------------------------------- LOCATION

function MaterialNode({ data }: { data: any }) {
  const color = data.paletteColor ?? "#727b83";
  return (
    <div className="matnode" style={{ border: `1px solid ${color}`, minWidth: 130 }}>
      <Handle type="target" position={Position.Top} id="in" />
      <div className="sw" style={{ background: color }} />
      <strong>{data.id}</strong>
      <div className="sub">density {data.value?.density ?? "?"}</div>
      <Handle type="source" position={Position.Right} id="out" />
    </div>
  );
}

function ReactionNode({ data }: { data: any }) {
  return (
    <div className="reacnode">
      <Handle type="target" position={Position.Left} id="in" />
      <strong>{data.id}</strong>
      <div className="sub">priority {data.value?.priority ?? 0}</div>
      <Handle type="source" position={Position.Right} id="out" />
    </div>
  );
}

const nodeTypes = { materialNode: MaterialNode, reactionNode: ReactionNode };

// --- graph canvas ---------------------------------------------------------- LOCATION

export default function Graph() {
  const { model, positions, applyModel, select, setPosition, selected } = useStore();
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildGraph(model, positions),
    [model, positions]
  );
  const reactflow = useReactFlow();

  // Node/edge arrays are rebuilt outright whenever the model changes
  // (keyed below by the model's JSON), keeping the graph in sync with the
  // working model after every applyModel/undo/redo.
  const modelKey = useMemo(() => JSON.stringify(model), [model]);

  const onConnect = useCallback(
    (connection: any) => {
      applyModel((world: any) => {
        connect(world, connection.source, connection.target);
      });
    },
    [applyModel]
  );

  const onNodeClick = (_: any, node: any) => {
    const [kindPrefix, id] = node.id.split(":");
    const kind = kindPrefix === "m" ? "materials" : "reactions";
    select(kind, id);
  };

  const onNodeDragStop = (_: any, node: any) => setPosition(String(node.id).slice(2), node.position);

  return (
    <div className="graphwrap">
      <div className="actions">
        <button
          onClick={() =>
            applyModel((world: any, snap: any) => {
              const paletteId =
                (world.palettes ?? [])[0]?.id ?? "";
              let n = 1;
              while ((world.materials ?? []).some((m: any) => m.id === `material_${n}`)) n++;
              world.materials.push({
                id: `material_${n}`,
                density: 1,
                palette: paletteId,
                color: 0,
                properties: { temperature: 0 },
              });
              const path = snap.categories.find((c: any) => c.kind === "materials")!.path;
              void path;
            })
          }
        >
          + Material
        </button>
        <button
          onClick={() =>
            applyModel((world: any) => {
              let n = 1;
              while ((world.reactions ?? []).some((r: any) => r.id === `reaction_${n}`)) n++;
              world.reactions.push({
                id: `reaction_${n}`,
                inputs: [],
                outputs: [],
                priority: 0,
              });
            })
          }
        >
          + Reaction
        </button>
        <button
          onClick={() => {
            if (!selected) return;
            applyModel((world: any) => {
              if (selected.kind === "materials") {
                world.materials = (world.materials ?? []).filter((m: any) => m.id !== selected.id);
                for (const r of world.reactions ?? []) {
                  r.inputs = (r.inputs ?? []).filter((i: string) => i !== selected.id);
                  r.outputs = (r.outputs ?? []).filter((o: string) => o !== selected.id);
                }
              } else {
                world.reactions = (world.reactions ?? []).filter((r: any) => r.id !== selected.id);
              }
            });
          }}
        >
          Delete selected
        </button>
        <button onClick={() => reactflow.fitView()}>Fit</button>
      </div>
      <ReactFlow
        key={modelKey}
        nodes={initialNodes as any}
        edges={initialEdges as any}
        nodeTypes={nodeTypes}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onNodeDragStop={onNodeDragStop}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={18} color="#23262e" />
        <MiniMap pannable zoomable nodeStrokeWidth={3} />
        <Controls />
      </ReactFlow>
    </div>
  );
}
