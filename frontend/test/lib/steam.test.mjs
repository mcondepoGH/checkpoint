import test from 'node:test';
import assert from 'node:assert/strict';
import { STEAM_POLL_MS, failureOf, normalizeDismissed, normalizeSuggestions, showBlock } from '#src/lib/steam.js';
import { startPolling } from '#src/lib/poll.js';
import { es, en, flat } from '../helpers/locales.mjs';

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

test('consulta cada 5 s', () => assert.equal(STEAM_POLL_MS, 5000));

test('normalizeSuggestions limpia filas y tolera basura', () => {
  const rows = normalizeSuggestions([sug(), null, { name: 'sin id' }, sug({ id: 's2', device_name: null, appid: 'x' })]);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], {
    id: 's1',
    appid: 292030,
    steamName: 'The Witcher 3 GOTY',
    game: 'witcher',
    gameName: 'The Witcher 3',
    device: 'deck',
    deviceName: 'Steam Deck',
  });
  assert.equal(rows[1].deviceName, 'deck', 'sin nombre de dispositivo se muestra su id');
  assert.equal(rows[1].appid, 0);
  assert.deepEqual(normalizeSuggestions(null), []);
  assert.deepEqual(normalizeSuggestions({}), []);
});

test('normalizeDismissed limpia filas y usa el id si el juego ya no existe', () => {
  const rows = normalizeDismissed([
    { id: 'd1', appid: 5, steam_name: 'X', game: 'g', game_name: null },
    { id: 'd2', appid: 6, steam_name: 'Y', game: 'h', game_name: 'Hache' },
    {},
    null,
  ]);
  assert.deepEqual(rows, [
    { id: 'd1', appid: 5, steamName: 'X', game: 'g', gameName: 'g' },
    { id: 'd2', appid: 6, steamName: 'Y', game: 'h', gameName: 'Hache' },
  ]);
  assert.deepEqual(normalizeDismissed(undefined), []);
});

test('el bloque solo aparece con sugerencias, descartes o un aviso', () => {
  assert.equal(showBlock([], [], null), false);
  assert.equal(showBlock([1], [], null), true);
  assert.equal(showBlock([], [1], null), true);
  assert.equal(showBlock([], [], { variant: 'ok' }), true);
});

test('failureOf: cada código del backend tiene mensaje claro y dice si refrescar', () => {
  const f = (status, code) => failureOf({ status, code });
  assert.deepEqual(f(404, 'err.steam.suggestion_unknown'), { body: { code: 'steam.gone', params: {} }, refresh: true });
  assert.deepEqual(f(404, 'err.steam.game_unknown'), { body: { code: 'steam.gameGone', params: {} }, refresh: true });
  assert.deepEqual(f(409, 'err.steam.game_has_appid'), { body: { code: 'steam.gameHasAppid', params: {} }, refresh: true });
  assert.deepEqual(f(409, 'err.steam.appid_in_use'), { body: { code: 'steam.appidInUse', params: {} }, refresh: true });
  assert.deepEqual(f(409, 'err.main.config_changed'), { body: { code: 'steam.configChanged', params: {} }, refresh: false });
  assert.deepEqual(f(404, 'err.steam.dismissed_unknown'), { body: { code: 'steam.dismissedGone', params: {} }, refresh: true });
  assert.equal(failureOf({ status: 404 }).body.code, 'steam.gone');
  assert.equal(failureOf(new Error('red'), 'accept').body.code, 'steam.failAccept');
  assert.equal(failureOf(new Error('red'), 'dismiss').body.code, 'steam.failDismiss');
  assert.equal(failureOf(new Error('red'), 'forget').body.code, 'steam.failForget');
  const other = failureOf({ status: 422, code: 'err.main.config_invalid', params: { a: 1 } });
  assert.deepEqual(other.body, { code: 'err.main.config_invalid', params: { a: 1 } });
});

test('el sondeo funciona con temporizadores que exigen this === globalThis', () => {
  // Doble que imita el navegador: setInterval/clearInterval lanzan si no se llaman sobre globalThis.
  const real = { si: globalThis.setInterval, ci: globalThis.clearInterval };
  const calls = [];
  globalThis.setInterval = function (fn, ms) {
    if (this !== globalThis) throw new TypeError('Illegal invocation');
    calls.push(['set', ms]);
    return 42;
  };
  globalThis.clearInterval = function (id) {
    if (this !== globalThis) throw new TypeError('Illegal invocation');
    calls.push(['clear', id]);
  };
  try {
    let n = 0;
    const stop = startPolling(() => n++, STEAM_POLL_MS, null);
    stop();
    assert.equal(n, 1);
    assert.deepEqual(calls, [
      ['set', 5000],
      ['clear', 42],
    ]);
  } finally {
    globalThis.setInterval = real.si;
    globalThis.clearInterval = real.ci;
  }
});

test('los mensajes que usa la lógica existen en es y en', () => {
  const keys = [
    'steam.gone',
    'steam.gameGone',
    'steam.gameHasAppid',
    'steam.appidInUse',
    'steam.configChanged',
    'steam.dismissedGone',
    'steam.failAccept',
    'steam.failDismiss',
    'steam.failForget',
    'steam.accepted',
    'steam.acceptedDirty',
    'steam.dismissedNow',
    'steam.forgotten',
  ];
  for (const cat of [es, en]) {
    const f = Object.fromEntries(flat(cat));
    for (const k of keys) assert.ok(f[k], k);
  }
});
