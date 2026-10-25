"""Render chosen moments of video.html to PNGs for checking."""
import sys
from playwright.sync_api import sync_playwright

ts = [float(a) for a in sys.argv[1:]]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.on("console", lambda m: print("console:", m.text) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: print("pageerror:", e))
    pg.goto("http://127.0.0.1:8766/video.html")
    pg.evaluate("window.ready")
    for t in ts:
        pg.evaluate(f"renderAt({t})")
        pg.screenshot(path=f"still_{t:05.2f}.png")
    b.close()
