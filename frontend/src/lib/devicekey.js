// Lógica del bloque «Clave» de un dispositivo http, sin React. La clave solo se guarda en el estado mientras está visible
// (`key`); al ocultarla, regenerarla o revocarla se descarta. Nunca llega al DOM salvo tras «Ver» (o al regenerar).
export const initialState = {
  loaded: false,
  exists: false,
  key: null,
  confirm: null,
  busy: false,
  copied: false,
  error: null,
  fresh: false,
};

// confirm: null | 'regenerate' | 'revoke' (confirmación en el propio bloque).
export function reduce(s, a) {
  switch (a.type) {
    case 'start':
      return { ...s, busy: true, error: null, copied: false, fresh: false };
    case 'loaded': // a.key solo viene si hay que mostrarla
      return {
        ...s,
        loaded: true,
        busy: false,
        exists: !!a.exists,
        key: a.exists && a.key ? a.key : null,
        confirm: null,
        fresh: !!(a.fresh && a.exists),
      };
    case 'copied':
      return { ...s, busy: false, copied: !!a.ok, error: a.ok ? null : a.error };
    case 'hide':
      return { ...s, key: null };
    case 'failed':
      return { ...s, loaded: true, busy: false, confirm: null, error: a.error };
    case 'ask':
      return { ...s, confirm: a.what, error: null };
    case 'cancel':
      return { ...s, confirm: null };
    default:
      return s;
  }
}

// Cuándo el desplegable «Clave del dispositivo» se abre solo: sin clave (para ver «Generar clave») o recién generada o regenerada
// (para poder copiarla). Cerrado en el resto; `fresh` lo pone `create` y lo quita la siguiente acción.
export const wantsOpen = (s) => !!s.loaded && !s.error && (!s.exists || s.fresh);

// `api` = { get, create, revoke } (funciones de lib/api/pairing.js con el id ya aplicado). Devuelve la acción del reductor.
// load: solo estado (la clave del GET se descarta); show: estado y clave visible; create: genera o regenera y muestra; revoke.
export async function run(api, what) {
  try {
    if (what === 'load') return { type: 'loaded', exists: (await api.get()).exists };
    if (what === 'show') {
      const r = await api.get();
      return { type: 'loaded', exists: r.exists, key: r.key };
    }
    if (what === 'create') {
      const r = await api.create();
      return { type: 'loaded', exists: r.exists, key: r.key, fresh: true };
    }
    if (what === 'revoke') return { type: 'loaded', exists: (await api.revoke()).exists };
    throw new Error(`acción desconocida: ${what}`);
  } catch (error) {
    return { type: 'failed', error };
  }
}

// Copiar sin mostrarla: pide la clave, la copia y no la guarda. `copy` es copyText.
export async function copyKey(api, key, copy) {
  try {
    const k = key ?? (await api.get()).key;
    if (!k) return { type: 'copied', ok: false, error: { code: 'devkey.copyFail', params: {} } };
    const ok = await copy(k);
    return { type: 'copied', ok, error: ok ? null : { code: 'devkey.copyFail', params: {} } };
  } catch (error) {
    return { type: 'copied', ok: false, error };
  }
}

// Las acciones de clave se bloquean si el dispositivo no está guardado o su tarjeta tiene cambios sin guardar. Devuelve la clave
// del catálogo con la explicación, o null si se pueden usar.
export const lockReason = (dev, renamed) => (!dev.id ? 'devkey.lockNew' : renamed ? 'devkey.lockDirty' : null);
