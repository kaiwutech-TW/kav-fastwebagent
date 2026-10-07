"""WP2b unit tests (no Chrome): recording -> `steps` draft (design 6.3), then candidates, pick / next_page suggestions, steps + recorded_from
evidence records, and compare_to for steps recipes. Hand-built logs in the format WP1 writes (tests/rec_fixtures.py)."""

import json
import re

import pytest
from rec_fixtures import Rec, button, button_target, field_target, link, list_row, res, select, table_group, target, text
from test_wp2_units import RID, dry, env, put_recording, run_result, save_err  # noqa: F401  (env is a fixture)

from kfw import draft, record, recipes

RESULT_ROWS = [["0101", "08:00", "Taichung"], ["0103", "09:00", "Taichung"], ["0105", "10:30", "Taichung"]]
SIG = "TR.|3"


def convert(rec, live=None):
    return draft.to_draft(rec.log, rec.snaps, live, recording_id=RID)


def ops(d):
    """(operation, target, value) per step: what the draft does, in order."""
    out = []
    for st in d["steps"]:
        if "click" in st:
            out.append(("click", st["click"], None))
        elif "pick" in st:
            out.append(("pick", st["pick"]["click"], st["pick"]["want"]))
        else:
            op = next(k for k in ("fill", "select", "check", "wait", "next_page") if k in st)
            out.append((op, st[op], st.get("value")))
    return out


def two_page_recording(name="王小明", date="2026-10-05"):
    """home: type a keyword, 下一步 -> page 2: type a date, 查詢 -> result page: mark the table."""
    r = Rec()
    f1 = [text("k1", "關鍵字", ""), button("k2", "下一步")]
    base = r.doc("http://a.test/p1.html", f1, res=res(heads=["首頁"]))
    typed = [text("k1", "關鍵字", name), f1[1]]
    _, c = r.group("text_input", field_target("k1", "關鍵字"), base, typed)
    r.group("pointer", button_target("k2", "下一步"), c, None, res=res(heads=["首頁"]))
    f2 = [text("k1", "日期", ""), select("k3", "座位", "靠窗", ["靠窗", "走道"]), button("k4", "查詢")]
    base2 = r.doc("http://a.test/p2.html", f2, res=res(heads=["第二步"]))
    typed2 = [text("k1", "日期", date), *f2[1:]]
    _, c = r.group("text_input", field_target("k1", "日期"), base2, typed2)
    r.group("pointer", button_target("k4", "查詢"), c, None, res=res(heads=["第二步"]))
    r.doc("http://a.test/result.html?q=" + name, [button("k9", "回首頁")], res=res([("ffee", 3, 3, SIG)], ["查詢結果"]))
    r.mark("車次 時間 目的地 " + " ".join(" ".join(x) for x in RESULT_ROWS),
           table_group(RESULT_ROWS, headers=["車次", "時間", "目的地"], fingerprint="ffee", sig=SIG), href="http://a.test/result.html?q=" + name)
    r.done()
    return r


# ---------- fields and clicks in order ----------

def test_a_two_page_flow_becomes_steps_in_the_order_it_was_done():
    out = convert(two_page_recording())
    d = out["draft"]
    assert out["state"] == "completed" and "unsupported" not in out
    assert d["type"] == "steps" and d["recorded_from"] == RID and d["url"] == "http://a.test/p1.html"
    assert ops(d) == [("fill", "關鍵字", "王小明"), ("click", "下一步", None), ("fill", "日期", "2026-10-05"), ("click", "查詢", None)]
    assert d["result"]["rows"]["columns"] == ["車次", "時間", "目的地"] and d["result"]["rows"]["pattern"]
    recipes.validate(d)                                            # a draft is a recipe the engine accepts as it stands
    assert out["demo"]["comparator"] == "rows-exact-v1" and out["demo"]["kind"] == "steps"
    cands = out["param_candidates"]
    assert [(c["label"], c["value"], c["kind"], c["step_index"]) for c in cands] == [("關鍵字", "王小明", "field", 0), ("日期", "2026-10-05", "field", 2)]
    assert not any(c["from_default"] for c in cands)               # steps write what the user did, not every default on the page


