// Lógica pura de la pantalla de datos sin dispositivo ni juego, y su API (con fetch simulado).
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canRelocate,
  hasOnlyCopy,
  keepSelected,
  moveNotice,
  payload,
  relocateNotice,
  selectedItems,
  targetGame,
  totalSize,
} from '#src/lib/orphans.js';
import { listOrphans, listTrash, relocateOrphan, restoreTrash, trashOrphans } from '#src/lib/api/orphans.js';
import { errorText } from '#src/lib/errors.js';
import { createI18n } from '#src/lib/i18n.js';
import { en, es } from '../helpers/locales.mjs';

const it = (o = {}) => ({ id: 'origin:g:x', kind: 'origin', game: 'g', source: 'x', size: 10, only_copy: false, token: 'tk', ...o });

test('selectedItems conserva el orden de la lista y hasOnlyCopy mira solo lo elegido', () => {
  const items = [it({ id: 'a' }), it({ id: 'b', only_copy: true }), it({ id: 'c' })];
  assert.deepEqual(
    selectedItems(items, ['c', 'a']).map((i) => i.id),
    ['a', 'c'],
  );
  assert.equal(hasOnlyCopy(selectedItems(items, ['a', 'c'])), false);
  assert.equal(hasOnlyCopy(selectedItems(items, ['b'])), true);
});

test('totalSize ignora tamaños que no son número; payload manda solo id y token', () => {
  assert.equal(totalSize([it({ size: 5 }), it({ size: 7 }), it({ size: null })]), 12);
  assert.deepEqual(payload([it({ id: 'a', token: 't1', size: 99 })]), [{ id: 'a', token: 't1' }]);
});

test('keepSelected desmarca lo que ya no está en la lista', () => {
  assert.deepEqual(keepSelected(['a', 'b'], [it({ id: 'b' })]), ['b']);
});

test('moveNotice: todo movido es ok; parcial lleva los motivos traducibles', () => {
  assert.deepEqual(moveNotice({ moved: [{}, {}], skipped: [] }), { variant: 'ok', body: { code: 'orphans.moved', params: { count: 2 } } });
  const n = moveNotice({ moved: [{}], skipped: [{ id: 'game:q', code: 'err.orphans.busy', params: {} }] });
  assert.equal(n.variant, 'warn');
  assert.equal(n.body.params.moved, 1);
  const t = createI18n({ catalogs: { es, en }, storage: null, languages: ['es'] }).t;
  assert.match(errorText(n.body, t), /No se han movido 1: game:q: hay una operación en curso/);
  assert.equal(moveNotice({ moved: [], skipped: [{ id: 'a', code: 'err.orphans.changed' }] }).variant, 'error');
});

test('la API usa las rutas y cuerpos esperados', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init?.method ?? 'GET', init?.body]);
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await listOrphans();
  await trashOrphans([{ id: 'a', token: 't' }]);
  await listTrash();
  await restoreTrash('2026-01-01_000000', 2);
  assert.deepEqual(calls, [
    ['/api/orphans', 'GET', undefined],
    ['/api/orphans/trash', 'POST', JSON.stringify({ items: [{ id: 'a', token: 't' }] })],
    ['/api/orphans/trash', 'GET', undefined],
    ['/api/orphans/trash/restore', 'POST', JSON.stringify({ entry: '2026-01-01_000000', item: 2 })],
  ]);
});

test('canRelocate: solo juegos huérfanos y con algún juego de destino', () => {
  const games = [{ id: 'g', name: 'G' }];
  assert.equal(canRelocate(it({ kind: 'game' }), games), true);
  assert.equal(canRelocate(it({ kind: 'origin' }), games), false);
  assert.equal(canRelocate(it({ kind: 'game' }), []), false);
  assert.equal(canRelocate(it({ kind: 'game' }), undefined), false);
});

test('targetGame y relocateNotice', () => {
  const games = [{ id: 'g', name: 'Juego' }];
  assert.deepEqual(targetGame(games, 'g'), games[0]);
  assert.equal(targetGame(games, 'x'), null);
  assert.equal(targetGame(undefined, 'x'), null);
  assert.deepEqual(relocateNotice({ versions: 3 }, games[0]), {
    variant: 'ok',
    body: { code: 'orphans.relocated', params: { count: 3, target: 'Juego' } },
  });
});

test('relocateOrphan manda id, token y destino', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init?.method ?? 'GET', init?.body]);
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await relocateOrphan('game:x', 'tk', 'g');
  assert.deepEqual(calls, [['/api/orphans/relocate', 'POST', JSON.stringify({ id: 'game:x', token: 'tk', target: 'g' })]]);
});
