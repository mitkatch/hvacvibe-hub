"""
balloon_screen_win.py — Windows test harness for balloon animation.
Requires balloon.png in same directory.

    pip install pygame
    python balloon_screen_win.py

Keys:  1/2/3=sensors  A=alarm  W=warn  D=disconnect  +/-=rms  ESC=quit
"""

import math
import os
import time
import pygame

C_BG    = (18,  22,  28)
C_WHITE = (220, 225, 230)
C_GREY  = (80,  90, 105)

COLORS = {
    "ok":    ((30,  180, 100), (60,  140,  80)),
    "warn":  ((220, 140,  20), (180, 110,  20)),
    "alarm": ((200,  45,  45), (180,  40,  40)),
    "disc":  ((90,  100, 115), (70,   80,  95)),
}

RMS_MIN    = 0.0
RMS_MAX    = 2.0
SCALE_MIN  = 1.10
SCALE_MAX  = 1.40
STRING_LEN = 70
STRING_SEG = 16

RISE_SPEED  = 28
SWAY_AMP    = 20
SWAY_SPEED  = 0.55
SHAKE_AMP   = 10
SHAKE_SPEED = 13.0

_balloon_base = None
_tint_cache   = {}

def _load_balloon(path):
    global _balloon_base
    if _balloon_base is None:
        _balloon_base = pygame.image.load(path).convert_alpha()

def _tinted(color_key, scale):
    key = (color_key, int(scale * 100))
    if key in _tint_cache:
        return _tint_cache[key]
    base   = _balloon_base
    w, h   = int(base.get_width() * scale), int(base.get_height() * scale)
    scaled = pygame.transform.smoothscale(base, (w, h))
    tr, tg, tb = COLORS[color_key][0]
    s = scaled.copy()
    a = pygame.surfarray.pixels3d(s)
    a[:,:,0] = (a[:,:,0].astype(float) * tr / 255).clip(0,255).astype('uint8')
    a[:,:,1] = (a[:,:,1].astype(float) * tg / 255).clip(0,255).astype('uint8')
    a[:,:,2] = (a[:,:,2].astype(float) * tb / 255).clip(0,255).astype('uint8')
    del a
    _tint_cache[key] = s
    return s


def _blit_clipped(surf, img, x, y, screen_h):
    """
    Blit img at (x, y) clipping against screen top (y<0) and bottom (y+h>screen_h).
    Uses pygame source rect so only the visible pixel rows are drawn.
    """
    iw, ih = img.get_size()

    src_y = 0
    dst_y = y

    # Clip top
    if dst_y < 0:
        src_y = -dst_y
        dst_y = 0

    # Clip bottom
    visible_h = ih - src_y
    if dst_y + visible_h > screen_h:
        visible_h = screen_h - dst_y

    if visible_h <= 0:
        return  # fully off screen

    src_rect = pygame.Rect(0, src_y, iw, visible_h)
    surf.blit(img, (x, dst_y), src_rect)


def _draw_string_clipped(surf, knot_x, knot_y, home_x, sway,
                         str_col, screen_h, string_len=STRING_LEN):
    """Draw bezier string, clipping segments outside screen bounds."""
    sx1    = int(home_x + sway * 0.25)
    sy1    = knot_y + string_len
    ctrl_x = int(home_x - sway * 0.45)
    ctrl_y = knot_y + string_len * 0.6

    pts = []
    for i in range(STRING_SEG + 1):
        f  = i / STRING_SEG
        bx = (1-f)**2 * knot_x + 2*(1-f)*f * ctrl_x + f**2 * sx1
        by = (1-f)**2 * knot_y + 2*(1-f)*f * ctrl_y + f**2 * sy1
        pts.append((int(bx), int(by)))

    # Draw only segments where at least one endpoint is on screen
    for i in range(len(pts) - 1):
        y0, y1 = pts[i][1], pts[i+1][1]
        if y1 < 0 or y0 > screen_h:
            continue
        pygame.draw.line(surf, str_col, pts[i], pts[i+1], 2)

    return sx1, sy1  # string end point


