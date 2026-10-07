"""WP0b unit tests (no Chrome): _find_control results, optional semantics, columns, result_ambiguous logic."""

import json
from pathlib import Path

import pytest

from kfw import form, recipes


def thsr():
    return json.load(open(recipes.BUILTIN / "thsr-timetable.json", encoding="utf-8"))


def C(label, kind="button", **kw):
    return {"id": "k" + label, "label": label, "kind": kind, **kw}


# ---------- 5.1 _find_control ----------

def test_find_control_three_outcomes():
    ctrls = [C("送出"), C("同意"), C("同意"), C("同意條款"), C("搜尋"), C("搜尋紀錄"), C("姓名", "text")]
    c, problem = recipes._find_control(ctrls, "送出", ("button",))
    assert c and c["label"] == "送出" and problem is None
    c, problem = recipes._find_control(ctrls, "找不到", ("button",))
    assert c is None and problem == {"why": "not_found", "candidates": 0}
    c, problem = recipes._find_control(ctrls, "同意", ("button",))  # two exact
    assert c is None and problem == {"why": "ambiguous", "candidates": 2}
    c, problem = recipes._find_control(ctrls, "搜", ("button",))  # two by contains
    assert c is None and problem == {"why": "ambiguous", "candidates": 2}
    c, problem = recipes._find_control(ctrls, "姓名", ("button",))  # right label, wrong kind
    assert c is None and problem["why"] == "not_found"
    c, _ = recipes._find_control(ctrls, "搜尋", ("button",))  # exact beats contains
    assert c and c["label"] == "搜尋"


class FakeTab:
    """Just enough of a tab for _fill_and_submit's pre-steps and for the result stage."""

    def __init__(self, ctrls=()):
        self.ctrls = list(ctrls)
        self.clicked = []

    def navigate(self, url):
        pass

    def wait_ready(self, **kw):
        return type("R", (), {"reason": "settled", "ms": 1, "inflight": 0})()

    def evaluate(self, js):
        return "http://x/" if "location.href" in js else ""

    def screenshot(self, path):
        Path(path).write_bytes(b"")

    def close(self):
        pass


@pytest.fixture
def fake_form(monkeypatch):
    monkeypatch.setattr(recipes.time, "sleep", lambda s: None)
    state = {"ctrls": [], "clicks": []}
    monkeypatch.setattr(form, "controls", lambda tab: state["ctrls"])
    monkeypatch.setattr(form, "settle_controls", lambda tab: (state["ctrls"], {"ok": True, "ms": 0}))
    monkeypatch.setattr(form, "describe", lambda tab, cid: next(
        ({"ok": True, "tag": "INPUT" if c["kind"] == "text" else "BUTTON", "type": "", "text": c["label"], "aria_label": "",
          "label": c["label"], "autocomplete": "", "sensitive": False, "form_has_sensitive": False}
         for c in state["ctrls"] if c["id"] == cid), {"ok": False, "why": "gone"}))
    monkeypatch.setattr(form, "click", lambda tab, cid: state["clicks"].append(cid) or {"ok": True, "_href": "h", "_at": 0.0})
    monkeypatch.setattr(form, "wait_submit_effect", lambda tab, r: ("dom", 1))
    return state


def _recipe(pre):
    return {"url": "http://x/", "pre": pre, "fields": [], "submit": {"click": "查詢"}}


def test_optional_pre_skips_only_not_found(fake_form):
    fake_form["ctrls"] = [C("查詢")]
    steps = []
    assert recipes._fill_and_submit(FakeTab(), _recipe([{"click": "關閉", "optional": True}]), None, steps) is None
    assert any(s.get("pre") == "關閉" and "skipped" in s for s in steps)
    assert fake_form["clicks"] == ["k查詢"]  # only the submit was clicked


def test_optional_pre_ambiguous_is_needs_help_not_skipped(fake_form):
    fake_form["ctrls"] = [C("查詢"), C("同意"), C("同意")]
    steps = []
    out = recipes._fill_and_submit(FakeTab(), _recipe([{"click": "同意", "optional": True}]), None, steps)
    assert out["status"] == "needs_help" and out["reason"] == "pre_step_failed" and out["why"] == "ambiguous"
    assert "2 candidates" in out["hint"] and "同意" in out["hint"]
    assert fake_form["clicks"] == []  # nothing was guessed and clicked


def test_required_pre_not_found_and_ambiguous_both_stop(fake_form):
    fake_form["ctrls"] = [C("查詢"), C("同意"), C("同意")]
    out = recipes._fill_and_submit(FakeTab(), _recipe([{"click": "關閉"}]), None, [])
    assert out["reason"] == "pre_step_failed" and out["why"] == "not_found"
    out = recipes._fill_and_submit(FakeTab(), _recipe([{"click": "同意"}]), None, [])
    assert out["reason"] == "pre_step_failed" and out["why"] == "ambiguous"


def test_field_and_submit_problems_carry_why(fake_form):
    fake_form["ctrls"] = [C("姓名", "text"), C("姓名", "text"), C("查詢")]
    r = {**_recipe([]), "fields": [{"label": "姓名", "kind": "text", "value": "x"}]}
    out = recipes._fill_and_submit(FakeTab(), r, None, [])
    assert out["reason"] == "field_not_found" and out["why"] == "ambiguous"
    fake_form["ctrls"] = [C("查詢"), C("查詢")]
    out = recipes._fill_and_submit(FakeTab(), _recipe([]), None, [])
    assert out["reason"] == "submit_not_found" and out["why"] == "ambiguous"


