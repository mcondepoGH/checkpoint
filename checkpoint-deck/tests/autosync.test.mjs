// Detección de abrir/cerrar juegos y toasts (src/autosync.ts). Sin Decky ni Steam: `SteamClient` falso.
// Se compila con el esbuild del frontend del hub (../frontend/node_modules); sin él, se omite.
// Ejecutar: node --test tests/autosync.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
let esbuild;
try {
  esbuild = createRequire(import.meta.url)(join(here, '../../frontend/node_modules/esbuild'));
} catch {
  /* sin esbuild: se omite */
}
const skip = esbuild ? false : 'falta ../frontend/node_modules/esbuild';

async function load() {
  const out = join(mkdtempSync(join(tmpdir(), 'as-')), 'as.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/autosync.ts')], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  return import(pathToFileURL(out));
}

function fakeSteam() {
  const s = { cb: null, unregistered: 0 };
  s.client = {
    GameSessions: {
      RegisterForAppLifetimeNotifications: (cb) => {
        s.cb = cb;
        return { unregister: () => s.unregistered++ };
      },
    },
  };
  return s;
}

test('abrir y cerrar se envían con appid y estado', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const sent = [];
  startGameWatch(s.client, (a, r) => sent.push([a, r]), () => assert.fail('sin problemas'));
  s.cb({ unAppID: 730, nInstanceID: 1, bRunning: true });
  s.cb({ unAppID: 730, nInstanceID: 1, bRunning: false });
  assert.deepEqual(sent, [[730, true], [730, false]]);
});

test('repetidos seguidos iguales se ignoran (varias instancias del mismo aviso)', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const sent = [];
  startGameWatch(s.client, (a, r) => sent.push([a, r]), () => {});
  s.cb({ unAppID: 5, bRunning: true });
  s.cb({ unAppID: 5, bRunning: true });
  s.cb({ unAppID: 6, bRunning: true });
  s.cb({ unAppID: 5, bRunning: false });
  s.cb({ unAppID: 5, bRunning: false });
  assert.deepEqual(sent, [[5, true], [6, true], [5, false]]);
});

test('avisos mal formados o de juegos que no son de Steam (appid 0) se ignoran', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const sent = [];
  startGameWatch(s.client, (a, r) => sent.push([a, r]), () => {});
  for (const bad of [null, undefined, {}, { unAppID: 0, bRunning: true }, { unAppID: -3, bRunning: true }, { unAppID: '7', bRunning: true }, { unAppID: 7 }, { unAppID: 1.5, bRunning: true }])
    s.cb(bad);
  assert.deepEqual(sent, []);
});

test('si enviar falla, se avisa del problema y no se rompe el escuchador', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const problems = [];
  startGameWatch(s.client, () => { throw new Error('backend caído'); }, (e) => problems.push(e.message));
  s.cb({ unAppID: 9, bRunning: true });
  assert.equal(problems.length, 1);
  assert.match(problems[0], /backend caído/);
});

test('sin la API interna de Steam se avisa y no se lanza', { skip }, async () => {
  const { startGameWatch } = await load();
  const problems = [];
  for (const steam of [undefined, {}, { GameSessions: {} }]) {
    const stop = startGameWatch(steam, () => {}, (e) => problems.push(e.message));
    stop();
  }
  assert.equal(problems.length, 3);
  assert.match(problems[0], /SteamClient/);
});

test('si registrar lanza, se avisa', { skip }, async () => {
  const { startGameWatch } = await load();
  const problems = [];
  const steam = { GameSessions: { RegisterForAppLifetimeNotifications: () => { throw new Error('API cambió'); } } };
  startGameWatch(steam, () => {}, (e) => problems.push(e.message));
  assert.match(problems[0], /API cambió/);
});

test('detener quita el registro una sola vez', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const stop = startGameWatch(s.client, () => {}, () => {});
  stop();
  stop();
  assert.equal(s.unregistered, 1);
});

const TOAST_BODIES = {
  downloaded: 'Partida actualizada desde el hub',
  uploaded: 'Partida enviada al hub correctamente',
  up_to_date: 'Partida al día, sin cambios pendientes',
  no_path: 'Falta la carpeta de guardado del juego',
  missing_dir: 'No se encuentra la carpeta de guardado',
  conflict: 'Conflicto: elige qué partida conservar',
  joined: 'Juego unido a esta Deck correctamente',
  sync_failed: 'No se pudo sincronizar: revisa los avisos',
  queued: 'Sin conexión: sincronizará al reconectar',
  offline_open: 'Sin conexión: no se pudo sincronizar',
  unauthorized: 'Clave no válida: vuelve a vincular',
};

