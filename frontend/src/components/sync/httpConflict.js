// Conflicto de datos de un juego solo http (lógica pura): qué mostrar y qué enviar al hub.

// Un elemento por dispositivo del juego con conflicto registrado o resolución pendiente: {device, conflict, resolution}.
// `watch` es el estado de /api/watches (`conflicts` y `resolutions`; un hub antiguo no los trae).
export function httpConflictItems(watch, game) {
  const mine = (l) => (Array.isArray(l) ? l.filter((x) => x.game === game) : []);
  const conflicts = mine(watch?.conflicts);
  const resolutions = mine(watch?.resolutions);
  const devices = [...new Set([...conflicts, ...resolutions].map((x) => x.device))].sort((a, b) => String(a).localeCompare(String(b)));
  return devices.map((device) => ({
    device,
    conflict: conflicts.find((c) => c.device === device) || null,
    resolution: resolutions.find((r) => r.device === device) || null,
  }));
}

// Cuerpo de `PUT /api/sync/{game}/resolution`: las huellas son las del conflicto que ve la persona (el hub rechaza si cambiaron).
export const resolutionBody = (conflict, winner) => ({
  device: conflict.device,
  winner,
  expect: { hub: conflict.hub, device: conflict.device_hash },
});