def test_a_select_between_clicks_is_a_select_step_before_its_click_and_a_never_edited_field_is_not_written():
    r = Rec()
    f = [select("k1", "城市", "Taipei", ["Taipei", "Taichung"]), text("k2", "備註", "預設"), button("k3", "下一步")]
    base = r.doc("http://a.test/p1.html", f)
    after = [select("k1", "城市", "Taichung", ["Taipei", "Taichung"]), *f[1:]]
    _, c = r.group("keyboard", field_target("k1", "城市", "SELECT"), base, after)
    r.group("pointer", button_target("k3", "下一步"), c, None)
    r.doc("http://a.test/p2.html", [button("k9", "查詢")])
    r.group("pointer", button_target("k9", "查詢"), [button("k9", "查詢")], None)
    r.doc("http://a.test/r.html")
    r.mark("公告 今日停駛:無", None, href="http://a.test/r.html", tag="DIV")
    out = convert(r)
    assert ops(out["draft"]) == [("select", "城市", "Taichung"), ("click", "下一步", None), ("click", "查詢", None)]
    assert out["demo"]["comparator"] == "text-contains-v1" and out["draft"]["result"]["expect_text"]


def test_the_edit_after_the_last_click_becomes_a_final_fill_with_a_warning():
    r = Rec()
    base = r.doc("http://a.test/p1.html", [button("k1", "前往")])
    r.group("pointer", button_target("k1", "前往"), base, None)
    f = [text("k1", "搜尋", "")]
    base2 = r.doc("http://a.test/p2.html", f)
    r.group("text_input", field_target("k1", "搜尋"), base2, [text("k1", "搜尋", "abc")])
    r.mark("結果 abc 共 3 筆", None, href="http://a.test/p2.html", tag="DIV")
    out = convert(r)
    assert ops(out["draft"]) == [("click", "前往", None), ("fill", "搜尋", "abc")]
    assert any("最後一次點擊之後又填了欄位" in w for w in out["warnings"])


def test_dependent_reset_is_still_unsupported_inside_a_steps_flow():
    r = Rec()
    base = r.doc("http://a.test/p1.html", [button("k1", "開始")])
    r.group("pointer", button_target("k1", "開始"), base, None)
    f = [select("k1", "縣市", "台北", ["台北", "高雄"]), select("k2", "區", "", ["", "中正", "苓雅"]), button("k3", "查詢")]
    base2 = r.doc("http://a.test/p2.html", f)
    a = [select("k1", "縣市", "高雄", ["台北", "高雄"]), f[1], f[2]]
    _, c = r.group("keyboard", field_target("k1", "縣市", "SELECT"), base2, a)
    b = [a[0], select("k2", "區", "苓雅", ["", "中正", "苓雅"]), f[2]]
    _, c = r.group("keyboard", field_target("k2", "區", "SELECT"), c, b)
    reset = [b[0], select("k2", "區", "", ["", "中正", "苓雅"]), f[2]]           # the site cleared the district after the user chose it
    r.group("pointer", button_target("k3", "查詢"), reset, None)
    r.doc("http://a.test/r.html")
    r.mark("x 1", None, href="http://a.test/r.html", tag="DIV")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "dependent_reset" and out["unsupported"]["field"] == "區"


@pytest.mark.parametrize("label", ["加入購物車", "收藏", "訂閱電子報"])
def test_a_state_changing_click_in_a_steps_flow_is_still_stateful_in_demo(label):
    r = Rec()
    base = r.doc("http://a.test/p1.html", [button("k1", "前往")])
    r.group("pointer", button_target("k1", "前往"), base, None)
    f = [button("k7", label), button("k8", "查詢")]
    base2 = r.doc("http://a.test/p2.html", f)
    _, c = r.group("pointer", button_target("k7", label), base2, f)
    r.group("pointer", button_target("k8", "查詢"), c, None)
    r.doc("http://a.test/r.html")
    r.mark("x 1", None, href="http://a.test/r.html", tag="DIV")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "stateful_in_demo" and label in out["unsupported"]["hint"]


