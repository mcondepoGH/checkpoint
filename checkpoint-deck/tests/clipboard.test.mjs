// copyText (src/clipboard.ts): navigator.clipboard -> execCommand -> false, sin lanzar nunca. `navigator` y `document` falsos.
// Se compila con el esbuild del frontend del hub (../frontend/node_modules); sin él, se omite.
// Ejecutar: node --test tests/clipboard.test.mjs
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
  const out = join(mkdtempSync(join(tmpdir(), 'cb-')), 'cb.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/clipboard.ts')], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  return import(pathToFileURL(out));
}

function fakeDom({ clip, exec } = {}) {
  const st = { written: null, appended: [], removed: 0, execCalls: [], selected: false, value: null };
  const ta = {
    style: {},
    setAttribute() {},
    focus() {},
    select() { st.selected = true; },
    remove() { st.removed++; },
  };
  const g = globalThis;
  Object.defineProperty(g, 'navigator', {
    configurable: true,
    value: clip === undefined ? {} : { clipboard: { writeText: async (t) => { st.written = t; return clip(t); } } },
  });
  g.document = {
    createElement: () => ta,
    body: { appendChild: (e) => { st.appended.push(e); st.value = e.value; } },
    execCommand: (c) => { st.execCalls.push(c); if (exec instanceof Error) throw exec; return exec ?? false; },
  };
  return st;
}

test('éxito por navigator.clipboard: no toca execCommand', { skip }, async () => {
  const { copyText } = await load();
  const st = fakeDom({ clip: () => undefined, exec: true });
  assert.equal(await copyText('http://hub/api/deck/plugin'), true);
  assert.equal(st.written, 'http://hub/api/deck/plugin');
  assert.deepEqual(st.execCalls, []);
});

test('si navigator.clipboard rechaza, cae a execCommand con un textarea temporal que se quita', { skip }, async () => {
  const { copyText } = await load();
  const st = fakeDom({ clip: () => { throw new Error('NotAllowedError'); }, exec: true });
  assert.equal(await copyText('abc'), true);
  assert.deepEqual(st.execCalls, ['copy']);
  assert.equal(st.value, 'abc');
  assert.equal(st.selected, true);
  assert.equal(st.removed, 1);
});

test('sin navigator.clipboard usa execCommand', { skip }, async () => {
  const { copyText } = await load();
  const st = fakeDom({ exec: true });
  assert.equal(await copyText('abc'), true);
  assert.deepEqual(st.execCalls, ['copy']);
});

test('fallo total: devuelve false y no lanza (execCommand false o que lanza)', { skip }, async () => {
  const { copyText } = await load();
  fakeDom({ clip: () => { throw new Error('x'); }, exec: false });
  assert.equal(await copyText('abc'), false);
  const st = fakeDom({ clip: () => { throw new Error('x'); }, exec: new Error('boom') });
  assert.equal(await copyText('abc'), false);
  assert.equal(st.removed, 1);
  delete globalThis.document;
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {} });
  assert.equal(await copyText('abc'), false);
});
