#!/usr/bin/env python3
"""WP-S spike: measure CDP behaviour for the demo recorder design. Not product code.

Run:  uv run --no-project --with websocket-client python spike/recording/spike.py --mode headless|headed
Isolated Chrome on :9445 with a temp profile. Never touches :9333, ~/.kav-fastweb or vendor/.
"""
from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import queue
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import zlib

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = os.environ.get("KFW_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PORT = 9445
P1, P2 = 18461, 18462
RECORDER_JS = open(os.path.join(HERE, "recorder.js"), encoding="utf-8").read()
q = lambda s: urllib.parse.quote(s, safe="")  # noqa: E731

# ------------------------------------------------------------------ fixtures
SERVER_LOG: list[tuple[str, str]] = []


def page(name: str, to: str = "", extra_head: str = "") -> str:
    link = f'<a id="lnk" href="{to}">go</a>' if to else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{name}</title>
<script>
document.documentElement.setAttribute('data-early', String(performance.now()));
window.__pageEarly = performance.now(); window.__pageshows = []; window.__loadId = Math.random().toString(36).slice(2);
addEventListener('pageshow', function (e) {{ window.__pageshows.push(e.persisted); }});
try {{ document.createElement('div').innerHTML = 'x'; document.documentElement.setAttribute('data-tt', 'allowed'); }}
catch (e) {{ document.documentElement.setAttribute('data-tt', 'blocked'); }}
</script>
<style>body{{background:rgb(255,238,238)}}</style>{extra_head}</head>
<body><h1>{name}</h1><button id="btn">click me</button> <input id="inp"> {link}
<script>window.__spa = 0;</script></body></html>"""


def spa_page() -> str:
    return page("spa").replace("</body>", """<button id="push">push</button> <button id="hash">hash</button>
<script>document.getElementById('push').addEventListener('click', function () { history.pushState({}, '', '/spa/x' + (++window.__spa)); });
document.getElementById('hash').addEventListener('click', function () { location.hash = '#h' + (++window.__spa); });</script></body>""")


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        to = urllib.parse.parse_qs(u.query).get("to", [""])[0]
        p = u.path
        hdr: dict[str, str] = {}
        SERVER_LOG.append((self.headers.get("Host", ""), self.path))
        if p.startswith("/spa"):
            body = spa_page()
        elif p == "/csp-script":
            hdr["Content-Security-Policy"] = "script-src 'none'"
            body = page("csp-script-none", to)
        elif p == "/csp-style":
            hdr["Content-Security-Policy"] = "style-src 'none'"
            body = page("csp-style-none", to)
        elif p == "/csp-tt":
            hdr["Content-Security-Policy"] = "require-trusted-types-for 'script'"
            body = page("csp-trusted-types", to)
        elif p == "/iframehost":
            body = page("iframehost", to).replace("</body>", f'<iframe id="same" src="http://a.test:{P2}/p2"></iframe>'
                                                  f'<iframe id="cross" src="http://b.test:{P1}/p2"></iframe></body>')
        elif p == "/favicon.ico":
            self.send_response(404)
            self.end_headers()
            return
        else:
            body = page(p.strip("/") or "root", to)
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in hdr.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


def start_servers():
    out = []
    for port in (P1, P2):
        s = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start()
        out.append(s)
    return out


# ------------------------------------------------------------------ CDP client
class CDPError(Exception):
    pass


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True, enable_multithread=True)
        self.lock = threading.Lock()
        self.next_id = 0
        self.pending: dict[int, list] = {}
        self.evq: queue.Queue = queue.Queue()
        self.listeners: list = []
        self.n = 0
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._dispatch, daemon=True).start()

    def _read(self):
        while self.alive:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
            if not raw:
                break
            msg = json.loads(raw)
            if "id" in msg and "method" not in msg:
                slot = self.pending.get(msg["id"])
                if slot:
                    slot[1] = msg
                    slot[0].set()
            else:
                self.n += 1
                msg["_n"] = self.n
                msg["_t"] = time.monotonic()
                self.evq.put(msg)

    def _dispatch(self):
        while True:
            msg = self.evq.get()
            for fn in list(self.listeners):
                try:
                    fn(msg)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()

    def send(self, method, params=None, session=None, timeout=20):
        with self.lock:
            self.next_id += 1
            i = self.next_id
            slot = [threading.Event(), None]
            self.pending[i] = slot
        m = {"id": i, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        self.ws.send(json.dumps(m))
        if not slot[0].wait(timeout):
            self.pending.pop(i, None)
            raise TimeoutError(method)
        self.pending.pop(i, None)
        r = slot[1]
        if "error" in r:
            raise CDPError(f"{method}: {r['error']}")
        return r.get("result", {})


# ------------------------------------------------------------------ PNG pixel sampling (no PIL)
def png_pixels(data: bytes, points):
    """points: list of (x, y) in image pixels. Returns (w, h, [rgb...])."""
    pos, idat = 8, b""
    w = h = bd = ct = il = 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, bd, ct, _, _, il = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat += body
    if bd != 8 or ct not in (2, 6) or il != 0:
        return w, h, None
    bpp = 3 if ct == 2 else 4
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows: list[bytearray] = []
    prev = bytearray(stride)
    p = 0
    maxy = max(y for _, y in points)
    for _y in range(min(h, maxy + 1)):
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        rows.append(line)
        prev = line
    out = []
    for x, y in points:
        if 0 <= y < len(rows) and 0 <= x < w:
            out.append(tuple(rows[y][x * bpp:x * bpp + 3]))
        else:
            out.append(None)
    return w, h, out


# ------------------------------------------------------------------ recorder driver (the "Python side" of the design)
def short(s, n=6):
    return (s or "")[-n:]


class Rec:
    def __init__(self, env, name, auto_arm=True):
        self.env = env
        self.cdp: CDP = env["cdp"]
        self.name = name
        self.auto_arm = auto_arm
        self.sid = None
        self.tid = None
        self.frame_id = None
        self.script_id = None
        self.ctx: dict[int, dict] = {}      # contextId -> latest context info
        self.ctx_history: list[dict] = []
        self.epoch = None
        self.tok_n = 0
        self.hellos: list[dict] = []
        self.armed: list[dict] = []
        self.evs: list[dict] = []
        self.arm_results: list[dict] = []
        self.log: list[tuple] = []           # (n, t, text)
        self.raw: list[dict] = []
        self.errors: list[str] = []
        self.results: dict[str, dict] = {}
        self.autoattach_cb = False
        self.cdp.listeners.append(self._on)

    # ---- plumbing
    def mark(self, text):
        self.log.append((self.cdp.n + 0.5, time.monotonic(), "## " + text))

    def call(self, method, params=None, timeout=20):
        return self.cdp.send(method, params, self.sid, timeout)

    def wait(self, cond, timeout=6.0, step=0.02):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(step)
        return cond()

    # ---- event handling
    def _on(self, msg):
        try:
            self._on2(msg)
        except Exception:  # noqa: BLE001
            self.errors.append(traceback.format_exc())

    def _on2(self, msg):
        m = msg["method"]
        p = msg.get("params", {})
        s = msg.get("sessionId")
        n, t = msg["_n"], msg["_t"]
        if m.startswith("Target."):
            ti = p.get("targetInfo", {})
            txt = f"{m} target=..{short(ti.get('targetId') or p.get('targetId'))} type={ti.get('type')} url={ti.get('url', '')[:60]}" \
                  f" attached={ti.get('attached')} session=..{short(p.get('sessionId'))} waiting={p.get('waitingForDebugger')}"
            if m == "Target.attachedToTarget":
                sid = p.get("sessionId")
                self.log.append((n, t, txt))
                if p.get("waitingForDebugger") and self.autoattach_cb:
                    threading.Thread(target=lambda: self._run_if_waiting(sid), daemon=True).start()
                return
            if s is None or s == self.sid:
                self.log.append((n, t, txt))
            return
        if s != self.sid or self.sid is None:
            return
        self.raw.append({"n": n, "method": m})
        if m == "Runtime.executionContextCreated":
            c = p["context"]
            aux = c.get("auxData", {})
            info = {"id": c["id"], "uid": c.get("uniqueId"), "name": c.get("name"), "origin": c.get("origin"),
                    "frameId": aux.get("frameId"), "isDefault": aux.get("isDefault"), "type": aux.get("type"), "n": n}
            self.ctx[c["id"]] = info
            self.ctx_history.append(info)
            self.log.append((n, t, f"ctx CREATED id={c['id']} uid=..{short(c.get('uniqueId'))} name={c.get('name')!r} "
                                   f"default={aux.get('isDefault')} type={aux.get('type')} frame=..{short(aux.get('frameId'), 4)} origin={c.get('origin')}"))
        elif m == "Runtime.executionContextDestroyed":
            self.log.append((n, t, f"ctx DESTROYED id={p.get('executionContextId')} uid=..{short(p.get('executionContextUniqueId'))}"))
        elif m == "Runtime.executionContextsCleared":
            self.log.append((n, t, "ctx CLEARED (all)"))
        elif m == "Runtime.bindingCalled":
            self._on_binding(n, t, p)
        elif m == "Page.frameNavigated":
            f = p["frame"]
            self.log.append((n, t, f"Page.frameNavigated frame=..{short(f['id'], 4)} parent={'..' + short(f.get('parentId'), 4) if f.get('parentId') else '-'} "
                                   f"type={p.get('type')} url={f['url'][:70]}"))
        elif m == "Page.navigatedWithinDocument":
            self.log.append((n, t, f"Page.navigatedWithinDocument type={p.get('navigationType')} url={p.get('url')}"))
        elif m == "Page.backForwardCacheNotUsed":
            reasons = [x.get("reason") for x in p.get("notRestoredExplanations", [])]
            self.log.append((n, t, f"Page.backForwardCacheNotUsed reasons={reasons}"))
        elif m in ("Page.loadEventFired", "Page.domContentEventFired", "Page.frameStartedLoading", "Page.frameStoppedLoading",
                   "Page.frameDetached"):
            self.log.append((n, t, m + (f" frame=..{short(p.get('frameId'), 4)}" if 'frameId' in p else "")))

    def _run_if_waiting(self, sid):
        try:
            self.cdp.send("Runtime.runIfWaitingForDebugger", {}, sid)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"runIfWaiting: {e}")

    def _on_binding(self, n, t, p):
        cid = p.get("executionContextId")
        raw = p.get("payload", "")
        try:
            pl = json.loads(raw)
        except Exception:  # noqa: BLE001
            self.log.append((n, t, f"binding ctx#{cid} BAD_JSON {raw[:60]!r}"))
            return
        ty = pl.get("type")
        verdict = ""
        known = cid in self.ctx
        if ty == "hello":
            self.tok_n += 1
            token = f"tok{self.tok_n}"
            self.epoch = {"token": token, "last_seq": 0, "ctx": cid, "armed": False, "docId": pl.get("docId")}
            self.hellos.append({"n": n, "t": t, "ctx": cid, "pl": pl, "known_ctx": known})
            verdict = f"known_ctx={known} -> epoch {token}"
            self.log.append((n, t, f"binding ctx#{cid} hello restored={pl.get('restored')} persisted={pl.get('persisted')} "
                                   f"navType={pl.get('navType')} rs={pl.get('readyState')} body={pl.get('hasBody')} early={pl.get('earlyAttr')} "
                                   f"jsT={pl.get('t'):.1f} {verdict}"))
            if self.auto_arm:
                self.arm(cid)
            return
        ep = self.epoch
        if ty == "armed":
            ok = ep is not None and pl.get("token") == ep["token"]
            if ok:
                ep["armed"] = True
            self.armed.append({"n": n, "t": t, "ctx": cid, "pl": pl, "ok": ok})
            self.log.append((n, t, f"binding ctx#{cid} armed token={pl.get('token')} preArm={pl.get('preArm')} preKinds={pl.get('preKinds')} ok={ok}"))
            return
        # ev / pagehide / ui_click: validate token, ctx, seq
        if ep is None:
            verdict = "no_epoch"
        elif pl.get("token") != ep["token"]:
            verdict = f"BAD_TOKEN({pl.get('token')} != {ep['token']})"
        elif cid != ep["ctx"]:
            verdict = f"CTX_MISMATCH({cid} != {ep['ctx']})"
        elif pl.get("seq") != ep["last_seq"] + 1:
            verdict = f"SEQ_GAP(exp {ep['last_seq'] + 1} got {pl.get('seq')})"
            ep["last_seq"] = pl.get("seq") or ep["last_seq"]
        else:
            ep["last_seq"] = pl["seq"]
            verdict = "ok"
        self.evs.append({"n": n, "t": t, "ctx": cid, "pl": pl, "verdict": verdict})
        self.log.append((n, t, f"binding ctx#{cid} {ty} kind={pl.get('kind')} tag={pl.get('tag')} key={pl.get('key')} seq={pl.get('seq')} verdict={verdict}"))

    def arm(self, cid, by="contextId"):
        ep = self.epoch
        params = {"expression": f"__kfwArm('{ep['token']}')", "returnByValue": True}
        if by == "unique":
            params["uniqueContextId"] = self.ctx[cid]["uid"]
        else:
            params["contextId"] = cid
        t0 = time.monotonic()
        r = self.cdp.send("Runtime.evaluate", params, self.sid)
        val = r.get("result", {}).get("value")
        exc = r.get("exceptionDetails", {}).get("exception", {}).get("description")
        self.arm_results.append({"by": by, "ctx": cid, "value": val, "exc": exc, "ms": (time.monotonic() - t0) * 1000})
        self.log.append((self.cdp.n + 0.5, time.monotonic(), f"PY arm({by}) ctx#{cid} -> {val!r} {exc or ''}"))

    # ---- startup (design 2.2 order)
    def start(self, autoattach=False):
        c = self.cdp
        r = c.send("Target.createTarget", {"url": "about:blank", "background": False})
        self.tid = r["targetId"]
        self.sid = c.send("Target.attachToTarget", {"targetId": self.tid, "flatten": True})["sessionId"]
        self.call("Page.enable")
        self.call("Runtime.enable")
        if autoattach:
            self.autoattach_cb = True
            self.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
        self.call("Runtime.addBinding", {"name": "__kfwRec", "executionContextName": "kfw_rec"})
        self.script_id = self.call("Page.addScriptToEvaluateOnNewDocument", {"source": RECORDER_JS, "worldName": "kfw_rec"})["identifier"]
        self.frame_id = self.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
        self.mark(f"START target=..{short(self.tid)} session=..{short(self.sid)} mainFrame=..{short(self.frame_id, 4)} script={self.script_id}")

    def stop(self):
        try:
            self.call("Page.removeScriptToEvaluateOnNewDocument", {"identifier": self.script_id})
        except Exception:  # noqa: BLE001
            pass
        try:
            self.cdp.send("Target.closeTarget", {"targetId": self.tid})
        except Exception:  # noqa: BLE001
            pass
        if self._on in self.cdp.listeners:
            self.cdp.listeners.remove(self._on)

    # ---- helpers
    def ev_main(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            return {"exception": (d.get("exception") or {}).get("description") or d.get("text")}
        return r["result"].get("value", r["result"].get("description", r["result"].get("type")))

    def ev_iso(self, expr, cid=None):
        cid = cid or (self.epoch or {}).get("ctx")
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "contextId": cid})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            return {"exception": (d.get("exception") or {}).get("description") or d.get("text")}
        return r["result"].get("value")

    def center(self, sel):
        v = self.ev_main(f"(()=>{{const r=document.querySelector({json.dumps(sel)}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()")
        return v

    def click_xy(self, x, y):
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {"type": typ, "x": x, "y": y, "button": "left" if typ != "mouseMoved" else "none",
                                                   "buttons": 1 if typ == "mousePressed" else 0, "clickCount": 1 if typ != "mouseMoved" else 0})

    def click_sel(self, sel):
        x, y = self.center(sel)
        self.click_xy(x, y)

    def key(self, k, code, vk, text=None):
        p = {"key": k, "code": code, "windowsVirtualKeyCode": vk}
        if text:
            p["text"] = text
        self.call("Input.dispatchKeyEvent", {"type": "keyDown", **p})
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", **p})

    def exercise(self):
        """click btn, click inp, key x (keydown+input), insertText yz (input) -> expect 5 events."""
        n0 = len(self.evs)
        self.mark("EXERCISE click #btn, click #inp, key x, insertText yz")
        self.click_sel("#btn")
        self.click_sel("#inp")
        self.key("x", "KeyX", 88, "x")
        self.call("Input.insertText", {"text": "yz"})
        self.wait(lambda: len(self.evs) - n0 >= 5, 2.0)
        time.sleep(0.15)
        got = self.evs[n0:]
        return {"expected": 5, "received": len(got), "kinds": [e["pl"].get("kind") or e["pl"].get("type") for e in got],
                "verdicts": sorted({e["verdict"] for e in got}), "seqs": [e["pl"].get("seq") for e in got]}

    def shot(self, name):
        r = self.call("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(r["data"])
        d = os.path.join(self.env["out"], "shots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{self.env['mode']}-{name}.png"), "wb") as f:
            f.write(data)
        return data

    def ui_pixel(self, data, info_key="btnRect"):
        """Sample a pixel in the button's left padding; expected rgb(0,170,119)."""
        info = self.ev_iso("__kfwInfo()")
        if not isinstance(info, dict) or not info.get(info_key):
            return {"sampled": None}
        vw = self.ev_main("innerWidth")
        bx, by, bw, bh = info[info_key]
        w, h, _ = png_pixels(data, [(0, 0)])
        scale = w / vw if vw else 1
        px = int((bx + 4) * scale)
        py = int((by + bh / 2) * scale)
        _, _, pix = png_pixels(data, [(px, py)])
        return {"png": [w, h], "scale": round(scale, 2), "at": [px, py], "rgb": list(pix[0]) if pix and pix[0] else None}

    def isolate(self):
        try:
            return short(self.call("Runtime.getIsolateId")["id"], 8)
        except Exception as e:  # noqa: BLE001
            return f"err {e}"

    # ---- one measured step
    def step(self, name, action, exercise=True, wait_armed=True, timeout=8.0, extra=None):
        h0, a0, e0 = len(self.hellos), len(self.armed), len(self.evs)
        c0 = len(self.ctx_history)
        n_start = self.cdp.n
        t_start = time.monotonic()
        self.mark(f"STEP {name}: ACTION")
        old_epoch_ctx = (self.epoch or {}).get("ctx")
        ares = action()
        got_h = self.wait(lambda: len(self.hellos) > h0, timeout)
        got_a = self.wait(lambda: len(self.armed) > a0, 3.0) if (got_h and wait_armed and self.auto_arm) else False
        f = {"action_result": ares if isinstance(ares, (dict, str, int, type(None))) else str(ares),
             "hello": got_h, "armed": got_a}
        if got_h:
            hh = self.hellos[h0]
            f["t_hello_ms"] = round((hh["t"] - t_start) * 1000)
            f["hello"] = {k: hh["pl"].get(k) for k in ("restored", "persisted", "navType", "readyState", "hasBody", "earlyAttr", "href")}
            f["hello_known_ctx"] = hh["known_ctx"]
            f["hello_contextId"] = hh["ctx"]
            f["hello_jsT"] = hh["pl"].get("t")
        if got_a:
            f["t_armed_ms"] = round((self.armed[a0]["t"] - t_start) * 1000)
            f["arm_result"] = self.arm_results[-1] if self.arm_results else None
        f["hello_count_delta"] = len(self.hellos) - h0
        time.sleep(0.1)
        f["new_contexts"] = [{k: c[k] for k in ("id", "uid", "name", "isDefault", "frameId")} | {"uid": short(c["uid"], 6), "frameId": short(c["frameId"], 4)}
                             for c in self.ctx_history[c0:]]
        f["kfw_rec_ctx_ids"] = [c["id"] for c in self.ctx_history[c0:] if c["name"] == "kfw_rec"]
        f["kfw_rec_uids"] = [short(c["uid"], 6) for c in self.ctx_history[c0:] if c["name"] == "kfw_rec"]
        f["isolate"] = self.isolate()
        try:
            f["main_world"] = self.ev_main("({early: window.__pageEarly, dataEarly: document.documentElement.getAttribute('data-early'), dataTT: document.documentElement.getAttribute('data-tt'), loadId: window.__loadId, pageshows: window.__pageshows, href: location.href})")
        except Exception as e:  # noqa: BLE001
            f["main_world"] = f"err {e}"
        mw = f["main_world"] if isinstance(f["main_world"], dict) else {}
        if got_h and mw.get("early") is not None and f.get("hello_jsT") is not None:
            f["recorder_before_page_script"] = f["hello_jsT"] < mw["early"] if not mw.get("pageshows") or len(mw["pageshows"]) == 1 else None
            f["hello_earlyAttr_null"] = f["hello"]["earlyAttr"] is None
        # pagehide from the previous document
        ph = [e for e in self.evs[e0:] if e["pl"].get("type") == "pagehide"]
        f["pagehide_msgs"] = [{"ctx": e["ctx"], "verdict": e["verdict"], "persisted": e["pl"].get("persisted")} for e in ph]
        if exercise and got_h and got_a:
            f["exercise"] = self.exercise()
        if extra:
            f.update(extra())
        self.results[name] = f
        self.dump(name, n_start, t_start)
        return f

    def dump(self, name, n_start, t_start):
        d = os.path.join(self.env["out"], "timelines", self.env["mode"])
        os.makedirs(d, exist_ok=True)
        lines = []
        for n, t, txt in sorted(self.log, key=lambda x: x[0]):
            if n >= n_start:
                lines.append(f"{(t - t_start) * 1000:9.1f}ms  n={int(n):5d}  {txt}")
        with open(os.path.join(d, f"{self.name}-{name}.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        self.results[name]["timeline_lines"] = len(lines)


# ------------------------------------------------------------------ scenarios
def ps_renderers(pid):
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            procs[int(parts[0])] = (int(parts[1]), parts[2])
    desc = set()
    changed = True
    while changed:
        changed = False
        for p, (pp, _c) in procs.items():
            if p not in desc and (pp == pid or pp in desc):
                desc.add(p)
                changed = True
    return sorted(p for p in desc if "--type=renderer" in procs[p][1])


def scen_chain(env):
    """S1..S6: initial, reload, same-origin, cross-origin same-site, cross-site (link click), then browser-initiated cross-site."""
    u5 = f"http://b.test:{P1}/p1"
    u4 = f"http://a.test:{P2}/p1?to={q(u5)}"
    u3 = f"http://a.test:{P1}/p2?to={q(u4)}"
    u1 = f"http://a.test:{P1}/p1?to={q(u3)}"
    rec = Rec(env, "chain")
    rec.start()
    try:
        rec.step("S1-initial-navigation", lambda: rec.call("Page.navigate", {"url": u1}),
                 extra=lambda: {"ui": rec.ev_iso("__kfwInfo()"),
                                "arm_by_uniqueContextId_probe": rec.call("Runtime.evaluate", {"expression": "typeof __kfwArm", "returnByValue": True,
                                                                                             "uniqueContextId": rec.ctx[rec.epoch["ctx"]]["uid"]}).get("result", {}).get("value"),
                                "ui_pixel": rec.ui_pixel(rec.shot("S1-baseline"))})
        rec.step("S2-reload", lambda: rec.call("Page.reload"))
        rec.step("S3-same-origin-page-change(link click)", lambda: rec.click_sel("#lnk"))
        rec.step("S4-cross-origin-same-site(a.test:p1->a.test:p2, link click)", lambda: rec.click_sel("#lnk"))
        before = ps_renderers(env["chrome_pid"])
        iso_before = rec.isolate()
        rec.step("S5-cross-site(a.test->b.test, link click)", lambda: rec.click_sel("#lnk"),
                 extra=lambda: {"renderers_before": before, "renderers_after": ps_renderers(env["chrome_pid"]), "isolate_before": iso_before})
        before = ps_renderers(env["chrome_pid"])
        iso_before = rec.isolate()
        rec.step("S5b-cross-site-browser-initiated(b.test->a.test, Page.navigate)",
                 lambda: rec.call("Page.navigate", {"url": f"http://a.test:{P1}/p1"}),
                 extra=lambda: {"renderers_before": before, "renderers_after": ps_renderers(env["chrome_pid"]), "isolate_before": iso_before})
        # contextId reuse across all documents of this tab
        seen: dict[int, set] = {}
        for c in rec.ctx_history:
            if c["name"] == "kfw_rec":
                seen.setdefault(c["id"], set()).add(c["uid"])
        rec.results["_contextId_reuse"] = {"kfw_rec_contexts": len([c for c in rec.ctx_history if c["name"] == "kfw_rec"]),
                                           "ids_with_multiple_uids": {str(k): len(v) for k, v in seen.items() if len(v) > 1},
                                           "all_ids": sorted(seen)}
        rec.results["_all_ctx"] = [f"id={c['id']} uid=..{short(c['uid'])} name={c['name']} default={c['isDefault']} origin={c['origin']}" for c in rec.ctx_history]
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_spa(env):
    rec = Rec(env, "spa")
    rec.start()
    try:
        rec.step("S6a-navigate-spa", lambda: rec.call("Page.navigate", {"url": f"http://a.test:{P1}/spa"}))
        h0 = len(rec.hellos)
        tok0 = rec.epoch["token"]

        def act():
            rec.click_sel("#push")
            time.sleep(0.3)
            rec.click_sel("#hash")
            time.sleep(0.3)
            rec.ev_main("history.back()")
            time.sleep(0.5)
            return "pushState click, hash click, history.back()"

        f = rec.step("S6b-spa-pushState-hash-back", act, exercise=False, timeout=1.0, wait_armed=False)
        f["new_hello_after_spa"] = len(rec.hellos) - h0
        f["epoch_token_unchanged"] = rec.epoch["token"] == tok0
        f["events_during_spa"] = [{"kind": e["pl"].get("kind"), "seq": e["pl"].get("seq"), "verdict": e["verdict"]} for e in rec.evs]
        f["exercise_after_spa"] = rec.exercise()
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_bfcache(env, same_site):
    tag = "same-site" if same_site else "cross-site"
    b = f"http://a.test:{P2}/p2" if same_site else f"http://b.test:{P1}/p2"
    a = f"http://a.test:{P1}/p1?to={q(b)}"
    rec = Rec(env, f"bfcache-{tag}")
    rec.start()
    try:
        rec.step(f"7-{tag}-A-load", lambda: rec.call("Page.navigate", {"url": a}))
        load_id_a = rec.ev_main("window.__loadId")
        rec.step(f"7-{tag}-B-click-link", lambda: rec.click_sel("#lnk"))
        hist = rec.call("Page.getNavigationHistory")
        prev = hist["entries"][hist["currentIndex"] - 1]["id"]
        ctxs_before = len(rec.ctx_history)

        def back():
            return rec.call("Page.navigateToHistoryEntry", {"entryId": prev})

        f = rec.step(f"7-{tag}-back-to-A", back, extra=lambda: {"loadId_same_as_before": rec.ev_main("window.__loadId") == load_id_a,
                                                                 "loadId_before": load_id_a, "loadId_after": rec.ev_main("window.__loadId"),
                                                                 "js_pageshow_persisted_list": rec.ev_main("window.__pageshows"),
                                                                 "iso_info_after_restore": rec.ev_iso("__kfwInfo()")})
        hist = rec.call("Page.getNavigationHistory")
        nxt = hist["entries"][hist["currentIndex"] + 1]["id"]
        rec.step(f"7-{tag}-forward-to-B", lambda: rec.call("Page.navigateToHistoryEntry", {"entryId": nxt}),
                 extra=lambda: {"js_pageshow_persisted_list": rec.ev_main("window.__pageshows")})
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_csp(env, key, path):
    rec = Rec(env, f"csp-{key}")
    rec.start()
    try:
        url = f"http://a.test:{P1}{path}"

        def extra():
            out = {}
            if not rec.epoch or rec.epoch["ctx"] is None:
                return out
            out["ui_info"] = rec.ev_iso("__kfwInfo()")
            out["probe"] = rec.ev_iso("__kfwProbe()")
            out["main_bg"] = rec.ev_main("getComputedStyle(document.body).backgroundColor")
            data = rec.shot(f"csp-{key}")
            out["ui_pixel_visible"] = rec.ui_pixel(data)
            info = out["ui_info"] if isinstance(out["ui_info"], dict) else {}
            out["body_children_before_teardown"] = rec.ev_main("document.body.childElementCount")
            # click the UI button (real input at button centre)
            if info.get("btnRect"):
                bx, by, bw, bh = info["btnRect"]
                u0 = len([e for e in rec.evs if e["pl"].get("type") == "ui_click"])
                rec.mark("EXERCISE click recorder UI button")
                rec.click_xy(bx + bw / 2, by + bh / 2)
                ok = rec.wait(lambda: len([e for e in rec.evs if e["pl"].get("type") == "ui_click"]) > u0, 2.0)
                out["ui_button_click_received"] = ok
                # our own UI must not produce a normal pointerdown event
                out["ui_click_events"] = [(e["pl"].get("type"), e["verdict"]) for e in rec.evs[-3:]]
            return out

        f = rec.step(f"8-csp-{key}", lambda: rec.call("Page.navigate", {"url": url}), exercise=True, timeout=6.0, extra=extra)
        if f.get("hello") and rec.epoch:
            rec.mark("TEARDOWN")
            n_ev = len(rec.evs)
            f["teardown_return"] = rec.ev_iso("__kfwTeardown()")
            f["ui_after_teardown"] = rec.ev_iso("__kfwInfo()")
            f["body_children_after_teardown"] = rec.ev_main("document.body.childElementCount")
            f["ui_pixel_after_teardown"] = rec.ui_pixel(rec.shot(f"csp-{key}-after")) if False else None
            rec.click_sel("#btn")
            rec.key("x", "KeyX", 88, "x")
            time.sleep(0.3)
            f["events_after_teardown"] = len(rec.evs) - n_ev
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_main_world(env):
    rec = Rec(env, "mainworld")
    rec.start()
    try:
        def extra():
            out = {}
            out["main_typeof"] = rec.ev_main("[typeof window.__kfwRec, typeof window.__kfwArm, typeof window.__kfwTeardown, typeof window.__kfwInfo, typeof globalThis.__kfwInstalled, Object.getOwnPropertyNames(window).filter(function(k){return k.indexOf('kfw')>=0}).join(',')]")
            n0 = len(rec.evs)
            nb = rec.cdp.n
            out["main_call_binding"] = rec.ev_main("window.__kfwRec(JSON.stringify({type:'ev',token:'x',seq:1}))")
            out["main_call_arm"] = rec.ev_main("window.__kfwArm('evil')")
            time.sleep(0.4)
            out["bindingCalled_after_main_calls"] = [x for x in rec.log if x[0] > nb and "binding" in x[2]]
            out["bindingCalled_after_main_calls"] = len(out["bindingCalled_after_main_calls"])
            out["iso_typeof_positive_control"] = rec.ev_iso("[typeof window.__kfwRec, typeof window.__kfwArm]")
            w = rec.call("Page.createIsolatedWorld", {"frameId": rec.frame_id, "worldName": "other"})
            out["other_isolated_world_typeof"] = rec.call("Runtime.evaluate", {"expression": "[typeof window.__kfwRec, typeof window.__kfwArm]", "returnByValue": True,
                                                                               "contextId": w["executionContextId"]}).get("result", {}).get("value")
            # page itself trying to spoof: inject a script tag in main world defining fake binding
            out["main_defines_fake_then_calls"] = rec.ev_main("window.__kfwRec = function(x){return 'fake'}; window.__kfwRec('a')")
            out["iso_binding_still_real"] = rec.ev_iso("typeof window.__kfwRec")
            out["evs_with_bad_verdict_after"] = [e["verdict"] for e in rec.evs[n0:]]
            return out

        rec.step("9-main-world", lambda: rec.call("Page.navigate", {"url": f"http://a.test:{P1}/p1"}), exercise=False, extra=extra)
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_prearm(env):
    rec = Rec(env, "prearm", auto_arm=False)
    rec.start()
    try:
        def extra():
            out = {}
            n0 = len(rec.evs)
            rec.mark("EXERCISE before arm")
            out["exercise_before_arm"] = None
            rec.click_sel("#btn")
            rec.click_sel("#inp")
            rec.key("x", "KeyX", 88, "x")
            rec.call("Input.insertText", {"text": "yz"})
            time.sleep(0.4)
            out["events_received_before_arm"] = len(rec.evs) - n0
            a0 = len(rec.armed)
            rec.arm(rec.epoch["ctx"])
            rec.wait(lambda: len(rec.armed) > a0, 2.0)
            out["armed_msg"] = rec.armed[-1]["pl"] if len(rec.armed) > a0 else None
            out["exercise_after_arm"] = rec.exercise()
            return out

        rec.step("10-input-before-arm", lambda: rec.call("Page.navigate", {"url": f"http://a.test:{P1}/p1"}), exercise=False, wait_armed=False, extra=extra)
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_autoattach(env):
    """11: autoAttach(waitForDebuggerOnStart) on the page session + iframe host + cross-site nav."""
    rec = Rec(env, "autoattach")
    rec.start(autoattach=True)
    try:
        b = f"http://b.test:{P1}/iframehost"
        a = f"http://a.test:{P1}/iframehost?to={q(b)}"
        f1 = rec.step("11a-iframehost-with-autoAttach", lambda: rec.call("Page.navigate", {"url": a}),
                      extra=lambda: {"kfw_rec_contexts_all_frames": [c for c in rec.ctx_history if c["name"] == "kfw_rec"] and
                                     [{"id": c["id"], "frame_is_main": c["frameId"] == rec.frame_id} for c in rec.ctx_history if c["name"] == "kfw_rec"],
                                     "frame_tree": rec.call("Page.getFrameTree")["frameTree"]["childFrames"] and
                                     [c["frame"]["url"] for c in rec.call("Page.getFrameTree")["frameTree"]["childFrames"]]})
        rec.step("11b-cross-site-nav-with-autoAttach", lambda: rec.click_sel("#lnk"))
    finally:
        rec.stop()
    return rec.results, rec.errors


def scen_autoattach_off(env):
    """11 control: same as above without autoAttach (iframes present; how many kfw_rec contexts)."""
    rec = Rec(env, "noautoattach")
    rec.start(autoattach=False)
    try:
        b = f"http://b.test:{P1}/iframehost"
        a = f"http://a.test:{P1}/iframehost?to={q(b)}"
        rec.step("11c-iframehost-no-autoAttach", lambda: rec.call("Page.navigate", {"url": a}),
                 extra=lambda: {"kfw_rec_contexts": [{"id": c["id"], "frame_is_main": c["frameId"] == rec.frame_id} for c in rec.ctx_history if c["name"] == "kfw_rec"],
                                "frame_tree": [c["frame"]["url"] for c in rec.call("Page.getFrameTree")["frameTree"].get("childFrames", [])]})
        rec.step("11d-cross-site-nav-no-autoAttach", lambda: rec.click_sel("#lnk"))
    finally:
        rec.stop()
    return rec.results, rec.errors


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["headless", "headed"], default="headless")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
        sys.exit(f"port {PORT} already in use; refusing")
    except Exception:  # noqa: BLE001
        pass
    servers = start_servers()
    prof = tempfile.mkdtemp(prefix="kfw-spike-")
    args = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
            "--host-resolver-rules=MAP a.test 127.0.0.1, MAP b.test 127.0.0.1"]
    if a.mode == "headless":
        args.insert(1, "--headless=new")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        ver = None
        for _ in range(100):
            try:
                ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1))
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        if not ver:
            sys.exit("chrome did not start")
        cdp = CDP(ver["webSocketDebuggerUrl"])
        env = {"cdp": cdp, "out": out, "mode": a.mode, "chrome_pid": proc.pid}
        cdp.send("Target.setDiscoverTargets", {"discover": True})
        results = {"chrome": ver.get("Browser"), "protocol": ver.get("Protocol-Version"), "user_agent": ver.get("User-Agent"), "mode": a.mode,
                   "browser_id": ver["webSocketDebuggerUrl"].rsplit("/", 1)[-1], "scenarios": {}}
        scenarios = [
            ("chain", lambda: scen_chain(env)),
            ("spa", lambda: scen_spa(env)),
            ("bfcache-cross-site", lambda: scen_bfcache(env, False)),
            ("bfcache-same-site", lambda: scen_bfcache(env, True)),
            ("csp-script-none", lambda: scen_csp(env, "script-none", "/csp-script")),
            ("csp-style-none", lambda: scen_csp(env, "style-none", "/csp-style")),
            ("csp-trusted-types", lambda: scen_csp(env, "trusted-types", "/csp-tt")),
            ("main-world", lambda: scen_main_world(env)),
            ("prearm", lambda: scen_prearm(env)),
            ("autoattach", lambda: scen_autoattach(env)),
            ("no-autoattach", lambda: scen_autoattach_off(env)),
        ]
        for name, fn in scenarios:
            if a.only and a.only not in name:
                continue
            print("== scenario", name, flush=True)
            try:
                res, errs = fn()
                results["scenarios"][name] = {"results": res, "errors": errs}
            except Exception:  # noqa: BLE001
                results["scenarios"][name] = {"error": traceback.format_exc()}
                print(traceback.format_exc(), flush=True)
        hosts = {}
        for h, _p in SERVER_LOG:
            hosts[h] = hosts.get(h, 0) + 1
        results["server_hosts_seen"] = hosts
        fn = f"results-{a.mode}{'-' + a.only if a.only else ''}.json"
        with open(os.path.join(out, fn), "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1, default=str)
        print("wrote", fn)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(prof, ignore_errors=True)
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()