def _widget_recording(last_label):
    r = Rec()
    base = r.doc("http://a.test/p1.html", [button("k1", "開始"), text("k2", "日期", "")])
    r.group("pointer", target("k2", "", tag="DIV"), base, [button("k1", "開始"), text("k2", "日期", "2026-10-05")])   # a widget cell sets the date
    r.group("pointer", button_target("k1", "開始"), [button("k1", "開始"), text("k2", "日期", "2026-10-05")], None)
    r.doc("http://a.test/p2.html", [button("k5", last_label)])
    r.group("pointer", button_target("k5", last_label), [button("k5", last_label)], None)
    r.doc("http://a.test/r.html")
    r.mark("x 1", None, href="http://a.test/r.html", tag="DIV")
    return r


def test_a_forbidden_click_and_a_widget_value_keep_their_a_version_rules_in_steps():
    out = convert(_widget_recording("登入"))
    assert out["draft"] is None and out["unsupported"]["reason"] == "forbidden_in_demo"
    out = convert(_widget_recording("查詢"))
    assert [c["via_widget"] for c in out["param_candidates"]] == [True]
    assert any("日期" in w and "widget_value_not_replayable" in w for w in out["warnings"])
    assert out["demo"]["actions"]["steps"][0]["via_widget"] is True


# ---------- then candidates ----------

def test_then_candidates_come_from_the_committed_snapshots_and_the_first_one_is_the_default_marked_for_review():
    out = convert(two_page_recording())
    tc = {c["step_index"]: c for c in out["then_candidates"]}
    assert set(tc) == {1, 3}
    first = tc[1]                                                     # click 下一步: page 2 has new fields, a new heading, a new button, a new URL
    assert first["candidates"][0] == {"field": "日期"} and {"field": "座位"} in first["candidates"]
    assert {"text": "第二步"} in first["candidates"] and {"url_contains": "p2.html"} in first["candidates"] and {"gone": "下一步"} in first["candidates"]
    assert first["chosen"] == first["candidates"][0] == out["draft"]["steps"][1]["then"]
    second = tc[3]                                                    # click 查詢: a new heading, the URL, and the marked table appearing
    assert second["candidates"][0] == {"text": "查詢結果"}
    assert {"url_contains": "result.html"} in second["candidates"] and {"rows": True} in second["candidates"]
    kinds = [next(iter(c)) for c in first["candidates"]]
    assert kinds == sorted(kinds, key=["field", "text", "url_contains", "rows", "gone"].index)      # the documented priority order
    assert [n["step_index"] for n in out["needs_review"] if n["what"] == "then"] == [1, 3]
    assert any("then 是程式從點擊後的畫面推出的候選" in w for w in out["warnings"])


def test_a_click_with_no_recognisable_effect_gets_a_placeholder_then_and_a_todo():
    r = Rec()
    f = [button("k1", "展開"), button("k2", "前往")]
    base = r.doc("http://a.test/p1.html", f)
    _, c = r.group("pointer", button_target("k1", "展開"), base, f)          # the page did not change at all
    r.group("pointer", button_target("k2", "前往"), c, None)
    r.doc("http://a.test/p2.html", [button("k5", "查詢")])
    r.group("pointer", button_target("k5", "查詢"), [button("k5", "查詢")], None)
    r.doc("http://a.test/r.html", [button("k9", "回首頁")])
    r.mark("公告 內容", None, href="http://a.test/r.html", tag="DIV")
    out = convert(r)
    s0 = out["draft"]["steps"][0]
    assert s0["click"] == "展開" and s0["then"] == {"text": draft.THEN_PLACEHOLDER}
    assert "steps[0].then" in out["draft_todo"]
    assert next(c for c in out["then_candidates"] if c["step_index"] == 0)["candidates"] == []
    assert any("沒有推得任何 then 候選" in w for w in out["warnings"])


