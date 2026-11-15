// Sugerencias de appid de Steam y descartes recordados. Todo con sesión (la Deck usa su propia clave, no pasa por aquí).
import { api } from '../api.js';

const enc = encodeURIComponent;
export const listSuggestions = () => api('/api/steam/suggestions');
export const acceptSuggestion = (id) => api(`/api/steam/suggestions/${enc(id)}/accept`, { method: 'POST' });
export const dismissSuggestion = (id) => api(`/api/steam/suggestions/${enc(id)}/dismiss`, { method: 'POST' });
export const listDismissed = () => api('/api/steam/dismissed');
export const forgetDismissed = (id) => api(`/api/steam/dismissed/${enc(id)}`, { method: 'DELETE' });
