"""WP5 units: the `pick` schema, Judge.choice_dist (request / response handling on fake HTTP), the acceptance rule."""

import json

import httpx
import pytest

from kfw import recipes
from kfw.judge import Judge
from kfw.steps import decide_pick

GOOD = {"rows": {"pattern": r"NT\$"}, "want": "{title}", "click": "查看"}


def flow(pick, extra=None):
    return {"name": "pick-fixture", "type": "steps", "description": "fixture", "url": "http://x.test/",
            "params": {"title": {"description": "t", "example": "x"}},
            "steps": [*(extra or []), {"pick": pick}], "result": {"expect_text": ["詳情"]}}


def test_valid():
    recipes.validate(flow(GOOD))
    recipes.validate(flow({**GOOD, "rows": {"pattern": "x", "min_rows": 3}}))
    recipes.validate(flow(GOOD, extra=[{"click": "查詢", "then": {"text": "x"}}]))


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p.pop("rows"), "rows"),
    (lambda p: p.update(rows={}), "pattern"),
    (lambda p: p.update(rows={"pattern": ""}), "pattern"),
    (lambda p: p.update(rows="NT"), "rows"),
    (lambda p: p.update(rows={"pattern": "x", "min_rows": 0}), "min_rows"),
    (lambda p: p.update(rows={"pattern": "x", "min_rows": True}), "min_rows"),
    (lambda p: p.update(rows={"pattern": "x", "columns": ["a"]}), "unsupported"),
    (lambda p: p.pop("want"), "want"),
    (lambda p: p.update(want="  "), "want"),
    (lambda p: p.update(want=3), "want"),
    (lambda p: p.pop("click"), "click"),
    (lambda p: p.update(click=""), "click"),
    (lambda p: p.update(stateful=True), "stateful"),
    (lambda p: p.update(then={"text": "x"}), "unsupported"),
    (lambda p: p.update(fallback="first"), "unsupported"),
])
def test_bad_pick_object(mutate, match):
    p = json.loads(json.dumps(GOOD))
    mutate(p)
    with pytest.raises(recipes.RecipeError, match=match):
        recipes.validate(flow(p))


def test_pick_is_not_a_string_and_not_stateful_at_step_level():
    with pytest.raises(recipes.RecipeError, match="object"):
        recipes.validate(flow("查看"))
    r = flow(GOOD)
    r["steps"][0]["stateful"] = True
    with pytest.raises(recipes.RecipeError, match="stateful|unsupported"):
        recipes.validate(r)
    r = flow(GOOD)
    r["steps"][0]["then"] = {"text": "x"}
    with pytest.raises(recipes.RecipeError, match="unsupported"):
        recipes.validate(r)


def test_want_takes_a_param():
    r = recipes.render_recipe(flow(GOOD), {"title": "進階課程"})
    assert r["steps"][0]["pick"]["want"] == "進階課程"


# ---------- Judge.choice_dist ----------

def judge_with(handler):
    j = Judge("http://kev.test")
    j.client = httpx.Client(transport=httpx.MockTransport(handler))
    return j


def kev_reply(probs):
    return {"model": "kev-latest", "answers": {"q": {"type": "choice", "choice": max(probs, key=probs.get), "confidence": 0.5,
                                                     "probabilities": probs}},
            "usage": {"input_tokens": 50, "output_tokens": 60}, "latency_ms": 100.0}


def test_choice_dist_request_and_full_distribution():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=kev_reply({"c1": 0.1, "c2": 0.7, "c3": 0.05, "none": 0.15}))
    j = judge_with(handler)
    probs = j.choice_dist("哪一個?", {"c1": "甲", "c2": "乙", "c3": "乙"}, state={"要找的": "乙"})
    assert probs == {"c1": 0.1, "c2": 0.7, "c3": 0.05, "none": 0.15}
    crit = seen[0]["questions"]["q"]["criteria"]
    assert list(crit) == ["c1", "c2", "c3", "none"] and crit["c2"] == crit["c3"] == "乙"  # same text, two ids: not merged
    assert seen[0]["questions"]["q"]["type"] == "choice" and seen[0]["state"] == {"要找的": "乙"}
    u = j.usage()
    assert u["calls"] == 1 and u["input_tokens"] == 50 and u["output_tokens"] == 60  # usage still accumulated


