// Plugin de Steam Deck: URLs públicas de descarga y normalización de `GET /api/deck/plugin/info`. Sin React.
export const DOWNLOAD_URL = '/api/deck/plugin';
export const ZIP_NAME = 'Checkpoint.zip';

const SHA_RE = /^[0-9a-f]{64}$/;

// {available, version, sha256, size} o {available:false}. Una suma que no sea SHA-256 válida cuenta como no disponible:
// el botón nunca ofrece un zip cuya suma no se pueda mostrar para verificarlo.
export function normalizeInfo(raw) {
  if (!raw || raw.available !== true || typeof raw.sha256 !== 'string') return { available: false };
  const sha256 = raw.sha256.toLowerCase();
  if (!SHA_RE.test(sha256)) return { available: false };
  return {
    available: true,
    sha256,
    version: typeof raw.version === 'string' && raw.version ? raw.version : null,
    size: Number.isFinite(raw.size) ? raw.size : null,
  };
}
