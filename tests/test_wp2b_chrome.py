"""WP2b Chrome integration (isolated test Chrome, KFW_CHROME_TESTS=1): a real multi-page demonstration (cookie consent -> keyword -> search ->
pick a list row -> mark the detail text) is recorded with simulated user input, converted to a `steps` draft at stop (then candidates, a
pick suggestion), parameterised, replayed in a fresh browser context, compared with what the user marked and saved. Nothing here touches
:9333 or ~/.kav-fastweb (chrome_harness points KFW_HOME / KFW_CDP at throwaway values)."""

import json

import pytest
from chrome_harness import CDP_URL
from test_wp2_chrome import as_recipe, browser_contexts, mgr, start  # noqa: F401  (fixtures)

from kfw import recipes, record
from kfw.cdp import Browser
from kfw.page import ObservedTab

pytestmark = pytest.mark.chrome

TITLE = "進階 Python 課程"


def set_consent(chrome, on):
    """The everyday profile's localStorage for the fixture origin: what a demonstrator's browser may already hold."""
    b = Browser(CDP_URL)
    tab = ObservedTab.open(b)
    try:
        tab.goto(chrome.url("rec_steps_home.html", "a.test"))
        tab.evaluate("localStorage.setItem('consent', '1')" if on else "localStorage.removeItem('consent')")
    finally:
        tab.close()
        b.close()


def demo_steps(s, kw="Python", row=2, consent=True):
    """cookie 同意 (skipped when the profile already consented) -> type the keyword -> 查詢 -> 查看 on the given list row -> mark the detail text."""
    n = 0
    if consent:
        s.sim.click("#ok")
        n += 1
        s.wait_groups(n)
    s.sim.focus_by_click("#kw")
    s.sim.insert(kw)
    n += 2
    s.wait_groups(n)
    s.sim.click("#go")
    s.wait_epoch(2)
    s.sim.click(f".row:nth-child({row}) a")
    s.wait_epoch(3)
    s.mark("#info")


def parameterised(res, name, has_consent_step=True):
    """What Claude does with the draft: fill the keyword and the pick's want from parameters, and expect the chosen title."""
    r = as_recipe(res, name, params={"kw": {"description": "關鍵字", "example": "Python"}, "title": {"description": "課程名稱", "example": TITLE}})
    i = 1 if has_consent_step else 0
    if has_consent_step:
        r["steps"][0] = {**r["steps"][0], "optional": True}      # the everyday profile already consented: the banner is simply not there
    r["steps"][i] = {**r["steps"][i], "value": "{kw}"}
    r["steps"][-1]["pick"]["want"] = "{title}"
    r["result"] = {"expect_text": ["{title}"]}
    return r


def demo_of(rid):
    rec = record.read_recording(rid)
    return {"comparator": rec["draft"]["demo"]["comparator"], "group": (rec["mark"] or {}).get("group"), "text": (rec["mark"] or {}).get("text", "")}