test('toast de cada aviso: sin nombre de juego, exacto, nivel y código intactos', { skip }, async () => {
  const { noticeText } = await load();
  for (const [code, body] of Object.entries(TOAST_BODIES)) {
    for (const game of ['Uno', 'Half-Life 2', null]) {
      const t = noticeText({ id: 1, code, game, level: 'info', params: {} });
      assert.equal(t.body, body);
      assert.equal(t.title, 'Checkpoint');
      assert.equal(t.code, code);
      if (game) assert.ok(!t.body.includes(game) && !t.title.includes(game));
    }
  }
  assert.equal(noticeText({ id: 1, code: 'conflict', game: 'Uno', level: 'warning', params: {} }).level, 'warning');
  assert.match(noticeText({ id: 1, code: 'algo_nuevo', game: 'Uno', level: 'info', params: {} }).body, /^Nuevo aviso de Checkpoint$/);
});

test('ningún toast pasa de 45 caracteres ni lleva punto final, con cualquier nombre de juego', { skip }, async () => {
  const { noticeText, TOAST_MAX } = await load();
  assert.equal(TOAST_MAX, 45);
  const codes = [...Object.keys(TOAST_BODIES), 'algo_nuevo_con_un_codigo_larguisimo'];
  for (const game of ['X', 'Call of Cthulhu: Dark Corners of the Earth', 'Ñ'.repeat(200), null]) {
    for (const code of codes) {
      const b = noticeText({ id: 1, code, game, level: 'info', params: { files: 123456, reason: 'x'.repeat(300) } }).body;
      assert.ok([...b].length <= 45, `${code}: ${b.length} > 45: ${b}`);
      assert.ok(!b.endsWith('.') && !b.includes('…'), b);
    }
  }
});

test('aviso (panel): nombre completo del juego; sin juego no se inventa nombre', { skip }, async () => {
  const { noticeFullText } = await load();
  const game = 'Ñ'.repeat(120);
  const n = (code, extra = {}) => ({ id: 1, code, game, level: 'info', params: {}, ...extra });
  assert.equal(noticeFullText(n('downloaded')), `${game}: partida actualizada desde el hub`);
  assert.equal(noticeFullText(n('uploaded')), `${game}: partida enviada al hub correctamente`);
  assert.equal(noticeFullText(n('up_to_date')), `${game}: partida al día, sin cambios pendientes`);
  assert.equal(noticeFullText(n('no_path')), `${game}: falta la carpeta de guardado del juego`);
  assert.equal(noticeFullText(n('missing_dir')), `${game}: no se encuentra la carpeta de guardado`);
  assert.equal(noticeFullText(n('conflict')), `${game}: conflicto: elige qué partida conservar`);
  assert.equal(noticeFullText(n('joined')), `${game}: juego unido a esta Deck correctamente`);
  assert.equal(noticeFullText(n('sync_failed')), `${game}: no se pudo sincronizar: revisa los avisos`);
  assert.ok(noticeFullText(n('algo_nuevo')).startsWith(`${game}: `));
  // avisos que no son de un juego: sin nombre aunque el backend mande uno
  assert.equal(noticeFullText(n('queued')), 'Sin conexión: sincronizará al reconectar');
  assert.equal(noticeFullText(n('offline_open')), 'Sin conexión: no se pudo sincronizar');
  assert.equal(noticeFullText(n('unauthorized')), 'Clave no válida: vuelve a vincular');
  // aviso de un juego sin nombre: nada inventado («Juego»)
  assert.equal(noticeFullText(n('up_to_date', { game: null })), 'Partida al día, sin cambios pendientes');
  for (const c of ['downloaded', 'conflict', 'sync_failed']) assert.ok(!/^Juego/.test(noticeFullText(n(c, { game: null }))));
  assert.ok(!noticeFullText(n('sync_failed')).includes('…'));
});

test('el bombeo de avisos los muestra, no se solapa y sobrevive a un fallo', { skip }, async () => {
  const { startNoticePump } = await load();
  let fn = null;
  const timers = { setInterval: (f) => ((fn = f), 1), clearInterval: () => (fn = null) };
  const shown = [];
  const errors = [];
  let calls = 0;
  const take = async () => {
    calls++;
    if (calls === 1) return [{ id: 1, code: 'conflict', game: 'A', level: 'warning', params: {} }];
    if (calls === 2) throw new Error('sin backend');
    return [{ id: 2, code: 'uploaded', game: 'B', level: 'info', params: {} }];
  };
  const stop = startNoticePump(take, (t) => shown.push(t), (e) => errors.push(e.message), 2000, timers);
  await fn();
  await fn();
  await fn();
  assert.equal(shown.length, 2);
  assert.equal(errors.length, 1);
  stop();
  assert.equal(fn, null);
});

