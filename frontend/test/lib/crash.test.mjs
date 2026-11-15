// Detalles de un fallo de render: solo name, message, stack recortado, user agent y versión; claves ocultas.
import test from 'node:test';
import assert from 'node:assert/strict';
import { crashDetails, redact, STACK_LINES } from '../../src/lib/crash.js';

test('redact oculta claves ck_/ckd_ y tokens largos', () => {
  assert.equal(redact('clave ck_abc123XYZ y ckd_Zz-9_k fin'), 'clave [oculto] y [oculto] fin');
  assert.equal(redact(`tok ${'a1B2'.repeat(10)} ok`), 'tok [oculto] ok');
  assert.equal(redact('texto normal con index-AbC123.js'), 'texto normal con index-AbC123.js');
  assert.equal(redact(undefined), '');
});

test('crashDetails incluye error, user agent y versión', () => {
  const e = new TypeError('x is undefined');
  const out = crashDetails(e, { userAgent: 'Mozilla/5.0 (iPad)', version: '1.16.0' });
  assert.match(out, /^Checkpoint: 1\.16\.0\nError: TypeError: x is undefined\nUser agent: Mozilla\/5\.0 \(iPad\)/);
});

test('crashDetails recorta la pila y oculta claves del mensaje y la pila', () => {
  const e = new Error('falla con ck_secreto123');
  e.stack = Array.from({ length: 40 }, (_, i) => `  at f${i} (ckd_otraclave9:1:1)`).join('\n');
  const out = crashDetails(e);
  assert.ok(!out.includes('secreto123') && !out.includes('otraclave9'));
  assert.ok(out.includes('[oculto]'));
  assert.ok(out.includes('f11') && !out.includes('f12 '));
  assert.ok(out.split('\n').length <= STACK_LINES + 4);
});

test('crashDetails tolera errores que no son Error', () => {
  assert.match(crashDetails('texto'), /Error: Error: texto/);
  assert.match(crashDetails(null), /Error: Error: /);
});
