// Lógica pura del panel por pestañas (src/panel.ts + textos nuevos de src/texts.ts). Sin Decky ni React.
// Se compila con el esbuild del frontend del hub (../frontend/node_modules); sin él, se omite.
// Ejecutar: node --test tests/panel.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
let esbuild;
try {
  esbuild = createRequire(import.meta.url)(join(here, '../../frontend/node_modules/esbuild'));
} catch {
  /* sin esbuild: se omite */
}
const skip = esbuild ? false : 'falta ../frontend/node_modules/esbuild';

async function load(entry) {
  const out = join(mkdtempSync(join(tmpdir(), 'pn-')), 'pn.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/', entry)], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  return import(pathToFileURL(out));
}

const G = (o = {}) => ({ id: 'g', name: 'Juego', appid: 1, enabled: true, state: 'up_to_date', ...o });
const H = (o = {}) => ({ link: 'linked', online: true, outdated: false, playing: null, running: false, conflicts: 0, errors: 0, ...o });

test('homeStatus: prioridad de estados y forma con texto', { skip }, async () => {
  const { homeStatus } = await load('panel.ts');
  assert.deepEqual(homeStatus(H()), { tone: 'ok', label: 'Todo al día' });
  assert.equal(homeStatus(H({ link: 'unlinked' })).label, 'Sin vincular');
  assert.equal(homeStatus(H({ link: 'waiting' })).label, 'Esperando aceptación');
  assert.equal(homeStatus(H({ link: 'error' })).label, 'Sin vincular');
  assert.equal(homeStatus(H({ conflicts: 1, errors: 1 })).label, 'Conflicto');
  assert.equal(homeStatus(H({ errors: 2 })).tone, 'err');
  assert.equal(homeStatus(H({ running: true, conflicts: 1 })).label, 'Sincronizando');
  assert.equal(homeStatus(H({ playing: 'Hades', running: true })).label, 'Juego abierto');
  assert.equal(homeStatus(H({ online: false, playing: 'Hades' })).label, 'Sin conexión');
  assert.deepEqual(homeStatus(H({ outdated: true, online: false })), { tone: 'err', label: 'Plugin antiguo' });
});

test('gameBadge: un desactivado manda sobre el estado; desconocidos caen en «Sin comprobar»', { skip }, async () => {
  const { gameBadge } = await load('panel.ts');
  assert.deepEqual(gameBadge('upload'), { tone: 'info', label: 'Por subir' });
  assert.deepEqual(gameBadge('conflict', false), { tone: 'nf', label: 'Desactivado' });
  assert.deepEqual(gameBadge('algo_raro'), { tone: 'nf', label: 'Sin comprobar' });
  assert.equal(gameBadge('missing_dir').label, 'Carpeta no encontrada');
});

test('countStates / playingGame ignoran los desactivados', { skip }, async () => {
  const { countStates, playingGame, conflictGames } = await load('panel.ts');
  const games = [G({ id: 'a', state: 'upload' }), G({ id: 'b', state: 'conflict', appid: 2 }), G({ id: 'c', state: 'conflict', enabled: false, appid: 3 }), G({ id: 'd', state: 'error', appid: null })];
  assert.deepEqual(countStates(games), { upload: 1, download: 0, conflict: 1, error: 1 });
  assert.deepEqual(conflictGames(games).map((g) => g.id), ['b']);
  assert.equal(playingGame(new Set([2]), games).id, 'b');
  assert.equal(playingGame(new Set([3]), games), null);
  assert.equal(playingGame(new Set(), games), null);
});

test('tally: conflictos y errores no frenan; juego abierto no es error; cortes dejan «a medias»', { skip }, async () => {
  const { tally } = await load('panel.ts');
  const plan = ['a', 'b', 'c', 'd', 'e', 'f'];
  const t = tally(plan, {
    a: { state: 'uploaded' }, b: { state: 'downloaded' }, c: { state: 'conflict' }, d: { state: 'error', code: 'file_changed' },
    e: { state: 'error', code: 'game_running' }, f: { state: 'up_to_date' },
  });
  assert.deepEqual(t, { up: 1, down: 1, conf: 1, err: 1, skipped: 1, left: 0, interrupted: false });
  const cut = tally(plan, { a: { state: 'uploaded' }, b: { state: 'error', code: 'connection' }, c: { state: 'error', code: 'cancelled' } });
  assert.equal(cut.left, 5);
  assert.equal(cut.interrupted, true);
  assert.equal(cut.err, 0);
  assert.equal(cut.up, 1);
  assert.equal(tally([], {}).interrupted, false);
});

