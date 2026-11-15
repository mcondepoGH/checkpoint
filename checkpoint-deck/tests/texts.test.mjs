// Textos del sistema de actualizaciones (src/texts.ts). Se compila con el esbuild del frontend del hub; sin él, se omite.
// Ejecutar: node --test tests/texts.test.mjs
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

async function load() {
  const out = join(mkdtempSync(join(tmpdir(), 'tx-')), 'tx.mjs');
  const r = await esbuild.build({ entryPoints: [join(here, '../src/texts.ts')], bundle: true, format: 'esm', write: false });
  writeFileSync(out, r.outputFiles[0].text);
  return import(pathToFileURL(out));
}

test('los códigos de error que quedan tienen texto y el desconocido cae en uno genérico', { skip }, async () => {
  const { updateError, UPDATE_ERRORS } = await load();
  for (const c of ['hub_old', 'connection', 'unauthorized', 'rate_limited', 'hub_error', 'not_linked', 'unavailable', 'unknown', 'unexpected']) {
    assert.ok(UPDATE_ERRORS[c], c);
  }
  assert.equal(updateError('algo_nuevo'), UPDATE_ERRORS.unexpected);
});

test('ya no hay textos de instalación dentro del plugin', { skip }, async () => {
  const t = await load();
  for (const n of ['describeInstall', 'describeBusy', 'describeManualZip', 'shortZipPath', 'MANUAL_ZIP_BUTTON', 'MANUAL_STEPS', 'RESTART_NOTICE']) {
    assert.equal(t[n], undefined, n);
  }
  for (const c of ['busy', 'sha_mismatch', 'too_large', 'truncated', 'bad_path', 'unsafe_link', 'bad_package', 'install_failed',
    'rollback_failed', 'not_newer', 'zip_incompatible', 'version_mismatch', 'bad_info', 'bad_zip']) {
    assert.equal(t.UPDATE_ERRORS[c], undefined, c);
  }
});

test('la compatibilidad avisa de cada caso', { skip }, async () => {
  const { describeCompat } = await load();
  assert.equal(describeCompat('ok'), null);
  assert.match(describeCompat('plugin_outdated', { min_plugin_protocol: 2, plugin_protocol: 1 }), /Actualiza el plugin/);
  assert.match(describeCompat('hub_old'), /hub.*antiguo|antigua|versión vieja/i);
  assert.match(describeCompat('plugin_unknown'), /versión del protocolo/i);
});

test('el aviso de versión nueva distingue estados y no promete instalar ni recargar', { skip }, async () => {
  const { describeUpdate } = await load();
  assert.equal(describeUpdate({ state: 'up_to_date', current: '0.1.0' }), 'El plugin está al día (0.1.0).');
  const a = describeUpdate({ state: 'available', current: '0.1.0', latest: '0.2.0', plain_http: true });
  assert.equal(a, 'Actualización disponible: 0.2.0 (instalada: 0.1.0).');
  assert.doesNotMatch(a, /http|sin cifrar|en claro/i);
  const old = describeUpdate({ state: 'available', current: '0.1.0', latest: '0.2.0', reason: 'hub_old' });
  assert.match(old, /hub/i);
  assert.match(old, /antigua/i);
  assert.doesNotMatch(old, /Instalar plugin desde URL/);
});

test('el aviso de versión nueva da los pasos de Decky y no afirma que se recargue solo', { skip }, async () => {
  const { UPDATE_TITLE, UPDATE_STEPS } = await load();
  assert.equal(UPDATE_TITLE('0.2.1'), 'Actualización disponible: 0.2.1');
  assert.equal(UPDATE_STEPS.length, 3);
  assert.equal(UPDATE_STEPS[0], '1) Ajustes de Decky > Desarrollador > Instalar plugin desde URL.');
  assert.equal(UPDATE_STEPS[1], '2) Pega esta dirección:');
  assert.equal(UPDATE_STEPS[2], '3) Reinicia Decky si no se recarga solo.');
  assert.doesNotMatch(UPDATE_STEPS.join(' '), /acepta|admite|funciona con http|se recarga automáticamente/i);
});

