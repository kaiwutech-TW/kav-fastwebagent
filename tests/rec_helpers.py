"""Helpers for the WP1 recorder Chrome tests: a second CDP connection that plays the user (Input.* events),
reads the page's main world and reaches the recorder's isolated world (only tests do that)."""

import json
import time

from chrome_harness import CDP_URL

from kfw.cdp import Browser, wait_until

SHIFT, CTRL, META, ALT = 8, 2, 4, 1


class Sim:
    def __init__(self, target_id):
        self.browser = Browser(CDP_URL)
        self.tid = target_id
        self.sid = self.browser.send("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
        self.kfw_ctx = None
        self.main_frame = None
        self.browser.on(self.sid, "Runtime.executionContextCreated", self._ctx)
        self.browser.on(self.sid, "Runtime.executionContextsCleared", lambda p: setattr(self, "kfw_ctx", None))
        self.call("Page.enable")
        self.main_frame = self.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
        self.call("Runtime.enable")

    def _ctx(self, p):
        c = p["context"]
        if c.get("name") == "kfw_rec" and (c.get("auxData") or {}).get("frameId") == self.main_frame:
            self.kfw_ctx = c["id"]

    def call(self, method, **p):
        return self.browser.send(method, session_id=self.sid, **p)

    def close(self):
        self.browser.close()

    # ---- reading ----
    def ev(self, expr, gesture=False):
        """Main world (the site's own world)."""
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, userGesture=gesture, awaitPromise=False)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"])
        return r.get("result", {}).get("value")

    def iso(self, expr):
        """The recorder's isolated world (name kfw_rec)."""
        assert wait_until(lambda: self.kfw_ctx is not None, 5), "no kfw_rec context"
        r = self.call("Runtime.evaluate", expression=expr, contextId=self.kfw_ctx, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"])
        return r.get("result", {}).get("value")

    def info(self):
        return self.iso("__kfwInfo()")

    def rect(self, sel):
        r = self.ev(f"(() => {{ const r = document.querySelector({json.dumps(sel)}).getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }})()")
        return r

    # ---- acting like the user ----
    def mouse(self, type_, x, y, button="none", clicks=0, modifiers=0):
        self.call("Input.dispatchMouseEvent", type=type_, x=x, y=y, button=button, clickCount=clicks, modifiers=modifiers)

    def click_at(self, x, y, modifiers=0, button="left"):
        self.mouse("mouseMoved", x, y, modifiers=modifiers)
        self.mouse("mousePressed", x, y, button, 1, modifiers)
        self.mouse("mouseReleased", x, y, button, 1, modifiers)

    def click(self, sel, modifiers=0, button="left"):
        x, y, w, h = self.rect(sel)
        self.click_at(x + min(w / 2, 40), y + h / 2, modifiers, button)

    def click_bar(self, which):
        """Click the recorder's own button (`mark` or `done`) with real mouse events."""
        x, y, w, h = self.info()[which + "Btn"]
        self.click_at(x + w / 2, y + h / 2)

    def key(self, key, code=None, text=None, modifiers=0, commands=None):
        p = {"key": key, "code": code or key, "modifiers": modifiers}
        if text is not None:
            p["text"] = text
        if commands:
            p["commands"] = commands
        if key in ("Enter",):
            p["windowsVirtualKeyCode"] = 13
            p.setdefault("text", "\r")
        elif key == "Escape":
            p["windowsVirtualKeyCode"] = 27
        elif key == "ArrowDown":
            p["windowsVirtualKeyCode"] = 40
        elif key == "ArrowUp":
            p["windowsVirtualKeyCode"] = 38
        self.call("Input.dispatchKeyEvent", type="keyDown" if text is None and key != "Enter" else "keyDown", **p)
        q = {k: v for k, v in p.items() if k not in ("text", "commands")}
        self.call("Input.dispatchKeyEvent", type="keyUp", **q)

    def type_keys(self, s):
        for ch in s:
            self.key(ch, code="Key" + ch.upper(), text=ch)

    def insert(self, s):
        self.call("Input.insertText", text=s)

    def focus_by_click(self, sel):
        self.click(sel)
        assert wait_until(lambda: self.ev(f"document.activeElement === document.querySelector({json.dumps(sel)})"), 3)

    def wheel(self, x, y, dy=120):
        self.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=dy)

    # ---- navigation ----
    def back(self):
        h = self.call("Page.getNavigationHistory")
        self.call("Page.navigateToHistoryEntry", entryId=h["entries"][h["currentIndex"] - 1]["id"])

    def forward(self):
        h = self.call("Page.getNavigationHistory")
        self.call("Page.navigateToHistoryEntry", entryId=h["entries"][h["currentIndex"] + 1]["id"])


def settle(seconds=0.5):
    time.sleep(seconds)


def groups_of(rec):
    """Closed/open groups of a live Recording, in order."""
    return sorted(rec.debug()["groups"], key=lambda g: (g["epoch"], int(g["gid"][1:])))