test('progressRows: hecho, en curso, en espera, fallo, conflicto, abierto y sin sincronizar', { skip }, async () => {
  const { progressRows } = await load('panel.ts');
  const names = { a: 'A', b: 'B', c: 'C', d: 'D', e: 'E', f: 'F', g: 'G' };
  const rows = progressRows(['a', 'b', 'c', 'd', 'e', 'f', 'g'], {
    a: { state: 'uploaded' }, b: { state: 'downloaded' }, c: { state: 'error', code: 'io_error' }, d: { state: 'conflict' }, e: { state: 'error', code: 'game_running' },
  }, 'f', names, false);
  assert.deepEqual(rows.map((r) => r.kind), ['done', 'done', 'fail', 'conflict', 'skip', 'run', 'wait']);
  assert.equal(rows[0].text, '✓ subido');
  assert.equal(rows[1].text, '✓ bajado');
  assert.equal(rows[0].name, 'A');
  const end = progressRows(['a', 'b'], { a: { state: 'uploaded' } }, null, {}, true);
  assert.equal(end[1].kind, 'left');
  assert.equal(end[1].name, 'b');
});

test('summaryLevel', { skip }, async () => {
  const { summaryLevel } = await load('panel.ts');
  const t = (o) => ({ up: 0, down: 0, conf: 0, err: 0, skipped: 0, left: 0, interrupted: false, ...o });
  assert.equal(summaryLevel(t({ up: 2 })), 'ok');
  assert.equal(summaryLevel(t({ conf: 1 })), 'warn');
  assert.equal(summaryLevel(t({ left: 2, interrupted: true })), 'warn');
  assert.equal(summaryLevel(t({ err: 1, conf: 1 })), 'error');
});

test('summaryText y summaryToast: singular/plural, al día y tope de 45 caracteres', { skip }, async () => {
  const { summaryText, summaryToast, TOAST_MAX } = await load('texts.ts');
  assert.equal(summaryText({ up: 1, down: 2, conf: 0, err: 0 }), '1 subido, 2 bajados, 0 conflictos');
  assert.equal(summaryText({ up: 0, down: 0, conf: 1, err: 1 }), '0 subidos, 0 bajados, 1 conflicto, 1 error');
  assert.equal(summaryText({ up: 0, down: 0, conf: 0, err: 0 }), 'Todo estaba al día');
  assert.equal(summaryToast({ up: 1, down: 2, conf: 0, err: 0 }), '1 subido, 2 bajados');
  assert.equal(summaryToast({ up: 0, down: 0, conf: 0, err: 0 }), 'Todo estaba al día');
  assert.equal(summaryToast({ up: 1, down: 1, conf: 1, err: 0 }), '1 subido, 1 bajado, 1 conflicto');
  const big = summaryToast({ up: 10, down: 20, conf: 30, err: 40 });
  assert.equal(big, 'Terminó con incidencias: mira Juegos');
  for (const t of [{ up: 1, down: 0, conf: 0, err: 0 }, { up: 99, down: 99, conf: 99, err: 99 }, { up: 0, down: 0, conf: 0, err: 5 }, { up: 12, down: 3, conf: 2, err: 1 }])
    assert.ok([...summaryToast(t)].length <= TOAST_MAX && !summaryToast(t).includes('…'), summaryToast(t));
});

test('syncBlockReason y canSyncRest', { skip }, async () => {
  const { syncBlockReason, canSyncRest } = await load('panel.ts');
  const g = (o) => ({ link: 'linked', online: true, outdated: false, playing: null, running: false, ...o });
  assert.equal(syncBlockReason(g()), null);
  assert.equal(syncBlockReason(g({ playing: 'Hades' })), 'Hades está abierto: se sincroniza solo al cerrarlo.');
  assert.equal(syncBlockReason(g({ online: false })), 'Sin conexión: no se puede sincronizar.');
  assert.equal(syncBlockReason(g({ outdated: true, online: false })), 'Actualiza el plugin para volver a sincronizar.');
  assert.equal(syncBlockReason(g({ running: true })), 'Hay una tarea en marcha.');
  assert.equal(syncBlockReason(g({ link: 'unlinked' })), 'Primero vincula la Deck con el hub.');
  assert.equal(canSyncRest(g({ playing: 'Hades' })), true);
  assert.equal(canSyncRest(g()), false);
  assert.equal(canSyncRest(g({ playing: 'Hades', online: false })), false);
  assert.equal(canSyncRest(g({ playing: 'Hades', running: true })), false);
});

