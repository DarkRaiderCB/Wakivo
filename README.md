# oncafe

Keep your machine awake for as long as a task actually runs — then let it sleep again.

Built for the case where you start something long (an agentic coding session, a training run, a big build), walk away from your desk, and come back to find the machine went to sleep half way through.

```sh
oncafe -- uv run train.py     # stay awake until the command exits
oncafe --pid 41823            # stay awake until that process exits
oncafe 2h                     # stay awake for two hours
oncafe                        # stay awake until Ctrl-C
```

`oncafe` exits with the wrapped command's own exit code, so it drops into scripts and CI without changing their behaviour.

## Install

```sh
uv tool install oncafe    # or: pipx install oncafe
```

Requires Python 3.13+.

## Options

| Flag | Effect |
| --- | --- |
| `-d`, `--keep-display` | Also keep the display on. Off by default — the screen still sleeps. |
| `-q`, `--quiet` | Suppress status output. |
| `--pid PID` | Release when this process exits. |

Durations accept `90s`, `20m`, `2h`, `1h30m`, or a bare number of seconds.

## Known limitation: closing the lid

**Closing the lid will still put the machine to sleep.** This is expected, not a bug.

The lid switch is a hardware event, separate from idle sleep. No wakelock on any
platform survives it — not `caffeinate`, not `SetThreadExecutionState`, not
`oncafe`. Holding a laptop awake through a closed lid requires root and a
*persistent* change to system power settings, which means a crash could leave
your machine permanently unable to sleep. That trade is deliberately not made
here. It may return later as an explicit opt-in flag.

## Design

Two independent axes:

- **`backends/`** — *how* the hold is taken, per platform. macOS uses IOKit
  power assertions via `ctypes`; Windows uses `SetThreadExecutionState` on a
  dedicated parked thread, because the flag is per-thread and evaporates when
  the setting thread exits.
- **`triggers/`** — *when* the hold is released: a command exiting, a pid dying,
  a timer, or an interrupt.

Any trigger composes with any backend, so a new release condition is a new file
rather than a change to the wakelock code.

Every backend must be crash-safe: the OS drops the hold when the process dies,
including on `SIGKILL`. `oncafe` never mutates persistent system settings, so
there is nothing to clean up and nothing to restore.

## Status

v0 supports macOS and Windows. Linux support is planned via the systemd-logind
inhibitor (`org.freedesktop.login1.Manager.Inhibit`), tested against Debian.

## Licence

MIT
