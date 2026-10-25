You are working in /workspace, an empty project. Build a small Flask website.

Requirements:

1. Application factory: `app.py` at the project root must define `create_app(test_config=None)` that returns a Flask app. `test_config` is an optional dict merged into `app.config`. The SQLite database path is read from `app.config["DATABASE"]` (default: `instance/site.db`). The schema must be created automatically on first use (no manual init command).

2. Pages and routes (server-rendered HTML using Jinja templates in `templates/`):
   - `GET /`: home page with links to `/contact`, `/login` and `/register`.
   - `GET /contact`: contact form with fields `name`, `email`, `message`.
   - `POST /contact`: all fields are required, `email` must look like an email address, `message` is at most 2000 characters. On success, store the submission in table `contacts` (columns: `id`, `name`, `email`, `message`, `created_at`) and redirect (HTTP 302) to `/contact?sent=1`, which shows the text "Thank you". On validation failure, re-render the form with HTTP status 400 and an error message, and store nothing.
   - `GET/POST /register`: fields `username` and `password`. Username is 3 to 30 characters and unique; password is at least 8 characters. Store users in table `users` (columns: `id`, `username`, `password_hash`) using a salted hash from `werkzeug.security`. On success, redirect to `/login`. A duplicate username or invalid input returns status 400 with an error message.
   - `GET/POST /login`: fields `username` and `password`. On success, log the user in (session) and redirect to `/dashboard`. Wrong credentials return status 401 with an error message.
   - `GET /logout`: log out and redirect to `/`.
   - `GET /dashboard`: requires login (otherwise redirect to `/login`). Shows "Welcome, <username>" and a table of all contact submissions, newest first.

3. Add `requirements.txt`, a short `README.md` explaining how to run the app, and at least 3 pytest tests in `tests/` that pass with `pytest -q`.

4. Everything you need (flask, werkzeug, pytest) is already installed. There is no internet access, so do not try to install anything.

When you are finished, reply with a short summary of what you built.
