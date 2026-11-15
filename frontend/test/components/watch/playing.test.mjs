// «Jugando ahora» de dispositivos http (los avisa el plugin): lógica pura, estado compartido y barras de la pestaña Sincronizar.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';
import { originOf } from '#src/components/autosync/runLog.js';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import { WatchBar } from '#src/components/ui/index.js';
  import PlayingBars from '#src/components/watch/PlayingBars.jsx';
  import { watchState, NO_WATCHES } from '#src/hooks/useWatches.js';
  import { SYNC_STATES, clock } from '#src/components/watch/watch.js';
  import { RunEntry } from '#src/components/autosync/AutoSyncLog.jsx';
  export { React, renderToStaticMarkup, i18n, PlayingBars, watchState, NO_WATCHES, SYNC_STATES, WatchBar, RunEntry, clock };`,
  { navigator: true, tag: 'ckpt-playing' },
);
const has = (h, s) => h.includes(s);
const P = (o = {}) => ({ game: 'a', device: 'deck', since: '2026-01-01T10:00:00Z', expires: '2026-01-01T22:00:00Z', ...o });
const R = (o = {}) => ({ game: 'a', device: 'deck', at: '2026-01-01T10:00:00Z', trigger: 'hook_opened', state: 'uploaded', ...o });
const devName = (id) => (id === 'deck' ? 'Steam Deck' : id);
const bars = (props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.PlayingBars, { devName, game: 'a', ...props }));
};

test('watchState conserva playing y results y tolera respuestas raras (hub antiguo)', () => {
  const s = m.watchState({ now: 'x', watches: [], playing: [P()], results: [R()] });
  assert.equal(s.playing.length, 1);
  assert.equal(s.results.length, 1);
  assert.deepEqual(m.watchState({ now: 'x', watches: [] }).playing, []);
  assert.deepEqual(m.watchState({ playing: 'no', results: 3 }).results, []);
  assert.deepEqual(m.NO_WATCHES.playing, []);
});

test('estados de resultado cerrados', () => {
  assert.deepEqual(m.SYNC_STATES, ['uploaded', 'downloaded', 'up_to_date', 'missing_dir', 'no_path', 'conflict', 'error']);
});

test('barra «Jugando en»: idéntica a la vigilancia clásica (con «desde HH:MM»), sin caducidad ni resultado (es/en)', { skip }, () => {
  const h = bars({ playing: [P({ result: { state: 'uploaded' } })], results: [R()] });
  m.i18n.setLocale('es');
  const since = m.i18n.t('sync.watch.since', { time: m.clock(P().since, m.i18n.locale) });
  const classic = m.renderToStaticMarkup(
    m.React.createElement(m.WatchBar, { state: 'running', since }, m.i18n.t('sync.watch.bar.running', { device: 'Steam Deck' })),
  );
  assert.equal(h, classic, h);
  assert.ok(has(h, 'Jugando en Steam Deck') && has(h, 'role="status"') && has(h, 'watch-bar running'), h);
  assert.ok(has(h, 'watch-since') && has(h, 'desde'), h);
  for (const x of ['caduca', 'Subido', 'último resultado', '>deck<', 'playing-last']) assert.ok(!has(h, x), `${x}: ${h}`);
  const e = bars({ playing: [P({ result: { state: 'up_to_date' } })], results: [] }, 'en');
  assert.ok(has(e, 'Playing on Steam Deck') && !has(e, 'No changes') && !has(e, 'expires') && has(e, 'watch-since'), e);
});

test('solo las barras de este juego, una por dispositivo; sin «último resultado» al dejar de jugar', { skip }, () => {
  const h = bars({ playing: [P(), P({ game: 'b', device: 'pc' })], results: [R({ device: 'pc' })] });
  assert.ok(has(h, 'Jugando en Steam Deck') && !has(h, 'pc'), h);
  assert.equal(bars({ playing: [], results: [R({ state: 'downloaded' })] }), '');
});

test('registro: hook_opened es Launcher; resultado visible en la fila', { skip }, () => {
  assert.equal(originOf('hook_opened'), 'launcher');
  m.i18n.setLocale('es');
  const e = {
    id: 'x',
    started: '2026-01-01T10:00:00Z',
    duration: 0,
    trigger: 'hook_opened',
    result: 'ok',
    device: 'deck',
    code: 'hook.sync.uploaded',
    params: {},
    message: '',
    games: { a: { name: 'Juego', result: 'ok', code: 'hook.sync.uploaded', params: {}, message: '' } },
  };
  const h = m.renderToStaticMarkup(m.React.createElement(m.RunEntry, { entry: e }));
  assert.ok(has(h, 'origin-launcher') && has(h, 'Subido al hub'), h);
});
