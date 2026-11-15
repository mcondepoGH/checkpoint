import test from 'node:test';
import assert from 'node:assert/strict';
import { startPolling } from '#src/lib/poll.js';

function fake(hidden = false) {
  const listeners = new Set();
  const doc = {
    hidden,
    addEventListener: (_, f) => listeners.add(f),
    removeEventListener: (_, f) => listeners.delete(f),
  };
  let fn = null;
  const timers = {
    setInterval: (f) => ((fn = f), 7),
    clearInterval: (id) => id === 7 && (fn = null),
  };
  return { doc, listeners, timers, tick: () => fn && fn(), active: () => fn !== null };
}

test('consulta al empezar, en cada intervalo y al volver a ver la pestaña', () => {
  const f = fake();
  let n = 0;
  startPolling(() => n++, 5000, f.doc, f.timers);
  assert.equal(n, 1);
  f.tick();
  assert.equal(n, 2);
  f.doc.hidden = true;
  f.tick();
  assert.equal(n, 2, 'con la pestaña oculta no consulta');
  f.doc.hidden = false;
  [...f.listeners].forEach((l) => l());
  assert.equal(n, 3, 'al volver a verla refresca');
});

test('pestaña oculta desde el inicio: no consulta', () => {
  const f = fake(true);
  let n = 0;
  startPolling(() => n++, 5000, f.doc, f.timers);
  assert.equal(n, 0);
});

test('detener limpia temporizador y escuchador', () => {
  const f = fake();
  const stop = startPolling(() => {}, 5000, f.doc, f.timers);
  assert.ok(f.active() && f.listeners.size === 1);
  stop();
  assert.ok(!f.active() && f.listeners.size === 0);
});

// El navegador exige this === window en setInterval/clearInterval y lanza TypeError si se llaman como método de otro objeto.
function strictGlobals() {
  const real = { si: globalThis.setInterval, ci: globalThis.clearInterval };
  const guard = (real, name) =>
    function (...a) {
      if (this !== globalThis) throw new TypeError(`Can only call Window.${name} on instances of Window`);
      return real.apply(globalThis, a);
    };
  globalThis.setInterval = guard(real.si, 'setInterval');
  globalThis.clearInterval = guard(real.ci, 'clearInterval');
  return () => Object.assign(globalThis, { setInterval: real.si, clearInterval: real.ci });
}

test('con temporizadores que exigen this === global (como el navegador) arranca y se detiene', () => {
  const restore = strictGlobals();
  try {
    let n = 0;
    const stop = startPolling(() => n++, 5000, null);
    assert.equal(n, 1);
    assert.doesNotThrow(stop);
  } finally {
    restore();
  }
});
