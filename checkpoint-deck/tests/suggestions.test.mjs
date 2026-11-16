// Lógica pura de «Sugerencias de guardado» (src/suggestions.ts). Sin Decky ni React.
// Se compila con el esbuild del frontend del hub (../frontend/node_modules); sin él, se omite.
// Ejecutar: node --test tests/suggestions.test.mjs
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
  const out = join(mkdtempSync(join(tmpdir(), 'sg-')), 'sg.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/suggestions.ts')], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  return import(pathToFileURL(out));
}

const P = (path, o = {}) => ({ path, exists: true, mtime: 100, ...o });
const G = (o = {}) => ({ source: 'steam', id: 1, name: 'J', confidence: 'high', needs_confirmation: true, state: 'found', paths: [P('/a')], ...o });

test('bestPath: existente > no dudosa > más reciente; empate = la primera; sin rutas = null', { skip }, async () => {
  const { bestPath } = await load();
  assert.equal(bestPath([]), null);
  assert.equal(bestPath([P('/a', { mtime: 1 }), P('/b', { mtime: 9 })]).path, '/b');
  assert.equal(bestPath([P('/a', { mtime: 9, doubtful: true }), P('/b', { mtime: 1 })]).path, '/b'); // confianza antes que fecha
  assert.equal(bestPath([P('/a', { exists: false, mtime: 99 }), P('/b', { doubtful: true, mtime: 1 })]).path, '/b'); // existir antes que nada
  assert.equal(bestPath([P('/a', { exists: false }), P('/b', { exists: false })]).path, '/a');
  assert.equal(bestPath([P('/a', { mtime: null }), P('/b', { mtime: null })]).path, '/a');
});

test('otherPaths: todas menos la mejor', { skip }, async () => {
  const { bestPath, otherPaths } = await load();
  const ps = [P('/a', { mtime: 1 }), P('/b', { mtime: 9 }), P('/c', { mtime: 5 })];
  assert.deepEqual(otherPaths(ps, bestPath(ps)).map((p) => p.path), ['/a', '/c']);
});

test('cardKind: segura, dudosa, no encontrada', { skip }, async () => {
  const { cardKind } = await load();
  assert.equal(cardKind(G()), 'safe');
  assert.equal(cardKind(G({ confidence: 'doubtful' })), 'doubtful');
  assert.equal(cardKind(G({ paths: [P('/a', { doubtful: true })] })), 'doubtful'); // juego fiable, ruta dudosa
  assert.equal(cardKind(G({ paths: [P('/a', { exists: false })], state: 'not_found_yet' })), 'not_found');
  assert.equal(cardKind(G({ paths: [] })), 'not_found');
  assert.equal(cardKind(G({ confidence: 'doubtful', paths: [P('/a', { exists: false })] })), 'not_found'); // nunca botón de aplicar
});

test('unconfiguredOnly: quita los de Steam ya en el hub, respeta añadidos y ocultos, no toca Lutris', { skip }, async () => {
  const { unconfiguredOnly, gameKey } = await load();
  const games = [G({ id: 1 }), G({ id: 2 }), G({ source: 'lutris', id: 2 }), G({ id: 3 })];
  assert.equal(gameKey(games[2]), 'lutris:2');
  const ids = (l) => l.map(gameKey);
  assert.deepEqual(ids(unconfiguredOnly(games, [2, null, undefined])), ['steam:1', 'lutris:2', 'steam:3']);
  assert.deepEqual(ids(unconfiguredOnly(games, [2], new Set(['steam:3']))), ['steam:1', 'lutris:2']);
  assert.deepEqual(ids(unconfiguredOnly(games, [1, 2], new Set(), new Set(['steam:1']))), ['steam:1', 'lutris:2', 'steam:3']); // recién añadido
  assert.deepEqual(ids(unconfiguredOnly(games, [])), ids(games));
});
