"""HTTP hardening for the hosted app (v6 Phase 6 security review).

- **Files served back to the browser** — pasted images, staged images,
  proxied tracker attachments — render inline only when they are raster
  images; anything else downloads, so nothing a user or a tracker supplies
  can run as a page on WorkTimer's origin. Always with nosniff and a
  sandboxing CSP.
- **Cross-site requests:** the Access cookie rides along on any request the
  browser sends, so a state-changing request (POST, PUT, PATCH, DELETE) that
  another site started is refused — Sec-Fetch-Site, else Origin against
  Host. Every response forbids framing (clickjacking) and cross-site
  referrers.
"""

from pathlib import PurePath
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
FILE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
    "Cache-Control": "private, max-age=3600",
}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def image_type(filename: str | None = None, content_type: str | None = None) -> str | None:
    """The raster image type of a file by its reported type, else its name —
    None for anything else (SVG and HTML included)."""
    reported = (content_type or "").split(";")[0].strip().lower()
    if reported in IMAGE_TYPES.values():
        return reported
    return IMAGE_TYPES.get(PurePath(filename or "").suffix.lower()) if not reported else None


def file_response(content: bytes, filename: str | None = None,
                  content_type: str | None = None) -> Response:
    """Bytes for the browser: an image inline, anything else as a download."""
    ctype = image_type(filename, content_type)
    headers = dict(FILE_HEADERS)
    if ctype is None:
        ctype = "application/octet-stream"
        headers["Content-Disposition"] = "attachment"
    return Response(content=content, media_type=ctype, headers=headers)


def is_cross_site(request: Request) -> bool:
    """A state-changing request another site started (a browser's word for it)."""
    if request.method in SAFE_METHODS:
        return False
    site = request.headers.get("sec-fetch-site")
    if site:
        return site not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if not origin:
        return False  # no browser marker at all: not a browser's cross-site request
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    return urlsplit(origin).netloc not in hosts


def install(app) -> None:
    """Add the cross-site guard and the page headers to the app."""

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if is_cross_site(request):
            return JSONResponse({"error": "cross-site request refused"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
