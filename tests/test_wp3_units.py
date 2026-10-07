"""WP3 units: the `steps` schema (recursive, exactly-one-operation, deep unknown keys) and dry_run's pass rule."""

import copy
import json

import pytest

from kfw import recipes, steps

RESULT = {"rows": {"pattern": r"\d{2}:\d{2}", "min_rows": 1}, "expect_text": ["{date}"]}


def good():
    return {"name": "steps-fixture", "type": "steps", "description": "fixture", "url": "http://x.test/",
            "params": {"date": {"description": "d", "example": "2026/10/12"}},
            "steps": [
                {"click": "不同意", "optional": True, "then": {"gone": "不同意"}},
                {"select": "出發站", "value": "{from}"},
                {"fill": "出發日期", "value": "{date}"},
                {"check": "只看直達車", "value": True},
                {"click": "查詢", "then": {"text": "查詢完成"}},
                {"click": "下一頁", "then": {"url_contains": "results"}},
                {"click": "篩選", "then": {"field": "價格"}},
                {"click": "重新整理", "then": {"rows": True}},
                {"wait": {"text": "結果已載入"}},
                {"click": "加入追蹤", "stateful": True, "then": {"text": "已加入"}},
            ],
            "result": copy.deepcopy(RESULT)}


def bad(mutate, match):
    r = good()
    mutate(r)
    with pytest.raises(recipes.RecipeError, match=match):
        recipes.validate(r)


def test_good_recipe_validates():
    recipes.validate(good())
    r = good()
    r["steps"] = [{"wait": {"text": "x"}}]
    r["result"] = {"expect_text": ["x"]}
    recipes.validate(r)  # expect_text alone is a valid completion proof
    assert "steps" in recipes.TYPES


def test_next_page_and_pick_keep_their_names():
    r = good()
    r["steps"].append({"next_page": {"click": "下一頁", "max_pages": 2, "end": "disabled"}})
    recipes.validate(r)  # next_page validates (WP4); pick is still reserved


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r["steps"].__setitem__(0, {"click": "a", "fill": "b", "then": {"text": "x"}}), r"steps\[0\].*exactly one operation"),
    (lambda r: r["steps"].__setitem__(0, {"value": "x"}), r"exactly one operation"),
    (lambda r: r.__setitem__("steps", []), "non-empty"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢"}), r"steps\[4\].*'then'"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {}}), r"steps\[4\].*'then'"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"text": "a", "gone": "b"}}), r"'then'"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"text": ""}}), r"then.text.*non-empty"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"text": "   "}}), r"then.text.*non-empty"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"gone": ""}}), r"then.gone.*non-empty"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"rows": "yes"}}), r"then.rows must be true"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"texts": "x"}}), r"steps\[4\].then.*unsupported"),
    (lambda r: r["steps"].__setitem__(3, {"check": "只看直達車", "value": "{flag}"}), r"JSON boolean"),
    (lambda r: r["steps"].__setitem__(3, {"check": "只看直達車", "value": "true"}), r"JSON boolean"),
    (lambda r: r["steps"].__setitem__(3, {"check": "只看直達車"}), r"JSON boolean"),
    (lambda r: r["steps"].__setitem__(3, {"check": "只看直達車", "value": True, "optional": True}), r"steps\[3\].*unsupported.*optional"),
    (lambda r: r["steps"].__setitem__(2, {"fill": "出發日期", "value": "x", "stateful": True}), r"steps\[2\].*unsupported.*stateful"),
    (lambda r: r["steps"].__setitem__(1, {"select": "出發站", "value": "x", "optional": True}), r"steps\[1\].*unsupported.*optional"),
    (lambda r: r["steps"].__setitem__(1, {"select": "出發站"}), r"needs a string value"),
    (lambda r: r["steps"].__setitem__(8, {"wait": {"text": ""}}), r"wait is"),
    (lambda r: r["steps"].__setitem__(8, {"wait": {"text": "x", "ms": 5}}), r"wait is"),
    (lambda r: r["steps"].__setitem__(8, {"wait": "結果已載入"}), r"wait is"),
    (lambda r: r["steps"].__setitem__(8, {"wait": {"text": "x"}, "then": {"text": "y"}}), r"steps\[8\].*unsupported.*then"),
    (lambda r: r["steps"].__setitem__(0, {"click": "a", "optinal": True, "then": {"text": "x"}}), r"steps\[0\].*optinal.*restart Claude Code"),
    (lambda r: r["steps"].__setitem__(4, {"click": "查詢", "then": {"text": "x", "deep": {"a": 1}}}), r"then"),
    (lambda r: r["steps"].__setitem__(4, {"click": "", "then": {"text": "x"}}), r"label"),
    (lambda r: r.pop("result"), "result needs"),
    (lambda r: r.__setitem__("result", {}), "result needs"),
    (lambda r: r.__setitem__("result", {"expect_text": []}), "result needs"),
    (lambda r: r.__setitem__("result", {"rows": {"pattern": "x", "min_rw": 1}}), r"result.rows.*min_rw"),
    (lambda r: r.__setitem__("result", {"expect_text": ["x"], "freshness": 1}), r"result.*freshness"),
    (lambda r: r.__setitem__("result", {"expect_text": ["x"], "rows": {"pattern": ""}}), r"pattern"),
    (lambda r: r.__setitem__("pre", []), r"recipe.*pre"),
    (lambda r: r.pop("url"), r"url"),
])
def test_invalid_shapes(mutate, match):
    bad(mutate, match)


