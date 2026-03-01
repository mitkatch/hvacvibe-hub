"""
Button Handler — GPIO5 (Button 1: screen flip) and GPIO26 (Button 2: reset)

Uses RPi.GPIO with internal pull-up resistors.
Button press pulls pin LOW.

Button 1 (GPIO5):  short press → post EVT_BUTTON1_PRESS
Button 2 (GPIO26): short press → ignored
                   hold 3s    → post EVT_BUTTON2_LONG_PRESS (reset)

On non-Pi systems: runs keyboard simulation (B=button1, R=button2 long)
"""
import logging
import platform
import threading
import time

log = logging.getLogger("buttons")
log.setLevel(logging.DEBUG)

ON_PI = platform.system() not in ("Windows", "Darwin")

# GPIO pins (BCM numbering)
BTN1_PIN = 5    # Screen flip
BTN2_PIN = 26   # Reset (long press)

DEBOUNCE_MS      = 50     # ignore bounces shorter than this
LONG_PRESS_MS    = 3000   # hold time for long press


class ButtonManager:
    """
    Monitors two GPIO buttons and calls registered callbacks.
    Thread-safe — callbacks are called from the button thread.
    """

    def __init__(self):
        self._cb_btn1  = None   # short press
        self._cb_btn2_long = None   # long press

    def on_button1(self, fn):
        """Register callback for Button 1 short press."""
        self._cb_btn1 = fn

    def on_button2_long(self, fn):
        """Register callback for Button 2 long press (3s)."""
        self._cb_btn2_long = fn

    def start(self) -> threading.Thread:
        if ON_PI:
            t = threading.Thread(target=self._gpio_loop,
                                 name="buttons", daemon=True)
        else:
            t = threading.Thread(target=self._keyboard_loop,
                                 name="buttons-sim", daemon=True)
        t.start()
        log.info(f"Button thread started: {t.name}")
        return t

    # ── GPIO loop (Pi) ────────────────────────────────────────
    def _gpio_loop(self):
        try:
            import RPi.GPIO as GPIO
        except ImportError:
            log.error("RPi.GPIO not found — buttons disabled")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BTN1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(BTN2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        log.info(f"GPIO buttons: BTN1=GPIO{BTN1_PIN} BTN2=GPIO{BTN2_PIN}")

        btn2_down_at = None
        last_debug    = 0.0

        while True:
            time.sleep(0.02)  # 20ms poll

            # ── Debug: log raw pin states every 2s ───────────
            now = time.time()
            if now - last_debug > 2.0:
                b1 = GPIO.input(BTN1_PIN)
                b2 = GPIO.input(BTN2_PIN)
                log.debug(f"GPIO raw: BTN1(GPIO{BTN1_PIN})={b1} BTN2(GPIO{BTN2_PIN})={b2}  (LOW=pressed)")
                last_debug = now

            # ── Button 1: short press ──────────────────────────
            if GPIO.input(BTN1_PIN) == GPIO.LOW:
                log.info(f"BTN1 raw LOW detected on GPIO{BTN1_PIN}")
                time.sleep(DEBOUNCE_MS / 1000)
                if GPIO.input(BTN1_PIN) == GPIO.LOW:
                    log.info("Button 1 CONFIRMED pressed — firing callback")
                    if self._cb_btn1:
                        self._cb_btn1()
                    else:
                        log.warning("Button 1: no callback registered!")
                    # Wait for release
                    while GPIO.input(BTN1_PIN) == GPIO.LOW:
                        time.sleep(0.02)
                    log.info("Button 1 released")
                else:
                    log.debug("BTN1: debounce rejected (bounce)")

            # ── Button 2: long press only ─────────────────────
            if GPIO.input(BTN2_PIN) == GPIO.LOW:
                if btn2_down_at is None:
                    btn2_down_at = time.time()
                    log.info(f"BTN2 raw LOW detected on GPIO{BTN2_PIN} — start timing")
                held_ms = (time.time() - btn2_down_at) * 1000
                log.debug(f"BTN2 held {held_ms:.0f}ms / {LONG_PRESS_MS}ms")
                if held_ms >= LONG_PRESS_MS:
                    log.info("Button 2 LONG PRESS confirmed — firing reset callback")
                    if self._cb_btn2_long:
                        self._cb_btn2_long()
                    else:
                        log.warning("Button 2: no callback registered!")
                    while GPIO.input(BTN2_PIN) == GPIO.LOW:
                        time.sleep(0.02)
                    btn2_down_at = None
            else:
                if btn2_down_at is not None:
                    log.info(f"BTN2 released early ({(time.time()-btn2_down_at)*1000:.0f}ms — need {LONG_PRESS_MS}ms)")
                btn2_down_at = None

    # ── Keyboard simulation (desktop) ────────────────────────
    def _keyboard_loop(self):
        """
        On desktop: press keys in terminal to simulate buttons.
        B = Button 1 (screen flip)
        R = Button 2 long press (reset)
        """
        log.info("Button sim: type 'b' + Enter = Button1, "
                 "'r' + Enter = Button2 long press")
        import sys
        while True:
            try:
                line = sys.stdin.readline().strip().lower()
                if line == "b":
                    log.info("SIM: Button 1")
                    if self._cb_btn1:
                        self._cb_btn1()
                elif line == "r":
                    log.info("SIM: Button 2 long press")
                    if self._cb_btn2_long:
                        self._cb_btn2_long()
            except Exception:
                time.sleep(0.1)


# Module-level singleton
buttons = ButtonManager()
