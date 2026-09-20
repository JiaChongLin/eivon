export function parseSpec(text: string): Record<string, unknown> {
  let result: unknown;
  try { result = JSON.parse(text); } catch { throw new Error("Specification must be valid JSON"); }
  if (!result || Array.isArray(result) || typeof result !== "object") throw new Error("Specification must be a JSON object");
  return result as Record<string, unknown>;
}
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => `${JSON.stringify(key)}:${stable(child)}`).join(",")}}`;
  return JSON.stringify(value) ?? "undefined";
}
export type Change = { path: string; before: unknown; after: unknown };
export function diffSpec(before: unknown, after: unknown, path = ""): Change[] {
  if (stable(before) === stable(after)) return [];
  if (before !== null && after !== null && typeof before === "object" && typeof after === "object" && !Array.isArray(before) && !Array.isArray(after)) {
    const left = before as Record<string, unknown>; const right = after as Record<string, unknown>;
    return [...new Set([...Object.keys(left), ...Object.keys(right)])].sort().flatMap((key) => diffSpec(Object.hasOwn(left, key) ? left[key] : undefined, Object.hasOwn(right, key) ? right[key] : undefined, `${path}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`));
  }
  return [{ path: path || "/", before, after }];
}
