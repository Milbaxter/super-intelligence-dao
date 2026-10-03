"""Mechanical quote check (CONTRACT §6) — security-critical.

`QuoteChecker.check(url, quote, value)` fetches the source (through an injectable fetcher),
normalizes the page text and returns
`{passed, reason, fetched_url, http_status, fetched_at, content_sha256}`.

The default `SafeFetcher` defends against SSRF: https only, every hop's hostname is
resolved and *all* resulting IPs must be public; the connection is then pinned to the
vetted IP (TLS SNI/cert still checked against the hostname) so DNS rebinding between
check and connect does not help an attacker. Redirects are followed manually (max 3),
re-validating each hop. Body is capped at 3 MB and the whole fetch at ~10 s.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from . import config, db

# Reasons where the source could not be evaluated (claim stays T0, not the agent's fault).
SOFT_FAIL_REASONS = {"unverifiable_format", "fetch_error", "timeout", "too_large"}

ALLOWED_CONTENT_TYPES = (
    "text/html", "text/plain", "text/markdown", "text/x-markdown",
    "application/json", "application/xhtml+xml",
)

_EXTRA_BLOCKED_NETS = [
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT (not flagged is_private)
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("fd00:ec2::/32"),  # AWS IMDS v6
]


class FetchError(Exception):
    def __init__(self, reason: str, message: str = "", status: int | None = None):
        super().__init__(message or reason)
        self.reason = reason
        self.status = status


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    content_type: str
    body: bytes


class Fetcher(Protocol):
    def __call__(self, url: str) -> FetchResult: ...


# --------------------------------------------------------------------------- SSRF


def ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
            or addr.is_reserved or addr.is_unspecified or not addr.is_global):
        return False
    return not any(addr in net for net in _EXTRA_BLOCKED_NETS if net.version == addr.version)


def _is_localhost(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1")


def validate_url(url: str, resolver: Callable[[str], list[str]], allow_http_localhost: bool = False) -> tuple[str, list[str]]:
    """Check scheme/host and resolve; returns (hostname, vetted_ips). Raises FetchError('blocked_url')."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        raise FetchError("blocked_url", "URL has no host")
    if parts.username or parts.password:
        raise FetchError("blocked_url", "credentials in URL are not allowed")
    if parts.scheme == "http" and allow_http_localhost and _is_localhost(host):
        return host, []  # test-only escape hatch, never enabled in production
    if parts.scheme != "https":
        raise FetchError("blocked_url", "only https URLs are fetched")
    try:
        port = parts.port
    except ValueError as e:
        raise FetchError("blocked_url", "invalid port") from e
    if port not in (None, 443):
        raise FetchError("blocked_url", "only the default https port (443) is fetched")
    try:
        ips = resolver(host)
    except OSError as e:
        raise FetchError("fetch_error", f"DNS resolution failed: {e}") from e
    if not ips:
        raise FetchError("fetch_error", "DNS returned no addresses")
    for ip in ips:
        if not ip_is_public(ip):
            raise FetchError("blocked_url", f"{host} resolves to non-public address {ip}")
    return host, ips


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def rewrite_url(url: str) -> list[str]:
    """Candidate URLs to try, in order (github blob → raw; arxiv abs/pdf → html fallback)."""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host in ("github.com", "www.github.com"):
        m = re.match(r"^/([^/]+)/([^/]+)/blob/(.+)$", p.path)
        if m:
            return [f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"]
    if host in ("arxiv.org", "www.arxiv.org"):
        m = re.match(r"^/(abs|pdf|html)/(.+?)(\.pdf)?/?$", p.path)
        if m:
            paper = m.group(2)
            if m.group(1) == "abs":
                return [url, f"https://arxiv.org/html/{paper}"]
            if m.group(1) == "pdf":
                return [f"https://arxiv.org/html/{paper}", f"https://arxiv.org/abs/{paper}"]
    return [url]


class SafeFetcher:
    """Production fetcher with SSRF protection, IP pinning, redirect re-validation and limits."""

    def __init__(self, resolver: Callable[[str], list[str]] = system_resolver,
                 allow_http_localhost: bool = False, timeout_s: float = config.FETCH_TIMEOUT_S,
                 max_bytes: int = config.FETCH_MAX_BYTES, max_redirects: int = config.FETCH_MAX_REDIRECTS):
        self.resolver = resolver
        self.allow_http_localhost = allow_http_localhost
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    def __call__(self, url: str) -> FetchResult:
        deadline = time.monotonic() + self.timeout_s
        current = url
        with httpx.Client(follow_redirects=False, timeout=self.timeout_s, trust_env=False) as client:
            for _hop in range(self.max_redirects + 1):
                host, ips = validate_url(current, self.resolver, self.allow_http_localhost)
                resp_status, headers, body = self._get_pinned(client, current, host, ips, deadline)
                if resp_status in (301, 302, 303, 307, 308):
                    loc = headers.get("location")
                    if not loc:
                        raise FetchError("fetch_error", "redirect without location", resp_status)
                    current = urljoin(current, loc)
                    continue
                ctype = headers.get("content-type", "").split(";")[0].strip().lower()
                return FetchResult(url=current, status=resp_status, content_type=ctype, body=body)
        raise FetchError("fetch_error", "too many redirects")

    def _get_pinned(self, client: httpx.Client, url: str, host: str, ips: list[str], deadline: float):
        parts = urlsplit(url)
        target = url
        extensions = {}
        headers = {"User-Agent": f"{config.SITE_NAME} quote-checker/0.1", "Accept": "text/html,text/plain,*/*;q=0.5"}
        if ips:  # pin the connection to the vetted IP, keep Host + SNI as the real hostname
            ip = ips[0]
            ip_host = f"[{ip}]" if ":" in ip else ip
            netloc = ip_host + (f":{parts.port}" if parts.port else "")
            target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
            headers["Host"] = host + (f":{parts.port}" if parts.port else "")
            extensions["sni_hostname"] = host
        try:
            req = client.build_request("GET", target, headers=headers, extensions=extensions)
            resp = client.send(req, stream=True)
        except httpx.TimeoutException as e:
            raise FetchError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise FetchError("fetch_error", str(e)) from e
        try:
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if resp.status_code in (301, 302, 303, 307, 308) or not _content_type_ok(ctype):
                return resp.status_code, resp.headers, b""  # don't download unusable bodies
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                raise FetchError("too_large", "response exceeds 3 MB", resp.status_code)
            chunks, total = [], 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > self.max_bytes:
                    raise FetchError("too_large", "response exceeds 3 MB", resp.status_code)
                if time.monotonic() > deadline:
                    raise FetchError("timeout", "fetch exceeded time budget", resp.status_code)
                chunks.append(chunk)
            return resp.status_code, resp.headers, b"".join(chunks)
        except httpx.TimeoutException as e:
            raise FetchError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise FetchError("fetch_error", str(e)) from e
        finally:
            resp.close()


def _content_type_ok(ctype: str) -> bool:
    return ctype in ALLOWED_CONTENT_TYPES or ctype == ""


# --------------------------------------------------------------------- normalize

_QUOTE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
}
_QUOTE_TRANS = str.maketrans(_QUOTE_MAP)
# Formatting characters dropped on BOTH sides so markdown/LaTeX/table rendering differences don't matter.
_DROP_CHARS = str.maketrans({c: None for c in "*`|#$"})


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1\s*>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return html.unescape(raw)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_TRANS).translate(_DROP_CHARS)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r" (?=[%,.;:)])", "", text).strip().lower()


