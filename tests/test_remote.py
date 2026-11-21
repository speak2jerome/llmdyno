"""Remote mode: the server's token check, the request log, connect() and live events over the WebSocket.
Requests carrying X-Forwarded-For count as remote (as they would through a reverse proxy), which is how these tests
play a client on another machine."""
import json

import pytest
from conftest import safe_app_client
from starlette.websockets import WebSocketDisconnect

import llmdyno
from llmdyno import auth, cli, config
from llmdyno.sdk import _backend
from llmdyno.sdk.remote import RemoteBackend

FAR = {"X-Forwarded-For": "203.0.113.9"}


@pytest.fixture(scope="module")
def app_client():
    client, mp = safe_app_client()
    yield client
    client.__exit__(None, None, None)
    mp.undo()


@pytest.fixture()
def token():
    tok, _ = auth.ensure_token()
    return tok


@pytest.fixture()
def restore_backend():
    prev = _backend._current["backend"]
    yield
    _backend._current["backend"] = prev


def test_this_machine_needs_no_token(app_client):
    assert app_client.get("/api/settings").status_code == 200


def test_remote_requests_need_the_token(app_client, token):
    r = app_client.get("/api/settings", headers=FAR)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer" and "access token" in r.json()["detail"]
    assert app_client.get("/api/settings", headers={**FAR, "Authorization": "Bearer wrong"}).status_code == 401
    assert app_client.get("/api/settings", headers={**FAR, "Authorization": f"Bearer {token}"}).status_code == 200
    assert app_client.get(f"/api/settings?token={token}", headers=FAR).status_code == 200      # downloads, links
    assert app_client.get("/", headers=FAR).status_code == 200                                 # the UI itself
    settings = app_client.get("/api/settings", headers={**FAR, "Authorization": f"Bearer {token}"}).text
    assert token not in settings                                                               # never handed out


def test_remote_changes_are_logged(app_client, token):
    log = config.DATA / "logs" / "remote-requests.jsonl"
    before = log.read_text().count("\n") if log.exists() else 0
    r = app_client.patch("/api/settings", json={"electricity_usd_per_kwh": 0.2},
                         headers={**FAR, "Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    lines = log.read_text().splitlines()
    assert len(lines) == before + 1
    entry = json.loads(lines[-1])
    assert entry["client"] == "203.0.113.9" and entry["method"] == "PATCH" and entry["path"] == "/api/settings"
    app_client.get("/api/settings", headers={**FAR, "Authorization": f"Bearer {token}"})
    assert len(log.read_text().splitlines()) == before + 1                                     # reads are not logged


def test_websocket_needs_the_token(app_client, token):
    with pytest.raises(WebSocketDisconnect) as e:
        with app_client.websocket_connect("/ws", headers=FAR) as ws:
            ws.receive_text()
    assert e.value.code == 1008
    with app_client.websocket_connect(f"/ws?token={token}", headers=FAR) as ws:
        ws.send_text(json.dumps({"sub": ["jobs"]}))


def test_rotating_the_token_locks_the_old_one_out(app_client, token):
    new = auth.rotate()
    try:
        assert app_client.get("/api/settings", headers={**FAR, "Authorization": f"Bearer {token}"}).status_code == 401
        assert app_client.get("/api/settings", headers={**FAR, "Authorization": f"Bearer {new}"}).status_code == 200
    finally:
        auth.rotate()


def test_connect_runs_the_library_over_http(app_client, token, restore_backend):
    app_client.headers.update(FAR)
    try:
        with pytest.raises(llmdyno.LLMDynoError, match="refused the connection"):
            llmdyno.connect("http://testserver", token="wrong", client=app_client)
        remote = llmdyno.connect("http://testserver", token=token, client=app_client)
        assert isinstance(llmdyno.connection(), RemoteBackend) and remote.server["version"] == llmdyno.__version__
        assert any(s["id"] == "suite_quick" for s in llmdyno.list_suites())
        assert llmdyno.data_dir() == config.DATA                                           # asked from the server
        with pytest.raises(llmdyno.LLMDynoError, match="remote"):
            llmdyno.init()
        with pytest.raises(llmdyno.NotFoundError):
            llmdyno.benchmark("no_such_benchmark")
        llmdyno.disconnect()
        assert isinstance(llmdyno.connection(), _backend.LocalBackend)
    finally:
        app_client.headers.pop("X-Forwarded-For", None)


def test_live_events_over_the_websocket(app_client, token, restore_backend):
    from llmdyno import jobs
    app_client.headers.update(FAR)
    try:
        llmdyno.connect("http://testserver", token=token, client=app_client)
        seen = []

        def work(ctx):
            import time
            time.sleep(0.6)                       # long enough for the watcher to subscribe first
            for i in range(3):
                ctx.log(f"line {i}")
        jid = jobs.submit("test", "Remote watch", work)
        for ev in llmdyno.watch(jid, poll_s=5, timeout=30):
            seen.append(ev)
        logs = [e.data for e in seen if e.kind == "log"]
        assert logs == ["line 0", "line 1", "line 2"]                    # only the WebSocket carries log lines
        assert seen[-1].kind == "job" and seen[-1].status == "done"
    finally:
        app_client.headers.pop("X-Forwarded-For", None)


def test_token_command_and_serve_notice(capsys, monkeypatch):
    from llmdyno import secrets
    secrets.delete(auth.SECRET)
    assert cli.main(["token"]) == 0
    first = capsys.readouterr().out.strip()
    assert len(first) >= 40 and auth.check(first)
    assert cli.main(["token"]) == 0
    out = capsys.readouterr()
    assert first not in out.out and "--rotate" in out.err                  # shown only when made
    assert cli.main(["token", "--rotate"]) == 0
    assert capsys.readouterr().out.strip() != first
    assert cli.remote_notice("127.0.0.1") is None
    assert "access token" in cli.remote_notice("0.0.0.0")
    secrets.delete(auth.SECRET)
    note = cli.remote_notice("0.0.0.0")
    assert "shown once" in note and auth.token() in note


def test_cli_url_option(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(llmdyno.lib, "connect", lambda url, token: calls.append((url, token)))
    monkeypatch.setattr(llmdyno.lib, "list_suites", lambda: [{"id": "suite_x", "name": "X"}])
    assert cli.main(["list-suites", "--url", "http://gpu-box:8777", "--api-token", "t0k"]) == 0
    assert calls == [("http://gpu-box:8777", "t0k")] and "suite_x" in capsys.readouterr().out
