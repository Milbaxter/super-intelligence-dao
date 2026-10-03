"""SIDAO_* env vars (AGENTDAO_* fallback) and the self-reported tokens_estimate cap."""

from __future__ import annotations

from agentdao import config
from conftest import claim, create_task, extract_payload, register, submit


def _clear(monkeypatch, name):
    for prefix in (config.ENV_PREFIX, config.LEGACY_ENV_PREFIX):
        monkeypatch.delenv(prefix + name, raising=False)


def test_sidao_env_takes_precedence(monkeypatch):
    for name in ("STEWARD_KEY", "PUBLIC_URL", "GITHUB_MIN_AGE_DAYS"):
        _clear(monkeypatch, name)
    monkeypatch.setenv("AGENTDAO_STEWARD_KEY", "legacy-key")
    monkeypatch.setenv("SIDAO_STEWARD_KEY", "new-key")
    monkeypatch.setenv("SIDAO_PUBLIC_URL", "https://sidao.example/")
    monkeypatch.setenv("AGENTDAO_GITHUB_MIN_AGE_DAYS", "7")
    monkeypatch.setenv("SIDAO_GITHUB_MIN_AGE_DAYS", "30")
    s = config.Settings()
    assert s.steward_key == "new-key" and s.public_url == "https://sidao.example" and s.github_min_age_days == 30


def test_agentdao_env_fallback(monkeypatch, tmp_path):
    for name in ("DB", "STEWARD_KEY", "ALLOW_LOCAL_SOURCES", "DEV_ALLOW_SAME_IP", "IP_SALT"):
        _clear(monkeypatch, name)
    monkeypatch.setenv("AGENTDAO_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setenv("AGENTDAO_STEWARD_KEY", "legacy-key")
    monkeypatch.setenv("AGENTDAO_ALLOW_LOCAL_SOURCES", "1")
    monkeypatch.setenv("AGENTDAO_DEV_ALLOW_SAME_IP", "1")
    monkeypatch.setenv("AGENTDAO_IP_SALT", "salt")
    s = config.Settings()
    assert s.db_path == str(tmp_path / "legacy.db") and s.steward_key == "legacy-key"
    assert s.allow_local_sources and s.dev_allow_same_ip and s.ip_salt == "salt"
    _clear(monkeypatch, "STEWARD_KEY")
    assert config.Settings().steward_key == config.DEV_STEWARD_KEY


def _submitted_tokens(client, conn, h, budget, tokens):
    create_task(client, budget_minutes=budget)
    lease = claim(client, h, task_types=["map.extract"]).json()["lease"]
    assert submit(client, h, lease["id"], extract_payload(), tokens=tokens).status_code == 200
    return conn.execute("SELECT tokens_estimate FROM submissions WHERE lease_id=?", (lease["id"],)).fetchone()[0]


def test_tokens_estimate_capped_by_task_budget(client, conn):
    h = register(client, "alice")
    assert _submitted_tokens(client, conn, h, 10, 10**9) == 10 * config.TOKENS_PER_BUDGET_MINUTE_MAX  # 1M
    assert _submitted_tokens(client, conn, h, 120, 10**9) == config.TOKENS_ESTIMATE_MAX == 5_000_000
    assert _submitted_tokens(client, conn, h, 10, 4321) == 4321
