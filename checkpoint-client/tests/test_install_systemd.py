"""Arranque automático con `systemd --user`: la unidad y los comandos de systemctl, sin ejecutar systemctl real.

El ejecutor de comandos se inyecta: aquí es un registro que contesta lo que cada test pida. HOME es falso (fixture
`home`), así que la unidad cae en un directorio temporal."""

import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import KEY

from checkpoint_client import cli, locks, settings, texts, watcher
from checkpoint_client.install import systemd

EXEC = ["/opt/venv/bin/checkpoint-client", "watch"]


class Systemctl:
    """Ejecutor falso: guarda cada comando y contesta con `answers[(argumentos)]` o con éxito."""

    def __init__(self, **answers):
        self.calls = []
        self.answers = answers

    def __call__(self, argv):
        self.calls.append(list(argv))
        key = " ".join(argv[2:])
        code, err = self.answers.get(key, (0, ""))
        return SimpleNamespace(returncode=code, stdout="", stderr=err)

    @property
    def verbs(self):
        return [" ".join(c[2:]) for c in self.calls if c[:2] == ["systemctl", "--user"] and c[2] != "show-environment"]


def unit_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / "checkpoint-client.service"


# ---------------------------------------------------------------- contenido de la unidad
def test_unit_text_runs_the_absolute_command_without_shell_and_restarts_on_failure():
    unit = systemd.unit_text(["/opt/venv/bin/checkpoint-client", "watch"])
    assert 'ExecStart="/opt/venv/bin/checkpoint-client" "watch"' in unit
    assert "Restart=on-failure" in unit and "RestartSec=30" in unit
    assert "WantedBy=default.target" in unit
    assert "/bin/sh" not in unit and "bash" not in unit and "Environment" not in unit


def test_unit_text_quotes_paths_with_spaces_and_specifiers():
    unit = systemd.unit_text(["/home/a b/100%/py$thon", "-m", "checkpoint_client", "watch"])
    assert 'ExecStart="/home/a b/100%%/py$$thon" "-m" "checkpoint_client" "watch"' in unit


def test_exec_command_prefers_the_script_next_to_the_interpreter(tmp_path):
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "checkpoint-client"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    assert systemd.exec_command(python=str(bin_dir / "python")) == [str(script), "watch"]


def test_exec_command_falls_back_to_the_module_with_the_absolute_interpreter(tmp_path):
    py = tmp_path / "bin" / "python"
    assert systemd.exec_command(python=str(py)) == [str(py), "-m", "checkpoint_client", "watch"]


def test_exec_command_is_absolute_for_the_running_interpreter():
    assert all(os.path.isabs(p) for p in systemd.exec_command()[:1])
    assert systemd.exec_command()[-1] == "watch"


def test_unit_has_no_secrets(home, monkeypatch):
    settings.save_settings(settings.config_dir(), {"hub_url": "http://h:1", "key": KEY, "device": "d"})
    monkeypatch.setenv("CHECKPOINT_TEST_SECRET", KEY)
    run = Systemctl()
    systemd.install(run, exec_command=EXEC)
    text = unit_path(home).read_text(encoding="utf-8")
    assert KEY not in text and "ckd_" not in text and "key" not in text.lower() and "http" not in text


# ---------------------------------------------------------------- install
def test_install_writes_the_unit_reloads_and_enables_now(home):
    run = Systemctl()
    systemd.install(run, exec_command=EXEC)
    assert unit_path(home).read_text(encoding="utf-8") == systemd.unit_text(EXEC)
    assert run.verbs == ["daemon-reload", "enable --now checkpoint-client.service"]
    assert all(c[0] == "systemctl" for c in run.calls)


def test_install_twice_is_idempotent_and_restarts_only_when_the_unit_changed(home):
    run = Systemctl()
    systemd.install(run, exec_command=EXEC)
    systemd.install(run, exec_command=EXEC)
    assert unit_path(home).read_text(encoding="utf-8") == systemd.unit_text(EXEC)
    assert "restart checkpoint-client.service" not in run.verbs
    systemd.install(run, exec_command=["/otro/checkpoint-client", "watch"])
    assert run.verbs[-1] == "restart checkpoint-client.service"
    assert "/otro/checkpoint-client" in unit_path(home).read_text(encoding="utf-8")


