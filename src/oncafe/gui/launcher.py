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


def install() -> list[Path]:
    """Create the launcher. Returns the paths written."""
    if sys.platform == "darwin":
        return _install_macos()
    if sys.platform == "win32":
        return _install_windows()
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
    return removed


# -- macOS -------------------------------------------------------------------


def _app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def _import_roots() -> list[str]:
    """Directories that must be on sys.path for the app to import.

    Recorded at install time because the bundled interpreter is reached
    through a symlink, which Python resolves back to the base install -- so it
    comes up without the virtualenv's site-packages.
    """
    import PIL
    import pystray

    import oncafe

    roots = []
    for module in (oncafe, pystray, PIL):
        root = str(Path(module.__file__).resolve().parent.parent)
        if root not in roots:
            roots.append(root)
    return roots


_BOOT_SOURCE = '''\
"""Started by the OnCafe launcher.

LaunchServices runs a bundle's executable with no arguments, so there is no
`-m oncafe.gui` to hand it. The bundle is therefore built as a virtualenv --
pyvenv.cfg beside the executable -- which puts this file on the path of that
interpreter and nothing else. Python imports sitecustomize during startup, and
that is the hook, reached before control would otherwise fall through to an
interactive prompt and exit.

Reaching it through the environment instead was tried first. LSEnvironment in
Info.plist is simply not applied on current macOS, even for a bundle
LaunchServices has never seen before.
"""

import os
import sys

for _root in {roots!r}:
    if _root not in sys.path:
        sys.path.insert(0, _root)

from oncafe.gui import main

_code = main()
# _exit rather than sys.exit: site.py runs this during startup, where a
# SystemExit is reported as a failed sitecustomize import.
os._exit(_code if isinstance(_code, int) else 0)
'''


def _install_macos() -> list[Path]:
    """Build the bundle.

    Three constraints, each found the hard way, and together they leave very
    little freedom:

    1. The executable must be the interpreter, not a script that execs it.
       LaunchServices registers the process it starts here; exec'ing away
       replaces that image and the app silently loses the right to own a status
       item -- the item is created but never granted a slot, so it comes up
       zero pixels high and never appears.
    2. It must be a *regular file*, not a symlink, or codesign refuses it.
    3. And it must be signed at all, or LaunchServices refuses to launch:
       "code has no resources but signature indicates they must be present."
       Ad-hoc signing satisfies this and needs no certificate.
    """
    app = _app_path()
    if app.exists():
        shutil.rmtree(app)

    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    site_packages = (
        contents / "lib" / f"python3.{sys.version_info.minor}" / "site-packages"
    )
    for directory in (macos, resources, site_packages):
        directory.mkdir(parents=True, exist_ok=True)

    interpreter = Path(sys.executable).resolve()
    executable = macos / APP_NAME
    shutil.copy2(interpreter, executable)
    executable.chmod(0o755)

    # The interpreter loads its library through @executable_path/../lib, which
    # inside the bundle means Contents/lib.
    library = Path(sys.base_prefix) / "lib"
    if library.is_dir():
        for entry in library.iterdir():
            if entry.is_file() and entry.suffix == ".dylib":
                link = contents / "lib" / entry.name
                if not link.exists():
                    link.symlink_to(entry)

    # pyvenv.cfg makes the bundle a virtualenv rooted at Contents, which is
    # what puts our boot module on that interpreter's path -- and only that
    # interpreter's. It has to sit beside the executable: one level up, in
    # Contents, Python does not honour it.
    (macos / "pyvenv.cfg").write_text(
        f"home = {interpreter.parent}\n"
        "include-system-site-packages = false\n"
        f"version = {sys.version.split()[0]}\n"
    )
    (site_packages / "sitecustomize.py").write_text(
        _BOOT_SOURCE.format(roots=_import_roots())
    )

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

    _check_bundled_interpreter(executable)
    _sign(app)
    return [app]


