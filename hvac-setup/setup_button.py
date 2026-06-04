"""
setup_button.py — Physical button long press detection for management mode.

Monitors a GPIO pin in a background thread.
On 3-second hold → triggers management mode callback.

Wiring:
  Button between GPIO_PIN and GND (active low, internal pull-up)
  Default pin: GPIO 17 — change BUTTON_PIN to any available GPIO

Usage:
  from setup_button import ButtonMonitor

  def on_long_press():
      # enter management mode
      pass

  monitor = ButtonMonitor(on_long_press=on_long_press)
  monitor.start()
"""

import logging
import os
import threading
import time

log = logging.getLogger("setup_button")

BUTTON_PIN   = 17     # GPIO pin number (BCM numbering) — change as needed
LONG_PRESS_S = 3.0    # seconds to hold for long press
POLL_HZ      = 20     # polls per second


class ButtonMonitor:
    def __init__(self, on_long_press, pin: int = BUTTON_PIN,
                 long_press_s: float = LONG_PRESS_S):
        self._pin           = pin
        self._long_press_s  = long_press_s
        self._on_long_press = on_long_press
        self._thread        = None
        self._stop          = threading.Event()
        self._gpio          = None

    def start(self):
        """Start button monitoring in background thread."""
        if not self._init_gpio():
            log.warning("GPIO unavailable — button monitoring disabled")
            return False

        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="button-monitor",
            daemon=True,
        )
        self._thread.start()
        log.info(f"Button monitor started: GPIO{self._pin}, "
                 f"long press = {self._long_press_s}s")
        return True

    def stop(self):
        self._stop.set()
        if self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:
                pass

    def _init_gpio(self) -> bool:
        """Initialize GPIO. Returns False if RPi.GPIO not available."""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            log.info(f"GPIO{self._pin} configured as input with pull-up")
            return True
        except ImportError:
            log.warning("RPi.GPIO not installed — trying gpiozero")
            return self._init_gpiozero()
        except Exception as e:
            log.warning(f"GPIO init failed: {e}")
            return False

    def _init_gpiozero(self) -> bool:
        """Fallback to gpiozero."""
        try:
            from gpiozero import Button
            btn = Button(self._pin, pull_up=True, hold_time=self._long_press_s)
            btn.when_held = self._on_long_press
            self._gpio = btn
            log.info(f"gpiozero Button on GPIO{self._pin}")
            # gpiozero handles its own thread — no need for _monitor_loop
            self._thread = threading.Thread(target=lambda: self._stop.wait(),
                                            daemon=True, name="button-gpiozero")
            return True
        except Exception as e:
            log.warning(f"gpiozero init failed: {e}")
            return False

    def _monitor_loop(self):
        """Poll GPIO pin and detect long press."""
        import RPi.GPIO as GPIO

        press_start = None
        triggered   = False
        interval    = 1.0 / POLL_HZ

        log.info("Button monitor loop running")

        while not self._stop.is_set():
            try:
                state = GPIO.input(self._pin)   # LOW = pressed (active low)

                if state == GPIO.LOW:
                    if press_start is None:
                        press_start = time.time()
                        triggered   = False
                        log.debug("Button pressed")

                    held = time.time() - press_start
                    if held >= self._long_press_s and not triggered:
                        triggered = True
                        log.info(f"Long press detected ({held:.1f}s) — "
                                 f"triggering management mode")
                        try:
                            self._on_long_press()
                        except Exception as e:
                            log.error(f"Long press callback error: {e}")
                else:
                    if press_start is not None:
                        held = time.time() - press_start
                        log.debug(f"Button released after {held:.1f}s")
                    press_start = None
                    triggered   = False

            except Exception as e:
                log.error(f"Button monitor error: {e}")

            time.sleep(interval)

        log.info("Button monitor stopped")