def test_url_change_token_prefers_a_new_path_segment_then_a_new_query_pair():
    assert draft._url_token("http://a.test/p1.html", "http://a.test/p2.html?x=1") == "p2.html"
    assert draft._url_token("http://a.test/s?q=a", "http://a.test/s?q=a&page=2") == "page=2"
    assert draft._url_token("http://a.test/s", "http://a.test/s") is None
    assert draft._url_token("http://a.test/s", "http://a.test/s#top") == "#top"


# ---------- pick ----------

LIST_ROWS = [["初階 Python 課程", "NT$1200", "查看"], ["進階 Python 課程", "NT$2400", "查看"], ["資料庫入門", "NT$1800", "查看"]]
LIST_TEXTS = ["".join(x) for x in LIST_ROWS]                      # inline cells: the row's innerText has no space between them


def list_recording(rows=LIST_ROWS, texts=LIST_TEXTS, clicked=1):
    r = Rec()
    f = [text("k1", "關鍵字", ""), button("k2", "查詢")]
    base = r.doc("http://a.test/home.html", f)
    _, c = r.group("text_input", field_target("k1", "關鍵字"), base, [text("k1", "關鍵字", "python"), f[1]])
    r.group("pointer", button_target("k2", "查詢"), c, None)
    links = [link("k5", "查看"), link("k6", "查看"), link("k7", "查看")]
    lst = r.doc("http://a.test/list.html?q=python", links, res=res([("aa11", len(rows), 3, "DIV.row|3")], ["搜尋結果"]))
    r.group("pointer", button_target("k6", "查看", row=list_row(rows, clicked, texts)), lst, None, res=res([("aa11", len(rows), 3, "DIV.row|3")], ["搜尋結果"]))
    r.doc("http://a.test/detail.html?item=x", [button("k9", "回清單")], res=res(heads=["詳情"]))
    r.mark("詳情:進階 Python 課程 價格 2400", None, href="http://a.test/detail.html?item=x", tag="DIV")
    r.done()
    return r


def test_a_click_inside_a_list_row_that_changes_the_page_is_suggested_as_pick():
    out = convert(list_recording())
    d = out["draft"]
    assert [next(iter(st)) for st in d["steps"]] == ["fill", "click", "pick"]
    pk = d["steps"][2]["pick"]
    assert pk["want"] == "進階 Python 課程" and pk["click"] == "查看"
    assert all(re.search(pk["rows"]["pattern"], t) for t in LIST_TEXTS)                    # the candidate pattern selects every row of that list
    assert set(pk["rows"]) == {"pattern"}
    recipes.validate(d)
    wants = [c for c in out["param_candidates"] if c["kind"] == "pick_want"]
    assert len(wants) == 1 and wants[0]["value"] == "進階 Python 課程" and wants[0]["step_index"] == 2 and wants[0]["in_result_text"] is True
    assert out["step_suggestions"][0]["kind"] == "pick" and out["step_suggestions"][0]["click"] == "查看"
    assert any("寫成 pick" in w for w in out["warnings"])
    assert d["result"]["expect_text"]                                                        # the marked text block on the detail page
    assert [c["step_index"] for c in out["then_candidates"]] == [1]                          # a pick has no `then`
    assert out["demo"]["actions"]["steps"][2] == {"op": "pick", "target": "查看", "want": "進階 Python 課程", "pattern": pk["rows"]["pattern"]}


def test_pick_want_prefers_a_cell_no_other_row_shares_and_skips_price_cells():
    rows = [["熱門課程", "NT$999", "查看"], ["熱門課程", "NT$100", "查看"], ["冷門課程", "NT$100", "查看"]]
    out = convert(list_recording(rows, ["".join(x) for x in rows], clicked=2))
    assert out["draft"]["steps"][2]["pick"]["want"] == "冷門課程"
    dupes = [["熱門課程", "查看"], ["熱門課程", "查看"], ["冷門課程", "查看"]]
    out = convert(list_recording(dupes, ["".join(x) for x in dupes], clicked=0))
    assert out["draft"]["steps"][2]["pick"]["want"] == "熱門課程"
    assert any("不是唯一的" in w for w in out["warnings"])


