"""WP3 Chrome integration: the steps engine on fixture sites (isolated :9444 Chrome, KFW_CHROME_TESTS=1).
Fixture pages count every pointerdown/mousedown/click/keydown/input/beforeinput they receive into localStorage
(gate_counter.js), so refused runs are shown to dispatch nothing and a stateful click is shown to happen once."""

import json

import pytest

from kfw import recipes, steps

pytestmark = pytest.mark.chrome

TIME_ROWS = {"pattern": r"\d{2}:\d{2}", "min_rows": 2}


def flow(chrome, page, step_list, result=None, host="127.0.0.1"):
    return {"name": "wp3-fixture", "type": "steps", "description": "fixture", "url": chrome.url(page, host),
            "steps": step_list, "result": result or {"rows": TIME_ROWS}}


def counts(load):
    return json.loads(load("gate_query.html").evaluate("localStorage.getItem('kfw_ev') || '{}'"))


def clear_counts(load):
    load("gate_query.html").evaluate("localStorage.removeItem('kfw_ev')")


def run(recipe, **kw):
    return recipes.execute(recipe, {}, **kw)


def click(label, then, **kw):
    return {"click": label, "then": then, **kw}


# ---------- the normal three-page flow ----------

def test_three_page_flow_is_done(chrome):
    r = flow(chrome, "steps_home.html", [
        click("不同意", {"gone": "不同意"}, optional=True),
        {"select": "出發站", "value": "台中"},
        {"fill": "出發日期", "value": "2026/10/12"},
        {"check": "只看直達車", "value": True},
        click("查詢", {"text": "查詢完成"}),
        click("下一頁", {"url_contains": "steps_results"}),
        {"wait": {"text": "結果已載入"}},
    ], {"rows": {"pattern": r"\d{4} \d{2}:\d{2}", "min_rows": 3, "columns": ["車次", "出發", "抵達"]},
        "expect_text": ["出發站:台中", "日期:2026/10/12", "直達:是"]}, host="a.test")
    out = run(r)
    assert out["status"] == "done", out
    assert out["rows"][0] == {"車次": "0648", "出發": "15:00", "抵達": "16:02"} and out["rows_total"] == 3
    assert out["expect_text_missing"] == []
    log = out["steps"]
    assert any(s.get("click") == "不同意" and s.get("then") == {"gone": "不同意"} for s in log)
    assert any(s.get("select") == "出發站" and s.get("how") == "exact" for s in log)
    assert any(s.get("check") == "只看直達車" and s.get("read_back") is True for s in log)
    assert any(s.get("click") == "下一頁" and s.get("ready") for s in log)  # a new document waited for readiness


def test_optional_click_is_skipped_when_absent_and_check_is_idempotent(chrome):
    r = flow(chrome, "steps_home.html", [
        click("不存在的橫幅", {"gone": "不存在的橫幅"}, optional=True),
        {"check": "只看直達車", "value": False},
        click("查詢", {"text": "查詢完成"}),
    ], {"expect_text": ["查詢完成"]}, host="a.test")
    out = run(r)
    assert out["status"] == "done", out
    assert out["steps"][2].get("skipped") and out["steps"][3].get("already") is True


def test_wait_is_pure_state_and_times_out(chrome, monkeypatch):
    monkeypatch.setattr(steps, "THEN_CAP_S", 2.0)
    ok = run(flow(chrome, "steps_dyn.html?mode=delay&ms=0", [
        {"wait": {"text": "城市"}}], {"expect_text": ["城市"]}))
    assert ok["status"] == "done", ok
    out = run(flow(chrome, "steps_dyn.html?mode=stale", [{"wait": {"text": "永遠不會出現"}}], {"expect_text": ["城市"]}))
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["why"] == "wait_timeout", out
    assert out["step_index"] == 0 and out["step"] == {"wait": {"text": "永遠不會出現"}} and out["evidence"]["screenshot"]


def test_select_never_guesses(chrome):
    r = flow(chrome, "steps_home.html", [{"select": "出發站", "value": "高雄"}], {"expect_text": ["x"]})
    out = run(r)
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["why"] == "not_found", out
    assert "台北" in out["options"] and out["kev"]["calls"] == 0


