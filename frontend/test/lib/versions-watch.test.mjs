import test from 'node:test';
import assert from 'node:assert/strict';
import { watchLatest, VERSIONS_POLL_MS } from '#src/lib/versionsWatch.js';

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
const flush = () => new Promise((r) => setTimeout(r, 0));

function setup(answers, hidden = false) {
  const f = fake(hidden);
  const changes = [];
  let i = 0;
  const fetchLimit = () => {
    const a = answers[Math.min(i++, answers.length - 1)];
    return a instanceof Error ? Promise.reject(a) : Promise.resolve(a);
  };
  const stop = watchLatest(fetchLimit, (l) => changes.push(l), VERSIONS_POLL_MS, f.doc, f.timers);
  return { f, changes, stop, calls: () => i };
}

test('el intervalo es de unos 15 s', () => {
  assert.equal(VERSIONS_POLL_MS, 15000);
});

test('la primera consulta fija la base y no recarga', async () => {
  const s = setup([{ latest: 'v1', count: 1 }]);
  await flush();
  assert.deepEqual(s.changes, []);
});

test('recarga si cambia el id de la última versión', async () => {
  const s = setup([
    { latest: 'v1', count: 5 },
    { latest: 'v2', count: 6 },
  ]);
  await flush();
  s.f.tick();
  await flush();
  assert.deepEqual(s.changes, [{ latest: 'v2', count: 6 }]);
});

test('recarga aunque count no cambie (rotación a max_versions)', async () => {
  const s = setup([
    { latest: 'v1', count: 20 },
    { latest: 'v2', count: 20 },
  ]);
  await flush();
  s.f.tick();
  await flush();
  assert.equal(s.changes.length, 1);
});

test('no recarga si no cambia y avisa una sola vez por cambio', async () => {
  const s = setup([{ latest: 'v1' }, { latest: 'v1' }, { latest: 'v2' }, { latest: 'v2' }]);
  await flush();
  for (let i = 0; i < 3; i++) {
    s.f.tick();
    await flush();
  }
  assert.deepEqual(s.changes, [{ latest: 'v2' }]);
});

test('con la pestaña oculta no consulta; al volver, sí', async () => {
  const s = setup([{ latest: 'v1' }, { latest: 'v2' }], true);
  await flush();
  assert.equal(s.calls(), 0);
  s.f.tick();
  assert.equal(s.calls(), 0);
  s.f.doc.hidden = false;
  [...s.f.listeners].forEach((l) => l());
  await flush();
  assert.equal(s.calls(), 1);
});

test('un fallo de red no molesta y se conserva la base', async () => {
  const s = setup([{ latest: 'v1' }, new Error('red'), { latest: 'v1' }, { latest: 'v2' }]);
  await flush();
  for (let i = 0; i < 3; i++) {
    s.f.tick();
    await flush();
  }
  assert.deepEqual(s.changes, [{ latest: 'v2' }]);
});

test('una respuesta sin latest (hub antiguo) se ignora', async () => {
  const s = setup([
    { max: 3, count: 1 },
    { max: 3, count: 2 },
  ]);
  await flush();
  s.f.tick();
  await flush();
  assert.deepEqual(s.changes, []);
});

test('la primera versión de un juego sin ninguna también recarga', async () => {
  const s = setup([
    { latest: null, count: 0 },
    { latest: 'v1', count: 1 },
  ]);
  await flush();
  s.f.tick();
  await flush();
  assert.deepEqual(s.changes, [{ latest: 'v1', count: 1 }]);
});

test('no solapa consultas', async () => {
  const f = fake();
  let calls = 0;
  let release;
  const fetchLimit = () => (calls++, new Promise((r) => (release = r)));
  watchLatest(fetchLimit, () => {}, 1000, f.doc, f.timers);
  f.tick();
  f.tick();
  assert.equal(calls, 1);
  release({ latest: 'a' });
  await flush();
  f.tick();
  assert.equal(calls, 2);
});

test('detener limpia el temporizador y no avisa después', async () => {
  const s = setup([{ latest: 'v1' }, { latest: 'v2' }]);
  await flush();
  s.stop();
  assert.equal(s.f.active(), false);
  assert.equal(s.f.listeners.size, 0);
  await flush();
  assert.deepEqual(s.changes, []);
});

test('si se detiene con una consulta en vuelo, su resultado se descarta', async () => {
  const f = fake();
  const changes = [];
  const rel = [];
  const stop = watchLatest(
    () => new Promise((r) => rel.push(r)),
    (l) => changes.push(l),
    1000,
    f.doc,
    f.timers,
  );
  rel[0]({ latest: 'v1' });
  await flush();
  f.tick();
  stop();
  rel[1]({ latest: 'v2' });
  await flush();
  assert.deepEqual(changes, []);
});

test('recarga si cambia el «Actual» del hub aunque la última versión no cambie', async () => {
  const s = setup([
    { latest: 'v1', current: { id: '1-2-8' } },
    { latest: 'v1', current: { id: '1-2-8' } },
    { latest: 'v1', current: { id: '5-2-9' } },
  ]);
  await flush();
  s.f.tick();
  await flush();
  assert.deepEqual(s.changes, []);
  s.f.tick();
  await flush();
  assert.equal(s.changes.length, 1);
  assert.equal(s.changes[0].current.id, '5-2-9');
});

test('recarga cuando el hub pasa de vacío (current null) a tener datos y al revés', async () => {
  const s = setup([
    { latest: null, current: null },
    { latest: null, current: { id: 'a' } },
    { latest: null, current: null },
  ]);
  await flush();
  s.f.tick();
  await flush();
  s.f.tick();
  await flush();
  assert.equal(s.changes.length, 2);
});
