"""<input type=submit value="查詢"> is a button: form_submit must find it (found in WP2 review, 2026-09-29).
Run with KFW_CHROME_TESTS=1 (isolated test Chrome)."""

import pytest

from kfw import form, recipes

pytestmark = pytest.mark.chrome


def test_input_submit_is_a_button_and_form_submit_uses_it(chrome):
    r = {"name": "input-submit", "type": "form_submit", "description": "fixture", "url": chrome.url("input_submit.html"),
         "params": {"kw": {"description": "keyword", "example": "abc", "pattern": "\\w+"}},
         "fields": [{"label": "關鍵字", "kind": "text", "value": "{kw}"}], "submit": {"click": "查詢"},
         "result": {"rows": {"pattern": "^R\\d", "min_rows": 3}, "expect_text": ["查的是 {kw}"]}}
    out = recipes.execute(r, {"kw": "abc"})
    assert out["status"] == "done", out
    assert len(out["rows"]) == 3


def test_input_buttons_are_not_text_fields(chrome):
    from kfw.page import ObservedTab
    from kfw.cdp import Browser
    b = Browser(chrome.cdp if hasattr(chrome, "cdp") else __import__("os").environ["KFW_CDP"])
    try:
        tab = ObservedTab.open(b)
        tab.goto(chrome.url("input_submit.html"))
        ctrls = form.controls(tab)
        buttons = {c["label"] for c in ctrls if c["kind"] == "button"}
        texts = [c for c in ctrls if c["kind"] == "text"]
        assert {"查詢", "清除"} <= buttons, ctrls
        assert [c["label"] for c in texts] == ["關鍵字"], texts
        tab.close()
    finally:
        b.close()


def test_groups_without_pattern_ignore_hidden_rows(chrome):
    """A user's mark has no pattern: the visible train rows win, not the larger hidden per-train stop lists (THSR demo)."""
    import os
    from kfw.page import ObservedTab
    from kfw.cdp import Browser
    b = Browser(os.environ["KFW_CDP"])
    try:
        tab = ObservedTab.open(b)
        tab.goto(chrome.url("rec_hidden_rows.html"))
        gs = form.groups(tab, None, 2, root="#res")
        best = max(gs, key=lambda g: g["total"])
        assert best["total"] == 3 and best["rows"][0]["cells"][:3] == ["15:11", "16:15", "0837"], gs
        tab.close()
    finally:
        b.close()
