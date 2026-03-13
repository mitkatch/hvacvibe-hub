#!/usr/bin/env python3
# ============================================================
# HVAC-Vibe Gateway Display  —  Landscape 480x320
# Industrial SCADA dark theme | Single sensor + daily RMS chart
# Chart: fixed 00:00-23:59, draws up to current time only
# ============================================================

import os
import sys
import math
import platform
import random
import time
import datetime
import collections
import struct
import pygame

W, H = 480, 320

# --- Platform detection ---
ON_PI = platform.system() not in ('Windows', 'Darwin')

if ON_PI:
    # SDL2 dropped fbcon — use offscreen rendering then blit to fb1
    os.environ['SDL_VIDEODRIVER'] = 'offscreen'

FB_DEVICE = '/dev/fb1'

def flush_to_fb(surface):
    """Rotate landscape 480x320 surface to portrait 320x480 and write to fb1."""
    # fb1 is physically 320x480 portrait — rotate our landscape render 90 degrees
    rotated = pygame.transform.rotate(surface, 90)
    raw = pygame.image.tostring(rotated, 'RGB')
    buf = bytearray(len(raw) // 3 * 2)
    idx = 0
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i+1], raw[i+2]
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        buf[idx]   = rgb565 & 0xFF
        buf[idx+1] = (rgb565 >> 8) & 0xFF
        idx += 2
    with open(FB_DEVICE, 'wb') as f:
        f.write(buf)

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
C_CHART_FILL = (0,   70, 120)
C_CHART_GRID = (38,  48,  62)
C_NOW_LINE   = (255, 220,  60)   # vertical "now" marker

# ============================================================
# LAYOUT  — carefully aligned so tiles and chart line up
# ============================================================
HEADER_H = 36
TILES_Y  = HEADER_H + 3
TILES_H  = 60

# Y-axis label column width (left of chart panel)
YAXIS_W  = 32

# Chart panel spans full width minus Y-axis column
CHART_PX = YAXIS_W          # panel left edge
CHART_PY = TILES_Y + TILES_H + 4
CHART_PW = W - YAXIS_W - 2  # panel width  (fills to right edge)
CHART_PH = H - CHART_PY - 2 # panel height (fills to bottom)

# Plot area inside the panel (inset padding)
PAD_L, PAD_R, PAD_T, PAD_B = 6, 8, 18, 16
PLOT_X = CHART_PX + PAD_L
PLOT_Y = CHART_PY + PAD_T
PLOT_W = CHART_PW - PAD_L - PAD_R
PLOT_H = CHART_PH - PAD_T - PAD_B

# Tiles span the full width but right-aligned to match chart right edge
TILE_TOTAL_W = W - 2         # tiles row total width (2px margin each side)
TILE_X0      = 1

# ============================================================
# HISTORY  — keyed by minute-of-day (0..1439)
# Each entry: (minute_of_day, rms_value)
# On real system replace with data from BLE/MQTT pipeline
# ============================================================
MINUTES_PER_DAY = 1440

class DailyHistory:
    """Stores one RMS value per minute for the current day (00:00-23:59)."""
    def __init__(self):
        # dict: minute_index -> float
        self.data = {}
        self._sim_fill()   # pre-fill with simulated past data

    def _sim_fill(self):
        """Pre-fill from midnight up to current time with simulated data."""
        now   = datetime.datetime.now()
        cur_m = now.hour * 60 + now.minute
        t     = 0.0
        for m in range(0, cur_m):
            t += 0.15
            val = max(0.01, 0.38 + 0.12 * math.sin(t * 0.9)
                      + 0.06 * math.sin(t * 3.1)
                      + random.uniform(0, 0.03))
            self.data[m] = val

    def push(self, minute_index, value):
        self.data[minute_index] = value

    def get_points(self, plot_x, plot_y, plot_w, plot_h, y_min, y_max):
        """
        Return list of (px, py) pixel coords for all stored minutes.
        X axis: 0 = 00:00, plot_w = 23:59
        Only draws up to current minute.
        """
        if not self.data:
            return []
        pts = []
        for minute, val in sorted(self.data.items()):
            x = plot_x + int(minute * plot_w / (MINUTES_PER_DAY - 1))
            y = plot_y + plot_h - int(plot_h * (val - y_min) / max(0.001, y_max - y_min))
            y = max(plot_y, min(plot_y + plot_h, y))
            pts.append((x, y))
        return pts

