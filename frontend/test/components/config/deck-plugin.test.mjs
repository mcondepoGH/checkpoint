// Bloque «Plugin de Steam Deck» (DeckPluginView) renderizado a HTML, y la normalización de /api/deck/plugin/info.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { DeckPluginView } from '#src/components/config/DeckPlugin.jsx';
  import { normalizeInfo, DOWNLOAD_URL } from '#src/lib/deck.js';
  export { React, renderToStaticMarkup, DeckPluginView, normalizeInfo, DOWNLOAD_URL };`,
  { tag: 'ckpt-deck' },
);

const SHA = 'a'.repeat(64);
const has = (h, s) => h.includes(s);
const view = (info, props = {}) =>
  mod.renderToStaticMarkup(mod.React.createElement(mod.DeckPluginView, { info: mod.normalizeInfo(info), loaded: true, ...props }));

test('normalizeInfo: sin datos o zip ausente = no disponible', { skip }, () => {
  assert.deepEqual(mod.normalizeInfo(null), { available: false });
  assert.deepEqual(mod.normalizeInfo({ available: false }), { available: false });
  assert.deepEqual(mod.normalizeInfo({ available: true, sha256: 'zz' }), { available: false });
});

test('normalizeInfo: disponible con versión, suma y tamaño', { skip }, () => {
  assert.deepEqual(mod.normalizeInfo({ available: true, sha256: SHA.toUpperCase(), version: '1.0.0', size: 10, x: 1 }), {
    available: true,
    sha256: SHA,
    version: '1.0.0',
    size: 10,
  });
  assert.equal(mod.normalizeInfo({ available: true, sha256: SHA, version: 5 }).version, null);
});

test('disponible: enlace de descarga y versión', { skip }, () => {
  const h = view({ available: true, sha256: SHA, version: '1.2.3', size: 40000 });
  assert.ok(has(h, `href="${mod.DOWNLOAD_URL}"`) && has(h, 'download'));
  assert.ok(has(h, 'Descargar plugin'));
  assert.ok(has(h, '1.2.3'));
  assert.ok(!has(h, SHA) && !has(h, 'sha256sum') && !has(h, 'deck-plugin-sha'));
  assert.ok(!/<button[^>]*disabled/.test(h));
});

test('disponible sin versión: lo dice', { skip }, () => {
  assert.ok(has(view({ available: true, sha256: SHA }), 'desconocida'));
});

test('no disponible: botón deshabilitado y mensaje, sin enlace', { skip }, () => {
  const h = view({ available: false });
  assert.ok(/<button[^>]*disabled/.test(h));
  assert.ok(!has(h, `href="${mod.DOWNLOAD_URL}"`)); // la intro cita la URL como texto, no como enlace
  assert.ok(has(h, 'no incluye el plugin'));
});

test('sin cargar: botón deshabilitado y sin mensaje de ausencia', { skip }, () => {
  const h = view(null, { loaded: false });
  assert.ok(/<button[^>]*disabled/.test(h));
  assert.ok(!has(h, 'no incluye el plugin'));
});

test('fallo al consultar: aviso y botón deshabilitado', { skip }, () => {
  const h = view(null, { failed: true });
  assert.ok(/<button[^>]*disabled/.test(h) && has(h, 'No se pudo consultar'));
});