def test_choice_dist_refuses_incomplete_or_malformed_answers():
    with pytest.raises(ValueError, match="cover exactly"):
        judge_with(lambda r: httpx.Response(200, json=kev_reply({"c1": 0.9, "none": 0.1}))).choice_dist("?", {"c1": "a", "c2": "b"})
    with pytest.raises(ValueError, match="cover exactly"):
        judge_with(lambda r: httpx.Response(200, json=kev_reply({"c1": 0.5, "c2": 0.4, "none": 0.1, "zzz": 0}))).choice_dist("?", {"c1": "a", "c2": "b"})
    with pytest.raises(ValueError, match="cover exactly"):
        judge_with(lambda r: httpx.Response(200, json={"answers": {}})).choice_dist("?", {"c1": "a"})
    with pytest.raises(ValueError, match="reserved"):
        judge_with(lambda r: httpx.Response(200, json={})).choice_dist("?", {"none": "a"})
    with pytest.raises(httpx.HTTPStatusError):
        judge_with(lambda r: httpx.Response(500)).choice_dist("?", {"c1": "a"})


def test_old_choice_is_unchanged():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"answers": {"q": {"choice": "台北", "probabilities": {"台北": 0.9, "台中": 0.1}}}})
    a = judge_with(handler).choice("哪個?", ["台北", "台中"], state={"x": 1})
    assert a == {"choice": "台北", "p": 0.9}
    assert seen[0]["questions"]["q"]["criteria"] == {"台北": None, "台中": None}


# ---------- the acceptance rule ----------

@pytest.mark.parametrize("probs,chosen,why", [
    ({"c1": 0.79, "c2": 0.10, "none": 0.11}, None, "low_confidence"),      # p just under 0.8
    ({"c1": 0.80, "c2": 0.10, "none": 0.10}, "c1", None),                  # p = 0.8, gap 0.7
    ({"c1": 0.80, "c2": 0.50, "none": 0.0}, "c1", None),                   # gap exactly 0.3
    ({"c1": 0.80, "c2": 0.51, "none": 0.0}, None, "small_gap"),            # gap 0.29
    ({"c1": 0.85, "c2": 0.20, "none": 0.0}, "c1", None),                   # gap 0.65
    ({"c1": 0.85, "c2": 0.0, "none": 0.56}, None, "small_gap"),            # the runner-up may be none
    ({"c1": 0.05, "c2": 0.05, "none": 0.90}, None, "none_highest"),        # none is highest
    ({"c1": 0.10, "c2": 0.10, "none": 0.80}, None, "none_highest"),
    ({"c1": 0.45, "c2": 0.45, "none": 0.10}, None, "low_confidence"),
    ({"c1": 0.10, "c2": 0.85, "c3": 0.0, "none": 0.05}, "c2", None),
])
def test_decide_pick(probs, chosen, why):
    assert decide_pick(probs) == (chosen, why)


# ---------- Judge.row_match (per-row yes/no) ----------

def test_row_match_one_noul_per_row_and_none_is_complement():
    seen = {}

    def reply(req):
        body = json.loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={"answers": {"c1": {"noul": 0.963}, "c2": {"noul": 0.612}, "c3": {"noul": 0.045}}})

    probs = judge_with(reply).row_match("想把錢退回來", {"c1": "退費申請表", "c2": "機票訂位", "c3": "請假單"})
    assert set(seen["questions"]) == {"c1", "c2", "c3"}
    assert all(q["type"] == "noul" for q in seen["questions"].values())
    assert probs["c1"] == 0.963 and abs(probs["none"] - 0.037) < 1e-9
    assert decide_pick(probs) == ("c1", None)  # 0.963 >= 0.8 and leads 0.612 by 0.351


def test_row_match_nothing_fits_is_none_highest():
    probs = judge_with(lambda r: httpx.Response(200, json={"answers": {"c1": {"noul": 0.007}, "c2": {"noul": 0.005}}})
                       ).row_match("想吃牛肉麵", {"c1": "機票訂位", "c2": "請假單"})
    assert decide_pick(probs) == (None, "none_highest")


def test_row_match_refuses_missing_rows():
    with pytest.raises(ValueError):
        judge_with(lambda r: httpx.Response(200, json={"answers": {"c1": {"noul": 0.9}}})).row_match("?", {"c1": "a", "c2": "b"})
    with pytest.raises(ValueError):
        judge_with(lambda r: httpx.Response(200, json={})).row_match("?", {"none": "a"})
