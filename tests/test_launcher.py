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


@macos_only
def test_the_stub_runs_the_interpreter_not_a_console_script(home) -> None:
    from oncafe.gui.launcher import install

    (app,) = install()
    stub = (app / "Contents" / "MacOS" / "OnCafe").read_text()

    # PATH is not what you would expect when Finder launches something, so the
    # launcher must not depend on a console script being findable.
    assert sys.executable in stub
    assert "-m oncafe.gui" in stub


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
    assert plist["ProgramArguments"][:1] == [sys.executable]


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
