# Power Management

`util_power.py` provides sleep/wake and reboot control for tests that involve timer interrupts,
reboots, and sleep state transitions (e.g. NPLAN-6711 B-series tests).

## Platform support

| Function | Windows | macOS | Linux |
|---|---|---|---|
| `enter_s0_and_wake(sec)` | pwrtest `/cs` → monitor-off ctypes fallback | `pmset displaysleepnow` + `caffeinate` | returns `False` |
| `enter_s1_and_wake(sec)` | pwrtest `/sleep /s:1` → `SetSuspendState` fallback | `pmset sleepnow` + scheduled wake | returns `False` |
| `enter_s4_and_wake(sec)` | pwrtest `/sleep /s:s4` → `SetSuspendState(hibernate)` | mapped to system sleep | returns `False` |
| `is_sleep_state_available(name)` | `powercfg /a` (EN + ZH-TW) | `pmset -g cap` | `False` |
| `enable_wake_timers()` | 3× `powercfg` GUIDs | `True` (N/A) | `False` |
| `reboot()` | `shutdown /r /t 0` | `sudo shutdown -r now` | `sudo reboot` |

## Usage in tests

```python
from util_power import (
    enter_s0_and_wake,
    enter_s1_and_wake,
    enter_s4_and_wake,
    is_sleep_state_available,
    enable_wake_timers,
    reboot,
)

# Check availability before entering a sleep state
if is_sleep_state_available("Hibernate"):
    enter_s4_and_wake(duration_seconds=300)

# Enable wake timers before any sleep test on Windows
enable_wake_timers()
enter_s1_and_wake(duration_seconds=120)
```

## Sleep state names for `is_sleep_state_available`

| Name | State |
|---|---|
| `"Standby (S0 Low Power Idle)"` | Modern Standby / AOAC |
| `"Standby (S1)"` | Legacy Standby |
| `"Hibernate"` | S4 Hibernate |

## Windows requirements

- **Admin privileges required** — `powercfg` and sleep state transitions need elevation.
  Use the `require_admin` fixture in feature tests.
- **pwrtest.exe** — bundled at `tool/pwrtest.exe`. Used for reliable sleep cycling.
  Falls back to ctypes if missing, but pwrtest is preferred.
- **Wake timers** — call `enable_wake_timers()` once before sleep tests, or add it to
  your feature `conftest.py` as a session-scoped fixture.

## Platform safety

Power functions on Linux return `False` cleanly — they never import Windows-only modules.
Tag sleep-state tests with the appropriate platform marker so they are auto-skipped on
other platforms:

```python
@pytest.mark.windows
@pytest.mark.priority_medium
def test_b04_s0_modern_standby(require_admin):
    enable_wake_timers()
    assert enter_s0_and_wake(duration_seconds=60)
```