_EMBEDDED_HTML = re.compile(r"(?i)</?(table|tr|td|th|thead|tbody|div|p|br|span|sup|sub|b|strong|em|i|a|img|details|summary)\b[^>]*>")


def page_texts(result: FetchResult) -> list[str]:
    """Normalized page text(s) a quote may match. HTML is tag-stripped. Markdown/plain text that embeds HTML
    (e.g. model-card READMEs with <table> results) is matched both raw and tag-stripped, since a quote may be
    copied from the rendered page or from the source."""
    raw = result.body.decode("utf-8", errors="replace")
    if result.content_type in ("text/html", "application/xhtml+xml") or (
        result.content_type == "" and "<html" in raw[:2000].lower()
    ):
        return [normalize(html_to_text(raw))]
    texts = [normalize(html.unescape(raw))]
    if _EMBEDDED_HTML.search(raw):
        texts.append(normalize(html_to_text(raw)))
    return texts


def page_text(result: FetchResult) -> str:
    return page_texts(result)[0]


def value_formats(value: float) -> list[str]:
    """Common renderings of a number: 72.4 → 72.4, 72.40, 0.724 ...; 0.724 → 72.4 too."""
    out: set[str] = set()

    def add(v: float):
        for places in range(0, 4):
            s = f"{v:.{places}f}"
            if float(s) == round(v, places) and abs(float(s) - v) < 1e-9:
                out.add(s)
                if "." in s:
                    out.add(s.rstrip("0").rstrip("."))
        out.add(f"{v:g}")

    add(value)
    if abs(value) > 1:
        add(value / 100)
    if abs(value) <= 1:
        add(value * 100)
    # Allow leading-zero-less fractions (".724")
    out |= {s[1:] for s in out if s.startswith("0.")}
    return sorted(out, key=len, reverse=True)


def value_in_text(value, text: str) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        norm = text.replace(",", "")
        for f in value_formats(float(value)):
            if re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", norm):
                return True
        return False
    v = normalize(str(value))
    return bool(v) and v in normalize(text)


_NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.(\d+))?)\s*(%?)")


