"""
Balloon Screen — cartoon balloon animation, one balloon per sensor.

Balloon shape matches reference: wider in upper-middle, tapered bottom
with small knot tip. Floats upward continuously, string sways.
"""

import math
import time
import pygame

C_BG    = (18,  22,  28)
C_WHITE = (220, 225, 230)
C_GREY  = (80,  90, 105)

COLORS = {
    "ok":    ((30,  180, 100), (120, 230, 170), (15,  100,  55), (60,  140,  80)),
    "warn":  ((220, 140,  20), (255, 210, 100), (140,  80,  10), (180, 110,  20)),
    "alarm": ((200,  45,  45), (255, 130, 130), (120,  20,  20), (180,  40,  40)),
    "disc":  ((60,   70,  85), (110, 120, 135), ( 35,  40,  50), ( 50,  60,  75)),
}

RMS_MIN    = 0.0
RMS_MAX    = 2.0
RAD_MIN    = 32
RAD_MAX    = 65
STRING_LEN = 80
STRING_SEG = 16

RISE_SPEED  = 28
SWAY_AMP    = 20
SWAY_SPEED  = 0.55
SHAKE_AMP   = 10
SHAKE_SPEED = 13.0


def _balloon_points(cx, cy, rad, segments=48):
    """
    Teardrop balloon shape:
    - Rounded top
    - Widest at ~40% from top
    - Pinched and tapered toward bottom
    """
    pts = []
    for i in range(segments):
        # angle: 0 = top, goes clockwise
        angle = math.pi * 2 * i / segments - math.pi / 2
        bx = math.cos(angle)
        by = math.sin(angle)

        # t: 0=top, 1=bottom
        t = (by + 1) / 2

        # Width: bulge at t≈0.42, pinch toward bottom
        width = 1.0 + 0.25 * math.exp(-((t - 0.42) ** 2) / 0.055)
        if t > 0.72:
            pinch = 1.0 - ((t - 0.72) / 0.28) ** 1.4 * 0.65
            width *= max(0.12, pinch)

        # Height: slightly tall
        height = 1.10

        pts.append((int(cx + bx * rad * width),
                    int(cy + by * rad * height)))
    return pts


