"""Browser dispatch layer against a fake websocket (no Chrome)."""

import json
import queue
import threading

import pytest
import websocket

from kfw import cdp
from kfw.cdp import Browser, CDPError

T = 2.0


class FakeWS:
    def __init__(self):
        self.inbox: queue.Queue = queue.Queue()
        self.sent: queue.Queue = queue.Queue()
        self.timeouts = 0

    def recv(self):
        item = self.inbox.get()
        if item is None:
            raise websocket.WebSocketConnectionClosedException("closed")
        if item == "timeout":
            self.timeouts += 1
            raise websocket.WebSocketTimeoutException("t")
        return item

    def send(self, data):
        self.sent.put(json.loads(data))

    def close(self):
        self.inbox.put(None)

    def push(self, msg):
        self.inbox.put(json.dumps(msg))

    def event(self, method, session="S", **params):
        self.push({"method": method, "sessionId": session, "params": params})

    def reply(self, mid, **result):
        self.push({"id": mid, "result": result})


@pytest.fixture
def env(monkeypatch):
    ws = FakeWS()

    class R:
        def json(self):
            return {"webSocketDebuggerUrl": "ws://x"}

    monkeypatch.setattr(cdp.httpx, "get", lambda *a, **k: R())
    monkeypatch.setattr(cdp.websocket, "create_connection", lambda *a, **k: ws)
    b = Browser()
    yield b, ws
    b.close()


def serve_echo(ws, stop):
    """Answer every command with {'echo': method}."""

    def run():
        while not stop.is_set():
            try:
                m = ws.sent.get(timeout=0.05)
            except queue.Empty:
                continue
            ws.reply(m["id"], echo=m["method"])

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_send_inside_listener_does_not_deadlock(env):
    b, ws = env
    stop = threading.Event()
    serve_echo(ws, stop)
    got, done = [], threading.Event()

    def cb(p):
        got.append(b.send("Foo.bar", timeout=T))
        done.set()

    b.on("S", "Ev.x", cb)
    ws.event("Ev.x")
    assert done.wait(T)
    assert got == [{"echo": "Foo.bar"}]
    stop.set()


def test_listener_exception_isolated(env):
    b, ws = env
    stop = threading.Event()
    serve_echo(ws, stop)
    seen, done = [], threading.Event()

    def bad(p):
        raise ValueError("boom")

    def good(p):
        seen.append(p["n"])
        if len(seen) == 2:
            done.set()

    b.on("S", "Ev.x", bad)
    b.on("S", "Ev.x", good)
    ws.event("Ev.x", n=1)
    ws.event("Ev.x", n=2)
    assert done.wait(T)
    assert seen == [1, 2]
    assert b.send("Ping", timeout=T) == {"echo": "Ping"}
    stop.set()


def test_disconnect_wakes_pending_and_fails_later_sends(env):
    b, ws = env
    fired = threading.Event()
    b.on_disconnect(fired.set)
    err: queue.Queue = queue.Queue()

    def call():
        try:
            b.send("Slow", timeout=30)
        except CDPError as e:
            err.put(str(e))

    t = threading.Thread(target=call, daemon=True)
    t.start()
    ws.sent.get(timeout=T)  # request is now pending
    ws.inbox.put(None)  # connection drops
    assert err.get(timeout=T) == "disconnected"
    assert fired.wait(T)
    with pytest.raises(CDPError, match="disconnected"):
        b.send("After", timeout=30)
    assert b.disconnected


def test_recv_timeout_is_not_disconnect(env):
    b, ws = env
    stop = threading.Event()
    serve_echo(ws, stop)
    for _ in range(3):
        ws.inbox.put("timeout")
    assert b.send("Still", timeout=T) == {"echo": "Still"}
    assert ws.timeouts == 3
    assert not b.disconnected
    stop.set()


def test_off_stops_delivery(env):
    b, ws = env
    a, c = [], []
    done = threading.Event()

    def cb_a(p):
        a.append(p["n"])

    def cb_c(p):
        c.append(p["n"])
        if p["n"] == 2:
            done.set()

    b.on("S", "Ev.x", cb_a)
    b.on("S", "Ev.x", cb_c)
    ws.event("Ev.x", n=1)
    b.off("S", "Ev.x", cb_a)
    b.off("S", "Ev.x", cb_a)  # idempotent
    ws.event("Ev.x", n=2)
    assert done.wait(T)
    assert 2 not in a
    assert c == [1, 2]


def test_dispatch_order_matches_arrival(env):
    b, ws = env
    seen, done = [], threading.Event()

    def cb(p):
        seen.append(p["n"])
        if len(seen) == 50:
            done.set()

    b.on("S", "Ev.x", cb)
    for i in range(50):
        ws.event("Ev.x", n=i)
    assert done.wait(T)
    assert seen == list(range(50))


def test_reply_not_blocked_by_slow_listener(env):
    b, ws = env
    gate, started = threading.Event(), threading.Event()

    def slow(p):
        started.set()
        gate.wait(T)

    b.on("S", "Ev.x", slow)
    ws.event("Ev.x")
    assert started.wait(T)
    stop = threading.Event()
    serve_echo(ws, stop)
    # dispatcher is stuck, but replies are still handled by the reader
    assert b.send("Quick", timeout=T) == {"echo": "Quick"}
    gate.set()
    stop.set()


def test_close_ends_threads(env):
    b, ws = env
    b.close()
    b._reader.join(T)
    b._dispatcher.join(T)
    assert not b._reader.is_alive() and not b._dispatcher.is_alive()
