"""
Screen Manager — cycles display screens on Button 1 press.

Screens cycle in order:
  1 sensor:   DASHBOARD → BALLOON → DASHBOARD → ...
  2 sensors:  CONSOLIDATED → SENSOR_0 → SENSOR_1 → BALLOON → CONSOLIDATED → ...
  3 sensors:  CONSOLIDATED → SENSOR_0 → SENSOR_1 → SENSOR_2 → BALLOON → ...
  etc.

Screen stays until button pressed — no auto-timeout.
"""
import logging
import threading

log = logging.getLogger("screen_mgr")

# Screen type constants
SCREEN_DASHBOARD    = "dashboard"    # consolidated / single sensor SCADA view
SCREEN_SENSOR       = "sensor"       # single sensor full screen (index N)
SCREEN_BALLOON      = "balloon"      # balloon animation


class ScreenState:
    """Current screen state — read by display loop."""
    def __init__(self):
        self._lock        = threading.Lock()
        self._screen      = SCREEN_DASHBOARD
        self._sensor_idx  = 0   # which sensor for SCREEN_SENSOR

    @property
    def screen(self) -> str:
        with self._lock:
            return self._screen

    @property
    def sensor_idx(self) -> int:
        with self._lock:
            return self._sensor_idx

    def set(self, screen: str, sensor_idx: int = 0):
        with self._lock:
            self._screen     = screen
            self._sensor_idx = sensor_idx
        log.info(f"Screen → {screen}"
                 + (f"[{sensor_idx}]" if screen == SCREEN_SENSOR else ""))


class ScreenManager:
    """
    Handles button1 presses and advances through the screen sequence.
    """

    def __init__(self, state: ScreenState):
        self._state    = state
        self._sequence = []   # rebuilt each press based on sensor count
        self._idx      = 0    # position in sequence

    def advance(self, sensor_count: int):
        """Called on Button 1 press. Advances to next screen."""
        seq = self._build_sequence(sensor_count)

        # If sequence changed (sensor count changed), restart
        if seq != self._sequence:
            self._sequence = seq
            self._idx      = 0
        else:
            self._idx = (self._idx + 1) % len(self._sequence)

        screen, sidx = self._sequence[self._idx]
        self._state.set(screen, sidx)

    def _build_sequence(self, n: int) -> list:
        """Build ordered screen list for N sensors."""
        seq = []
        if n <= 1:
            # Single sensor or none: dashboard → balloon
            seq.append((SCREEN_DASHBOARD, 0))
            seq.append((SCREEN_BALLOON,   0))
        else:
            # Multi: consolidated → each sensor → balloon
            seq.append((SCREEN_DASHBOARD, 0))
            for i in range(n):
                seq.append((SCREEN_SENSOR, i))
            seq.append((SCREEN_BALLOON, 0))
        return seq

    def reset_to_dashboard(self):
        """Jump back to dashboard — called after reset or reconnect."""
        self._idx = 0
        self._sequence = []
        self._state.set(SCREEN_DASHBOARD, 0)


# Module-level singletons
screen_state   = ScreenState()
screen_manager = ScreenManager(screen_state)
