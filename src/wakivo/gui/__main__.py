"""Lets the launcher start the app as `python -m wakivo.gui`.

Generated launchers point at the interpreter rather than at a console script,
because that path is stable wherever the tool was installed and does not
depend on PATH being set up in whatever context the OS launches it from.
"""

from __future__ import annotations

from . import main

raise SystemExit(main())
