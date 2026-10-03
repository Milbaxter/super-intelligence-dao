"""Operator (person) labels on invites and GitHub-linked identity for referee work. No network: fake GitHub API."""

from __future__ import annotations

from datetime import timedelta

import pytest

from agentdao import cli, config, db
from agentdao.app import create_app
from agentdao.github import GitHubError, HttpGitHub, parse_gist_id

from conftest import STEWARD, claim, create_task, do_extract, register

GIST = "aa11bb22cc33dd44ee55ff66aa77bb88"


class FakeGitHub:
    """path → dict (or GitHubError). Records calls."""

    def __init__(self):
        self.gists: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self.calls: list[str] = []

    def get_json(self, path):
        self.calls.append(path)
        kind, _, key = path.strip("/").partition("/")
        src = self.gists if kind == "gists" else self.users
        if key not in src:
            raise GitHubError("not_found", status=404)
        return src[key]

    def add(self, gist_id, content, login="octo", gh_id=1001, age_days=400, public=True):
        self.gists[gist_id] = {"public": public, "owner": {"login": login, "id": gh_id},
                               "files": {"proof.txt": {"content": content}}}
        created = db.ts(db.utcnow() - timedelta(days=age_days))
        self.users[login] = {"login": login, "id": gh_id, "created_at": created}


@pytest.fixture
def gh(app):
    fake = FakeGitHub()
    app.state.github = fake
    return fake


def strict(app):
    """Production-like: no dev bypasses (same-IP block and GitHub requirement on)."""
    app.state.settings.dev_allow_same_ip = False
    app.state.settings.allow_local_sources = False


def link(client, gh, headers, login="octo", gh_id=1001, age_days=400, gist=GIST):
    ch = client.post("/api/v1/me/github/challenge", headers=headers)
    assert ch.status_code == 200, ch.text
    gh.add(gist, "proof:\n" + ch.json()["challenge"] + "\n", login=login, gh_id=gh_id, age_days=age_days)
    return client.post("/api/v1/me/github/verify", json={"gist_url": f"https://gist.github.com/{login}/{gist}"},
                       headers=headers)


def register_with(client, handle, code, family="claude"):
    r = client.post("/api/v1/register", json={"invite_code": code, "handle": handle, "model_family": family})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


# ---------------------------------------------------------------------------------------------------- person labels


def test_invites_minted_together_share_person_and_cannot_verify_each_other(client, conn):
    r = client.post("/api/v1/admin/invites", json={"count": 2, "person": "alice"}, headers=STEWARD)
    assert r.status_code == 200 and r.json()["person"] == "alice"
    a, b = r.json()["codes"]
    ha, hb = register_with(client, "alice-1", a), register_with(client, "alice-2", b, "gpt")
    persons = {row[0] for row in conn.execute("SELECT person FROM contributors")}
    assert len(persons) == 1
    do_extract(client, ha)
    assert claim(client, hb, task_types=["verify.blind_extract"]).status_code == 204  # same operator
    hc = register(client, "bob")  # unlabeled invite = a different person
    assert claim(client, hc, task_types=["verify.blind_extract"]).status_code == 200


def test_unlabeled_invites_are_separate_people(client, conn):
    codes = client.post("/api/v1/admin/invites", json={"count": 3}, headers=STEWARD).json()["codes"]
    persons = {row[0] for row in conn.execute("SELECT person FROM invites WHERE code IN (?,?,?)", codes)}
    assert len(persons) == 3


def test_person_label_not_public(client):
    client.post("/api/v1/admin/invites", json={"count": 1, "person": "Secret Name"}, headers=STEWARD)
    register(client, "pub")
    for path in ("/api/v1/contributors", "/api/v1/activity"):
        assert "Secret Name" not in client.get(path).text


def test_invite_person_validation(client):
    r = client.post("/api/v1/admin/invites", json={"count": 1, "person": 5}, headers=STEWARD)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_person"


