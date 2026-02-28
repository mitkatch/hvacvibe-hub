#!/usr/bin/env python3
"""
Display — pygame LCD renderer.
Reads data_store directly, no network needed.
Adaptive layout based on sensor count:
  1 sensor  → full screen with chart
  2 sensors → split screen, chart per sensor
  3-4       → 2x2 grid, tiles + sparkline
  5+        → list view
"""
import os
import sys
import math
import time
import datetime
import platform
import threading
import logging
import pygame

from data_store import store, SensorState
from config import DISPLAY, ALARMS, ON_PI
import cloud_sync

log = logging.getLogger('display')

if ON_PI:
    os.environ['SDL_VIDEODRIVER'] = 'offscreen'

W = DISPLAY["width"]
H = DISPLAY["height"]

# ── Palette ───────────────────────────────────────────────────
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
C_NOW_LINE   = (255, 220,  60)
C_WARN       = (255, 140,   0)

MINUTES_PER_DAY = 1440


# ── Framebuffer flush ─────────────────────────────────────────
def flush_to_fb(surface):
    import numpy as np
    rotated = pygame.transform.rotate(surface, DISPLAY["rotate"])
    raw = pygame.image.tostring(rotated, 'RGB')
    px  = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
    r   = px[:, 0].astype(np.uint16)
    g   = px[:, 1].astype(np.uint16)
    b   = px[:, 2].astype(np.uint16)
    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    with open(DISPLAY["fb_device"], 'wb') as f:
        f.write(rgb565.astype('<u2').tobytes())


# ── Helpers ───────────────────────────────────────────────────
def rssi_bars(rssi: int) -> int:
    if rssi >= -60: return 4
    if rssi >= -70: return 3
    if rssi >= -80: return 2
    if rssi >= -90: return 1
    return 0

def bat_color(pct: int):
    if pct > 50: return C_GREEN
    if pct > 20: return C_YELLOW
    return C_RED

def alarm_color(s: SensorState):
    if s.alarm: return C_RED
    if s.warn:  return C_WARN
    return C_ACCENT


# ── Drawing primitives ────────────────────────────────────────
def draw_signal_bars(surf, x, y, rssi, h=14):
    bars = rssi_bars(rssi)
    bw, gap = 5, 2
    for i in range(4):
        bh = int(h * (i + 1) / 4)
        col = C_ACCENT if i < bars else C_DIVIDER
        pygame.draw.rect(surf, col,
                         (x + i * (bw + gap), y + h - bh, bw, bh),
                         border_radius=1)

def draw_battery(surf, x, y, pct, w=36, h=14):
    col = bat_color(pct)
    pygame.draw.rect(surf, C_EDGE, (x, y, w, h), border_radius=2)
    fw = max(2, int((w - 4) * pct / 100))
    pygame.draw.rect(surf, col, (x+2, y+2, fw, h-4), border_radius=1)
    pygame.draw.rect(surf, C_EDGE, (x+w, y+4, 3, h-8), border_radius=1)

def draw_conn_dot(surf, x, y, connected):
    col = C_GREEN if connected else C_RED
    pygame.draw.circle(surf, col, (x, y), 5)
    pygame.draw.circle(surf, C_EDGE, (x, y), 5, 1)


