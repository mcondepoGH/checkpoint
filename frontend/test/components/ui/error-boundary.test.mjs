// ErrorBoundary: un fallo al pintar una zona no debe dejar toda la pantalla en blanco. Se prueba el contrato de la clase
// (react-dom/server no ejecuta límites de error) y el aviso que pinta, sin datos del error.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import ErrorBoundary from '#src/components/ui/ErrorBoundary.jsx';
  export { React, renderToStaticMarkup, i18n, ErrorBoundary };`,
  { navigator: true, tag: 'ckpt-errbound' },
);

const render = (state, lang = 'es') => {
  mod.i18n.setLocale(lang);
  const b = new mod.ErrorBoundary({ children: mod.React.createElement('p', null, 'hijo') });
  b.state = state;
  return mod.renderToStaticMarkup(b.render());
};

test('sin fallo pinta a los hijos', { skip }, () => {
  assert.equal(render(mod.ErrorBoundary.getDerivedStateFromError ? { failed: false } : {}), '<p>hijo</p>');
});

test('un fallo de render cambia al aviso (getDerivedStateFromError)', { skip }, () => {
  const err = new Error('secreto-xyz');
  assert.deepEqual(mod.ErrorBoundary.getDerivedStateFromError(err), { failed: true, error: err });
});

test('el aviso está en es y en, con recargar y detalles plegados (Ver detalles / Show details)', { skip }, () => {
  const state = { failed: true, error: new Error('fallo ck_clave123 raro') };
  const es = render(state, 'es');
  assert.match(es, /role="alert"/);
  assert.match(es, /Recargar/);
  assert.match(es, /<details[^>]*>\s*<summary>Ver detalles<\/summary>/);
  assert.ok(!/<details[^>]* open/.test(es));
  assert.match(es, /Copiar detalles/);
  assert.ok(!es.includes('hijo'));
  const en = render(state, 'en');
  assert.match(en, /Reload/);
  assert.match(en, /Show details/);
  assert.match(en, /Copy details/);
});

test('los detalles llevan error, user agent y versión, con claves ocultas', { skip }, () => {
  mod.i18n.setLocale('es');
  const b = new mod.ErrorBoundary({ children: null, version: '9.9.9' });
  b.state = { failed: true, error: new Error('fallo ck_clave123 raro') };
  const html = mod.renderToStaticMarkup(b.render());
  assert.match(html, /<pre[^>]*>/);
  assert.match(html, /Checkpoint: 9\.9\.9/);
  assert.match(html, /Error: Error: fallo \[oculto\] raro/);
  assert.ok(html.includes(`User agent: ${globalThis.navigator.userAgent}`));
  assert.ok(!html.includes('clave123'));
});

test('resetKey rearma el límite y borra el error', { skip }, () => {
  const next = mod.ErrorBoundary.getDerivedStateFromProps({ resetKey: 'b' }, { failed: true, error: new Error('x'), resetKey: 'a' });
  assert.deepEqual(next, { failed: false, error: null, resetKey: 'b' });
});
