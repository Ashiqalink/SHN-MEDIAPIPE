// JSON-string deserialize; server already normalizes numbers.
export async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return (await resp.json()) as T;
}

export async function apiGet<T = any>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return (await resp.json()) as T;
}
