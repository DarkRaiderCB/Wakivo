"""Generate a double-clickable launcher, so the tray app needs a terminal once.

Building the launcher *locally* is what makes this free. Code signing and
notarization exist to vouch for software that arrived from elsewhere -- the
quarantine attribute is applied by whatever downloaded it. A bundle written by
the user's own machine never carries that attribute, so Gatekeeper has nothing
to object to and no certificate is involved.

Nothing here embeds a Python runtime. The launcher points at the interpreter
that is already installed and runs `python -m oncafe.gui`, which is stable
wherever the tool was installed and does not depend on PATH being set in
whatever context the OS launches it from.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .. import __version__
from . import icon as artwork

APP_NAME = "OnCafe"
BUNDLE_ID = "io.github.darkraidercb.oncafe"

ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


class LauncherError(RuntimeError):
    pass


def install(startup: bool = False) -> list[Path]:
    """Create the launcher. Returns the paths written."""
    if sys.platform == "darwin":
        return _install_macos(startup)
    if sys.platform == "win32":
        return _install_windows(startup)
    raise LauncherError(f"no launcher for {sys.platform!r}")


def uninstall() -> list[Path]:
    """Remove anything install() created. Returns the paths removed."""
    removed = []
    for path in _installed_paths():
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(path)

    if sys.platform == "darwin":
        _launchctl("bootout", _launch_agent_path())
    return removed


# -- macOS -------------------------------------------------------------------


def _app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"


def _install_macos(startup: bool) -> list[Path]:
    app = _app_path()
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    artwork.render_app().save(resources / f"{APP_NAME}.icns", format="ICNS")

    contents.joinpath("Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleExecutable": APP_NAME,
                "CFBundleIconFile": APP_NAME,
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": __version__,
                "CFBundleVersion": __version__,
                # The app lives in the menu bar, so keep it out of the Dock and
                # the ⌘-Tab switcher.
                "LSUIElement": True,
                "NSHighResolutionCapable": True,
            }
        )
    )

    stub = macos / APP_NAME
    stub.write_text(f'#!/bin/sh\nexec {_quote_sh(sys.executable)} -m oncafe.gui "$@"\n')
    stub.chmod(0o755)

    created = [app]
    if startup:
        created.append(_install_launch_agent())
    return created


def _install_launch_agent() -> Path:
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        plistlib.dumps(
            {
                "Label": BUNDLE_ID,
                "ProgramArguments": [sys.executable, "-m", "oncafe.gui"],
                "RunAtLoad": True,
            }
        )
    )
    # Best effort: if launchd will not take it now, it is picked up at the next
    # login anyway, which is when it matters.
    _launchctl("bootout", path)
    _launchctl("bootstrap", path)
    return path


def _launchctl(verb: str, path: Path) -> None:
    domain = f"gui/{os.getuid()}"
    target = str(path) if verb == "bootstrap" else f"{domain}/{BUNDLE_ID}"
    args = [domain, target] if verb == "bootstrap" else [target]
    try:
        subprocess.run(
            ["launchctl", verb, *args], capture_output=True, check=False, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _quote_sh(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


# -- Windows -----------------------------------------------------------------


def _programs_dir() -> Path:
    return (
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )


def _shortcut_path() -> Path:
    return _programs_dir() / f"{APP_NAME}.lnk"


def _startup_shortcut_path() -> Path:
    return _programs_dir() / "Startup" / f"{APP_NAME}.lnk"


def _ico_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "oncafe" / f"{APP_NAME}.ico"


def _install_windows(startup: bool) -> list[Path]:
    ico = _ico_path()
    ico.parent.mkdir(parents=True, exist_ok=True)
    artwork.render_app(256).save(ico, format="ICO", sizes=ICO_SIZES)

    target, arguments = _windows_target()
    created = []
    paths = [_shortcut_path()] + ([_startup_shortcut_path()] if startup else [])
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        _create_shortcut(path, target, arguments, ico)
        created.append(path)
    return created


def _windows_target() -> tuple[str, str]:
    """Prefer pythonw, so launching never flashes a console window."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return str(interpreter), "-m oncafe.gui"


def _create_shortcut(path: Path, target: str, arguments: str, ico: Path) -> None:
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({path});"
        "$s.TargetPath = {target};"
        "$s.Arguments = {arguments};"
        "$s.IconLocation = {ico};"
        "$s.Description = 'Keep this computer awake';"
        "$s.Save()"
    ).format(
        path=_quote_ps(str(path)),
        target=_quote_ps(target),
        arguments=_quote_ps(arguments),
        ico=_quote_ps(str(ico)),
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise LauncherError(
            f"could not create {path.name}: {result.stderr.strip() or result.returncode}"
        )


def _quote_ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# -- shared ------------------------------------------------------------------


def _installed_paths() -> list[Path]:
    if sys.platform == "darwin":
        return [_app_path(), _launch_agent_path()]
    if sys.platform == "win32":
        return [_shortcut_path(), _startup_shortcut_path(), _ico_path().parent]
    return []