# ============================================================
# SENSOR DATA
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
        self.alarm     = False
        self._t        = 0.0
        self.history   = DailyHistory()
        self._last_min = -1

    def tick(self):
        self._t     += 0.04
        self.vib_rms = max(0.01, 0.42 + 0.12 * math.sin(self._t * 1.1)
                           + 0.06 * math.sin(self._t * 3.7)
                           + random.uniform(-0.02, 0.02))
        self.vib_peak  = self.vib_rms * 2.6 + random.uniform(-0.04, 0.04)
        self.temp      = 24.3 + 0.8  * math.sin(self._t * 0.08)
        self.humidity  = 52.1 + 1.5  * math.sin(self._t * 0.05)
        self.rssi      = int(-65 + 6 * math.sin(self._t * 0.25))
        self.alarm     = self.vib_rms > 0.62

        # Push to daily history once per minute
        now = datetime.datetime.now()
        cur_min = now.hour * 60 + now.minute
        if cur_min != self._last_min:
            self.history.push(cur_min, self.vib_rms)
            self._last_min = cur_min

SENSOR = SensorData("UNIT-01", "AA:BB:CC:DD:EE:01")

# ============================================================
# HELPERS
# ============================================================
def bat_color(pct):
    if pct > 50: return C_GREEN
    if pct > 20: return C_YELLOW
    return C_RED

def rssi_bars(rssi):
    if rssi >= -60: return 4
    if rssi >= -70: return 3
    if rssi >= -80: return 2
    if rssi >= -90: return 1
    return 0

