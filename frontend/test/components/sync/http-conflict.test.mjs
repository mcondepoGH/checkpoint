// Conflicto de datos de un juego solo http: funciones puras, estado de /api/watches y render estático del aviso
// (botones, resolución pendiente y cancelar). Sin navegador.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import HttpConflicts from '#src/components/sync/HttpConflicts.jsx';
  import { httpConflictItems, resolutionBody } from '#src/components/sync/httpConflict.js';
  import { watchState, NO_WATCHES } from '#src/hooks/useWatches.js';
  import Sync from '#src/pages/Sync.jsx';
  export { React, renderToStaticMarkup, i18n, HttpConflicts, httpConflictItems, resolutionBody, watchState, NO_WATCHES, Sync };`,
  { navigator: true, tag: 'ckpt-http-conflict' },
);
const has = (h, s) => h.includes(s);
const H = 'a'.repeat(64);
const D = 'b'.repeat(64);
const C = (o = {}) => ({ game: 'g', device: 'deck', reason: 'both-changed', hub: H, device_hash: D, at: '2026-01-01T10:00:00Z', ...o });
const R = (o = {}) => ({
  game: 'g',
  device: 'deck',
  winner: 'hub',
  by: 'web',
  at: '2026-01-01T10:05:00Z',
  expires: '2026-01-02T10:05:00Z',
  ...o,
});
const devName = (id) => (id === 'deck' ? 'Steam Deck' : id);

test('watchState conserva conflicts y resolutions y tolera un hub antiguo', { skip }, () => {
  const s = m.watchState({ now: 'x', watches: [], conflicts: [C()], resolutions: [R()] });
  assert.equal(s.conflicts.length, 1);
  assert.equal(s.resolutions.length, 1);
  assert.deepEqual(m.watchState({ now: 'x' }).conflicts, []);
  assert.deepEqual(m.watchState({ conflicts: 'no', resolutions: 3 }).resolutions, []);
  assert.deepEqual(m.NO_WATCHES.conflicts, []);
  assert.deepEqual(m.NO_WATCHES.resolutions, []);
});

test('httpConflictItems: solo el juego pedido, uno por dispositivo, con su resolución', { skip }, () => {
  const items = m.httpConflictItems(
    { conflicts: [C(), C({ device: 'tab' }), C({ game: 'otro' })], resolutions: [R(), R({ game: 'otro', device: 'deck' })] },
    'g',
  );
  assert.deepEqual(
    items.map((i) => [i.device, !!i.conflict, i.resolution?.winner ?? null]),
    [
      ['deck', true, 'hub'],
      ['tab', true, null],
    ],
  );
  assert.deepEqual(m.httpConflictItems(undefined, 'g'), []);
  assert.deepEqual(m.httpConflictItems({ conflicts: [], resolutions: [] }, 'g'), []);
});

test('resolutionBody: dispositivo, ganador y huellas del conflicto registrado', { skip }, () => {
  assert.deepEqual(m.resolutionBody(C(), 'hub'), { device: 'deck', winner: 'hub', expect: { hub: H, device: D } });
  assert.deepEqual(m.resolutionBody(C(), 'device').winner, 'device');
});

const render = (props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.HttpConflicts, { game: 'g', gameName: 'Juego', devName, ...props }));
};

test('aviso de conflicto: texto, dos botones con el nombre del dispositivo, es y en', { skip }, () => {
  const h = render({ items: [{ device: 'deck', conflict: C(), resolution: null }] });
  assert.ok(has(h, 'role="alert"') && has(h, 'Conflicto:') && has(h, 'Steam Deck'));
  assert.ok(has(h, 'Usar los datos del hub') && has(h, 'Usar los de Steam Deck'));
  assert.ok(!has(h, 'Resolución pendiente'));
  const en = render({ items: [{ device: 'deck', conflict: C(), resolution: null }] }, 'en');
  assert.ok(has(en, 'Conflict:') && has(en, 'Use the hub') && has(en, 'Use Steam Deck'));
});

test('resolución pendiente: aviso con Cancelar y sin botones de resolver', { skip }, () => {
  const items = [{ device: 'deck', conflict: C(), resolution: R({ winner: 'device' }) }];
  const h = render({ items });
  assert.ok(has(h, 'Resolución pendiente') && has(h, 'Steam Deck') && has(h, 'Cancelar'));
  assert.ok(!has(h, 'Usar los datos del hub') && !has(h, 'Usar los de'));
  assert.ok(has(render({ items }, 'en'), 'Pending resolution'));
});

test('sin conflictos ni resoluciones no pinta nada', { skip }, () => {
  assert.equal(render({ items: [] }), '');
});

const mk = (games) => ({ devices: { deck: { name: 'Steam Deck', http: true }, pc: { name: 'PC' } }, games });
const W = (o) => ({ ...m.NO_WATCHES, ...o });
const sync = (config, watch) => {
  m.i18n.setLocale('es');
  return m.renderToStaticMarkup(m.React.createElement(m.Sync, { config, watch }));
};

test('tarjeta Sincronizar: el aviso sale solo en juegos solo http', { skip }, () => {
  const watch = W({ conflicts: [C()], resolutions: [] });
  const http = sync(mk({ g: { name: 'CoC', devices: ['deck'] } }), watch);
  assert.ok(has(http, 'Usar los datos del hub') && has(http, 'Usar los de Steam Deck'));
  assert.ok(!has(http, 'con el plugin'));
  const mixed = sync(mk({ g: { name: 'Mixto', devices: ['deck', 'pc'] } }), watch);
  assert.ok(!has(mixed, 'Usar los datos del hub'));
  const other = sync(mk({ h: { name: 'Otro', devices: ['deck'] } }), watch);
  assert.ok(!has(other, 'Usar los datos del hub'));
});
