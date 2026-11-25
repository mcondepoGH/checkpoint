// Tarjeta «Arrancar al iniciar sesión»: oculta hasta que el backend confirma que el hub es el de Windows.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle, readSrc } from '../../helpers/bundle.mjs';
import { en, es } from '../../helpers/locales.mjs';

const { mod, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import Autostart from '#src/components/updates/Autostart.jsx';
  export { React, renderToStaticMarkup, Autostart };`,
  { tag: 'ckpt-autostart' },
);

test('Autostart no pinta nada sin respuesta del backend (ni en Docker/Linux: supported=false)', { skip }, () => {
  assert.equal(mod.renderToStaticMarkup(mod.React.createElement(mod.Autostart)), '');
});

test('General incluye la tarjeta de autoarranque', () => {
  assert.match(readSrc('pages', 'settings', 'General.jsx'), /<Autostart \/>/);
});

test('textos aprobados de la tarjeta en es y en', () => {
  assert.equal(es.autostart.title, 'Arrancar al iniciar sesión');
  assert.equal(en.autostart.title, 'Start at sign-in');
  assert.match(es.err.main.autostart.create_failed, /\{reason\}/);
  assert.match(en.err.main.autostart.not_supported, /only available on Windows/);
});
