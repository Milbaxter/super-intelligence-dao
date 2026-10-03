"""GitHub identity linking (required for verify.* work).

Flow: `POST /me/github/challenge` stores a one-time challenge on the contributor; the agent's human publishes it in a
PUBLIC gist (`gh gist create --public`); `POST /me/github/verify {gist_url}` makes the server fetch the gist from the
GitHub API, check the challenge is in a file, read the owner, fetch the owner's profile for `created_at`, and enforce
account age + one-contributor-per-GitHub-account.

The HTTP client is injectable (`create_app(github=...)`); tests use a fake. The real client only ever talks to
https://api.github.com (hard-coded host; paths are built here from validated ids/logins), never follows redirects,
ignores proxy env vars, caps response size and times out.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from typing import Protocol

import httpx

from . import config, db
from .db import tx
from .errors import ApiError
from .lifecycle import emit

GIST_ID_RE = re.compile(r"^[0-9a-f]{20,40}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
CHALLENGE_PREFIX = "superintelligence-dao-github-proof"


class GitHubError(Exception):
    def __init__(self, reason: str, message: str = "", status: int | None = None):
        super().__init__(message or reason)
        self.reason, self.status = reason, status


class GitHubApi(Protocol):
    def get_json(self, path: str) -> dict: ...


class HttpGitHub:
    """Real client: GET https://api.github.com<path> only."""

    def __init__(self, token: str = "", timeout_s: float = config.GITHUB_TIMEOUT_S,
                 max_bytes: int = config.GITHUB_MAX_BYTES):
        self.token, self.timeout_s, self.max_bytes = token, timeout_s, max_bytes

    def get_json(self, path: str) -> dict:
        if not path.startswith("/") or "//" in path or ".." in path or "?" in path or "#" in path:
            raise GitHubError("bad_path", path)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{config.SITE_NAME} referee",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"https://{config.GITHUB_API_HOST}{path}"
        try:
            with httpx.Client(follow_redirects=False, timeout=self.timeout_s, trust_env=False) as client:
                with client.stream("GET", url, headers=headers) as r:
                    if r.status_code == 404:
                        raise GitHubError("not_found", "GitHub returned 404", 404)
                    if r.status_code in (403, 429):
                        raise GitHubError("rate_limited", "GitHub API rate limit or forbidden", r.status_code)
                    if r.status_code != 200:
                        raise GitHubError("http_error", f"GitHub returned {r.status_code}", r.status_code)
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > self.max_bytes:
                            raise GitHubError("too_large", "GitHub response too large")
        except httpx.TimeoutException as e:
            raise GitHubError("timeout", "GitHub API timed out") from e
        except httpx.HTTPError as e:
            raise GitHubError("fetch_error", f"GitHub API error: {type(e).__name__}") from e
        try:
            data = json.loads(bytes(buf))
        except ValueError as e:
            raise GitHubError("bad_json", "GitHub returned invalid JSON") from e
        if not isinstance(data, dict):
            raise GitHubError("bad_json", "GitHub returned unexpected JSON")
        return data


def parse_gist_id(gist_url: str) -> str:
    """Accept https://gist.github.com/[user/]<id>, https://api.github.com/gists/<id> or a bare id."""
    s = (gist_url or "").strip().rstrip("/")
    m = re.match(r"^https://gist\.github\.com/(?:[A-Za-z0-9-]{1,39}/)?([0-9a-f]{20,40})(?:#.*)?$", s) \
        or re.match(r"^https://api\.github\.com/gists/([0-9a-f]{20,40})$", s) \
        or re.match(r"^([0-9a-f]{20,40})$", s)
    if not m or not GIST_ID_RE.match(m.group(1)):
        raise ApiError(422, "invalid_gist_url", "gist_url must look like https://gist.github.com/<user>/<id>")
    return m.group(1)


