// Información del plugin de Steam Deck (público: no necesita sesión). La descarga es un enlace directo, no pasa por aquí.
import { api } from '../api.js';

export const getDeckPluginInfo = () => api('/api/deck/plugin/info');
