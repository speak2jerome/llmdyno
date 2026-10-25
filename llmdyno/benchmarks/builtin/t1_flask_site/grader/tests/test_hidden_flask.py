import importlib
import sqlite3
import sys

import pytest


@pytest.fixture()
def app(tmp_path):
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    db = tmp_path / "test.db"
    application = mod.create_app({"TESTING": True, "DATABASE": str(db), "SECRET_KEY": "test-secret",
                                  "WTF_CSRF_ENABLED": False})
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def rows(app, sql):
    con = sqlite3.connect(app.config["DATABASE"])
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def count_contacts(app):
    # The schema may be created lazily, so a missing table means nothing was stored.
    try:
        return rows(app, "SELECT COUNT(*) FROM contacts")[0][0]
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return 0
        raise


def register(client, username="alice", password="s3cretpass"):
    return client.post("/register", data={"username": username, "password": password})


def login(client, username="alice", password="s3cretpass"):
    return client.post("/login", data={"username": username, "password": password})


def contact(client, name="Bob", email="bob@example.com", message="Hello there"):
    return client.post("/contact", data={"name": name, "email": email, "message": message})


def test_home_links(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for href in ("/contact", "/login", "/register"):
        assert href in html


def test_contact_form_fields(client):
    html = client.get("/contact").get_data(as_text=True)
    for field in ('name="name"', 'name="email"', 'name="message"'):
        assert field in html


def test_contact_success_redirect_and_stored(client, app):
    r = contact(client)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/contact?sent=1")
    assert "Thank you" in client.get("/contact?sent=1").get_data(as_text=True)
    stored = rows(app, "SELECT name, email, message FROM contacts")
    assert stored == [("Bob", "bob@example.com", "Hello there")]


def test_contact_has_created_at(client, app):
    contact(client)
    assert rows(app, "SELECT created_at FROM contacts")[0][0]


def test_contact_invalid_email(client, app):
    r = contact(client, email="not-an-email")
    assert r.status_code == 400
    assert count_contacts(app) == 0


def test_contact_missing_field(client, app):
    r = contact(client, name="")
    assert r.status_code == 400
    assert count_contacts(app) == 0


def test_contact_message_too_long(client, app):
    assert contact(client, message="x" * 2001).status_code == 400
    assert contact(client, message="x" * 2000).status_code == 302


def test_register_success_redirects_to_login(client):
    r = register(client)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")


def test_register_short_password(client, app):
    assert register(client, password="short").status_code == 400


def test_register_bad_username(client):
    assert register(client, username="ab").status_code == 400


def test_register_duplicate(client):
    register(client)
    assert register(client).status_code == 400


def test_password_is_hashed(client, app):
    register(client, password="plaintextpw1")
    (h,) = rows(app, "SELECT password_hash FROM users WHERE username='alice'")[0]
    assert h and "plaintextpw1" not in h and h != "plaintextpw1"


def test_login_success_and_welcome(client):
    register(client)
    r = login(client)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/dashboard")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Welcome, alice" in html


def test_login_wrong_password(client):
    register(client)
    assert login(client, password="wrongpassword").status_code == 401


def test_login_unknown_user(client):
    assert login(client, username="nobody").status_code == 401


def test_dashboard_requires_login(client):
    r = client.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_dashboard_lists_contacts_newest_first(client):
    contact(client, name="First", message="first message")
    contact(client, name="Second", message="second message")
    register(client)
    login(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "First" in html and "Second" in html
    assert html.index("Second") < html.index("First")


def test_logout(client):
    register(client)
    login(client)
    r = client.get("/logout")
    assert r.status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_default_database_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    application = mod.create_app({"TESTING": True})
    assert str(application.config["DATABASE"]).replace("\\", "/").endswith("site.db")
