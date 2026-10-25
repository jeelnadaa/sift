"""Render every frame of video.html (30 fps) straight into ffmpeg."""
import subprocess
from playwright.sync_api import sync_playwright

FPS, DUR = 30, 32.0
N = int(FPS * DUR)
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
                       "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), "video_only.mp4"],
                      stdin=subprocess.PIPE)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.on("pageerror", lambda e: print("pageerror:", e))
    pg.goto("http://127.0.0.1:8766/video.html")
    pg.evaluate("window.ready")
    for i in range(N):
        pg.evaluate(f"renderAt({i / FPS})")
        ff.stdin.write(pg.screenshot(type="png"))
        if i % 120 == 0:
            print("frame", i, flush=True)
    b.close()
ff.stdin.close()
ff.wait()
print("done", ff.returncode)
