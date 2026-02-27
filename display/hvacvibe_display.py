#!/usr/bin/env python3
# ============================================================
# HVAC-Vibe Gateway Display
# Industrial SCADA-style UI for Waveshare 3.5" LCD (G)
# 320x480 pixels | Pygame | Dark theme
# ============================================================

import os
import sys
import math
import platform
import random
import time
import pygame

# --- Platform detection: use framebuffer on Pi, window on Windows/Mac ---
if platform.system() != 'Windows' and platform.system() != 'Darwin':
    os.environ['SDL_VIDEODRIVER'] = 'fbcon'
    os.environ['SDL_FBDEV']       = '/dev/fb1'

# ============================================================
# COLOUR PALETTE  (SCADA industrial dark)
# ============================================================
C_BG          = (18,  22,  28)    # near-black background
C_PANEL       = (28,  34,  44)    # card/panel background
C_PANEL_EDGE  = (45,  55,  70)    # panel border
C_HEADER_BG   = (22,  28,  38)    # top header bar
C_ACCENT      = (0,  160, 220)    # blue accent
C_GREEN       = (0,  200, 100)    # OK / connected
C_YELLOW      = (255, 190,  0)    # warning
C_RED         = (220,  50,  50)   # alarm / disconnected
C_WHITE       = (220, 225, 230)
C_GREY        = (100, 110, 125)
C_DIVIDER     = (40,  50,  62)

# Battery colours
C_BAT_HIGH    = (0,  200, 100)
C_BAT_MED     = (255, 190,   0)
C_BAT_LOW     = (220,  50,  50)

# ============================================================
# MOCK DATA  —  replace with real BLE data later
# ============================================================
class SensorData:
    def __init__(self, name, address):
        self.name      = name
        self.address   = address
        self.connected = True
        self.rssi      = -65
        self.battery   = 78          # percent
        self.temp      = 24.3        # °C
        self.humidity  = 52.1        # %RH
        self.vib_rms   = 0.42        # g
        self.vib_peak  = 1.15        # g
        self.vib_freq  = 48.0        # Hz dominant
        self.alarm     = False
        self._t        = 0.0

    def tick(self):
        """Simulate live data — remove when using real BLE"""
        self._t += 0.05
        self.vib_rms  = max(0.01, 0.42 + 0.08 * math.sin(self._t * 1.3) + random.uniform(-0.02, 0.02))
        self.vib_peak = self.vib_rms * 2.7 + random.uniform(-0.05, 0.05)
        self.vib_freq = 48.0 + 2.0 * math.sin(self._t * 0.4)
        self.temp     = 24.3 + 0.5 * math.sin(self._t * 0.1)
        self.humidity = 52.1 + 1.0 * math.sin(self._t * 0.07)
        self.rssi     = int(-65 + 5 * math.sin(self._t * 0.3))
        self.alarm    = self.vib_rms > 0.55

SENSORS = [
    SensorData("UNIT-01", "AA:BB:CC:DD:EE:01"),
    SensorData("UNIT-02", "AA:BB:CC:DD:EE:02"),
]
SENSORS[1].battery  = 23   # low battery demo
SENSORS[1].vib_rms  = 0.18
SENSORS[1].temp     = 31.7
SENSORS[1].humidity = 61.4
SENSORS[1].rssi     = -82

# ============================================================
# HELPERS
# ============================================================
def bat_color(pct):
    if pct > 50: return C_BAT_HIGH
    if pct > 20: return C_BAT_MED
    return C_BAT_LOW

def rssi_bars(rssi):
    """Return 0-4 signal bars from RSSI"""
    if rssi >= -60: return 4
    if rssi >= -70: return 3
    if rssi >= -80: return 2
    if rssi >= -90: return 1
    return 0

def alarm_color(alarm):
    return C_RED if alarm else C_GREEN

def fmt_float(val, decimals=2):
    return f"{val:.{decimals}f}"

# ============================================================
# DRAWING PRIMITIVES
# ============================================================
def draw_panel(surf, x, y, w, h, title=None, title_color=None):
    """Draw a labelled panel card"""
    pygame.draw.rect(surf, C_PANEL,      (x, y, w, h), border_radius=4)
    pygame.draw.rect(surf, C_PANEL_EDGE, (x, y, w, h), width=1, border_radius=4)
    if title:
        col = title_color or C_GREY
        lbl = FONT_TINY.render(title.upper(), True, col)
        surf.blit(lbl, (x + 8, y + 5))

