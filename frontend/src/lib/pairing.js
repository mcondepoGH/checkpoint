// Lógica de las solicitudes de vinculación pendientes, sin React (se prueba sin navegador).
export const PAIRING_POLL_MS = 5000;

// Respuesta de GET /api/pairing/pending -> filas limpias con la hora de caducidad calculada (`expiresAt`, ms).
export function normalizePending(r, now) {
  if (!Array.isArray(r)) return [];
  return r
    .filter((x) => x && typeof x.id === 'string')
    .map((x) => ({
      id: x.id,
      name: String(x.name ?? ''),
      os: String(x.os ?? ''),
      code: String(x.code ?? ''),
      ip: String(x.ip ?? ''),
      existing: x.existing === 'http' || x.existing === 'other' ? x.existing : 'none',
      expiresAt: now + (Number(x.expires_in) || 0) * 1000,
    }));
}

export const remainingSeconds = (row, now) => Math.max(0, Math.ceil((row.expiresAt - now) / 1000));
export const formatRemaining = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

// Aceptar se puede si no choca con un dispositivo que no es http y no ha caducado.
export const canAccept = (row, remaining) => row.existing !== 'other' && remaining > 0;
// Clave del catálogo del aviso por dispositivo ya existente (null si no hay).
export const existingNoteKey = (row) =>
  row.existing === 'http' ? 'pairing.existing.http' : row.existing === 'other' ? 'pairing.existing.other' : null;

// Qué hacer tras un fallo de aceptar o rechazar: mensaje claro ({code, params}, se traduce al pintar) y si hay que refrescar la lista.
// 404 = caducada o retirada; 409 no_pending = ya resuelta; 409 config_changed = reintentar (la fila sigue y Aceptar vale otra vez).
export function failureOf(e, what = 'accept') {
  const code = e?.code;
  if (e?.status === 404 || code === 'err.pairing.request_unknown') return { body: { code: 'pairing.gone', params: {} }, refresh: true };
  if (code === 'err.pairing.not_pending') return { body: { code: 'pairing.notPending', params: {} }, refresh: true };
  if (code === 'err.main.config_changed') return { body: { code: 'pairing.configChanged', params: {} }, refresh: false };
  if (code === 'err.pairing.device_not_http') return { body: { code, params: e.params ?? {} }, refresh: true };
  return {
    body: e?.code
      ? { code, params: e.params ?? {} }
      : { code: what === 'accept' ? 'pairing.failAccept' : 'pairing.failReject', params: {} },
    refresh: false,
  };
}

// Tras aceptar: con el borrador limpio se recarga la config; con cambios sin guardar no se toca (se avisa).
export const afterAccept = (dirty) => (dirty ? 'keep' : 'reload');