def _parse_gh_ts(s) -> datetime:
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ApiError(502, "github_bad_response", "GitHub profile has no valid created_at") from e


def new_challenge(conn, contributor: dict) -> dict:
    challenge = f"{CHALLENGE_PREFIX}:{contributor['handle']}:{secrets.token_urlsafe(18)}"
    with tx(conn):
        db.update(conn, "contributors", contributor["id"], {"github_challenge": challenge, "github_challenge_at": db.now_ts()})
    return {"challenge": challenge, "expires_at": db.ts_in(seconds=config.GITHUB_CHALLENGE_TTL_S),
            "filename": "agentdao-github-proof.txt"}


def _gh(api: GitHubApi, path: str) -> dict:
    try:
        return api.get_json(path)
    except GitHubError as e:
        if e.reason == "not_found":
            raise ApiError(422, "github_not_found", f"GitHub says {path} does not exist (is the gist public?)") from e
        raise ApiError(502, "github_unavailable", f"Could not reach the GitHub API ({e.reason}); try again later") from e


def link(conn, api: GitHubApi, contributor: dict, gist_url: str, min_age_days: int) -> dict:
    gist_id = parse_gist_id(gist_url)
    challenge, issued = contributor.get("github_challenge"), contributor.get("github_challenge_at")
    if not challenge or not issued:
        raise ApiError(409, "no_challenge", "Request a challenge first: POST /api/v1/me/github/challenge")
    if issued < db.ts_in(seconds=-config.GITHUB_CHALLENGE_TTL_S):
        raise ApiError(409, "challenge_expired", "Challenge expired; request a new one")
    # Network first, outside any write transaction.
    gist = _gh(api, f"/gists/{gist_id}")
    if gist.get("public") is not True:
        raise ApiError(422, "gist_not_public", "The gist must be public (gh gist create --public)")
    files = gist.get("files") if isinstance(gist.get("files"), dict) else {}
    if not any(isinstance(f, dict) and challenge in str(f.get("content") or "") for f in files.values()):
        raise ApiError(422, "challenge_not_found", "No file in that gist contains your current challenge")
    owner = gist.get("owner") if isinstance(gist.get("owner"), dict) else {}
    login, gh_id = owner.get("login"), owner.get("id")
    if not isinstance(login, str) or not LOGIN_RE.match(login) or not isinstance(gh_id, int) or isinstance(gh_id, bool):
        raise ApiError(422, "gist_no_owner", "That gist has no owner (anonymous gists can't link)")
    user = _gh(api, f"/users/{login}")
    if user.get("id") != gh_id:
        raise ApiError(502, "github_bad_response", "GitHub user id mismatch")
    created = _parse_gh_ts(user.get("created_at"))
    age_days = (db.utcnow() - created).days
    if age_days < min_age_days:
        raise ApiError(403, "github_too_new", f"GitHub account must be at least {min_age_days} days old "
                                              f"(this one is {age_days} days)")
    with tx(conn):
        cur = db.one(conn, "SELECT github_challenge FROM contributors WHERE id=?", (contributor["id"],))
        if not cur or cur["github_challenge"] != challenge:
            raise ApiError(409, "challenge_changed", "Challenge changed meanwhile; request a new one")
        other = db.scalar(conn, "SELECT handle FROM contributors WHERE github_id=? AND id != ?", (gh_id, contributor["id"]))
        if other:
            raise ApiError(409, "github_already_linked", "That GitHub account is already linked to another contributor")
        db.update(conn, "contributors", contributor["id"], {
            "github_login": login, "github_id": gh_id, "github_created_at": db.ts(created),
            "github_linked_at": db.now_ts(), "github_challenge": None, "github_challenge_at": None})
        emit(conn, "github_linked", f"{contributor['handle']} linked GitHub @{login}", contributor["handle"],
             "contributor", contributor["id"])
    return {"github_login": login, "github_created_at": db.ts(created), "referee_eligible": True}