# ---------- 5.3 columns ----------

def test_duplicate_column_names_are_refused():
    r = thsr()
    r["result"]["rows"]["columns"] = ["出發", "抵達", "出發", None, None, None]
    with pytest.raises(recipes.RecipeError, match="duplicate"):
        recipes.validate(r)
    r["result"]["rows"]["columns"] = ["出發", None, None, "抵達", None, None]  # repeated nulls are fine
    recipes.validate(r)
    d = {"name": "dup-test", "type": "detail_extract", "description": "x", "url": "https://x",
         "rows": {"pattern": "a", "columns": ["a", "a"]}}
    with pytest.raises(recipes.RecipeError, match="duplicate"):
        recipes.validate(d)


# ---------- 5.2 result_ambiguous ----------

def test_ambiguity_judgement():
    assert recipes._ambiguity({"rows": [["a"]], "group_fingerprint": "x", "other_qualifying_groups": 0}) is None
    a = recipes._ambiguity({"rows": [["a"]], "group_fingerprint": "x", "other_qualifying_groups": 2})
    assert a["reason"] == "result_ambiguous" and "3 張表" in a["hint"]


def _form_recipe():
    return {"name": "amb-test", "type": "form_submit", "description": "x", "url": "http://x/", "fields": [],
            "submit": {"click": "查詢"}, "result": {"rows": {"pattern": r"\d", "min_rows": 2}}}


def _patch_engine(monkeypatch, detail):
    tab = FakeTab()
    monkeypatch.setattr(recipes.ObservedTab, "open", classmethod(lambda cls, b: tab))
    monkeypatch.setattr(recipes, "_fill_and_submit", lambda t, r, j, steps, *a: steps.append({"submit": "查詢", "ok": True, "effect": "dom"}))
    monkeypatch.setattr(form, "wait_rows", lambda t, p, m: ([["a", "1"], ["b", "2"]], 5))
    monkeypatch.setattr(form, "rows_detail", lambda t, p, m: detail)


def test_form_submit_result_ambiguous_is_needs_help(monkeypatch, tmp_path):
    _patch_engine(monkeypatch, {"rows": [["a", "1"], ["b", "2"]], "group_fingerprint": "f", "other_qualifying_groups": 1})
    out = recipes.run_form_submit(_form_recipe(), {}, None, None, tmp_path)
    assert out["status"] == "needs_help" and out["reason"] == "result_ambiguous"
    assert "2 張表" in out["hint"]
    assert (tmp_path / "result.jpg").exists()  # the screenshot is still evidence


def test_form_submit_single_group_is_done(monkeypatch, tmp_path):
    _patch_engine(monkeypatch, {"rows": [["a", "1"], ["b", "2"]], "group_fingerprint": "f", "other_qualifying_groups": 0})
    out = recipes.run_form_submit(_form_recipe(), {}, None, None, tmp_path)
    assert out["status"] == "done" and out["rows"] == [["a", "1"], ["b", "2"]] and out["rows_skipped"] == 0 and "note" not in out


def test_rows_the_pattern_skipped_are_reported_even_when_the_run_is_done(monkeypatch, tmp_path):
    """591: a pattern written from a few cards missed 4 of 30 (decimal 坪, B1, 頂樓加蓋) and nothing said so. The count
    is always returned; a done run carries a note, a failed one gets it in the hint."""
    _patch_engine(monkeypatch, {"rows": [["a", "1"], ["b", "2"]], "group_fingerprint": "f", "other_qualifying_groups": 0, "rows_skipped": 4})
    out = recipes.run_form_submit(_form_recipe(), {}, None, None, tmp_path)
    assert out["status"] == "done" and out["rows_skipped"] == 4 and "4 列不符 rows.pattern" in out["note"]
    assert recipes.skipped_note(0) is None


def test_detail_extract_result_ambiguous(monkeypatch, tmp_path):
    tab = FakeTab()
    monkeypatch.setattr(recipes.ObservedTab, "open", classmethod(lambda cls, b: tab))
    monkeypatch.setattr(recipes, "read_product", lambda t: ({}, 1))
    d = {"name": "amb-detail", "type": "detail_extract", "description": "x", "url": "http://x/", "rows": {"pattern": r"\d"}}
    monkeypatch.setattr(form, "rows_detail", lambda t, p, m: {"rows": [["a", "1"]], "group_fingerprint": "f", "other_qualifying_groups": 1})
    out = recipes.run_detail_extract(d, {}, None, tmp_path)
    assert out["status"] == "needs_help" and out["reason"] == "result_ambiguous"
    monkeypatch.setattr(form, "rows_detail", lambda t, p, m: {"rows": [["a", "1"]], "group_fingerprint": "f", "other_qualifying_groups": 0})
    out = recipes.run_detail_extract(d, {}, None, tmp_path)
    assert out["status"] == "done" and out["rows"] == [["a", "1"]]


def test_observe_js_is_shared_by_all_entry_points():
    for js in (form.CONTROLS_JS, form.ROWS_JS, form.ROWS_DETAIL_JS, form.GROUPS_JS):
        assert form.OBSERVE_JS in js