test('firstPlan y firstConfirm: lo que baja, sube, se salta y queda en conflicto', { skip }, async () => {
  const { firstPlan } = await load('panel.ts');
  const { firstConfirm } = await load('texts.ts');
  const p = firstPlan([G({ state: 'download' }), G({ state: 'download' }), G({ state: 'upload' }), G({ state: 'conflict' }), G({ enabled: false, state: 'download' }), G({ state: 'no_path' }), G({ state: 'up_to_date' })]);
  assert.deepEqual(p, { down: 2, up: 1, conflicts: 1, skipped: 2 });
  const c = firstConfirm(p);
  assert.match(c.description, /Se bajan del hub: 2 juegos/);
  assert.match(c.description, /Se suben al hub: 1 juego\n/);
  assert.match(c.description, /Se saltan \(desactivados o sin carpeta\): 2 juegos/);
  assert.equal(c.ok, 'Sincronizar todo');
  assert.doesNotMatch(firstConfirm({ down: 0, up: 0, conflicts: 0, skipped: 0 }).description, /Se saltan/);
});

const B = (o = {}) => ({
  tab: 'games', link: 'linked', online: true, outdated: false, outdatedText: 'Actualiza.', running: false, summary: null, playing: null,
  conflict: null, failed: false, failedText: 'Falló.', firstSync: false, update: null, connectionText: 'No se pudo conectar.', ...o,
});
const T = (o = {}) => ({ up: 0, down: 0, conf: 0, err: 0, skipped: 0, left: 0, interrupted: false, ...o });

test('banners: sin vincular solo avisa fuera de Inicio y sin vincular nada más', { skip }, async () => {
  const { banners } = await load('panel.ts');
  assert.deepEqual(banners(B({ link: 'unlinked', tab: 'home' })), []);
  const b = banners(B({ link: 'unlinked', tab: 'set', conflict: 'X', playing: 'Y' }));
  assert.equal(b.length, 1);
  assert.equal(b[0].action.kind, 'go_home');
  assert.deepEqual(banners(B({ link: 'waiting', tab: 'set' })), []);
});

test('banners: máximo 2 por prioridad; sin banner de resumen', { skip }, async () => {
  const { banners } = await load('panel.ts');
  const b = banners(B({ summary: T({ up: 1, conf: 1 }), outdated: true, online: false, playing: 'Hades', conflict: 'Cuphead' }));
  assert.deepEqual(b.map((x) => x.id), ['outdated', 'offline']);
  const c = banners(B({ online: false, playing: 'Hades', conflict: 'Cuphead', failed: true }));
  assert.deepEqual(c.map((x) => x.id), ['offline', 'playing']);
  assert.match(c[0].text, /^No se pudo conectar\. El cierre de un juego queda en cola/);
});

test('banners: sincronización cortada ofrece reintentar o probar la conexión; sin resumen mientras corre', { skip }, async () => {
  const { banners } = await load('panel.ts');
  const cut = T({ up: 1, left: 3, interrupted: true });
  assert.equal(banners(B({ summary: cut }))[0].action.kind, 'retry');
  assert.match(banners(B({ summary: cut }))[0].text, /^Quedaron 3 juegos sin sincronizar\./);
  assert.equal(banners(B({ summary: cut, online: false }))[0].action.kind, 'ping');
  assert.match(banners(B({ summary: T({ interrupted: true, left: 1 }) }))[0].text, /^Quedaron 1 juego sin/);
  assert.deepEqual(banners(B({ summary: cut, running: true })), []);
  // el éxito (y el resumen con conflictos o errores) solo va por toast: ningún banner de resumen
  assert.deepEqual(banners(B({ summary: T({ up: 2 }) })), []);
  assert.deepEqual(banners(B({ summary: T({ up: 1, conf: 1 }) })), []);
  assert.deepEqual(banners(B({ summary: T({ err: 1 }) })), []);
  // los problemas siguen fijos por su propio aviso, sin duplicar el toast de éxito
  assert.deepEqual(banners(B({ summary: T({ conf: 1 }), conflict: 'Cuphead' })).map((x) => x.id), ['conflict']);
  assert.deepEqual(banners(B({ summary: T({ err: 1 }), failed: true })).map((x) => x.id), ['failed']);
  const { BANNER } = await load('texts.ts');
  assert.equal(BANNER.doneTitle, undefined);
});

