// Borradores del formulario «Configurar» (src/drafts.ts). Sin Decky ni React.
// Se compila con el esbuild del frontend del hub (../frontend/node_modules); sin él, se omite.
// Ejecutar: node --test tests/drafts.test.mjs
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
  const out = join(mkdtempSync(join(tmpdir(), 'dr-')), 'dr.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/drafts.ts')], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  const m = await import(pathToFileURL(out));
  m.drafts.clear();
  return m;
}

const base = { open: true, gname: 'Juego', path: '', sug: { candidates: ['/a'] } };

test('get, set y delete', { skip }, async () => {
  const { drafts } = await load();
  assert.equal(drafts.get(1), undefined);
  drafts.set(1, { open: true, gname: 'A', path: '/x', sug: null });
  assert.deepEqual(drafts.get(1), { open: true, gname: 'A', path: '/x', sug: null });
  drafts.delete(1);
  assert.equal(drafts.get(1), undefined);
});

test('get devuelve una copia: mutarla no altera el almacén', { skip }, async () => {
  const { drafts } = await load();
  drafts.set(1, { open: true, gname: 'A', path: '/x', sug: null });
  drafts.get(1).path = '/otra';
  assert.equal(drafts.get(1).path, '/x');
});

test('patch con borrador previo conserva open y los demás campos', { skip }, async () => {
  const { drafts } = await load();
  drafts.set(7, { open: true, gname: 'Editado', path: '/viejo', sug: { n: 1 } });
  const r = drafts.patch(7, { path: '/elegida' }, base);
  assert.deepEqual(r, { open: true, gname: 'Editado', path: '/elegida', sug: { n: 1 } });
  assert.deepEqual(drafts.get(7), r);
});

test('patch sin borrador previo lo crea abierto desde la base y con la ruta elegida', { skip }, async () => {
  const { drafts } = await load();
  const r = drafts.patch(9, { path: '/elegida' }, base);
  assert.deepEqual(r, { open: true, gname: 'Juego', path: '/elegida', sug: { candidates: ['/a'] } });
  assert.equal(drafts.get(9).open, true);
  assert.ok(drafts.get(9).path.trim()); // «Guardar en el hub» queda activo al remontar
});

test('aislamiento por appid', { skip }, async () => {
  const { drafts } = await load();
  drafts.set(1, { open: true, gname: 'A', path: '/a', sug: null });
  drafts.set(2, { open: true, gname: 'B', path: '/b', sug: null });
  drafts.patch(1, { path: '/a2' }, base);
  drafts.delete(2);
  assert.equal(drafts.get(1).path, '/a2');
  assert.equal(drafts.get(2), undefined);
});

test('borrado al guardar: tras delete el remontaje no recupera nada', { skip }, async () => {
  const { drafts } = await load();
  drafts.patch(3, { path: '/p' }, base);
  drafts.delete(3); // lo que hace save() tras onDone ok
  assert.equal(drafts.get(3), undefined);
  assert.equal(drafts.size(), 0);
});

test('prune quita los appids que ya no están y no toca los abiertos que siguen', { skip }, async () => {
  const { drafts } = await load();
  drafts.set(1, { open: true, gname: 'A', path: '/a', sug: null });
  drafts.set(2, { open: true, gname: 'B', path: '/b', sug: null });
  drafts.prune([1, 5]);
  assert.deepEqual(drafts.get(1), { open: true, gname: 'A', path: '/a', sug: null });
  assert.equal(drafts.get(2), undefined);
  assert.equal(drafts.size(), 1);
});
