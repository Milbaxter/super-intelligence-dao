"""FastAPI app factory: API under /api/v1, agent protocol files, static web/ at /."""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import mimetypes
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import api_admin, api_agent, api_public, config, db
from .deps import bearer, hash_key
from .errors import ApiError
from .github import GitHubApi, HttpGitHub
from .verify import Fetcher, QuoteChecker, SafeFetcher

API_PREFIX = "/api/v1"


def _err(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


class BodySizeLimit:
    """Pure ASGI middleware: reject request bodies over the limit (header or streamed)."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > self.max_bytes:
                return await _err(413, "payload_too_large", f"Body exceeds {self.max_bytes} bytes")(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    raise ApiError(413, "payload_too_large", f"Body exceeds {self.max_bytes} bytes")
            return msg

        await self.app(scope, limited_receive, send)


class RateLimiter:
    """Sliding 60 s window per key. In-memory, per process — good enough for Phase 0."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50_000:  # crude memory guard
                self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v and now - v[-1] < 60})
            return True


def _not_built(what: str) -> HTMLResponse:
    what = html.escape(what)  # `what` contains the request path: never reflect it unescaped (XSS)
    return HTMLResponse(f"<!doctype html><title>Not found</title><p>{what} not found. "
                        f"If this is a fresh checkout, the file may not be written yet. API: <a href='/api/v1/stats'>/api/v1/stats</a></p>",
                        status_code=404)


_INLINE_SCRIPT = re.compile(r"(?is)<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>")


def _inline_script_hashes(web_dir: Path) -> list[str]:
    """CSP hashes for the small inline scripts in web/*.html (e.g. the theme bootstrap), computed at startup."""
    out: set[str] = set()
    for f in sorted(web_dir.glob("*.html")) if web_dir.is_dir() else []:
        for body in _INLINE_SCRIPT.findall(f.read_text(encoding="utf-8", errors="replace")):
            out.add("'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'")
    return sorted(out)


def build_csp(web_dir: Path) -> str:
    scripts = " ".join(["'self'", *_inline_script_hashes(web_dir)])
    return ("default-src 'self'; "
            f"script-src {scripts}; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _startup_sweep(db_path: str) -> None:
    """Apply the active applicability rules to existing open tasks (idempotent; old DBs get cleaned on deploy)."""
    from . import council
    conn = db.connect(db_path)
    try:
        council.startup_sweep(conn)
    finally:
        conn.close()


def create_app(settings: config.Settings | None = None, fetcher: Fetcher | None = None,
               github: GitHubApi | None = None) -> FastAPI:
    settings = settings or config.Settings()
    db.init_db(settings.db_path)
    _startup_sweep(settings.db_path)
    app = FastAPI(title=f"{config.SITE_NAME} API", version=config.SKILL_VERSION, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.settings = settings
    if fetcher is None and settings.allow_local_sources:
        fetcher = SafeFetcher(allow_http_localhost=True)  # dev/test only (SIDAO_/AGENTDAO_ALLOW_LOCAL_SOURCES=1)
    app.state.checker = QuoteChecker(fetcher)
    app.state.github = github or HttpGitHub(token=settings.github_token)  # injectable: tests never hit the network
    limiter = RateLimiter()
    csp = build_csp(settings.web_dir)
    if settings.steward_key == config.DEV_STEWARD_KEY:
        logging.getLogger("agentdao").warning("SIDAO_STEWARD_KEY (alias AGENTDAO_STEWARD_KEY) is the public dev default %r; set a real key "
                                              "before exposing this server.", config.DEV_STEWARD_KEY)
    if settings.ip_salt == config.DEFAULT_IP_SALT:
        # The salt keys the HMAC in contributors.registered_ip_hash. A public salt makes those hashes brute-forceable
        # (the IPv4 space is only 2^32), so anyone holding a DB copy or backup could recover registration IPs.
        logging.getLogger("agentdao").warning("SIDAO_IP_SALT (alias AGENTDAO_IP_SALT) is the public default %r; stored IP hashes can be "
                                              "brute-forced back to IPs. Set a random secret salt in production.",
                                              config.DEFAULT_IP_SALT)

    @app.exception_handler(ApiError)
    async def _api_error(_req, exc: ApiError):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")} for e in exc.errors()]
        return _err(422, "validation_error", "Request validation failed", fields=fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _err(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_req, exc: Exception):
        return _err(500, "internal_error", "Internal server error")

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        path = request.url.path
        if path.startswith(API_PREFIX):
            token = bearer(request)
            ip = request.client.host if request.client else "?"
            if token:
                key, limit = "k:" + hash_key(token), settings.rate_agent_per_min
            elif request.method == "GET":
                key, limit = "ip:" + ip, settings.rate_public_per_min
            else:
                key, limit = "ipw:" + ip, settings.rate_agent_per_min
            # Per-IP ceiling on top of the per-key bucket, so rotating made-up bearer tokens can't bypass limits.
            if not limiter.allow(key, limit) or (token and not limiter.allow("ipall:" + ip, settings.rate_public_per_min)):
                return _err(429, "rate_limited", f"Too many requests (limit {limit}/min)")
        resp = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if not path.startswith("/api/") and resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers.setdefault("Content-Security-Policy", csp)
        return resp

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
    app.add_middleware(BodySizeLimit, max_bytes=config.MAX_BODY_BYTES)

    app.include_router(api_public.router, prefix=API_PREFIX)
    app.include_router(api_agent.router, prefix=API_PREFIX)
    app.include_router(api_admin.router, prefix=API_PREFIX)

    @app.get("/skill-version", include_in_schema=False)
    @app.get(API_PREFIX + "/skill-version", include_in_schema=False)
    def skill_version():
        return {"version": config.SKILL_VERSION, "sha256": config.skill_sha256(settings)}

    @app.get(API_PREFIX + "/{rest:path}", include_in_schema=False)
    def _api_404(rest: str):
        raise ApiError(404, "not_found", f"No API route /{rest}")

    # ---- agent protocol files -------------------------------------------------
    @app.get("/join.md", include_in_schema=False)
    def join_md():
        text = config.render_agent_file(settings, "join.md")
        if text is None:
            return _not_built("agent/join.md")
        return Response(text, media_type="text/markdown; charset=utf-8")

    @app.get("/task-types/{task_type}.md", include_in_schema=False)
    def task_type_md(task_type: str):
        if task_type not in config.TASK_TYPES:
            return _not_built(f"task type {task_type!r}")
        text = config.render_agent_file(settings, f"task-types/{task_type}.md")
        if text is None:
            return _not_built(f"agent/task-types/{task_type}.md")
        return Response(text, media_type="text/markdown; charset=utf-8")

    # ---- static web/ ------------------------------------------------------------
    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str):
        web = settings.web_dir.resolve()
        rel = path.strip("/") or "index.html"
        target = (web / rel).resolve()
        if target.is_dir():
            target = target / "index.html"
        elif not target.exists() and not Path(rel).suffix:
            target = (web / f"{rel}.html").resolve()  # /map → map.html
        hidden = any(part.startswith(".") for part in target.relative_to(web).parts) if target.is_relative_to(web) else True
        if hidden or not target.is_file():  # no traversal, no dotfiles (.DS_Store, .env, ...)
            return _not_built(f"/{rel}")
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            mime = "text/javascript"
        # no-cache = always revalidate (ETag), so a deploy is visible immediately; no build step to fingerprint assets.
        return FileResponse(target, media_type=mime, headers={"Cache-Control": "no-cache"})

    return app