def quote_ambiguity(quote: str, value) -> bool:
    """True when the quote holds ≥ AMBIGUOUS_QUOTE_MIN_NUMBERS numbers in the same format as `value`
    (same decimal places and %-ness) — typically a flattened table row where the column is not evident."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    toks = [(float(m.group(1)), len(m.group(2) or ""), m.group(3)) for m in _NUM_RE.finditer(quote.replace(",", ""))]
    v = float(value)
    mine = [t for t in toks if any(abs(t[0] - x) < 1e-9 for x in (v, v * 100, v / 100))]
    if not mine:
        return False
    fmt = mine[0][1:]
    return sum(1 for t in toks if t[1:] == fmt) >= config.AMBIGUOUS_QUOTE_MIN_NUMBERS


# --------------------------------------------------------------------- checker


class QuoteChecker:
    """Runs the mechanical check with a 1 h per-URL page cache.

    Thread-safe: the cache is lock-protected and concurrent requests for the same URL share one
    in-flight fetch (the first caller fetches, the others wait on its Future)."""

    def __init__(self, fetcher: Fetcher | None = None, cache_ttl_s: float = config.FETCH_CACHE_TTL_S):
        self.fetcher: Fetcher = fetcher or SafeFetcher()
        self.cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[float, dict]] = {}
        self._inflight: dict[str, Future] = {}
        self._lock = threading.Lock()

    def _get_page(self, url: str) -> dict:
        """Returns {ok, reason, text, url, status, sha}. Cached (including failures) for 1 h."""
        with self._lock:
            hit = self._cache.get(url)
            if hit and time.monotonic() - hit[0] < self.cache_ttl_s:
                return hit[1]
            fut = self._inflight.get(url)
            owner = fut is None
            if owner:
                fut = self._inflight[url] = Future()
        if not owner:
            return fut.result()  # bounded by the owner's fetch (SafeFetcher has its own timeout)
        try:
            page = self._fetch_page(url)
        except BaseException as e:  # never strand waiters on an unexpected error
            with self._lock:
                self._inflight.pop(url, None)
            fut.set_exception(e)
            raise
        with self._lock:
            self._cache[url] = (time.monotonic(), page)
            self._inflight.pop(url, None)
        fut.set_result(page)
        return page

    def _fetch_page(self, url: str) -> dict:
        try:
            res = self.fetcher(url)
            if res.status >= 400:
                soft = res.status in (401, 403, 429) or res.status >= 500
                return {"ok": False, "reason": "fetch_error" if soft else "http_error", "url": res.url, "status": res.status}
            if res.content_type == "application/pdf" or not _content_type_ok(res.content_type):
                return {"ok": False, "reason": "unverifiable_format", "url": res.url, "status": res.status}
            return {"ok": True, "reason": "ok", "url": res.url, "status": res.status,
                    "texts": page_texts(res), "sha": hashlib.sha256(res.body).hexdigest()}
        except FetchError as e:
            return {"ok": False, "reason": e.reason, "url": url, "status": e.status, "message": str(e)}

    def check_many(self, items: list[tuple], workers: int | None = None, deadline_s: float | None = None) -> list[dict]:
        """Run `check(*item)` for each (url, quote, value) concurrently; results keep input order.

        Checks not finished within `deadline_s` (default config.PRECHECK_DEADLINE_S) get a soft-fail
        "timeout" result. Their threads are not waited on; each is bounded by the fetcher's own timeout."""
        if not items:
            return []
        workers = workers or config.PRECHECK_WORKERS
        deadline_s = config.PRECHECK_DEADLINE_S if deadline_s is None else deadline_s
        pool = ThreadPoolExecutor(max_workers=min(workers, len(items)), thread_name_prefix="quotecheck")
        try:
            futs = [pool.submit(self.check, *item) for item in items]
            wait_futures(futs, timeout=deadline_s)
            out = []
            for fut in futs:
                if fut.done():
                    out.append(fut.result())  # unexpected exceptions propagate, as with a sequential check
                else:
                    out.append({"passed": False, "reason": "timeout", "fetched_url": None, "http_status": None,
                                "fetched_at": db.now_ts(), "content_sha256": None,
                                "detail": f"check did not finish within the {deadline_s:g} s submission deadline"})
            return out
        finally:
            pool.shutdown(wait=False, cancel_futures=True)  # drop queued checks; running ones end on fetch timeout

    def check(self, source_url: str, quote: str, value=None) -> dict:
        """Mechanical check. `value` may be a number (format-tolerant) or a string, or None to skip."""
        result = {"passed": False, "reason": "", "fetched_url": None, "http_status": None,
                  "fetched_at": db.now_ts(), "content_sha256": None}
        quote = (quote or "").strip()
        if not (config.QUOTE_MIN_CHARS <= len(quote) <= config.QUOTE_MAX_CHARS):
            result["reason"] = "quote_length"
            return result
        if value is not None and not value_in_text(value, quote):
            result["reason"] = "value_not_in_quote"
            return result
        nq = normalize(quote)
        last, any_ok = None, False
        for candidate in rewrite_url(source_url):
            page = self._get_page(candidate)
            last, any_ok = page, any_ok or page["ok"]
            result.update(fetched_url=page.get("url"), http_status=page.get("status"),
                          content_sha256=page.get("sha"))
            if page["ok"] and any(nq in t for t in page["texts"]):
                result.update(passed=True, reason="ok")
                return result
        if last and not any_ok:
            result["reason"] = last["reason"]
            if last.get("message"):
                result["detail"] = last["message"][:200]
        else:
            result["reason"] = "quote_not_found"
        return result
