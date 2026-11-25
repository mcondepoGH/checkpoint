// Ajustes del sistema que solo aplican al hub instalado en Windows.
import { api } from '../api.js';

export const getAutostart = () => api('/api/autostart');
export const putAutostart = (enabled) => api('/api/autostart', { method: 'PUT', body: { enabled } });
