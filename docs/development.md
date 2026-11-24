# Desarrollo

Mapa del código y reglas de dependencia: [`structure.md`](structure.md). Aquí: arranque local, pruebas, lint, auditorías, publicación de versiones y guía de UI.

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt && pytest
cd ../frontend && npm install && npm run dev     # desarrollo
npm test                                         # pruebas de node (borrador, formato, i18n es/en, tarjeta de dispositivo, avisos de versión y arquitectura)
npm run build                                    # producción
```

## Pruebas

`pytest` a secas ya usa lo seguro por defecto (`addopts` en `backend/pytest.ini` y `checkpoint-deck/pytest.ini`): `-p no:cacheprovider -n 2`. Necesita `pytest-xdist` (en `requirements-dev.txt`; en el plugin, `pip install pytest pytest-xdist`).

```bash
cd backend
python -m pytest -q                                                       # por defecto: todo, -n 2, sin caché
python -m pytest -q -m "not slow" --basetemp=/dev/shm/ck-pytest           # ciclo rápido (más rápido aún)
python -m pytest -q -n 0                                                  # en serie
python -m pytest -n 0 --cov=app --cov-fail-under=90                       # cobertura, como CI
```

- `-m "not slow"` NO es por defecto: omite los pocos tests marcados `slow` (esperas reales de los temporizadores del vigilante, análisis de todo el código) y CI debe correr todos.
- `--basetemp=/dev/shm/ck-pytest` NO es por defecto: `/dev/shm` suele ser de solo 64 MB, de sobra para el backend pero no para compartirlo con el plugin; pásalo a mano solo en el backend.
- `-n 2` usa `pytest-xdist` con dos procesos: no uses `-n auto` en el NAS (4 núcleos sin AVX2, comparte CPU con el resto del stack). Cada test escribe solo en su `tmp_path`, así que el paralelo da los mismos aprobados que el serie; si un fallo aparece solo en paralelo, repite con `-n 0` antes de darlo por bueno.
- CI no cambia de comportamiento: `pytest -n 0 --cov=app --cov-fail-under=90` en serie, con todos los tests y con cobertura (`-n 0` anula el `-n 2` de `addopts`).
- El job `backend-windows` de `ci.yml` (`windows-latest`) corre solo las pruebas del motor de sincronización (bloqueo `msvcrt`, «Este equipo» y detección con `tasklist`), sin ruff ni umbral de cobertura; lista los ficheros a mano, así que añade ahí cualquier prueba nueva del motor. Las pruebas de permisos POSIX (`chmod`) y de `fcntl`/`flock` se omiten en Windows con `skipif`.
- En `checkpoint-deck/` no uses `--basetemp=/dev/shm/...`: el plugin rechaza rutas bajo `/dev` y fallan unos 125 tests; deja el directorio temporal por defecto (`pytest -q`: 44 s a 28 s en el NAS con `-n 2`, mismos aprobados; en serie, `-n 0`).

## Formato, lint y auditorías

- Frontend: `npm run lint` (ESLint), `npm run format` y `npm run format:check` (Prettier, incluye los SCSS; los JSON de `src/locales` quedan fuera).
- Backend: `ruff check .` y `ruff format .` (o `--check`) desde `backend/`; configuración en `backend/ruff.toml`.
- Cobertura: `pytest --cov=app --cov-fail-under=90` (backend) y `npm run test:coverage` (frontend: líneas ≥ 90 %, ramas ≥ 88 % sobre `src/**`). Tamaño del bundle: `npm run build && npm run check:size` (umbrales en `frontend/scripts/check-bundle-size.mjs`).
- Las auditorías ya no están en `ci.yml`: las hacen workflows propios (gitleaks y CodeQL, además de `audit.yml`). El workflow `audit.yml` ejecuta `npm audit` y `pip-audit` (`--audit-level=high` en producción, también cada semana, más un lote mensual de desarrollo) y deja informes JSON; `security-issues.yml` los convierte, junto con los de gitleaks, en un issue con plazo por hallazgo (los de Trivy y de paquetes, agrupados por paquete y versión, máximo 10 nuevos por ejecución; 48 h crítico y alto, siguiente versión moderado, mensual bajo; un secreto, inmediato; ajustable con las variables `SLA_CRITICAL_HIGH_HOURS`, `SLA_MODERATE` y `SLA_LOW`). Gitleaks usa el binario oficial con versión y SHA-256 fijados: al actualizarlo cambia `GITLEAKS_VERSION` y `GITLEAKS_SHA256` a la vez (Dependabot no lo mantiene). Dependabot abre PRs que se revisan a mano: mensuales en npm y pip (un PR con las minor y patch agrupadas y uno aparte por cada major, salvo `react` con `react-dom` y `vite` con `@vitejs/*`, que llegan agrupados como majors porque son dependencias de pares acopladas y un PR suelto rompe `npm ci`; hay que probar cada major a mano) y semanales y agrupados en docker y github-actions (en github-actions, con 7 días de espera tras publicarse cada versión, `upload-artifact` y `download-artifact` en su propio grupo y sus majors, igual que los majors y minors de `codeql-action`, subidos a mano). Los majors de `eslint` y `@eslint/js` se ignoran porque `eslint-plugin-jsx-a11y` y `eslint-plugin-react` solo admiten eslint hasta la 9; hay que revisarlo cuando admitan la 10 (ver el comentario de `.github/dependabot.yml`). Los majors de `react` y `react-dom` también se ignoran por ahora: React 19 añade ~80 KB al bundle propio y hace fallar el presupuesto de `check:size`; al levantar la regla hay que subir ese presupuesto (ver el comentario de `.github/dependabot.yml`).
- Los commits de formato masivo están listados en `.git-blame-ignore-revs`. GitHub lo respeta solo; para que `git blame` también los ignore en local:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## Depuración de errores del frontend

Si algo falla al pintar una pantalla, o hay un error no capturado, la app lo avisa en lugar de quedarse en blanco: un aviso de zona (o de toda la app, como último recurso) con «Recargar la página», o una banda discreta abajo que no tapa nada. Ambos traen **Ver detalles** (plegado) con el error, el navegador y la versión, y **Copiar detalles** para pegarlo al reportar el fallo (útil en iPad, sin consola). Los detalles ocultan claves (`ck_…`, `ckd_…`), tokens y parámetros de URL; el mismo error repetido no vuelve a avisar durante unos segundos y el ruido sin importancia (p. ej. `ResizeObserver`, cancelaciones) se ignora.

## Publicación de versiones

Al subir un tag `vX.Y.Z` el workflow `.github/workflows/release.yml` publica la imagen en GHCR y crea la GitHub Release (la que consulta la comprobación de nuevas versiones).

1. Edita `VERSION` con la versión nueva (sin `v`), por ejemplo `1.0.0` o `1.0.0-rc.1`, y pon la misma en `frontend/package.json` y `frontend/package-lock.json` (`npm test` lo comprueba). Haz commit en `main`.
2. Crea un tag anotado con el mismo número: `git tag -a v1.0.0 -m "v1.0.0"`.
3. Sube el commit y el tag: `git push origin main v1.0.0`.

Tras publicar, el job `trivy` escanea la imagen (informativo, no bloquea ni deshace la Release) y deja el informe JSON como artefacto; si hay vulnerabilidades altas o críticas, `security-issues` abre un issue por paquete y versión (con la lista de CVE y la solución) con plazo. Si `VERSION` no coincide con el tag, el workflow falla antes de construir nada. Un tag con sufijo (`-rc.1`, `-beta.2`) se publica como pre-release.

Etiquetas de imagen (`ghcr.io/<owner>/checkpoint`, con `<owner>` en minúsculas):

| Tag | Etiquetas de imagen | Release |
|---|---|---|
| `v1.0.0` (estable) | `v1.0.0`, `1.0.0`, `latest` | normal |
| `v1.0.0-rc.1` (pre-release) | `v1.0.0-rc.1`, `1.0.0-rc.1`, `beta` | pre-release |

La imagen se construye solo para `linux/amd64`; para añadir `arm64` hay instrucciones en un comentario del workflow.

Uso en compose:

```yaml
services:
  checkpoint:
    image: ghcr.io/<owner>/checkpoint:latest   # o una versión fija, p. ej. :1.0.0, o :beta
```

Tras la primera publicación, el paquete de GHCR es privado por defecto: cámbialo a público en la página del paquete (Package settings > Danger Zone > Change visibility) si quieres bajarlo sin autenticarte.

## Escala tipográfica

Los tamaños de texto viven como tokens en `frontend/src/styles/_variables.scss` (`$fs-*`, en rem con html a 16 px). No uses tamaños sueltos.

| Token | px | Uso |
|---|---|---|
| `$fs-label` | 12 | badges, etiquetas en mayúsculas, pie |
| `$fs-hint` | 13 | ayudas, texto secundario, código, logs |
| `$fs-body` | 15 | texto normal, botones, campos |
| `$fs-subtitle` | 17 | h3, título de tarjeta |
| `$fs-title` | 20 | h2, estado vacío |
| `$fs-page` | 28 | h1 |

Excepciones explícitas: `$fs-input-mobile` (1rem = 16 px, evita el zoom de iOS), `$fs-tab-mobile` y `$fs-tab-narrow` (pestañas móviles compactas), `$fs-icon` y `$fs-hero` (iconos).

`esbuild` no está declarado en `frontend/package.json`: llega como dependencia transitiva de `vite`.

## Componentes de UI

Los elementos que se repiten viven en `frontend/src/components/ui/` (importa desde `components/ui/index.js`), cada uno con su partial SCSS al lado (`frontend/src/components/ui/_<componente>.scss`). Para cambiar el aspecto de todos los usos, edita el partial; para cambiar el marcado, el componente. No escribas a mano `className="btn"`, `badge`, `alert`, etc.

| Componente | Props | Estilos |
|---|---|---|
| `Button` | `variant` (`primary`, `danger`, `ghost`), `className`, `type` (`button` por defecto) | `_button.scss` |
| `Badge` | `status` (`ok`, `error`, `conflict`, `partial`, `aborted`, `dry-run`, `running`) | `_badge.scss` |
| `Alert` | `variant` (`error`, `ok`, `warn`, `info`), `inline`, `compact` (sin márgenes, icono + texto en fila), `as` | `_alert.scss` |
| `Pill` | `highlight`, `tone` (`info`, y `manual`, `scheduled`, `launcher` = origen en el registro) | `_pill.scss` |
| `Select` | `options` (`[{ value, label }]`), `placeholder` | `_control.scss` |
| `Checkbox` | `label` + props del input | `_control.scss` |
| `Switch` | `label` + props del input | `_switch.scss` |
| `Tabs` | `tabs` (`[{ id, label, short?, dot? }]`), `value`, `onChange`, `label`; los hijos son el panel activo. `variant="subnav"`: subnavegación subrayada (Configuración), distinta del filtro normal; `keepMounted` + `panels` (`{ id: nodo }`): todos los paneles, los inactivos con `hidden` sin desmontar (un valor null no se pinta); `short`: etiqueta corta en ≤640 px; `dot`: punto de aviso con ese texto para lectores de pantalla. Roles `tablist`/`tab`/`tabpanel`, flechas, Inicio y Fin | `_tabs.scss` |
| `CopyBox` | `value`, `label`, `what` (qué se copia: el botón dice «Copiar {what}», p. ej. «Copiar comando de Steam» o «Copiar clave API»), `describedBy`; caja de código monoespaciada que ajusta líneas + botón copiar (`copy` → `check` 2 s, `clipboard.js` con fallback) | `_copybox.scss` |
| `WatchBar` | `state` (`waiting`, `running`, `settling`, `stale`), `since` (opcional), hijos = texto; franja inferior de la tarjeta con icono decorativo + texto, color por estado (el icono se dibuja sin glifos de fuente: punto y anillo por CSS, `spinner` y `alert` de `Icon`; alineado con la primera línea del texto); la tarjeta lleva el borde con `watchCardClass(estado)` de `src/components/watch/watch.js` | `_watch.scss` |
| `WatchStatus` | `state` (igual), hijos = texto; punto decorativo + texto en línea (filas de la lista de la cabecera), `running` pulsa | `_watch.scss` |
| `WatchSummary` (componente de la app, no genérico) | `watch` (`{now, watches}` de `useWatches`), `config`; chip «● Vigilando · N ▾» en la barra superior con lista desplegable (juego, dispositivo, estado con `WatchStatus`); oculto sin vigilancia; Esc, clic fuera y salir del foco lo cierran. En móvil (<=640 px) es punto + número («99+»; el texto completo va en `aria-label`) y la lista ocupa el ancho de la barra con 8 px de margen y scroll propio; chip y filas de 44 px (`$touch-watch`, local) | `_watch.scss` |
| `Input` | props del input (texto sin autocompletar ni corrector por defecto); acepta `ref` | `_control.scss` |

Registro de ejecuciones (`AutoSyncLog`): cada entrada es un `<li class="run">` con cabecera en rejilla (fecha y hora, origen —etiqueta `Pill` de color con texto: Manual, Programado o Launcher; `startup` cuenta como Programado y `hook`/`hook_closed` como Launcher, el valor guardado no cambia—, duración —«—» si es 0 o falta— y una única `Badge` de estado) y, debajo, una línea por juego (nombre y dispositivo si consta) con su mensaje; solo se repite la `Badge` en una fila de juego si hay resultados distintos. Todo lo que no es correcto lleva icono además de texto, y el motivo sale una sola vez (el resumen de una entrada con `code` no se repite si su juego dice lo mismo). Con más de 3 juegos, los correctos van plegados tras un botón-resumen con `aria-expanded` («N juegos: 12 correctos, 1 error») y los omitidos, con error o abortados se ven siempre. Encima de la lista, un filtro por origen (`Tabs`: Todos, Manual, Programado, Launcher; estado local, sin llamar al servidor; los orígenes desconocidos solo salen en «Todos»). Tipos y resultados desconocidos se muestran tal cual. El estilo vive en `_autosync.scss` (la etiqueta de origen, en `_pill.scss`); las columnas de la cabecera usan `minmax(..., max-content)` y en <=640 px pasa a dos líneas.

La consulta de `/api/watches` (cada 5 s, solo con la pestaña visible) vive en un único hook, `useWatches` (`src/hooks/useWatches.js`), llamado desde `App`: el contador de la barra y las tarjetas de Sincronizar reciben los mismos datos, sin peticiones duplicadas.

Aviso de actualización: en pantallas anchas (>=480 px) es el botón de la barra; por debajo sale de la barra y pasa al menú del perfil como entrada «Actualizar a vX.Y.Z» (abre el mismo diálogo), y el avatar muestra un punto con texto accesible mientras haya actualización aplicable.

Menú del perfil (`ProfileMenu`), de arriba abajo, con separador fino y rótulo discreto por grupo (`role="group"` + `aria-labelledby`): identidad (foto, nombre, Cambiar/Quitar foto), entrada «Actualizar a vX.Y.Z» (solo <480 px y con actualización), **Preferencias** (Idioma y Tema con el mismo patrón de fila `.profile-row`: icono + etiqueta + valor actual a la derecha, 44 px; el idioma es el `Select` nativo como valor, `LanguageSelect row`), **Integración** (API key plegable, cerrada por defecto, `aria-expanded`/`aria-controls`; el contenido sigue montado y solo `hidden`) con, justo debajo, el enlace «Documentación de la API» (`/api/docs`, pestaña nueva con `rel="noopener"`; fila `.profile-row`) y **Cuenta** (Salir; la versión instalada solo se muestra en el pie de la app). Esc y clic fuera cierran; no es modal.

El perfil usa estos componentes: la sección «API key» es un bloque con fondo `--surface-2` (encabezado con icono `key`), la key completa en un cuadro monoespaciado que ajusta en varias líneas, `CopyBox` para la key y para los comandos de la subpestaña Lanzadores (copia con icono `copy` → `check` 2 s), `Button` y `Button variant="danger"` (Regenerar / Revocar, mismo ancho) y `Alert compact` para el aviso de HTTP.

Los tests `frontend/test/components/ui/ui-components.test.mjs` fijan las clases y atributos que producen.
