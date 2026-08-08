from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

from oncafe import gui

pytest.importorskip("PIL", reason="the GUI extra is not installed")

pytestmark = pytest.mark.skipif(
    sys.platform not in gui.SUPPORTED_PLATFORMS,
    reason="launchers are generated for macOS and Windows only",
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway home, so nothing lands in the real one."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    # Never talk to the real launchd: bootstrapping a plist from tmp_path
    # would register a login item on the machine running the tests.
    monkeypatch.setattr("oncafe.gui.launcher._launchctl", lambda *a, **k: None)
    return tmp_path


macos_only = pytest.mark.skipif(sys.platform != "darwin", reason="macOS bundle")


@macos_only
def test_install_builds_a_launchable_bundle(home) -> None:
    from oncafe.gui.launcher import install

    (app,) = install()
    contents = app / "Contents"

    assert app == home / "Applications" / "OnCafe.app"
    assert (contents / "Info.plist").is_file()
    assert (contents / "Resources" / "OnCafe.icns").is_file()

    stub = contents / "MacOS" / "OnCafe"
    assert stub.is_file()
    # Executable, or double-clicking it does nothing at all.
    assert stub.stat().st_mode & 0o111


@macos_only
def test_the_bundle_stays_out_of_the_dock(home) -> None:
    from oncafe.gui.launcher import BUNDLE_ID, install

    (app,) = install()
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())

    # A menu bar app with a Dock icon and a ⌘-Tab entry is wrong.
    assert plist["LSUIElement"] is True
    assert plist["CFBundleIdentifier"] == BUNDLE_ID
    assert plist["CFBundleExecutable"] == "OnCafe"
    assert plist["CFBundleIconFile"] == "OnCafe"


def boot_module(app: Path) -> Path:
    minor = sys.version_info.minor
    return app / "Contents" / "lib" / f"python3.{minor}" / "site-packages" / "sitecustomize.py"


@macos_only
def test_the_bundle_executable_is_a_real_copy_of_the_interpreter(home) -> None:
    # Three constraints, each found by measurement:
    #   - a shell stub that execs Python replaces the process LaunchServices
    #     registered, and the app then silently loses the right to own a status
    #     item: created, never granted a slot, zero height, never appears
    #   - a symlink is rejected by codesign, which wants a regular file
    #   - so it has to be a copy
    from oncafe.gui.launcher import install

    (app,) = install()
    executable = app / "Contents" / "MacOS" / "OnCafe"

    assert executable.is_file()
    assert not executable.is_symlink()
    assert executable.stat().st_mode & 0o111


@macos_only
def test_the_bundle_is_a_virtualenv_so_the_boot_module_is_found(home) -> None:
    # LaunchServices runs the executable with no arguments, so there is no
    # `-m oncafe.gui` to hand it. Reaching it through LSEnvironment was tried
    # and does not work on current macOS at all, so the bundle is instead built
    # as a virtualenv and sitecustomize does the work.
    from oncafe.gui.launcher import install

    (app,) = install()

    config = app / "Contents" / "MacOS" / "pyvenv.cfg"
    assert config.is_file(), "must sit beside the executable; Contents/ is ignored"
    assert "home = " in config.read_text()

    source = boot_module(app).read_text()
    assert "from oncafe.gui import main" in source

    # No environment reliance left over.
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert "LSEnvironment" not in plist


@macos_only
def test_the_interpreter_can_find_its_library_inside_the_bundle(home) -> None:
    # The copied binary loads its library through @executable_path/../lib.
    from oncafe.gui.launcher import install

    (app,) = install()
    dylibs = list((app / "Contents" / "lib").glob("*.dylib"))
    assert dylibs, "the copied interpreter would not start without these"


@macos_only
def test_the_boot_module_records_where_to_import_from(home) -> None:
    # The bundled interpreter is a copy of the *base* install, so it comes up
    # without the virtualenv's site-packages and has to be told where they are.
    from oncafe.gui.launcher import install

    (app,) = install()
    source = boot_module(app).read_text()

    import oncafe

    assert str(Path(oncafe.__file__).resolve().parent.parent) in source


