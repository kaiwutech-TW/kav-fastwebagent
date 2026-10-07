"""WP2 Chrome integration (isolated test Chrome, KFW_CHROME_TESTS=1): a real demonstration is recorded with simulated user input,
converted to a draft at stop, replayed in a fresh browser context, compared with what the user marked, and saved.
Nothing here touches :9333 or ~/.kav-fastweb (chrome_harness points KFW_HOME / KFW_CDP at throwaway values)."""

import json
import shutil

import pytest

from chrome_harness import CDP_URL
from rec_helpers import Sim, groups_of

from kfw import compare, recipes, record
from kfw.cdp import Browser, wait_until
from kfw.page import ObservedTab

pytestmark = pytest.mark.chrome


@pytest.fixture
def mgr(chrome):
    chrome.check_identity()
    b = Browser(CDP_URL)
    before = {t["targetId"] for t in b.send("Target.getTargets")["targetInfos"] if t["type"] == "page"}
    m = record.Manager(home=compare.HOME, browser_factory=lambda: Browser(CDP_URL))   # recipes read recordings from compare.HOME
    yield m
    a = m.active()
    if a is not None:
        a.finish(discard=True)
    for t in b.send("Target.getTargets")["targetInfos"]:
        if t["type"] == "page" and t["targetId"] not in before:
            try:
                b.send("Target.closeTarget", targetId=t["targetId"])
            except Exception:
                pass
    b.close()


class Session:
    def __init__(self, mgr, chrome, page, host="a.test"):
        self.mgr, self.chrome = mgr, chrome
        self.url = chrome.url(page, host)
        started = mgr.start(self.url)
        assert started["state"] == "recording", started
        self.id = started["recording_id"]
        self.rec = mgr.active()
        assert self.rec is not None
        self.sim = Sim(self.rec.target_id)

    def wait_groups(self, n, timeout=6):
        assert wait_until(lambda: len([g for g in groups_of(self.rec) if g["closed"]]) >= n, timeout), groups_of(self.rec)

    def wait_epoch(self, n, timeout=8):
        assert wait_until(lambda: (lambda d: d["epoch"] == n and d["armed"])(self.rec.debug()), timeout), self.rec.debug()

    def mark(self, sel, ups=0):
        self.sim.click_bar("mark")
        assert wait_until(lambda: self.sim.info()["marking"], 3)
        x, y, w, h = self.sim.rect(sel)
        self.sim.mouse("mouseMoved", x + 5, y + 5)
        for _ in range(ups):
            self.sim.key("ArrowUp", code="ArrowUp")
        self.sim.mouse("mousePressed", x + 5, y + 5, "left", 1)
        self.sim.mouse("mouseReleased", x + 5, y + 5, "left", 1)
        assert wait_until(lambda: self.rec.debug()["marks"] >= 1, 3), self.sim.info()

    def mark_table(self):
        self.mark("#t td", 3)          # td -> tr -> tbody -> table

    def stop(self, **kw):
        res = self.mgr.stop(self.id, **kw)
        self.sim.close()
        return res


@pytest.fixture
def start(mgr, chrome):
    made = []

    def _start(page, host="a.test"):
        s = Session(mgr, chrome, page, host)
        made.append(s)
        return s
    yield _start
    for s in made:
        try:
            s.sim.close()
        except Exception:
            pass


def demo_form(s):
    """City (select, type-ahead), name (typed), date (a home-made picker grid: not a field), then 查詢, then mark the result table."""
    s.sim.ev("document.getElementById('city').focus()")
    s.sim.key("k", code="KeyK", text="k")                                  # -> Kaohsiung
    s.wait_groups(1)
    s.sim.focus_by_click("#who")
    s.sim.insert("王小明")
    s.wait_groups(3)
    s.sim.click('.cell[data-d="2026-10-05"]')
    s.wait_groups(4)
    s.sim.click("#go")
    s.wait_epoch(2)
    s.mark_table()


def as_recipe(res, name, **over):
    r = dict(res["draft"])
    r.update(name=name, description="測試用的流程", **over)
    return r


def browser_contexts():
    b = Browser(CDP_URL)
    try:
        return set(b.send("Target.getBrowserContexts")["browserContextIds"])
    finally:
        b.close()


