import React from 'react';
import { WatchBar } from '#src/components/ui/index.js';
import { clock } from '#src/components/watch/watch.js';
import { useI18n } from '#src/hooks/useI18n.js';

// Barra «Jugando en <dispositivo>» de cada dispositivo http que juega a este juego (avisa el plugin, no el hub: sin latido).
// Es la misma WatchBar, la misma clave (`sync.watch.bar.running`) y el mismo «desde HH:MM» que la vigilancia de los dispositivos clásicos:
// sin caducidad ni resultado (el resultado de la sync local queda en el Registro de ejecuciones). `playing` es el de la respuesta de /api/watches.
export default function PlayingBars({ game, playing = [], devName }) {
  const { t, locale } = useI18n();
  const mine = playing.filter((p) => p.game === game).sort((a, b) => String(a.device).localeCompare(String(b.device)));
  return mine.map((p) => (
    <WatchBar key={`playing|${p.device}`} state="running" since={t('sync.watch.since', { time: clock(p.since, locale) })}>
      {t('sync.watch.bar.running', { device: devName(p.device) })}
    </WatchBar>
  ));
}
