// Lógica de las sugerencias de Steam, sin React (se prueba sin navegador).
export const STEAM_POLL_MS = 5000;

const text = (v) => (typeof v === 'string' ? v : '');

// Respuesta de GET /api/steam/suggestions -> filas limpias.
export function normalizeSuggestions(r) {
  if (!Array.isArray(r)) return [];
  return r
    .filter((x) => x && typeof x.id === 'string')
    .map((x) => ({
      id: x.id,
      appid: Number.isInteger(x.appid) ? x.appid : 0,
      steamName: text(x.steam_name),
      game: text(x.game),
      gameName: text(x.game_name) || text(x.game),
      device: text(x.device),
      deviceName: text(x.device_name) || text(x.device),
    }));
}

// Respuesta de GET /api/steam/dismissed -> filas limpias (sin nombre de juego se muestra su id).
export function normalizeDismissed(r) {
  if (!Array.isArray(r)) return [];
  return r
    .filter((x) => x && typeof x.id === 'string')
    .map((x) => ({
      id: x.id,
      appid: Number.isInteger(x.appid) ? x.appid : 0,
      steamName: text(x.steam_name),
      game: text(x.game),
      gameName: text(x.game_name) || text(x.game),
    }));
}

// El bloque solo se pinta si hay algo que decidir, que olvidar o que contar.
export const showBlock = (rows, dismissed, notice) => rows.length > 0 || dismissed.length > 0 || !!notice;

// Qué hacer tras un fallo de aceptar, descartar u olvidar: mensaje claro ({code, params}, se traduce al pintar) y si refrescar la lista.
// 404 = ya no existe; 409 game_has_appid / appid_in_use = ya no vale (el backend la retira); config_changed = reintentar (la fila sigue).
export function failureOf(e, what = 'accept') {
  const code = e?.code;
  const gone = (key) => ({ body: { code: key, params: {} }, refresh: true });
  if (code === 'err.steam.dismissed_unknown') return gone('steam.dismissedGone');
  if (code === 'err.steam.game_unknown') return gone('steam.gameGone');
  if (code === 'err.steam.game_has_appid') return gone('steam.gameHasAppid');
  if (code === 'err.steam.appid_in_use') return gone('steam.appidInUse');
  if (e?.status === 404 || code === 'err.steam.suggestion_unknown') return gone(what === 'forget' ? 'steam.dismissedGone' : 'steam.gone');
  if (code === 'err.main.config_changed') return { body: { code: 'steam.configChanged', params: {} }, refresh: false };
  if (code) return { body: { code, params: e.params ?? {} }, refresh: false };
  const fallback = { accept: 'steam.failAccept', dismiss: 'steam.failDismiss', forget: 'steam.failForget' };
  return { body: { code: fallback[what] ?? 'steam.failAccept', params: {} }, refresh: false };
}