def test_no_pick_when_the_list_is_one_row_or_ragged_or_the_row_is_only_the_button():
    only = [["初階", "NT$1", "查看"]]
    out = convert(list_recording(only, ["初階NT$1查看"], clicked=0))
    assert [next(iter(st)) for st in out["draft"]["steps"]] == ["fill", "click", "click"]        # one row: nothing to choose from
    ragged = [["初階", "NT$1", "查看"], ["進階", "查看"]]
    out = convert(list_recording(ragged, ["初階NT$1查看", "進階查看"], clicked=0))
    assert [next(iter(st)) for st in out["draft"]["steps"]][2] == "click" and any("無法從各列推出 rows.pattern" in w for w in out["warnings"])
    bare = [["查看"], ["查看"], ["查看"]]
    out = convert(list_recording(bare, ["查看"] * 3, clicked=0))
    assert [next(iter(st)) for st in out["draft"]["steps"]][2] == "click"                       # a row with nothing but the button: no want


# ---------- next_page ----------

def pager_recording(clicks=2, distinct=True):
    r = Rec()
    f = [text("k1", "關鍵字", ""), button("k2", "查詢"), button("k3", "下一頁")]
    base = r.doc("http://a.test/results.html", f)
    typed = [text("k1", "關鍵字", "kw"), f[1], f[2]]
    _, c = r.group("text_input", field_target("k1", "關鍵字"), base, typed)
    fps = ["p1", "p2", "p3", "p4"] if distinct else ["p1", "p1", "p1", "p1"]
    _, c = r.group("pointer", button_target("k2", "查詢"), c, c, res=res())
    for i in range(clicks):
        _, c = r.group("pointer", button_target("k3", "下一頁"), c, c, res=res([(fps[i], 3, 3, SIG)]))
    r.mark("車次 時間 目的地 " + " ".join(" ".join(x) for x in RESULT_ROWS),
           table_group(RESULT_ROWS, headers=["車次", "時間", "目的地"], fingerprint=fps[clicks], sig=SIG), href="http://a.test/results.html")
    r.done()
    return r


def test_repeated_clicks_on_the_same_button_that_each_change_the_result_are_suggested_as_next_page_with_end_left_empty():
    out = convert(pager_recording(2))
    d = out["draft"]
    assert ops(d) == [("fill", "關鍵字", "kw"), ("click", "查詢", None), ("click", "下一頁", None), ("click", "下一頁", None)]   # the draft keeps plain clicks
    sug = [s for s in out["step_suggestions"] if s["kind"] == "next_page"]
    assert len(sug) == 1 and sug[0]["step_indices"] == [2, 3] and sug[0]["next_page"] == {"click": "下一頁", "max_pages": 3, "end": ""}
    assert sug[0]["can_replace_now"] is True
    assert any("end 留空" in w and "next_page" in w for w in out["warnings"])
    assert d["steps"][2]["then"] == {"rows": True} and d["steps"][3]["then"] == {"rows": True}     # a pager's own effect first
    assert [n for n in out["needs_review"] if n["what"] == "next_page.end"][0]["step_indices"] == [2, 3]


def test_a_single_click_or_clicks_that_do_not_change_the_result_are_not_a_pager():
    assert not [s for s in convert(pager_recording(1)).get("step_suggestions", []) if s["kind"] == "next_page"]
    assert not [s for s in convert(pager_recording(2, distinct=False)).get("step_suggestions", []) if s["kind"] == "next_page"]


# ---------- rendered actions, demo-run recognition, hash ----------