def test_cli_invite_person(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTDAO_DB", str(tmp_path / "c.db"))
    assert cli.main(["invite", "--count", "2", "--person", "carol"]) == 0
    codes = capsys.readouterr().out.split()
    conn = db.connect(str(tmp_path / "c.db"))
    assert {r[0] for r in conn.execute("SELECT person FROM invites")} == {"op:carol"} and len(codes) == 2
    conn.close()


# ---------------------------------------------------------------------------------------------------- GitHub linking


def test_github_link_happy_path_and_public_login(client, gh):
    h = register(client, "linker")
    r = link(client, gh, h)
    assert r.status_code == 200, r.text
    assert r.json()["github_login"] == "octo"
    assert gh.calls == [f"/gists/{GIST}", "/users/octo"]
    me = client.get("/api/v1/me", headers=h).json()
    assert me["github_login"] == "octo" and me["referee_eligible"] is True
    row = next(p for p in client.get("/api/v1/contributors").json() if p["handle"] == "linker")
    assert row["github_login"] == "octo" and "github_id" not in row and "person" not in row
    # challenge is single-use
    again = client.post("/api/v1/me/github/verify", json={"gist_url": GIST}, headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "no_challenge"


@pytest.mark.parametrize("mutate,code", [
    (lambda g: g.gists[GIST].update(public=False), "gist_not_public"),
    (lambda g: g.gists[GIST]["files"]["proof.txt"].update(content="something else"), "challenge_not_found"),
    (lambda g: g.gists[GIST].update(owner=None), "gist_no_owner"),
    (lambda g: g.gists.pop(GIST), "github_not_found"),
])
def test_github_link_rejections(client, gh, mutate, code):
    h = register(client, "rej")
    ch = client.post("/api/v1/me/github/challenge", headers=h).json()["challenge"]
    gh.add(GIST, ch)
    mutate(gh)
    r = client.post("/api/v1/me/github/verify", json={"gist_url": f"https://gist.github.com/octo/{GIST}"}, headers=h)
    assert r.json()["error"]["code"] == code, r.text


def test_github_account_too_new(client, gh, app):
    h = register(client, "newbie")
    r = link(client, gh, h, age_days=30)
    assert r.status_code == 403 and r.json()["error"]["code"] == "github_too_new"
    app.state.settings.github_min_age_days = 10
    assert link(client, gh, h, age_days=30).status_code == 200


def test_github_account_links_only_once(client, gh):
    h1, h2 = register(client, "first"), register(client, "second")
    assert link(client, gh, h1).status_code == 200
    r = link(client, gh, h2, gist="ff" * 16)
    assert r.status_code == 409 and r.json()["error"]["code"] == "github_already_linked"


def test_challenge_expires(client, gh, monkeypatch):
    h = register(client, "slow")
    ch = client.post("/api/v1/me/github/challenge", headers=h).json()["challenge"]
    gh.add(GIST, ch)
    later = db.utcnow() + timedelta(seconds=config.GITHUB_CHALLENGE_TTL_S + 60)
    monkeypatch.setattr(db, "utcnow", lambda: later)
    r = client.post("/api/v1/me/github/verify", json={"gist_url": GIST}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "challenge_expired"


def test_github_unavailable_is_502(client, gh):
    h = register(client, "flaky")
    client.post("/api/v1/me/github/challenge", headers=h)

    def boom(path):
        raise GitHubError("timeout")
    gh.get_json = boom
    r = client.post("/api/v1/me/github/verify", json={"gist_url": GIST}, headers=h)
    assert r.status_code == 502 and r.json()["error"]["code"] == "github_unavailable"


def test_parse_gist_id():
    assert parse_gist_id(f"https://gist.github.com/octo/{GIST}") == GIST
    assert parse_gist_id(f"https://gist.github.com/{GIST}/") == GIST
    assert parse_gist_id(f"https://api.github.com/gists/{GIST}") == GIST
    for bad in ("https://evil.example/gists/" + GIST, f"http://gist.github.com/octo/{GIST}", "../../users/x",
                f"https://gist.github.com.evil.io/octo/{GIST}"):
        with pytest.raises(Exception):
            parse_gist_id(bad)


def test_http_client_refuses_odd_paths():
    c = HttpGitHub()
    for bad in ("users/x", "//evil.com/x", "/users/../x", "/users/x?y=1"):
        with pytest.raises(GitHubError):
            c.get_json(bad)


# ---------------------------------------------------------------------------------------------------- eligibility


def test_verify_tasks_require_linked_github_in_production(app, client, gh):
    strict(app)
    author, verifier = register(client, "author"), register(client, "verifier", "gpt")
    app.state.settings.dev_allow_same_ip = True  # let the author do primary work despite TestClient's shared IP
    do_extract(client, author)
    app.state.settings.dev_allow_same_ip = False
    # TestClient registers everyone from one IP, so clear the IP hash to isolate the GitHub rule.
    c = db.connect(app.state.settings.db_path)
    with db.tx(c):
        c.execute("UPDATE contributors SET registered_ip_hash=NULL")
    c.close()
    assert claim(client, verifier, task_types=["verify.blind_extract"]).status_code == 204
    assert client.get("/api/v1/me", headers=verifier).json()["referee_eligible"] is False
    assert link(client, gh, verifier).status_code == 200
    assert claim(client, verifier, task_types=["verify.blind_extract"]).status_code == 200


def test_non_verify_tasks_do_not_need_github(app, client):
    strict(app)
    h = register(client, "worker")
    create_task(client)
    assert claim(client, h, task_types=["map.extract"]).status_code == 200


def test_same_github_id_treated_as_same_person(client, conn):
    ha, hb = register(client, "gh-a"), register(client, "gh-b", "gpt")
    do_extract(client, ha)
    with db.tx(conn):  # can't happen via the API (unique index); simulate legacy data with the index dropped
        conn.execute("DROP INDEX ux_contributors_github_id")
        conn.execute("UPDATE contributors SET github_id=42")
    assert claim(client, hb, task_types=["verify.blind_extract"]).status_code == 204


def test_github_id_unique_index(conn, client):
    register(client, "uq1"), register(client, "uq2")
    with pytest.raises(Exception):
        with db.tx(conn):
            conn.execute("UPDATE contributors SET github_id=7")


def test_dev_flag_refuses_public_bind_and_skips_github():
    s = config.Settings(steward_key="x" * 32, dev_allow_same_ip=True)
    assert not s.github_required_for_verify
    assert any("GitHub" in p for p in config.unsafe_for_public_bind(s, "0.0.0.0"))
    assert config.Settings(steward_key="x" * 32, dev_allow_same_ip=False,
                           allow_local_sources=False).github_required_for_verify


def test_min_age_env(monkeypatch):
    monkeypatch.setenv("AGENTDAO_GITHUB_MIN_AGE_DAYS", "7")
    assert config.Settings().github_min_age_days == 7


def test_migration_adds_columns_to_old_db(tmp_path):
    path = str(tmp_path / "old.db")
    c = db.connect(path)
    c.executescript("""CREATE TABLE contributors (id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE, model_family TEXT NOT NULL,
        api_key_hash TEXT NOT NULL UNIQUE, invite_code TEXT, contact TEXT, joined_at TEXT NOT NULL,
        is_steward INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active');
        CREATE TABLE invites (code TEXT PRIMARY KEY, created_at TEXT NOT NULL, used_by TEXT, note TEXT);
        INSERT INTO contributors (id, handle, model_family, api_key_hash, joined_at) VALUES
          ('c_old1', 'old-one', 'claude', 'h1', '2026-01-01T00:00:00Z'), ('c_old2', 'old-two', 'gpt', 'h2', '2026-01-01T00:00:00Z');
        INSERT INTO invites (code, created_at, used_by) VALUES ('inv-a', '2026-01-01T00:00:00Z', NULL),
          ('inv-b', '2026-01-01T00:00:00Z', 'c_old1');""")
    c.close()
    create_app(config.Settings(db_path=path, steward_key="k" * 30, web_dir=tmp_path, agent_dir=tmp_path))
    c = db.connect(path)
    cols = {r[1] for r in c.execute("PRAGMA table_info(contributors)")}
    assert {"person", "github_login", "github_id", "github_created_at"} <= cols
    assert "person" in {r[1] for r in c.execute("PRAGMA table_info(invites)")}
    persons = [r[0] for r in c.execute("SELECT person FROM contributors UNION ALL SELECT person FROM invites")]
    assert len(persons) == 4 and all(persons) and len(set(persons)) == 4  # old rows = separate people
    assert [r[0] for r in c.execute("SELECT handle FROM contributors ORDER BY handle")] == ["old-one", "old-two"]
    c.close()
    db.init_db(path)  # idempotent on restart: labels unchanged
    c = db.connect(path)
    assert sorted(r[0] for r in c.execute("SELECT person FROM contributors UNION ALL SELECT person FROM invites")) == sorted(persons)
    c.close()
