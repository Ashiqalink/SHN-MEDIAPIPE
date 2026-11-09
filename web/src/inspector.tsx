import { useStore, deepCopy } from "./store";
import type { Entity } from "./store";

/* Schema-driven inspector. Field widgets derive from the category's JSON
 * schema plus x-pixorra annotations: reference -> entity picker resolved
 * against declared content (resolved pickers), paletteIndex -> per-palette
 * color picker with swatches, expression fields stay free-form strings. */

function selectedEntity(): Entity | null {
  const { snapshot, selected } = useStore.getState();
  if (!snapshot || !selected) return null;
  return (
    snapshot.entities.find(
      (e) => e.kind === selected.kind && e.id === selected.id
    ) ?? null
  );
}

function pickers() {
  const { snapshot, model } = useStore.getState();
  return { snapshot, model };
}

function Options({ kind, selfId }: { kind?: string; selfId?: string }) {
  const { snapshot } = pickers();
  const options = (snapshot?.entities ?? [])
    .filter((e) => (kind ? e.kind === kind : true) && e.id !== selfId)
    .map((e) => e.id);
  return (
    <>
      {options.map((id) => (
        <option key={id}>{id}</option>
      ))}
    </>
  );
}

function ColorOptions({ paletteId }: { paletteId: string }) {
  const { model } = pickers();
  const palette = (model?.palettes ?? []).find((p: any) => p.id === paletteId);
  return (
    <>
      {(palette?.colors ?? []).map((c: string, i: number) => (
        <option key={i} value={i}>
          {i === (palette?.colors ?? []).length ? "—" : i + 1}· {c}
        </option>
      ))}
    </>
  );
}

