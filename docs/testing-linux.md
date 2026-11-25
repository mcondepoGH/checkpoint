# Cómo probar la instalación en Linux

Lista de comprobación manual de la instalación nativa (tarball + servicio de usuario de systemd) y de la actualización con un clic. Úsala en una máquina Linux real con systemd (no un contenedor). Instalación: [`README.md`](../README.md#instalación-sin-docker); variables: [`configuration.md`](configuration.md#instalación-nativa-en-linux-installsh).

## Qué está probado y qué no

- Probado en CI (sin systemd real): construcción del tarball, `install.sh --no-login --no-start` en un HOME temporal con venv y dependencias reales, arranque del hub, `/api/session`, la web, el plugin de Deck y `--uninstall`; y los tests del backend con `systemctl`, `systemd-run` y el lanzador simulados.
- **NO probado con systemd real** (es lo que cubre esta guía): `systemctl --user enable --now/restart`, `loginctl enable-linger`, la unidad con `WantedBy=default.target`, el lanzamiento desacoplado con `systemd-run --user` (unidad transitoria que sobrevive al reinicio del hub y su cgroup), el reinicio del hub durante la actualización con un clic, la vuelta atrás automática si el reinicio falla y la pantalla de espera en un navegador.
- Texto de la interfaz: `updates.check.textWindows` y `updates.install.windowsNote` se muestran también en Linux (mencionan Windows). Es un fallo conocido de redacción, no de funcionamiento.

## Preparación

Necesitas dos Releases del hub con tarball: una **anterior** (A) para instalar y una **posterior** (B) a la que actualizar (puede ser una pre-release en el canal de pruebas de Configuración). Cada Release debe llevar `checkpoint-<versión>-linux.tar.gz` y su `.sha256`.

Requisitos: Python 3.12+, `python3-venv`, `rsync`/`ssh` solo para dispositivos remotos. Usa un usuario normal, nunca root.

## 1. Descarga y verificación

- [ ] Descargar de la Release A el `.tar.gz` y el `.sha256` en la misma carpeta.
- [ ] `sha256sum -c checkpoint-<A>-linux.tar.gz.sha256` imprime `OK`.
- [ ] Comprobar que falla con un tarball alterado: copia el fichero, añade un byte y repite; debe decir `FAILED`.
- [ ] `tar xzf checkpoint-<A>-linux.tar.gz && cd checkpoint-<A>`.

## 2. Instalación sin login

- [ ] `./install.sh --dry-run --no-login` solo muestra el plan y no crea nada (`ls ~/.local/share/checkpoint-app` no existe).
- [ ] `./install.sh --no-login` termina sin errores e indica la URL.
- [ ] `systemctl --user status checkpoint` muestra `active (running)` y `enabled`.
- [ ] `http://127.0.0.1:8088` abre sin pedir login y la versión mostrada es A.
- [ ] Rutas: `~/.local/share/checkpoint-app/<A>/` con `current` apuntando a ella; `~/.config/systemd/user/checkpoint.service` con `Environment=CHECKPOINT_RUNTIME=native`; `~/.config/checkpoint/checkpoint.env` con permisos `-rw-------`.
- [ ] `journalctl --user -u checkpoint -n 30` sin errores.

## 3. Arranque sin sesión (linger)

- [ ] `loginctl show-user "$USER" -p Linger` dice `Linger=no` y el instalador avisó de ello.
- [ ] `loginctl enable-linger "$USER"` (o `./install.sh --enable-linger` en una instalación nueva) y `Linger=yes`.
- [ ] Reiniciar el equipo y comprobar, antes de iniciar sesión (por SSH o con `--host` abierto), que el hub responde: arrancó solo.
- [ ] Sin linger el servicio se detiene al cerrar la última sesión; es lo esperado.

## 4. Instalación con usuario y contraseña

- [ ] `./install.sh --uninstall`, comprobar que los datos siguen en `~/.local/share/checkpoint` y borrar solo el entorno sin login (`rm ~/.config/checkpoint/checkpoint.env`; si existe, `install.sh` lo conserva e ignora `--user`). Reinstalar con credenciales: `printf '%s\n' 'una-clave-larga' > /tmp/pw && chmod 600 /tmp/pw && ./install.sh --user prueba --password-file /tmp/pw && rm /tmp/pw`.
- [ ] El hub pide login y entra con `prueba` y la clave. Un `checkpoint.env` existente no se pisa (aviso al reinstalar) y la contraseña no aparece en `ps` ni en el historial.
- [ ] Con terminal y sin opciones: `./install.sh` pregunta usuario y contraseña; Intro vacío genera una y la muestra una sola vez.

## 5. Actualización con un clic (A a B)

- [ ] Con A instalada y B publicada, el hub muestra el aviso de versión nueva y, en el detalle, el botón «Actualizar ahora».
- [ ] Pulsarlo y confirmar. Esperado en pantalla: fases de comprobación, descarga, instalación y «reiniciando»; la página espera (hasta 300 s en Linux) y se recarga sola con la versión B.
- [ ] `~/.local/share/checkpoint-app/` contiene `<A>` y `<B>`, y `current` apunta a `<B>`.
- [ ] `journalctl --user -u checkpoint` muestra la parada y el arranque de la unidad; si hay unidad transitoria, `systemctl --user list-units 'run-*'` la muestra durante la actualización.
- [ ] `~/.local/share/checkpoint/update/upgrade-<B>.log` termina sin errores (es el registro de `install.sh --upgrade`).
- [ ] Datos y credenciales intactos (mismos dispositivos y juegos, mismo login).
- [ ] Sin Release más nueva, el botón no aparece.

## 6. Fallos forzados y vuelta atrás

Cada caso debe terminar con el hub A (o la versión previa) funcionando y un error legible, nunca con el hub parado.

- [ ] **Red cortada durante la descarga**: lanzar la actualización y desconectar la red (o bloquear `github.com` con el cortafuegos) en cuanto empiece. Esperado: error en el diálogo, versión sin cambios, `current` sigue en A.
- [ ] **Carpeta sin permisos**: `chmod a-w ~/.local/share/checkpoint/update` (o la carpeta de datos) y actualizar. Esperado: error al preparar la descarga y nada instalado. Restaura con `chmod u+w`.
- [ ] **Reinicio fallido**: instalar B y romperla antes (p. ej. en una copia de prueba, un `VERSION` o dependencia inválida) o matar el reinicio. Esperado: `install.sh` vuelve a la versión anterior (`current` otra vez en A) y lo deja en `upgrade-<B>.log`; la interfaz acaba en error de tiempo agotado si no vuelve.
- [ ] **Rollback manual**: con `current` en B, `cd ~/.local/share/checkpoint-app && ln -sfn <A> current.tmp && mv -T current.tmp current && systemctl --user restart checkpoint`; el hub vuelve a mostrar A.
- [ ] Tarball con hash incorrecto (solo en una Release de prueba): la actualización se rechaza con el error de hash y no instala nada.

## 7. Desinstalación

- [ ] `./install.sh --uninstall`: la unidad se para y desaparece, `checkpoint-app/` desaparece, y **se conservan** `~/.local/share/checkpoint` (datos) y `~/.config/checkpoint/checkpoint.env`. `systemctl --user status checkpoint` dice que no existe.
- [ ] Reinstalar tras desinstalar recupera los datos y las credenciales.
- [ ] `./install.sh --uninstall --purge` sin terminal (p. ej. `</dev/null`) se niega y no borra nada.
- [ ] Con terminal pide escribir `BORRAR`; otra cosa cancela sin borrar. Con `BORRAR` se borran también `~/.local/share/checkpoint` y `~/.config/checkpoint`.

## Qué anotar si algo falla

Salida de `./install.sh` o del botón, `journalctl --user -u checkpoint -n 100`, `~/.local/share/checkpoint/update/upgrade-<versión>.log`, `ls -l ~/.local/share/checkpoint-app` y la versión de systemd (`systemctl --version`). No pegues contraseñas.
