// Datos sin dispositivo ni juego en la config: lista, papelera y restauración. Todo con sesión.
import { api } from '../api.js';

export const listOrphans = () => api('/api/orphans');
// `items`: [{id, token}] tal y como los devolvió `listOrphans` (el token liga la confirmación a lo que vio el usuario).
export const trashOrphans = (items) => api('/api/orphans/trash', { method: 'POST', body: { items } });
export const listTrash = () => api('/api/orphans/trash');
export const restoreTrash = (entry, item) => api('/api/orphans/trash/restore', { method: 'POST', body: { entry, item } });
// Reubica un huérfano de juego en un juego existente de la config: `id` y `token` del listado y `target` = id del destino.
export const relocateOrphan = (id, token, target) => api('/api/orphans/relocate', { method: 'POST', body: { id, token, target } });