def test_multi_page_demo_becomes_steps_with_pick_then_dry_run_in_a_clean_context_second_params_and_save(start, chrome, mgr):
    set_consent(chrome, False)
    s = start("rec_steps_home.html")
    demo_steps(s)
    res = s.stop()
    assert res["state"] == "completed", res
    d = res["draft"]
    assert d["type"] == "steps" and d["recorded_from"] == s.id and d["url"].endswith("/rec_steps_home.html") and "unsupported" not in res
    assert [next(iter(st)) for st in d["steps"]] == ["click", "fill", "click", "pick"]
    assert d["steps"][0]["click"] == "同意" and d["steps"][1] == {"fill": "關鍵字", "value": "Python"} and d["steps"][2]["click"] == "查詢"
    pk = d["steps"][3]["pick"]
    assert pk["want"] == TITLE and pk["click"] == "查看" and pk["rows"]["pattern"]
    # then: candidates from the committed snapshots, the first one is the default, all flagged for review
    tc = {c["step_index"]: c for c in res["then_candidates"]}
    assert tc[0]["candidates"] == [{"gone": "同意"}] and d["steps"][0]["then"] == {"gone": "同意"}
    assert {"text": "搜尋結果"} in tc[2]["candidates"] and {"url_contains": "rec_steps_list.html"} in tc[2]["candidates"]
    assert d["steps"][2]["then"] == tc[2]["chosen"] == tc[2]["candidates"][0]
    assert {n["step_index"] for n in res["needs_review"] if n["what"] == "then"} == {0, 2}
    assert res["step_suggestions"][0]["kind"] == "pick" and res["step_suggestions"][0]["list_rows"] == 2
    assert [c["value"] for c in res["param_candidates"]] == ["Python", TITLE] and res["param_candidates"][1]["kind"] == "pick_want"
    assert res["demo"]["comparator"] == "text-contains-v1" and res["demo"]["kind"] == "steps"
    assert any("可關閉的橫幅" in w and "optional" in w for w in res["warnings"])
    assert len(json.dumps(res, ensure_ascii=False)) < 12000
    # the recorder wrote what the converter used: the list row of the click and the result groups before it
    opens = [r for r in record.read_log(mgr.root / s.id) if r.get("type") == "group_open" and (r.get("target") or {}).get("row")]
    assert len(opens) == 1 and opens[0]["target"]["row"]["total"] == 2 and opens[0]["target"]["row"]["cells"][0] == TITLE
    assert opens[0]["res"]["groups"] and opens[0]["res"]["heads"] == ["搜尋結果"]
    # Claude parameterises the keyword and the pick, keeps the recorded then's
    recipe = parameterised(res, "wp2b-steps-recipe")
    recipes.validate(recipe)
    before = browser_contexts()
    demo_run = recipes.dry_run(recipe, {"kw": "Python", "title": TITLE})
    assert demo_run["passed"] is True, demo_run
    assert demo_run["demo"]["demo_run"] is True and demo_run["demo"]["match"] is True and demo_run["demo"]["isolated"] is True
    assert demo_run["demo"]["comparator"] == "text-contains-v1"
    saved_rec = json.loads((recipes.DRYRUNS / f"{demo_run['dry_run_id']}.json").read_text())
    assert saved_rec["isolated"] is True and saved_rec["match"] is True and saved_rec["rendered_actions_hash"] and saved_rec["sig"]
    assert demo_run["result"]["kev"]["calls"] == 0                                   # the exact-name pick needs no Kev
    with pytest.raises(recipes.RecipeError, match=r"\(b\)"):
        recipes.save(recipe, demo_run["dry_run_id"])                                 # params: one run is not enough
    other = recipes.dry_run(recipe, {"kw": "Java", "title": "進階 Java 課程"})
    assert other["passed"] is True, other
    assert other["demo"]["demo_run"] is False and other["demo"]["isolated"] is True
    assert browser_contexts() == before                                             # every isolated context was disposed
    assert recipes.save(recipe, other["dry_run_id"]).endswith("wp2b-steps-recipe.json")
    # run_recipe never depends on the recording: delete it, the saved recipe still runs (in the everyday profile)
    import shutil
    shutil.rmtree(mgr.root / s.id)
    out = recipes.execute(recipes.get("wp2b-steps-recipe"), {"kw": "Java", "title": "進階 Java 課程"})
    assert out["status"] == "done" and out["isolated"] is False


def test_residual_state_a_dropped_step_wrote_cannot_be_saved_and_isolation_shows_it(start, chrome):
    """B3: the demo's consent click wrote localStorage that the detail page reads. A recipe that leaves the click out is not the demonstration,
    its clean-context replay shows a different page, and only a run in the everyday profile (which kept the state) would look fine."""
    set_consent(chrome, False)
    s = start("rec_steps_home.html")
    demo_steps(s)
    res = s.stop()
    dropped = parameterised(res, "wp2b-steps-dropped")
    dropped["steps"] = dropped["steps"][1:]                                          # the state-writing step is missing
    params = {"kw": "Python", "title": TITLE}
    run = recipes.dry_run(dropped, params)
    assert run["passed"] is True and run["demo"]["demo_run"] is False and run["demo"]["isolated"] is True     # the engine can finish; it is not the demo
    with pytest.raises(recipes.RecipeError, match=r"\(a\)"):
        recipes.save(dropped, run["dry_run_id"])
    demo = demo_of(s.id)
    clean = recipes.execute(dropped, params, isolated=True, demo=demo)
    assert clean["isolated"] is True and clean["status"] == "done" and clean["demo_compare"]["match"] is False       # 一般價, not 會員價
    assert "標記的文字沒有完整出現" in clean["demo_compare"]["diff"]["why"]
    leaky = recipes.execute(dropped, params, demo=demo)                              # the everyday profile still holds the consent: it "passes"
    assert leaky["isolated"] is False and leaky["demo_compare"]["match"] is True


