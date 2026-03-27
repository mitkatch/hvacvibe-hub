"""
setup_display.py — Waveshare 3.5" IPS LCD display for setup mode.

Shows:
  - QR code + AP SSID/password during setup
  - IP address + success message after WiFi connect
  - Error screen on connection failure

Writes directly to /dev/fb0 (framebuffer) using pygame,
same as hvac-pygame service.
"""

import logging
import os
import sys

log = logging.getLogger("setup_display")

FB_DEV   = "/dev/fb0"
WIDTH    = 480
HEIGHT   = 320

# Colors
BLACK    = (0,   0,   0)
WHITE    = (255, 255, 255)
BLUE     = (30,  120, 220)
GREEN    = (40,  180,  80)
RED      = (220,  50,  50)
GRAY     = (60,   60,  60)
LGRAY    = (180, 180, 180)


def _init_pygame():
    import pygame
    os.environ["SDL_VIDEODRIVER"] = "fbcon"
    os.environ["SDL_FBDEV"]       = FB_DEV
    os.environ["SDL_NOMOUSE"]     = "1"
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    return pygame, screen


def show_setup_screen(ap_ssid: str, ap_password: str, url: str = "192.168.4.1"):
    """Show QR code + connection instructions during AP setup mode."""
    try:
        import qrcode
        import pygame

        pygame, screen = _init_pygame()
        screen.fill(BLACK)

        # Generate QR code for the setup URL
        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data(f"http://{url}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="white", back_color="black")

        # Convert QR PIL image to pygame surface
        qr_w, qr_h = qr_img.size
        qr_surface = pygame.Surface((qr_w, qr_h))
        for y in range(qr_h):
            for x in range(qr_w):
                pixel = qr_img.getpixel((x, y))
                color = WHITE if pixel == 255 else BLACK
                qr_surface.set_at((x, y), color)

        # Layout — QR on left, text on right
        qr_x = 20
        qr_y = (HEIGHT - qr_h) // 2
        screen.blit(qr_surface, (qr_x, qr_y))

        # Text panel
        font_title  = pygame.font.SysFont("monospace", 18, bold=True)
        font_body   = pygame.font.SysFont("monospace", 14)
        font_small  = pygame.font.SysFont("monospace", 12)

        tx = qr_x + qr_w + 20
        ty = 30

        # Title
        title = font_title.render("HVAC-Vibe Setup", True, BLUE)
        screen.blit(title, (tx, ty))
        ty += 30

        # Divider
        pygame.draw.line(screen, GRAY, (tx, ty), (WIDTH - 10, ty), 1)
        ty += 12

        # Step 1
        s1 = font_body.render("1. Connect to WiFi:", True, LGRAY)
        screen.blit(s1, (tx, ty)); ty += 20
        ssid_surf = font_body.render(f"   {ap_ssid}", True, WHITE)
        screen.blit(ssid_surf, (tx, ty)); ty += 20
        pw_label = font_small.render(f"   pw: {ap_password}", True, LGRAY)
        screen.blit(pw_label, (tx, ty)); ty += 24

        # Step 2
        s2 = font_body.render("2. Scan QR or open:", True, LGRAY)
        screen.blit(s2, (tx, ty)); ty += 20
        url_surf = font_body.render(f"   http://{url}", True, WHITE)
        screen.blit(url_surf, (tx, ty)); ty += 24

        # Step 3
        s3 = font_body.render("3. Choose your WiFi", True, LGRAY)
        screen.blit(s3, (tx, ty)); ty += 20
        s4 = font_body.render("   and enter password", True, LGRAY)
        screen.blit(s4, (tx, ty))

        pygame.display.flip()
        log.info("Setup screen displayed")

    except Exception as e:
        log.error(f"Display error: {e}")


def show_connecting_screen(ssid: str):
    """Show 'connecting...' while applying credentials."""
    try:
        import pygame
        pygame, screen = _init_pygame()
        screen.fill(BLACK)

        font_big  = pygame.font.SysFont("monospace", 22, bold=True)
        font_body = pygame.font.SysFont("monospace", 16)

        title = font_big.render("Connecting...", True, BLUE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 110))

        ssid_surf = font_body.render(f"Network: {ssid}", True, LGRAY)
        screen.blit(ssid_surf, (WIDTH // 2 - ssid_surf.get_width() // 2, 150))

        note = font_body.render("Please wait...", True, GRAY)
        screen.blit(note, (WIDTH // 2 - note.get_width() // 2, 185))

        pygame.display.flip()
    except Exception as e:
        log.error(f"Display error: {e}")


def show_success_screen(ip: str):
    """Show IP address after successful WiFi connection."""
    try:
        import pygame
        pygame, screen = _init_pygame()
        screen.fill(BLACK)

        font_big   = pygame.font.SysFont("monospace", 24, bold=True)
        font_body  = pygame.font.SysFont("monospace", 17)
        font_small = pygame.font.SysFont("monospace", 14)

        # Green checkmark area
        pygame.draw.circle(screen, GREEN, (WIDTH // 2, 100), 35, 3)
        check = font_big.render("✓", True, GREEN)
        screen.blit(check, (WIDTH // 2 - check.get_width() // 2, 82))

        title = font_big.render("Connected!", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 150))

        ip_label = font_body.render("IP Address:", True, LGRAY)
        screen.blit(ip_label, (WIDTH // 2 - ip_label.get_width() // 2, 188))

        ip_surf = font_big.render(ip, True, BLUE)
        screen.blit(ip_surf, (WIDTH // 2 - ip_surf.get_width() // 2, 212))

        note = font_small.render("Engine starting...", True, GRAY)
        screen.blit(note, (WIDTH // 2 - note.get_width() // 2, 255))

        pygame.display.flip()
        log.info(f"Success screen: {ip}")
    except Exception as e:
        log.error(f"Display error: {e}")


def show_error_screen(message: str = "Connection failed"):
    """Show error + retry instructions."""
    try:
        import pygame
        pygame, screen = _init_pygame()
        screen.fill(BLACK)

        font_big  = pygame.font.SysFont("monospace", 20, bold=True)
        font_body = pygame.font.SysFont("monospace", 15)

        err = font_big.render("Connection Failed", True, RED)
        screen.blit(err, (WIDTH // 2 - err.get_width() // 2, 100))

        msg = font_body.render(message, True, LGRAY)
        screen.blit(msg, (WIDTH // 2 - msg.get_width() // 2, 140))

        r1 = font_body.render("Reconnect to:", True, LGRAY)
        screen.blit(r1, (WIDTH // 2 - r1.get_width() // 2, 180))

        r2 = font_body.render("HVAC-Vibe-Setup", True, WHITE)
        screen.blit(r2, (WIDTH // 2 - r2.get_width() // 2, 205))

        r3 = font_body.render("and try again", True, LGRAY)
        screen.blit(r3, (WIDTH // 2 - r3.get_width() // 2, 230))

        pygame.display.flip()
    except Exception as e:
        log.error(f"Display error: {e}")


def clear():
    try:
        import pygame
        pygame, screen = _init_pygame()
        screen.fill(BLACK)
        pygame.display.flip()
    except Exception:
        pass