test('banners: dispositivo nuevo, actualización y conflicto con su acción', { skip }, async () => {
  const { banners } = await load('panel.ts');
  const f = banners(B({ firstSync: true }));
  assert.equal(f[0].id, 'first');
  assert.equal(f[0].action.kind, 'sync_all');
  assert.deepEqual(banners(B({ firstSync: true, summary: T({ up: 1 }) })).map((x) => x.id), []); // tras sincronizar ya no
  assert.deepEqual(banners(B({ firstSync: true, online: false })).map((x) => x.id), ['offline']);
  const u = banners(B({ update: { latest: '1.3.0', current: '1.2.1' } }))[0];
  assert.equal(u.title, 'Actualización disponible: 1.3.0');
  assert.equal(u.text, 'Instalada: 1.2.1.');
  assert.equal(u.action.kind, 'go_ver');
  const c = banners(B({ conflict: 'Cuphead' }))[0];
  assert.equal(c.title, 'Conflicto en Cuphead.');
  assert.equal(c.action.kind, 'go_games');
  assert.deepEqual(banners(B()), []);
});

const TI = (o = {}) => ({ link: 'linked', conflicts: 0, errors: 0, pending: 0, showPending: true, updateAvailable: false, ...o });

test('tabDot y tabDisabled', { skip }, async () => {
  const { tabDot, tabDisabled } = await load('panel.ts');
  assert.equal(tabDot('games', TI()), null);
  assert.deepEqual(tabDot('games', TI({ conflicts: 1 })), { kind: 'attention' });
  assert.deepEqual(tabDot('games', TI({ errors: 1 })), { kind: 'attention' });
  assert.deepEqual(tabDot('pend', TI({ pending: 3 })), { kind: 'count', n: 3, label: '3 pendientes' });
  assert.equal(tabDot('pend', TI({ pending: 1 })).label, '1 pendiente');
  assert.equal(tabDot('pend', TI({ pending: 3, showPending: false })), null);
  assert.deepEqual(tabDot('ver', TI({ updateAvailable: true })), { kind: 'update' });
  assert.equal(tabDot('games', TI({ link: 'unlinked', conflicts: 2 })), null); // desactivada: sin punto
  assert.equal(tabDot('ver', TI({ link: 'unlinked', updateAvailable: true })).kind, 'update'); // Versión no necesita vínculo
  assert.equal(tabDisabled('games', false), true);
  assert.equal(tabDisabled('sugg', false), true);
  assert.equal(tabDisabled('pend', false), true);
  assert.equal(tabDisabled('set', false), false);
  assert.equal(tabDisabled('ver', false), false);
  assert.equal(tabDisabled('games', true), false);
});

test('stepTab: L1/R1 saltan las desactivadas y no dan la vuelta', { skip }, async () => {
  const { stepTab } = await load('panel.ts');
  assert.equal(stepTab('home', 1, true), 'games');
  assert.equal(stepTab('games', -1, true), 'home');
  assert.equal(stepTab('home', -1, true), 'home');
  assert.equal(stepTab('ver', 1, true), 'ver');
  assert.equal(stepTab('home', 1, false), 'set'); // sin vincular: salta Juegos, Sugerencias y Pendientes
  assert.equal(stepTab('set', -1, false), 'home');
  assert.equal(stepTab('set', 1, false), 'ver');
});

test('whenText y latestSync', { skip }, async () => {
  const { whenText, latestSync } = await load('panel.ts');
  const now = new Date(2026, 10, 16, 15, 0, 0);
  const at = (d, h, m) => new Date(2026, 10, d, h, m, 0).getTime() / 1000;
  assert.equal(whenText(at(16, 9, 5), now), 'hoy 09:05');
  assert.equal(whenText(at(15, 23, 30), now), 'ayer 23:30');
  assert.equal(whenText(at(3, 8, 0), now), '03/11/2026 08:00');
  assert.equal(whenText(null, now), 'ninguna todavía');
  assert.equal(whenText(0, now), 'ninguna todavía');
  assert.equal(latestSync([{ last_at: 5 }, {}, { last_at: 9 }, { last_at: 2 }]), 9);
  assert.equal(latestSync([{}]), null);
});

