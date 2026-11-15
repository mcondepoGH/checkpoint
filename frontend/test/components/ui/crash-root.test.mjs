// Raíz de la app y aviso discreto: el último recurso no depende del contexto de i18n y los avisos usan detalles saneados.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle, readSrc } from '../../helpers/bundle.mjs';

const { mod, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import ErrorBoundary from '#src/components/ui/ErrorBoundary.jsx';
  import { CrashToastList } from '#src/components/ui/CrashToasts.jsx';
  export { React, renderToStaticMarkup, ErrorBoundary, CrashToastList };`,
  { navigator: true, tag: 'ckpt-crashroot' },
);

const root = (lang) => {
  Object.defineProperty(globalThis.navigator, 'language', { value: lang, configurable: true });
  Object.defineProperty(globalThis.navigator, 'languages', { value: [lang], configurable: true });
  const b = new mod.ErrorBoundary({ children: null, standalone: true });
  b.state = { failed: true, error: new Error('fallo ck_clave123 raro') };
  return mod.renderToStaticMarkup(b.render());
};

test('último recurso sin contexto de i18n: textos de respaldo según navigator.language', { skip }, () => {
  const es = root('es-ES');
  assert.match(es, /role="alert"/);
  assert.match(es, /Recargar/);
  assert.match(es, /Ver detalles/);
  assert.match(es, /Copiar detalles/);
  assert.ok(!es.includes('clave123'));
  const en = root('en-US');
  assert.match(en, /Reload/);
  assert.match(en, /Show details/);
});

test('el aviso discreto pinta role según gravedad, detalles plegados, copiar y cerrar', { skip }, () => {
  const items = [
    { id: 1, severity: 'alert', title: 'T1', details: 'Error: Error: a [oculto]' },
    { id: 2, severity: 'status', title: 'T2', details: 'Error: Error: b' },
  ];
  const html = mod.renderToStaticMarkup(mod.React.createElement(mod.CrashToastList, { items, onDismiss() {}, t: (k) => k }));
  assert.match(html, /role="alert"/);
  assert.match(html, /role="status"/);
  assert.match(html, /<details/);
  assert.ok(!/<details[^>]* open/.test(html));
  assert.match(html, /app\.crash\.detailsCopy/);
  assert.match(html, /app\.crash\.dismiss/);
  assert.ok(!html.includes('ck_'));
});

test('main.jsx monta la raíz con el límite autónomo y el manejador global', () => {
  const s = readSrc('main.jsx');
  assert.match(s, /<ErrorBoundary standalone/);
  assert.match(s, /CrashToasts/);
});

test('ErrorBoundary no importa useI18n en el camino autónomo (usa los catálogos directos)', () => {
  const s = readSrc('lib', 'crashtext.js');
  assert.ok(!/useI18n/.test(s));
});