def test_radio_can_only_be_true(chrome):
    out = run(flow(chrome, "steps_home.html", [{"check": "單選A", "value": False}], {"expect_text": ["x"]}))
    assert out["status"] == "needs_help" and out["why"] == "radio_false", out
    out = run(flow(chrome, "steps_home.html", [{"check": "單選A", "value": True}], {"expect_text": ["單選A"]}))
    assert out["status"] == "done" and out["steps"][-1]["read_back"] is True, out


# ---------- then transitions ----------

def test_then_already_true(chrome, load):
    clear_counts(load)
    out = run(flow(chrome, "steps_dyn.html?mode=already", [click("查詢", {"text": "查詢完成"})]))
    assert out["status"] == "needs_help" and out["reason"] == "then_already_true", out
    assert out["step_index"] == 0 and "點擊前" in out["hint"]
    assert counts(load) == {}  # nothing was clicked


def test_old_page_taken_for_new_is_not_a_transition(chrome, monkeypatch):
    """The click does nothing and the old table is still there: rows-then must not accept the old table."""
    monkeypatch.setattr(steps, "THEN_CAP_S", 3.0)
    out = run(flow(chrome, "steps_dyn.html?mode=stale", [click("查詢", {"rows": True})]))
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["why"] == "then_not_met", out
    assert not out.get("rows")  # the page has rows; a failed step does not report them as a result


def test_existing_table_is_not_already_true_and_a_changed_table_is(chrome):
    out = run(flow(chrome, "steps_dyn.html?mode=changes", [click("查詢", {"rows": True})]))
    assert out["status"] == "done", out
    assert out["rows"] == [["B1", "10:00"], ["B2", "11:00"], ["B3", "12:00"]]  # the new table, not the old A rows


def test_delayed_result_within_cap_holds(chrome):
    out = run(flow(chrome, "steps_dyn.html?mode=delay&ms=1500", [click("查詢", {"text": "查詢完成"})]))
    assert out["status"] == "done", out
    ms = next(s["then_ms"] for s in out["steps"] if s.get("click") == "查詢")
    assert 1200 <= ms < 4000, ms


def test_delayed_result_beyond_cap_is_needs_help(chrome):
    out = run(flow(chrome, "steps_dyn.html?mode=delay&ms=12500", [click("查詢", {"text": "查詢完成"})]))
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["why"] == "then_not_met", out
    assert "10" in out["hint"] and out["step_index"] == 0


def test_ambiguous_button_stops(chrome, load):
    clear_counts(load)
    out = run(flow(chrome, "steps_dyn.html?mode=ambiguous", [click("查詢", {"text": "查詢完成"})]))
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["why"] == "ambiguous", out
    assert counts(load) == {}


def test_optional_does_not_skip_ambiguity(chrome, load):
    clear_counts(load)
    out = run(flow(chrome, "optional_buttons.html", [click("同意", {"gone": "同意"}, optional=True)], {"expect_text": ["x"]}))
    assert out["status"] == "needs_help" and out["why"] == "ambiguous", out


def test_gone_that_becomes_ambiguous_is_not_gone(chrome):
    """The target is unique before the click; if the click leaves two of it, that is not 'gone'."""
    out = run(flow(chrome, "steps_dyn.html?mode=dup", [click("查詢", {"gone": "查詢"})]))
    assert out["status"] == "needs_help" and out["why"] == "then_not_met", out


# ---------- safety: gate, stateful, never re-run ----------

CART = "steps_cart.html"


def cart_flow(chrome, *extra, stateful=True):
    return flow(chrome, CART, [click("加入購物車", {"text": "已加入購物車"}, **({"stateful": True} if stateful else {})), *extra],
                {"expect_text": ["已加入購物車"]})


def test_unmarked_stateful_click_is_refused_with_zero_events(chrome, load):
    for allow in (False, True):  # the flag alone never stands in for the mark
        clear_counts(load)
        out = run(cart_flow(chrome, stateful=False), allow_stateful=allow)
        assert out["status"] == "needs_help" and out["reason"] == "stateful_not_authorized", out
        assert out["action"] == "click" and out["target"] == "加入購物車" and out["step_index"] == 0
        assert counts(load) == {}


