// Comprobación de actualizaciones.
import { api } from '../api.js';

export const getUpdates = () => api('/api/updates');
export const refreshUpdates = () => api('/api/updates?refresh=true');
export const putUpdates = (body) => api('/api/updates', { method: 'PUT', body });
// Actualización con un clic (solo instalador de Windows): el servidor decide qué instalar; el cliente no manda nada.
export const installUpdate = () => api('/api/updates/install', { method: 'POST' });
export const getInstallStatus = () => api('/api/updates/install');