def _check_bundled_interpreter(executable: Path) -> None:
    """Fail loudly here rather than with a bundle that silently does nothing.

    Copying the interpreter assumes it finds its library through a relative
    rpath, which holds for the standalone builds uv and pyenv install. A
    framework build may not survive being copied out of its framework.
    """
    # -S skips site, and so skips the boot module we just installed -- without
    # it this check launches the app and blocks until the timeout.
    result = subprocess.run(
        [str(executable), "-S", "-c", "import sys"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise LauncherError(
            "the bundled copy of Python will not run, so this interpreter's "
            "layout is not supported for --install; the oncafe and oncafe-gui "
            f"commands still work. Details: {result.stderr.strip()}"
        )


def _sign(app: Path) -> None:
    """Ad-hoc sign, best effort.

    codesign objects to pyvenv.cfg living in Contents/MacOS, where it treats
    every file as code -- and pyvenv.cfg has to live there, because Python does
    not honour it anywhere else. The bundle launches regardless, so this is not
    worth failing an install over. It is still attempted, because a signature
    is what stops Gatekeeper complaining when one *can* be produced.
    """
    try:
        subprocess.run(
            ["codesign", "--force", "--sign", "-", str(app)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        pass


# -- Windows -----------------------------------------------------------------


def _programs_dir() -> Path:
    return (
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )


def _shortcut_path() -> Path:
    return _programs_dir() / f"{APP_NAME}.lnk"


def _ico_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "oncafe" / f"{APP_NAME}.ico"


def _install_windows() -> list[Path]:
    ico = _ico_path()
    ico.parent.mkdir(parents=True, exist_ok=True)
    artwork.render_app(256).save(ico, format="ICO", sizes=ICO_SIZES)

    target, arguments = _windows_target()
    path = _shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _create_shortcut(path, target, arguments, ico)
    return [path]


_WINDOWS_LAUNCH_SOURCE = '''\
"""Started by the OnCafe shortcut.

The shortcut runs the *base* interpreter's pythonw, not the virtualenv's, so
this puts the virtualenv's packages back on the path. See _windows_target for
why the virtualenv's own pythonw cannot be used.
"""

import sys

for _root in {roots!r}:
    if _root not in sys.path:
        sys.path.insert(0, _root)

from oncafe.gui import main

sys.exit(main())
'''


def _windows_launcher_path() -> Path:
    return _ico_path().parent / "launch.pyw"


def _windows_target() -> tuple[str, str]:
    """Pick an interpreter that will not put a console behind the tray icon.

    Not the virtualenv's pythonw.exe, and not the oncafe-gui shim. Under uv
    both are trampolines: GUI-subsystem themselves, so they look right, but
    they spawn the base *python.exe*, which is console-subsystem, and Windows
    gives that a terminal. It stays for as long as the app runs.

    Hence the real pythonw from the base installation, with the virtualenv's
    packages handed to it through a launch script -- a shortcut cannot set
    environment variables, so the paths cannot be passed as PYTHONPATH.
    """
    launcher = _windows_launcher_path()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(_WINDOWS_LAUNCH_SOURCE.format(roots=_import_roots()))
    arguments = f'"{launcher}"'

    for candidate in (
        Path(sys.base_prefix) / "pythonw.exe",
        Path(sys.base_exec_prefix) / "pythonw.exe",
        # Last resort. In a uv environment this is the trampoline described
        # above, so it is better than nothing and worse than the two above it.
        Path(sys.executable).with_name("pythonw.exe"),
    ):
        if candidate.exists() and _is_windowless(candidate):
            return str(candidate), arguments

    return str(sys.executable), arguments


_IMAGE_SUBSYSTEM_WINDOWS_GUI = 2


def _is_windowless(executable: Path) -> bool:
    """Whether a PE binary is a GUI subsystem image rather than a console one.

    The subsystem field is what decides if Windows attaches a console, and it
    sits at a fixed offset that is the same for PE32 and PE32+: the optional
    header begins 24 bytes past the PE signature, and Subsystem is 68 bytes
    into it.
    """
    try:
        with executable.open("rb") as handle:
            handle.seek(0x3C)
            pe_offset = int.from_bytes(handle.read(4), "little")
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\0\0":
                return False
            handle.seek(pe_offset + 24 + 68)
            subsystem = int.from_bytes(handle.read(2), "little")
    except OSError:
        return False
    return subsystem == _IMAGE_SUBSYSTEM_WINDOWS_GUI


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
        return [_app_path()]
    if sys.platform == "win32":
        return [_shortcut_path(), _ico_path().parent]
    return []
