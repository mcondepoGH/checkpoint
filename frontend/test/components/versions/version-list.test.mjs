// Lista de Versiones: «Actual» (estado del hub) siempre primero, con insignia de texto y sin Restaurar; las anteriores, con Restaurar.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import VersionList from '#src/components/versions/VersionList.jsx';
  export { React, renderToStaticMarkup, i18n, VersionList };`,
  { navigator: true, tag: 'ckpt-versions' },
);
const render = (props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.VersionList, { onRestore() {}, ...props }));
};
const CUR = { id: '1-2-8', mtime: '2026-01-02 10:00:00', files: 2, size: 8 };
const V = (version) => ({ version, sources: [{ source: 'pc', name: 'PC', files: 3, mtime: '2026-01-01 09:00:00' }] });

test('«Actual» va primero, con insignia de texto y sin botón Restaurar', { skip }, () => {
  const h = render({ current: CUR, list: [V('2026-01-01_090000')] });
  assert.ok(h.indexOf('Actual') >= 0 && h.indexOf('Actual') < h.indexOf('2026-01-01_090000'));
  assert.ok(h.includes('2026-01-02 10:00:00') && h.includes('2 ficheros'));
  assert.equal((h.match(/Restaurar/g) || []).length, 1, 'solo la versión anterior se restaura');
});

test('«Actual» solo, sin versiones anteriores, sin Restaurar', { skip }, () => {
  const h = render({ current: CUR, list: [] });
  assert.ok(h.includes('Actual') && !h.includes('Restaurar'));
});

test('sin «Actual» (hub vacío) solo salen las versiones', { skip }, () => {
  const h = render({ current: null, list: [V('2026-01-01_090000')] });
  assert.ok(!h.includes('Actual') && h.includes('Restaurar'));
  assert.ok(!render({ current: undefined, list: [] }).includes('Actual'));
});

test('en inglés: Current', { skip }, () => {
  const h = render({ current: CUR, list: [V('2026-01-01_090000')] }, 'en');
  assert.ok(h.includes('Current') && (h.match(/Restore/g) || []).length === 1);
});
