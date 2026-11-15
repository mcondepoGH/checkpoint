// Borradores del formulario «Configurar» de los juegos sin configurar (sin Decky ni React).
// Viven a nivel de módulo, por appid: el selector de carpetas de Decky cierra la Quick Access y desmonta el panel, y el
// formulario (estado local de React) nacería vacío al volver. Aquí sobrevive al remontaje del componente.

export interface Draft {
  open: boolean;
  gname: string;
  path: string;
  sug: unknown; // la sugerencia del backend (el componente la tipa)
}

const store = new Map<number, Draft>();

export const drafts = {
  get(appid: number): Draft | undefined {
    const d = store.get(appid);
    return d ? { ...d } : undefined;
  },
  set(appid: number, d: Draft): void {
    store.set(appid, { ...d });
  },
  // Cambia solo los campos dados. Sin borrador previo (el componente se desmontó antes de crearlo) parte de `base`.
  patch(appid: number, changes: Partial<Draft>, base: Draft): Draft {
    const next: Draft = { ...(store.get(appid) ?? base), ...changes };
    store.set(appid, next);
    return { ...next };
  },
  delete(appid: number): void {
    store.delete(appid);
  },
  // Quita los borradores de appids que ya no están en la lista (evita fugas); no toca los que siguen.
  prune(keep: Iterable<number>): void {
    const k = new Set(keep);
    for (const id of [...store.keys()]) if (!k.has(id)) store.delete(id);
  },
  clear(): void {
    store.clear();
  },
  size(): number {
    return store.size;
  },
};
