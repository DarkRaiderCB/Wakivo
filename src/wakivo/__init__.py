from importlib.metadata import PackageNotFoundError, version

try:
    # One source of truth: pyproject. A hardcoded copy here drifted from it
    # immediately -- `wakivo --version` reported 0.1.0 for a 0.1.0a1 build.
    __version__ = version("wakivo")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0+unknown"

__all__ = ["__version__"]
