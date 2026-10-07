"""WP4 Chrome integration: steps' `next_page` on the pager_js.html fixture (isolated :9444 Chrome, KFW_CHROME_TESTS=1)."""

import json

import pytest

from kfw import form, recipes

pytestmark = pytest.mark.chrome

ROWS = {"pattern": r"\d{2}:\d{2}", "min_rows": 2, "columns": ["代號", "時間"]}


def pager(chrome, query="", max_pages=3, end="disabled", result=None, click="下一頁"):
    return {"name": "wp4-fixture", "type": "steps", "description": "fixture",
            "url": chrome.url("pager_js.html" + ("?" + query if query else "")),
            "steps": [{"next_page": {"click": click, "max_pages": max_pages, "end": end}}],
            "result": result or {"rows": ROWS, "expect_text": ["資料表"]}}


def run(r, **kw):
    return recipes.execute(r, {}, **kw)


def counts(load):
    return json.loads(load("gate_query.html").evaluate("localStorage.getItem('kfw_ev') || '{}'"))


def codes(out):
    return [r["代號"] for r in out["rows"]]


def test_three_pages_disabled_end(chrome):
    out = run(pager(chrome))
    assert out["status"] == "done" and out["more_pages"] is False and out["pages_collected"] == 3, out
    assert codes(out) == [f"P{n}{c}" for n in (1, 2, 3) for c in "ABC"] and out["rows_total"] == 9
    assert [p["page"] for p in out["pages"]] == [1, 2, 3] and all(p["rows_count"] == 3 and p["fingerprint"] for p in out["pages"])
    assert len({p["fingerprint"] for p in out["pages"]}) == 3
    assert out["rows"][0] == {"代號": "P1A", "時間": "10:00"}


def test_three_pages_absent_end(chrome):
    out = run(pager(chrome, "end=absent", end="absent"))
    assert out["status"] == "done" and out["pages_collected"] == 3 and out["rows_total"] == 9, out


def test_end_mismatch_wants_disabled_but_button_absent(chrome):
    out = run(pager(chrome, "end=absent", end="disabled"))
    assert out["status"] == "needs_help" and out["reason"] == "end_mismatch" and out["why"] == "absent", out
    assert out["pages_collected"] == 3 and out["evidence"]["screenshot"]


def test_end_mismatch_wants_absent_but_button_disabled(chrome):
    out = run(pager(chrome, "end=disabled", end="absent"))
    assert out["status"] == "needs_help" and out["reason"] == "end_mismatch" and out["why"] == "disabled", out


def test_loop_is_detected_and_partial(chrome):
    out = run(pager(chrome, "loop=1&pages=99", max_pages=6))
    assert out["status"] == "partial" and out["reason"] == "loop_detected", out
    assert out["pages_collected"] == 2 and out["more_pages"] is False and codes(out) == ["P1A", "P1B", "P1C", "P2A", "P2B", "P2C"]
    assert "不是全部" in out["hint"]


def test_dry_run_does_not_pass_a_partial(chrome):
    d = recipes.dry_run(pager(chrome, "loop=1&pages=99", max_pages=6), {})
    assert d["passed"] is False and d["result"]["status"] == "partial"
    assert recipes.dry_run(pager(chrome), {})["passed"] is True


def test_loading_skeleton_is_waited_out(chrome):
    out = run(pager(chrome, "skeleton=1"))
    assert out["status"] == "done" and out["pages_collected"] == 3 and codes(out)[3:6] == ["P2A", "P2B", "P2C"], out
    ms = [s["then_ms"] for s in out["steps"] if s.get("then")]
    assert len(ms) == 2 and all(m >= 700 for m in ms), ms  # the placeholder period was not taken for the new page


def test_max_pages_reached_reports_more(chrome):
    out = run(pager(chrome, "pages=99", max_pages=2))
    assert out["status"] == "done" and out["more_pages"] is True and out["pages_collected"] == 2, out
    assert codes(out) == ["P1A", "P1B", "P1C", "P2A", "P2B", "P2C"]
    assert "已收集前 2 頁,還有更多" in out["hint"]


def test_max_pages_equal_to_real_page_count_is_not_more(chrome):
    out = run(pager(chrome, max_pages=3))
    assert out["more_pages"] is False and out["hint"] is None


def test_single_page_max_pages_one_with_disabled_button(chrome):
    out = run(pager(chrome, "pages=1", max_pages=1))
    assert out["status"] == "done" and out["pages_collected"] == 1 and out["more_pages"] is False, out


def test_rows_are_deduplicated_across_pages(chrome):
    out = run(pager(chrome, "dup=1"))
    assert out["status"] == "done" and out["pages_collected"] == 3, out
    assert out["rows_total"] == 9 and codes(out) == [f"P{n}{c}" for n in (1, 2, 3) for c in "ABC"], codes(out)
    assert [p["rows_count"] for p in out["pages"]] == [3, 4, 4]  # per-page counts are what each page showed


def test_forbidden_word_on_the_next_button_is_refused_with_zero_events(chrome, load):
    load("gate_query.html").evaluate("localStorage.removeItem('kfw_ev')")
    out = run(pager(chrome, "bad=1", click="下一頁"))
    assert out["status"] == "needs_help" and out["reason"] == "unsafe_action" and "付款" in out["hint"], out
    assert counts(load) == {}


def test_state_changing_word_on_the_next_button_is_refused_never_authorized(chrome, load):
    load("gate_query.html").evaluate("localStorage.removeItem('kfw_ev')")
    out = run(pager(chrome, "stateful=1", click="下一頁"), allow_stateful=True)  # even with the run authorised
    assert out["status"] == "needs_help" and out["reason"] == "stateful_not_authorized" and "收藏" in out["hint"], out
    assert counts(load) == {}


def test_expect_text_is_checked_on_every_page(chrome):
    out = run(pager(chrome, "noexp=1"))
    assert out["status"] == "needs_help" and out["reason"] == "result_not_proven", out
    assert out["expect_text_missing"] == ["資料表"] and out["pages_collected"] == 3 and not out.get("rows")


def test_click_that_changes_nothing_is_step_failed(chrome, monkeypatch):
    from kfw import steps
    monkeypatch.setattr(steps, "THEN_CAP_S", 2.0)
    out = run(pager(chrome, "sameclick=1"))
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["why"] == "then_not_met", out


def test_find_clickable_sees_disabled_but_controls_does_not(chrome, load):
    tab = load("pager_js.html?pages=1")
    assert form.find_clickable(tab, "下一頁")["state"] == "disabled"
    assert form.find_clickable(tab, "下一頁", include_disabled=False)["state"] == "absent"
    assert not [c for c in form.controls(tab) if c["label"] == "下一頁"]  # controls() keeps filtering disabled
    assert form.find_clickable(tab, "不存在")["state"] == "absent"
    tab = load("pager_js.html")
    assert form.find_clickable(tab, "下一頁")["state"] == "enabled"
