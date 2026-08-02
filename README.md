# oncafe

[![CI](https://github.com/DarkRaiderCB/OnCafe/actions/workflows/ci.yml/badge.svg)](https://github.com/DarkRaiderCB/OnCafe/actions/workflows/ci.yml)

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
| `-d`, `--keep-display` | Also keep the display on. Off by default — the screen still sleeps. Not yet supported on Linux, where it is refused rather than silently ignored. |
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
  the setting thread exits; Linux takes a systemd-logind idle inhibitor.
- **`triggers/`** — *when* the hold is released: a command exiting, a pid dying,
  a timer, or an interrupt.

Any trigger composes with any backend, so a new release condition is a new file
rather than a change to the wakelock code.

Every backend must be crash-safe: the OS drops the hold when the process dies,
including on `SIGKILL`. `oncafe` never mutates persistent system settings, so
there is nothing to clean up and nothing to restore.

### Why Linux drives a subprocess

macOS and Windows call the platform API directly rather than shelling out to
`caffeinate` — a child process is one more thing that can outlive us still
holding the hold.

logind is genuinely different. Its inhibitor is handed out as a *file
descriptor* over D-Bus, so taking it in-process means implementing D-Bus fd
passing. `systemd-inhibit` is the canonical client for that, so the Linux
backend runs it as a child and uses `PR_SET_PDEATHSIG` to keep the guarantee:
the kernel kills the helper the moment `oncafe` dies, so the descriptor is
dropped however we exit. Taking the fd directly would remove the child
entirely and is worth doing later.

The inhibitor is `--what=idle`, not `idle:sleep`, so an explicit
`systemctl suspend` still works — matching `PreventUserIdleSystemSleep` on
macOS.

## Status

macOS, Windows and Linux all pass in CI, each asserting against its own power
tooling — `pmset -g assertions`, `powercfg /requests`, `systemd-inhibit
--list` — that the hold is visible to the OS and is reclaimed when the process
is killed outright.

Two honest limits on what that proves:

- No CI runner ever idles into sleep, so CI shows the platform *accepts the
  hold and reports it*, not that the machine stays awake. That part is
  verified by hand, once per platform.
- Linux is covered on `ubuntu-latest`, a headless systemd VM. That exercises
  the logind path, which is the whole of the Linux backend today, but says
  nothing about desktop environments — and `--keep-display`, which would need
  the DE-specific screensaver interfaces, is refused on Linux rather than
  silently ignored.

## Development

```sh
uv sync
uv run pytest
```

The backend tests take a real wakelock and assert the OS can see it, so they
catch a broken `ctypes` signature before a user does. On macOS one of them
`SIGKILL`s a child holding an assertion and checks the kernel reclaimed it.

## Licence

MIT — see [LICENSE](LICENSE).