# ============================================================
# HEADER
# ============================================================
def draw_header(surf, s):
    pygame.draw.rect(surf, C_PANEL, (0, 0, W, HEADER_H))
    pygame.draw.line(surf, C_ACCENT, (0, HEADER_H), (W, HEADER_H), 1)

    # Title
    surf.blit(FONT_MED.render("HVAC-Vibe", True, C_ACCENT), (8, 4))

    # Status dot + name
    col = C_GREEN if s.connected else C_RED
    pygame.draw.circle(surf, col,    (116, HEADER_H // 2), 5)
    pygame.draw.circle(surf, C_EDGE, (116, HEADER_H // 2), 5, 1)
    surf.blit(FONT_MED.render(s.name, True, C_WHITE), (125, 4))
    lbl = "Connected" if s.connected else "No Signal"
    surf.blit(FONT_TINY.render(lbl, True, col), (125, 22))

    # Signal bars
    bw, gap, max_bh = 5, 2, 14
    for i in range(4):
        bh = int(max_bh * (i + 1) / 4)
        bx = 228 + i * (bw + gap)
        by = HEADER_H // 2 - bh // 2 + 2
        pygame.draw.rect(surf, C_ACCENT if i < rssi_bars(s.rssi) else C_DIVIDER,
                         (bx, by, bw, bh), border_radius=1)
    surf.blit(FONT_TINY.render(f"{s.rssi}dBm", True, C_GREY), (256, 12))

    # Battery
    bc = bat_color(s.battery)
    bx, by, bww, bhh = 312, 11, 42, 14
    pygame.draw.rect(surf, C_EDGE, (bx, by, bww, bhh), border_radius=2)
    fw = max(2, int((bww - 4) * s.battery / 100))
    pygame.draw.rect(surf, bc, (bx + 2, by + 2, fw, bhh - 4), border_radius=1)
    pygame.draw.rect(surf, C_EDGE, (bx + bww, by + 4, 3, 6), border_radius=1)
    surf.blit(FONT_TINY.render(f"{s.battery}%", True, bc), (bx + bww + 6, by + 1))

    # Clock or alarm — top right
    if s.alarm and s.connected:
        badge = FONT_TINY.render(" ! ALARM ", True, C_BG)
        bw2 = badge.get_width() + 4
        pygame.draw.rect(surf, C_RED, (W - bw2 - 4, 8, bw2, 18), border_radius=3)
        surf.blit(badge, (W - bw2 - 2, 11))
    else:
        ts = FONT_TINY.render(time.strftime("%H:%M:%S"), True, C_GREY)
        surf.blit(ts, (W - ts.get_width() - 6, 12))

# ============================================================
# TILES  — aligned to TILE_X0 .. TILE_X0+TILE_TOTAL_W
# ============================================================
def draw_tiles(surf, s):
    tile_defs = [
        ("VIB RMS", f"{s.vib_rms:.3f}", "g",   C_RED if s.alarm else C_ACCENT),
        ("PEAK",    f"{s.vib_peak:.2f}", "g",   C_YELLOW),
        ("TEMP",    f"{s.temp:.1f}",     "\u00b0C", C_YELLOW),
        ("HUMIDITY",f"{s.humidity:.1f}", "%RH", C_ACCENT),
    ]
    n      = len(tile_defs)
    tile_w = TILE_TOTAL_W // n

    for i, (label, value, unit, col) in enumerate(tile_defs):
        tx = TILE_X0 + i * tile_w
        ty = TILES_Y
        tw = tile_w if i < n - 1 else (TILE_TOTAL_W - tile_w * (n - 1))  # last tile fills remainder

        pygame.draw.rect(surf, C_PANEL, (tx + 1, ty, tw - 2, TILES_H), border_radius=4)
        pygame.draw.rect(surf, C_EDGE,  (tx + 1, ty, tw - 2, TILES_H), width=1, border_radius=4)

        # Label top-left
        surf.blit(FONT_TINY.render(label, True, C_GREY), (tx + 7, ty + 5))

        # Value
        val_s = FONT_MED.render(value, True, col)
        surf.blit(val_s, (tx + 7, ty + 20))

        # Unit next to value
        surf.blit(FONT_TINY.render(unit, True, C_GREY),
                  (tx + 7 + val_s.get_width() + 3, ty + 26))

# ============================================================
# CHART  — time-anchored daily chart 00:00 → 23:59
# ============================================================
def draw_chart(surf, s):
    now     = datetime.datetime.now()
    cur_min = now.hour * 60 + now.minute

    # Panel background — aligned to CHART_PX
    pygame.draw.rect(surf, C_PANEL, (CHART_PX, CHART_PY, CHART_PW, CHART_PH), border_radius=4)
    pygame.draw.rect(surf, C_EDGE,  (CHART_PX, CHART_PY, CHART_PW, CHART_PH), width=1, border_radius=4)

    # Title inside panel
    title = f"VIB RMS  —  {now.strftime('%Y-%m-%d')}"
    surf.blit(FONT_TINY.render(title, True, C_GREY), (CHART_PX + 8, CHART_PY + 5))

    px, py = PLOT_X, PLOT_Y
    pw, ph = PLOT_W, PLOT_H

    # --- Y axis range ---
    vals  = list(s.history.data.values())
    y_max = max(1.0, max(vals) * 1.15) if vals else 1.0
    y_max = math.ceil(y_max * 4) / 4    # round up to nearest 0.25
    y_min = 0.0

    # --- Y axis labels + horizontal grid lines (4 divisions) ---
    for gi in range(5):
        gy_val = y_min + (y_max - y_min) * gi / 4
        gy_px  = py + ph - int(ph * gi / 4)
        # grid line across plot area
        pygame.draw.line(surf, C_CHART_GRID, (px, gy_px), (px + pw, gy_px), 1)
        # Y label in the left column (right-aligned)
        lbl = FONT_TINY.render(f"{gy_val:.2f}", True, C_GREY)
        surf.blit(lbl, (CHART_PX - lbl.get_width() - 2, gy_px - 6))

    # --- Alarm threshold ---
    thresh = 0.6
    if thresh <= y_max:
        ay = py + ph - int(ph * thresh / y_max)
        pygame.draw.line(surf, C_RED, (px, ay), (px + pw, ay), 1)
        surf.blit(FONT_TINY.render("ALM", True, C_RED), (px + pw - 24, ay - 12))

    # --- X axis time labels: 00:00, 06:00, 12:00, 18:00, 23:59 ---
    x_labels = [(0, "00:00"), (360, "06:00"), (720, "12:00"), (1080, "18:00"), (1439, "24:00")]
    for minute, label in x_labels:
        lx = px + int(minute * pw / (MINUTES_PER_DAY - 1))
        # vertical tick
        pygame.draw.line(surf, C_CHART_GRID, (lx, py + ph), (lx, py + ph + 3), 1)
        lbl = FONT_TINY.render(label, True, C_GREY)
        # centre label on tick, keep within bounds
        lx_txt = max(px, min(lx - lbl.get_width() // 2, px + pw - lbl.get_width()))
        surf.blit(lbl, (lx_txt, py + ph + 4))

    # --- "Now" vertical line ---
    now_x = px + int(cur_min * pw / (MINUTES_PER_DAY - 1))
    pygame.draw.line(surf, C_NOW_LINE, (now_x, py), (now_x, py + ph), 1)
    now_lbl = FONT_TINY.render("NOW", True, C_NOW_LINE)
    # place label left of line if near right edge
    nlx = now_x + 3 if now_x + now_lbl.get_width() + 6 < px + pw else now_x - now_lbl.get_width() - 3
    surf.blit(now_lbl, (nlx, py + 1))

    # --- Grey future area (NOW → 23:59) ---
    future_x = now_x + 1
    future_w = px + pw - future_x
    if future_w > 0:
        future_surf = pygame.Surface((future_w, ph), pygame.SRCALPHA)
        future_surf.fill((255, 255, 255, 12))
        surf.blit(future_surf, (future_x, py))

    # --- Data line + fill ---
    points = s.history.get_points(px, py, pw, ph, y_min, y_max)

    if len(points) >= 2:
        # Filled area
        poly = [(px, py + ph)] + points + [(points[-1][0], py + ph)]
        fill_surf = pygame.Surface((pw + 2, ph + 2), pygame.SRCALPHA)
        adj = [(p[0] - px, p[1] - py) for p in poly]
        pygame.draw.polygon(fill_surf, (*C_CHART_FILL, 140), adj)
        surf.blit(fill_surf, (px, py))

        # Line
        pygame.draw.lines(surf, C_CHART_LINE, False, points, 2)

        # Current value dot at last point
        last = points[-1]
        pygame.draw.circle(surf, C_BG,         last, 5)
        pygame.draw.circle(surf, C_CHART_LINE, last, 4)
        pygame.draw.circle(surf, C_WHITE,       last, 2)

        # Value label near dot
        cur_lbl = FONT_TINY.render(f"{vals[-1]:.3f}g", True, C_WHITE)
        lx = last[0] + 6
        if lx + cur_lbl.get_width() > px + pw:
            lx = last[0] - cur_lbl.get_width() - 4
        surf.blit(cur_lbl, (lx, last[1] - 13))

    elif len(points) == 1:
        pygame.draw.circle(surf, C_CHART_LINE, points[0], 3)

# ============================================================
# Y AXIS UNIT LABEL  (left of chart, vertical)
# ============================================================
def draw_yaxis_unit(surf):
    lbl = FONT_TINY.render("g", True, C_GREY)
    surf.blit(lbl, (2, CHART_PY + CHART_PH // 2 - 5))

# ============================================================
# MAIN
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

    frame = 0
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()

        SENSOR.tick()

        screen.fill(C_BG)
        draw_header(screen, SENSOR)
        draw_tiles(screen, SENSOR)
        draw_chart(screen, SENSOR)
        draw_yaxis_unit(screen)

        if ON_PI:
            flush_to_fb(screen)
        else:
            pygame.display.flip()

        clock.tick(15)
        frame += 1

if __name__ == '__main__':
    main()
