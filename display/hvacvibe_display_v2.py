#!/usr/bin/env python3
# ============================================================
# HVAC-Vibe Gateway Display  —  Landscape 480x320
# Industrial SCADA dark theme | Single sensor + 24h RMS chart
# ============================================================

import os
import sys
import math
import platform
import random
import time
import collections
import pygame

# --- Platform: framebuffer on Pi, window on Windows/Mac ---
if platform.system() not in ('Windows', 'Darwin'):
    os.environ['SDL_VIDEODRIVER'] = 'fbcon'
    os.environ['SDL_FBDEV']       = '/dev/fb1'

W, H = 480, 320

# ============================================================
# COLOUR PALETTE
# ============================================================
C_BG         = (18,  22,  28)
C_PANEL      = (28,  34,  44)
C_EDGE       = (45,  55,  70)
C_ACCENT     = (0,  160, 220)
C_GREEN      = (0,  200, 100)
C_YELLOW     = (255, 190,   0)
C_RED        = (220,  50,  50)
C_WHITE      = (220, 225, 230)
C_GREY       = (100, 110, 125)
C_DIVIDER    = (40,  50,  62)
C_CHART_LINE = (0,  180, 255)
C_CHART_FILL = (0,   80, 130)
C_CHART_GRID = (35,  45,  58)

# ============================================================
# LAYOUT CONSTANTS
# ============================================================
HEADER_H  = 36
TILES_H   = 62
TILES_Y   = HEADER_H + 2
CHART_Y   = TILES_Y + TILES_H + 4
CHART_H   = H - CHART_Y - 2          # ~216px — most of the screen
CHART_X   = 36                        # left margin for Y-axis labels
CHART_W   = W - CHART_X - 6

# 24h history: store one sample per minute = 1440 points max
# For simulation we use seconds as "minutes"
HISTORY_LEN = 480   # 480 pixels wide max, one point per pixel

# ============================================================
# SENSOR DATA  —  replace .tick() internals with real BLE data
# ============================================================
class SensorData:
    def __init__(self, name, address):
        self.name      = name
        self.address   = address
        self.connected = True
        self.rssi      = -65
        self.battery   = 78
        self.temp      = 24.3
        self.humidity  = 52.1
        self.vib_rms   = 0.42
        self.vib_peak  = 1.15
        self.vib_freq  = 48.0
        self.alarm     = False
        self._t        = 0.0
        # circular buffer for chart
        self.history   = collections.deque(
            [0.3 + 0.15 * math.sin(i * 0.15) + random.uniform(0, 0.05)
             for i in range(HISTORY_LEN)],
            maxlen=HISTORY_LEN
        )

    def tick(self):
        """Simulate live data — swap for real BLE values"""
        self._t       += 0.04
        self.vib_rms   = max(0.01, 0.42 + 0.12 * math.sin(self._t * 1.1)
                             + 0.06 * math.sin(self._t * 3.7)
                             + random.uniform(-0.02, 0.02))
        self.vib_peak  = self.vib_rms * 2.6 + random.uniform(-0.04, 0.04)
        self.vib_freq  = 48.0 + 2.0 * math.sin(self._t * 0.4)
        self.temp      = 24.3 + 0.8 * math.sin(self._t * 0.08)
        self.humidity  = 52.1 + 1.5 * math.sin(self._t * 0.05)
        self.rssi      = int(-65 + 6 * math.sin(self._t * 0.25))
        self.alarm     = self.vib_rms > 0.62

    def push_history(self):
        """Call once per minute (or per sample interval) to log chart data"""
        self.history.append(self.vib_rms)

SENSOR = SensorData("UNIT-01", "AA:BB:CC:DD:EE:01")

# ============================================================
# HELPERS
# ============================================================
def bat_color(pct):
    if pct > 50: return (0, 200, 100)
    if pct > 20: return (255, 190, 0)
    return (220, 50, 50)

def rssi_bars(rssi):
    if rssi >= -60: return 4
    if rssi >= -70: return 3
    if rssi >= -80: return 2
    if rssi >= -90: return 1
    return 0