def test_marked_but_not_authorized_is_refused_with_zero_events(chrome, load):
    clear_counts(load)
    out = run(cart_flow(chrome))  # allow_stateful defaults to False
    assert out["status"] == "needs_help" and out["reason"] == "stateful_not_authorized", out
    assert "allow_stateful" in out["hint"]
    assert counts(load) == {}


def test_marked_and_authorized_runs_exactly_once(chrome, load):
    clear_counts(load)
    out = run(cart_flow(chrome), allow_stateful=True)
    assert out["status"] == "done", out
    assert counts(load).get("click") == 1, counts(load)
    # I7: the authorization was for that call only
    clear_counts(load)
    again = run(cart_flow(chrome))
    assert again["reason"] == "stateful_not_authorized" and counts(load) == {}


def test_failure_after_a_stateful_click_does_not_rerun_it(chrome, load):
    clear_counts(load)
    out = run(cart_flow(chrome, click("不存在的按鈕", {"text": "x"})), allow_stateful=True)
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["step_index"] == 1, out
    assert out["why"] == "not_found"
    assert counts(load).get("click") == 1, counts(load)  # the state change happened once and is not repeated
    assert out["evidence"]["screenshot"] and out["step"]["click"] == "不存在的按鈕"


def test_sensitive_field_fill_is_refused_with_zero_events(chrome, load):
    clear_counts(load)
    out = run(flow(chrome, "gate_password_field.html", [{"fill": "密碼", "value": "x"}], {"expect_text": ["zzz"]}), allow_stateful=True)
    assert out["status"] == "needs_help" and out["reason"] == "unsafe_action" and "敏感欄位" in out["hint"], out
    assert out["action"] == "fill" and counts(load) == {}


def test_preflight_refuses_before_earlier_steps_touch_the_page(chrome, load):
    """The password fill is the third step: the earlier fill on the same page must not run either."""
    clear_counts(load)
    r = flow(chrome, "gate_password_field.html", [
        {"click": "查詢", "then": {"text": "zzz"}},
        {"fill": "密碼", "value": "x"}], {"expect_text": ["zzz"]})
    out = run(r)
    assert out["reason"] == "unsafe_action" and out["step_index"] == 1, out
    assert counts(load) == {}


def test_forbidden_word_click_is_refused(chrome, load):
    load("gate_pre_login.html")
    clear_counts(load)
    out = run(flow(chrome, "gate_pre_login.html", [click("登入", {"text": "x"}, optional=True)], {"expect_text": ["x"]}))
    assert out["reason"] == "unsafe_action" and "登入" in out["hint"] and counts(load) == {}


# ---------- failed step is never rescued by the final page ----------

def test_failed_step_with_results_on_the_final_page_is_not_done(chrome):
    out = run(flow(chrome, "steps_dyn.html?mode=changes", [click("不存在的按鈕", {"text": "x"})]))
    assert out["status"] == "needs_help" and out["reason"] == "step_failed" and out["step_index"] == 0, out
    assert out["step"] == {"click": "不存在的按鈕", "then": {"text": "x"}}
    assert out.get("rows") in (None, [])  # the table on the page was not collected as a result


def test_result_must_be_proven_after_all_steps_pass(chrome):
    out = run(flow(chrome, "steps_dyn.html?mode=changes", [click("查詢", {"text": "查詢完成"})], {"expect_text": ["不會出現的字"]}))
    assert out["status"] == "needs_help" and out["reason"] == "result_not_proven", out
    assert out["expect_text_missing"] == ["不會出現的字"]


def test_two_matching_tables_is_result_ambiguous(chrome):
    out = run(flow(chrome, "result_form.html", [click("查詢", {"rows": True})], {"rows": {"pattern": r"\d{2}:\d{2}", "min_rows": 3}}))
    assert out["status"] == "needs_help" and out["reason"] == "result_ambiguous", out


def test_dry_run_records_a_passing_steps_run(chrome):
    r = flow(chrome, "steps_dyn.html?mode=changes", [click("查詢", {"rows": True})])
    d = recipes.dry_run(r, {})
    assert d["passed"] is True and d["result"]["status"] == "done"
    r2 = flow(chrome, "steps_dyn.html?mode=changes", [click("不存在的按鈕", {"text": "x"})])
    assert recipes.dry_run(r2, {})["passed"] is False
