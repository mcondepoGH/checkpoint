// Bloque «Sugerencias de Steam» (SteamList) renderizado a HTML.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { SteamList } from '#src/components/config/SteamSuggestions.jsx';
  import { normalizeSuggestions, normalizeDismissed } from '#src/lib/steam.js';
  export { React, renderToStaticMarkup, SteamList, normalizeSuggestions, normalizeDismissed };`,
  { tag: 'ckpt-steam' },
);

const has = (h, s) => h.includes(s);
const sug = (o = {}) => ({
  id: 's1',
  appid: 292030,
  steam_name: 'The Witcher 3 GOTY',
  game: 'witcher',
  game_name: 'The Witcher 3',
  device: 'deck',
  device_name: 'Steam Deck',
  ...o,
});
const dis = (o = {}) => ({ id: 'd1', appid: 5, steam_name: 'Hades Demo', game: 'hades', game_name: 'Hades', ...o });
const list = (rows, dismissed = [], props = {}) =>
  mod.renderToStaticMarkup(
    mod.React.createElement(mod.SteamList, {
      rows: mod.normalizeSuggestions(rows),
      dismissed: mod.normalizeDismissed(dismissed),
      busy: null,
      notice: null,
      dirty: false,
      onAccept() {},
      onDiscard() {},
      onForget() {},
      onCloseNotice() {},
      ...props,
    }),
  );

test('sin sugerencias, descartes ni aviso no se pinta nada', { skip }, () => {
  assert.equal(list([]), '');
});

test('fila: nombre de Steam, appid, juego propuesto, dispositivo y botones', { skip }, () => {
  const h = list([sug()]);
  assert.ok(has(h, 'Sugerencias de Steam'));
  assert.ok(has(h, 'The Witcher 3 GOTY') && has(h, '292030') && has(h, 'The Witcher 3') && has(h, 'Steam Deck'));
  assert.ok(has(h, '>Aceptar<') && has(h, '>Descartar<'));
  assert.ok(!/<button[^>]*disabled/.test(h));
});

test('varias sugerencias', { skip }, () => {
  const h = list([sug(), sug({ id: 's2', appid: 9, steam_name: 'Otro', game_name: 'Mi Otro' })]);
  assert.equal(h.split('pairing-row').length - 1, 2);
  assert.ok(has(h, 'Mi Otro'));
});

test('el nombre de Steam se escapa (no es HTML)', { skip }, () => {
  const h = list([sug({ steam_name: '<img src=x onerror=alert(1)>' })]);
  assert.ok(!has(h, '<img') && has(h, '&lt;img'));
});

test('descartes: plegados por defecto, con botón Olvidar', { skip }, () => {
  const h = list([], [dis()]);
  assert.ok(has(h, 'Descartes recordados') && has(h, 'Hades Demo') && has(h, '>Olvidar<'));
  assert.ok(/<details(?![^>]*\bopen\b)/.test(h), 'details cerrado');
  assert.ok(!has(h, 'Sugerencias de Steam<'), 'sin sugerencias no hay título de sugerencias vacío');
});

test('en curso: todos los botones deshabilitados', { skip }, () => {
  const h = list([sug(), sug({ id: 's2' })], [dis()], { busy: 's1' });
  assert.equal((h.match(/<button[^>]*disabled/g) || []).length, 5);
});

test('borrador sucio: avisa; limpio: no', { skip }, () => {
  assert.ok(has(list([sug()], [], { dirty: true }), 'cambios sin guardar'));
  assert.ok(!has(list([sug()], [], { dirty: false }), 'cambios sin guardar'));
});

test('avisos: éxito, borrador sucio y error', { skip }, () => {
  const ok = list([], [], { notice: { variant: 'ok', body: { code: 'steam.accepted', params: { game: 'Hades', appid: 1 } } } });
  assert.ok(has(ok, 'alert ok') && has(ok, 'Hades'));
  const warn = list([], [], { notice: { variant: 'warn', body: { code: 'steam.acceptedDirty', params: { game: 'Hades', appid: 1 } } } });
  assert.ok(has(warn, 'alert warn') && has(warn, 'Guarda o descarta'));
  const err = list([sug()], [], { notice: { variant: 'error', body: { code: 'steam.configChanged', params: {} } } });
  assert.ok(has(err, 'alert error') && has(err, 'Vuelve a pulsar Aceptar'));
  for (const code of ['steam.gone', 'steam.gameHasAppid', 'steam.appidInUse', 'steam.gameGone', 'steam.dismissedGone']) {
    assert.ok(has(list([], [], { notice: { variant: 'error', body: { code, params: {} } } }), 'alert error'), code);
  }
});

test('en inglés se pinta con el mismo conjunto de claves', { skip }, async () => {
  const { es, en, flat } = await import('../../helpers/locales.mjs');
  const keys = (c) =>
    flat(c)
      .map(([k]) => k)
      .filter((k) => k.startsWith('steam.') || k.startsWith('err.steam.'))
      .sort();
  assert.ok(keys(es).length > 20);
  assert.deepEqual(keys(es), keys(en));
});
