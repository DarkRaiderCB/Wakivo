# wakivo

[![CI](https://github.com/DarkRaiderCB/Wakivo/actions/workflows/ci.yml/badge.svg)](https://github.com/DarkRaiderCB/Wakivo/actions/workflows/ci.yml)

Keep your machine awake for as long as a task actually runs — then let it sleep again.

Built for the case where you start something long (an agentic coding session, a training run, a big build), walk away from your desk, and come back to find the machine went to sleep half way through.

```sh
wakivo -- uv run train.py     # stay awake until the command exits
wakivo --pid 41823            # stay awake until that process exits
wakivo 2h                     # stay awake for two hours
wakivo                        # stay awake until Ctrl-C
```

`wakivo` exits with the wrapped command's own exit code, so it drops into scripts and CI without changing their behaviour.

## Install

```sh
uv tool install wakivo            # the CLI
uv tool install "wakivo[gui]"     # and the menu bar app
```

`pipx install` works the same way. Requires Python 3.13+.

## Menu bar app

`wakivo-gui` puts a cup in the menu bar (macOS) or notification area
(Windows), for when you would rather not open a terminal.

```
● Awake — 1h 30m left
──────────────────────
Keep awake for      ▸   15m · 30m · 1h · 2h · 4h
Keep awake until I quit
Stop
──────────────────────
☑ Also keep the display on
Quit
```

Two modes, on purpose. Binding a hold to a particular process means knowing
which process, and anyone who does is already served by `wakivo --pid` — so
the GUI has no picker to misunderstand. The icon is filled while a hold is
active and outlined when it is not, so "is it on?" needs no click.

### Launching it without a terminal

```sh
wakivo-gui --install       # then launch it like any other app
wakivo-gui --uninstall
```

On macOS this writes `~/Applications/Wakivo.app`; on Windows, a Start menu
shortcut. Run it once and you never need a shell again.

No code signing is involved, because the launcher is built **on your machine**
rather than downloaded. Gatekeeper and SmartScreen act on the quarantine
attribute, which is applied by whatever fetched a file from elsewhere — a
bundle your own computer just wrote never carries one. Nothing here embeds a
Python runtime either; the launcher simply starts the interpreter you already
have.

**macOS and Windows only.** Linux keeps the CLI: GNOME removed system tray
support years ago, so a tray icon needs a shell extension the user has to
install first. `wakivo-gui` says so and exits rather than half-working.

## Options

| Flag | Effect |
| --- | --- |
| `-d`, `--keep-display` | Also keep the display on. Off by default — the screen still sleeps. Not yet supported on Linux, where it is refused rather than silently ignored. |
| `-q`, `--quiet` | Suppress status output. |
| `--pid PID` | Release when this process exits. |

Durations accept `90s`, `20m`, `2h`, `1h30m`, or a bare number of seconds.

## Scope

wakivo prevents **idle sleep** — the machine suspending because you stopped
touching it. That is the failure that interrupts a long task. Everything else
is deliberately out of scope.

| Behaviour | Held off? |
| --- | --- |
| Idle system sleep / suspend | **Yes** — the entire point |
| Screen blanking | No by default; `-d` on macOS and Windows |
| Session lock / password prompt | No |
| Closing the lid | **No** |
| Suspend at critical battery | **No** |
| Deliberate sleep (`systemctl suspend`, menu, ⌘⌥⏏) | Allowed on macOS and Windows; refused on Linux where the stronger hold is permitted |

A blanked, locked screen with your job still running is the *intended*
outcome, not a failure — it is why screen-off is the default rather than `-d`.
Neither blanking nor locking stops a running process.

Two of those rows are worth explaining, because they surprise people:

**Closing the lid still sleeps the machine.** The lid switch is a hardware
event, separate from idle sleep, and no wakelock on any platform survives it —
not `caffeinate`, not `SetThreadExecutionState`, not `wakivo`. Holding a laptop
awake through a closed lid requires root and a *persistent* change to system
power settings, so a crash could leave your machine permanently unable to
sleep. That trade is deliberately not made here. It may return as an explicit
opt-in flag.

**A critical battery still sleeps the machine.** UPower on Linux, and the
equivalent elsewhere, suspends or hibernates directly at critical charge and
ignores every inhibitor by design. You cannot inhibit your way out of a dying
battery, and shouldn't be able to.

## Design

Two independent axes:

- **`backends/`** — *how* the hold is taken, per platform. macOS uses IOKit
  power assertions via `ctypes`; Windows uses `SetThreadExecutionState` on a
  dedicated parked thread, because the flag is per-thread and evaporates when
  the setting thread exits; Linux takes a systemd-logind inhibitor, plus
  GNOME's own session inhibitor when running inside a GNOME session.
- **`triggers/`** — *when* the hold is released: a command exiting, a pid dying,
  a timer, or an interrupt.
- **`session.py`** — a hold that can be started and stopped rather than waited
  out. The CLI runs to completion; the menu bar app needs to acquire and
  return, then release later. Both drive the same backends and triggers.

Any trigger composes with any backend, so a new release condition is a new file
rather than a change to the wakelock code.

Every backend must be crash-safe: the OS drops the hold when the process dies,
including on `SIGKILL`. `wakivo` never mutates persistent system settings, so
there is nothing to clean up and nothing to restore.

### Why Linux drives a subprocess

macOS and Windows call the platform API directly rather than shelling out to
`caffeinate` — a child process is one more thing that can outlive us still
holding the hold.

logind is genuinely different. Its inhibitor is handed out as a *file
descriptor* over D-Bus, so taking it in-process means implementing D-Bus fd
passing. `systemd-inhibit` is the canonical client for that, so the Linux
backend runs it as a child and uses `PR_SET_PDEATHSIG` to keep the guarantee:
the kernel kills the helper the moment `wakivo` dies, so the descriptor is
dropped however we exit. Taking the fd directly would remove the child
entirely and is worth doing later.

### Two holds on Linux, not one

A logind inhibitor alone does not stop GNOME. Measured on Debian/GNOME with a
60-second idle timeout, journal markers either side of the hold:

```
18:51:41  CONTROL START
18:52:41  will suspend now      <- 60s, control valid
18:54:26  HOLD START
18:56:18  will suspend now      <- 112s, suspended mid-hold
18:59:31  HOLD END
```

wakivo was holding `sleep:idle` in **block** mode throughout — strong enough
that `systemctl suspend` was refused outright — and `gsd-power` suspended the
machine anyway. GNOME runs its own idle policy against its own session
inhibitors, which live on the session bus and are entirely separate from
logind's. Adding `gnome-session-inhibit` fixed it: the same run now reaches
`HOLD END` with no suspend in between.

So inside a GNOME session wakivo takes both: the logind inhibitor, which
governs headless and non-GNOME systems, and `gnome-session-inhibit`, which is
the one GNOME actually consults. Neither subsumes the other — a Debian server
has no `gnome-session` at all.

The logind hold tries `--what=idle:sleep` first and falls back to `idle`.
Blocking `sleep` also stops `Suspend()` calls, covering desktops whose power
daemon hasn't been measured here — but it needs the
`org.freedesktop.login1.inhibit-block-sleep` polkit action, which is denied
without an active seat session, so headless servers and CI runners are refused
outright. Blocking `idle` is granted broadly and covers logind's own
`IdleAction`, which is exactly what governs those machines.

Where the stronger hold is permitted, a deliberate `systemctl suspend` is
refused while wakivo runs. That differs from macOS, where
`PreventUserIdleSystemSleep` leaves intentional sleep alone.

The GNOME hold inhibits `suspend` only, deliberately not `idle` — GNOME's idle
inhibitor also suppresses screen blanking and locking, and screen-off is
wakivo's default.

## Status

macOS, Windows and Linux all pass in CI, each asserting against its own power
tooling — `pmset -g assertions`, `powercfg /requests`, `systemd-inhibit
--list` — that the hold is visible to the OS and is reclaimed when the process
is killed outright.

Beyond CI, all three have been verified on real hardware the only way that
counts: shorten the idle timeout to one minute, confirm with a control run
that the machine *does* sleep, then hold for four minutes and confirm it
doesn't.

| Platform | Control confirmed by | Result |
| --- | --- | --- |
| macOS | `pmset -g log` idle sleep entries | stayed awake |
| Windows | Kernel-Power Event 42 | stayed awake |
| Debian / GNOME | journal markers around the hold | stayed awake |

Two honest limits on what CI itself proves:

- No CI runner ever idles into sleep, so CI shows the platform *accepts the
  hold and reports it*, not that the machine stays awake. That part is only
  verifiable by hand.
- Linux runs on `ubuntu-latest`, a headless systemd VM with no seat session.
  It covers the logind path and the fallback to an idle-only hold, but never
  reaches the GNOME branch — which is exactly where the bug above lived.
  Desktop coverage is manual.

`--keep-display` is unimplemented on Linux; it needs the DE-specific
screensaver interfaces, and is refused rather than silently ignored.

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