def test_form_demo_to_draft_isolated_demo_run_second_params_and_save(start, mgr):
    s = start("wp2_form.html")
    demo_form(s)
    res = s.stop()
    assert res["state"] == "completed", res
    d = res["draft"]
    assert d["type"] == "form_submit" and d["recorded_from"] == s.id and d["url"].endswith("/wp2_form.html")
    assert [(f["label"], f["kind"], f["value"]) for f in d["fields"]] == [("城市", "select", "Kaohsiung"), ("姓名", "text", "王小明"), ("日期", "text", "2026-10-05")]
    assert [c["via_widget"] for c in res["param_candidates"]] == [False, False, True]            # the date came from the picker grid
    assert d["submit"] == {"click": "查詢"} and d["result"]["rows"]["columns"] == ["車次", "時間", "目的地"]
    assert res["live_checks"]["status"] == "checked" and res["live_checks"]["pattern_specific"] is True     # one table matches, same fingerprint
    assert res["demo"]["comparator"] == "rows-exact-v1" and "unsupported" not in res
    assert len(json.dumps(res, ensure_ascii=False)) < 9000
    # Claude parameterises: city and name; the pattern's copied constant column follows the city parameter
    pattern = d["result"]["rows"]["pattern"]
    assert "Kaohsiung" in pattern
    recipe = as_recipe(res, "wp2-form-recipe", params={"city": {"description": "城市", "example": "Kaohsiung"}, "who": {"description": "姓名", "example": "王小明"}})
    recipe["fields"] = [{**recipe["fields"][0], "value": "{city}"}, {**recipe["fields"][1], "value": "{who}"}, recipe["fields"][2]]
    recipe["result"] = {"rows": {**recipe["result"]["rows"], "pattern": pattern.replace("Kaohsiung", "{city}")}}
    before = browser_contexts()
    demo_run = recipes.dry_run(recipe, {"city": "Kaohsiung", "who": "王小明"})
    assert demo_run["passed"] is True, demo_run
    assert demo_run["demo"] == {"demo_run": True, "comparator": "rows-exact-v1", "match": True, "diff": demo_run["demo"]["diff"], "isolated": True}
    rec = json.loads((recipes.DRYRUNS / f"{demo_run['dry_run_id']}.json").read_text())
    assert rec["isolated"] is True and rec["match"] is True and rec["recording_digest"] and rec["rendered_actions_hash"] and rec["recipe_hash"] == recipes.recipe_hash(recipe)
    with pytest.raises(recipes.RecipeError, match="(b)"):
        recipes.save(recipe, demo_run["dry_run_id"])                                             # params: one run is not enough
    other = recipes.dry_run(recipe, {"city": "Taichung", "who": "李四"})
    assert other["passed"] is True and other["demo"]["demo_run"] is False and other["result"]["rows"][0]["目的地"] == "Taichung"
    assert browser_contexts() == before                                                            # every isolated context was disposed
    path = recipes.save(recipe, other["dry_run_id"])
    assert path.endswith("wp2-form-recipe.json")
    # run_recipe never depends on the recording: delete it, the saved recipe still runs (in the normal profile)
    shutil.rmtree(mgr.root / s.id)
    out = recipes.execute(recipes.get("wp2-form-recipe"), {"city": "Taichung", "who": "甲"})
    assert out["status"] == "done" and out["isolated"] is False and out["rows"][0]["目的地"] == "Taichung"


def test_text_block_demo_becomes_detail_extract_and_saves_with_only_the_demo_run(start):
    s = start("wp2_notice.html")
    s.mark("#note p", 1)
    res = s.stop()
    d = res["draft"]
    assert res["state"] == "completed" and d["type"] == "detail_extract" and d["url"].endswith("/wp2_notice.html") and "rows" not in d
    assert res["demo"]["comparator"] == "text-contains-v1" and d["expect_text"] and any("expect_text" in w for w in res["warnings"])
    recipe = as_recipe(res, "wp2-notice-recipe")
    run = recipes.dry_run(recipe, {})
    assert run["passed"] is True, run
    assert run["demo"]["match"] is True and run["demo"]["comparator"] == "text-contains-v1" and run["demo"]["isolated"] is True
    assert run["result"]["product"] is None and run["result"]["status"] == "done"                  # found through text-contains, not product/rows
    assert recipes.save(recipe, run["dry_run_id"]).endswith("wp2-notice-recipe.json")               # no params: (a) alone is enough
    # a page whose text changed no longer matches: the same recipe on a different page is not the demonstration
    wrong = {**recipe, "name": "wp2-notice-wrong", "url": recipe["url"].replace("wp2_notice", "wp2_one_table")}
    bad = recipes.dry_run(wrong, {})
    assert bad["passed"] is False


