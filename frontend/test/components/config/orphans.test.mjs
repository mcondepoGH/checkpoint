// Pantalla de datos sin dispositivo ni juego (OrphanList) y aviso en Versiones, renderizados a HTML.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import { OrphanList } from '#src/components/config/Orphans.jsx';
  import { OrphansNotice } from '#src/pages/Versions.jsx';
  export { React, renderToStaticMarkup, i18n, OrphanList, OrphansNotice };`,
  { navigator: true, tag: 'ckpt-orphans' },
);

const ORIGIN = {
  id: 'origin:g:gone-1',
  kind: 'origin',
  game: 'g',
  source: 'gone-1',
  size: 2048,
  files: 4,
  versions: 3,
  oldest: '2026-01-01 10:00:00',
  newest: '2026-02-03 04:05:06',
  only_copy: false,
  token: 't1',
};
const GAME = { ...ORIGIN, id: 'game:old', kind: 'game', game: 'old', source: null, only_copy: true, token: 't2' };
const noop = () => {};
const base = { items: [], trash: [], ttlDays: 30, selected: [], busy: false, notice: null, confirming: false, ack: false };
const GAMES = [
  { id: 'tgt', name: 'Destino <b>' },
  { id: 'other', name: 'Otro' },
];
const handlers = {
  onToggle: noop,
  onAsk: noop,
  onCancel: noop,
  onAck: noop,
  onConfirm: noop,
  onRestore: noop,
  onDismiss: noop,
  onRelocate: noop,
  onTarget: noop,
  onRelocateCancel: noop,
  onRelocateConfirm: noop,
};
const render = (props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.OrphanList, { ...base, ...handlers, ...props }));
};

test('sin datos, sin papelera y sin aviso no se pinta nada', { skip }, () => {
  assert.equal(render({}), '');
});

test('fila de origen desconocido: nombre, tamaño, versiones y fechas', { skip }, () => {
  const h = render({ items: [ORIGIN] });
  assert.ok(h.includes('g · dispositivo desconocido (gone-1)'));
  assert.ok(h.includes('2 KB') && h.includes('2026-01-01 10:00:00') && h.includes('2026-02-03 04:05:06'));
  assert.ok(h.includes('30 días') && !h.includes('Única copia'));
});

test('juego fuera de la configuración con única copia: aviso y días de papelera', { skip }, () => {
  const h = render({ items: [GAME] });
  assert.ok(h.includes('old · juego fuera de la configuración'));
  assert.ok(h.includes('Única copia') && h.includes('pasados 30 días'));
});

test('el botón de mover está desactivado sin selección y cuenta lo elegido', { skip }, () => {
  assert.match(render({ items: [ORIGIN] }), /<button[^>]*disabled[^>]*>Mover a la papelera… \(0\)/);
  const h = render({ items: [ORIGIN], selected: [ORIGIN.id] });
  assert.ok(!/<button[^>]*disabled[^>]*>Mover a la papelera/.test(h) && h.includes('Mover a la papelera… (1)'));
});

test('no hay botón de borrado directo, solo de papelera', { skip }, () => {
  const h = render({ items: [ORIGIN, GAME], selected: [ORIGIN.id] });
  assert.ok(!/Eliminar|Borrar ahora|Delete/.test(h));
});

test('diálogo de confirmación: resumen, casilla obligatoria y confirmar desactivado hasta marcarla', { skip }, () => {
  const props = { items: [ORIGIN], selected: [ORIGIN.id], confirming: true };
  const h = render(props);
  assert.ok(h.includes('role="dialog"') && h.includes('Se va a mover 1 elemento a la papelera'));
  assert.ok(h.includes('Entiendo que, pasados 30 días'));
  assert.match(h, /<button[^>]*disabled[^>]*>Confirmar y mover a la papelera/);
  assert.ok(!/<button[^>]*disabled[^>]*>Confirmar y mover a la papelera/.test(render({ ...props, ack: true })));
});

test('diálogo con única copia: texto reforzado', { skip }, () => {
  const h = render({ items: [ORIGIN, GAME], selected: [ORIGIN.id, GAME.id], confirming: true });
  assert.ok(h.includes('Se van a mover 2 elementos') && h.includes('Entre ellos hay datos que son la única copia'));
  assert.ok(h.includes('hay datos que son la única copia y que se borrarán del todo'));
});

test('papelera: entradas con restaurar y fecha de borrado', { skip }, () => {
  const trash = [
    {
      entry: '2026-03-01_000000',
      created: '2026-03-01T00:00:00+00:00',
      expires: '2026-03-31T00:00:00+00:00',
      items: [{ index: 0, kind: 'game', game: 'old', source: null, size: 1024 }],
    },
  ];
  const h = render({ trash });
  assert.ok(h.includes('Papelera') && h.includes('old · juego fuera de la configuración') && h.includes('>Restaurar<'));
});

test('aviso tras mover o restaurar', { skip }, () => {
  const h = render({ notice: { variant: 'ok', body: { code: 'orphans.moved', params: { count: 2 } } } });
  assert.ok(h.includes('Movidos a la papelera: 2 elementos'));
});

test('en inglés', { skip }, () => {
  const h = render({ items: [ORIGIN, GAME], selected: [GAME.id], confirming: true }, 'en');
  assert.ok(h.includes('g · unknown device (gone-1)') && h.includes('Only copy') && h.includes('Move to trash… (1)'));
  assert.ok(h.includes('I understand that some of it is the only copy'));
});

test('los nombres del disco se escapan (nunca HTML)', { skip }, () => {
  const h = render({ items: [{ ...ORIGIN, source: '<img src=x>' }] });
  assert.ok(!h.includes('<img src=x>') && h.includes('&lt;img src=x&gt;'));
});

test('aviso en Versiones: plural, enlace a Configuración y sin enlace si no hay manejador', { skip }, () => {
  m.i18n.setLocale('es');
  const r = (props) => m.renderToStaticMarkup(m.React.createElement(m.OrphansNotice, props));
  const one = r({ count: 1, onGoSettings: noop });
  assert.ok(one.includes('Hay 1 elemento de datos sin dispositivo ni juego') && one.includes('Revisar en Configuración'));
  assert.ok(r({ count: 3, onGoSettings: noop }).includes('Hay 3 elementos'));
  assert.ok(!r({ count: 2 }).includes('Revisar'));
});

test('«Reubicar…» solo en los juegos fuera de la configuración y con juegos de destino', { skip }, () => {
  const h = render({ items: [ORIGIN, GAME], games: GAMES });
  assert.equal(h.split('Reubicar…').length - 1, 1);
  assert.ok(!render({ items: [GAME], games: [] }).includes('Reubicar…'));
  assert.ok(!render({ items: [ORIGIN], games: GAMES }).includes('Reubicar…'));
});

test('diálogo de reubicar: desplegable con nombres legibles, resumen y confirmar desactivado sin destino', { skip }, () => {
  const props = { items: [GAME], games: GAMES, relocating: GAME };
  const h = render(props);
  assert.ok(h.includes('role="dialog"') && h.includes('Reubicar en un juego existente') && h.includes('Elige un juego…'));
  assert.ok(h.includes('<option value="tgt">Destino &lt;b&gt;</option>') && h.includes('<option value="other">Otro</option>'));
  assert.match(h, /<button[^>]*disabled[^>]*>Confirmar y reubicar/);
  assert.ok(!h.includes('conserva sus partidas actuales'));
  const c = render({ ...props, target: 'tgt' });
  assert.ok(!/<button[^>]*disabled[^>]*>Confirmar y reubicar/.test(c));
  assert.ok(c.includes('«Destino &lt;b&gt;» conserva sus partidas actuales') && c.includes('30 días') && c.includes('2 KB'));
  assert.ok(c.includes('<dd>old</dd>') && c.includes('<dd>3</dd>'));
});

test('diálogo de reubicar en inglés y ocupado', { skip }, () => {
  const h = render({ items: [GAME], games: GAMES, relocating: GAME, target: 'other', busy: true }, 'en');
  assert.ok(h.includes('Relocate to an existing game') && h.includes('keeps its current saves'));
  assert.match(h, /<button[^>]*disabled[^>]*>Relocating…/);
});

test('aviso tras reubicar', { skip }, () => {
  const h = render({ notice: { variant: 'ok', body: { code: 'orphans.relocated', params: { count: 2, target: 'Destino' } } } });
  assert.ok(h.includes('Reubicado en «Destino»: 2 versiones sumadas a su historial'));
});