test('VersionNotifier avisa una vez por versión; updatedTo solo si cambió', { skip }, async () => {
  const { VersionNotifier, hasUpdate, updatedTo } = await load('panel.ts');
  const n = new VersionNotifier();
  assert.equal(n.shouldToast('1.3.0'), true);
  assert.equal(n.shouldToast('1.3.0'), false);
  assert.equal(n.shouldToast('1.4.0'), true);
  assert.equal(n.shouldToast(null), false);
  assert.equal(hasUpdate({ state: 'available', latest: '1.3.0' }), true);
  assert.equal(hasUpdate({ state: 'up_to_date', latest: '1.3.0' }), false);
  assert.equal(hasUpdate({ state: 'available', latest: null }), false);
  assert.equal(hasUpdate(null), false);
  assert.equal(updatedTo(null, '1.3.0'), null);
  assert.equal(updatedTo('1.3.0', '1.3.0'), null);
  assert.equal(updatedTo('1.2.1', '1.3.0'), '1.3.0');
});

test('textos nuevos: toasts de menos de 45 caracteres', { skip }, async () => {
  const t = await load('texts.ts');
  for (const s of [t.UPDATED_TOAST('10.20.30'), t.VER_AUTO_TOAST('10.20.30-rc.1'), t.SYNC_CUT_TOAST, t.SYNC_CANCELLED_TOAST, t.UNLINK_TOAST, t.JOINED_TOAST, t.LINKED_TOAST]) {
    assert.ok([...s].length <= t.TOAST_MAX, s);
  }
  assert.equal(t.UPDATED_TOAST('1.3.0'), 'Checkpoint actualizado a 1.3.0');
  assert.equal(t.VER_AUTO_TOAST('1.3.3'), 'Hay una versión nueva: 1.3.3');
  assert.equal(t.SYNC_CUT_TOAST, 'Sin conexión: quedaron juegos pendientes');
  assert.equal(t.SYNC_CANCELLED_TOAST, 'Sincronización cancelada');
  assert.equal(t.UNLINK_TOAST, 'Deck desvinculada. Revoca la clave en el hub');
  assert.ok([...t.UNLINK_TOAST].length <= t.TOAST_MAX);
  assert.ok([...t.JOINED_TOAST].length <= t.TOAST_MAX);
  assert.equal(t.VER_AUTO_TOAST('10.20.30-rc.1-con-sufijo-larguisimo').endsWith('…'), true);
  assert.equal(t.LINKED_TOAST, 'Deck vinculada con el hub correctamente');
  assert.deepEqual(t.TAB_ORDER, ['home', 'games', 'sugg', 'pend', 'set', 'ver']);
  assert.equal(t.COMING_SOON, undefined);
  assert.equal(t.CHANGED_VIEW, undefined);
});

test('gameExpanded: plegada salvo conflicto o error activados; lo que elige el usuario manda', { skip }, async () => {
  const { gameExpanded } = await load('panel.ts');
  for (const st of ['up_to_date', 'upload', 'download', 'unknown', 'no_path', 'missing_dir']) assert.equal(gameExpanded(G({ state: st })), false, st);
  assert.equal(gameExpanded(G({ state: 'conflict' })), true);
  assert.equal(gameExpanded(G({ state: 'error' })), true);
  assert.equal(gameExpanded(G({ state: 'conflict', enabled: false })), false);
  assert.equal(gameExpanded(G({ state: 'conflict' }), false), false);
  assert.equal(gameExpanded(G({ state: 'up_to_date' }), true), true);
});

test('tabScrollLeft: centra la pestaña, sin pasarse y sin scroll si caben', { skip }, async () => {
  const { tabScrollLeft } = await load('panel.ts');
  // 6 pestañas de 100 px en 400 px de barra (scrollWidth 600): máximo 200
  assert.equal(tabScrollLeft(0, 100, 400, 600), 0); // la primera
  assert.equal(tabScrollLeft(100, 100, 400, 600), 0); // aún no hace falta
  assert.equal(tabScrollLeft(250, 100, 400, 600), 100); // centrada
  assert.equal(tabScrollLeft(500, 100, 400, 600), 200); // la última: tope
  assert.equal(tabScrollLeft(300, 100, 400, 400), 0); // caben: sin scroll
  assert.equal(tabScrollLeft(300, 100, 400, 350), 0);
});

