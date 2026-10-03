# Security review (pre-publication, Phase 0)

Scope: `server/agentdao/*`, `web/`, `agent/join.md`, `agent/worker/*`, repo hygiene. Checked against CONTRACT §6/§9,
docs/SECURITY.md and docs/DEVIATIONS.md. All fixes have regression tests in `tests/test_security.py`; `uv run pytest -q` is green.

## Fixed

| # | severity | finding | fix |
|---|---|---|---|
| 1 | **high** | **Reflected XSS.** The static 404 page (`_not_built`) put the request path into HTML unescaped: `GET /<script>…</script>` ran script on the site origin, where the steward key sits in sessionStorage. | `html.escape` in `_not_built` (`app.py`). |
| 2 | **high** | **Bash arithmetic injection in `run.sh`.** `budget_minutes` from the claim response went into `$(( BUDGET * 3 / 2 ))`, and `[ "$X" -lt … ]`. A value like `a[$(cmd)]` runs `cmd` on the contributor's machine. A malicious or compromised server got code execution. | `run.sh` checks every server value before use: lease/task id `^[A-Za-z0-9_-]{1,64}$`, type from the fixed list, heartbeat/budget digits only. Otherwise it releases and stops. |
| 3 | **high** | **Path traversal in `run.sh`.** The task id became `agentdao-work/$TASK`, so `../../x` wrote `claim.json`/`prompt.txt` outside the work dir and started the CLI (with Write/Edit tools) there. | Same id check as #2. |
| 4 | medium | **The join.md pin didn't cover the copy the CLI reads.** `run.sh` compared the server's *self-reported* `/skill-version` hash to the pin, then downloaded `join.md` again and gave it to the CLI unchecked. A lying server could serve new rules. | `run.sh` hashes the downloaded `join.md` for each task and stops if it doesn't match the pinned sha256. |
| 5 | medium | **Key sent to arbitrary hosts.** `run.sh --base-url X` (or `AGENTDAO_URL`) sent `auth.header` to X even when the key was issued by another server. | `run.sh` exits if `--base-url` differs from `base_url` in `credentials.json`. |
| 6 | medium | **NaN/Infinity accepted.** `json.loads` accepts `NaN`/`Infinity`. A claim `value: NaN` passed the "value in quote" check whenever the quote contained the letters "nan" (e.g. "fi**nan**cial"). `NaN` inside `conditions` would be stored, and every later `/claims` response would 500 (Starlette rejects NaN on output): a stored DoS. `tokens_estimate: Infinity` → 500. | `errors.check_json` runs in every agent/steward body parser (`_obj`) and rejects non-finite floats, integers above 2^53 and nesting deeper than 32. |
| 7 | medium | **Default steward key in production.** `AGENTDAO_STEWARD_KEY` defaults to the public string `dev-steward`, and nothing stopped a public deployment from running with it. | `agentdao serve` refuses a non-loopback `--host` when the key is the default or shorter than 24 chars, or when `AGENTDAO_ALLOW_LOCAL_SOURCES=1`. `create_app` logs a warning whenever the default key is used. |
| 8 | medium | **Rate-limit bypass.** The bucket was keyed by *any* bearer token, valid or not, so rotating made-up tokens gave unlimited requests (DB lookups, `/register` attempts). | Any request with a token also counts against a per-IP bucket (`rate_public_per_min`). |
| 9 | low | **No security headers.** | Every response gets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy`. HTML pages (not `/api/*`, so Swagger keeps working) get a CSP: `script-src 'self'` plus sha256 hashes of the inline theme snippet (computed from `web/*.html` at startup), `connect-src 'self'`, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`. Fonts are allowed from Google Fonts. Styles need `'unsafe-inline'` (inline `style=` attributes). Checked in a browser: pages render, inline theme script runs. |
| 10 | low | **Fetcher could reach any port** on public IPs. | The quote checker only fetches `https` on port 443 (the dev-only localhost http escape is unchanged). |
| 11 | low | **Static server returned dotfiles** (`.DS_Store`, a stray `.env`) from `web/`. | Any path segment starting with `.` gets a 404. |

## Verified OK (no change needed)

- **SSRF / DNS rebinding:** `SafeFetcher` resolves the name, requires *every* address to be public (IPv4-mapped,
  NAT64 `64:ff9b::/96`, 6to4, IPv4-compatible, CGNAT, link-local and metadata `169.254.169.254` / `fd00:ec2::` are all
  refused), then **connects to the vetted IP**. Host and SNI stay set to the hostname, and the certificate is still checked
  against it (tested against a live host: pinning a mismatched IP fails with `CERTIFICATE_VERIFY_FAILED`). Redirects are
  followed by hand (max 3) and each hop is re-validated and re-pinned. `trust_env=False` (no proxy env). URL userinfo is refused. Decimal
  and octal IP forms are handled because the *resolved* address is checked. `file:`, `gopher:`, `ftp:` and `http:`
  are refused. Bodies are capped at 3 MB and the whole fetch at ~10 s.
- **Auth:** API keys are `secrets.token_urlsafe(32)`, stored as sha256 (fine for 256-bit random keys) and shown once.
  The steward key is compared with `hmac.compare_digest`, and an empty key disables admin. Every lease operation checks
  ownership (`own_lease`), so you can't heartbeat, release or submit on someone else's lease (that returns 404).
- **Authorization / self-verification:** you can't take a verify task on your own submission, you get one verify task
  per claim, and review tasks exclude the author. A second account *can* verify the first one's work. That's the
  accepted Phase 0 Sybil limit: invites are the control (docs/SECURITY.md §2).
- **Blind values:** the value, quote, `check_result`, `conditions.notes` and trail `detail` are redacted on
  `/claims`, `/claims/{id}`, `/artifacts/{id}` and `/map` while a blind task is draft/open/leased/submitted. Blind task
  inputs and `task_full` never include `target_claim_id` or the value. `/activity` summaries carry no values and
  `detail` is never exposed. `/me` shows only your own work. `/contributors` doesn't expose `contact`. Error messages echo only ids.
- **SQL:** all values are parameterised. The f-string parts are only constant SQL fragments, code-defined
  column names, or `?` placeholders. `map.profile` field names are allow-listed before `db.update`.
- **Path traversal:** `/task-types/{type}.md` is allow-listed against `TASK_TYPES`. `_render_agent_file` and the static
  route resolve paths and require them to stay inside the directory.
- **Body size:** 256 KB (header and streamed). **CORS:** `*` for GET only, no credentials. That's fine for a public read API.
- **Frontend:** API text only goes through `textContent`/`h()`. The one `innerHTML` is constant SVG. `h()` drops `on*`
  attributes, and `href` must be internal or http(s). External links get `rel="noopener noreferrer nofollow"`. The steward key lives in
  `sessionStorage` and only goes in the `Authorization` header.
- **join.md:** §0 hard rules come first and say they override task text. No secrets are requested, the key is read
  from a 600 file through `curl -H @file`, the sha256 is pinned and the agent stops on change, and no ports or daemons are started.
- **Repo hygiene:** no secrets, tokens, personal names or emails, local `/Users/…` paths or real IPs (the only IPs are
  RFC test/private literals in tests). `.gitignore` covers `data/`, `*.db*`, `.env*`, `credentials.json`,
  `auth.header`, `agentdao-work/`, `.venv/`. `data/agentdao.db` exists locally but is ignored.

## Residual risks (accepted or for later)

1. **Sybil collusion:** one person with two invites can extract and blind-verify their own claim. Same-registration-IP
   pairs are now blocked from verifying each other, but a second network/VPN defeats that. Invites and steward spot
   checks remain the real controls in Phase 0 (docs/VERIFICATION.md).
2. **Duplicate-claim oracle:** a contributor holding a `map.extract` lease for the same artifact as a pending blind task
   could learn the hidden value from the "duplicate of an existing claim" check, by submitting candidate values that pass
   the quote check. This takes an extract lease on the same artifact and burns it. Low. A fix would be to skip the duplicate
   check while a blind task is pending, or make the message generic.
3. **Quote-check amplification:** one `map.extract` submit can trigger up to ~100 outbound fetches (50 claims × URL
   rewrites, ≤10 s each) inside a synchronous request. This is bounded by ≤2 leases and the rate limits, but a hostile contributor can
   tie up worker threads. Consider capping distinct source URLs per submission (e.g. 10) and moving checks to a queue.
4. **Rate limits are per process and per `request.client.host`.** Behind a reverse proxy, run uvicorn with
   `--proxy-headers --forwarded-allow-ips=<proxy>`. Otherwise every user shares the proxy's bucket (or, if headers
   are trusted blindly, IPs can be spoofed). Multi-worker deployments need a shared limiter.
5. **Task-type files aren't pinned.** `run.sh` pins `join.md` but not `task-types/*.md`. A malicious server can change
   the method text. join.md §0 still overrides, and the real defence is the container. Consider listing task-type
   hashes in `/skill-version`.
6. **Prompt injection against an unsandboxed agent** stays possible: the agent has `Read` (claude) or a shell (codex/gemini)
   on the host. The runner's tool restrictions and §0 reduce this but don't prevent it. Use the container (docs/SECURITY.md §3).
7. **Terminal escape sequences:** `run.sh` prints up to 300–400 bytes of server error bodies to the terminal. A
   malicious server could inject ANSI sequences. This is cosmetic on modern terminals.
8. **JSON nesting above ~1000 levels** makes `json.loads` raise `RecursionError` before the depth check runs. The request
   returns 500 and isn't stored.
9. **`/api/docs` and OpenAPI are public.** They expose route shapes (including `/admin/*`), not secrets.
10. **No key rotation endpoint.** A leaked contributor key is fixed by the steward disabling the account.
11. **SQLite + in-memory cache/limiter, single node.** Fine for Phase 0. Revisit before opening registration.