def test_residual_state_the_draft_dropped_cannot_be_saved(start):
    """B3: the demo set localStorage (a button click) and the result page depends on it. A draft that leaves that operation out
    replays in a clean context, shows different rows, and must not be savable; a non-isolated run would have passed by accident."""
    s = start("wp2_state_form.html")
    s.sim.click("#adv")
    s.wait_groups(1)
    s.sim.focus_by_click("#q")
    s.sim.insert("abc")
    s.wait_groups(3)
    s.sim.click("#go")
    s.wait_epoch(2)
    s.mark_table()
    res = s.stop()
    d = res["draft"]
    assert d["pre"] == [{"click": "啟用進階", "optional": True}] and res["demo"]["marked_rows"] == 4
    control = as_recipe(res, "wp2-state-with-pre")
    ok = recipes.dry_run(control, {})
    assert ok["passed"] is True and ok["demo"]["match"] is True                                     # the click is in the recipe: the state is rebuilt
    dropped = as_recipe(res, "wp2-state-no-pre")
    dropped.pop("pre")
    bad = recipes.dry_run(dropped, {})
    assert bad["passed"] is False and bad["demo"]["demo_run"] is True and bad["demo"]["match"] is False
    assert "列數不同" in bad["demo"]["diff"]["why"] and bad["demo"]["isolated"] is True
    assert bad["unsupported"]["reason"] == "needs_profile_state" and "不會自動改用你的 profile" in bad["unsupported"]["hint"]
    with pytest.raises(recipes.RecipeError, match="did not pass"):
        recipes.save(dropped, bad["dry_run_id"])
    # the same recipe in the everyday profile (which still holds the demo's localStorage) would have passed: that is why isolation is mandatory
    leaky = recipes.execute(dropped, {})
    assert leaky["status"] == "done" and leaky["isolated"] is False and leaky["rows_total"] == 4


def test_isolation_evidence_storage_is_not_inherited_between_runs_and_forged_records_are_refused(start, chrome):
    s = start("wp2_storage.html")
    s.mark("#out", 0)                                                   # "visits: 1 ..." (the demo's own visit)
    res = s.stop()
    assert res["draft"]["expect_text"] and res["demo"]["comparator"] == "text-contains-v1"   # the comparator, not the anchor, holds "visits: 1"
    recipe = as_recipe(res, "wp2-storage-recipe")
    before = browser_contexts()
    runs = [recipes.dry_run(recipe, {}) for _ in range(2)]
    assert all(r["passed"] and r["demo"]["match"] and r["demo"]["isolated"] for r in runs)          # both see "visits: 1": nothing carried over
    assert browser_contexts() == before
    # the everyday profile only ever saw the demo's visit (+ this navigation), never the replays'
    b = Browser(CDP_URL)
    tab = ObservedTab.open(b)
    try:
        tab.goto(chrome.url("wp2_storage.html", "a.test"))
        assert tab.evaluate("localStorage.getItem('visits')") == "2"
    finally:
        tab.close()
        b.close()
    # a record edited after the fact, or with the flag claimed by hand, is refused by save
    forged = recipes.DRYRUNS / f"{runs[1]['dry_run_id']}.json"
    rec = json.loads(forged.read_text())
    assert rec["isolated"] is True and rec["sig"]
    forged.write_text(json.dumps({**rec, "isolated": False}))
    with pytest.raises(recipes.RecipeError, match=r"\(e\)"):
        recipes.save(recipe, runs[1]["dry_run_id"])
    forged.write_text(json.dumps({k: v for k, v in rec.items() if k != "sig"}))
    with pytest.raises(recipes.RecipeError, match=r"\(e\)"):
        recipes.save(recipe, runs[1]["dry_run_id"])
    assert recipes.save(recipe, runs[0]["dry_run_id"]).endswith("wp2-storage-recipe.json")


