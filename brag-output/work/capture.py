"""Capture the real web app's rendered pages (fictional data on the throwaway server) as inert HTML."""
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

WORK = Path(__file__).parent
BASE = "http://127.0.0.1:8010"
email, pw = (WORK / "video-cred.txt").read_text().split()[:2]
ids = dict(a.split("=") for a in sys.argv[1:])

req = urllib.request.Request(f"{BASE}/api/v1/auth/login", data=json.dumps({"email": email, "password": pw}).encode(),
                             headers={"Content-Type": "application/json"})
token = json.load(urllib.request.urlopen(req))["token"]

# the app's own built assets (CSS bundle, fonts), served next to the video page
dist = Path(r"D:\inbox-app\web\dist")
shutil.rmtree(WORK / "app", ignore_errors=True)
shutil.copytree(dist, WORK / "app")

PAGES = {
    "feed": "/app/",
    "timeline": f"/app/opportunities/{ids['acme']}",
    "folders": f"/app/folders/{ids['places']}",
    "mail": f"/app/mail/{ids['test']}",
}

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
    ctx.add_init_script(f"""localStorage.setItem('sift.token', {json.dumps(token)});
        localStorage.setItem('sift.email', {json.dumps(email)}); localStorage.setItem('sift.sidebar', '0');""")
    page = ctx.new_page()
    for name, path in PAGES.items():
        page.goto(BASE + path)
        page.wait_for_load_state("load")
        page.wait_for_selector("main .top h1", timeout=15000)
        page.wait_for_timeout(2500)  # data loads (the live-updates stream keeps the network busy by design)
        if name == "folders":
            page.click(".tree .tw")  # open Placements to show its company subfolders
            page.wait_for_timeout(400)
            page.locator("[aria-label='Include subfolders']").last.click()  # the list shows the mail in them
            page.wait_for_timeout(1800)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(800)  # entrance animations finish (the app's CSP rightly blocks injected styles)
        html = page.evaluate("document.documentElement.outerHTML")
        html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)  # inert: no scripts
        (WORK / f"snap_{name}.html").write_text("<!doctype html>\n" + html, encoding="utf-8")
        page.screenshot(path=str(WORK / f"snap_{name}.png"))
        print("captured", name)
    b.close()