def draw_battery(surf, x, y, w, h, pct):
    """Draw battery icon with fill level"""
    col = bat_color(pct)
    tip_w, tip_h = 4, h // 3
    # body
    pygame.draw.rect(surf, C_PANEL_EDGE, (x, y, w, h), border_radius=2)
    # fill
    fill_w = max(2, int((w - 4) * pct / 100))
    fill_col = col
    pygame.draw.rect(surf, fill_col, (x + 2, y + 2, fill_w, h - 4), border_radius=1)
    # tip
    pygame.draw.rect(surf, C_PANEL_EDGE, (x + w, y + (h - tip_h) // 2, tip_w, tip_h), border_radius=1)
    # label
    lbl = FONT_TINY.render(f"{pct}%", True, col)
    surf.blit(lbl, (x + w + tip_w + 4, y + (h - lbl.get_height()) // 2))

def draw_signal(surf, x, y, bars):
    """Draw 4-bar signal strength indicator"""
    bar_w = 5
    gap   = 2
    max_h = 16
    for i in range(4):
        bh  = int(max_h * (i + 1) / 4)
        bx  = x + i * (bar_w + gap)
        by  = y + max_h - bh
        col = C_ACCENT if i < bars else C_DIVIDER
        pygame.draw.rect(surf, col, (bx, by, bar_w, bh), border_radius=1)

def draw_vib_bar(surf, x, y, w, h, value, max_val, alarm):
    """Horizontal bar graph for vibration RMS"""
    pygame.draw.rect(surf, C_DIVIDER, (x, y, w, h), border_radius=2)
    fill = min(1.0, value / max_val)
    if fill > 0:
        col = C_RED if alarm else C_ACCENT
        pygame.draw.rect(surf, col, (x, y, int(w * fill), h), border_radius=2)
    # threshold marker at 70%
    mx = x + int(w * 0.7)
    pygame.draw.line(surf, C_YELLOW, (mx, y - 2), (mx, y + h + 2), 1)

def draw_status_dot(surf, x, y, r, connected):
    col = C_GREEN if connected else C_RED
    pygame.draw.circle(surf, col, (x, y), r)
    pygame.draw.circle(surf, C_PANEL_EDGE, (x, y), r, 1)

def draw_divider(surf, x, y, w):
    pygame.draw.line(surf, C_DIVIDER, (x, y), (x + w, y), 1)

# ============================================================
# SENSOR CARD   (fits in half the screen height minus header)
# ============================================================
CARD_X = 4
CARD_W = 312
CARD_H = 210

def draw_sensor_card(surf, sensor, x, y):
    alarm = sensor.alarm and sensor.connected

    # Card background — red tint if alarm
    bg = (38, 22, 22) if alarm else C_PANEL
    pygame.draw.rect(surf, bg,           (x, y, CARD_W, CARD_H), border_radius=6)
    border_col = C_RED if alarm else C_PANEL_EDGE
    pygame.draw.rect(surf, border_col,   (x, y, CARD_W, CARD_H), width=1, border_radius=6)

    # ---- Header row ----
    # Status dot
    draw_status_dot(surf, x + 14, y + 14, 6, sensor.connected)

    # Sensor name
    name_surf = FONT_MED.render(sensor.name, True, C_WHITE)
    surf.blit(name_surf, (x + 26, y + 6))

    # Alarm badge
    if alarm:
        badge = FONT_TINY.render("! ALARM", True, C_BG)
        bw = badge.get_width() + 10
        pygame.draw.rect(surf, C_RED, (x + CARD_W - bw - 6, y + 5, bw, 18), border_radius=3)
        surf.blit(badge, (x + CARD_W - bw - 1, y + 8))

    # Signal bars + RSSI
    bars = rssi_bars(sensor.rssi)
    draw_signal(surf, x + CARD_W - 90, y + 7, bars)
    rssi_lbl = FONT_TINY.render(f"{sensor.rssi}dBm", True, C_GREY)
    surf.blit(rssi_lbl, (x + CARD_W - 90 + 26, y + 9))

    draw_divider(surf, x + 6, y + 26, CARD_W - 12)

    # ---- Vibration section ----
    surf.blit(FONT_TINY.render("VIBRATION", True, C_GREY), (x + 8, y + 32))

    # RMS value — large
    rms_col = C_RED if alarm else C_ACCENT
    rms_str = fmt_float(sensor.vib_rms, 3)
    rms_surf = FONT_LARGE.render(rms_str, True, rms_col)
    surf.blit(rms_surf, (x + 8, y + 44))
    surf.blit(FONT_TINY.render("g RMS", True, C_GREY), (x + 8 + rms_surf.get_width() + 4, y + 58))

    # Peak + Freq on same line
    surf.blit(FONT_SMALL.render(f"Peak: {fmt_float(sensor.vib_peak, 2)} g", True, C_WHITE), (x + 140, y + 48))
    surf.blit(FONT_SMALL.render(f"Freq: {fmt_float(sensor.vib_freq, 1)} Hz", True, C_WHITE), (x + 140, y + 66))

    # RMS bar
    draw_vib_bar(surf, x + 8, y + 88, CARD_W - 16, 10, sensor.vib_rms, 1.0, alarm)
    surf.blit(FONT_TINY.render("0", True, C_GREY),    (x + 8, y + 100))
    surf.blit(FONT_TINY.render("1.0g", True, C_GREY), (x + CARD_W - 30, y + 100))

    draw_divider(surf, x + 6, y + 114, CARD_W - 12)

    # ---- Environment section ----
    surf.blit(FONT_TINY.render("ENVIRONMENT", True, C_GREY), (x + 8, y + 118))

    # Temp box
    draw_panel(surf, x + 8, y + 130, 130, 48)
    surf.blit(FONT_TINY.render("TEMP", True, C_GREY), (x + 16, y + 134))
    t_str  = fmt_float(sensor.temp, 1)
    t_surf = FONT_MED.render(t_str, True, C_YELLOW)
    surf.blit(t_surf, (x + 16, y + 147))
    surf.blit(FONT_SMALL.render("°C", True, C_GREY), (x + 16 + t_surf.get_width() + 2, y + 152))

    # Humidity box
    draw_panel(surf, x + 148, y + 130, 130, 48, )
    surf.blit(FONT_TINY.render("HUMIDITY", True, C_GREY), (x + 156, y + 134))
    h_str  = fmt_float(sensor.humidity, 1)
    h_surf = FONT_MED.render(h_str, True, C_ACCENT)
    surf.blit(h_surf, (x + 156, y + 147))
    surf.blit(FONT_SMALL.render("%RH", True, C_GREY), (x + 156 + h_surf.get_width() + 2, y + 152))

    draw_divider(surf, x + 6, y + 184, CARD_W - 12)

    # ---- Battery row ----
    surf.blit(FONT_TINY.render("BATTERY", True, C_GREY), (x + 8, y + 189))
    draw_battery(surf, x + 70, y + 189, 60, 12, sensor.battery)

    # BLE address
    addr_surf = FONT_TINY.render(sensor.address, True, C_GREY)
    surf.blit(addr_surf, (x + CARD_W - addr_surf.get_width() - 6, y + 192))

# ============================================================
# HEADER BAR
# ============================================================
def draw_header(surf, timestamp):
    pygame.draw.rect(surf, C_HEADER_BG, (0, 0, 320, 36))
    pygame.draw.line(surf, C_ACCENT, (0, 36), (320, 36), 1)

    # Logo / title
    title = FONT_MED.render("HVAC-Vibe", True, C_ACCENT)
    surf.blit(title, (8, 9))

    # Subtitle
    sub = FONT_TINY.render("Gateway Monitor", True, C_GREY)
    surf.blit(sub, (10, 26))

    # Time
    ts = FONT_TINY.render(timestamp, True, C_GREY)
    surf.blit(ts, (320 - ts.get_width() - 6, 6))

    # Online count
    online = sum(1 for s in SENSORS if s.connected)
    status_str = f"{online}/{len(SENSORS)} Online"
    status_col = C_GREEN if online == len(SENSORS) else C_YELLOW
    st = FONT_TINY.render(status_str, True, status_col)
    surf.blit(st, (320 - st.get_width() - 6, 20))

# ============================================================
# FOOTER BAR
# ============================================================
def draw_footer(surf):
    y = 460
    pygame.draw.line(surf, C_DIVIDER, (0, y), (320, y), 1)
    alarms = sum(1 for s in SENSORS if s.alarm and s.connected)
    if alarms:
        msg = FONT_TINY.render(f"  {alarms} ACTIVE ALARM{'S' if alarms > 1 else ''}  ", True, C_BG)
        mw  = msg.get_width() + 4
        pygame.draw.rect(surf, C_RED, (0, y + 2, mw, 18), border_radius=2)
        surf.blit(msg, (2, y + 4))
    else:
        surf.blit(FONT_TINY.render("All systems normal", True, C_GREEN), (8, y + 4))

    ver = FONT_TINY.render("v0.1", True, C_GREY)
    surf.blit(ver, (320 - ver.get_width() - 6, y + 4))

# ============================================================
# MAIN
# ============================================================
def main():
    global FONT_TINY, FONT_SMALL, FONT_MED, FONT_LARGE

    pygame.init()
    screen = pygame.display.set_mode((320, 480))
    pygame.display.set_caption("HVAC-Vibe")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()

    # Fonts — monospace for that SCADA feel
    FONT_TINY  = pygame.font.SysFont('monospace', 11)
    FONT_SMALL = pygame.font.SysFont('monospace', 13)
    FONT_MED   = pygame.font.SysFont('monospace', 16, bold=True)
    FONT_LARGE = pygame.font.SysFont('monospace', 28, bold=True)

    frame = 0
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()

        # Simulate live data
        for s in SENSORS:
            s.tick()

        # --- Draw ---
        screen.fill(C_BG)

        ts = time.strftime("%H:%M:%S")
        draw_header(screen, ts)

        # Two sensor cards stacked
        draw_sensor_card(screen, SENSORS[0], CARD_X, 42)
        draw_sensor_card(screen, SENSORS[1], CARD_X, 42 + CARD_H + 6)

        draw_footer(screen)

        pygame.display.flip()
        clock.tick(10)   # 10 fps is plenty for a status display
        frame += 1

if __name__ == '__main__':
    main()