# ── Chart ─────────────────────────────────────────────────────
def draw_chart(surf, sensor: SensorState,
               px, py, pw, ph,
               ft, show_title=True):
    """Draw vibration RMS daily chart in given plot rect."""
    now     = datetime.datetime.now()
    cur_min = now.hour * 60 + now.minute

    # Background
    pygame.draw.rect(surf, C_PANEL,
                     (px - 4, py - (20 if show_title else 4),
                      pw + 8, ph + (24 if show_title else 8)),
                     border_radius=4)
    pygame.draw.rect(surf, C_EDGE,
                     (px - 4, py - (20 if show_title else 4),
                      pw + 8, ph + (24 if show_title else 8)),
                     width=1, border_radius=4)

    if show_title:
        surf.blit(ft.render(
            f"VIB RMS  {now.strftime('%Y-%m-%d')}",
            True, C_GREY), (px, py - 16))

    # Y range
    hist   = sensor.history_list()
    vals   = [v for _, v in hist]
    y_max  = math.ceil(max(1.0, max(vals) * 1.15 if vals else 1.0) * 4) / 4
    y_min  = 0.0

    # Grid + Y labels
    for i in range(5):
        gy_val = y_min + (y_max - y_min) * i / 4
        gy     = py + ph - int(ph * i / 4)
        pygame.draw.line(surf, C_CHART_GRID, (px, gy), (px + pw, gy), 1)
        lbl = ft.render(f"{gy_val:.2f}", True, C_GREY)
        surf.blit(lbl, (px - lbl.get_width() - 3, gy - 6))

    # Alarm threshold
    if ALARMS["vib_rms_alarm"] <= y_max:
        ay = py + ph - int(ph * ALARMS["vib_rms_alarm"] / y_max)
        pygame.draw.line(surf, C_RED, (px, ay), (px + pw, ay), 1)
        surf.blit(ft.render("ALM", True, C_RED),
                  (px + pw - 24, ay - 11))

    # X labels
    for minute, label in [(0,"00:00"),(360,"06:00"),
                           (720,"12:00"),(1080,"18:00"),(1439,"24:00")]:
        lx  = px + int(minute * pw / (MINUTES_PER_DAY - 1))
        lbl = ft.render(label, True, C_GREY)
        pygame.draw.line(surf, C_CHART_GRID,
                         (lx, py + ph), (lx, py + ph + 3), 1)
        surf.blit(lbl, (max(px, min(lx - lbl.get_width()//2,
                                    px + pw - lbl.get_width())),
                        py + ph + 4))

    # NOW line
    now_x = px + int(cur_min * pw / (MINUTES_PER_DAY - 1))
    pygame.draw.line(surf, C_NOW_LINE,
                     (now_x, py), (now_x, py + ph), 1)
    now_lbl = ft.render("NOW", True, C_NOW_LINE)
    nlx = now_x + 3 if now_x + now_lbl.get_width() + 6 < px + pw \
          else now_x - now_lbl.get_width() - 3
    surf.blit(now_lbl, (nlx, py + 1))

    # Future dimmed
    future_w = px + pw - now_x - 1
    if future_w > 0:
        fs = pygame.Surface((future_w, ph), pygame.SRCALPHA)
        fs.fill((255, 255, 255, 12))
        surf.blit(fs, (now_x + 1, py))

    # Data line
    if len(hist) < 2:
        return

    points = []
    for minute, rms in hist:
        x = px + int(minute * pw / (MINUTES_PER_DAY - 1))
        y = py + ph - int(ph * (rms - y_min) / max(0.001, y_max - y_min))
        points.append((x, max(py, min(py + ph, y))))

    if len(points) >= 2:
        poly = [(px, py + ph)] + points + [(points[-1][0], py + ph)]
        fs   = pygame.Surface((pw + 2, ph + 2), pygame.SRCALPHA)
        pygame.draw.polygon(fs, (*C_CHART_FILL, 140),
                            [(p[0]-px, p[1]-py) for p in poly])
        surf.blit(fs, (px, py))
        pygame.draw.lines(surf, C_CHART_LINE, False, points, 2)

        last = points[-1]
        pygame.draw.circle(surf, C_BG, last, 5)
        pygame.draw.circle(surf, C_CHART_LINE, last, 4)
        pygame.draw.circle(surf, C_WHITE, last, 2)

        cur_lbl = ft.render(f"{vals[-1]:.3f}g", True, C_WHITE)
        lx = last[0] + 6
        if lx + cur_lbl.get_width() > px + pw:
            lx = last[0] - cur_lbl.get_width() - 4
        surf.blit(cur_lbl, (lx, last[1] - 13))


