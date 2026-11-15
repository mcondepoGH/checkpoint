import test from 'node:test';
import assert from 'node:assert/strict';
import { copyKey, initialState, lockReason, reduce, run } from '#src/lib/devicekey.js';

const api = (o = {}) => ({
  get: async () => ({ exists: true, key: 'ckd_secreta' }),
  create: async () => ({ exists: true, key: 'ckd_nueva' }),
  revoke: async () => ({ exists: false, key: null }),
  ...o,
});

test('cargar solo informa del estado: la clave no entra en el estado', async () => {
  const a = await run(api(), 'load');
  assert.deepEqual(a, { type: 'loaded', exists: true });
  const s = reduce(initialState, a);
  assert.equal(s.exists, true);
  assert.equal(s.key, null);
  assert.ok(!JSON.stringify(s).includes('ckd_'));
});

test('Ver muestra la clave y Ocultar la descarta', async () => {
  let s = reduce(initialState, await run(api(), 'show'));
  assert.equal(s.key, 'ckd_secreta');
  s = reduce(s, { type: 'hide' });
  assert.equal(s.key, null);
  assert.equal(s.exists, true);
});

test('sin clave: Ver no muestra nada; generar y regenerar muestran la nueva', async () => {
  const none = api({ get: async () => ({ exists: false, key: null }) });
  const s = reduce(initialState, await run(none, 'show'));
  assert.deepEqual([s.exists, s.key], [false, null]);
  const g = reduce(s, await run(api(), 'create'));
  assert.deepEqual([g.exists, g.key], [true, 'ckd_nueva']);
});

test('revocar descarta clave y cierra la confirmación', async () => {
  let s = { ...initialState, loaded: true, exists: true, key: 'ckd_x' };
  s = reduce(s, { type: 'ask', what: 'revoke' });
  assert.equal(s.confirm, 'revoke');
  s = reduce(s, await run(api(), 'revoke'));
  assert.deepEqual([s.exists, s.key, s.confirm], [false, null, null]);
});

test('cancelar la confirmación no cambia nada más', () => {
  let s = reduce({ ...initialState, exists: true }, { type: 'ask', what: 'regenerate' });
  s = reduce(s, { type: 'cancel' });
  assert.deepEqual([s.confirm, s.exists], [null, true]);
});

test('un fallo guarda el error y no muestra clave', async () => {
  const err = Object.assign(new Error('x'), { code: 'err.hook.device_not_http', params: {} });
  const s = reduce(initialState, await run(api({ get: async () => Promise.reject(err) }), 'show'));
  assert.equal(s.error, err);
  assert.equal(s.key, null);
});

test('copiar pide la clave si no está visible, la copia y no la guarda', async () => {
  let copied = null;
  const a = await copyKey(api(), null, async (k) => ((copied = k), true));
  assert.equal(copied, 'ckd_secreta');
  assert.deepEqual(a, { type: 'copied', ok: true, error: null });
  const s = reduce(initialState, a);
  assert.equal(s.copied, true);
  assert.equal(s.key, null);
});

test('copiar con la clave visible no vuelve a pedirla; el fallo de copia se avisa', async () => {
  const a = await copyKey(api({ get: async () => assert.fail('no debe pedirla') }), 'ckd_vista', async () => false);
  assert.equal(a.ok, false);
  assert.equal(a.error.code, 'devkey.copyFail');
});

test('bloqueo: dispositivo nuevo o tarjeta con cambios', () => {
  assert.equal(lockReason({ id: null }, false), 'devkey.lockNew');
  assert.equal(lockReason({ id: 'a' }, true), 'devkey.lockDirty');
  assert.equal(lockReason({ id: 'a' }, false), null);
});

test('wantsOpen: abierto sin clave o recién generada; cerrado con clave existente y sin cargar', async () => {
  const { wantsOpen } = await import('#src/lib/devicekey.js');
  assert.equal(wantsOpen(initialState), false);
  assert.equal(wantsOpen(reduce(initialState, await run(api(), 'load'))), false);
  assert.equal(wantsOpen(reduce(initialState, await run(api(), 'show'))), false);
  const none = api({ get: async () => ({ exists: false, key: null }) });
  assert.equal(wantsOpen(reduce(initialState, await run(none, 'load'))), true);
  const fresh = reduce(initialState, await run(api(), 'create'));
  assert.equal(wantsOpen(fresh), true);
  assert.equal(wantsOpen(reduce(fresh, { type: 'start' })), false);
  assert.equal(wantsOpen(reduce(initialState, await run(api(), 'revoke'))), true);
  assert.equal(wantsOpen(reduce(initialState, { type: 'failed', error: { code: 'x', params: {} } })), false);
});
