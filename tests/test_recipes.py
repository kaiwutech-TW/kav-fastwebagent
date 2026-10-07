import json
import re

import pytest

from kfw import recipes


def thsr():
    return json.load(open(recipes.BUILTIN / "thsr-timetable.json", encoding="utf-8"))


def test_builtin_recipes_are_valid_and_verified():
    for p in recipes.BUILTIN.glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        recipes.validate(r)
        assert r["status"] == "verified" and r["verified_runs"], p.name


def test_param_patterns_reject_bad_formats():
    r = thsr()
    recipes.check_params(r, {"from": "台北", "to": "左營", "date": "2026/10/05", "time": "08:00"})
    with pytest.raises(recipes.RecipeError, match="date"):
        recipes.check_params(r, {"from": "台北", "to": "左營", "date": "2026/10/5", "time": "08:00"})
    with pytest.raises(recipes.RecipeError, match="from"):
        recipes.check_params(r, {"from": "臺北車站", "to": "左營", "date": "2026/10/05", "time": "08:00"})
    with pytest.raises(recipes.RecipeError, match="missing"):
        recipes.check_params(r, {"from": "台北"})


def test_render_fills_nested_templates():
    out = recipes.render_recipe({"a": "{x}-{y}", "b": [{"c": "{x}"}], "n": 3}, {"x": "台北", "y": 1})
    assert out == {"a": "台北-1", "b": [{"c": "台北"}], "n": 3}


def test_today_is_filled_by_code_in_taiwan_time(monkeypatch):
    monkeypatch.setattr(recipes, "today", lambda: "2026/09/29")
    out = recipes.render_recipe({"expect_text": ["{today}"], "a": "{x}"}, {"x": 1})
    assert out == {"expect_text": ["2026/09/29"], "a": "1"}
    assert recipes.render_recipe({"a": "{today}"}, {"today": "2026/01/02"}) == {"a": "2026/01/02"}
    assert re.fullmatch(r"\d{4}/\d{2}/\d{2}", recipes.today())


def test_completion_must_be_checkable():
    r = thsr()
    r["result"] = {}
    with pytest.raises(recipes.RecipeError, match="completion"):
        recipes.validate(r)


def test_find_by_natural_request_and_url():
    assert recipes.find("高鐵 新竹到台南 下午兩點 時刻")[0]["name"] == "thsr-timetable"
    assert recipes.find("https://www.thsrc.com.tw/")[0]["name"] == "thsr-timetable"
    assert recipes.find("幫我比價 AirPods Pro 3 哪裡最便宜")[0]["name"] == "tw-shop-compare"
    assert recipes.find("今天天氣如何") == []


def test_save_requires_passing_dry_run_of_same_recipe(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes, "DRYRUNS", tmp_path / "dry")
    monkeypatch.setattr(recipes, "USER", tmp_path / "user")
    r = thsr()
    (tmp_path / "dry").mkdir()

    def record(run_id, passed, h):
        (tmp_path / "dry" / f"{run_id}.json").write_text(json.dumps(
            {"run_id": run_id, "at": "t", "recipe_hash": h, "params": {}, "passed": passed, "result": {"status": "x"}}))

    with pytest.raises(recipes.RecipeError, match="unknown"):
        recipes.save(r, "nope")
    record("failed", False, recipes.recipe_hash(r))
    with pytest.raises(recipes.RecipeError, match="did not pass"):
        recipes.save(r, "failed")
    record("other", True, "0" * 16)
    with pytest.raises(recipes.RecipeError, match="differs"):
        recipes.save(r, "other")
    record("good", True, recipes.recipe_hash(r))
    assert recipes.save(r, "good").endswith("thsr-timetable.json")


def _passing_dry_run(tmp_path, r, run_id, at):
    (tmp_path / "dry").mkdir(exist_ok=True)
    (tmp_path / "dry" / f"{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "at": at, "recipe_hash": recipes.recipe_hash(r), "params": {}, "passed": True, "result": {"status": "done"}}))


def test_resave_keeps_verified_history(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes, "DRYRUNS", tmp_path / "dry")
    monkeypatch.setattr(recipes, "USER", tmp_path / "user")
    r = {k: v for k, v in thsr().items() if k != "verified_runs"}  # how a repairing caller passes it
    _passing_dry_run(tmp_path, r, "a", "t1")
    recipes.save(r, "a")
    _passing_dry_run(tmp_path, r, "b", "t2")
    saved = json.loads(open(recipes.save(r, "b"), encoding="utf-8").read())
    assert [x["at"] for x in saved["verified_runs"]] == ["t1", "t2"]


def test_summary_and_delete_user_recipe(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes, "DRYRUNS", tmp_path / "dry")
    monkeypatch.setattr(recipes, "USER", tmp_path / "user")
    monkeypatch.setattr(recipes, "HOME", tmp_path)
    r = {**thsr(), "name": "my-thsr"}
    r.pop("verified_runs")
    _passing_dry_run(tmp_path, r, "a", "t1")
    recipes.save(r, "a")
    s = recipes.summary()
    assert s["my-thsr"]["source"] == "user" and s["my-thsr"]["last_verified"] == "t1"
    assert s["my-thsr"]["example_params"]["from"] == "台北"
    assert s["thsr-timetable"]["source"] == "builtin"
    with pytest.raises(recipes.RecipeError, match="built in"):
        recipes.delete("thsr-timetable")
    with pytest.raises(recipes.RecipeError, match="no recipe"):
        recipes.delete("nope")
    out = recipes.delete("my-thsr")
    assert out["builtin_remains"] is False and (tmp_path / "trash").exists()
    assert "my-thsr" not in recipes.summary()


def test_unknown_fields_are_refused_not_skipped():
    r = thsr()
    r["result"]["must_be_today"] = True  # a check this engine does not have
    with pytest.raises(recipes.RecipeError, match="restart Claude Code"):
        recipes.validate(r)
    r = thsr()
    r["fields"][0]["optinal"] = True  # typo
    with pytest.raises(recipes.RecipeError, match=r"fields\[0\]"):
        recipes.validate(r)
    r = thsr()
    r["freshness"] = "{today}"
    with pytest.raises(recipes.RecipeError, match="freshness"):
        recipes.validate(r)
    d = {"name": "fx-test", "type": "detail_extract", "description": "x", "url": "https://x", "rows": {"pattern": "a", "min_row": 1}}
    with pytest.raises(recipes.RecipeError, match="rows"):
        recipes.validate(d)


def test_columns_label_cells_and_refuse_mismatched_rows():
    rows = [["15:00", "00:59", "15:59", "0648", "10-12", "台中 15:00 台北 16:02"], ["15:08", "00:46"]]
    out, bad = recipes.label_rows(rows, ["出發", "行車時間", "抵達", "車次", None, "停靠站發車時間"])
    assert out == [{"出發": "15:00", "行車時間": "00:59", "抵達": "15:59", "車次": "0648", "停靠站發車時間": "台中 15:00 台北 16:02"}]
    assert bad == 1  # never labelled by guess
    assert recipes.label_rows(rows, None) == (rows, 0)
    r = thsr()
    r["result"]["rows"]["columns"] = "出發,抵達"
    with pytest.raises(recipes.RecipeError, match="columns"):
        recipes.validate(r)
    r["result"]["rows"]["columns"] = [None, None]
    with pytest.raises(recipes.RecipeError, match="columns"):
        recipes.validate(r)
