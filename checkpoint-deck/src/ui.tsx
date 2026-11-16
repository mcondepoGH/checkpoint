// Piezas visuales del panel por pestañas (solo presentación; la lógica está en panel.ts). Componentes de @decky/ui: el foco
// de mando lo dan DialogButton y Focusable. Cada insignia lleva forma (icono) + color + texto: el color solo nunca dice nada.
import { ReactNode } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { toaster } from "@decky/api";
import { FaCheckCircle, FaExclamationTriangle, FaInfoCircle, FaTimesCircle } from "react-icons/fa";
import type { Badge as BadgeData, Banner, ProgressRow, TabDot } from "./panel";
import { ToastKind, toastDuration } from "./autosync";
import { TAB_DOT_ATTENTION, TAB_DOT_UPDATE, TAB_LABELS, TAB_ORDER, TONE_ICON, TabId, Tone } from "./texts";

export const TONE_COLOR: Record<Tone, string> = { ok: "#52c98f", info: "#6cb8ff", warn: "#f2bd4b", err: "#ff9d94", nf: "#93a1b2" };
const TONE_BG: Record<Tone, string> = { ok: "#52c98f22", info: "#6cb8ff22", warn: "#f2bd4b22", err: "#ff9d9422", nf: "#93a1b222" };

// Texto que se parte en varias líneas (direcciones y rutas largas) en vez de cortarse
export const WRAP = { whiteSpace: "normal", overflowWrap: "anywhere", wordBreak: "break-all" } as const;
export const MONO = { ...WRAP, fontFamily: "monospace", fontSize: "0.85em" } as const;
export const MUTED = { ...WRAP, opacity: 0.75, fontSize: "0.9em" } as const;

export function StatusBadge({ badge }: { badge: BadgeData }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 999,
        border: `1px solid ${TONE_COLOR[badge.tone]}`,
        background: TONE_BG[badge.tone],
        color: TONE_COLOR[badge.tone],
        fontWeight: 600,
        fontSize: "0.9em",
        whiteSpace: "nowrap",
      }}
    >
      <span aria-hidden="true">{TONE_ICON[badge.tone]}</span>
      {badge.label}
    </span>
  );
}

// ---- toasts: de Decky solo se controlan título, cuerpo, icono y duración; el nivel se dice con el icono ----
const KIND_ICON: Record<ToastKind, ReactNode> = {
  ok: <FaCheckCircle color={TONE_COLOR.ok} />,
  info: <FaInfoCircle color={TONE_COLOR.info} />,
  warn: <FaExclamationTriangle color={TONE_COLOR.warn} />,
  error: <FaTimesCircle color={TONE_COLOR.err} />,
};
export function showToast(kind: ToastKind, body: string, title = "Checkpoint"): void {
  toaster.toast({ title, body, icon: KIND_ICON[kind], duration: toastDuration(kind) });
}

// ---- pestañas ----
const dotStyle = {
  position: "absolute",
  top: 2,
  right: 2,
  minWidth: 16,
  height: 16,
  borderRadius: 8,
  fontSize: 11,
  lineHeight: "16px",
  textAlign: "center",
  fontWeight: 700,
  color: "#0e141b",
} as const;
function Dot({ dot }: { dot: TabDot }) {
  if (dot.kind === "count") return <span role="img" aria-label={dot.label} style={{ ...dotStyle, background: TONE_COLOR.warn, padding: "0 4px" }}>{dot.n}</span>;
  if (dot.kind === "attention") return <span role="img" aria-label={TAB_DOT_ATTENTION} style={{ ...dotStyle, background: TONE_COLOR.warn }}>!</span>;
  return <span role="img" aria-label={TAB_DOT_UPDATE} style={{ ...dotStyle, background: TONE_COLOR.info }}>↑</span>;
}

export function TabBar({ tab, onTab, disabled, dots }: { tab: TabId; onTab: (t: TabId) => void; disabled: (t: TabId) => boolean; dots: (t: TabId) => TabDot | null }) {
  return (
    <Focusable flow-children="row" style={{ display: "flex", gap: 4, overflowX: "auto", padding: "4px 0 8px" }}>
      {TAB_ORDER.map((id) => {
        const dot = dots(id);
        const on = tab === id;
        return (
          <DialogButton
            key={id}
            disabled={disabled(id)}
            onClick={() => onTab(id)}
            aria-selected={on}
            style={{
              position: "relative",
              flex: "0 0 auto",
              width: "auto",
              minWidth: 0,
              height: 44,
              padding: "0 16px",
              fontWeight: on ? 700 : 500,
              background: on ? "#1a73c9" : undefined,
              color: on ? "#fff" : undefined,
              borderBottom: on ? "3px solid #fff" : "3px solid transparent",
            }}
          >
            {TAB_LABELS[id]}
            {dot && <Dot dot={dot} />}
          </DialogButton>
        );
      })}
    </Focusable>
  );
}

// ---- avisos fijos ----
export function BannerList({ items, onAction }: { items: Banner[]; onAction: (b: Banner) => void }) {
  if (items.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 8 }}>
      {items.map((b) => (
        <div
          key={b.id}
          role={b.tone === "err" ? "alert" : "status"}
          style={{ borderLeft: `4px solid ${TONE_COLOR[b.tone]}`, background: TONE_BG[b.tone], borderRadius: 4, padding: "8px 10px" }}
        >
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <span aria-hidden="true" style={{ color: TONE_COLOR[b.tone], fontWeight: 700, minWidth: 14 }}>{TONE_ICON[b.tone]}</span>
            <div style={WRAP}>
              <b>{b.title}</b>
              <div>{b.text}</div>
            </div>
          </div>
          {b.action && (
            <DialogButton style={{ marginTop: 6, height: 44, width: "100%" }} onClick={() => onAction(b)}>
              {b.action.label}
            </DialogButton>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- progreso: barra simple (la ProgressBar de Decky se busca por webpack y puede no existir) ----
export function Bar({ pct }: { pct: number }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  return (
    <div role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} style={{ height: 8, borderRadius: 4, background: "#ffffff22", overflow: "hidden" }}>
      <div style={{ width: `${v}%`, height: "100%", background: TONE_COLOR.info }} />
    </div>
  );
}

const ROW_TONE: Record<ProgressRow["kind"], Tone> = { done: "ok", run: "info", wait: "nf", fail: "err", conflict: "warn", skip: "info", left: "nf" };
export function RunList({ rows }: { rows: ProgressRow[] }) {
  return (
    <div role="list" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {rows.map((r) => (
        <div key={r.id} role="listitem" style={{ display: "flex", justifyContent: "space-between", gap: 8, color: TONE_COLOR[ROW_TONE[r.kind]] }}>
          <span style={{ ...WRAP, color: "inherit", fontWeight: r.kind === "run" ? 700 : 400 }}>{r.name}</span>
          <span style={{ whiteSpace: "nowrap" }}>{r.text}</span>
        </div>
      ))}
    </div>
  );
}
