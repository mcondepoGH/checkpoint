// Captura de fallos del panel (src/crashwatch.ts, port del hub). Sin Decky ni navegador: `window` falso.
// Se compila con el esbuild del frontend del hub (../frontend/node_modules); sin él, se omite.
// Ejecutar: node --test tests/crashwatch.test.mjs
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
  const out = join(mkdtempSync(join(tmpdir(), 'cw-')), 'cw.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/crashwatch.ts')], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  return import(pathToFileURL(out));
}

function fakeWin() {
  const l = {};
  return {
    navigator: { userAgent: 'UA-test' },
    addEventListener: (n, f) => (l[n] ||= new Set()).add(f),
    removeEventListener: (n, f) => l[n]?.delete(f),
    count: (n) => l[n]?.size ?? 0,
    fire: (n, ev) => [...(l[n] || [])].forEach((f) => f(ev)),
  };
}

test('error global: aviso saneado (clave y steamid fuera) y onReport una vez', { skip }, async () => {
  const { startCrashWatch } = await load();
  const win = fakeWin();
  const reported = [];
  const w = startCrashWatch(win, { version: '0.1', onReport: (it) => reported.push(it) });
  const message = 'falla con ckd_secreta123 y steamid 76561198000000000 en http://hub:8080/api?key=abc';
  win.fire('error', { message, error: new Error(message) });
  const [a] = w.list();
  assert.equal(a.severity, 'alert');
  assert.doesNotMatch(a.details + a.title, /ckd_secreta123|76561198000000000|key=abc/);
  assert.match(a.details, /Checkpoint: 0\.1/);
  assert.equal(reported.length, 1);
  w.stop();
  assert.equal(win.count('error') + win.count('unhandledrejection'), 0);
});

test('promesa rechazada se captura; ruido (AbortError, sin mensaje) no', { skip }, async () => {
  const { startCrashWatch } = await load();
  const win = fakeWin();
  const w = startCrashWatch(win);
  win.fire('unhandledrejection', { reason: Object.assign(new Error('x'), { name: 'AbortError' }) });
  win.fire('unhandledrejection', { reason: null });
  assert.equal(w.list().length, 0);
  win.fire('unhandledrejection', { reason: new Error('callable fallo') });
  assert.equal(w.list().length, 1);
});

test('report(): llamada al backend que falla se ve una vez aunque se repita cada segundo', { skip }, async () => {
  const { startCrashWatch } = await load();
  let t = 0;
  const w = startCrashWatch(fakeWin(), { now: () => t });
  for (let i = 0; i < 20; i++) {
    t += 1000; // pasa de dedupeMs: aun así no se repite mientras siga en pantalla
    w.report(new Error('estado de los juegos: socket cerrado'));
  }
  assert.equal(w.list().length, 1);
  w.dismiss(w.list()[0].id);
  t += 1000;
  w.report(new Error('estado de los juegos: socket cerrado'));
  assert.equal(w.list().length, 1); // descartado: puede volver a avisar
});

test('tope de avisos visibles', { skip }, async () => {
  const { startCrashWatch, MAX_VISIBLE } = await load();
  const w = startCrashWatch(fakeWin());
  for (let i = 0; i < 10; i++) w.report(new Error(`fallo distinto ${i}`));
  assert.equal(w.list().length, MAX_VISIBLE);
});

test('el TypeError conocido del selector de Decky no es un aviso: avisa a onPickerError y no oculta otros fallos', { skip }, async () => {
  const { startCrashWatch } = await load();
  const win = fakeWin();
  const picker = [];
  const reported = [];
  const w = startCrashWatch(win, { onPickerError: () => picker.push(1), onReport: (it) => reported.push(it) });
  const known = new TypeError('theError.match is not a function');
  win.fire('unhandledrejection', { reason: known });
  win.fire('error', { message: 'Uncaught TypeError: theError.match is not a function', error: known });
  assert.equal(picker.length, 2);
  assert.equal(w.list().length, 0);
  assert.equal(reported.length, 0);
  win.fire('unhandledrejection', { reason: new TypeError('x.foo is not a function') });
  win.fire('error', { message: 'otra cosa', error: new Error('otra cosa') });
  assert.equal(picker.length, 2);
  assert.equal(w.list().length, 2);
  w.stop();
});

test('sin onPickerError el error conocido se sigue mostrando (nada se oculta por defecto)', { skip }, async () => {
  const { startCrashWatch } = await load();
  const win = fakeWin();
  const w = startCrashWatch(win);
  win.fire('unhandledrejection', { reason: new TypeError('theError.match is not a function') });
  assert.equal(w.list().length, 1);
  w.stop();
});

test('el título del fallo llega entero hasta TITLE_MAX (antes 200) y sigue saneado', { skip }, async () => {
  const { startCrashWatch, TITLE_MAX } = await load();
  const win = fakeWin();
  const w = startCrashWatch(win, { version: '0.1' });
  const message = `${'fallo largo '.repeat(40)}con ckd_secreta123`; // ~480 caracteres
  win.fire('error', { message, error: new Error(message) });
  const [a] = w.list();
  assert.equal(TITLE_MAX, 1000);
  assert.ok(a.title.length > 200 && a.title.length <= TITLE_MAX, String(a.title.length));
  assert.doesNotMatch(a.title, /ckd_secreta123/);
  assert.match(a.title, /fallo largo con \[oculto\]$/); // completo, hasta el final
  w.stop();
});