# ── Sparkline (mini chart, no labels) ────────────────────────
def draw_sparkline(surf, sensor: SensorState, x, y, w, h):
    hist = sensor.history_list()
    if len(hist) < 2:
        return
    vals  = [v for _, v in hist]
    y_max = max(vals) * 1.1 or 1.0
    now   = datetime.datetime.now()
    cur_m = now.hour * 60 + now.minute

    pygame.draw.rect(surf, C_PANEL, (x, y, w, h), border_radius=2)

    points = []
    for minute, rms in hist:
        px2 = x + int(minute * w / (MINUTES_PER_DAY - 1))
        py2 = y + h - int(h * rms / y_max)
        points.append((px2, max(y, min(y + h, py2))))

    if len(points) >= 2:
        pygame.draw.lines(surf, C_CHART_LINE, False, points, 1)

    # NOW marker
    nx = x + int(cur_m * w / (MINUTES_PER_DAY - 1))
    pygame.draw.line(surf, C_NOW_LINE, (nx, y), (nx, y + h), 1)


# ── Layout: 1 sensor ─────────────────────────────────────────
def draw_single(surf, sensor: SensorState, fonts):
    ft, fm = fonts["tiny"], fonts["med"]

    HEADER_H = 36
    TILES_H  = 63
    YAXIS_W  = 36
    TILES_Y  = HEADER_H + 3
    CHART_PY = TILES_Y + TILES_H + 4
    CHART_PH = H - CHART_PY - 18   # leave room for x-axis labels
    PLOT_X   = YAXIS_W + 4
    PLOT_W   = W - YAXIS_W - 10
    PLOT_Y   = CHART_PY + 20
    PLOT_H   = CHART_PH - 20

    # Header
    pygame.draw.rect(surf, C_PANEL, (0, 0, W, HEADER_H))
    pygame.draw.line(surf, C_ACCENT, (0, HEADER_H), (W, HEADER_H), 1)
    surf.blit(fm.render("HVAC-Vibe", True, C_ACCENT), (8, 4))
    draw_conn_dot(surf, 116, HEADER_H//2, sensor.connected)
    col = C_GREEN if sensor.connected else C_RED
    surf.blit(fm.render(sensor.name, True, C_WHITE), (125, 4))
    surf.blit(ft.render("Connected" if sensor.connected else "No Signal",
                         True, col), (125, 22))
    draw_signal_bars(surf, 228, HEADER_H//2 - 7, sensor.rssi)
    surf.blit(ft.render(f"{sensor.rssi}dBm", True, C_GREY), (256, 12))
    draw_battery(surf, 312, 11, sensor.battery)
    surf.blit(ft.render(f"{sensor.battery}%", True, bat_color(sensor.battery)),
              (356, 12))

    if sensor.alarm:
        badge = fm.render(" ! ALARM ", True, C_BG)
        bw2 = badge.get_width() + 4
        pygame.draw.rect(surf, C_RED, (W - bw2 - 4, 8, bw2, 18), border_radius=3)
        surf.blit(badge, (W - bw2 - 2, 11))
    else:
        ts = ft.render(time.strftime("%H:%M:%S"), True, C_GREY)
        surf.blit(ts, (W - ts.get_width() - 6, 12))

    # Tiles
    tile_defs = [
        ("VIB RMS",  f"{sensor.vib_rms:.3f}",  "g",        alarm_color(sensor)),
        ("PEAK",     f"{sensor.vib_peak:.2f}",  "g",        C_YELLOW),
        ("TEMP",     f"{sensor.temp:.1f}",      "\u00b0C", C_YELLOW),
        ("HUMIDITY", f"{sensor.humidity:.1f}",  "%RH",      C_ACCENT),
        ("PRESSURE", f"{sensor.pressure:.0f}",  "hPa",      C_ACCENT),
    ]
    tw = (W - 2) // 5
    for i, (label, value, unit, col) in enumerate(tile_defs):
        tx = 1 + i * tw
        pygame.draw.rect(surf, C_PANEL, (tx+1, TILES_Y, tw-2, TILES_H),
                         border_radius=4)
        pygame.draw.rect(surf, C_EDGE,  (tx+1, TILES_Y, tw-2, TILES_H),
                         width=1, border_radius=4)
        surf.blit(ft.render(label, True, C_GREY), (tx+7, TILES_Y+5))
        vs = fm.render(value, True, col)
        surf.blit(vs, (tx+7, TILES_Y+20))
        surf.blit(ft.render(unit, True, C_GREY),
                  (tx+7+vs.get_width()+3, TILES_Y+26))

    # Chart
    draw_chart(surf, sensor, PLOT_X, PLOT_Y, PLOT_W, PLOT_H, ft,
               show_title=True)

    # Y axis label
    surf.blit(ft.render("g", True, C_GREY), (2, CHART_PY + CHART_PH//2))

    # Cloud sync status (bottom-left, tiny)
    cs = cloud_sync.get_status()
    if cs["wifi"]:
        sync_txt = f"SYNC OK {cs['records_sent_today']}rec"
        sync_col = C_GREEN
    elif cs["last_error"]:
        sync_txt = "SYNC ERR"
        sync_col = C_RED
    else:
        sync_txt = "NO WIFI"
        sync_col = C_GREY
    surf.blit(ft.render(sync_txt, True, sync_col), (PLOT_X, H - 12))


# ── Layout: 2 sensors ────────────────────────────────────────
def draw_dual(surf, sensors: list[SensorState], fonts):
    ft, fm = fonts["tiny"], fonts["med"]
    HEADER_H  = 24
    HALF_H    = (H - HEADER_H) // 2
    DIVIDER_Y = HEADER_H + HALF_H

    # Top header
    pygame.draw.rect(surf, C_PANEL, (0, 0, W, HEADER_H))
    pygame.draw.line(surf, C_ACCENT, (0, HEADER_H), (W, HEADER_H), 1)
    surf.blit(fm.render("HVAC-Vibe", True, C_ACCENT), (8, 4))
    ts = ft.render(time.strftime("%H:%M:%S"), True, C_GREY)
    surf.blit(ts, (W - ts.get_width() - 6, 7))

    # Divider
    pygame.draw.line(surf, C_DIVIDER, (0, DIVIDER_Y), (W, DIVIDER_Y), 1)

    for idx, sensor in enumerate(sensors[:2]):
        y0 = HEADER_H + idx * HALF_H
        h  = HALF_H - 1
        _draw_sensor_row(surf, sensor, 0, y0, W, h, ft, fm)


def _draw_sensor_row(surf, sensor: SensorState,
                     x, y, w, h, ft, fm):
    """Compact single-sensor row: name | 4 values | sparkline."""
    PAD   = 4
    NAME_W = 70
    VAL_W  = 56
    SPARK_W = w - NAME_W - VAL_W * 4 - PAD * 2
    SPARK_H = h - PAD * 2

    # Name + status
    col = C_GREEN if sensor.connected else C_RED
    draw_conn_dot(surf, x + PAD + 5, y + h//2, sensor.connected)
    surf.blit(fm.render(sensor.name[:8], True,
                        alarm_color(sensor) if sensor.alarm else C_WHITE),
              (x + PAD + 14, y + h//2 - 8))
    surf.blit(ft.render(f"{sensor.rssi}dBm", True, C_GREY),
              (x + PAD + 14, y + h//2 + 6))

    # 4 value columns
    vals = [
        ("RMS",  f"{sensor.vib_rms:.3f}",  "g",   alarm_color(sensor)),
        ("PEAK", f"{sensor.vib_peak:.2f}", "g",   C_YELLOW),
        ("TEMP", f"{sensor.temp:.1f}",     "\u00b0C", C_YELLOW),
        ("HUM",  f"{sensor.humidity:.1f}", "%",   C_ACCENT),
    ]
    for i, (label, val, unit, c) in enumerate(vals):
        vx = x + NAME_W + i * VAL_W
        surf.blit(ft.render(label, True, C_GREY), (vx, y + PAD))
        vs = fm.render(val, True, c)
        surf.blit(vs, (vx, y + PAD + 12))
        surf.blit(ft.render(unit, True, C_GREY),
                  (vx + vs.get_width() + 2, y + PAD + 18))

    # Sparkline
    sx = x + NAME_W + VAL_W * 4 + PAD
    draw_sparkline(surf, sensor, sx, y + PAD, SPARK_W, SPARK_H)


# ── Layout: 3-4 sensors (2×2 grid) ───────────────────────────
def draw_grid(surf, sensors: list[SensorState], fonts):
    ft, fm = fonts["tiny"], fonts["med"]
    HEADER_H = 24
    COLS, ROWS = 2, 2
    CW = W // COLS
    CH = (H - HEADER_H) // ROWS

    pygame.draw.rect(surf, C_PANEL, (0, 0, W, HEADER_H))
    pygame.draw.line(surf, C_ACCENT, (0, HEADER_H), (W, HEADER_H), 1)
    surf.blit(fm.render("HVAC-Vibe", True, C_ACCENT), (8, 4))
    ts = ft.render(time.strftime("%H:%M:%S"), True, C_GREY)
    surf.blit(ts, (W - ts.get_width() - 6, 7))

    for idx, sensor in enumerate(sensors[:4]):
        col_i = idx % COLS
        row_i = idx // COLS
        cx = col_i * CW
        cy = HEADER_H + row_i * CH
        if col_i > 0:
            pygame.draw.line(surf, C_DIVIDER, (cx, cy), (cx, cy + CH), 1)
        if row_i > 0:
            pygame.draw.line(surf, C_DIVIDER, (cx, cy), (cx + CW, cy), 1)
        _draw_grid_cell(surf, sensor, cx, cy, CW, CH, ft, fm)


def _draw_grid_cell(surf, sensor: SensorState,
                    x, y, w, h, ft, fm):
    PAD = 4
    col = C_GREEN if sensor.connected else C_RED

    draw_conn_dot(surf, x + PAD + 5, y + PAD + 6, sensor.connected)
    surf.blit(fm.render(sensor.name[:10], True,
                        alarm_color(sensor) if sensor.alarm else C_WHITE),
              (x + PAD + 14, y + PAD))
    surf.blit(ft.render(f"{'ALM' if sensor.alarm else 'WARN' if sensor.warn else 'OK'}",
                         True, alarm_color(sensor)),
              (x + w - 30, y + PAD))

    # Two rows of values
    surf.blit(ft.render("RMS", True, C_GREY),  (x + PAD, y + 22))
    surf.blit(fm.render(f"{sensor.vib_rms:.3f}", True, alarm_color(sensor)),
              (x + PAD + 24, y + 18))

    surf.blit(ft.render("PEAK", True, C_GREY), (x + PAD, y + 36))
    surf.blit(fm.render(f"{sensor.vib_peak:.2f}", True, C_YELLOW),
              (x + PAD + 32, y + 32))

    surf.blit(ft.render(f"{sensor.temp:.1f}\u00b0C", True, C_YELLOW),
              (x + PAD, y + 50))
    surf.blit(ft.render(f"{sensor.humidity:.1f}%", True, C_ACCENT),
              (x + PAD + 50, y + 50))

    # Mini sparkline
    SPARK_H = h - 68
    if SPARK_H > 10:
        draw_sparkline(surf, sensor, x + PAD, y + 64, w - PAD*2, SPARK_H)


# ── Layout: 5+ sensors (list) ────────────────────────────────
def draw_list(surf, sensors: list[SensorState], fonts):
    ft, fm = fonts["tiny"], fonts["med"]
    HEADER_H = 24
    ROW_H    = (H - HEADER_H) // min(len(sensors), 8)

    pygame.draw.rect(surf, C_PANEL, (0, 0, W, HEADER_H))
    pygame.draw.line(surf, C_ACCENT, (0, HEADER_H), (W, HEADER_H), 1)
    surf.blit(fm.render(f"HVAC-Vibe  ({len(sensors)} sensors)", True, C_ACCENT),
              (8, 4))
    ts = ft.render(time.strftime("%H:%M:%S"), True, C_GREY)
    surf.blit(ts, (W - ts.get_width() - 6, 7))

    for idx, sensor in enumerate(sensors[:8]):
        ry  = HEADER_H + idx * ROW_H
        col = alarm_color(sensor)
        pygame.draw.line(surf, C_DIVIDER, (0, ry), (W, ry), 1)
        draw_conn_dot(surf, 10, ry + ROW_H//2, sensor.connected)
        surf.blit(fm.render(f"{sensor.name[:10]}", True, C_WHITE), (22, ry + 2))
        surf.blit(ft.render(
            f"RMS:{sensor.vib_rms:.3f}g  "
            f"T:{sensor.temp:.1f}C  "
            f"H:{sensor.humidity:.0f}%  "
            f"BAT:{sensor.battery}%",
            True, col), (22, ry + ROW_H//2 + 2))
        if sensor.alarm:
            badge = ft.render("ALM", True, C_BG)
            bw2 = badge.get_width() + 4
            pygame.draw.rect(surf, C_RED,
                             (W - bw2 - 4, ry + 4, bw2, ROW_H - 8),
                             border_radius=2)
            surf.blit(badge, (W - bw2 - 2, ry + ROW_H//2 - 5))


# ── No sensors ────────────────────────────────────────────────
def draw_waiting(surf, fonts):
    ft, fm = fonts["tiny"], fonts["med"]
    surf.fill(C_BG)
    pygame.draw.rect(surf, C_PANEL, (0, 0, W, 36))
    pygame.draw.line(surf, C_ACCENT, (0, 36), (W, 36), 1)
    surf.blit(fm.render("HVAC-Vibe", True, C_ACCENT), (8, 4))
    surf.blit(ft.render(time.strftime("%H:%M:%S"), True, C_GREY),
              (W - 70, 12))
    msg = fm.render("Scanning for sensors...", True, C_GREY)
    surf.blit(msg, (W//2 - msg.get_width()//2, H//2 - 10))
    dots = "." * (int(time.time()) % 4)
    surf.blit(ft.render(dots, True, C_ACCENT),
              (W//2 - 10, H//2 + 14))


# ── Main render dispatch ──────────────────────────────────────
def render(surf, sensors: list[SensorState], fonts):
    surf.fill(C_BG)
    # Store is keyed by name — no duplicates possible
    n = len(sensors)
    if n == 0:
        draw_waiting(surf, fonts)
    elif n == 1:
        draw_single(surf, sensors[0], fonts)
    elif n == 2:
        draw_dual(surf, sensors, fonts)
    elif n <= 4:
        draw_grid(surf, sensors, fonts)
    else:
        draw_list(surf, sensors, fonts)


# ── Main loop ─────────────────────────────────────────────────
def run():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("HVAC-Vibe")
    pygame.mouse.set_visible(not ON_PI)
    clock = pygame.time.Clock()

    fonts = {
        "tiny":  pygame.font.SysFont(DISPLAY["font_mono"], 11),
        "small": pygame.font.SysFont(DISPLAY["font_mono"], 13),
        "med":   pygame.font.SysFont(DISPLAY["font_mono"], 15, bold=True),
        "large": pygame.font.SysFont(DISPLAY["font_mono"], 26, bold=True),
    }

    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return

            sensors = store.get_all()
            render(screen, sensors, fonts)

            if ON_PI:
                flush_to_fb(screen)
            else:
                pygame.display.flip()

            clock.tick(DISPLAY["fps"])
    finally:
        # Clear framebuffer to black on exit
        if ON_PI:
            try:
                screen.fill((0, 0, 0))
                flush_to_fb(screen)
            except Exception:
                pass
        pygame.quit()


if __name__ == "__main__":
    run()
