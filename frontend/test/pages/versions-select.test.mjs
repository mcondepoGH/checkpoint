// Pestaña Versiones: el selector de juego no se muestra sin juegos (el estado vacío ya lo explica) y sí con juegos.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import Versions from '#src/pages/Versions.jsx';
  export { React, renderToStaticMarkup, i18n, Versions };`,
  { navigator: true, tag: 'ckpt-versions-select' },
);
const render = (games) => {
  m.i18n.setLocale('es');
  return m.renderToStaticMarkup(m.React.createElement(m.Versions, { config: { games }, onGoSettings() {} }));
};

test('sin juegos no hay <select> y sí el estado vacío', { skip }, () => {
  const h = render({});
  assert.ok(!h.includes('<select'), 'selector vacío visible');
  assert.ok(h.includes('Ir a Configuración') || h.toLowerCase().includes('configuraci'));
});

test('con juegos hay <select> con sus opciones', { skip }, () => {
  const h = render({ a: { name: 'A' }, b: { name: 'B' } });
  assert.ok(h.includes('<select'));
  assert.equal((h.match(/<option/g) || []).length, 2);
});
