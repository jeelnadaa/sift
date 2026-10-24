"""Serves the React web UI (web/, built with `npm run build`) at /app from the same origin as
the API, so it shares sign-in and needs no CORS. Unknown paths under /app get index.html
(client-side routes). Every page carries a strict Content-Security-Policy: scripts only from
this origin, no inline script, no framing; mail text is rendered as text, never as HTML.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.config import get_settings

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def dist_dir() -> Path:
    configured = get_settings().web_dist
    if configured:
        return Path(configured)
    here = Path(__file__).resolve().parent.parent  # backend/
    for candidate in (here.parent / "web" / "dist", here / "web"):  # checkout, then Docker image
        if (candidate / "index.html").exists():
            return candidate
    return here.parent / "web" / "dist"


def mount(app: FastAPI) -> None:
    root = dist_dir().resolve()

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/app/")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    def web(path: str = ""):
        index = root / "index.html"
        if not index.exists():
            return HTMLResponse("<h1>Sift web UI is not built</h1><p>Run <code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>.</p>",
                                status_code=503, headers=HEADERS)
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            # hashed build assets never change; everything else is revalidated
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={**HEADERS, "Cache-Control": cache})
        return FileResponse(index, headers={**HEADERS, "Cache-Control": "no-cache"})