def test_state_the_demonstrator_already_had_is_not_replayable_needs_profile_state(start, chrome):
    """The profile consented before the recording, so the banner (and its click) never appears in the demonstration: the draft replays in a clean
    context, the detail text differs, and the recorded recipe is not savable (no silent fallback to the user's profile)."""
    set_consent(chrome, True)
    s = start("rec_steps_home.html")
    demo_steps(s, consent=False)
    res = s.stop()
    d = res["draft"]
    assert [next(iter(st)) for st in d["steps"]] == ["fill", "click", "pick"]
    recipe = as_recipe(res, "wp2b-steps-prestate", params={"title": {"description": "課程", "example": TITLE}})
    recipe["steps"][-1]["pick"]["want"] = "{title}"
    recipe["result"] = {"expect_text": ["{title}"]}
    out = recipes.dry_run(recipe, {"title": TITLE})
    assert out["passed"] is False and out["demo"]["demo_run"] is True and out["demo"]["match"] is False and out["demo"]["isolated"] is True
    assert out["unsupported"]["reason"] == "needs_profile_state" and "不會自動改用你的 profile" in out["unsupported"]["hint"]
    with pytest.raises(recipes.RecipeError, match="did not pass"):
        recipes.save(recipe, out["dry_run_id"])
    assert recipes.execute(recipe, {"title": TITLE}, demo=demo_of(s.id))["demo_compare"]["match"] is True         # the everyday profile would have passed
    set_consent(chrome, False)


def test_compare_to_reports_the_site_renaming_the_list_button(start, chrome, mgr):
    set_consent(chrome, False)
    s1 = start("rec_steps_home.html")
    demo_steps(s1)
    res1 = s1.stop()
    set_consent(chrome, False)                                                        # the first demonstration left its consent behind
    s2 = start("rec_steps_home.html?v=2")                                            # the site now calls the row link 詳情
    demo_steps(s2)
    saved = parameterised(res1, "wp2b-old-steps")
    saved["url"] = s2.url                                                             # same page as the new demonstration: only the site changed
    saved["result"] = {"expect_text": ["Python", TITLE]}
    recipes.USER.mkdir(parents=True, exist_ok=True)
    (recipes.USER / "wp2b-old-steps.json").write_text(json.dumps(saved, ensure_ascii=False))
    res2 = s2.stop(compare_to="wp2b-old-steps")
    assert res2["state"] == "completed" and res2["draft"]["steps"][-1]["pick"]["click"] == "詳情"
    diff = res2["diff"]
    assert diff["recipe"] == "wp2b-old-steps" and diff["same"] is False
    ren, pat = diff["changes"]                                        # the rename, and the pick's row pattern that carries the button word as a constant cell
    assert (ren["kind"], ren["op"], ren["recipe"], ren["demo"]) == ("step_renamed", "pick", "查看", "詳情")
    assert pat["kind"] == "step_pick_pattern" and pat["recipe"].endswith("查看$") and pat["demo"].endswith("詳情$")
    set_consent(chrome, False)


def test_a_repeated_pager_click_is_suggested_as_next_page_and_the_finished_recipe_saves(start, chrome):
    s = start("pager_js.html")
    s.sim.click("#next")
    s.wait_groups(1)
    s.sim.click("#next")
    s.wait_groups(2)
    s.mark("#out tr:first-child td", 3)                                              # td -> tr -> tbody -> table
    res = s.stop()
    d = res["draft"]
    assert res["state"] == "completed" and d["type"] == "steps" and [st.get("click") for st in d["steps"]] == ["下一頁", "下一頁"]
    assert d["steps"][0]["then"] == {"rows": True} and d["steps"][1]["then"] == {"rows": True}
    sug = [x for x in res["step_suggestions"] if x["kind"] == "next_page"]
    assert len(sug) == 1 and sug[0]["next_page"] == {"click": "下一頁", "max_pages": 3, "end": ""} and sug[0]["can_replace_now"] is True
    assert any("end 留空" in w for w in res["warnings"])
    # Claude tries it, sees the last page's button disabled, writes end and the column names
    recipe = as_recipe(res, "wp2b-pager-recipe")
    recipe["steps"] = [{"next_page": {"click": "下一頁", "max_pages": 3, "end": "disabled"}}]
    recipe["result"]["rows"]["columns"] = ["場次", "時間"]
    run = recipes.dry_run(recipe, {})
    assert run["passed"] is True, run
    assert run["demo"]["demo_run"] is True and run["demo"]["match"] is True and run["demo"]["isolated"] is True    # the marked page 3 = the replayed last page
    assert run["result"]["pages_collected"] == 3 and run["result"]["rows_total"] == 9
    assert recipes.save(recipe, run["dry_run_id"]).endswith("wp2b-pager-recipe.json")
