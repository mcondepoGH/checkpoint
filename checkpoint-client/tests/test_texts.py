"""Los textos aprobados de la tarjeta, tal cual (y nada de literales sueltos en `cli.py`)."""

import string

from checkpoint_client import texts


def test_approved_texts_are_verbatim():
    assert (
        texts.HELP_ROOT
        == "checkpoint-client: sincroniza los guardados de tus juegos con el hub de Checkpoint, sin SSH."
    )
    assert texts.LINK_WAITING == "Esperando aceptación en el hub… (Ctrl+C para cancelar)"
    assert texts.LINK_CODE.format(code="123 456") == (
        "Código de vinculación: 123 456. Acéptalo en el hub (Configuración > Biblioteca > Solicitudes de vinculación). "
        "Caduca en 10 minutos."
    )
    assert texts.SYNC_DOWNLOADED.format(game="Hades", n=3, path="/x/Hades") == (
        "Hades: bajado (3 ficheros). Tu carpeta anterior quedó en «/x/Hades.checkpoint-backup»."
    )
    assert texts.SYNC_SUMMARY.format(ok=2, c=1, e=0) == "2 al día o sincronizados, 1 en conflicto, 0 con error."
    assert texts.ERR_NOT_LINKED == "Este equipo no está vinculado. Ejecuta «checkpoint-client link <hub>»."
    assert texts.ERR_RATE_LIMITED.format(s=5) == "El hub pide esperar antes de otra petición. Espera 5 s."
    assert (
        texts.SYNC_RUNNING.format(game="Hades")
        == "Hades está abierto: no se sincroniza. Ciérralo y vuelve a intentarlo."
    )


def test_watcher_texts_approved_by_the_user():
    assert texts.WATCH_RUNNING == "Ya hay un vigilante en marcha."
    assert texts.STATUS_KEYS["watch"] == "vigilante"
    assert (texts.STATUS_WATCH_ACTIVE, texts.STATUS_WATCH_STOPPED) == ("activo", "parado")
    assert texts.SYNC_RUNNING_WATCHED.format(game="Hades") == (
        "Hades está abierto: no se sincroniza. El vigilante lo sincronizará al cerrarlo."
    )


def test_uninstall_texts_approved_by_the_user():
    assert texts.UNINSTALL_DONE_LINUX == "Desinstalado el arranque automático y detenido el vigilante de systemd."
    assert texts.UNINSTALL_FAILED.format(reason="x") == "No se pudo quitar la unidad systemd --user: x."


def test_engine_error_texts_do_not_mention_deck():
    assert all("Deck" not in t for t in texts.SYNC_ERRORS.values())
    assert texts.SYNC_ERRORS["no_space"].endswith("en este equipo para bajar los ficheros.")


def test_every_format_field_is_filled_by_known_names():
    allowed = {"code", "device", "where", "game", "n", "path", "i", "name", "message", "ok", "c", "e", "url", "min",
              "s", "log", "key", "value", "reason"}  # fmt: skip
    for name in dir(texts):
        value = getattr(texts, name)
        if isinstance(value, str):
            fields = {f for _, f, _, _ in string.Formatter().parse(value) if f}
            assert fields <= allowed, (name, fields - allowed)