@macos_only
def test_startup_is_opt_in(home) -> None:
    from oncafe.gui.launcher import _launch_agent_path, install

    install()
    assert not _launch_agent_path().exists()

    created = install(startup=True)
    agent = _launch_agent_path()
    assert agent in created

    plist = plistlib.loads(agent.read_bytes())
    assert plist["RunAtLoad"] is True
    # Launches the bundle, not the interpreter: started any other way the
    # status item never receives a slot in the menu bar.
    assert plist["ProgramArguments"][:2] == ["/usr/bin/open", "-a"]
    assert plist["ProgramArguments"][2].endswith("OnCafe.app")


@macos_only
def test_uninstall_removes_everything_it_made(home) -> None:
    from oncafe.gui.launcher import _launch_agent_path, install, uninstall

    install(startup=True)
    removed = uninstall()

    assert removed
    assert not (home / "Applications" / "OnCafe.app").exists()
    assert not _launch_agent_path().exists()
    # And it is idempotent, so a second run is not an error.
    assert uninstall() == []


def test_uninstall_is_quiet_when_nothing_is_installed(home) -> None:
    from oncafe.gui.launcher import uninstall

    assert uninstall() == []


def test_startup_alone_is_rejected(capsys) -> None:
    # It only means something alongside --install; silently ignoring it would
    # leave someone believing they had set up autostart.
    assert gui.main(["--startup"]) == 2
    assert "--install" in capsys.readouterr().err


def test_the_app_icon_has_its_own_ground() -> None:
    from oncafe.gui.icon import APP_GROUND, render_app

    image = render_app(128)
    # Unlike the menu bar icon, this one sits on the user's wallpaper, so it
    # must not be transparent behind the cup.
    assert image.getpixel((64, 120))[3] == 255
    assert image.getpixel((6, 64))[:3] in (APP_GROUND[:3], (0, 0, 0))


def write_pe(path: Path, subsystem: int) -> None:
    """A PE header just complete enough for the subsystem check."""
    pe_offset = 0x80
    data = bytearray(pe_offset + 24 + 70)
    data[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    offset = pe_offset + 24 + 68
    data[offset : offset + 2] = subsystem.to_bytes(2, "little")
    path.write_bytes(bytes(data))


def test_a_console_shim_is_not_treated_as_windowless(tmp_path) -> None:
    from oncafe.gui.launcher import _is_windowless

    gui, console, junk = (tmp_path / n for n in ("g.exe", "c.exe", "j.exe"))
    write_pe(gui, 2)
    write_pe(console, 3)
    junk.write_bytes(b"not a PE file at all")

    assert _is_windowless(gui)
    assert not _is_windowless(console)
    assert not _is_windowless(junk)
    assert not _is_windowless(tmp_path / "missing.exe")


def test_windows_target_avoids_the_uv_trampolines(tmp_path, monkeypatch) -> None:
    # Under uv both the virtualenv's pythonw.exe and the oncafe-gui shim are
    # trampolines: GUI-subsystem themselves, so they look correct, but they
    # spawn the base console python.exe and Windows gives that a terminal that
    # sits behind the tray icon for as long as the app runs.
    from oncafe.gui import launcher

    base, venv = tmp_path / "base", tmp_path / "venv"
    base.mkdir()
    venv.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(sys, "executable", str(venv / "python.exe"))
    monkeypatch.setattr(sys, "base_prefix", str(base))
    monkeypatch.setattr(sys, "base_exec_prefix", str(base))

    # A trampoline beside the executable is passed over ...
    write_pe(venv / "pythonw.exe", 2)
    write_pe(venv / "oncafe-gui.exe", 2)
    write_pe(base / "pythonw.exe", 2)

    target, arguments = launcher._windows_target()
    assert target == str(base / "pythonw.exe")
    assert "oncafe-gui.exe" not in target
    # ... and the packages travel as a script argument, because a shortcut
    # cannot set PYTHONPATH.
    assert arguments.strip('"').endswith("launch.pyw")


def test_the_windows_launcher_script_restores_the_import_paths(tmp_path, monkeypatch) -> None:
    # The shortcut runs the base interpreter, which has none of the
    # virtualenv's packages on its path.
    from oncafe.gui import launcher

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path))
    monkeypatch.setattr(sys, "base_exec_prefix", str(tmp_path))
    launcher._windows_target()

    import oncafe

    source = launcher._windows_launcher_path().read_text()
    assert str(Path(oncafe.__file__).resolve().parent.parent) in source
    assert "from oncafe.gui import main" in source
