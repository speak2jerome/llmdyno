"""Event bus hygiene (no leaked topics, overflow triggers a resync) and the panic stop's container handling."""
import asyncio
import subprocess

from llmdyno import events, safety


def test_unsubscribe_drops_empty_topics():
    q = events.ClientQueue()
    events.subscribe("run:abc", q)
    events.subscribe("jobs", q)
    events.unsubscribe(q, "run:abc")
    assert "run:abc" not in events._subs
    events.unsubscribe(q)
    assert all(q not in subs for subs in events._subs.values())


def test_slow_client_gets_a_resync_instead_of_unbounded_memory():
    async def scenario():
        events.bind(asyncio.get_running_loop())
        q = events.ClientQueue()
        events.subscribe("run:flood", q)
        for i in range(events.MAX_QUEUE + 50):
            events.publish("run:flood", "transcript", {"i": i})
        await asyncio.sleep(0.05)
        events.unsubscribe(q)
        return q.qsize(), q.overflow
    size, overflow = asyncio.run(scenario())
    assert size == events.MAX_QUEUE and overflow is True


def test_kill_containers_removes_only_labelled_ones(monkeypatch):
    calls = []

    def fake_docker(args, timeout=60):
        calls.append(args)
        if args[:2] == ["ps", "-aq"]:
            assert "label=org.llmdyno.role=proxy" in args
            return subprocess.CompletedProcess(args, 0, "abc123\ndef456\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(safety, "_docker", fake_docker)
    assert safety.kill_containers("proxy") == 2
    assert calls[-1] == ["rm", "-f", "abc123", "def456"]


def test_kill_containers_without_docker(monkeypatch):
    monkeypatch.setattr(safety, "_docker", lambda *a, **k: None)
    assert safety.kill_containers() == 0
