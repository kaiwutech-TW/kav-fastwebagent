"""Isolated Chrome + static fixture server for integration tests (design section 8, M04).

Import this module BEFORE anything imports `kfw`: it points KFW_HOME at a throwaway folder and KFW_CDP at
:9444, so no test can touch the user's :9333 Chrome or ~/.kav-fastweb. The Chrome process is started only
when a test asks for it (chrome_session()), with its own --user-data-dir; its identity (browser id from
/json/version) is recorded at launch and re-checked, so a foreign Chrome squatting on :9444 is refused.
"""

import atexit
import functools
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PORT = int(os.environ.get("KFW_TEST_CDP_PORT", "9444"))  # parallel worktrees each pick their own
CDP_URL = f"http://127.0.0.1:{PORT}"
_TMP = Path(tempfile.mkdtemp(prefix="kfw-test-"))
os.environ["KFW_HOME"] = str(_TMP / "home")
os.environ["KFW_CDP"] = CDP_URL
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)

if "kfw" in sys.modules:  # a kfw imported earlier would have captured the real HOME/CDP
    raise RuntimeError("chrome_harness must be imported before kfw")

import httpx  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "site"
HOST_RULES = "MAP a.test 127.0.0.1, MAP b.test 127.0.0.1"


def _browser_id(version_json):
    m = re.search(r"/devtools/browser/([0-9a-f-]+)", version_json["webSocketDebuggerUrl"])
    assert m, version_json
    return m.group(1)


class ChromeSession:
    def __init__(self):
        from kfw import compare
        assert compare.CDP == CDP_URL and str(compare.HOME).startswith(str(_TMP)), "kfw imported with real env"
        try:
            httpx.get(f"{CDP_URL}/json/version", timeout=1)
        except httpx.HTTPError:
            pass
        else:
            raise RuntimeError(f"something already listens on :{PORT}; refusing to reuse a Chrome the harness did not start")
        self.profile = _TMP / "chrome-profile"
        self.profile.mkdir(parents=True)
        self.proc = subprocess.Popen(
            [compare.CHROME, *([] if os.environ.get("KFW_CHROME_HEADED") == "1" else ["--headless=new"]),
             f"--remote-debugging-port={PORT}", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", f"--host-resolver-rules={HOST_RULES}", "--window-size=1280,900",
             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 30
        while True:
            try:
                self.version = httpx.get(f"{CDP_URL}/json/version", timeout=1).json()
                break
            except httpx.HTTPError:
                if time.time() > end or self.proc.poll() is not None:
                    self.stop()
                    raise RuntimeError("test Chrome did not open its debugging port")
                time.sleep(0.2)
        self.browser_id = _browser_id(self.version)
        self.product = self.version["Browser"]
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(FIXTURES)))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def check_identity(self):
        now = _browser_id(httpx.get(f"{CDP_URL}/json/version", timeout=3).json())
        assert now == self.browser_id, f"the browser on :{PORT} is not the one this harness started"

    def url(self, name, host="127.0.0.1"):
        return f"http://{host}:{self.port}/{name}"

    def stop(self):
        server = getattr(self, "server", None)
        if server:
            server.shutdown()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


# fixtures that must be served with a Content-Security-Policy header (the recorder bar must survive all of them)
FIXTURE_HEADERS = {
    "rec_csp_script.html": {"Content-Security-Policy": "script-src 'none'"},
    "rec_csp_style.html": {"Content-Security-Policy": "style-src 'none'"},
    "rec_csp_tt.html": {"Content-Security-Policy": "require-trusted-types-for 'script'"},
}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        name = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
        for k, v in FIXTURE_HEADERS.get(name, {}).items():
            self.send_header(k, v)
        super().end_headers()