def _draw_balloon(surf, cx, cy, rad, body_col, hi_col, sh_col):
    """Draw the shaped balloon with shadow, body, highlight, outline."""
    # Shadow (offset down-right slightly)
    shadow_pts = _balloon_points(cx + 4, cy + 5, rad)
    if len(shadow_pts) >= 3:
        pygame.draw.polygon(surf, sh_col, shadow_pts)

    # Body
    pts = _balloon_points(cx, cy, rad)
    if len(pts) >= 3:
        pygame.draw.polygon(surf, body_col, pts)

    # Specular highlight — upper-left oval
    hi_r  = max(5, rad // 4)
    hi_rx = max(3, rad // 6)
    hi_x  = cx - int(rad * 0.28)
    hi_y  = cy - int(rad * 0.32)
    hi_surf = pygame.Surface((hi_rx * 4, hi_r * 2 + 4), pygame.SRCALPHA)
    pygame.draw.ellipse(hi_surf, (*hi_col, 155),
                        (0, 0, hi_rx * 4, hi_r * 2))
    # Rotate highlight ~20° to follow balloon lean
    hi_rot = pygame.transform.rotate(hi_surf, 20)
    surf.blit(hi_rot, (hi_x - hi_rot.get_width() // 2,
                        hi_y - hi_rot.get_height() // 2))

    # Outline
    if len(pts) >= 3:
        pygame.draw.polygon(surf, sh_col, pts, 2)

    # Knot: small teardrop at bottom of balloon
    knot_y = cy + int(rad * 1.10)
    pygame.draw.circle(surf, sh_col, (cx, knot_y), 5)
    # Small tie lines
    pygame.draw.line(surf, sh_col,
                     (cx - 4, knot_y + 3), (cx, knot_y + 7), 2)
    pygame.draw.line(surf, sh_col,
                     (cx + 4, knot_y + 3), (cx, knot_y + 7), 2)

    return knot_y + 7   # string attach point Y


class Balloon:
    def __init__(self, idx, total, W, H):
        self.W       = W
        self.H       = H
        self.phase   = idx * 2.1 + 0.7
        self.home_x  = self._lane_x(idx, total, W)
        self._offset = (H + 240) * idx / max(total, 1)

    def _lane_x(self, idx, total, W):
        if total == 1:
            return W // 2
        return W // (total + 1) * (idx + 1)

    def _color_set(self, sensor):
        if not sensor.connected: return COLORS["disc"]
        if sensor.alarm:         return COLORS["alarm"]
        if sensor.warn:          return COLORS["warn"]
        return COLORS["ok"]

    def _radius(self, sensor):
        rms = max(RMS_MIN, min(RMS_MAX, sensor.vib_rms))
        return int(RAD_MIN + (rms / RMS_MAX) * (RAD_MAX - RAD_MIN))

    def draw(self, surf, sensor, fonts):
        t   = time.time()
        rad = self._radius(sensor)

        # Upward loop
        travel = self.H + rad * 2 + STRING_LEN + 60
        raw_y  = (t * RISE_SPEED + self._offset) % travel
        cy     = int(self.H + rad - raw_y)

        # Sway
        sway  = math.sin(t * SWAY_SPEED + self.phase) * SWAY_AMP
        shake = math.sin(t * SHAKE_SPEED) * SHAKE_AMP if sensor.alarm else 0.0
        cx    = int(self.home_x + sway + shake)

        body_col, hi_col, sh_col, str_col = self._color_set(sensor)

        # Draw balloon, get string attach Y
        attach_y = _draw_balloon(surf, cx, cy, rad, body_col, hi_col, sh_col)

        # String end (pendulum lag)
        sx0    = cx
        sy0    = attach_y
        sx1    = int(self.home_x + sway * 0.25)
        sy1    = sy0 + STRING_LEN
        ctrl_x = int(self.home_x - sway * 0.45)
        ctrl_y = sy0 + STRING_LEN * 0.6

        pts = []
        for i in range(STRING_SEG + 1):
            f  = i / STRING_SEG
            bx = (1-f)**2 * sx0 + 2*(1-f)*f * ctrl_x + f**2 * sx1
            by = (1-f)**2 * sy0 + 2*(1-f)*f * ctrl_y + f**2 * sy1
            pts.append((int(bx), int(by)))
        if len(pts) >= 2:
            pygame.draw.lines(surf, str_col, False, pts, 2)

        # Labels below string end
        ft       = fonts["tiny"]
        fm       = fonts["med"]
        name_lbl = ft.render(sensor.name[:10], True, C_WHITE)
        rms_lbl  = fm.render(f"{sensor.vib_rms:.3f}g", True,
                             body_col if sensor.connected else C_GREY)
        for lbl, ly in [(name_lbl, sy1 + 5),
                        (rms_lbl,  sy1 + 5 + name_lbl.get_height() + 2)]:
            lx = sx1 - lbl.get_width() // 2
            surf.blit(lbl, (max(2, min(self.W - lbl.get_width() - 2, lx)), ly))

        # Badge
        if sensor.alarm:
            b = ft.render("ALARM", True, (255, 60, 60))
            surf.blit(b, (cx - b.get_width() // 2, cy - 10))
        elif not sensor.connected:
            b = ft.render("offline", True, C_GREY)
            surf.blit(b, (cx - b.get_width() // 2, cy - 8))


class BalloonScreen:
    def __init__(self, W, H):
        self.W = W
        self.H = H
        self._balloons = []
        self._n = 0

    def _rebuild(self, n):
        self._n        = n
        self._balloons = [Balloon(i, n, self.W, self.H) for i in range(n)]

    def draw(self, surf, sensors, fonts):
        surf.fill(C_BG)
        n = len(sensors)
        if n == 0:
            msg = fonts["med"].render("No sensors", True, C_GREY)
            surf.blit(msg, (self.W//2 - msg.get_width()//2, self.H//2 - 10))
        else:
            if n != self._n:
                self._rebuild(n)
            for i, s in enumerate(sensors):
                if i < len(self._balloons):
                    self._balloons[i].draw(surf, s, fonts)

        ts = fonts["tiny"].render(time.strftime("%H:%M:%S"), True, C_GREY)
        surf.blit(ts, (self.W - ts.get_width() - 6, 6))
        hint = fonts["tiny"].render("[ BTN1 ] switch screen", True, (45, 55, 70))
        surf.blit(hint, (self.W//2 - hint.get_width()//2, self.H - 14))