def test_install_respects_xdg_config_home(home, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    systemd.install(Systemctl(), exec_command=EXEC)
    assert (tmp_path / "xdg" / "systemd" / "user" / "checkpoint-client.service").is_file()
    assert not unit_path(home).exists()


def test_install_without_user_bus_writes_nothing(home):
    run = Systemctl(**{"show-environment": (1, "Failed to connect to bus")})
    with pytest.raises(systemd.Unavailable):
        systemd.install(run, exec_command=EXEC)
    assert not unit_path(home).exists() and run.verbs == []


def test_install_without_systemctl_binary_is_unavailable(home):
    def missing(argv):
        raise FileNotFoundError("systemctl")

    with pytest.raises(systemd.Unavailable):
        systemd.install(missing, exec_command=EXEC)
    assert not unit_path(home).exists()


def test_install_failure_rolls_back_a_new_unit(home):
    run = Systemctl(**{"enable --now checkpoint-client.service": (1, "Failed to enable unit: boom\nmás")})
    with pytest.raises(systemd.InstallError) as e:
        systemd.install(run, exec_command=EXEC)
    assert e.value.reason == "Failed to enable unit: boom"
    assert not unit_path(home).exists()
    assert run.verbs[-1] == "daemon-reload"  # tras deshacer se vuelve a recargar


def test_install_failure_restores_the_previous_unit(home):
    systemd.install(Systemctl(), exec_command=EXEC)
    before = unit_path(home).read_text(encoding="utf-8")
    run = Systemctl(**{"daemon-reload": (1, "no")})
    with pytest.raises(systemd.InstallError):
        systemd.install(run, exec_command=["/otro/checkpoint-client", "watch"])
    assert unit_path(home).read_text(encoding="utf-8") == before


def test_install_unwritable_directory_is_an_install_error(home):
    (home / ".config").write_text("fichero, no carpeta", encoding="utf-8")
    run = Systemctl()
    with pytest.raises(systemd.InstallError) as e:
        systemd.install(run, exec_command=EXEC)
    assert e.value.reason and run.verbs == []


# ---------------------------------------------------------------- uninstall
def test_uninstall_disables_now_removes_the_unit_and_keeps_data(home):
    systemd.install(Systemctl(), exec_command=EXEC)
    settings.save_settings(settings.config_dir(), {"key": KEY})
    run = Systemctl()
    systemd.uninstall(run)
    assert run.verbs == ["disable --now checkpoint-client.service", "daemon-reload"]
    assert not unit_path(home).exists()
    assert settings.load_settings(settings.config_dir())["key"] == KEY


def test_uninstall_without_unit_is_idempotent(home):
    run = Systemctl()
    systemd.uninstall(run)
    systemd.uninstall(run)
    assert run.verbs == []


def test_uninstall_without_user_bus_is_unavailable_and_keeps_the_unit(home):
    systemd.install(Systemctl(), exec_command=EXEC)
    with pytest.raises(systemd.Unavailable):
        systemd.uninstall(Systemctl(**{"show-environment": (1, "bus")}))
    assert unit_path(home).exists()


def test_uninstall_failure_keeps_the_unit(home):
    systemd.install(Systemctl(), exec_command=EXEC)
    run = Systemctl(**{"disable --now checkpoint-client.service": (1, "no se pudo")})
    with pytest.raises(systemd.InstallError) as e:
        systemd.uninstall(run)
    assert e.value.reason == "no se pudo" and unit_path(home).exists()


# ---------------------------------------------------------------- ejecutor real (sin shell)
def test_default_runner_uses_no_shell_and_utf8(monkeypatch):
    seen = {}

    def fake(argv, **kw):
        seen.update(kw, argv=argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    systemd.run_command(["systemctl", "--user", "daemon-reload"])
    assert seen["argv"] == ["systemctl", "--user", "daemon-reload"]
    assert not seen.get("shell") and seen["encoding"] == "utf-8" and seen["capture_output"] and seen["timeout"]


# ---------------------------------------------------------------- CLI
@pytest.fixture
def systemctl(monkeypatch):
    run = Systemctl()
    monkeypatch.setattr(systemd, "run_command", run)
    monkeypatch.setattr(systemd, "exec_command", lambda python=None: EXEC)
    return run


@pytest.fixture
def linked_home(home):
    settings.save_settings(settings.config_dir(), {"hub_url": "http://h:1", "key": KEY, "device": "pc"})
    return home


def cli_run(capsys, *argv):
    code = cli.main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_cli_install_and_uninstall_messages(linked_home, systemctl, capsys):
    code, out, err = cli_run(capsys, "install")
    assert code == 0 and err == "" and out.strip() == texts.INSTALL_DONE
    assert unit_path(linked_home).is_file()
    code, out, err = cli_run(capsys, "uninstall")
    assert code == 0 and err == "" and out.strip() == texts.UNINSTALL_DONE_LINUX
    assert not unit_path(linked_home).exists()


def test_cli_install_unavailable(linked_home, monkeypatch, capsys):
    monkeypatch.setattr(systemd, "run_command", Systemctl(**{"show-environment": (1, "bus")}))
    code, out, err = cli_run(capsys, "install")
    assert code == 1 and out == "" and err.strip() == texts.INSTALL_NO_SYSTEMD
    code, out, err = cli_run(capsys, "uninstall")
    assert code == 1 and err.strip() == texts.INSTALL_NO_SYSTEMD


def test_cli_install_failure_shows_the_reason_without_secrets(linked_home, monkeypatch, capsys):
    run = Systemctl(**{"daemon-reload": (1, f"fallo con {KEY}")})
    monkeypatch.setattr(systemd, "run_command", run)
    monkeypatch.setattr(systemd, "exec_command", lambda python=None: EXEC)
    code, out, err = cli_run(capsys, "install")
    assert code == 1 and KEY not in err
    assert err.startswith("No se pudo crear la unidad systemd --user: fallo con ")
    assert err.strip().endswith("No se ha cambiado nada.")


def test_cli_uninstall_failure_text(linked_home, systemctl, capsys, monkeypatch):
    cli_run(capsys, "install")
    monkeypatch.setattr(systemd, "run_command", Systemctl(**{"disable --now checkpoint-client.service": (1, "x")}))
    code, _, err = cli_run(capsys, "uninstall")
    assert code == 1 and err.strip() == texts.UNINSTALL_FAILED.format(reason="x")


def test_cli_install_refuses_when_not_linked(home, systemctl, capsys):
    code, out, err = cli_run(capsys, "install")
    assert code == 1 and out == "" and err.strip() == texts.ERR_NOT_LINKED
    assert systemctl.calls == [] and not unit_path(home).exists()


def test_cli_uninstall_does_not_need_a_link(home, systemctl, capsys):
    code, out, err = cli_run(capsys, "uninstall")
    assert code == 0 and err == "" and out.strip() == texts.UNINSTALL_DONE_LINUX


def test_cli_install_only_on_linux(home, systemctl, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "win32")
    for cmd in ("install", "uninstall"):
        code, out, err = cli_run(capsys, cmd)
        assert code == 1 and out == "" and err.strip() == texts.INSTALL_ONLY_LINUX
    assert systemctl.calls == [] and not unit_path(home).exists()


def test_cli_help_texts():
    sub = {a.dest: a for a in cli.build_parser()._subparsers._group_actions[0]._choices_actions}  # noqa: SLF001
    assert sub["install"].help == texts.HELP_INSTALL
    assert sub["uninstall"].help == texts.HELP_UNINSTALL


# ---------------------------------------------------------------- SIGTERM (systemd para con SIGTERM)
class _NoProcesses:
    def process_iter(self, attrs):
        return iter(())


def test_watch_stops_cleanly_on_sigterm(home, fakehub, monkeypatch, capsys):
    settings.save_settings(settings.config_dir(), {"hub_url": fakehub.url, "key": KEY, "device": "pc-ab12"})
    monkeypatch.setattr(cli, "_DETECTOR", watcher.ProcessDetector(_NoProcesses()))
    monkeypatch.setattr(watcher.time, "sleep", lambda _s: os.kill(os.getpid(), signal.SIGTERM))
    before = signal.getsignal(signal.SIGTERM)
    code = cli.main(["watch"])
    out = capsys.readouterr().out.splitlines()
    assert code == 0 and out[-1] == texts.WATCH_STOPPED
    assert not locks.is_locked(os.path.join(settings.config_dir(), "locks"), locks.WATCH)  # soltó el lock
    assert signal.getsignal(signal.SIGTERM) == before  # y dejó el manejador como estaba
