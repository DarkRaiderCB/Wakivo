# Contributing

Thanks for looking. This file covers the things that are specific to wakivo:
the invariants, and how to verify a change to a platform backend. For what
wakivo does and does not do, read the Scope section of the [README](README.md)
first; a lot of proposals turn out to be things that were left out on purpose.

## Getting set up

```sh
uv sync --all-extras     # --all-extras matters: it pulls the GUI dependencies
uv run pytest
```

Python 3.13+. The CLI has no runtime dependencies; the menu bar app adds
pystray and Pillow behind the `gui` extra.

## The one invariant

**The operating system must reclaim the hold when the process dies.** Every
backend holds something the kernel owns (an IOKit assertion, a per-thread
execution state, a logind inhibitor file descriptor) so that `SIGKILL`, a
crash, or a closed terminal leaves nothing behind.

This rules out the obvious shortcuts. `pmset disablesleep` and
`powercfg /change` would both work, and both write persistent system settings:
if wakivo died between setting and restoring them, the machine would never
sleep again and the user would have no idea why. A patch that mutates
persistent power settings will be declined however convenient it is.

The Linux backend runs `systemd-inhibit` as a child rather than calling the
API directly, because logind hands the inhibitor out as a file descriptor over
D-Bus. `PR_SET_PDEATHSIG` preserves the invariant there: the kernel kills the
helper when wakivo dies.

## Architecture

Two independent axes, which is what keeps platform code and policy separate:

- **`backends/`**: *how* a hold is taken, one module per platform
- **`triggers/`**: *when* it is released: a command exits, a pid dies, a timer
  runs out, an interrupt arrives
- **`session.py`**: a hold that can be started and stopped rather than waited
  out; the CLI runs to completion, the tray app does not
- **`gui/`**: a front end only. It builds a `Trigger` and hands it to the
  controller. No power logic lives there.

A new release condition should be a new file in `triggers/`, not a change to
any backend.

## Tests

```sh
uv run pytest
```

The backend tests take a **real** wakelock and assert the OS can see it, rather
than mocking the platform call. That is deliberate: the failure mode these
guard against is a wrong `ctypes` signature, and a mock accepts those happily.
One test per platform kills a child process holding a hold and checks the
kernel reclaimed it.

Tests skip themselves off their platform, so a green run on one machine has
not exercised the others. `pytest -ra` prints the skip reasons; read them
before concluding a change is covered.

## Verifying a backend change

CI cannot prove a machine stays awake, because no runner ever idles into sleep. It
proves the platform accepts the hold and reports it. Anything that changes
power behaviour has to be checked by hand on that platform, and the honest
method needs a control:

1. Shorten the idle sleep timeout to one minute.
2. **Control run:** leave the machine alone and confirm it *does* sleep. If it
   does not, the setting did not apply and the next step proves nothing.
3. **Test run:** hold for several minutes and confirm it does not.

Where to look for the hold itself:

| Platform | Command |
| --- | --- |
| macOS | `pmset -g assertions`, and `pmset -g log` for sleep history |
| Windows | `powercfg /requests`, needs an elevated shell |
| Linux | `systemd-inhibit --list`, and `journalctl` for suspend events |

Say in the pull request which platforms you verified on and how. "Tests pass"
is not the same claim.

## Pull requests

CI runs on Linux, Windows and macOS, and all three must pass before merge.
Branch protection means everything reaches `main` through a pull request.

Commit messages here explain *why*, not what. Several record measurements
that took hours to obtain, such as a status item coming up zero pixels high,
or a launcher spawning a console interpreter. If your change fixes something
non-obvious, put the evidence in the message; the next person will need it,
and it may be you.

Two things that will be pushed back on:

- **New runtime dependencies.** The CLI has none, and that is a feature worth
  keeping. GUI-only dependencies belong in the `gui` extra.
- **Anything that reaches the network.** wakivo makes no network calls, has no
  telemetry, and does not check for updates. For a background process that
  manipulates system power, that is a promise worth keeping.

## Reporting a bug

Include your OS and version, `wakivo --version`, the exact command, and what
the platform tool above reported while the hold was meant to be active. For
"it went to sleep anyway", the journal or log excerpt is the useful part. The
lid, a critical battery, and a desktop environment with its own idle policy
are all out of wakivo's reach, and the logs are what tell those apart.
