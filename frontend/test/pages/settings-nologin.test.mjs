// Aviso del modo sin login: ya no es un banner global; vive como tarjeta en Configuración > General y solo con noLogin.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../helpers/bundle.mjs';
import { en, es } from '../helpers/locales.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import General from '#src/pages/settings/General.jsx';
  export { React, renderToStaticMarkup, i18n, General };`,
  { navigator: true, tag: 'ckpt-general-nologin' },
);

const G = (props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.General, { updates: null, onUpdates() {}, ...props }));
};

test('General muestra el aviso (mismo texto aprobado) como tarjeta solo con noLogin', { skip }, () => {
  const on = G({ noLogin: true });
  assert.ok(on.includes(es.app.noLogin));
  assert.match(on, /<section class="card"[^>]*>[^]*solo se puede abrir desde este equipo/);
  assert.ok(!G({ noLogin: false }).includes(es.app.noLogin));
  assert.ok(!G({}).includes(es.app.noLogin));
});

test('mismo aviso en inglés', { skip }, () => {
  assert.ok(G({ noLogin: true }, 'en').includes(en.app.noLogin));
});

test('textos aprobados intactos', () => {
  assert.equal(es.app.noLogin, 'Checkpoint no tiene usuario ni contraseña: solo se puede abrir desde este equipo (127.0.0.1).');
  assert.equal(en.app.noLogin, 'Checkpoint has no username or password: it can only be opened from this computer (127.0.0.1).');
});