def steps_recipe(**kw):
    d = dict(convert(two_page_recording())["draft"])
    d.update(name="recorded-s-test", description="d", **kw)
    return d


def acts(recipe, params=None):
    return draft.rendered_actions(recipes.render_recipe(recipe, params or {}))


def test_rendered_steps_actions_are_the_demo_run_only_with_the_demonstrated_values_and_ignore_waits_optional_clicks_and_then():
    d = convert(two_page_recording())
    demo = d["demo"]["actions"]
    r = steps_recipe()
    assert draft.is_demo_run(acts(r), demo) is True
    with_extras = {**r, "steps": [{"click": "同意", "optional": True, "then": {"gone": "同意"}}, r["steps"][0], {"wait": {"text": "x"}}, *r["steps"][1:]]}
    assert draft.is_demo_run(acts(with_extras), demo) is True                       # Claude's additions do not change what the demonstration is
    other = {**r, "steps": [{**r["steps"][0], "value": "李四"}, *r["steps"][1:]]}
    assert draft.is_demo_run(acts(other), demo) is False
    swapped = {**r, "steps": [r["steps"][2], r["steps"][1], r["steps"][0], r["steps"][3]]}
    assert draft.is_demo_run(acts(swapped), demo) is False                          # order counts
    assert draft.is_demo_run(acts({**r, "url": "http://a.test/other"}), demo) is False
    rethen = {**r, "steps": [r["steps"][0], {**r["steps"][1], "then": {"text": "第二步"}}, *r["steps"][2:]]}
    assert draft.actions_hash(acts(rethen)) == draft.actions_hash(acts(r))          # a different `then` is not a different action


def test_a_pager_recipe_written_as_next_page_is_still_the_demonstrated_run():
    d = convert(pager_recording(2))
    demo = d["demo"]["actions"]
    r = {**d["draft"], "name": "recorded-p-test", "description": "d"}
    as_pager = {**r, "steps": [*r["steps"][:2], {"next_page": {"click": "下一頁", "max_pages": 3, "end": "disabled"}}]}
    assert draft.is_demo_run(acts(as_pager), demo) is True
    longer = {**as_pager, "steps": [*r["steps"][:2], {"next_page": {"click": "下一頁", "max_pages": 4, "end": "disabled"}}]}
    assert draft.is_demo_run(acts(longer), demo) is False


def test_hash_follows_params_used_by_steps_and_not_unused_ones():
    r = steps_recipe(params={"kw": {"example": "王小明"}, "unused": {"example": "z", "required": False}})
    r["steps"] = [{**r["steps"][0], "value": "{kw}"}, *r["steps"][1:]]
    a = draft.actions_hash(acts(r, {"kw": "王小明"}))
    assert a == draft.actions_hash(acts(r, {"kw": "王小明", "unused": "1"}))
    assert a != draft.actions_hash(acts(r, {"kw": "李四"}))


# ---------- dry_run records and save for steps ----------

def rec_steps(env, rid=RID):
    put_recording(env, rid, two_page_recording())
    d = convert(two_page_recording())["draft"]
    d = {**d, "name": "recorded-s-test", "description": "d", "recorded_from": rid}
    d["steps"] = [{**d["steps"][0], "value": "{kw}"}, *d["steps"][1:]]
    d["params"] = {"kw": {"example": "王小明"}}
    return d


def test_a_recorded_steps_recipe_gets_isolated_demo_evidence_and_saves_with_a_second_parameter_run(env, monkeypatch):
    r = rec_steps(env)
    a = dry(monkeypatch, r, {"kw": "王小明"}, run_result())
    assert a["passed"] is True and a["demo"]["demo_run"] is True and a["demo"]["match"] is True and a["demo"]["isolated"] is True
    assert a["result"]["_isolated_arg"] is True and a["result"]["_demo_arg"]["comparator"] == "rows-exact-v1"
    saved = json.loads((env / "dry" / f"{a['dry_run_id']}.json").read_text())
    assert saved["recipe_hash"] == recipes.recipe_hash(r) and saved["comparator"] == "rows-exact-v1" and saved["sig"] and saved["rendered_actions_hash"]
    assert "(b)" in save_err(r, a["dry_run_id"], "(b)")                                 # params: the demo run alone is not enough
    b = dry(monkeypatch, r, {"kw": "李四"}, run_result(match=None))
    assert b["passed"] is True and b["demo"]["demo_run"] is False and b["result"]["_demo_arg"] is None
    assert recipes.save(r, b["dry_run_id"]).endswith("recorded-s-test.json")
    assert json.loads((env / "user" / "recorded-s-test.json").read_text())["recorded_from"] == RID


