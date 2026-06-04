

def show_unconfigured_screen():
    """Static 'Hold 5s to setup WiFi' screen for first boot."""
    try:
        import pygame
        pygame, screen = _init_pygame()
        screen.fill(BLACK)

        font_big   = pygame.font.SysFont("monospace", 22, bold=True)
        font_body  = pygame.font.SysFont("monospace", 15)
        font_small = pygame.font.SysFont("monospace", 13)

        title = font_big.render("HVAC-Vibe", True, BLUE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 80))

        line1 = font_body.render("WiFi not configured", True, LGRAY)
        screen.blit(line1, (WIDTH // 2 - line1.get_width() // 2, 135))

        line2 = font_body.render("Hold button 5s to setup", True, WHITE)
        screen.blit(line2, (WIDTH // 2 - line2.get_width() // 2, 165))

        line3 = font_small.render("Short press: sensor management", True, GRAY)
        screen.blit(line3, (WIDTH // 2 - line3.get_width() // 2, 205))

        pygame.display.flip()
        log.info("Unconfigured screen shown")
    except Exception as e:
        log.error(f"Display error: {e}")


def show_management_starting():
    """Brief 'Management Mode' flash before starting."""
    try:
        import pygame
        pygame, screen = _init_pygame()
        screen.fill(BLACK)

        font_big  = pygame.font.SysFont("monospace", 22, bold=True)
        font_body = pygame.font.SysFont("monospace", 14)

        title = font_big.render("Management Mode", True, BLUE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 120))

        sub = font_body.render("Starting...", True, LGRAY)
        screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 160))

        pygame.display.flip()
    except Exception as e:
        log.error(f"Display error: {e}")


def show_ip_on_pygame(ip: str):
    """
    Send the IP address to the running pygame display service.
    Writes to a shared file that hvac-pygame reads on next frame.
    This avoids framebuffer conflict — pygame owns the display.
    """
    try:
        import json
        overlay_file = "/tmp/hvac-display-overlay.json"
        with open(overlay_file, "w") as f:
            json.dump({"ip": ip, "ts": __import__("time").time()}, f)
        log.info(f"IP overlay written: {ip}")
    except Exception as e:
        log.error(f"IP overlay error: {e}")