test('el panel de juegos: introducción corta y sin decir lo que no se puede hacer', { skip }, async () => {
  const { GAMES_INTRO } = await load();
  assert.match(GAMES_INTRO, /abrir/i);
  assert.match(GAMES_INTRO, /cerrarlo|cerrar/i);
  assert.match(GAMES_INTRO, /hub/i);
  assert.ok(GAMES_INTRO.length < 120, `demasiado larga: ${GAMES_INTRO.length}`);
  assert.doesNotMatch(GAMES_INTRO, /\bno\b|nunca|solo a mano|copia de seguridad/i);
});

test('buscar y comprobar se distinguen: cada botón dice qué hace y no se parecen', { skip }, async () => {
  const { SEARCH_LABEL, SEARCH_HELP, CHECK_LABEL, CHECK_HELP } = await load();
  assert.notEqual(SEARCH_LABEL, CHECK_LABEL);
  assert.match(SEARCH_HELP, /instalados/i);
  assert.match(CHECK_HELP, /sin cambiar nada/i);
  assert.match(CHECK_HELP, /subir|bajar/i);
  assert.doesNotMatch(CHECK_LABEL, /estado/i); // «Comprobar estado» era la etiqueta ambigua
});

test('los errores al configurar o activar un juego tienen texto propio', { skip }, async () => {
  const { gameError } = await load();
  assert.match(gameError({ error: 'game_invalid', error_params: { field: 'name', reason: 'err.config.name_duplicate' } }), /con ese nombre/i);
  assert.match(gameError({ error: 'game_invalid', error_params: { field: 'path', reason: 'err.config.nueva' } }), /ruta/i);
  assert.match(gameError({ error: 'game_invalid' }), /no acepta/i);
  const why = (reason) => gameError({ error: 'game_invalid', error_params: { field: 'name', reason } });
  assert.equal(why('err.steam.no_free_slot'), 'El juego ya tiene 2 dispositivos.');
  assert.equal(why('err.steam.appid_mismatch'), 'Ese nombre ya existe con otro juego de Steam.');
  assert.match(why('err.steam.appid_in_use'), /otro juego/i);
  assert.match(why('err.config.name_duplicate'), /con ese nombre/i);
  assert.match(gameError({ error: 'path_forbidden' }), /carpeta/i);
  assert.match(gameError({ error: 'unknown_game' }), /Busca de nuevo/i);
  assert.match(gameError({ error: 'connection' }), /conectar/i);
  assert.match(gameError({ error: 'rate_limited', error_params: { wait_s: 30 } }), /30 s/);
  assert.match(gameError({ error: 'plugin_outdated' }), /plugin/i);
});

test('ya no hay aviso de HTTP plano en los textos', { skip }, async () => {
  const t = await load();
  assert.equal(t.PLAIN_HTTP_WARNING, undefined);
});