def test_steps_evidence_refuses_the_same_things_form_submit_does(env, monkeypatch):
    r = rec_steps(env)
    columnless = {**r, "result": {"rows": {k: v for k, v in r["result"]["rows"].items() if k != "columns"}}}
    a2 = dry(monkeypatch, columnless, {"kw": "王小明"}, run_result())
    dry(monkeypatch, columnless, {"kw": "李四"}, run_result(match=None))
    assert "(c)" in save_err(columnless, a2["dry_run_id"], "(c)")                      # (c) reads result.rows of a steps recipe too
    bad = dry(monkeypatch, r, {"kw": "王小明"}, run_result(match=False))
    assert bad["passed"] is False and bad["unsupported"]["reason"] == "needs_profile_state"
    with pytest.raises(recipes.RecipeError, match="did not pass"):
        recipes.save(r, bad["dry_run_id"])
    unisolated = dry(monkeypatch, r, {"kw": "李四"}, run_result(match=None, isolated=False))
    assert unisolated["passed"] is False
    # a recipe that dropped a step of the demonstration is not a demo run: only the engine is checked, and (a) stays missing
    dropped = {**r, "name": "recorded-s-drop", "steps": r["steps"][:2] + r["steps"][3:]}
    d1 = dry(monkeypatch, dropped, {"kw": "王小明"}, run_result(match=None))
    assert d1["demo"]["demo_run"] is False and "(a)" in save_err(dropped, d1["dry_run_id"], "(a)")


def test_a_failed_demo_run_of_a_steps_recipe_names_the_widget_assumption(env, monkeypatch):
    r = _widget_recording("查詢")
    r.epoch = 3
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]], fingerprint="aa", sig=SIG), href="http://a.test/r.html")
    r.done()
    put_recording(env, RID, r)
    d = {**convert(r)["draft"], "name": "recorded-w-test", "description": "d"}
    out = dry(monkeypatch, d, {}, run_result(match=False))
    assert out["passed"] is False and out["unsupported"]["reason"] == "widget_value_not_replayable" and "日期" in out["unsupported"]["hint"]


# ---------- compare_to ----------

def matching_old(d):
    """A saved steps recipe equal to the draft `d` except that its values are parameters."""
    return {"name": "old-steps", "type": "steps", "description": "d", "url": d["url"], "params": {"title": {"example": "進階 Python 課程"}},
            "steps": [{"fill": "關鍵字", "value": "python"}, {"click": "查詢", "then": {"text": "搜尋結果"}},
                      {"pick": {"rows": {"pattern": d["steps"][2]["pick"]["rows"]["pattern"]}, "want": "{title}", "click": "查看"}}],
            "result": {"expect_text": d["result"]["expect_text"]}}


