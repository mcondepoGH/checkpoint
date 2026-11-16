// Juego desactivado en Sync, Versiones, Lanzadores y el contador de vigilancia (render a HTML, es y en).
// Usa esbuild (viene con Vite); si no está disponible el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { bundle } from '../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import Sync from '#src/pages/Sync.jsx';
  import Versions from '#src/pages/Versions.jsx';
  import WatchSummary from '#src/components/watch/WatchSummary.jsx';
  import LauncherBlock from '#src/components/launchers/LauncherBlock.jsx';
  export { React, renderToStaticMarkup, i18n, Sync, Versions, WatchSummary, LauncherBlock };`,
  { navigator: true, tag: 'ckpt-disabled' },
);

const has = (h, s) => h.includes(s);
const R = (C, props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m[C], props));
};
const dev = { name: 'PC' };
const mk = (games) => ({ devices: { pc: dev, tv: { name: 'TV' } }, games });
const ON = { name: 'Activo', devices: ['pc', 'tv'] };
const OFF = { name: 'Apagado', devices: ['pc', 'tv'], enabled: false };

test('Sync: el desactivado es visible, atenuado, con etiqueta, sin Sincronizar/Simulación y con ir a Configuración', { skip }, () => {
  const h = R('Sync', { config: mk({ a: ON, b: OFF }), onGoSettings() {} });
  assert.equal((h.match(/game-disabled/g) || []).length, 1);
  assert.ok(has(h, 'Apagado') && has(h, 'Desactivado'));
  const card = h.slice(h.indexOf('game-disabled'));
  const cardOff = card;
  assert.ok(has(cardOff, 'Ir a Configuración'));
  assert.equal((h.match(/btn primary">Sincronizar/g) || []).length, 1, 'solo el juego activo tiene botón Sincronizar');
  assert.equal((h.match(/Simulación/g) || []).length, 1, 'solo el juego activo tiene Simulación');
  assert.ok(!has(h, 'Todos los juegos están desactivados'));
});

test('Sync: todos desactivados lo dice y no hay botón Sincronizar', { skip }, () => {
  const h = R('Sync', { config: mk({ b: OFF }), onGoSettings() {} });
  assert.ok(has(h, 'Todos los juegos están desactivados') && has(h, 'game-disabled'));
  assert.ok(!has(h, 'btn primary">Sincronizar') && !has(h, 'Simulación'));
  const en = R('Sync', { config: mk({ b: OFF }), onGoSettings() {} }, 'en');
  assert.ok(has(en, 'All games are disabled') && has(en, 'Disabled'));
});

test('Versiones: el juego desactivado sale con sufijo y nota; el activo no', { skip }, () => {
  const h = R('Versions', { config: mk({ a: ON, b: OFF }), onGoSettings() {} });
  assert.ok(has(h, 'Apagado (desactivado)') && has(h, 'Activo</option>'));
  assert.ok(!has(h, 'Activo (desactivado)'));
  const only = R('Versions', { config: mk({ b: OFF }), onGoSettings() {} });
  assert.ok(has(only, 'restaurar solo copia al hub'));
  assert.ok(!has(R('Versions', { config: mk({ a: ON }), onGoSettings() {} }), 'restaurar solo copia'));
  assert.ok(has(R('Versions', { config: mk({ b: OFF }) }, 'en'), 'Apagado (disabled)'));
});

test('WatchSummary: no cuenta los desactivados', { skip }, () => {
  const w = (game) => ({
    game,
    device: 'pc',
    state: 'running',
    since: '2026-01-01T11:00:00Z',
    last_poll: '2026-01-01T11:59:55Z',
    poll: 15,
  });
  const watch = { now: '2026-01-01T12:00:00Z', watches: [w('a'), w('b')] };
  assert.equal(R('WatchSummary', { watch, config: mk({ a: ON, b: OFF }), open: true }).includes('Apagado'), false);
  assert.ok(has(R('WatchSummary', { watch, config: mk({ a: ON, b: OFF }), open: true }), 'Activo'));
  assert.equal(R('WatchSummary', { watch: { ...watch, watches: [w('b')] }, config: mk({ b: OFF }) }), '');
});

test('LauncherBlock: nota «Desactivado: el aviso se omitirá» solo con el juego desactivado', { skip }, () => {
  const g = (o = {}) => ({ sel: 'j-1', id: 'j-1', name: 'J', process: 'j.exe', devices: [{ id: 'pc', name: 'PC' }], ...o });
  const props = (game) => ({
    games: [game],
    active: true,
    defaultHub: 'http://h:1',
    initial: { loaded: true, key: 'ck_abc', status: null },
    now: new Date('2026-11-09T12:00:00Z'),
  });
  const off = R('LauncherBlock', props(g({ enabled: false })));
  assert.ok(has(off, 'Desactivado: el aviso se omitirá.'));
  assert.ok(!has(R('LauncherBlock', props(g({ enabled: true }))), 'el aviso se omitirá'));
  assert.ok(!has(R('LauncherBlock', props(g())), 'el aviso se omitirá'), 'sin el campo cuenta como activo');
  assert.ok(has(R('LauncherBlock', props(g({ enabled: false })), 'en'), 'Disabled: the notice will be skipped.'));
});

const HTTP = { name: 'Solo http', devices: ['deck'] };
const MIX = { name: 'Mezcla', devices: ['pc', 'deck'] };
const mkh = (games) => ({ devices: { pc: dev, deck: { name: 'Deck', http: true } }, games });

test('Sync: juego solo http sin Sincronizar ni Simulación y con la línea del plugin (es y en)', { skip }, () => {
  const h = R('Sync', { config: mkh({ a: HTTP }) });
  assert.ok(!has(h, 'btn primary">Sincronizar') && !has(h, 'Simulación'));
  assert.ok(has(h, 'Se sincroniza desde el propio dispositivo<'));
  const en = R('Sync', { config: mkh({ a: HTTP }) }, 'en');
  assert.ok(!has(en, 'Dry run') && !has(en, 'btn primary">Sync'));
  assert.ok(has(en, 'Syncs from the device itself<'));
});

test('Sync: juego mixto clásico + http mantiene el botón y la simulación', { skip }, () => {
  const h = R('Sync', { config: mkh({ a: MIX }) });
  assert.equal((h.match(/btn primary">Sincronizar/g) || []).length, 1);
  assert.equal((h.match(/Simulación/g) || []).length, 1);
  assert.ok(!has(h, 'Se sincroniza desde el propio dispositivo'));
});

test('Sync: solo http conserva «Jugando» y el último resultado de PlayingBars', { skip }, () => {
  const watch = {
    now: '2026-01-01T10:00:00Z',
    watches: [],
    playing: [{ game: 'a', device: 'deck', since: '2026-01-01T10:00:00Z', expires: '2026-01-01T22:00:00Z' }],
    results: [],
  };
  const h = R('Sync', { config: mkh({ a: HTTP }), watch });
  assert.ok(has(h, 'Jugando en Deck'));
  assert.ok(!has(h, 'btn primary">Sincronizar'));
});

test(
  'Sync: la etiqueta «Solo checkpoint» va en la cabecera (h3) junto a la insignia, no en una fila propia; meter y última sync anclados al fondo',
  { skip },
  () => {
    const SOLO = { name: 'Solo', devices: ['pc'] };
    const h = R('Sync', { config: mk({ a: SOLO, b: ON }) });
    const cards = h.split('<h3').slice(1);
    const solo = cards.find((c) => c.includes('Solo checkpoint'));
    assert.ok(solo, 'la etiqueta se pinta');
    const head = solo.slice(0, solo.indexOf('</h3>'));
    assert.ok(has(head, 'game-name') && has(head, 'Solo checkpoint'), 'etiqueta en el mismo h3 que el nombre y la insignia');
    assert.ok(!/<p>\s*<span class="pill/.test(h), 'sin fila <p> propia para la etiqueta');
    assert.equal((h.match(/Solo checkpoint/g) || []).length, 1, 'solo la lleva el juego de un dispositivo');
    assert.ok(has(h, 'class="game-last"'), 'meter y última sync en un bloque inferior');
    const css = fs.readFileSync(new URL('../../src/styles/_components.scss', import.meta.url), 'utf8');
    assert.match(css, /\.game-last\s*\{[^}]*margin-top:\s*auto/);
  },
);
