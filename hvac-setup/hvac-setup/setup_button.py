"""
setup_button.py — GPIO button with two distinct press durations.

Short press (1-4s release) → management mode callback
Long press  (5s+ hold)     → WiFi setup callback

Wiring: button between GPIO_PIN and GND (active low, internal pull-up)
Default pin: GPIO 17
"""

import logging
import threading
import time

log = logging.getLogger("setup_button")

BUTTON_PIN      = 17
SHORT_MIN_S     = 1.0   # minimum hold for short press
LONG_PRESS_S    = 5.0   # hold duration for WiFi setup
POLL_HZ         = 20


class ButtonMonitor:
    def __init__(self, on_short_press=None, on_long_press=None,
                 pin: int = BUTTON_PIN):
        self._pin            = pin
        self._on_short_press = on_short_press
        self._on_long_press  = on_long_press
        self._thread         = None
        self._stop           = threading.Event()
        self._gpio           = None

    def start(self):
        if not self._init_gpio():
            log.warning("GPIO unavailable — button monitoring disabled")
            return False
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="button-monitor",
            daemon=True,
        )
        self._thread.start()
        log.info(f"Button monitor started: GPIO{self._pin} "
                 f"short={SHORT_MIN_S}-{LONG_PRESS_S}s long={LONG_PRESS_S}s+")
        return True

    def stop(self):
        self._stop.set()
        if self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:
                pass

    def _init_gpio(self) -> bool:
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            log.info(f"GPIO{self._pin} initialized")
            return True
        except ImportError:
            return self._init_gpiozero()
        except Exception as e:
            log.warning(f"GPIO init failed: {e}")
            return False

    def _init_gpiozero(self) -> bool:
        try:
            from gpiozero import Button
            btn = Button(self._pin, pull_up=True, hold_time=LONG_PRESS_S)

            def _on_held():
                if self._on_long_press:
                    self._on_long_press()

            def _on_released():
                held = btn.active_time or 0
                if SHORT_MIN_S <= held < LONG_PRESS_S:
                    if self._on_short_press:
                        self._on_short_press()

            btn.when_held     = _on_held
            btn.when_released = _on_released
            self._gpio = btn
            return True
        except Exception as e:
            log.warning(f"gpiozero init failed: {e}")
            return False

    def _monitor_loop(self):
        import RPi.GPIO as GPIO
        press_start    = None
        long_triggered = False
        interval       = 1.0 / POLL_HZ

        while not self._stop.is_set():
            try:
                state = GPIO.input(self._pin)

                if state == GPIO.LOW:
                    if press_start is None:
                        press_start    = time.time()
                        long_triggered = False

                    held = time.time() - press_start
                    if held >= LONG_PRESS_S and not long_triggered:
                        long_triggered = True
                        log.info(f"Long press ({held:.1f}s) — WiFi setup")
                        if self._on_long_press:
                            threading.Thread(target=self._on_long_press,
                                             daemon=True).start()
                else:
                    if press_start is not None:
                        held = time.time() - press_start
                        if SHORT_MIN_S <= held < LONG_PRESS_S and not long_triggered:
                            log.info(f"Short press ({held:.1f}s) — management mode")
                            if self._on_short_press:
                                threading.Thread(target=self._on_short_press,
                                                 daemon=True).start()
                    press_start    = None
                    long_triggered = False

            except Exception as e:
                log.error(f"Button error: {e}")

            time.sleep(interval)
