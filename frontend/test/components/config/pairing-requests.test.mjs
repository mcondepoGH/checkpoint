// Solicitudes de vinculación (PairingList) y tarjeta http con su bloque de clave, renderizadas a HTML.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { PairingList } from '#src/components/config/PairingRequests.jsx';
  import DeviceKey from '#src/components/config/DeviceKey.jsx';
  import DeviceCard from '#src/components/config/DeviceCard.jsx';
  import { normalizePending } from '#src/lib/pairing.js';
  export { React, renderToStaticMarkup, PairingList, DeviceKey, DeviceCard, normalizePending };`,
  { tag: 'ckpt-pairing' },
);

const has = (h, s) => h.includes(s);
const NOW = 1_000_000;
const row = (o = {}) => ({
  id: 'r1',
  name: 'Steam Deck',
  os: 'linux',
  code: '482913',
  ip: '192.0.2.9',
  expires_in: 125,
  existing: 'none',
  ...o,
});
const list = (rows, props = {}) =>
  mod.renderToStaticMarkup(
    mod.React.createElement(mod.PairingList, {
      rows: mod.normalizePending(rows, NOW),
      busy: null,
      notice: null,
      dirty: false,
      now: NOW,
      onAccept() {},
      onReject() {},
      onDismiss() {},
      ...props,
    }),
  );

test('sin solicitudes ni aviso no se pinta nada', { skip }, () => {
  assert.equal(list([]), '');
});

test('fila: nombre, código, IP, tiempo restante, comprobación y botones', { skip }, () => {
  const h = list([row()]);
  assert.ok(has(h, 'Steam Deck') && has(h, '482913') && has(h, '192.0.2.9'));
  assert.ok(has(h, '2:05'));
  assert.ok(has(h, 'Comprueba que el código 482913 es el que muestra tu dispositivo'));
  assert.ok(has(h, '>Aceptar<') && has(h, '>Rechazar<'));
  assert.ok(!/<button[^>]*disabled[^>]*>Aceptar/.test(h));
  assert.ok(!has(h, 'se reutilizará') && !has(h, 'no es http'));
});

test('existing http: avisa de que se reutiliza y regenera la clave; Aceptar activo', { skip }, () => {
  const h = list([row({ existing: 'http' })]);
  assert.ok(has(h, 'se reutilizará y se regenerará su clave'));
  assert.ok(!/<button[^>]*disabled[^>]*>Aceptar/.test(h));
});

test('existing other: aviso, Aceptar deshabilitado, Rechazar activo y sin texto de comprobación', { skip }, () => {
  const h = list([row({ existing: 'other' })]);
  assert.ok(has(h, 'no es http') && has(h, 'solo rechazar'));
  assert.ok(/<button[^>]*disabled[^>]*>Aceptar/.test(h));
  assert.ok(!/<button[^>]*disabled[^>]*>Rechazar/.test(h));
  assert.ok(!has(h, 'Comprueba que el código'));
});

test('caducada: Aceptar deshabilitado y texto «Caducada»', { skip }, () => {
  const h = list([row({ expires_in: 0 })]);
  assert.ok(has(h, 'Caducada') && /<button[^>]*disabled[^>]*>Aceptar/.test(h));
});

test('en curso: todos los botones deshabilitados', { skip }, () => {
  const h = list([row(), row({ id: 'r2', name: 'Otro' })], { busy: 'r1' });
  assert.equal((h.match(/<button[^>]*disabled/g) || []).length, 4);
});

test('varias solicitudes y aviso de borrador sucio', { skip }, () => {
  const h = list([row(), row({ id: 'r2', name: 'Otro', code: '111111' })], { dirty: true });
  assert.ok(has(h, 'Otro') && has(h, '111111'));
  assert.ok(has(h, 'cambios sin guardar'));
  assert.ok(!has(list([row()], { dirty: false }), 'cambios sin guardar'));
});

test('avisos: éxito, borrador sucio y error se pintan con su variante', { skip }, () => {
  const ok = list([], { notice: { variant: 'ok', body: { code: 'pairing.accepted', params: { name: 'Deck' } } } });
  assert.ok(has(ok, 'alert ok') && has(ok, '«Deck» vinculado'));
  const warn = list([], { notice: { variant: 'warn', body: { code: 'pairing.acceptedDirty', params: { name: 'Deck' } } } });
  assert.ok(has(warn, 'alert warn') && has(warn, 'Guarda o descarta'));
  const err = list([row()], { notice: { variant: 'error', body: { code: 'pairing.configChanged', params: {} } } });
  assert.ok(has(err, 'alert error') && has(err, 'Vuelve a pulsar Aceptar'));
  for (const code of ['pairing.gone', 'pairing.notPending']) {
    assert.ok(has(list([], { notice: { variant: 'error', body: { code, params: {} } } }), 'La lista se ha actualizado'));
  }
});

// --- Tarjeta http y bloque de clave ---
const dev = (o = {}) => ({
  key: 'd1',
  id: 'deck-1a2b3c4d',
  name: 'Steam Deck',
  orig: 'Steam Deck',
  local: false,
  http: true,
  host: 'oculto.example',
  port: '22',
  user: 'oculto',
  os: 'linux',
  ...o,
});
const card = (d, props = {}) =>
  mod.renderToStaticMarkup(
    mod.React.createElement(mod.DeviceCard, {
      dev: d,
      errors: {},
      idText: d.id,
      renamed: false,
      onChange() {},
      onTest() {},
      onRemove() {},
      runtime: 'native',
      platform: 'linux',
      canLocal: true,
      ...props,
    }),
  );

test('tarjeta http: distintivo, ayuda, nombre editable, SO solo lectura, sin campos SSH ni «Probar conexión»', { skip }, () => {
  const h = card(dev());
  assert.ok(has(h, '>Plugin<') && has(h, 'no hace falta SSH'));
  assert.ok(has(h, 'value="Steam Deck"'));
  assert.ok(has(h, 'Sistema operativo') && has(h, '<strong>Linux</strong>') && !has(h, '<select'));
  for (const s of [
    'Host / IP',
    'Puerto',
    'Usuario',
    'Probar conexión',
    'Comprobar carpeta',
    'Este equipo',
    'oculto.example',
    'type="checkbox"',
  ]) {
    assert.ok(!has(h, s), `no debe aparecer ${s}`);
  }
  assert.ok(has(h, 'Eliminar') && has(h, 'Eliminar dispositivo Steam Deck'));
});

test('tarjeta SSH normal no cambia (sin distintivo ni bloque de clave)', { skip }, () => {
  const h = card(dev({ http: false }));
  assert.ok(has(h, 'Host / IP') && has(h, 'Probar conexión'));
  assert.ok(!has(h, '>Plugin<') && !has(h, 'Clave del dispositivo'));
});

const key = (initial, props = {}) =>
  mod.renderToStaticMarkup(mod.React.createElement(mod.DeviceKey, { deviceId: 'deck-1a2b3c4d', initial, insecure: false, ...props }));
const loaded = { loaded: true };

test('clave con estado «Tiene clave»: acciones y la clave NO está en el DOM', { skip }, () => {
  const h = key({ ...loaded, exists: true });
  assert.ok(has(h, 'Tiene clave'));
  for (const b of ['>Ver<', '>Copiar<', '>Regenerar<', '>Revocar<']) assert.ok(has(h, b), b);
  assert.ok(!has(h, 'ckd_') && !has(h, 'copybox'));
  assert.ok(!/<button[^>]*disabled/.test(h));
});

test('clave visible: se pinta en la caja de copiar y el botón pasa a Ocultar', { skip }, () => {
  const h = key({ ...loaded, exists: true, key: 'ckd_abcdef' });
  assert.ok(has(h, 'ckd_abcdef') && has(h, '>Ocultar<') && !has(h, '>Ver<'));
});

test('sin clave: estado «Sin clave» y solo Generar', { skip }, () => {
  const h = key({ ...loaded, exists: false });
  assert.ok(has(h, 'Sin clave') && has(h, '>Generar clave<'));
  assert.ok(!has(h, '>Ver<') && !has(h, '>Regenerar<') && !has(h, '>Revocar<'));
});

const isOpen = (h) => /<details[^>]*\sopen/.test(h);

test('desplegable de clave: cerrado con clave existente, con el estado en el resumen', { skip }, () => {
  const h = key({ ...loaded, exists: true });
  assert.ok(has(h, '<details') && !isOpen(h));
  assert.match(h, /<summary[^>]*>Clave del dispositivo<span[^>]*>Tiene clave<\/span><\/summary>/);
  assert.ok(!has(h, 'ckd_'));
});

test('desplegable de clave: abierto sin clave y tras generar o regenerar; resumen siempre visible', { skip }, () => {
  const n = key({ ...loaded, exists: false });
  assert.ok(isOpen(n) && has(n, '<summary') && has(n, 'Sin clave') && has(n, '>Generar clave<'));
  const f = key({ ...loaded, exists: true, key: 'ckd_nueva', fresh: true });
  assert.ok(isOpen(f) && has(f, '<summary') && has(f, 'Tiene clave') && has(f, 'ckd_nueva'));
  const v = key({ ...loaded, exists: true, key: 'ckd_vista' });
  assert.ok(!isOpen(v) && has(v, '<summary'));
  assert.ok(!isOpen(key(null)) && has(key(null), '<summary'));
});

test('desplegable de clave: avisos de borrador dentro del desplegable', { skip }, () => {
  const h = key({ ...loaded, exists: true }, { lock: 'devkey.lockDirty' });
  assert.ok(h.indexOf('cambios sin guardar') > h.indexOf('</summary>'));
});

test('confirmaciones claras de regenerar y revocar', { skip }, () => {
  const r = key({ ...loaded, exists: true, confirm: 'regenerate' });
  assert.ok(has(r, 'role="alertdialog"') && has(r, 'La clave anterior dejará de valer y habrá que ponerla de nuevo en el dispositivo'));
  assert.ok(has(r, 'Sí, regenerar') && has(r, 'Cancelar'));
  const v = key({ ...loaded, exists: true, confirm: 'revoke' });
  assert.ok(has(v, 'Sí, revocar') && has(v, 'dejará de poder conectarse'));
});

test('bloqueada (cambios sin guardar o dispositivo nuevo): acciones deshabilitadas con explicación', { skip }, () => {
  const d = key({ ...loaded, exists: true }, { lock: 'devkey.lockDirty' });
  assert.ok(has(d, 'cambios sin guardar'));
  assert.equal((d.match(/<button[^>]*disabled/g) || []).length, 4);
  const n = key(null, { deviceId: null, lock: 'devkey.lockNew' });
  assert.ok(has(n, 'Guarda primero la configuración'));
});

test('error de la API y copiado', { skip }, () => {
  const e = key({ ...loaded, exists: true, error: { code: 'err.hook.device_not_http', params: {} } });
  assert.ok(has(e, 'role="alert"'));
  const c = key({ ...loaded, exists: true, copied: true });
  assert.ok(has(c, '>Copiado<'));
});

test('tarjeta http renombrada: bloque de clave bloqueado', { skip }, () => {
  const h = card(dev({ name: 'Otro nombre' }), { renamed: true });
  assert.ok(has(h, 'cambios sin guardar'));
});
