import test from 'node:test';
import assert from 'node:assert/strict';
import {
  afterAccept,
  canAccept,
  existingNoteKey,
  failureOf,
  formatRemaining,
  normalizePending,
  remainingSeconds,
} from '#src/lib/pairing.js';
import { es, en, flat } from '../helpers/locales.mjs';

const raw = (o = {}) => ({ id: 'r1', name: 'Deck', os: 'linux', code: '123456', ip: '192.0.2.9', expires_in: 120, existing: 'none', ...o });

test('normalizePending limpia filas, calcula la caducidad y tolera basura', () => {
  const rows = normalizePending([raw(), null, { name: 'sin id' }, raw({ id: 'r2', existing: 'rara', expires_in: 'x' })], 1000);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].expiresAt, 1000 + 120000);
  assert.equal(rows[1].existing, 'none');
  assert.equal(rows[1].expiresAt, 1000);
  assert.deepEqual(normalizePending(null, 0), []);
  assert.deepEqual(normalizePending({}, 0), []);
});

test('tiempo restante: cuenta atrás, nunca negativo, formato m:ss', () => {
  const [r] = normalizePending([raw({ expires_in: 65 })], 0);
  assert.equal(remainingSeconds(r, 0), 65);
  assert.equal(remainingSeconds(r, 64500), 1);
  assert.equal(remainingSeconds(r, 99999), 0);
  assert.equal(formatRemaining(65), '1:05');
  assert.equal(formatRemaining(0), '0:00');
  assert.equal(formatRemaining(600), '10:00');
});

test('aceptar: no con existing other ni caducada; sí con none y http', () => {
  const row = (existing) => normalizePending([raw({ existing })], 0)[0];
  assert.equal(canAccept(row('none'), 10), true);
  assert.equal(canAccept(row('http'), 10), true);
  assert.equal(canAccept(row('other'), 10), false);
  assert.equal(canAccept(row('none'), 0), false);
});

test('avisos por dispositivo ya existente', () => {
  assert.equal(existingNoteKey({ existing: 'none' }), null);
  assert.equal(existingNoteKey({ existing: 'http' }), 'pairing.existing.http');
  assert.equal(existingNoteKey({ existing: 'other' }), 'pairing.existing.other');
});

test('failureOf: 404, 409 y config_changed tienen mensaje claro; 404 y no_pending refrescan; config_changed no', () => {
  assert.deepEqual(failureOf({ status: 404, code: 'err.pairing.request_unknown' }), {
    body: { code: 'pairing.gone', params: {} },
    refresh: true,
  });
  assert.deepEqual(failureOf({ status: 409, code: 'err.pairing.not_pending' }), {
    body: { code: 'pairing.notPending', params: {} },
    refresh: true,
  });
  assert.deepEqual(failureOf({ status: 409, code: 'err.main.config_changed' }), {
    body: { code: 'pairing.configChanged', params: {} },
    refresh: false,
  });
  const nh = failureOf({ status: 409, code: 'err.pairing.device_not_http', params: { name: 'PC' } });
  assert.deepEqual(nh.body, { code: 'err.pairing.device_not_http', params: { name: 'PC' } });
  assert.equal(nh.refresh, true);
  assert.equal(failureOf(new Error('red'), 'accept').body.code, 'pairing.failAccept');
  assert.equal(failureOf(new Error('red'), 'reject').body.code, 'pairing.failReject');
});

test('tras aceptar: borrador sucio se conserva, limpio se recarga', () => {
  assert.equal(afterAccept(true), 'keep');
  assert.equal(afterAccept(false), 'reload');
});

test('los mensajes que usa la lógica existen en es y en', () => {
  const keys = [
    'pairing.gone',
    'pairing.notPending',
    'pairing.configChanged',
    'pairing.failAccept',
    'pairing.failReject',
    'pairing.accepted',
    'pairing.acceptedDirty',
  ];
  for (const cat of [es, en]) {
    const f = Object.fromEntries(flat(cat));
    for (const k of keys) assert.ok(f[k], k);
  }
});