def _draw_labels_clipped(surf, sx1, sy1, sensor, ckey, fonts, W, screen_h):
    """Draw name + rms labels, only if they're within screen bounds."""
    ft = fonts["tiny"]
    fm = fonts["med"]
    name_lbl = ft.render(sensor.name[:10], True, C_WHITE)
    rms_lbl  = fm.render(f"{sensor.vib_rms:.3f}g", True,
                         COLORS[ckey][0] if sensor.connected else C_GREY)
    for lbl, ly in [(name_lbl, sy1 + 4),
                    (rms_lbl,  sy1 + 4 + name_lbl.get_height() + 2)]:
        if ly > screen_h or ly + lbl.get_height() < 0:
            continue
        lx = sx1 - lbl.get_width() // 2
        surf.blit(lbl, (max(2, min(W - lbl.get_width() - 2, lx)), ly))


class FakeSensor:
    def __init__(self, name, rms=0.9):
        self.name = name;  self.vib_rms = rms
        self.connected = True;  self.alarm = False;  self.warn = False


class Balloon:
    def __init__(self, idx, total, W, H):
        self.W = W;  self.H = H
        self.phase  = idx * 2.1 + 0.7
        self.home_x = W // 2 if total == 1 else W // (total+1) * (idx+1)
        # Stagger start so balloons don't all enter at same time
        self._t_offset = idx * (H / max(total, 1)) / RISE_SPEED

    def _ckey(self, s):
        if not s.connected: return "disc"
        if s.alarm:         return "alarm"
        if s.warn:          return "warn"
        return "ok"

    def _scale(self, s):
        return SCALE_MIN + (max(0, min(RMS_MAX, s.vib_rms)) / RMS_MAX) * (SCALE_MAX - SCALE_MIN)

    def draw(self, surf, sensor, fonts, balloon_path):
        _load_balloon(balloon_path)
        t     = time.time() + self._t_offset
        ckey  = self._ckey(sensor)
        bsurf = _tinted(ckey, self._scale(sensor))
        bw, bh = bsurf.get_size()

        # ── Position ──────────────────────────────────────────
                # travel = H + bh: top_y goes H → -bh (exits through top)
        # ghost = top_y + H: at top_y=0 ghost=H, at top_y=-bh ghost=H-bh
        # Both visible only during crossing (-bh < top_y < 0) — seamless ✓
        travel  = self.H + bh
        raw_y   = (t * RISE_SPEED) % travel
        top_y   = int(self.H - raw_y)
        ghost_y = top_y + self.H        # always H px below primary

        sway  = math.sin(t * SWAY_SPEED + self.phase) * SWAY_AMP
        shake = math.sin(t * SHAKE_SPEED) * SHAKE_AMP if sensor.alarm else 0.0
        cx    = int(self.home_x + sway + shake)

        str_col = COLORS[ckey][1]

        # ── Draw primary (clips at top) ───────────────────────
        _blit_clipped(surf, bsurf, cx - bw//2, top_y, self.H)
        knot_y = top_y + int(bh * 0.91)
        sx1, sy1 = _draw_string_clipped(surf, cx, knot_y, self.home_x,
                                         sway, str_col, self.H)
        _draw_labels_clipped(surf, sx1, sy1, sensor, ckey, fonts, self.W, self.H)

        # ── Draw ghost (clips at bottom) ──────────────────────
        _blit_clipped(surf, bsurf, cx - bw//2, ghost_y, self.H)
        knot_y2 = ghost_y + int(bh * 0.91)
        sx1_g, sy1_g = _draw_string_clipped(surf, cx, knot_y2, self.home_x,
                                             sway, str_col, self.H)
        _draw_labels_clipped(surf, sx1_g, sy1_g, sensor, ckey, fonts, self.W, self.H)

        # ── Status badge ──────────────────────────────────────
        ft = fonts["tiny"]
        for ty in (top_y, ghost_y):
            mid_y = ty + bh // 2
            if 0 <= mid_y <= self.H:
                if sensor.alarm:
                    b = ft.render("ALARM", True, (255, 60, 60))
                    surf.blit(b, (cx - b.get_width()//2, mid_y - 8))
                elif not sensor.connected:
                    b = ft.render("offline", True, C_GREY)
                    surf.blit(b, (cx - b.get_width()//2, mid_y - 6))


class BalloonScreen:
    def __init__(self, W, H):
        self.W = W;  self.H = H
        self._balloons = [];  self._n = 0

    def _rebuild(self, n):
        self._n = n
        self._balloons = [Balloon(i, n, self.W, self.H) for i in range(n)]

    def draw(self, surf, sensors, fonts):
        surf.fill(C_BG)
        n = len(sensors)
        if n == 0:
            m = fonts["med"].render("No sensors", True, C_GREY)
            surf.blit(m, (self.W//2 - m.get_width()//2, self.H//2-10))
        else:
            if n != self._n: self._rebuild(n)
            bpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "balloon.png")
            for i, s in enumerate(sensors):
                if i < len(self._balloons):
                    self._balloons[i].draw(surf, s, fonts, bpath)

        ts = fonts["tiny"].render(time.strftime("%H:%M:%S"), True, C_GREY)
        surf.blit(ts, (self.W - ts.get_width()-6, 6))
        h = fonts["tiny"].render("[ BTN1 ] switch screen", True, (45,55,70))
        surf.blit(h, (self.W//2 - h.get_width()//2, self.H-14))


def main():
    W, H = 480, 320
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("HVAC-Vibe Balloon Test")
    clock = pygame.time.Clock()
    fonts = {
        "tiny":  pygame.font.SysFont("consolas", 11),
        "small": pygame.font.SysFont("consolas", 13),
        "med":   pygame.font.SysFont("consolas", 15, bold=True),
        "large": pygame.font.SysFont("consolas", 26, bold=True),
    }
    bpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "balloon.png")
    sensors = [FakeSensor("HVAC-Vibe-1", 0.90),
               FakeSensor("HVAC-Vibe-2", 0.45),
               FakeSensor("HVAC-Vibe-3", 1.30)]
    active = 1
    balloons = [Balloon(0, 1, W, H)]

    def rebuild(n):
        nonlocal active, balloons
        active = n
        balloons = [Balloon(i, n, W, H) for i in range(n)]

    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT: pygame.quit(); return
            if e.type == pygame.KEYDOWN:
                k = e.key
                if   k == pygame.K_ESCAPE:                  pygame.quit(); return
                elif k == pygame.K_1:                       rebuild(1)
                elif k == pygame.K_2:                       rebuild(2)
                elif k == pygame.K_3:                       rebuild(3)
                elif k == pygame.K_a:
                    sensors[0].alarm = not sensors[0].alarm
                    sensors[0].warn  = False;  _tint_cache.clear()
                elif k == pygame.K_w:
                    sensors[0].warn  = not sensors[0].warn
                    sensors[0].alarm = False;  _tint_cache.clear()
                elif k == pygame.K_d:
                    sensors[0].connected = not sensors[0].connected
                    _tint_cache.clear()
                elif k in (pygame.K_PLUS, pygame.K_EQUALS):
                    sensors[0].vib_rms = min(RMS_MAX, sensors[0].vib_rms + 0.1)
                elif k == pygame.K_MINUS:
                    sensors[0].vib_rms = max(0.05, sensors[0].vib_rms - 0.1)

        screen.fill(C_BG)
        for i, s in enumerate(sensors[:active]):
            balloons[i].draw(screen, s, fonts, bpath)

        ts = fonts["tiny"].render(time.strftime("%H:%M:%S"), True, C_GREY)
        screen.blit(ts, (W - ts.get_width()-6, 6))
        screen.blit(fonts["tiny"].render(
            "1/2/3=sensors  A=alarm  W=warn  D=disc  +/-=rms  ESC=quit",
            True, (50,60,75)), (6,6))
        screen.blit(fonts["tiny"].render(
            f"RMS={sensors[0].vib_rms:.2f}g", True, C_GREY), (6, H-14))

        pygame.display.flip()
        clock.tick(30)

if __name__ == "__main__":
    main()
