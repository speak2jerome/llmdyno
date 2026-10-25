"""Beyond-spec robustness probes for the Flask task. Each checks behaviour any careful implementation shares."""
import importlib
import sqlite3
import sys

import pytest


@pytest.fixture()
def app(tmp_path):
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    return mod.create_app({"TESTING": True, "DATABASE": str(tmp_path / "p.db"), "SECRET_KEY": "k", "WTF_CSRF_ENABLED": False})


@pytest.fixture()
def client(app):
    return app.test_client()


def contacts(app):
    try:
        con = sqlite3.connect(app.config["DATABASE"])
        return con.execute("SELECT name, email, message FROM contacts").fetchall()
    except sqlite3.OperationalError:
        return []


def login_as(client, user="probeuser", pw="probe-pass-123"):
    client.post("/register", data={"username": user, "password": pw})
    return client.post("/login", data={"username": user, "password": pw})


def test_xss_is_escaped_on_dashboard(client):
    client.post("/contact", data={"name": "<script>alert(1)</script>", "email": "x@example.com", "message": "<b>hi</b>"})
    login_as(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "<b>hi</b>" not in html


def test_sql_injection_login_rejected(client):
    login_as(client)
    client.get("/logout")
    r = client.post("/login", data={"username": "' OR '1'='1", "password": "' OR '1'='1"})
    assert r.status_code in (400, 401)


def test_whitespace_only_fields_rejected(client, app):
    r = client.post("/contact", data={"name": "   ", "email": "x@example.com", "message": "   "})
    assert r.status_code == 400 and contacts(app) == []


def test_email_with_spaces_rejected(client, app):
    r = client.post("/contact", data={"name": "A", "email": "a b@example.com", "message": "hello"})
    assert r.status_code == 400 and contacts(app) == []


def test_unicode_round_trip(client):
    client.post("/contact", data={"name": "Zoë 测试", "email": "zoe@example.com", "message": "héllo ✓"})
    login_as(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Zoë 测试" in html and "héllo ✓" in html


def test_missing_form_fields_do_not_500(client):
    for path in ("/contact", "/login", "/register"):
        assert client.post(path, data={}).status_code < 500


def test_password_never_echoed(client):
    r = client.post("/register", data={"username": "echo", "password": "super-secret-pw"}, follow_redirects=True)
    assert "super-secret-pw" not in r.get_data(as_text=True)
    r = client.post("/login", data={"username": "echo", "password": "wrong-secret-pw"})
    assert "wrong-secret-pw" not in r.get_data(as_text=True)
