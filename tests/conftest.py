import os

import chrome_harness  # noqa: F401  (first: sets KFW_HOME/KFW_CDP to throwaway values before kfw is imported)
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "chrome: needs a real Chrome (isolated :9444); runs only with KFW_CHROME_TESTS=1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("KFW_CHROME_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set KFW_CHROME_TESTS=1 to run Chrome integration tests")
    for item in items:
        if "chrome" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def chrome():
    s = chrome_harness.ChromeSession()
    print(f"\n[chrome] {s.product} id={s.browser_id}")
    yield s
    s.check_identity()
    s.stop()


@pytest.fixture
def tab(chrome):
    from kfw.cdp import Browser
    from kfw.page import ObservedTab
    chrome.check_identity()
    browser = Browser(chrome_harness.CDP_URL)
    t = ObservedTab.open(browser)
    yield t
    try:
        t.close()
    finally:
        browser.close()


@pytest.fixture
def load(chrome, tab):
    def _load(name):
        tab.navigate(chrome.url(name))
        ready = tab.wait_ready(cap_ms=8000, net_quiet_ms=200, dom_quiet_ms=200)
        assert ready.ok, ready
        return tab
    return _load
