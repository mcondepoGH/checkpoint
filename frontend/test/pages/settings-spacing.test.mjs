// Separación entre bloques de las subpestañas de Configuración (General, Biblioteca, Lanzadores).
// Regla: el panel de la subpestaña es una columna con UN `gap`; los bloques de primer nivel no definen margen vertical propio
// (los márgenes sueltos se suman o colapsan y rompían la separación cada vez que se añadía o quitaba un bloque).
// Se compila el SCSS real con sass y se renderiza Configuración a HTML (sin navegador).
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import * as sass from 'sass';
import { bundle } from '../helpers/bundle.mjs';

const css = sass.compile(fileURLToPath(new URL('../../src/styles/main.scss', import.meta.url)), { style: 'expanded' }).css;

// Reglas planas {sel, decl}: la regex salta el preludio de @media y toma cada regla interna.
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), decl: m[2] }));

// Margen vertical positivo en una regla (los negativos son compensaciones de relleno, p. ej. la barra de guardar).
const verticalMargin = (decl) => {
  const bad = [];
  const val = (v) => v.trim() && !/^(0|0px|0rem|auto|-.*|calc\(\s*-.*)$/.test(v.trim());
  for (const [, prop, v] of decl.matchAll(/(margin(?:-top|-bottom|-block(?:-start|-end)?)?)\s*:\s*([^;]+)/g)) {
    if (prop === 'margin') {
      // Valores del atajo con calc(...) o var(...) dentro: se parten fuera de los paréntesis.
      const parts = v.match(/(?:[^\s(]+|\w*\([^)]*\))+/g) || [];
      const [top, , bottom] = [parts[0], parts[1] ?? parts[0], parts[2] ?? parts[0]];
      if (val(top) || val(bottom)) bad.push(`${prop}: ${v}`);
    } else if (val(v)) bad.push(`${prop}: ${v}`);
  }
  return bad;
};

test('el panel de subpestaña es una columna con un único gap', () => {
  const r = rules.find((x) => x.sel === '.uitabs.subnav > .uitabs-panel');
  assert.ok(r, 'regla del panel subnav');
  assert.match(r.decl, /display:\s*flex/);
  assert.match(r.decl, /flex-direction:\s*column/);
  assert.match(r.decl, /gap:\s*1\.5rem/);
});

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import Settings from '#src/pages/Settings.jsx';
  export { React, renderToStaticMarkup, i18n, Settings };`,
  { navigator: true, tag: 'ckpt-spacing' },
);

// Hijos directos (etiqueta + clases) de un nodo HTML: recorre el marcado con una pila, sin DOM.
const VOID = new Set(['input', 'br', 'img', 'hr', 'meta', 'link']);
const directChildren = (html, from) => {
  const out = [];
  const re = /<(\/?)([a-zA-Z][\w-]*)([^>]*?)(\/?)>/g;
  re.lastIndex = from;
  let depth = 0;
  for (let t; (t = re.exec(html));) {
    const [, close, tag, attrs, self] = t;
    if (close) {
      if (depth === 0) break;
      depth--;
      continue;
    }
    if (depth === 0) out.push({ tag, classes: (/class="([^"]*)"/.exec(attrs)?.[1] || '').split(/\s+/).filter(Boolean) });
    if (!self && !VOID.has(tag)) depth++;
  }
  return out;
};

test('los bloques de primer nivel de cada subpestaña no definen margen vertical propio', { skip }, () => {
  m.i18n.setLocale('es');
  const html = m.renderToStaticMarkup(
    m.React.createElement(m.Settings, {
      loaded: {
        version: 'v1',
        config: { max_versions: 5, devices: { 'pc-1a2b3c4d': { name: 'Mi PC', host: 'h', user: 'u', os: 'linux', port: 22 } }, games: {} },
      },
      stale: false,
      configError: null,
      runtime: 'host',
      platform: 'linux',
      onApplied() {},
      onReload() {},
      onDirty() {},
      updates: null,
      onUpdates() {},
    }),
  );
  const panels = [...html.matchAll(/<div[^>]*class="uitabs-panel"[^>]*>/g)];
  assert.equal(panels.length, 3);
  let checked = 0;
  for (const p of panels) {
    for (const child of directChildren(html, p.index + p[0].length)) {
      for (const r of rules) {
        // Última pieza del selector, solo clases: `.a.b` aplica a este hijo si todas sus clases las tiene.
        const last = r.sel.split(',').map((s) =>
          s
            .trim()
            .split(/\s*[>+~ ]\s*/)
            .pop(),
        );
        for (const l of last) {
          const cls = l.match(/^(\.[\w-]+)+$/) ? l.split('.').filter(Boolean) : null;
          if (!cls || !cls.every((c) => child.classes.includes(c))) continue;
          assert.deepEqual(verticalMargin(r.decl), [], `${r.sel} (bloque «${child.classes.join('.') || child.tag}»)`);
          checked++;
        }
      }
    }
  }
  assert.ok(checked > 5, 'se comprobó algún bloque');
});

test('Biblioteca: SSH, versiones, dispositivos, juegos y barra cuelgan del mismo panel', { skip }, () => {
  m.i18n.setLocale('es');
  const html = m.renderToStaticMarkup(
    m.React.createElement(m.Settings, {
      loaded: {
        version: 'v1',
        config: { max_versions: 5, devices: { 'pc-1a2b3c4d': { name: 'Mi PC', host: 'h', user: 'u', os: 'linux', port: 22 } }, games: {} },
      },
      stale: false,
      configError: null,
      runtime: 'host',
      platform: 'linux',
      onApplied() {},
      onReload() {},
      onDirty() {},
      updates: null,
      onUpdates() {},
    }),
  );
  const panels = [...html.matchAll(/<div[^>]*class="uitabs-panel"[^>]*>/g)];
  const kids = directChildren(html, panels[1].index + panels[1][0].length).map((c) => c.classes.join('.'));
  for (const c of ['card.pubkey', 'card.cfg-card', 'cfg-section', 'actionbar']) assert.ok(kids.includes(c), `${c} en ${kids}`);
});
