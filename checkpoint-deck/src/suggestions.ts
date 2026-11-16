// Lógica pura de «Sugerencias de guardado» (sin Decky ni React): elegir la mejor ruta de un juego, decidir qué botón
// le toca (segura / dudosa / no encontrada) y filtrar los juegos que ya están en el hub.
import type { SavePath } from "./texts";

export interface SaveGame {
  source: "steam" | "lutris";
  id: number;
  name: string;
  manifest_name?: string;
  confidence: "high" | "doubtful";
  needs_confirmation: boolean; // siempre true: nunca se aplica solo
  state: "found" | "not_found_yet";
  paths: SavePath[];
}

// segura: «Añadir al hub» (confirma y guarda); doubtful: «Revisar y añadir» (abre «Configurar», no guarda);
// not_found: sin botón de aplicar, solo la opción manual.
export type CardKind = "safe" | "doubtful" | "not_found";

export const gameKey = (g: { source: string; id: number | string }): string => `${g.source}:${g.id}`;

// Mejor ruta: la que existe antes que la que no, la no dudosa antes que la dudosa y, a igualdad, la modificada más
// recientemente. Empate total: la primera (el orden del backend). Sin rutas: null.
export function bestPath(paths: SavePath[]): SavePath | null {
  let best: SavePath | null = null;
  const rank = (p: SavePath) => (p.exists ? 2 : 0) + (p.doubtful ? 0 : 1);
  for (const p of paths) {
    if (best === null) {
      best = p;
      continue;
    }
    const a = rank(p);
    const b = rank(best);
    if (a > b || (a === b && (p.mtime ?? 0) > (best.mtime ?? 0))) best = p;
  }
  return best;
}

export function otherPaths(paths: SavePath[], best: SavePath | null): SavePath[] {
  return paths.filter((p) => p !== best);
}

export function cardKind(g: SaveGame, best: SavePath | null = bestPath(g.paths)): CardKind {
  if (!best || !best.exists) return "not_found";
  return g.confidence === "high" && best.doubtful !== true ? "safe" : "doubtful";
}

// Solo juegos «Sin configurar en el hub»: se quitan los de Steam cuyo appid ya está en el hub (`configured`), salvo los
// que se acaban de añadir desde aquí (`keep`, para poder mostrarlos «Añadido») y los que el backend dijo que ya no
// están sin configurar (`hidden`). Los de Lutris no se pueden casar aquí con un appid: los filtra el backend al aplicar.
export function unconfiguredOnly(
  games: SaveGame[],
  configured: Iterable<number | null | undefined>,
  hidden: ReadonlySet<string> = new Set(),
  keep: ReadonlySet<string> = new Set(),
): SaveGame[] {
  const inHub = new Set<number>();
  for (const a of configured) if (typeof a === "number") inHub.add(a);
  return games.filter((g) => {
    const k = gameKey(g);
    if (keep.has(k)) return true;
    if (hidden.has(k)) return false;
    return !(g.source === "steam" && inHub.has(g.id));
  });
}
