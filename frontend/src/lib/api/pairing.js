// Vinculación de dispositivos (solicitudes pendientes) y API key de cada dispositivo http. Todo con sesión.
import { api } from '../api.js';

export const listPending = () => api('/api/pairing/pending');
// El backend exige el código; la interfaz envía el de la fila (el usuario ya lo comprobó contra su dispositivo).
export const acceptPending = (id, code) => api(`/api/pairing/pending/${encodeURIComponent(id)}/accept`, { method: 'POST', body: { code } });
export const rejectPending = (id) => api(`/api/pairing/pending/${encodeURIComponent(id)}/reject`, { method: 'POST' });

const keyPath = (id) => `/api/devices/${encodeURIComponent(id)}/apikey`;
export const getDeviceKey = (id) => api(keyPath(id)); // {exists, key}
export const createDeviceKey = (id) => api(keyPath(id), { method: 'POST' }); // genera o regenera
export const revokeDeviceKey = (id) => api(keyPath(id), { method: 'DELETE' });
