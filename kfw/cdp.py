"""Minimal Chrome DevTools Protocol client: one browser websocket, flattened tab sessions.

A tab (Tab) owns one attached session. Cross-process navigations (e.g. tw.coupang.com
redirecting /search) invalidate the session; Tab.call() re-attaches to the same targetId once.
"""

import itertools
import json
import logging
import queue
import threading
import time
from collections import defaultdict

import httpx
import websocket


log = logging.getLogger(__name__)
_STOP = object()
_DISCONNECT = object()


class CDPError(RuntimeError):
    pass


class _Slot:
    """A pending request: the reader thread fills msg and sets done."""

    def __init__(self):
        self.done = threading.Event()
        self.msg: dict = {}


class Browser:
    """One browser websocket.

    Threads: the reader only parses frames; command replies wake their slot directly, events go to a
    queue drained by a dispatcher thread (so listeners may call send() without deadlocking).
    """

    def __init__(self, endpoint="http://127.0.0.1:9333"):
        ws_url = httpx.get(f"{endpoint}/json/version", timeout=5).json()["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._ids = itertools.count(1)
        self._pending: dict = {}
        self._lock = threading.Lock()  # guards _pending, _disconnected, _listeners, _disconnect_cbs
        self._send_lock = threading.Lock()  # serialises ws.send
        self._listeners = defaultdict(list)  # (session_id, method) -> [callback]
        self._disconnect_cbs: list = []
        self._events: queue.Queue = queue.Queue()
        self._disconnected = False
        self._closing = False
        self._reader = threading.Thread(target=self._read, daemon=True, name="cdp-reader")
        self._dispatcher = threading.Thread(target=self._dispatch, daemon=True, name="cdp-dispatcher")
        self._dispatcher.start()
        self._reader.start()

    def _read(self):
        while True:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue  # a quiet connection is not a dead one
            except Exception:
                break
            if not raw:  # websocket-client hands back "" for a close frame; the next recv raises
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                log.warning("cdp: undecodable frame ignored")
                continue
            if not isinstance(msg, dict):
                continue
            if "id" in msg:
                with self._lock:
                    slot = self._pending.pop(msg["id"], None)
                if slot:
                    slot.msg = msg
                    slot.done.set()
            elif "method" in msg:
                self._events.put((msg.get("sessionId"), msg["method"], msg.get("params", {})))
        self._on_disconnected()

    def _on_disconnected(self):
        with self._lock:
            self._disconnected = True
            pending = list(self._pending.values())
            self._pending.clear()
        for slot in pending:
            slot.msg = {"disconnected": True}
            slot.done.set()
        self._events.put(_DISCONNECT)  # callbacks run on the dispatcher, after already-queued events

    def _dispatch(self):
        while True:
            item = self._events.get()
            if item is _STOP:
                return
            if item is _DISCONNECT:
                with self._lock:
                    cbs = list(self._disconnect_cbs)
                    quiet = self._closing
                if not quiet:
                    for cb in cbs:
                        try:
                            cb()
                        except Exception:
                            log.exception("cdp: on_disconnect callback raised")
                return
            session_id, method, params = item
            with self._lock:
                cbs = list(self._listeners.get((session_id, method), []))
            for cb in cbs:
                try:
                    cb(params)
                except Exception:
                    log.exception("cdp: listener for %s raised", method)

    def send(self, method, session_id=None, timeout=30, **params):
        mid = next(self._ids)
        slot = _Slot()
        with self._lock:
            if self._disconnected:
                raise CDPError("disconnected")
            self._pending[mid] = slot
        body = {"id": mid, "method": method, "params": params}
        if session_id:
            body["sessionId"] = session_id
        try:
            with self._send_lock:
                self.ws.send(json.dumps(body))
        except Exception as e:
            with self._lock:
                self._pending.pop(mid, None)
            raise CDPError("disconnected") from e
        if not slot.done.wait(timeout):
            with self._lock:
                self._pending.pop(mid, None)
            raise CDPError(f"{method} timed out")
        msg = slot.msg
        if msg.get("disconnected"):
            raise CDPError("disconnected")
        if "error" in msg:
            raise CDPError(f"{method}: {msg['error'].get('message')}")
        return msg.get("result", {})

    def on(self, session_id, method, callback):
        with self._lock:
            self._listeners[(session_id, method)].append(callback)

    def off(self, session_id, method, callback):
        with self._lock:
            cbs = self._listeners.get((session_id, method))
            if cbs and callback in cbs:
                cbs.remove(callback)
                if not cbs:
                    del self._listeners[(session_id, method)]

    def on_disconnect(self, callback):
        """Call callback() (on the dispatcher thread) when the connection drops.

        Not called for a deliberate close(). If the connection is already down, callback runs
        immediately on a helper thread.
        """
        with self._lock:
            already = self._disconnected and not self._closing
            if not already:
                self._disconnect_cbs.append(callback)
        if already:
            threading.Thread(target=callback, daemon=True).start()

    @property
    def disconnected(self) -> bool:
        return self._disconnected

    def new_tab(self, url="about:blank"):
        target = self.send("Target.createTarget", url=url, background=True)["targetId"]
        return Tab(self, target)

    def close(self):
        with self._lock:
            self._closing = True
        try:
            self.ws.close()
        except Exception:
            pass
        self._events.put(_STOP)


class Tab:
    def __init__(self, browser, target_id):
        self.browser = browser
        self.target_id = target_id
        self.session = None
        self.attach()

    def attach(self):
        self.session = self.browser.send("Target.attachToTarget", targetId=self.target_id, flatten=True)["sessionId"]
        self.on_attach()

    def on_attach(self):
        """Hook for subclasses (e.g. re-enable domains, re-register listeners)."""

    def call(self, method, **params):
        try:
            return self.browser.send(method, session_id=self.session, **params)
        except CDPError as e:
            if "Session with given id not found" not in str(e):
                raise
            self.attach()
            return self.browser.send(method, session_id=self.session, **params)

    def on(self, method, callback):
        self.browser.on(self.session, method, callback)

    def off(self, method, callback):
        self.browser.off(self.session, method, callback)

    def evaluate(self, expression, await_promise=False):
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if r.get("exceptionDetails"):
            raise CDPError("evaluate: " + r["exceptionDetails"].get("text", "exception"))
        return r.get("result", {}).get("value")

    def navigate(self, url):
        self.call("Page.navigate", url=url)

    def screenshot(self, path, full_page=False):
        import base64

        data = self.call("Page.captureScreenshot", format="jpeg", quality=70, captureBeyondViewport=full_page)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def close(self):
        self.browser.send("Target.closeTarget", targetId=self.target_id)


def wait_until(pred, timeout, poll=0.05):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if pred():
            return True
        time.sleep(poll)
    return False
