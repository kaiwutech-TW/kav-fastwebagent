"""Observation layer: know when a page is actually ready, and read what is on it.

Readiness is decided by code, not by the model (see TRAPS web-agent-false-done-before-async-results):
  readyState complete  AND  network quiet (no request started or finished for net_quiet_ms,
  ignoring long-lived streams)  AND  DOM quiet (no mutation for dom_quiet_ms).
Every wait returns how long it took and which condition ended it, so traces stay honest.
"""

import time
from dataclasses import dataclass

from .cdp import Tab

# Records the time of the last DOM mutation. Installed on every new document.
MUTATION_PROBE = """
(() => { if (window.__kfwMut) return; window.__kfwMut = {last: performance.now()};
  new MutationObserver(() => { window.__kfwMut.last = performance.now(); })
    .observe(document, {subtree: true, childList: true, characterData: true, attributes: false}); })()
"""

STREAM_TYPES = {"EventSource", "WebSocket", "Ping", "CSPViolationReport"}


@dataclass
class Ready:
    ok: bool
    ms: int
    reason: str
    inflight: int = 0


class ObservedTab(Tab):
    @classmethod
    def open(cls, browser, browser_context_id=None):
        """A background tab. browser_context_id: open it in that isolated browser context (design 7.4, I8) and verify Chrome put it
        there; a tab that landed anywhere else is closed and refused, never used."""
        params = {"browserContextId": browser_context_id} if browser_context_id else {}
        tid = browser.send("Target.createTarget", url="about:blank", background=True, **params)["targetId"]
        if browser_context_id:
            got = browser.send("Target.getTargetInfo", targetId=tid)["targetInfo"].get("browserContextId")
            if got != browser_context_id:
                try:
                    browser.send("Target.closeTarget", targetId=tid)
                except Exception:
                    pass
                raise RuntimeError(f"tab was not created in the requested browser context ({got} != {browser_context_id})")
        return cls(browser, tid)

    def __init__(self, browser, target_id):
        self.inflight, self.last_net, self.last_req = {}, time.perf_counter(), 0.0
        super().__init__(browser, target_id)

    def on_attach(self):
        # Background tabs are throttled (timers, rAF, IntersectionObserver), which stalls lazy lists;
        # focus emulation keeps them rendering. A fixed viewport keeps extraction comparable across runs.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        self.call("Page.enable")
        self.call("Network.enable")
        self.call("Page.addScriptToEvaluateOnNewDocument", source=MUTATION_PROBE)
        self.on("Network.requestWillBeSent", self._req)
        for ev in ("Network.loadingFinished", "Network.loadingFailed"):
            self.on(ev, self._done)

    def _req(self, p):
        if p.get("type") in STREAM_TYPES:
            return
        self.inflight[p["requestId"]] = self.last_net = self.last_req = time.perf_counter()

    def _done(self, p):
        if self.inflight.pop(p["requestId"], None) is not None:
            self.last_net = time.perf_counter()

    def wait_ready(self, net_quiet_ms=500, dom_quiet_ms=400, max_inflight=0, stale_request_s=5.0, cap_ms=12000):
        """Block until the page is settled. Requests hanging longer than stale_request_s
        (analytics beacons, long polls) stop counting as in flight."""
        t0 = time.perf_counter()
        try:
            self.evaluate(MUTATION_PROBE)
        except Exception:
            pass
        while (time.perf_counter() - t0) * 1000 < cap_ms:
            now = time.perf_counter()
            live = [t for t in self.inflight.values() if now - t < stale_request_s]
            try:
                state = self.evaluate("[document.readyState, performance.now() - (window.__kfwMut?.last ?? 0)]")
            except Exception:
                state = None  # navigating
            if state and state[0] == "complete" and len(live) <= max_inflight \
                    and (now - self.last_net) * 1000 >= net_quiet_ms and state[1] >= dom_quiet_ms:
                return Ready(True, round((now - t0) * 1000), "settled", len(live))
            time.sleep(0.05)
        now = time.perf_counter()
        live = [t for t in self.inflight.values() if now - t < stale_request_s]
        return Ready(False, round((now - t0) * 1000), "cap", len(live))

    def goto(self, url, **kw):
        self.navigate(url)
        time.sleep(0.2)  # let the navigation start before the readiness checks
        return self.wait_ready(**kw)

    def scroll_to_load(self, max_screens=6, **kw):
        """Scroll down one viewport at a time so lazy lists render (IntersectionObserver-driven
        cards stay empty placeholders until seen), then return to the top. Returns ms spent."""
        t0 = time.perf_counter()
        for _ in range(max_screens):
            at_bottom = self.evaluate("""(() => { window.scrollBy(0, innerHeight * 0.9);
              return scrollY + innerHeight >= document.documentElement.scrollHeight - 4; })()""")
            time.sleep(0.15)  # let intersection callbacks fire and requests start
            self.wait_ready(**{"cap_ms": 3000, "net_quiet_ms": 300, "dom_quiet_ms": 250, **kw})
            if at_bottom:
                break
        self.evaluate("window.scrollTo(0, 0)")
        return round((time.perf_counter() - t0) * 1000)