test('la bomba recuerda el último aviso entregado (hora y texto) y no lo cambia si no llega nada', { skip }, async () => {
  const { startNoticePump, getLastNotice } = await load();
  let fn = null;
  const timers = { setInterval: (f) => ((fn = f), 1), clearInterval: () => (fn = null) };
  const clock = [new Date(2026, 10, 14, 9, 5), new Date(2026, 10, 14, 21, 7)];
  let i = 0;
  const batches = [
    [],
    [{ id: 1, code: 'uploaded', game: 'Uno', level: 'info', params: {} }],
    [],
    [
      { id: 2, code: 'conflict', game: 'Dos', level: 'warning', params: {} },
      { id: 3, code: 'uploaded', game: 'Tres', level: 'info', params: {} },
    ],
  ];
  let calls = 0;
  const take = async () => batches[calls++];
  const shown = [];
  const stop = startNoticePump(take, (t) => shown.push(t), () => {}, 2000, timers, () => clock[Math.min(i++, 1)]);
  await fn();
  const before = getLastNotice();
  await fn();
  const one = getLastNotice();
  await fn();
  assert.deepEqual(getLastNotice(), one); // un tick vacío no lo borra
  await fn();
  stop();
  assert.equal(before, null);
  assert.equal(one.time, '09:05');
  assert.match(one.text, /Uno.*enviada/i);
  const last = getLastNotice();
  assert.match(last.text, /Tres/); // el último de la tanda
  assert.equal(shown.length, 3);
});

test('si mostrar el toast lanza, el aviso cuenta como entregado y se avisa del fallo', { skip }, async () => {
  const { startNoticePump, getLastNotice } = await load();
  let fn = null;
  const timers = { setInterval: (f) => ((fn = f), 1), clearInterval: () => {} };
  const problems = [];
  startNoticePump(
    async () => [{ id: 9, code: 'conflict', game: 'Tres', level: 'warning', params: {} }],
    () => { throw new Error('toaster roto'); },
    (e) => problems.push(e.message),
    2000,
    timers,
    () => new Date(2026, 0, 1, 8, 0),
  );
  await fn();
  assert.match(problems[0], /toaster roto/);
  assert.match(getLastNotice().text, /Tres/);
});

test('cierres duplicados seguidos de Steam no repiten el evento; abrir-cerrar-abrir-cerrar sí pasa', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const sent = [];
  startGameWatch(s.client, (a, r) => sent.push([a, r]), () => {});
  s.cb({ unAppID: 5, bRunning: true });
  s.cb({ unAppID: 5, bRunning: false });
  s.cb({ unAppID: 5, bRunning: false });
  s.cb({ unAppID: 5, bRunning: false });
  assert.deepEqual(sent, [[5, true], [5, false]]);
  s.cb({ unAppID: 5, bRunning: true });
  s.cb({ unAppID: 5, bRunning: false });
  assert.equal(sent.length, 4);
});

test('el bombeo entrega y recuerda los avisos nuevos como último aviso', { skip }, async () => {
  const { startNoticePump, getLastNotice } = await load();
  const shown = [];
  let given = false;
  const take = async () => (given ? [] : ((given = true), [{ id: 1, code: 'up_to_date', game: 'Uno', level: 'info', params: {} }]));
  const timers = { setInterval: (f) => (f(), 1), clearInterval: () => {} };
  const stop = startNoticePump(take, (t) => shown.push(t), () => assert.fail('sin problemas'), 2000, timers, () => new Date(2026, 0, 1, 9, 5));
  await new Promise((r) => setImmediate(r));
  stop();
  assert.deepEqual(shown, [{ title: 'Checkpoint', body: 'Partida al día, sin cambios pendientes', level: 'info', kind: 'ok', code: 'up_to_date' }]);
  assert.deepEqual(getLastNotice(), { time: '09:05', text: 'Uno: partida al día, sin cambios pendientes' });
});

test('onRaw recibe el evento crudo antes del filtro y el filtro descarta igual', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const sent = [];
  const raw = [];
  startGameWatch(s.client, (a, r) => sent.push([a, r]), () => assert.fail('sin problemas'), (a, t, r) => raw.push([a, t, r]));
  s.cb({ unAppID: 0, bRunning: true });
  s.cb({ unAppID: -3, bRunning: true });
  s.cb({ unAppID: 1.5, bRunning: true });
  s.cb({ unAppID: '7', bRunning: true });
  s.cb({ unAppID: 8, bRunning: 'yes' });
  s.cb({ unAppID: 730, bRunning: true });
  s.cb(null);
  assert.deepEqual(raw, [
    ['0', 'number', 'true'],
    ['-3', 'number', 'true'],
    ['1.5', 'number', 'true'],
    ['7', 'string', 'true'],
    ['8', 'number', 'yes'],
    ['730', 'number', 'true'],
    ['undefined', 'undefined', 'undefined'],
  ]);
  assert.deepEqual(sent, [[730, true]]);
});