# ============================================================
# DRAWING
# ============================================================
def draw_header(surf, s):
    # Background
    pygame.draw.rect(surf, C_PANEL, (0, 0, W, HEADER_H))
    pygame.draw.line(surf, C_ACCENT, (0, HEADER_H), (W, HEADER_H), 1)

    # App title
    surf.blit(FONT_MED.render("HVAC-Vibe", True, C_ACCENT), (8, 4))

    # Status dot + sensor name
    col = C_GREEN if s.connected else C_RED
    pygame.draw.circle(surf, col, (115, HEADER_H // 2), 5)
    pygame.draw.circle(surf, C_EDGE, (115, HEADER_H // 2), 5, 1)
    surf.blit(FONT_MED.render(s.name, True, C_WHITE), (124, 4))

    # Connected / Disconnected label
    lbl = "Connected" if s.connected else "No Signal"
    surf.blit(FONT_TINY.render(lbl, True, col), (124, 22))

    # Signal bars
    bars = rssi_bars(s.rssi)
    bw, gap, max_bh = 5, 2, 14
    for i in range(4):
        bh = int(max_bh * (i + 1) / 4)
        bx = 225 + i * (bw + gap)
        by = HEADER_H // 2 - bh // 2 + 2
        pygame.draw.rect(surf, C_ACCENT if i < bars else C_DIVIDER,
                         (bx, by, bw, bh), border_radius=1)
    rssi_s = FONT_TINY.render(f"{s.rssi}dBm", True, C_GREY)
    surf.blit(rssi_s, (252, 12))

    # Battery
    pct = s.battery
    bc  = bat_color(pct)
    bx, by, bww, bhh = 310, 10, 44, 16
    pygame.draw.rect(surf, C_EDGE, (bx, by, bww, bhh), border_radius=2)
    fw = max(2, int((bww - 4) * pct / 100))
    pygame.draw.rect(surf, bc, (bx + 2, by + 2, fw, bhh - 4), border_radius=1)
    pygame.draw.rect(surf, C_EDGE, (bx + bww, by + 5, 3, 6), border_radius=1)
    bat_lbl = FONT_TINY.render(f"{pct}%", True, bc)
    surf.blit(bat_lbl, (bx + bww + 6, by + 2))

    # Alarm badge
    if s.alarm and s.connected:
        badge = FONT_TINY.render(" ! ALARM ", True, C_BG)
        bw2 = badge.get_width() + 4
        pygame.draw.rect(surf, C_RED, (W - bw2 - 4, 8, bw2, 18), border_radius=3)
        surf.blit(badge, (W - bw2 - 2, 11))
    else:
        # Clock top-right
        ts = FONT_TINY.render(time.strftime("%H:%M:%S"), True, C_GREY)
        surf.blit(ts, (W - ts.get_width() - 6, 12))


def draw_tiles(surf, s):
    """4 metric tiles in one compact row"""
    tile_defs = [
        ("VIB RMS",  f"{s.vib_rms:.3f}",  "g",    C_RED if s.alarm else C_ACCENT),
        ("PEAK",     f"{s.vib_peak:.2f}",  "g",    C_YELLOW),
        ("TEMP",     f"{s.temp:.1f}",      "\u00b0C", C_YELLOW),
        ("HUMIDITY", f"{s.humidity:.1f}",  "%RH",  C_ACCENT),
    ]
    tile_w = W // 4
    for i, (label, value, unit, col) in enumerate(tile_defs):
        tx = i * tile_w
        ty = TILES_Y

        # Background
        pygame.draw.rect(surf, C_PANEL, (tx + 2, ty, tile_w - 4, TILES_H), border_radius=4)
        pygame.draw.rect(surf, C_EDGE,  (tx + 2, ty, tile_w - 4, TILES_H), width=1, border_radius=4)

        # Label
        surf.blit(FONT_TINY.render(label, True, C_GREY), (tx + 8, ty + 5))

        # Value
        val_surf = FONT_MED.render(value, True, col)
        surf.blit(val_surf, (tx + 8, ty + 20))

        # Unit
        surf.blit(FONT_TINY.render(unit, True, C_GREY),
                  (tx + 8 + val_surf.get_width() + 3, ty + 26))


def draw_chart(surf, s):
    """Line chart with filled area — vibration RMS history"""
    cx, cy = CHART_X, CHART_Y
    cw, ch = CHART_W, CHART_H

    # Chart background
    pygame.draw.rect(surf, C_PANEL, (cx, cy, cw, ch), border_radius=4)
    pygame.draw.rect(surf, C_EDGE,  (cx, cy, cw, ch), width=1, border_radius=4)

    # Title
    surf.blit(FONT_TINY.render("VIBRATION RMS  —  LAST 24H", True, C_GREY), (cx + 8, cy + 5))

    # Plot area (inset)
    px, py = cx + 4, cy + 18
    pw, ph = cw - 8, ch - 30

    # Y-axis range
    hist   = list(s.history)
    y_max  = max(1.0, max(hist) * 1.15) if hist else 1.0
    y_max  = round(y_max * 4) / 4       # round to nearest 0.25
    y_min  = 0.0

    # Grid lines + Y labels (4 lines)
    for gi in range(5):
        gy_val = y_min + (y_max - y_min) * gi / 4
        gy_px  = py + ph - int(ph * gi / 4)
        pygame.draw.line(surf, C_CHART_GRID, (px, gy_px), (px + pw, gy_px), 1)
        lbl = FONT_TINY.render(f"{gy_val:.2f}", True, C_GREY)
        surf.blit(lbl, (cx, gy_px - 5))

    # Alarm threshold line at 0.6g
    alarm_thresh = 0.6
    if alarm_thresh <= y_max:
        ay = py + ph - int(ph * (alarm_thresh - y_min) / (y_max - y_min))
        pygame.draw.line(surf, C_RED, (px, ay), (px + pw, ay), 1)
        surf.blit(FONT_TINY.render("ALM", True, C_RED), (px + pw - 22, ay - 11))

    # X-axis labels
    surf.blit(FONT_TINY.render("00:00", True, C_GREY), (px,               py + ph + 2))
    surf.blit(FONT_TINY.render("12:00", True, C_GREY), (px + pw // 2 - 12, py + ph + 2))
    surf.blit(FONT_TINY.render("now",   True, C_GREY), (px + pw - 18,     py + ph + 2))

    # Build pixel points
    n      = len(hist)
    if n < 2:
        return

    points = []
    for i, val in enumerate(hist):
        x = px + int(i * pw / (HISTORY_LEN - 1))
        y = py + ph - int(ph * (val - y_min) / (y_max - y_min))
        y = max(py, min(py + ph, y))
        points.append((x, y))

    # Filled area under line
    if len(points) >= 2:
        poly = [(px, py + ph)] + points + [(points[-1][0], py + ph)]
        fill_surf = pygame.Surface((pw + 8, ph + 4), pygame.SRCALPHA)
        offset_x  = px - 4
        offset_y  = py
        adj_poly  = [(p[0] - offset_x, p[1] - offset_y) for p in poly]
        pygame.draw.polygon(fill_surf, (*C_CHART_FILL, 120), adj_poly)
        surf.blit(fill_surf, (offset_x, offset_y))

        # Line on top
        pygame.draw.lines(surf, C_CHART_LINE, False, points, 2)

        # Current value dot
        last = points[-1]
        pygame.draw.circle(surf, C_WHITE,      last, 4)
        pygame.draw.circle(surf, C_CHART_LINE, last, 3)

        # Current value label
        cur_lbl = FONT_TINY.render(f"{hist[-1]:.3f}g", True, C_WHITE)
        lx = min(last[0] + 5, px + pw - cur_lbl.get_width() - 2)
        surf.blit(cur_lbl, (lx, last[1] - 14))


def draw_y_axis_label(surf):
    """Rotated Y-axis label"""
    lbl  = FONT_TINY.render("g", True, C_GREY)
    surf.blit(lbl, (2, CHART_Y + CHART_H // 2))


# ============================================================
# MAIN LOOP
# ============================================================
def main():
    global FONT_TINY, FONT_SMALL, FONT_MED, FONT_LARGE

    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("HVAC-Vibe")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()

    FONT_TINY  = pygame.font.SysFont('monospace', 11)
    FONT_SMALL = pygame.font.SysFont('monospace', 13)
    FONT_MED   = pygame.font.SysFont('monospace', 15, bold=True)
    FONT_LARGE = pygame.font.SysFont('monospace', 26, bold=True)

    # Push a history sample every N frames (simulate 1 per "minute")
    HISTORY_INTERVAL = 30   # frames — reduce for faster simulation
    frame = 0

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()

        SENSOR.tick()
        if frame % HISTORY_INTERVAL == 0:
            SENSOR.push_history()

        # --- Render ---
        screen.fill(C_BG)
        draw_header(screen, SENSOR)
        draw_tiles(screen, SENSOR)
        draw_chart(screen, SENSOR)
        draw_y_axis_label(screen)
        pygame.display.flip()

        clock.tick(15)
        frame += 1


if __name__ == '__main__':
    main()
