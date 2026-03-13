"""
balloon_screen_one.py — Single balloon clean cycle, Pi version.
Balloon rises fully from bottom, exits top fully, reappears from bottom.
Cycles through 3 x-positions spaced W//3 apart.
No clipping, no ghost.
balloon.png must be in same directory.
"""

import math
import os
import time
import pygame

C_BG     = (18,  22,  28)
C_WHITE  = (220, 225, 230)
C_GREY   = (80,  90, 105)

COLORS = {
    "ok":    ((30,  180, 100), (60,  140,  80)),
    "warn":  ((220, 140,  20), (180, 110,  20)),
    "alarm": ((200,  45,  45), (180,  40,  40)),
    "disc":  ((90,  100, 115), (70,   80,  95)),
}

RMS_MIN     = 0.0
RMS_MAX     = 2.0
SCALE_MIN   = 0.80
SCALE_MAX   = 1.20
STRING_LEN  = 70
STRING_SEG  = 16
RISE_SPEED  = 30        # px/s
SWAY_AMP    = 20
SWAY_SPEED  = 0.275     # rad/s — 50% of original 0.55
SHAKE_AMP   = 10
SHAKE_SPEED = 13.0
N_POS       = 3

# Phase modulo: exact LCM of sway and shake periods so sin/cos are continuous at wrap.
# sway period = 2π/0.275 ≈ 22.8s, shake period = 2π/13.0 ≈ 0.48s
# T_PHASE = 110 * 2π/0.275 = 2513.27s ≈ 42 min — both periods divide evenly.
_T_PHASE = 110 * 2 * 3.141592653589793 / 0.275   # ≈ 2513.27 s

_DIR          = os.path.dirname(os.path.abspath(__file__))
_balloon_base = None
_tint_cache   = {}

def _load_balloon():
    global _balloon_base
    if _balloon_base is None:
        _balloon_base = pygame.image.load(
            os.path.join(_DIR, "balloon.png")).convert_alpha()

def _tinted(color_key, scale):
    key = (color_key, int(scale * 100))
    if key in _tint_cache:
        return _tint_cache[key]
    base = _balloon_base
    w, h = int(base.get_width() * scale), int(base.get_height() * scale)
    s    = pygame.transform.smoothscale(base, (w, h)).copy()
    tr, tg, tb = COLORS[color_key][0]
    a = pygame.surfarray.pixels3d(s)
    a[:,:,0] = (a[:,:,0].astype(float) * tr / 255).clip(0,255).astype('uint8')
    a[:,:,1] = (a[:,:,1].astype(float) * tg / 255).clip(0,255).astype('uint8')
    a[:,:,2] = (a[:,:,2].astype(float) * tb / 255).clip(0,255).astype('uint8')
    del a
    _tint_cache[key] = s
    return s


class BalloonScreenOne:
    def __init__(self, W, H):
        self.W         = W
        self.H         = H
        self._pos_idx  = 0
        self._prev_raw = -1

    def _launch_x(self, idx):
        """Centers of 3 equal screen thirds. W=480 → 80, 240, 400."""
        return self.W // (N_POS * 2) + (idx % N_POS) * (self.W // N_POS)

    def _ckey(self, s):
        if not s.connected: return "disc"
        if s.alarm:         return "alarm"
        if s.warn:          return "warn"
        return "ok"

    def _scale(self, s):
        return SCALE_MIN + (max(0, min(RMS_MAX, s.vib_rms)) / RMS_MAX) * (SCALE_MAX - SCALE_MIN)

    def draw(self, surf, sensor, fonts):
        _load_balloon()
        now    = time.time()
        # t_raw: unbounded, used only for modulo — float64 is precise for years
        # t_phase: bounded to _T_PHASE, used for sin/cos — exact period, no jump at wrap
        t_raw   = now
        t_phase = now % _T_PHASE

        ckey   = self._ckey(sensor)
        bsurf  = _tinted(ckey, self._scale(sensor))
        bw, bh = bsurf.get_size()

        label_h  = 44
        assembly = bh + STRING_LEN + label_h

        travel = self.H + assembly
        raw_y  = (t_raw * RISE_SPEED) % travel

        # Detect wrap → advance x position
        # raw_y derived from unbounded t_raw so no false triggers from phase reset
        if self._prev_raw >= 0 and raw_y < self._prev_raw:
            self._pos_idx = (self._pos_idx + 1) % N_POS
        self._prev_raw = raw_y

        top_y = int(self.H - raw_y)

        surf.fill(C_BG)

        if top_y <= self.H and top_y + assembly >= 0:
            launch_x = self._launch_x(self._pos_idx)
            sway  = math.sin(t_phase * SWAY_SPEED) * SWAY_AMP
            shake = math.sin(t_phase * SHAKE_SPEED) * SHAKE_AMP if sensor.alarm else 0.0
            cx    = int(launch_x + sway + shake)

            surf.blit(bsurf, (cx - bw//2, top_y))

            knot_x = cx
            knot_y = top_y + int(bh * 0.91)
            sx1    = int(launch_x + sway * 0.25)
            sy1    = knot_y + STRING_LEN
            ctrl_x = int(launch_x - sway * 0.45)
            ctrl_y = knot_y + STRING_LEN * 0.6

            str_col = COLORS[ckey][1]
            pts = []
            for i in range(STRING_SEG + 1):
                f  = i / STRING_SEG
                bx = (1-f)**2*knot_x + 2*(1-f)*f*ctrl_x + f**2*sx1
                by = (1-f)**2*knot_y + 2*(1-f)*f*ctrl_y + f**2*sy1
                pts.append((int(bx), int(by)))
            if len(pts) >= 2:
                pygame.draw.lines(surf, str_col, False, pts, 2)

            ft = fonts["tiny"]
            fm = fonts["med"]
            name_lbl = ft.render(sensor.name[:10], True, C_WHITE)
            rms_lbl  = fm.render(f"{sensor.vib_rms:.3f}g", True,
                                 COLORS[ckey][0] if sensor.connected else C_GREY)
            for lbl, ly in [(name_lbl, sy1+4),
                            (rms_lbl,  sy1+4+name_lbl.get_height()+2)]:
                lx = sx1 - lbl.get_width()//2
                surf.blit(lbl, (max(2, min(self.W - lbl.get_width()-2, lx)), ly))

            if sensor.alarm:
                b = ft.render("ALARM", True, (255, 60, 60))
                surf.blit(b, (cx - b.get_width()//2, top_y + bh//2 - 8))
            elif not sensor.connected:
                b = ft.render("offline", True, C_GREY)
                surf.blit(b, (cx - b.get_width()//2, top_y + bh//2 - 6))

        ts   = fonts["tiny"].render(time.strftime("%H:%M:%S"), True, C_GREY)
        hint = fonts["tiny"].render("[ BTN1 ] switch screen", True, (45,55,70))
        surf.blit(ts,   (self.W - ts.get_width()-6, 6))
        surf.blit(hint, (self.W//2 - hint.get_width()//2, self.H-14))
