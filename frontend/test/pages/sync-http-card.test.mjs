// Tarjeta de Sincronizar de un juego solo http: insignia derivada del último resultado del plugin (no del estado
// antiguo del hub), bloque «Última sync» con ese resultado y separación entre título e insignia. Sin navegador.
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import * as sass from 'sass';
import { bundle } from '../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import Sync from '#src/pages/Sync.jsx';
  import { httpBadge, resultBadge, lastHttpResult, httpRunStatus } from '#src/components/watch/watch.js';
  import { Badge } from '#src/components/ui/index.js';
  export { React, renderToStaticMarkup, i18n, Sync, Badge, httpBadge, resultBadge, lastHttpResult, httpRunStatus };`,
  { navigator: true, tag: 'ckpt-sync-http' },
);

const has = (h, s) => h.includes(s);
const res = (o = {}) => ({ game: 'g', device: 'deck', at: '2026-01-01T10:30:00Z', trigger: 'hook_opened', state: 'uploaded', ...o });

test('httpBadge: estados del plugin -> estilo de insignia existente', { skip }, () => {
  for (const s of ['uploaded', 'downloaded', 'up_to_date'])
    assert.deepEqual(m.httpBadge(res({ state: s })), { status: 'ok', key: 'sync.state.ok' });
  assert.deepEqual(m.httpBadge(res({ state: 'conflict' })), { status: 'conflict', key: 'sync.state.conflict' });
  assert.deepEqual(m.httpBadge(res({ state: 'error' })), { status: 'error', key: 'sync.state.error' });
  assert.deepEqual(m.httpBadge(res({ state: 'missing_dir' })), { status: 'warn', key: 'hook.sync.missing_dir' });
  assert.deepEqual(m.httpBadge(res({ state: 'no_path' })), { status: 'warn', key: 'hook.sync.no_path' });
  assert.equal(m.httpBadge(null), null);
  assert.equal(m.httpBadge(res({ state: 'raro' })), null);
});

test('lastHttpResult: el más reciente del juego; null sin resultados', { skip }, () => {
  const list = [
    res({ at: '2026-01-01T09:00:00Z' }),
    res({ device: 'tv', at: '2026-01-01T11:00:00Z', state: 'error' }),
    res({ game: 'otro', at: '2026-01-02T00:00:00Z' }),
  ];
  assert.equal(m.lastHttpResult(list, 'g').state, 'error');
  assert.equal(m.lastHttpResult(list, 'nada'), null);
  assert.equal(m.lastHttpResult(undefined, 'g'), null);
});

test('httpRunStatus: forma que pinta LastRun, sin dry-run', { skip }, () => {
  const s = m.httpRunStatus(res({ state: 'error', code: 'boom' }));
  assert.equal(s.finished, '2026-01-01T10:30:00Z');
  assert.equal(s.code, 'hook.sync.error');
  assert.deepEqual(s.params, { reason: 'boom' });
  assert.ok(!s.dry_run && !s.result);
});

const mk = (games) => ({ devices: { deck: { name: 'Steam Deck', http: true }, pc: { name: 'PC' } }, games });
const HTTP = { name: 'Call of Cthulhu', devices: ['deck'] };
const MIXED = { name: 'Clásico', devices: ['deck', 'pc'] };
const render = (config, watch, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.Sync, { config, watch }));
};
const W = (results) => ({ now: null, watches: [], playing: [], results });

test('tarjeta solo http: «Última sync» con el resultado del plugin, sin Simulación', { skip }, () => {
  const h = render(mk({ g: HTTP }), W([res({ state: 'uploaded' })]));
  assert.ok(has(h, 'lastrun') && has(h, 'Última sync') && has(h, 'lr-time') && has(h, 'lr-date'));
  assert.ok(has(h, 'Detalle') && has(h, 'Subido al hub'));
  assert.ok(!has(h, 'lr-tag') && !/Simulaci/.test(h));
  assert.ok(has(h, 'badge ok'));
  const en = render(mk({ g: HTTP }), W([res({ state: 'error', code: 'boom' })]), 'en');
  assert.ok(has(en, 'Last sync') && has(en, 'Sync error: boom') && has(en, 'badge error'));
});

test('tarjeta solo http: sin resultados no hay bloque ni insignia', { skip }, () => {
  const h = render(mk({ g: HTTP }), W([]));
  assert.ok(!has(h, 'lastrun') && !has(h, 'class="badge') && !has(h, 'Sin ejecuciones'));
  assert.ok(has(h, 'Se sincroniza desde el propio dispositivo'));
});

test('tarjeta solo http: nunca ABORTED del estado antiguo del hub', { skip }, () => {
  // status vacío en el render estático (getStatus es asíncrono): la insignia sale solo del resultado del plugin.
  const h = render(mk({ g: HTTP }), W([res({ state: 'conflict' })]));
  assert.ok(!/aborted/i.test(h));
  assert.ok(has(h, 'badge conflict'));
});

test('juego mixto: sigue con Sincronizar y sin bloque del plugin', { skip }, () => {
  const h = render(mk({ g: MIXED }), W([res()]));
  assert.ok(has(h, 'btn primary">Sincronizar') && !has(h, 'Subido al hub'));
});

const css = sass.compile(fileURLToPath(new URL('../../src/styles/main.scss', import.meta.url)), { style: 'expanded' }).css;
const rule = (sel) => css.match(new RegExp(`(?:^|\\n)${sel.replace(/[>.]/g, '\\$&')}\\s*\\{([^}]*)\\}`))?.[1] ?? '';

test('encabezado de tarjeta: separación entre título e insignia y estilo de aviso', () => {
  assert.match(rule('.grid > .card h3'), /gap:\s*0\.35rem 0\.75rem/);
  assert.match(css, /\.badge\.warn/);
});

test('insignia http y clásica: mismo helper, mismas clases y mismo marcado', { skip }, () => {
  // Clásica (status[g].result) y http (estado del plugin) salen de la misma tabla {status, key}.
  const pairs = [
    ['ok', 'uploaded'],
    ['ok', 'up_to_date'],
    ['conflict', 'conflict'],
    ['error', 'error'],
  ];
  for (const [result, state] of pairs) assert.deepEqual(m.resultBadge(result), m.httpBadge(res({ state })), `${result}/${state}`);
  assert.equal(m.resultBadge('desconocido'), null);
});

test('tarjeta solo http: la insignia es exactamente <span class="badge X">texto</span> como la clásica', { skip }, () => {
  const badge = (status, text) => m.renderToStaticMarkup(m.React.createElement(m.Badge, { status }, text));
  const cases = [
    ['uploaded', 'ok', 'OK'],
    ['conflict', 'conflict', 'Conflicto'],
    ['error', 'error', 'Error'],
  ];
  for (const [state, status, text] of cases) {
    const h = render(mk({ g: HTTP }), W([res({ state })]));
    assert.ok(has(h, badge(status, text)), `${state}: ${badge(status, text)}`);
  }
  const warn = render(mk({ g: HTTP }), W([res({ state: 'missing_dir' })]));
  assert.ok(/<span class="badge warn">[^<]+<\/span>/.test(warn));
});

test('insignia: punto y texto centrados en vertical (inline-flex + align-items) y punto sin encoger', () => {
  assert.match(rule('.badge'), /display:\s*inline-flex/);
  assert.match(rule('.badge'), /align-items:\s*center/);
  const dot = rule('.badge::before');
  assert.match(dot, /flex:\s*none/);
  assert.match(dot, /align-self:\s*center/);
  assert.match(css, /\.badge\.warn/);
});