def test_then_rows_needs_a_rows_pattern_to_name_the_table():
    r = good()
    r["result"] = {"expect_text": ["x"]}  # the rows-then in the flow has no table to point at
    with pytest.raises(recipes.RecipeError, match=r"then.rows needs result.rows.pattern"):
        recipes.validate(r)


def test_form_submit_checks_are_untouched():
    r = json.load(open(recipes.BUILTIN / "thsr-timetable.json", encoding="utf-8"))
    recipes.validate(r)
    r["fields"][0]["optinal"] = True
    with pytest.raises(recipes.RecipeError, match=r"fields\[0\]"):
        recipes.validate(r)


def test_op_of_finds_the_single_operation():
    assert steps.op_of({"click": "x", "then": {"text": "y"}}) == "click"
    assert steps.op_of({"wait": {"text": "y"}}) == "wait"


def test_option_choice_is_exact_then_contains_and_never_guesses():
    opts = ["請選擇", "台北", "台中", "台南", "", "南港"]
    assert steps._pick_option(opts, "台中") == ("台中", "exact")
    assert steps._pick_option(opts, "台北車站") == ("台北", "contains")
    assert steps._pick_option(opts, "高雄") == (None, "not_found")
    assert steps._pick_option(["台北 1", "台北 2"], "台北") == (None, "ambiguous")
    assert steps._pick_option(["A", "A"], "A") == (None, "ambiguous")


def _fake_execute(monkeypatch, result, tmp_path):
    monkeypatch.setattr(recipes, "DRYRUNS", tmp_path)
    monkeypatch.setattr(recipes, "execute", lambda recipe, params, allow_stateful=False: result)


@pytest.mark.parametrize("result,passed", [
    ({"status": "done", "rows": [{"a": 1}]}, True),
    ({"status": "done", "rows": []}, True),          # expect_text-only steps recipes prove themselves without rows
    ({"status": "partial", "rows": [{"a": 1}]}, False),
    ({"status": "needs_help", "reason": "step_failed", "rows": [{"a": 1}]}, False),
    ({"status": "blocked", "rows": [{"a": 1}]}, False),
])
def test_dry_run_passes_only_on_done(monkeypatch, tmp_path, result, passed):
    _fake_execute(monkeypatch, result, tmp_path)
    assert recipes.dry_run(good(), {"date": "2026/10/12"})["passed"] is passed


def test_dry_run_rule_for_other_types_is_unchanged(monkeypatch, tmp_path):
    _fake_execute(monkeypatch, {"status": "partial", "rows": [{"a": 1}]}, tmp_path)
    r = json.load(open(recipes.BUILTIN / "thsr-timetable.json", encoding="utf-8"))
    assert recipes.dry_run(r, {"from": "台北", "to": "左營", "date": "2026/10/05", "time": "08:00"})["passed"] is True
    _fake_execute(monkeypatch, {"status": "done", "rows": []}, tmp_path)
    assert recipes.dry_run(r, {"from": "台北", "to": "左營", "date": "2026/10/05", "time": "08:00"})["passed"] is False