test('texto largo: salta de línea sin elipsis y con scroll solo por altura máxima', { skip }, async () => {
  const { LONG_TEXT_STYLE, LONG_TEXT_MAX_HEIGHT } = await load('panel.ts');
  assert.equal(LONG_TEXT_STYLE.whiteSpace, 'pre-wrap');
  assert.equal(LONG_TEXT_STYLE.overflowWrap, 'anywhere');
  assert.equal(LONG_TEXT_STYLE.maxHeight, LONG_TEXT_MAX_HEIGHT);
  assert.equal(LONG_TEXT_STYLE.overflowY, 'auto');
  assert.ok(!('textOverflow' in LONG_TEXT_STYLE) && !('WebkitLineClamp' in LONG_TEXT_STYLE));
});

test('«Último aviso» y «Fallos detectados» pintan el texto largo con LongText (sin Field, que corta)', () => {
  const idx = readFileSync(join(here, '../src/index.tsx'), 'utf8');
  assert.match(idx, /<LongText>\{lastNoticeText\(notice\)\}<\/LongText>/);
  const crash = idx.slice(idx.indexOf('function CrashNotices'), idx.indexOf('// ---- textos (español)'));
  assert.match(crash, /<LongText/);
  assert.doesNotMatch(crash, /<Field /);
});

test('FolderChanges: solo recuerda el último cambio; sin ruta anterior o con la misma no hay Deshacer', { skip }, async () => {
  const { FolderChanges } = await load('panel.ts');
  const f = new FolderChanges();
  let n = 0;
  f.subscribe(() => n++);
  assert.equal(f.undoOf('a'), undefined);
  f.applied('a', { path: '/b', previous: '/a' });
  assert.deepEqual(f.undoOf('a'), { path: '/b', previous: '/a' });
  f.applied('a', { path: '/c', previous: '/b' });
  assert.deepEqual(f.undoOf('a'), { path: '/c', previous: '/b' });
  f.applied('a', { path: '/c', previous: '/c' }); // misma ruta: nada cambia
  assert.deepEqual(f.undoOf('a'), { path: '/c', previous: '/b' });
  f.applied('x', { path: '/n', previous: null }); // no había ruta: no se puede deshacer
  assert.equal(f.undoOf('x'), undefined);
  f.undone('a');
  assert.equal(f.undoOf('a'), undefined);
  assert.ok(n >= 3);
});

test('FolderChanges: el error se recuerda por juego y se limpia; un cambio bien hecho lo borra', { skip }, async () => {
  const { FolderChanges } = await load('panel.ts');
  const f = new FolderChanges();
  f.fail('a', 'texto');
  assert.equal(f.errorOf('a'), 'texto');
  assert.equal(f.errorOf('b'), undefined);
  f.applied('a', { path: '/b', previous: '/a' });
  assert.equal(f.errorOf('a'), undefined);
  f.fail('a', 'otro');
  f.clearError('a');
  assert.equal(f.errorOf('a'), undefined);
});

test('FolderChanges: subscribe devuelve la baja', { skip }, async () => {
  const { FolderChanges } = await load('panel.ts');
  const f = new FolderChanges();
  let n = 0;
  const off = f.subscribe(() => n++);
  f.fail('a', 'x');
  off();
  f.fail('a', 'y');
  assert.equal(n, 1);
});

test('changeFolderBlock: con el juego abierto se desactiva y dice por qué; con una tarea en marcha, sin texto', { skip }, async () => {
  const { changeFolderBlock } = await load('panel.ts');
  assert.deepEqual(changeFolderBlock({ playing: false, busy: false }), { disabled: false, hint: null });
  assert.deepEqual(changeFolderBlock({ playing: true, busy: false }), { disabled: true, hint: 'Cierra el juego para cambiar la carpeta' });
  assert.deepEqual(changeFolderBlock({ playing: false, busy: true }), { disabled: true, hint: null });
  assert.equal(changeFolderBlock({ playing: true, busy: true }).hint, 'Cierra el juego para cambiar la carpeta');
});

test('FolderChanges: avisa «changed» al aplicar o deshacer y «error» al fallar o limpiar el error', { skip }, async () => {
  const { FolderChanges } = await load('panel.ts');
  const f = new FolderChanges();
  const seen = [];
  f.subscribe((k) => seen.push(k));
  f.applied('a', { path: '/b', previous: '/a' });
  f.fail('a', 'x');
  f.clearError('a');
  f.clearError('a'); // ya limpio: no avisa
  f.undone('a');
  assert.deepEqual(seen, ['changed', 'error', 'error', 'changed']);
});
