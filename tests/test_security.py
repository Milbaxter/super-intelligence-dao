"""Regression tests for docs/SECURITY.md fixes."""

import pytest
from fastapi.testclient import TestClient

from agentdao import config
from agentdao.verify import FetchError, validate_url
from conftest import claim, create_task, register

PUBLIC = lambda h: ["93.184.216.34"]  # noqa: E731


def test_not_found_page_escapes_path(client):
    r = client.get("/<script>alert(1)</script>")
    assert r.status_code == 404 and "<script>alert" not in r.text and "&lt;script&gt;" in r.text
    r = client.get("/task-types/<img src=x onerror=alert(1)>.md")
    assert "<img" not in r.text


def test_security_headers_and_csp(client, app):
    web = app.state.settings.web_dir
    web.mkdir()
    (web / "index.html").write_text("<script>var t=1</script><h1>hi</h1>")
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")
    api = client.get("/api/v1/stats")
    assert api.headers["x-content-type-options"] == "nosniff" and "content-security-policy" not in api.headers


def test_csp_hashes_inline_scripts(tmp_path):
    from agentdao.app import build_csp
    (tmp_path / "a.html").write_text("<script>var t=1</script><script type=module src='x.js'></script>")
    csp = build_csp(tmp_path)
    assert "'sha256-" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


@pytest.mark.parametrize("bad", ['{"progress_note": NaN}', '{"x": Infinity}', '{"x": -Infinity}',
                                 '{"x": 1' + '0' * 30 + '}', '{"x":' + '[' * 40 + ']' * 40 + '}'])
def test_non_finite_and_deep_json_rejected(client, bad):
    h = register(client, "alice")
    r = client.post("/api/v1/leases/l_x/heartbeat", content=bad, headers={**h, "content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_body"


def test_nan_claim_value_rejected(client):
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h, task_types=["map.extract"]).json()["lease"]["id"]
    body = ('{"payload":{"claims":[{"benchmark":"b","metric":"m","value":NaN,"source_url":"https://example.org/results",'
            '"quote":"information about the financial results"}]}}')
    r = client.post(f"/api/v1/leases/{lease}/submit", content=body, headers={**h, "content-type": "application/json"})
    assert r.status_code == 422
    assert client.get("/api/v1/claims").status_code == 200


def test_random_bearer_tokens_cannot_bypass_rate_limit(app):
    app.state.settings.rate_public_per_min = 5
    with TestClient(app) as c:
        codes = [c.get("/api/v1/stats", headers={"Authorization": f"Bearer junk{i}"}).status_code for i in range(7)]
    assert codes[-1] == 429


def test_only_default_https_port():
    assert validate_url("https://example.org:443/x", PUBLIC)
    for url in ("https://example.org:8443/x", "https://example.org:22/", "https://example.org:99999/"):
        with pytest.raises(FetchError) as e:
            validate_url(url, PUBLIC)
        assert e.value.reason == "blocked_url"
    for url in ("file:///etc/passwd", "gopher://example.org/", "ftp://example.org/"):
        with pytest.raises(FetchError):
            validate_url(url, PUBLIC)


@pytest.mark.parametrize("ip", ["64:ff9b::7f00:1", "2002:7f00:1::", "::127.0.0.1", "::ffff:10.0.0.1", "fd00:ec2::254"])
def test_tunnelled_private_ipv6_blocked(ip):
    with pytest.raises(FetchError):
        validate_url("https://evil.example/", lambda h: [ip])


def test_refuse_public_bind_with_dev_key(tmp_path):
    s = config.Settings(db_path=str(tmp_path / "x.db"), steward_key=config.DEV_STEWARD_KEY)
    assert config.unsafe_for_public_bind(s, "127.0.0.1") == []
    assert config.unsafe_for_public_bind(s, "0.0.0.0")
    s.steward_key = "x" * 40
    assert config.unsafe_for_public_bind(s, "0.0.0.0") == []
    s.allow_local_sources = True
    assert config.unsafe_for_public_bind(s, "0.0.0.0")


def test_cli_serve_refuses(monkeypatch, tmp_path):
    from agentdao import cli
    monkeypatch.setenv("AGENTDAO_DB", str(tmp_path / "x.db"))
    monkeypatch.delenv("AGENTDAO_STEWARD_KEY", raising=False)
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2


def test_static_refuses_dotfiles_and_traversal(client, app):
    web = app.state.settings.web_dir
    web.mkdir()
    (web / ".env").write_text("SECRET=1")
    (web / "ok.html").write_text("ok")
    assert client.get("/.env").status_code == 404 and client.get("/ok").text == "ok"
    assert client.get("/%2e%2e/pyproject.toml").status_code == 404