test('si onRaw lanza, no se rompe el escuchador ni el envío', { skip }, async () => {
  const { startGameWatch } = await load();
  const s = fakeSteam();
  const sent = [];
  startGameWatch(s.client, (a, r) => sent.push([a, r]), () => assert.fail('sin problemas'), () => { throw new Error('diag'); });
  s.cb({ unAppID: 5, bRunning: true });
  assert.deepEqual(sent, [[5, true]]);
});

test('noticeKind: éxito separado de info; avisos y errores por su nivel', { skip }, async () => {
  const { noticeKind, toastDuration } = await load();
  const k = (code, level = 'info') => noticeKind({ code, level });
  assert.equal(k('uploaded'), 'ok');
  assert.equal(k('downloaded'), 'ok');
  assert.equal(k('up_to_date'), 'ok');
  assert.equal(k('joined'), 'ok');
  assert.equal(k('no_path'), 'info');
  assert.equal(k('missing_dir'), 'info');
  assert.equal(k('conflict', 'warning'), 'warn');
  assert.equal(k('queued', 'warning'), 'warn');
  assert.equal(k('sync_failed', 'error'), 'error');
  assert.equal(k('uploaded', 'error'), 'error'); // el nivel del backend manda
  assert.equal(toastDuration('ok'), 6000);
  assert.equal(toastDuration('warn'), 12000);
  assert.equal(toastDuration('error'), 12000);
});

test('RunningApps: avisa solo cuando cambia y se puede dejar de escuchar', { skip }, async () => {
  const { RunningApps } = await load();
  const r = new RunningApps();
  let n = 0;
  const off = r.subscribe(() => n++);
  r.set(5, true);
  r.set(5, true); // repetido: sin aviso
  assert.equal(n, 1);
  assert.deepEqual([...r.snapshot()], [5]);
  r.set(6, false); // nunca estuvo abierto: sin aviso
  assert.equal(n, 1);
  r.set(5, false);
  assert.equal(n, 2);
  assert.equal(r.snapshot().size, 0);
  off();
  r.set(7, true);
  assert.equal(n, 2);
});

test('noticeText lleva el icono (kind) y el código del aviso', { skip }, async () => {
  const { noticeText } = await load();
  const t = noticeText({ id: 1, code: 'uploaded', game: 'Uno', level: 'info', params: {} });
  assert.equal(t.kind, 'ok');
  assert.equal(t.code, 'uploaded');
  assert.equal(noticeText({ id: 1, code: 'queued', game: null, level: 'warning', params: {} }).kind, 'warn');
});

test('«Último aviso» guarda el texto completo (nombre y motivo sin recortar); el toast va sin juego y en 45 caracteres', { skip }, async () => {
  const { startNoticePump, getLastNotice, noticeFullText } = await load();
  const game = 'Call of Cthulhu: Dark Corners of the Earth - Edición completa';
  const n = { id: 1, code: 'sync_failed', game, level: 'error', params: { reason: 'connection' } };
  const full = noticeFullText(n);
  assert.ok(full.startsWith(`${game}: no se pudo sincronizar: revisa los avisos. `), full);
  assert.ok(!full.includes('…'));
  assert.ok([...full].length > 45);
  assert.equal(noticeFullText({ id: 2, code: 'up_to_date', game, level: 'info', params: {} }), `${game}: partida al día, sin cambios pendientes`);
  assert.equal(noticeFullText({ id: 3, code: 'unauthorized', game: null, level: 'error', params: {} }), 'Clave no válida: vuelve a vincular');
  const shown = [];
  let given = false;
  const take = async () => (given ? [] : ((given = true), [n]));
  const timers = { setInterval: (f) => (f(), 1), clearInterval: () => {} };
  const stop = startNoticePump(take, (t) => shown.push(t), () => assert.fail('sin problemas'), 2000, timers, () => new Date(2026, 0, 1, 9, 5));
  await new Promise((r) => setImmediate(r));
  stop();
  assert.ok([...shown[0].body].length <= 45, 'el toast sigue limitado');
  assert.ok(!shown[0].body.includes('Cthulhu'), 'el toast no lleva el juego');
  assert.equal(getLastNotice().text, full);
});
