// Lógica pura de la comprobación de actualizaciones (sin React): fácil de probar.

// El backend dice `aplicable: false` cuando la comprobación no va con este entorno (Docker, salvo forzado).
// Mientras no hay respuesta (info null) tampoco se muestra nada: así la tarjeta no parpadea.
export function updatesApplicable(info) {
  return !!info && info.aplicable !== false;
}

// La insignia solo aparece si la comprobación es aplicable y está activa, y el backend dice que hay versión nueva.
export function showBadge(info) {
  return !!(info && info.aplicable !== false && info.habilitado !== false && info.hay_actualizacion === true);
}

// Solo se enlazan URLs https (las notas vienen de fuera: nunca se confía en el esquema).
export function safeUrl(u) {
  return typeof u === 'string' && /^https:\/\//i.test(u) ? u : null;
}

// `label` y CHANNEL_HELP son claves del catálogo (se traducen al pintar); `value` es el valor estable del backend.
export const CHANNEL_OPTIONS = [
  { value: 'stable', label: 'updates.channel.stable' },
  { value: 'beta', label: 'updates.channel.beta' },
];
export const CHANNEL_HELP = 'updates.channel.help';

export function channelOf(info) {
  return info && info.canal === 'beta' ? 'beta' : 'stable';
}

// «preliminar» solo cuando el backend lo marca para la versión ofrecida.
export function isPrerelease(info) {
  return !!(info && info.prerelease === true);
}

// Versión instalada para el pie de página ('' si aún no se conoce o es una compilación de desarrollo).
export function installedVersion(info) {
  const v = info && typeof info.actual === 'string' ? info.actual.trim() : '';
  return v && v !== 'desconocida' ? v : '';
}

// Resumen del estado de la comprobación, traducido con `t`.
export function updateSummary(info, t) {
  if (!info) return '';
  if (info.habilitado === false) return t('updates.summary.disabled');
  if (info.hay_actualizacion)
    return t(isPrerelease(info) ? 'updates.summary.newerPre' : 'updates.summary.newer', { latest: info.ultima, current: info.actual });
  if (info.error) return t('updates.summary.failed'); // fallo de la última comprobación: no es «al día» (el detalle queda en API/log)
  if (info.ultima) return t('updates.summary.upToDate', { current: info.actual });
  return t('updates.summary.noData', { current: info.actual });
}

// La actualización con un clic solo se ofrece cuando el backend dice `instalable` (instalador de Windows o instalación
// nativa de Linux, y Release con el asset de esa plataforma y su hash publicado); el backend decide, el cliente no mira
// la plataforma. Si no (Docker, repo clonado, macOS, Windows sin instalador), se mantiene el texto manual.
export function canInstall(info) {
  return !!(showBadge(info) && info.instalable === true);
}

// Hub con actualización con un clic (instalador de Windows o instalación nativa de Linux), aunque ahora no haya versión
// nueva: cambia el texto de la tarjeta.
export function isInstaller(info) {
  return !!(info && info.instalador === true);
}

// Fases de la actualización: idle -> confirm -> checking -> downloading -> installing -> restarting -> done | error.
export const INSTALL_BUSY = ['checking', 'downloading', 'installing', 'restarting'];

// Tiempo máximo esperando a que el hub vuelva con la versión nueva (si el instalador falla sin cerrar el hub, no vuelve
// nunca). Por defecto 120 s (Windows); el backend publica `espera_reinicio` (s) en GET /api/updates y en Linux son 300 s
// porque install.sh crea el venv e instala las dependencias (pip) antes de reiniciar la unidad.
export const RESTART_TIMEOUT_MS = 120000;
export const restartWaitMs = (info) => {
  const s = info && info.espera_reinicio;
  return typeof s === 'number' && Number.isFinite(s) && s > 0 ? s * 1000 : RESTART_TIMEOUT_MS;
};
export const restartTimedOut = (startedMs, nowMs, waitMs = RESTART_TIMEOUT_MS) => nowMs - startedMs >= waitMs;

// Fase siguiente según el estado que informa `GET /api/updates/install` ({state, error}).
export function phaseFromStatus(prev, status) {
  if (!status) return prev;
  if (status.state === 'error') return 'error';
  if (['downloading', 'installing', 'restarting'].includes(status.state)) return status.state;
  return prev; // idle: el servidor aún no ha empezado o se acaba de reiniciar (lo resuelve la espera de reinicio)
}

// ¿Ya corre la versión nueva? (tras el reinicio el hub responde con `actual` igual a la que se instaló)
export function reachedVersion(info, target) {
  return !!(info && target && info.actual === target);
}

// Clave del catálogo (con {version}) del texto de cada fase.
export const PHASE_TEXT = {
  checking: 'updates.install.checking',
  downloading: 'updates.install.downloading',
  installing: 'updates.install.installing',
  restarting: 'updates.install.restarting',
  done: 'updates.install.done',
};
