// Lógica pura de la pantalla de datos sin dispositivo ni juego (sin React, se prueba sin navegador).
import { ui } from '#src/lib/errors.js';

// Elementos elegidos (en el orden de la lista) a partir de los ids marcados.
export const selectedItems = (items, ids) => items.filter((i) => ids.includes(i.id));

// ¿Alguno es la única copia de unos datos? (hub de un juego fuera de la configuración).
export const hasOnlyCopy = (items) => items.some((i) => i.only_copy);

export const totalSize = (items) => items.reduce((n, i) => n + (Number.isFinite(i.size) ? i.size : 0), 0);

// Cuerpo de la petición de mover a la papelera: id y token tal cual los dio el listado.
export const payload = (items) => items.map((i) => ({ id: i.id, token: i.token }));

// Aviso tras mover: todo bien, o parcial con el motivo de cada elemento que no se movió (el id es el del listado).
export function moveNotice(res) {
  const moved = res?.moved?.length ?? 0;
  const skipped = res?.skipped ?? [];
  if (skipped.length === 0) return { variant: 'ok', body: ui('orphans.moved', { count: moved }) };
  const causes = skipped.map((s) => ({ path: s.id, code: s.code, params: s.params ?? {} }));
  return { variant: moved ? 'warn' : 'error', body: ui('orphans.partial', { moved, skipped: skipped.length, causes }) };
}

// Ids marcados que siguen existiendo en la lista nueva (tras recargar, lo que ya no está se desmarca).
export const keepSelected = (ids, items) => ids.filter((id) => items.some((i) => i.id === id));