function Field({ schema, label, value, onChange }: any) {
  const ann = schema?.["x-pixorra"] ?? {};
  const { model, snapshot } = pickers();
  void snapshot;

  if (ann.reference) {
    return (
      <label>
        {label} → {ann.reference.kind}
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          <option value="">(none)</option>
          <Options kind={ann.reference.kind} />
        </select>
      </label>
    );
  }
  if (ann.paletteIndex) {
    const paletteId = String(value_path(model) ?? "");
    void paletteId;
    return null; // rendered by MaterialInspector with palette context
  }
  if (typeof schema?.type === "number" || schema?.type === "integer") {
    return (
      <label>
        {label}
        <input
          type="number"
          step="any"
          value={value ?? 0}
          onChange={(e) => {
            const raw = e.target.value;
            const num =
              schema.type === "integer" && !raw.includes(".")
                ? parseInt(raw || "0", 10)
                : parseFloat(raw || "0");
            onChange(isNaN(num) ? 0 : num);
          }}
        />
      </label>
    );
  }
  if (schema?.type === "boolean") {
    return (
      <label>
        {label}
        <select value={String(!!value)} onChange={(e) => onChange(e.target.value === "true")}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      </label>
    );
  }
  if (schema?.type === "array") {
    return (
      <label>
        {label} (list)
        <textarea
          rows={Math.min(6, (value?.length ?? 0) + 1)}
          value={(value ?? []).join(", ")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            )
          }
          style={{ width: "100%" }}
        />
      </label>
    );
  }
  if (schema?.type === "object") {
    return (
      <fieldset style={{ border: "1px solid var(--border)" }}>
        <legend style={{ fontSize: 11 }}>{label}</legend>
        {Object.entries(schema.properties ?? {}).map(([k, sub]: any) => (
          <Field
            key={k}
            schema={sub}
            label={k}
            value={(value ?? {})[k]}
            onChange={(child: any) => onChange({ ...(value ?? {}), [k]: child })}
          />
        ))}
      </fieldset>
    );
  }
  // Default: string. Expression-annotated fields keep the raw text.
  return (
    <label>
      {label}
      <input type="text" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function value_path(model: any) {
  return null;
}

function MaterialInspector({ entity }: { entity: Entity }) {
  const { snapshot, model, applyModel } = useStore();
  const category = snapshot?.categories.find((c) => c.kind === "materials");
  const schemaProps = category?.schema?.items?.properties ?? {};
  const paletteId = String(entity.value.palette ?? "");

  return (
    <>
      {Object.entries(schemaProps).map(([key, sub]: any) => {
        if (sub?.["x-pixorra"]?.paletteIndex) {
          return (
            <label key={key}>
              {key} ({paletteId || "?"})
              <select
                value={Number(entity.value[key] ?? 0)}
                onChange={(e) =>
                  applyModel((world: any) => {
                    const m = (world.materials ?? []).find(
                      (x: any) => x.id === entity.id
                    );
                    if (m) m[key] = Number(e.target.value);
                  })
                }
              >
                {(
                  (model?.palettes ?? []).find((p: any) => p.id === paletteId)?.colors ?? []
                ).map((c: string, i: number) => (
                  <option key={i} value={i}>
                    {i} · {c}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        return (
          <Field
            key={key}
            schema={sub}
            label={key}
            value={entity.value[key]}
            onChange={(child: any) =>
              applyModel((world: any) => {
                const m = (world.materials ?? []).find(
                  (x: any) => x.id === entity.id
                );
                if (m) m[key] = child;
              })
            }
          />
        );
      })}
      <button
        style={{ marginTop: 10, width: "100%" }}
        onClick={() =>
          applyModel((world: any) => {
            world.materials = (world.materials ?? []).filter(
              (x: any) => x.id !== entity.id
            );
          })
        }
      >
        Delete {entity.id}
      </button>
    </>
  );
}

function ReactionInspector({ entity }: { entity: Entity }) {
  const { snapshot, applyModel } = useStore();
  const category = snapshot?.categories.find((c) => c.kind === "reactions");
  const schemaProps = category?.schema?.items?.properties ?? {};
  const patch = (field: string, value: any) =>
    applyModel((world: any) => {
      const r = (world.reactions ?? []).find((x: any) => x.id === entity.id);
      if (r) r[field] = value;
    });

  return (
    <>
      {Object.entries(schemaProps).map(([key, sub]: any) => {
        const ann = sub?.["x-pixorra"] ?? {};
        const value = entity.value[key];
        if (ann.reference && Array.isArray(value)) {
          return (
            <Field
              key={key}
              schema={{ type: "array" }}
              label={key}
              value={value}
              onChange={(child: any) => patch(key, child)}
            />
          );
        }
        return (
          <Field
            key={key}
            schema={sub}
            label={key}
            value={value}
            onChange={(child: any) => patch(key, child)}
          />
        );
      })}
      <div style={{ marginTop: 10 }}>
        <label style={{ display: "block" }}>Wiring (inputs/outputs)</label>
        {((entity.value.inputs ?? []) as string[]).map((input: string) => (
          <div key={input}>
            in · {input}
            <button
              style={{ float: "right" }}
              onClick={() =>
                applyModel((world: any) => {
                  const r = (world.reactions ?? []).find((x: any) => x.id === entity.id);
                  if (r) r.inputs = (r.inputs ?? []).filter((i: string) => i !== input);
                })
              }
            >
              remove
            </button>
          </div>
        ))}
        {((entity.value.outputs ?? []) as string[]).map((output: string) => (
          <div key={output}>
            out · {output}
            <button
              style={{ float: "right" }}
              onClick={() =>
                applyModel((world: any) => {
                  const r = (world.reactions ?? []).find((x: any) => x.id === entity.id);
                  if (r) r.outputs = (r.outputs ?? []).filter((o: string) => o !== output);
                })
              }
            >
              remove
            </button>
          </div>
        ))}
      </div>
    </>
  );
}

export default function Inspector() {
  const { selected, snapshot } = useStore();
  const entity = selectedEntity();
  void snapshot;
  if (!entity)
    return (
      <div className="inspector">
        <h4>Inspector</h4>
        <p style={{ fontSize: 12, color: "var(--muted)" }}>
          Select a material or reaction node to edit its schema-declared fields.
        </p>
      </div>
    );
  return (
    <div className="inspector">
      <h4>
        {entity.kind} · {entity.id}
      </h4>
      {entity.kind === "materials" ? (
        <MaterialInspector entity={entity} />
      ) : entity.kind === "reactions" ? (
        <ReactionInspector entity={entity} />
      ) : (
        <p style={{ fontSize: 12, color: "var(--muted)" }}>
          Browser-only category inspection arrives with quest/optional modules.
        </p>
      )}
    </div>
  );
}

export function cloneSelected() {
  const { selected, model, applyModel } = useStore.getState();
  if (!selected || !model) return;
  const entity = (model[selected.kind] ?? []).find((e: any) => e.id === selected.id);
  if (!entity) return;
  const copy = deepCopy(entity);
  let n = 2;
  while ((model[selected.kind] ?? []).some((e: any) => e.id === `${selected.id}_${n}`)) n++;
  copy.id = `${selected.id}_${n}`;
  applyModel((world: any) => {
    world[selected.kind].push(copy);
  });
}
