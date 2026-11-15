// Detalles técnicos de un fallo de render, para diagnosticar sin consola (iPad). Solo salen name, message, stack
// recortado, user agent y versión: nunca configuración, cabeceras ni respuestas de red. Lo que parece una clave se oculta.
export const STACK_LINES = 12;
const HIDDEN = '[oculto]';
// ck_… / ckd_… (claves de Checkpoint) y cualquier token largo sin separadores (32+ caracteres base64/hex/guiones).
const SECRET = /\bckd?_[A-Za-z0-9_-]+|[A-Za-z0-9_-]{32,}/g;

// Parámetros de URL (?key=…, #token=…) fuera: la dirección se conserva, lo demás no sale nunca.
const URL_QUERY = /(https?:\/\/[^\s?#'")]*)[?#][^\s'")]*/g;

export const redact = (s) =>
  String(s ?? '')
    .replace(URL_QUERY, '$1?[oculto]')
    .replace(SECRET, HIDDEN);

export function crashDetails(error, { userAgent = '', version = '' } = {}) {
  const e = error && typeof error === 'object' ? error : { message: error };
  const stack = String(e.stack ?? '')
    .split('\n')
    .slice(0, STACK_LINES)
    .join('\n');
  const lines = [];
  if (version) lines.push(`Checkpoint: ${redact(version)}`);
  lines.push(`Error: ${redact(e.name || 'Error')}: ${redact(e.message)}`);
  if (userAgent) lines.push(`User agent: ${redact(userAgent)}`);
  if (stack) lines.push('', redact(stack));
  return lines.join('\n');
}

// Única función que da forma al texto de los detalles, para el aviso de último recurso, el de zona y el discreto.
// `nav` es el navigator (inyectable en los tests; sin él, el global si existe).
export function crashReport(error, { version = '', nav = globalThis.navigator } = {}) {
  return crashDetails(error, { userAgent: nav?.userAgent || '', version });
}
