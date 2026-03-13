"""
screen_manager.py — Minimal screen state for pygame display.
Handles BTN1 screen cycling, BTN2 setup mode.
"""
import threading

SCREEN_DASHBOARD = "dashboard"
SCREEN_SENSOR    = "sensor"
SCREEN_BALLOON   = "balloon"


class ScreenState:
    def __init__(self):
        self._lock      = threading.Lock()
        self.screen     = SCREEN_DASHBOARD
        self.sensor_idx = 0

    def set(self, screen):
        with self._lock:
            self.screen = screen

    def advance(self, sensor_count):
        """BTN1 press — cycle through screens."""
        with self._lock:
            if self.screen == SCREEN_DASHBOARD:
                if sensor_count > 0:
                    self.screen     = SCREEN_SENSOR
                    self.sensor_idx = 0
                else:
                    self.screen = SCREEN_BALLOON
            elif self.screen == SCREEN_SENSOR:
                self.sensor_idx += 1
                if self.sensor_idx >= sensor_count:
                    self.screen = SCREEN_BALLOON
            elif self.screen == SCREEN_BALLOON:
                self.screen = SCREEN_DASHBOARD


class ScreenManager:
    def advance(self, sensor_count):
        screen_state.advance(sensor_count)


screen_state   = ScreenState()
screen_manager = ScreenManager()
