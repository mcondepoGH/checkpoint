// Detalles técnicos de un fallo, para diagnosticar sin consola. Port de `frontend/src/lib/crash.js` del hub (mismas
// funciones y mismas reglas): solo salen name, message, stack recortado, user agent y versión; nunca claves ni
// cabeceras ni respuestas. Lo que parece una clave o un steamid64 se oculta; las URLs pierden sus parámetros.
export const STACK_LINES = 12;
const HIDDEN = "[oculto]";
// ck_… / ckd_… (claves de Checkpoint), steamid64 (17 cifras que empiezan por 7656119) y cualquier token largo sin
// separadores (32+ caracteres base64/hex/guiones).
const SECRET = /\bckd?_[A-Za-z0-9_-]+|\b7656119\d{10}\b|[A-Za-z0-9_-]{32,}/g;
const URL_QUERY = /(https?:\/\/[^\s?#'")]*)[?#][^\s'")]*/g;

export interface Crashable {
  name?: string;
  message?: unknown;
  stack?: string;
}

export const redact = (s: unknown): string =>
  String(s ?? "")
    .replace(URL_QUERY, "$1?[oculto]")
    .replace(SECRET, HIDDEN);

export function crashDetails(
  error: unknown,
  { userAgent = "", version = "" }: { userAgent?: string; version?: string } = {},
): string {
  const e: Crashable = error && typeof error === "object" ? (error as Crashable) : { message: error };
  const stack = String(e.stack ?? "")
    .split("\n")
    .slice(0, STACK_LINES)
    .join("\n");
  const lines: string[] = [];
  if (version) lines.push(`Checkpoint: ${redact(version)}`);
  lines.push(`Error: ${redact(e.name || "Error")}: ${redact(e.message)}`);
  if (userAgent) lines.push(`User agent: ${redact(userAgent)}`);
  if (stack) lines.push("", redact(stack));
  return lines.join("\n");
}

// Única función que da forma al texto de los detalles. `nav`: el navigator (inyectable en los tests).
export function crashReport(
  error: unknown,
  { version = "", nav = globalThis.navigator }: { version?: string; nav?: { userAgent?: string } | undefined } = {},
): string {
  return crashDetails(error, { userAgent: nav?.userAgent || "", version });
}