test('la URL del plugin se deriva del hub sin doble barra', { skip }, async () => {
  const { pluginUrl } = await load();
  assert.equal(pluginUrl('http://hub:8000'), 'http://hub:8000/api/deck/plugin');
  assert.equal(pluginUrl('http://hub:8000/'), 'http://hub:8000/api/deck/plugin');
  assert.equal(pluginUrl('http://hub:8000///'), 'http://hub:8000/api/deck/plugin');
  assert.equal(pluginUrl('https://x.org/base/'), 'https://x.org/base/api/deck/plugin');
  assert.doesNotMatch(pluginUrl('http://h/'), /[^:]\/\//);
});

test('el selector nativo de Decky recibe valores explícitos y válidos en todos los parámetros', { skip }, async () => {
  const { pickerArgs } = await load();
  const a = pickerArgs('/home/deck/saves');
  assert.equal(a.length, 8); // openFilePicker(select, ...a): startPath, files, folders, filter, extensions, hidden, allowAll, max
  const [start, files, folders, filter, exts, hidden, allowAll, max] = a;
  assert.equal(start, '/home/deck/saves');
  assert.equal(files, false);
  assert.equal(folders, true);
  assert.equal(filter, undefined); // RegExp/función viajan como {} y el backend de Decky lanza; sin filtro llega null
  assert.equal(exts, undefined); // sin extensiones llega null: el backend lo admite (lista vacía también)
  assert.equal(hidden, true);
  assert.equal(allowAll, true);
  assert.equal(max, 1000);
  assert.equal(typeof max, 'number');
  // lo que viaja por el websocket: ni objetos ni NaN (un {} en filter o un null en max lanzan en filepicker_ls)
  const wire = JSON.parse(JSON.stringify(a));
  for (const v of [wire[0], wire[1], wire[2], wire[5], wire[6], wire[7]]) assert.notEqual(v, null);
  assert.ok(wire.every((v) => v === null || typeof v !== 'object'));
});

test('el selector tiene texto de botón, de ayuda y del fallo conocido de Decky', { skip }, async () => {
  const t = await load();
  assert.match(t.BROWSE_LABEL, /Examinar/);
  assert.match(t.BROWSE_HELP, /ruta/i);
  assert.match(t.PICKER_FAIL, /Decky no puede abrir esa carpeta/);
  assert.match(t.PICKER_FAIL, /escribe la ruta/i);
  assert.ok(t.PICKER_FAIL.length < 80);
  for (const gone of ['BROWSE_USE', 'BROWSE_UP', 'BROWSE_CLOSE', 'BROWSE_EMPTY', 'BROWSE_TRUNCATED', 'browseError', 'pickerStart']) {
    assert.equal(t[gone], undefined, gone);
  }
});

test('el examinador propio ya no está en la interfaz ni en el contrato con main.py', () => {
  const src = readFileSync(join(here, '../src/index.tsx'), 'utf8');
  for (const gone of ['list_dirs', 'listDirs', 'Browsed', 'BROWSE_USE', 'BROWSE_UP', 'browseTo', 'useBrowsed']) {
    assert.ok(!src.includes(gone), gone);
  }
  assert.match(src, /openFilePicker\(FileSelectionType\.FOLDER, \.\.\.pickerArgs\(/); // el nativo, con los argumentos de texts.ts
  assert.match(src, /callable<\[path: string\], \{ ok: boolean; path: string \}>\("picker_start"\)/);
});

test('el último aviso tiene texto corto en español', { skip }, async () => {
  const t = await load();
  for (const k of ['TEST_DIRECT_LABEL', 'TEST_DIRECT_HELP', 'TEST_DIRECT_BODY', 'TEST_PLUGIN_LABEL', 'TEST_PLUGIN_HELP', 'NOTICE_TEST_BODY']) {
    assert.equal(t[k], undefined, k);
  }
  assert.equal(t.lastNoticeText(null), 'Último aviso: Ninguno todavía');
  assert.equal(t.lastNoticeText({ time: '14:05', text: 'Uno: save subido al hub.' }), 'Último aviso: 14:05 — Uno: save subido al hub.');
});

test('«Actividad reciente» ya no existe en textos, panel ni backend', () => {
  for (const f of ['../src/index.tsx', '../src/texts.ts', '../src/autosync.ts', '../main.py', '../py_modules/checkpoint_auto.py']) {
    const s = readFileSync(join(here, f), 'utf8');
    assert.doesNotMatch(s, /Actividad reciente|get_activity|getActivity|ACTIVITY_|ActivityItem|activityLine|Sin actividad/, f);
  }
});

test('el interruptor de juegos sin configurar tiene texto corto y el contador no da nombres', { skip }, async () => {
  const t = await load();
  assert.equal(t.SHOW_UNCONFIGURED_LABEL, 'Mostrar juegos sin configurar');
  assert.ok(t.SHOW_UNCONFIGURED_HELP && !t.SHOW_UNCONFIGURED_HELP.includes('\n') && t.SHOW_UNCONFIGURED_HELP.length < 90);
  assert.equal(t.hiddenUnconfiguredText(1), '1 juego sin configurar oculto');
  assert.equal(t.hiddenUnconfiguredText(3), '3 juegos sin configurar ocultos');
});

test('unconfiguredView decide qué se muestra según el interruptor y el conteo', { skip }, async () => {
  const { unconfiguredView } = await load();
  assert.deepEqual(unconfiguredView(true, 2), { showList: true, hiddenNote: null });
  assert.deepEqual(unconfiguredView(true, 0), { showList: false, hiddenNote: null });
  assert.deepEqual(unconfiguredView(false, 2), { showList: false, hiddenNote: '2 juegos sin configurar ocultos' });
  assert.deepEqual(unconfiguredView(false, 1), { showList: false, hiddenNote: '1 juego sin configurar oculto' });
  assert.deepEqual(unconfiguredView(false, 0), { showList: false, hiddenNote: null });
});

test('el panel usa el interruptor con get_prefs y set_pref', () => {
  const src = readFileSync(join(here, '../src/index.tsx'), 'utf8');
  assert.match(src, /callable<[^>]*>\("get_prefs"\)/);
  assert.match(src, /callable<[^\n]*>\("set_pref"\)/);
  assert.match(src, /SHOW_UNCONFIGURED_LABEL/);
  assert.match(src, /unconfiguredView\(/);
});

test('la interfaz no llama a ningún método que instale: ni install_update ni botón de descarga', () => {
  const src = readFileSync(join(here, '../src/index.tsx'), 'utf8');
  assert.doesNotMatch(src, /install_update|installUpdate|describeInstall|Descargar el zip|Actualizar a /);
  assert.match(src, /check_update/);
});

test('el panel y el backend ya no ofrecen probar avisos', () => {
  for (const f of ['../src/index.tsx', '../src/texts.ts', '../src/autosync.ts', '../main.py']) {
    const s = readFileSync(join(here, f), 'utf8');
    assert.doesNotMatch(s, /Probar aviso|test_notice|testNotice|NOTICE_TEST_BODY/, f);
  }
});

test('copiar la dirección: botón y mensajes de éxito y de fallo', { skip }, async () => {
  const { COPY_BUTTON, COPY_OK, COPY_FAIL } = await load();
  assert.equal(COPY_BUTTON, 'Copiar dirección');
  assert.equal(COPY_OK, 'Dirección copiada');
  assert.equal(COPY_FAIL, 'No se pudo copiar: selecciona y escribe la dirección');
});

test('al unirse a un juego existente el aviso es corto y nombra el juego', { skip }, async () => {
  const { joinedText } = await load();
  assert.equal(joinedText('Celeste'), 'Celeste: unido a este equipo');
  assert.ok([...joinedText('Z'.repeat(80))].length <= 45);
});


test('resolver un conflicto: errores con texto, confirmaciones y estado de conflicto obsoleto', { skip }, async () => {
  const t = await load();
  for (const c of ['bad_winner', 'resolution_unsupported', 'resolution_stale', 'side_empty']) assert.ok(t.SYNC_ERRORS[c], c);
  assert.match(t.syncError('resolution_unsupported'), /El hub no admite esta función: actualízalo/);
  assert.equal(t.RESOLVE_HUB_LABEL, 'Usar datos del hub');
  assert.equal(t.RESOLVE_DEVICE_LABEL, 'Usar datos de este equipo');
  const hub = t.resolveConfirm('hub', 'Celeste');
  assert.match(hub.title, /Celeste/);
  assert.match(hub.description, /checkpoint-backup/);
  assert.equal(hub.ok, 'Usar datos del hub');
  const dev = t.resolveConfirm('device', 'Celeste');
  assert.match(dev.description, /versión/);
  assert.equal(dev.ok, 'Usar datos de este equipo');
  assert.match(t.conflictText({ state: 'conflict', code: 'resolution_stale' }), /Conflicto sin resolver.*cambiaron/);
  assert.match(t.conflictText({ state: 'conflict', code: 'game_running' }), /abierto/);
  assert.match(t.conflictText({ state: 'conflict', code: 'codigo_raro' }), /Conflicto: cambios/);
  assert.match(t.conflictText({ state: 'conflict' }), /Conflicto/);
});