def test_compare_to_reports_a_renamed_button_added_removed_and_changed_steps_and_order():
    d = convert(list_recording())["draft"]
    same = matching_old(d)
    assert draft.diff_against_recipe(d, same) == {"same": True, "changes": []}
    renamed = {**same, "steps": [same["steps"][0], same["steps"][1], {"pick": {**same["steps"][2]["pick"], "click": "詳情"}}]}
    diff = draft.diff_against_recipe(d, renamed)               # the site renamed 詳情 -> 查看 (the recording is the new site)
    ren = [c for c in diff["changes"] if c["kind"] == "step_renamed"]
    assert diff["same"] is False and len(ren) == 1 and (ren[0]["op"], ren[0]["recipe"], ren[0]["demo"]) == ("pick", "詳情", "查看")
    assert len(diff["changes"]) == 1                            # nothing else differs
    clk = {**same, "steps": [same["steps"][0], {**same["steps"][1], "click": "搜尋"}, same["steps"][2]]}
    assert [(x["kind"], x["recipe"], x["demo"]) for x in draft.diff_against_recipe(d, clk)["changes"]] == [("step_renamed", "搜尋", "查詢")]
    val = {**same, "params": {"title": {"example": "資料庫入門"}}}
    assert [(x["kind"], x["recipe"], x["demo"]) for x in draft.diff_against_recipe(d, val)["changes"]] == [("step_value", "資料庫入門", "進階 Python 課程")]
    extra = {**same, "steps": [{"click": "同意", "then": {"gone": "同意"}}, *same["steps"][:2]]}       # a consent click the demo lacks; the pick is missing
    ch = draft.diff_against_recipe(d, extra)["changes"]
    assert {(x["kind"], x["step"]["target"]) for x in ch if "step" in x} == {("step_removed", "同意"), ("step_added", "查看")}
    order = {**same, "steps": [same["steps"][1], same["steps"][0], same["steps"][2]]}
    assert [x["kind"] for x in draft.diff_against_recipe(d, order)["changes"]] == ["order"]
    assert any(x["kind"] == "step_value_param_unresolved" for x in draft.diff_against_recipe(d, {**same, "params": {"title": {}}})["changes"])
    assert [x["kind"] for x in draft.diff_against_recipe(d, {**same, "result": {"expect_text": ["別的"]}})["changes"]] == ["result_expect_text"]
    pat = {**same, "steps": [*same["steps"][:2], {"pick": {**same["steps"][2]["pick"], "rows": {"pattern": "^other$"}}}]}
    assert [x["kind"] for x in draft.diff_against_recipe(d, pat)["changes"]] == ["step_pick_pattern"]


def test_compare_to_between_steps_and_another_type_says_so_instead_of_pretending():
    d = convert(list_recording())["draft"]
    form = {"name": "f-old", "type": "form_submit", "description": "d", "url": d["url"], "fields": [{"label": "a", "kind": "text", "value": "b"}],
            "submit": {"click": "查詢"}, "result": {"expect_text": ["x"]}}
    kinds = [c["kind"] for c in draft.diff_against_recipe(d, form)["changes"]]
    assert "type" in kinds and "steps_vs_other" in kinds


# ---------- payload schema of the new recorder fields ----------

def test_the_new_optional_recorder_fields_are_validated_and_old_payloads_still_pass():
    tgt = {"tag": "A", "native": False, "in_controls": True, "id": "k1", "label": "查看", "text": "查看", "is_button_like": True,
           "custom_element": False, "iframe": False}
    base = {"type": "group_open", "gid": "g1", "kind": "pointer", "prev_snap": None}
    assert record.clean_payload({**base, "target": tgt})["target"] == tgt                                   # a recorder without the new fields
    row = list_row(LIST_ROWS, 1, LIST_TEXTS)
    ok = record.clean_payload({**base, "target": {**tgt, "row": row}, "res": res([("ab", 3, 3, "TR.|3")], ["標題"])})
    assert ok["target"]["row"]["total"] == 3 and ok["res"]["groups"][0]["fp"] == "ab"
    with pytest.raises(record.BadPayload):
        record.clean_payload({**base, "target": {**tgt, "row": {**row, "total": "x"}}})
    with pytest.raises(record.BadPayload):
        record.clean_payload({**base, "target": tgt, "res": {"groups": [{"fp": 1}], "heads": []}})
    b = record.clean_payload({"type": "baseline", "snap": "ab", "res": res(heads=["x"])})
    assert b["res"]["heads"] == ["x"] and "res" not in record.clean_payload({"type": "baseline", "snap": "ab"})
