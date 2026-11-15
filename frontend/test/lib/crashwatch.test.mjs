// Manejador global de fallos: filtrado de ruido, agrupación de repeticiones, tope de avisos y detalles saneados.
// Lógica pura con un doble de `window` (sin navegador).
import test from 'node:test';
import assert from 'node:assert/strict';
import { isNoise, startCrashWatch } from '../../src/lib/crashwatch.js';

function fakeWin() {
  const l = {};
  return {
    navigator: { userAgent: 'UA-test' },
    addEventListener: (n, f) => (l[n] ||= new Set()).add(f),
    removeEventListener: (n, f) => l[n]?.delete(f),
    count: (n) => l[n]?.size ?? 0,
    fire: (n, ev) => [...(l[n] || [])].forEach((f) => f(ev)),
  };
}
const setup = (opts = {}) => {
  const win = fakeWin();
  let t = 1000;
  const seen = [];
  const w = startCrashWatch(win, { now: () => t, onChange: (x) => seen.push(x), version: '1.2.3', ...opts });
  return { win, w, seen, tick: (ms) => (t += ms) };
};
const err = (message, extra = {}) => ({ message, error: Object.assign(new Error(message), extra.error), ...extra.ev });

test('registra error y unhandledrejection una vez y la limpieza los quita', () => {
  const { win, w } = setup();
  assert.equal(win.count('error'), 1);
  assert.equal(win.count('unhandledrejection'), 1);
  w.stop();
  assert.equal(win.count('error'), 0);
  assert.equal(win.count('unhandledrejection'), 0);
});

test('un error no capturado genera un aviso con detalles saneados', () => {
  const { win, w } = setup();
  win.fire('error', err('falla con ck_clave123 y ckd_otra456'));
  const [a] = w.list();
  assert.equal(a.severity, 'alert');
  assert.match(a.details, /Checkpoint: 1\.2\.3/);
  assert.match(a.details, /User agent: UA-test/);
  assert.ok(!/ck_clave123|ckd_otra456/.test(a.details + a.title));
});

test('una promesa rechazada genera un aviso discreto (status) con detalles saneados', () => {
  const { win, w } = setup();
  win.fire('unhandledrejection', { reason: new TypeError('token ck_secreto999 roto') });
  const [a] = w.list();
  assert.equal(a.severity, 'status');
  assert.ok(!a.details.includes('secreto999'));
  win.fire('unhandledrejection', { reason: 'texto suelto' });
  assert.equal(w.list().length, 2);
});

test('ruido: ResizeObserver, recursos, sin mensaje, AbortError, extensiones', () => {
  assert.ok(isNoise('error', { message: 'ResizeObserver loop completed with undelivered notifications.' }));
  assert.ok(isNoise('error', { message: 'ResizeObserver loop limit exceeded' }));
  assert.ok(isNoise('error', { target: { tagName: 'IMG' }, message: undefined }));
  assert.ok(isNoise('error', { message: 'Script error.', error: null }));
  assert.ok(isNoise('error', { message: '' }));
  assert.ok(isNoise('error', { message: 'boom', filename: 'chrome-extension://abc/x.js', error: new Error('boom') }));
  assert.ok(isNoise('error', { message: 'x', filename: 'safari-extension://abc/x.js' }));
  const ab = new Error('The user aborted a request.');
  ab.name = 'AbortError';
  assert.ok(isNoise('unhandledrejection', { reason: ab }));
  assert.ok(isNoise('unhandledrejection', { reason: new DOMException('x', 'AbortError') }));
  assert.ok(isNoise('unhandledrejection', { reason: undefined }));
  assert.ok(isNoise('unhandledrejection', { reason: {} }));
  assert.ok(!isNoise('error', { message: 'x is not a function', error: new TypeError('x is not a function') }));
  assert.ok(!isNoise('unhandledrejection', { reason: 'fallo real' }));
});

test('el ruido no crea avisos', () => {
  const { win, w } = setup();
  win.fire('error', { message: 'ResizeObserver loop limit exceeded' });
  win.fire('error', { target: { tagName: 'SCRIPT' } });
  win.fire('unhandledrejection', { reason: new DOMException('x', 'AbortError') });
  assert.equal(w.list().length, 0);
});

test('repeticiones iguales dentro de la ventana no duplican; pasada la ventana sí', () => {
  const { win, w, tick } = setup({ dedupeMs: 5000 });
  win.fire('error', err('mismo fallo'));
  tick(1000);
  win.fire('error', err('mismo fallo'));
  assert.equal(w.list().length, 1);
  tick(6000);
  win.fire('error', err('mismo fallo'));
  assert.equal(w.list().length, 2);
});

test('tope de avisos visibles: sale el más antiguo', () => {
  const { win, w, tick } = setup({ max: 3 });
  for (const m of ['a', 'b', 'c', 'd']) {
    win.fire('error', err(`fallo ${m}`));
    tick(10);
  }
  const msgs = w.list().map((x) => x.details);
  assert.equal(msgs.length, 3);
  assert.ok(!msgs.some((d) => d.includes('fallo a')));
  assert.ok(msgs.some((d) => d.includes('fallo d')));
});

test('dismiss cierra un aviso y notifica', () => {
  const { win, w, seen } = setup();
  win.fire('error', err('uno'));
  w.dismiss(w.list()[0].id);
  assert.equal(w.list().length, 0);
  assert.ok(seen.length >= 2);
});

test('errores de red: sin pila, sin parámetros de URL', () => {
  const { win, w } = setup();
  const e = new TypeError('Failed to fetch https://h.local/api?key=ck_abc123&x=1');
  e.stack = 'TypeError: Failed to fetch\n    at secretFn (app.js:1:1)';
  win.fire('unhandledrejection', { reason: e });
  const [a] = w.list();
  assert.ok(!a.details.includes('secretFn'));
  assert.ok(!/key=|ck_abc123|x=1/.test(a.details));
});

test('si onChange falla no hay bucle ni se rompe el manejador', () => {
  const { win, w } = setup({
    onChange: () => {
      throw new Error('onChange roto');
    },
  });
  win.fire('error', err('uno'));
  win.fire('error', err('dos'));
  assert.equal(w.list().length, 2);
});

test('un evento que rompe el análisis no lanza (reentrada)', () => {
  const { win, w } = setup();
  const bad = {
    get message() {
      throw new Error('getter roto');
    },
  };
  assert.doesNotThrow(() => win.fire('error', bad));
  assert.doesNotThrow(() =>
    win.fire('unhandledrejection', {
      get reason() {
        throw new Error('x');
      },
    }),
  );
  assert.equal(w.list().length, 0);
});