def test_autocomplete_value_set_by_picking_a_suggestion_is_not_replayable(start):
    s = start("wp2_auto.html")
    s.sim.focus_by_click("#place")
    s.sim.insert("Tai")
    s.wait_groups(2)
    assert wait_until(lambda: s.sim.ev("document.querySelectorAll('.sug').length") == 3, 3)
    s.sim.click(".sug")                                                 # Taichung: sets the visible text AND a hidden code
    s.wait_groups(3)
    s.sim.click("#go")
    s.wait_epoch(2)
    s.mark_table()
    res = s.stop()
    d = res["draft"]
    assert d["fields"] == [{"label": "城市搜尋", "kind": "text", "value": "Taichung"}]
    assert res["param_candidates"][0]["via_widget"] is True
    assert res["demo"]["actions"]["fields"][0]["via_widget"] is True
    out = recipes.dry_run(as_recipe(res, "wp2-auto-recipe"), {})
    assert out["passed"] is False and out["demo"]["demo_run"] is True and out["demo"]["match"] is False
    assert out["unsupported"]["reason"] == "widget_value_not_replayable" and "城市搜尋" in out["unsupported"]["hint"]
    assert out["demo"]["diff"]["why"]                                    # the comparison says what differed (no matching table / other cells)


def test_live_check_single_table_is_specific_two_same_shaped_tables_are_not(start):
    s = start("wp2_one_table.html")
    s.mark_table()
    res = s.stop()
    lc = res["live_checks"]
    assert lc["status"] == "checked" and lc["groups_matched"] == 1 and lc["fingerprint_equal"] is True and lc["pattern_specific"] is True
    assert res["draft"]["type"] == "detail_extract" and res["draft"]["rows"]["pattern"] == lc["pattern"]
    assert not any("不專一" in w for w in res["warnings"])
    s2 = start("wp2_two_tables.html")
    s2.mark_table()
    res2 = s2.stop()
    lc2 = res2["live_checks"]
    assert lc2["status"] == "checked" and lc2["groups_matched"] == 2 and lc2["pattern_specific"] is False
    assert any("不專一" in w for w in res2["warnings"]) and "rows.pattern(not specific)" in res2["draft_todo"]


def test_live_check_is_pending_when_the_page_left_the_marked_document(start, chrome):
    s = start("wp2_one_table.html")
    s.mark_table()
    s.sim.call("Page.navigate", url=chrome.url("rec_b.html", "a.test"))
    s.wait_epoch(2)
    res = s.stop()
    assert res["live_checks"]["status"] == "pending" and res["live_checks"]["reason"] == "page_left_marked_document"
    assert res["live_checks"]["pattern_specific"] is None and any("專一性沒有" in w for w in res["warnings"])
    assert res["draft"]["url"].endswith("/wp2_one_table.html")             # the marked page's URL, not where the user went afterwards


def test_compare_to_diffs_a_recording_against_a_saved_recipe(start, mgr):
    s = start("wp2_form.html")
    demo_form(s)
    res = s.stop()
    old = {"name": "wp2-old-form", "type": "form_submit", "description": "舊版", "url": res["draft"]["url"],
           "fields": [{"label": "城市", "kind": "select", "value": "Taipei"}, {"label": "姓名", "kind": "text", "value": "王小明"}],
           "submit": {"click": "送出"}, "result": {"rows": {"pattern": "^x$", "columns": ["a", "b", "c"]}}}
    recipes.USER.mkdir(parents=True, exist_ok=True)
    (recipes.USER / "wp2-old-form.json").write_text(json.dumps(old, ensure_ascii=False))
    again = mgr.stop(s.id, compare_to="wp2-old-form")                     # a finished recording answers again, now with the diff
    kinds = {c["kind"] for c in again["diff"]["changes"]}
    assert again["diff"]["recipe"] == "wp2-old-form" and {"field_added", "field_value", "submit", "result_pattern"} <= kinds
    assert "diff" not in mgr.stop(s.id)
