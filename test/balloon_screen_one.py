"""
balloon_screen_one.py — Single balloon, clean cycle.
Balloon rises from bottom, exits top fully, reappears from bottom.
Cycles through 3 x-positions spaced W//3 apart.
No partial clipping, no ghost — just a clean loop.
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
RISE_SPEED  = 30        # px/s — 50% of original 60
SWAY_AMP    = 20
SWAY_SPEED  = 0.55
SHAKE_AMP   = 10
SHAKE_SPEED = 13.0
N_POS       = 3         # number of x launch positions

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
        self.W        = W
        self.H        = H
        self._pos_idx = 0       # current x launch position index (0,1,2)
        self._prev_raw = -1     # track modulo wrap to advance position

    def _launch_x(self, idx):
        """3 x positions: centers of 3 equal thirds of the screen.
        W=480 → 80, 240, 400"""
        return self.W // (N_POS * 2) + (idx % N_POS) * (self.W // N_POS)

    def _ckey(self, s):
        if not s.connected: return "disc"
        if s.alarm:         return "alarm"
        if s.warn:          return "warn"
        return "ok"

    def _scale(self, s):
        return SCALE_MIN + (max(0, min(RMS_MAX, s.vib_rms)) / RMS_MAX) * (SCALE_MAX - SCALE_MIN)

    def draw(self, surf, sensor, fonts, balloon_path):
        _load_balloon(balloon_path)
        t      = time.time()
        ckey   = self._ckey(sensor)
        bsurf  = _tinted(ckey, self._scale(sensor))
        bw, bh = bsurf.get_size()

        label_h  = 44
        assembly = bh + STRING_LEN + label_h

        # Full journey: enter from bottom (top_y=H), exit top (top_y=-assembly)
        travel = self.H + assembly
        raw_y  = (t * RISE_SPEED) % travel

        # Detect wrap → advance to next x position
        if self._prev_raw >= 0 and raw_y < self._prev_raw:
            self._pos_idx = (self._pos_idx + 1) % N_POS
        self._prev_raw = raw_y

        top_y = int(self.H - raw_y)

        surf.fill(C_BG)

        # Only draw when assembly is on screen
        if top_y <= self.H and top_y + assembly >= 0:
            cx    = self._launch_x(self._pos_idx)
            sway  = math.sin(t * SWAY_SPEED) * SWAY_AMP
            shake = math.sin(t * SHAKE_SPEED) * SHAKE_AMP if sensor.alarm else 0.0
            cx    = int(cx + sway + shake)

            surf.blit(bsurf, (cx - bw//2, top_y))

            knot_x = cx
            knot_y = top_y + int(bh * 0.91)
            sx1    = int(self._launch_x(self._pos_idx) + sway * 0.25)
            sy1    = knot_y + STRING_LEN
            ctrl_x = int(self._launch_x(self._pos_idx) - sway * 0.45)
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


# ── Standalone test ───────────────────────────────────────────
class FakeSensor:
    def __init__(self):
        self.name="HVAC-Vibe-1"; self.vib_rms=0.9
        self.connected=True; self.alarm=False; self.warn=False

def main():
    W, H = 480, 320
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Balloon One")
    clock  = pygame.time.Clock()
    fonts  = {
        "tiny":  pygame.font.SysFont("consolas", 11),
        "small": pygame.font.SysFont("consolas", 13),
        "med":   pygame.font.SysFont("consolas", 15, bold=True),
        "large": pygame.font.SysFont("consolas", 26, bold=True),
    }
    bpath  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "balloon.png")
    sensor = FakeSensor()
    scr    = BalloonScreenOne(W, H)

    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT: pygame.quit(); return
            if e.type == pygame.KEYDOWN:
                k = e.key
                if k == pygame.K_ESCAPE: pygame.quit(); return
                elif k == pygame.K_a:
                    sensor.alarm = not sensor.alarm; sensor.warn = False
                    _tint_cache.clear()
                elif k == pygame.K_w:
                    sensor.warn = not sensor.warn; sensor.alarm = False
                    _tint_cache.clear()
                elif k == pygame.K_d:
                    sensor.connected = not sensor.connected; _tint_cache.clear()
                elif k in (pygame.K_PLUS, pygame.K_EQUALS):
                    sensor.vib_rms = min(RMS_MAX, sensor.vib_rms + 0.1)
                elif k == pygame.K_MINUS:
                    sensor.vib_rms = max(0.05, sensor.vib_rms - 0.1)

        scr.draw(screen, sensor, fonts, bpath)
        screen.blit(fonts["tiny"].render(
            "A=alarm W=warn D=disc +/-=rms ESC=quit", True, (50,60,75)), (6,6))
        pygame.display.flip()
        clock.tick(30)

if __name__ == "__main__":
    main()
