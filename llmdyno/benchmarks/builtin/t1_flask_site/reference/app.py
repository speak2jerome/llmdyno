import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, g, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, name TEXT, email TEXT, message TEXT, created_at TEXT);
"""
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PAGE = """<html><body><a href="/">Home</a> <a href="/contact">Contact</a> <a href="/login">Login</a>
<a href="/register">Register</a>{% if error %}<p class="error">{{ error }}</p>{% endif %}{{ body|safe }}</body></html>"""


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(SECRET_KEY="dev", DATABASE=os.path.join("instance", "site.db"))
    if test_config:
        app.config.update(test_config)

    def db():
        if "db" not in g:
            os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.executescript(SCHEMA)
        return g.db

    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d:
            d.close()

    def page(body, error=None, status=200):
        return render_template_string(PAGE, body=body, error=error), status

    @app.get("/")
    def home():
        return page("<h1>Home</h1>")

    form = ('<form method="post"><input name="name"><input name="email"><textarea name="message"></textarea>'
            '<button>Send</button></form>')

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        if request.method == "GET":
            return page(("<p>Thank you</p>" if request.args.get("sent") else "") + form)
        name, email, msg = (request.form.get(k, "").strip() for k in ("name", "email", "message"))
        if not name or not email or not msg or not EMAIL.match(email) or len(msg) > 2000:
            return page(form, "Invalid input", 400)
        db().execute("INSERT INTO contacts (name, email, message, created_at) VALUES (?,?,?,?)",
                     (name, email, msg, datetime.now(timezone.utc).isoformat()))
        db().commit()
        return redirect("/contact?sent=1")

    auth_form = '<form method="post"><input name="username"><input name="password" type="password"><button>Go</button></form>'

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "GET":
            return page(auth_form)
        u, p = request.form.get("username", "").strip(), request.form.get("password", "")
        if not (3 <= len(u) <= 30) or len(p) < 8:
            return page(auth_form, "Invalid input", 400)
        try:
            db().execute("INSERT INTO users (username, password_hash) VALUES (?,?)", (u, generate_password_hash(p)))
            db().commit()
        except sqlite3.IntegrityError:
            return page(auth_form, "Username taken", 400)
        return redirect("/login")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return page(auth_form)
        u, p = request.form.get("username", ""), request.form.get("password", "")
        row = db().execute("SELECT password_hash FROM users WHERE username=?", (u,)).fetchone()
        if not row or not check_password_hash(row[0], p):
            return page(auth_form, "Bad credentials", 401)
        session["user"] = u
        return redirect("/dashboard")

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect("/")

    @app.get("/dashboard")
    def dashboard():
        if "user" not in session:
            return redirect(url_for("login"))
        rows = db().execute("SELECT name, email, message FROM contacts ORDER BY id DESC").fetchall()
        table = "".join(f"<tr><td>{n}</td><td>{e}</td><td>{m}</td></tr>" for n, e, m in rows)
        return page(f"<p>Welcome, {session['user']}</p><table>{table}</table>")

    return app
