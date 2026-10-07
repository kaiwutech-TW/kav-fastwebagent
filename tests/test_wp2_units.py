"""WP2 unit tests (no Chrome): recording -> draft conversion, row_pattern, comparators, rendered-actions hash, compare_to diff,
recorded_from validation, dry_run's evidence records and save_recipe's checks (a)-(e), all on hand-built recordings in the
format WP1 writes (tests/rec_fixtures.py, tests/fixtures/recordings/)."""

import json
import re
import shutil
import time

import pytest
from rec_fixtures import (CITIES, FIXTURE_DIR, Rec, button, button_target, checkbox, detail_recording, field_target, form_recording,
                          select, table_group, target, text)

from kfw import draft, recipes, record

RID = "abcdef012345"
REAL_EXECUTE = recipes.execute


def convert(rec, live=None, state=None):
    return draft.to_draft(rec.log, rec.snaps, live, recording_id=RID, terminal_state=state)


def reasons(out):
    return [i["reason"] for i in (out.get("unsupported") or {}).get("all", [out["unsupported"]] if out.get("unsupported") else [])]


# ---------- the committed scenarios and the canonical form_submit ----------

def load(name):
    d = FIXTURE_DIR / name
    return record.read_log(d), record.read_snapshots(d)


def test_committed_form_scenario_becomes_a_valid_form_submit_draft():
    log, snaps = load("form_basic")
    out = draft.to_draft(log, snaps, None, recording_id=RID)
    d = out["draft"]
    assert out["state"] == "completed" and "unsupported" not in out
    assert d["type"] == "form_submit" and d["recorded_from"] == RID and d["url"] == "http://a.test/form.html"
    assert [(f["label"], f["kind"], f["value"]) for f in d["fields"]] == [("城市", "select", "Taichung"), ("姓名", "text", "王小明"), ("日期", "text", "2026-10-05")]
    assert d["submit"] == {"click": "查詢"} and "pre" not in d
    assert d["result"]["rows"]["columns"] == ["車次", "時間", "目的地"] and d["result"]["rows"]["min_rows"] == 1
    recipes.validate(d)                                          # the draft is a recipe the engine accepts as it stands
    assert [c["suggested_name"] for c in out["param_candidates"]] == ["p1", "p2", "p3"]
    date = out["param_candidates"][2]
    assert date["via_widget"] is True and date["from_default"] is False
    assert any("日期" in w and "widget_value_not_replayable" in w for w in out["warnings"])       # via_widget is a stated assumption
    assert out["demo"]["comparator"] == "rows-exact-v1" and out["demo"]["actions"]["fields"][2]["via_widget"] is True


def test_committed_widgetless_variant_has_no_via_widget_and_committed_text_scenario_is_detail_extract():
    log, snaps = load("form_no_widget")
    out = draft.to_draft(log, snaps, None, recording_id=RID)
    assert out["param_candidates"][2]["via_widget"] is False
    log, snaps = load("detail_text")
    out = draft.to_draft(log, snaps, None, recording_id=RID)
    d = out["draft"]
    assert d["type"] == "detail_extract" and d["url"] == "http://a.test/notice.html" and d["expect_text"] and "rows" not in d
    assert out["demo"]["comparator"] == "text-contains-v1" and out["live_checks"] == {"status": "not_applicable"}
    recipes.validate(d)


def test_fields_order_unedited_first_in_dom_order_then_edited_by_last_edit():
    r = Rec()
    f = [text("k1", "姓名", ""), select("k2", "城市", "Taipei", CITIES), text("k3", "備註", "預設備註"), button("k4", "查詢")]
    base = r.doc("http://a.test/", f)
    after_memo_edit = [f[0], f[1], text("k3", "備註", "改過"), f[3]]
    p, c = r.group("text_input", field_target("k3", "備註"), base, after_memo_edit)
    after_name = [text("k1", "姓名", "小明"), *after_memo_edit[1:]]
    r.group("text_input", field_target("k1", "姓名"), c, after_name)
    r.group("pointer", button_target("k4", "查詢"), after_name, None)
    r.doc("http://a.test/r")
    r.mark("a 1 b 2", table_group([["a", "1"], ["b", "2"]]), href="http://a.test/r")
    out = convert(r)
    # 城市 was never edited (default, DOM order) -> first; then the edited fields in the order of their LAST edit: 備註, 姓名
    assert [x["label"] for x in out["draft"]["fields"]] == ["城市", "備註", "姓名"]
    assert [(c["label"], c["from_default"]) for c in out["param_candidates"]] == [("城市", True), ("備註", False), ("姓名", False)]
    assert any("城市" in w and "預設" in w for w in out["warnings"])


def test_a_field_edited_twice_uses_its_last_value_and_position():
    r = Rec()
    f = [text("k1", "姓名", ""), text("k2", "備註", ""), button("k3", "查詢")]
    base = r.doc("http://a.test/", f)
    a = [text("k1", "姓名", "甲"), f[1], f[2]]
    r.group("text_input", field_target("k1", "姓名"), base, a)
    b = [a[0], text("k2", "備註", "備"), f[2]]
    r.group("text_input", field_target("k2", "備註"), a, b)
    c = [text("k1", "姓名", "乙"), b[1], f[2]]
    r.group("text_input", field_target("k1", "姓名"), b, c)
    r.group("pointer", button_target("k3", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert [(x["label"], x["value"]) for x in out["draft"]["fields"]] == [("備註", "備"), ("姓名", "乙")]


# ---------- absorbing rules ----------

def test_a_button_group_never_absorbs_a_field_change_the_site_made_itself():
    r = Rec()
    f = [text("k1", "姓名", "甲"), text("k2", "郵遞區號", ""), button("k3", "查詢")]
    base = r.doc("http://a.test/", f)
    after = [f[0], text("k2", "郵遞區號", "100"), f[2]]        # the site normalised another field while the button was clicked
    r.group("pointer", button_target("k3", "查詢"), base, after)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert out["draft"] is not None
    # not recorded as a set (no edit event), it is only an effective value at the boundary: 姓名 and 郵遞區號 come from defaults
    assert all(c["from_default"] for c in out["param_candidates"]) and [c["label"] for c in out["param_candidates"]] == ["姓名"]


def test_only_a_non_field_non_button_target_becomes_via_widget_and_a_button_click_that_changes_a_field_is_not_absorbed():
    r = form_recording()
    out = convert(r)
    assert [c["via_widget"] for c in out["param_candidates"]] == [False, False, True]
    assert not any(c["via_widget"] for c in convert(form_recording(via_widget=False))["param_candidates"])


def test_custom_element_widget_is_unsupported_custom_widget():
    r = Rec()
    f = [text("k3", "日期", ""), button("k4", "查詢")]
    base = r.doc("http://a.test/", f)
    r.group("pointer", target(None, "", tag="DATE-PICKER", custom=True), base, [text("k3", "日期", "2026-10-05"), f[1]])
    r.group("pointer", button_target("k4", "查詢"), r.snap([text("k3", "日期", "2026-10-05"), f[1]]), None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "custom_widget" and "日期" in out["unsupported"]["hint"]


def test_readonly_field_changed_by_a_widget_is_unsupported_readonly_widget():
    r = Rec()
    f = [text("k3", "日期", "", readonly=True), button("k4", "查詢")]
    base = r.doc("http://a.test/", f)
    after = [text("k3", "日期", "2026-10-05", readonly=True), f[1]]
    r.group("pointer", target(None, "", tag="TD"), base, after)
    r.group("pointer", button_target("k4", "查詢"), after, None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert out["unsupported"]["reason"] == "readonly_widget" and out["draft"] is None


def test_enter_submit_is_unsupported_and_a_harmless_enter_is_not():
    r = Rec()
    f = [text("k1", "關鍵字", ""), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    after = [text("k1", "關鍵字", "abc"), f[1]]
    r.group("text_input", field_target("k1", "關鍵字"), base, after, keys=["Enter"], nav=True)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert out["unsupported"]["reason"] == "enter_submit"
    # Enter in a field followed later by a real click on the button, no navigation from the Enter: the click submits, the Enter is harmless
    r = Rec()
    base = r.doc("http://a.test/", f)
    _, c = r.group("text_input", field_target("k1", "關鍵字"), base, after, keys=["Enter"])
    r.group("pointer", button_target("k2", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    assert convert(r)["draft"]["type"] == "form_submit"


def test_typing_without_any_submit_click_is_unsupported():
    r = Rec()
    f = [text("k1", "姓名", ""), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    r.group("text_input", field_target("k1", "姓名"), base, [text("k1", "姓名", "甲"), f[1]])
    r.mark("x 1", None, href="http://a.test/", tag="DIV")
    assert convert(r)["unsupported"]["reason"] == "no_submit_click"


def test_unlabeled_or_duplicate_label_fields_with_a_value_are_reported_not_filtered():
    r = Rec()
    f = [text("k1", "", "abc"), text("k2", "姓名", ""), button("k3", "查詢")]
    base = r.doc("http://a.test/", f)
    r.group("pointer", button_target("k3", "查詢"), base, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    # untouched and unnameable: left to the site's default, REPORTED as a warning (the isolated demo replay is the check)
    assert out["draft"] is not None and any("沒有名稱" in w and "abc" in w for w in out["warnings"])
    assert all(f["label"] for f in out["draft"]["fields"])
    # but a field the user DID edit and that has no name is unsupported: the flow could not reproduce that edit
    r = Rec()
    base = r.doc("http://a.test/", [text("k1", "", ""), button("k3", "查詢")])
    after = r.snap([text("k1", "", "typed"), button("k3", "查詢")])
    r.group("text_input", {"tag": "INPUT", "label": "", "native": True, "in_controls": True, "id": "k1"}, base, after)
    r.group("pointer", button_target("k3", "查詢"), after, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "ambiguous_field_label"
    dup = [text("k1", "姓名", "甲"), text("k2", "姓名", "乙"), button("k3", "查詢")]
    r = Rec()
    base = r.doc("http://a.test/", dup)
    r.group("pointer", button_target("k3", "查詢"), base, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    dup_out = convert(r)   # untouched duplicates: reported as warnings, left to the site (isolated replay checks it)
    assert dup_out["draft"] is not None and sum("姓名" in w and "沒動過" in w for w in dup_out["warnings"]) == 2
    ok = [text("k1", "姓名", ""), text("k2", "姓名", ""), button("k3", "查詢")]   # duplicates that hold no value are not a problem
    r = Rec()
    base = r.doc("http://a.test/", ok)
    r.group("pointer", button_target("k3", "查詢"), base, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    assert convert(r)["draft"] is not None


def test_checkbox_and_radio_changes_are_unsupported():
    r = Rec()
    f = [checkbox("k1", "同意", False), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    _, c = r.group("pointer", field_target("k1", "同意"), base, [checkbox("k1", "同意", True), f[1]])
    r.group("pointer", button_target("k2", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "checkbox_radio" and out["unsupported"]["field"] == "同意"


@pytest.mark.parametrize("label,why", [("加入購物車", "stateful_in_demo"), ("訂閱", "stateful_in_demo"), ("結帳", "forbidden_in_demo")])
def test_state_changing_or_forbidden_clicks_in_the_demo_are_unsupported(label, why):
    r = Rec()
    f = [text("k1", "姓名", ""), button("k2", label)]
    base = r.doc("http://a.test/", f)
    r.group("pointer", button_target("k2", label), base, None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == why


def test_the_pre_click_before_the_first_edit_is_suggested_optional_with_a_warning():
    r = Rec()
    f = [button("k0", "同意 Cookie"), text("k1", "姓名", ""), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    r.group("pointer", button_target("k0", "同意 Cookie"), base, base)
    a = [f[0], text("k1", "姓名", "甲"), f[2]]
    r.group("text_input", field_target("k1", "姓名"), base, a)
    r.group("pointer", button_target("k2", "查詢"), a, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert out["draft"]["pre"] == [{"click": "同意 Cookie", "optional": True}]
    assert any("同意 Cookie" in w and "可省略" in w for w in out["warnings"])


def test_a_click_between_edits_or_a_page_change_is_no_longer_form_submit_it_becomes_a_steps_draft():
    r = Rec()
    f = [text("k1", "姓名", ""), text("k2", "備註", ""), button("k3", "下一步"), button("k4", "查詢")]
    base = r.doc("http://a.test/", f)
    a = [text("k1", "姓名", "甲"), *f[1:]]
    _, c = r.group("text_input", field_target("k1", "姓名"), base, a)
    _, c = r.group("pointer", button_target("k3", "下一步"), c, c)
    b = [a[0], text("k2", "備註", "乙"), *f[2:]]
    _, c = r.group("text_input", field_target("k2", "備註"), c, b)
    r.group("pointer", button_target("k4", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert "unsupported" not in out and out["draft"]["type"] == "steps"      # WP2b: the shapes version A cannot hold are steps
    # two documents each with actions
    r = Rec()
    f1 = [button("k1", "開始")]
    base = r.doc("http://a.test/1", f1)
    r.group("pointer", button_target("k1", "開始"), base, None)
    f2 = [text("k1", "姓名", ""), button("k2", "查詢")]
    base2 = r.doc("http://a.test/2", f2)
    _, c = r.group("text_input", field_target("k1", "姓名"), base2, [text("k1", "姓名", "甲"), f2[1]])
    r.group("pointer", button_target("k2", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert "unsupported" not in out and out["draft"]["type"] == "steps"


def test_actions_after_the_mark_are_unsupported():
    r = form_recording()
    r.group("pointer", button_target("k9", "回表單"), [button("k9", "回表單")], None)
    out = convert(r)
    assert out["unsupported"]["reason"] == "actions_after_mark"


def test_no_mark_incomplete_state_and_multiple_marks():
    r = Rec()
    r.doc("http://a.test/", [button("k1", "x")])
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "no_mark" and draft.W_NO_MARK in out["warnings"]
    r = form_recording()
    r.incomplete("new_tab")
    out = convert(r)
    assert out["state"] == "incomplete" and out["draft"] is None and "unsupported" not in out
    assert convert(form_recording(), state="incomplete")["draft"] is None
    r = form_recording()
    r.mark("nope 1 x 2", table_group([["nope", "1"], ["x", "2"]]), href="http://a.test/result.html")
    out = convert(r)
    assert draft.w_multi_mark(2) in out["warnings"]
    assert out["demo"]["marked_rows"] == 2 and "columns" not in out["draft"]["result"]["rows"]     # the LAST mark (2 rows, no th) is the one used


# ---------- dependent fields (V05, I2) ----------

def _dependent(delayed):
    """City first, then district; then the site resets the district after the user set it (the reset shows up in the next
    committed snapshot: a later group's `snap`, or the submit boundary itself)."""
    r = Rec()
    f = [select("k1", "縣市", "台北", ["台北", "高雄"]), select("k2", "區", "", ["", "中正", "苓雅"]), button("k3", "查詢")]
    base = r.doc("http://a.test/", f)
    a = [select("k1", "縣市", "高雄", ["台北", "高雄"]), f[1], f[2]]
    _, c = r.group("keyboard", field_target("k1", "縣市", "SELECT"), base, a)
    b = [a[0], select("k2", "區", "苓雅", ["", "中正", "苓雅"]), f[2]]
    _, c = r.group("keyboard", field_target("k2", "區", "SELECT"), c, b)
    if delayed:
        # the user changes city AGAIN and the site clears the district only afterwards
        c2 = [select("k1", "縣市", "台北", ["台北", "高雄"]), b[1], f[2]]
        _, c = r.group("keyboard", field_target("k1", "縣市", "SELECT"), c, c2)
        boundary = [c2[0], select("k2", "區", "", ["", "中正", "苓雅"]), f[2]]
    else:
        boundary = [b[0], select("k2", "區", "", ["", "中正", "苓雅"]), f[2]]
    r.group("pointer", button_target("k3", "查詢"), boundary, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    return r


@pytest.mark.parametrize("delayed", [False, True])
def test_dependent_reset_is_unsupported(delayed):
    out = convert(_dependent(delayed))
    assert out["draft"] is None and out["unsupported"]["reason"] == "dependent_reset" and out["unsupported"]["field"] == "區"
    assert "苓雅" in out["unsupported"]["hint"]


def test_a_deliberately_cleared_default_is_unsupported_cleared_field():
    r = Rec()
    f = [text("k1", "備註", "預設"), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    cleared = [text("k1", "備註", ""), f[1]]
    _, c = r.group("text_input", field_target("k1", "備註"), base, cleared)
    r.group("pointer", button_target("k2", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert out["draft"] is None and out["unsupported"]["reason"] == "cleared_field" and out["unsupported"]["field"] == "備註"
    # typing something then deleting it again, on a field that started empty, is no clear at all
    r = Rec()
    f = [text("k1", "備註", ""), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    _, c = r.group("text_input", field_target("k1", "備註"), base, [text("k1", "備註", "a"), f[1]])
    _, c = r.group("text_input", field_target("k1", "備註"), c, [text("k1", "備註", ""), f[1]])
    r.group("pointer", button_target("k2", "查詢"), c, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    assert convert(r)["draft"]["fields"] == []


def test_the_default_value_of_an_untouched_field_is_written_and_marked_from_default():
    r = Rec()
    f = [select("k1", "座位", "標準座車", ["標準座車", "商務車廂"]), text("k2", "姓名", ""), button("k3", "查詢")]
    base = r.doc("http://a.test/", f)
    r.group("pointer", button_target("k3", "查詢"), base, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert out["draft"]["fields"] == [{"label": "座位", "kind": "select", "value": "標準座車"}]
    assert out["param_candidates"][0]["from_default"] is True


def test_input_submit_buttons_are_not_fields():
    r = Rec()
    f = [text("k1", "姓名", "甲"), text("k2", "查詢", "查詢", input_type="submit")]
    base = r.doc("http://a.test/", f)
    r.group("pointer", target("k2", "查詢", tag="INPUT", native=True, button_=True, text_="查詢"), base, None)
    r.doc("http://a.test/r")
    r.mark("x 1 y 2", table_group([["x", "1"], ["y", "2"]]), href="http://a.test/r")
    out = convert(r)
    assert [f["label"] for f in out["draft"]["fields"]] == ["姓名"] and out["draft"]["submit"] == {"click": "查詢"}


# ---------- results: rows, columns, pattern, expect_text ----------

def test_row_pattern_generalises_per_cell_and_matches_every_marked_row():
    rows = [["0101", "08:00", "台中", "NT$ 700"], ["0103", "09:30", "台中", "NT$ 1,200"], ["0105", "10:30", "台中", "NT$ 730"]]
    p = draft.row_pattern(rows)
    assert p is not None and p.startswith("^") and p.endswith("$")
    assert p == r"^[-+]?\d[\d,]*(?:\.\d+)? \d{1,2}:\d{2}(?::\d{2})? 台中 NT\$ \S(?:.*?\S)?$" or "台中" in p       # constant copied, shapes for train/time
    for r in rows:
        assert re.fullmatch(p[1:-1], " ".join(r))
    assert not re.fullmatch(p[1:-1], "abc 08:00 台中 NT$ 1")
    assert draft.row_pattern([["a", "1"]]) is None and draft.row_pattern([]) is None          # one row says nothing about what varies
    assert draft.row_pattern([["a", "1"], ["b"]]) is None                                     # ragged
    assert draft.row_pattern([["x.y", "1"], ["x.y", "2"]]).startswith(r"^x\.y ")             # literals are escaped
    dates = draft.row_pattern([["2026/10/05", "a"], ["2026-11-06", "b"]])
    assert dates and re.fullmatch(dates[1:-1], "2027/01/31 zzz")


def test_a_single_row_group_gives_no_pattern_and_says_so():
    r = form_recording(rows=[["0101", "08:00", "台中"]])
    out = convert(r)
    assert "pattern" not in out["draft"]["result"]["rows"] and out["draft_todo"][0] == "rows.pattern"
    assert any(w.startswith("single_row") for w in out["warnings"])
    assert out["live_checks"] == {"status": "not_applicable"}
    with pytest.raises(recipes.RecipeError, match="pattern"):
        recipes.validate(out["draft"])                             # a recorded recipe cannot run without the pattern Claude must write


def test_columns_only_from_a_th_header_row_with_matching_count_and_no_repeats():
    assert convert(form_recording())["draft"]["result"]["rows"]["columns"] == ["車次", "時間", "目的地"]
    for headers, why in ((None, "沒有 th"), (("車次", "時間"), "欄數對不上"), (("車次", "車次", "目的地"), "重複"), (("車次", "", "目的地"), "空")):
        out = convert(form_recording(headers=headers))
        assert "columns" not in out["draft"]["result"]["rows"], why
        assert "rows.columns" in out["draft_todo"] and any("columns 沒有自動填" in w for w in out["warnings"])
    # a th header count is not enough when the recorder gave no header texts (old recordings)
    r = form_recording()
    for rec in r.log:
        if rec["type"] == "mark":
            rec["group"]["headers"] = None
    assert "columns" not in convert(r)["draft"]["result"]["rows"]


def test_result_kinds_truncated_empty_and_oversized_are_unsupported():
    big = form_recording()
    for rec in big.log:
        if rec["type"] == "mark":
            rec["group"].update(truncated=True, total=250)
    assert convert(big)["unsupported"]["reason"] == "result_kind"
    part = form_recording()
    for rec in part.log:
        if rec["type"] == "mark":
            rec["group"].update(total=9)                              # rows_sent 3 < total 9: the recorder cut it for size
    assert convert(part)["unsupported"]["reason"] == "result_kind"
    r = detail_recording(text_="")
    assert convert(r)["unsupported"]["reason"] == "result_kind"
    r = detail_recording()
    for rec in r.log:
        if rec["type"] == "mark":
            rec["text_truncated"] = True
    assert convert(r)["unsupported"]["reason"] == "result_kind"


def test_expect_text_is_suggested_from_demo_values_that_appear_in_the_marked_text():
    out = convert(form_recording())
    assert out["suggested_expect_text"] == ["Taichung"]
    assert [c["in_result_text"] for c in out["param_candidates"]] == [True, False, False]
    assert "expect_text" not in out["draft"]["result"]                # a suggestion only, for a rows result
    assert any("Taichung" in w and "照抄" in w for w in out["warnings"])   # the constant column would break after parameterising 城市


def test_text_result_uses_the_demo_value_found_in_the_text_as_expect_text():
    r = Rec()
    f = [text("k1", "追蹤碼", "TW123456"), button("k2", "查詢")]
    base = r.doc("http://a.test/", f)
    r.group("pointer", button_target("k2", "查詢"), base, None)
    r.doc("http://a.test/r")
    r.mark("包裹 TW123456 已送達 2026/10/05", None, href="http://a.test/r", tag="DIV")
    out = convert(r)
    assert out["draft"]["result"] == {"expect_text": ["TW123456"]} and out["demo"]["comparator"] == "text-contains-v1"


def test_no_result_actions_when_only_a_page_change_happened_uses_the_marked_page_url():
    r = Rec()
    r.doc("http://a.test/redirect")
    r.doc("http://a.test/final")
    r.mark("公告 內容 很多字", None, href="http://a.test/final", tag="DIV")
    out = convert(r)
    assert out["draft"]["url"] == "http://a.test/final" and any("換過文件" in w for w in out["warnings"])


# ---------- live check (7.3) as seen by the conversion ----------

def test_live_check_results_reach_the_draft_and_warn_when_not_specific_or_pending():
    r = form_recording()
    pattern = convert(r)["draft"]["result"]["rows"]["pattern"]
    ok = {"status": "checked", "pattern": pattern, "groups_matched": 1, "fingerprint_equal": True, "pattern_specific": True}
    out = convert(r, ok)
    assert out["live_checks"]["pattern_specific"] is True and not any("不專一" in w or "專一性沒有" in w for w in out["warnings"])
    bad = {**ok, "groups_matched": 2, "fingerprint_equal": False, "pattern_specific": False}
    out = convert(r, bad)
    assert out["live_checks"]["pattern_specific"] is False and any("不專一" in w and "2" in w for w in out["warnings"])
    assert "rows.pattern(not specific)" in out["draft_todo"]
    out = convert(r, {"status": "pending", "pattern": pattern, "reason": "page_left_marked_document"})
    assert out["live_checks"]["status"] == "pending" and any("專一性沒有" in w for w in out["warnings"])
    stale = convert(r, {**ok, "pattern": "^other$"})           # a check made for some other pattern is not evidence for this one
    assert stale["live_checks"]["status"] == "pending"


# ---------- comparators (7.4) ----------

def grp(rows, **kw):
    return {"rows": rows, "rows_sent": len(rows), "total": len(rows), "truncated": False, **kw}


def test_rows_exact_compares_canonical_cells_after_normalisation():
    demo = grp([["0101", "08:00"], ["0103", "09:00"]])
    ok, diff = draft.compare_rows_exact(demo, {"rows": [["0101", "08:00"], ["0103", " 09:00 "]], "total": 2, "truncated": False})
    assert ok is True and diff["demo_total"] == 2
    ok, diff = draft.compare_rows_exact(demo, {"rows": [["0101", "08:00"], ["0103", "09:01"]], "total": 2, "truncated": False})
    assert ok is False and diff["row"] == 2 and diff["demo"] == ["0103", "09:00"] and diff["replay"] == ["0103", "09:01"]
    ok, diff = draft.compare_rows_exact(demo, {"rows": [["0101", "08:00"]], "total": 1, "truncated": False})
    assert ok is False and "列數不同" in diff["why"]
    ok, diff = draft.compare_rows_exact(demo, {"rows": [["0101", "08:00", "x"], ["0103", "09:00", "x"]], "total": 2, "truncated": False})
    assert ok is False                                                                   # one more cell in each row
    ok, diff = draft.compare_rows_exact(demo, {"rows": [], "total": 0, "truncated": False})
    assert ok is False and "空" in diff["why"]
    assert draft.compare_rows_exact(grp([]), {"rows": [["a"]], "total": 1, "truncated": False})[0] is False      # empty demo
    assert draft.compare_rows_exact({**demo, "truncated": True}, {"rows": demo["rows"], "total": 2, "truncated": False})[0] is False
    assert draft.compare_rows_exact({**demo, "total": 5}, {"rows": demo["rows"], "total": 5, "truncated": False})[0] is False   # recorder cut it (rows_sent < total)
    assert draft.compare_rows_exact(demo, {"rows": demo["rows"], "total": 2, "truncated": True})[0] is False
    assert draft.compare_rows_exact(None, None)[0] is False


def test_text_contains_needs_the_whole_non_empty_marked_text():
    assert draft.compare_text_contains("公告 今日 正常", "頁首\n公告   今日\n正常 頁尾")[0] is True     # whitespace-normalised
    ok, diff = draft.compare_text_contains("公告 今日 正常", "公告 今日 停駛")
    assert ok is False and diff["matched_prefix_chars"] >= 5 and "正常" in diff["demo_next"]
    assert draft.compare_text_contains("", "anything")[0] is False and draft.compare_text_contains("   ", "x")[0] is False
    assert draft.compare_text_contains("abc", "")[0] is False


# ---------- rendered actions and their hash (I5) ----------

def form_recipe(**kw):
    r = {"name": "recorded-x-test", "type": "form_submit", "description": "d", "recorded_from": RID, "url": "http://a.test/form.html",
         "params": {"city": {"example": "Taichung"}, "who": {"example": "王小明"}, "unused": {"example": "zzz", "required": False}},
         "fields": [{"label": "城市", "kind": "select", "value": "{city}"}, {"label": "姓名", "kind": "text", "value": "{who}"},
                    {"label": "日期", "kind": "text", "value": "2026-10-05"}],
         "submit": {"click": "查詢"},
         "result": {"rows": {"pattern": "^\\d+ \\S+ \\S+$", "min_rows": 1, "columns": ["車次", "時間", "目的地"]}}}
    r.update(kw)
    return r


def actions(recipe, params):
    return draft.rendered_actions(recipes.render_recipe(recipe, params))


def test_hash_ignores_unused_params_and_changes_when_an_action_value_changes():
    r = form_recipe()
    a = actions(r, {"city": "Taichung", "who": "王小明"})
    assert draft.actions_hash(a) == draft.actions_hash(actions(r, {"city": "Taichung", "who": "王小明", "unused": "1"}))
    assert draft.actions_hash(a) == draft.actions_hash(actions(r, {"city": "Taichung", "who": "王小明", "unused": "2"}))
    assert draft.actions_hash(a) != draft.actions_hash(actions(r, {"city": "Kaohsiung", "who": "王小明"}))
    assert draft.actions_hash(a) != draft.actions_hash(actions({**r, "url": "http://a.test/other"}, {"city": "Taichung", "who": "王小明"}))
    # the hash is over what runs: pre clicks, field order and the submit target count
    reordered = {**r, "fields": list(reversed(r["fields"]))}
    assert draft.actions_hash(actions(reordered, {"city": "Taichung", "who": "王小明"})) != draft.actions_hash(a)
    with_pre = {**r, "pre": [{"click": "同意", "optional": True}]}
    assert draft.actions_hash(actions(with_pre, {"city": "Taichung", "who": "王小明"})) != draft.actions_hash(a)


def test_a_parameter_no_action_uses_does_not_make_a_second_run_different():
    r = form_recipe(params={"city": {"example": "Taichung"}, "who": {"example": "王小明"}, "decor": {"example": "x", "required": False}},
                    fields=[{"label": "城市", "kind": "select", "value": "{city}"}, {"label": "姓名", "kind": "text", "value": "王小明"}])
    assert (draft.actions_hash(actions(r, {"city": "Taichung", "who": "甲"}))
            == draft.actions_hash(actions(r, {"city": "Taichung", "who": "乙", "decor": "y"})))       # unreferenced params: same actions


def demo_of(rec):
    return draft.to_draft(rec.log, rec.snaps, None, recording_id=RID)["demo"]["actions"]


def test_demo_run_is_recognised_by_rendered_values_url_and_submit():
    demo = demo_of(form_recording())
    r = form_recipe()
    assert draft.is_demo_run(actions(r, {"city": "Taichung", "who": "王小明"}), demo) is True
    assert draft.is_demo_run(actions(r, {"city": "Kaohsiung", "who": "王小明"}), demo) is False
    assert draft.is_demo_run(actions({**r, "url": "http://a.test/x"}, {"city": "Taichung", "who": "王小明"}), demo) is False
    assert draft.is_demo_run(actions({**r, "submit": {"click": "送出"}}, {"city": "Taichung", "who": "王小明"}), demo) is False
    # a dropped optional pre-click does not change which values ran
    demo_pre = dict(demo, pre=[{"click": "同意", "optional": True}])
    assert draft.is_demo_run(actions(r, {"city": "Taichung", "who": "王小明"}), demo_pre) is True
    detail = demo_of(detail_recording())
    assert draft.is_demo_run({"type": "detail_extract", "url": "http://a.test/notice.html"}, detail) is True
    assert draft.is_demo_run({"type": "detail_extract", "url": "http://a.test/other"}, detail) is False


# ---------- compare_to ----------

def test_diff_against_an_existing_recipe_reports_actions_values_order_and_result_contract():
    out = convert(form_recording())
    d = out["draft"]
    same = {**form_recipe(), "fields": [{"label": "城市", "kind": "select", "value": "Taichung"}, {"label": "姓名", "kind": "text", "value": "王小明"},
                                        {"label": "日期", "kind": "text", "value": "2026-10-05"}],
            "result": {"rows": dict(d["result"]["rows"])}}
    assert draft.diff_against_recipe(d, same)["same"] is True
    old = {**same, "url": "http://a.test/old.html", "pre": [{"click": "同意"}], "submit": {"click": "送出"},
           "fields": [{"label": "縣市", "kind": "select", "value": "Taichung"}, {"label": "日期", "kind": "text", "value": "2026-10-01"},
                      {"label": "姓名", "kind": "text", "value": "王小明"}, {"label": "舊欄位", "kind": "text", "value": "x"}],
           "result": {"rows": {"pattern": "^different$", "min_rows": 2, "columns": ["a", "b", "c"]}, "expect_text": ["Taichung"]}}
    diff = draft.diff_against_recipe(d, old)
    kinds = {c["kind"] for c in diff["changes"]}
    assert diff["same"] is False
    assert {"url", "pre_removed", "field_renamed", "field_removed", "field_value", "order", "submit", "result_pattern", "result_columns",
            "result_min_rows", "result_expect_text"} <= kinds
    ren = next(c for c in diff["changes"] if c["kind"] == "field_renamed")
    assert (ren["from"], ren["to"]) == ("縣市", "城市")
    val = next(c for c in diff["changes"] if c["kind"] == "field_value")
    assert (val["label"], val["recipe"], val["demo"]) == ("日期", "2026-10-01", "2026-10-05")
    # a {param} value is compared through its example; without an example it is reported as not comparable, never equal
    p = {**same, "fields": [{"label": "城市", "kind": "select", "value": "{city}"}, *same["fields"][1:]]}
    assert draft.diff_against_recipe(d, p)["same"] is True                       # example Taichung == demo
    p["params"] = {"city": {}}
    assert any(c["kind"] == "field_value_param_unresolved" for c in draft.diff_against_recipe(d, p)["changes"])
    assert "error" in draft.diff_against_recipe(d, {"type": "search_compare"})
    assert "error" in draft.diff_against_recipe(None, same)


# ---------- recorded_from in the recipe format ----------

def test_recorded_from_is_accepted_only_as_12_hex_and_needs_a_checkable_result():
    r = form_recipe()
    recipes.validate(r)
    for bad in ("short", "ABCDEF012345", "abcdef01234g", "abcdef0123456", 123456789012, None):
        with pytest.raises(recipes.RecipeError, match="recorded_from"):
            recipes.validate({**r, "recorded_from": bad})
    with pytest.raises(recipes.RecipeError, match="pattern"):
        recipes.validate({**r, "result": {"rows": {"min_rows": 1}}})
    with pytest.raises(recipes.RecipeError, match="expect_text"):
        recipes.validate({**r, "result": {"expect_text": []}})
    recipes.validate({**r, "result": {"expect_text": ["x"]}})
    d = {"name": "recorded-y-test", "type": "detail_extract", "description": "d", "recorded_from": RID, "url": "http://a.test/n", "expect_text": ["x"]}
    recipes.validate(d)
    with pytest.raises(recipes.RecipeError, match="expect_text"):
        recipes.validate({**d, "expect_text": [" "]})
    plain = {k: v for k, v in r.items() if k != "recorded_from"}
    recipes.validate(plain)                                        # hand-written recipes stay as they were


def test_the_mark_payload_accepts_optional_header_texts_and_rejects_bad_ones():
    grp_ = {"rows": [["a", "1"]], "rows_sent": 1, "total": 1, "truncated": False, "fingerprint": "ff", "has_th": True, "same_signature_groups": 1}
    mark = {"type": "mark", "tag": "TABLE", "text": "t", "text_truncated": False, "href": "http://a/"}
    assert record.clean_payload({**mark, "group": {**grp_, "headers": ["品名", "價格"]}})["group"]["headers"] == ["品名", "價格"]
    assert record.clean_payload({**mark, "group": grp_})["group"]["rows"] == [["a", "1"]]            # older recorder without headers
    assert record.clean_payload({**mark, "group": {**grp_, "headers": None}})["group"]["headers"] is None
    with pytest.raises(record.BadPayload):
        record.clean_payload({**mark, "group": {**grp_, "headers": [1, 2]}})


# ---------- dry_run records and save_recipe (a)-(e) ----------

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes, "DRYRUNS", tmp_path / "dry")
    monkeypatch.setattr(recipes, "USER", tmp_path / "user")
    monkeypatch.setattr(recipes, "BUILTIN", tmp_path / "builtin")
    monkeypatch.setattr(record.compare, "HOME", tmp_path)
    (tmp_path / "dry").mkdir()
    (tmp_path / "recordings").mkdir()
    return tmp_path


def put_recording(env, rid=RID, rec=None, state="completed", finished=None):
    rec = rec or form_recording()
    d = env / "recordings" / rid
    return rec.write(d, state=state, finished=finished)


def run_result(rows=True, status="done", isolated=True, match=True, diff=None):
    res = {"status": status, "rows": [["1", "a"]] if rows else [], "evidence": {"screenshot": "x"}, "isolated": isolated}
    if match is not None:
        res["demo_compare"] = {"comparator": "rows-exact-v1", "match": match, "diff": diff or {"comparator": "rows-exact-v1"}}
    return res


DEMO = {"city": "Taichung", "who": "王小明"}
OTHER = {"city": "Kaohsiung", "who": "王小明"}


def dry(monkeypatch, recipe, params, result):
    monkeypatch.setattr(recipes, "execute", lambda r, p, allow_stateful=False, isolated=False, demo=None: {**result, "_demo_arg": demo, "_isolated_arg": isolated})
    return recipes.dry_run(recipe, params)


def test_dry_run_of_a_recorded_recipe_requires_the_isolated_context_and_records_the_evidence(env, monkeypatch):
    put_recording(env)
    r = form_recipe()
    out = dry(monkeypatch, r, DEMO, run_result())
    assert out["passed"] is True and out["demo"]["demo_run"] is True and out["demo"]["match"] is True and out["demo"]["isolated"] is True
    assert out["result"]["_isolated_arg"] is True and out["result"]["_demo_arg"]["comparator"] == "rows-exact-v1"     # always isolated, comparison requested
    saved = json.loads((env / "dry" / f"{out['dry_run_id']}.json").read_text())
    dig = json.loads((env / "recordings" / RID / "meta.json").read_text())["digest"]
    assert saved["recipe_hash"] == recipes.recipe_hash(r) and saved["recording_digest"] == dig and saved["comparator"] == "rows-exact-v1"
    assert saved["match"] is True and saved["isolated"] is True and saved["rendered_actions_hash"] == draft.actions_hash(actions(r, DEMO)) and saved["diff"]
    assert saved["demo_run"] is True and saved["sig"]
    # different values: not a demo run, no comparison asked for, still isolated
    out = dry(monkeypatch, r, OTHER, run_result(match=None))
    assert out["passed"] is True and out["demo"]["demo_run"] is False and out["result"]["_demo_arg"] is None and out["result"]["_isolated_arg"] is True
    saved = json.loads((env / "dry" / f"{out['dry_run_id']}.json").read_text())
    assert saved["comparator"] is None and saved["match"] is None and saved["isolated"] is True


def test_a_demo_run_that_does_not_match_fails_and_explains_needs_profile_state_or_widget(env, monkeypatch):
    put_recording(env)
    nowidget = form_recipe(fields=[f for f in form_recipe()["fields"] if f["label"] != "日期"])       # not the demo's actions: 日期 dropped
    out = dry(monkeypatch, nowidget, DEMO, run_result())
    assert out["demo"]["demo_run"] is False
    put_recording(env, "bbbbbbbbbbbb", form_recording(via_widget=False))
    r = form_recipe(recorded_from="bbbbbbbbbbbb")
    out = dry(monkeypatch, r, DEMO, run_result(match=False, diff={"why": "第 2 列的內容不同"}))
    assert out["passed"] is False and out["demo"]["match"] is False and out["demo"]["diff"]["why"]
    assert out["unsupported"]["reason"] == "needs_profile_state" and "不會自動改用你的 profile" in out["unsupported"]["hint"]
    assert "刪掉 recorded_from" in out["unsupported"]["hint"] and "不是網站伺服器端的交易" in out["unsupported"]["hint"]
    # the demonstration set 日期 through a widget: the failure is named after that assumption
    out = dry(monkeypatch, form_recipe(), DEMO, run_result(match=False))
    assert out["unsupported"]["reason"] == "widget_value_not_replayable" and "日期" in out["unsupported"]["hint"]
    # the engine itself failing (a field not found) is reported by its own reason, not blamed on profile state
    out = dry(monkeypatch, r, DEMO, run_result(status="needs_help", rows=False, match=None))
    assert out["passed"] is False and "unsupported" not in out
    # same when the demonstration had a widget-set field: the engine failed before any comparison, so the widget
    # assumption was never tested and must not be blamed (first real-site acceptance hit this misreport)
    out = dry(monkeypatch, form_recipe(), DEMO, run_result(status="needs_help", rows=False, match=None))
    assert out["passed"] is False and "unsupported" not in out


def test_dry_run_never_passes_without_the_isolated_environment_and_never_lets_the_caller_claim_it(env, monkeypatch):
    put_recording(env)
    r = form_recipe()
    out = dry(monkeypatch, r, DEMO, run_result(isolated=False))
    assert out["passed"] is False
    assert json.loads((env / "dry" / f"{out['dry_run_id']}.json").read_text())["isolated"] is False
    out = dry(monkeypatch, r, DEMO, {"status": "error", "reason": "isolation_unavailable", "isolated": False, "hint": "x"})
    assert out["passed"] is False and "unsupported" not in out and out["result"]["reason"] == "isolation_unavailable"


def test_dry_run_of_a_recorded_recipe_needs_a_usable_recording(env, monkeypatch):
    r = form_recipe()
    with pytest.raises(recipes.RecipeError, match="找不到錄製"):
        dry(monkeypatch, r, DEMO, run_result())
    put_recording(env, state="incomplete")
    with pytest.raises(recipes.RecipeError, match="completed"):
        dry(monkeypatch, r, DEMO, run_result())
    unsupported = Rec()
    f = [checkbox("k1", "同意", False), button("k2", "查詢")]
    base = unsupported.doc("http://a.test/", f)
    unsupported.group("pointer", field_target("k1", "同意"), base, [checkbox("k1", "同意", True), f[1]])
    unsupported.mark("x 1", None, href="http://a.test/", tag="DIV")
    unsupported.done()
    put_recording(env, "cccccccccccc", unsupported)
    with pytest.raises(recipes.RecipeError, match="沒有可用的草稿"):
        dry(monkeypatch, form_recipe(recorded_from="cccccccccccc"), DEMO, run_result())
    put_recording(env, "dddddddddddd", form_recording())
    with pytest.raises(recipes.RecipeError):                     # search_compare cannot carry recorded_from
        recipes.dry_run({"name": "recorded-s-test", "type": "search_compare", "description": "d", "recorded_from": "dddddddddddd",
                         "search": {"a": "http://x/?q={query}"}, "expect_text": ["b"]}, {"query": "q", "must": ["a"]})


def test_non_recorded_dry_run_calls_execute_exactly_as_before(env, monkeypatch):
    seen = []
    monkeypatch.setattr(recipes, "execute", lambda recipe, params, allow_stateful=False: seen.append(allow_stateful) or {"status": "done", "rows": [["a"]]})
    plain = {k: v for k, v in form_recipe().items() if k != "recorded_from"}
    out = recipes.dry_run(plain, DEMO, allow_stateful=True)
    assert out["passed"] is True and seen == [True] and "demo" not in out
    rec = json.loads((env / "dry" / f"{out['dry_run_id']}.json").read_text())
    assert "sig" not in rec and "isolated" not in rec


def passing_pair(env, monkeypatch, recipe=None, with_second=True):
    r = recipe or form_recipe()
    a = dry(monkeypatch, r, DEMO, run_result())
    b = dry(monkeypatch, r, OTHER, run_result(match=None)) if with_second else None
    return r, a, b


def save_err(recipe, dry_id, match):
    with pytest.raises(recipes.RecipeError, match=re.escape(match)) as e:
        recipes.save(recipe, dry_id)
    return str(e.value)


def test_save_accepts_a_recorded_recipe_with_all_evidence(env, monkeypatch):
    put_recording(env)
    r, a, b = passing_pair(env, monkeypatch)
    for did in (a["dry_run_id"], b["dry_run_id"]):
        assert recipes.save(r, did).endswith("recorded-x-test.json")
    saved = json.loads((env / "user" / "recorded-x-test.json").read_text())
    assert saved["recorded_from"] == RID and saved["status"] == "verified"


def test_save_refuses_without_a_demo_value_run_that_matched(env, monkeypatch):
    put_recording(env)
    r = form_recipe()
    # (a) only a second-parameter run exists
    b = dry(monkeypatch, r, OTHER, run_result(match=None))
    assert "(a)" in save_err(r, b["dry_run_id"], "(a)")
    # a demo run whose comparison did not match never counts (the failed run itself is refused first)
    bad = dry(monkeypatch, r, DEMO, run_result(match=False))
    with pytest.raises(recipes.RecipeError, match="did not pass"):
        recipes.save(r, bad["dry_run_id"])
    assert "(a)" in save_err(r, b["dry_run_id"], "(a)")


def test_save_with_params_needs_a_second_run_with_different_actions_and_without_params_only_the_demo_run(env, monkeypatch):
    put_recording(env)
    r = form_recipe()
    a = dry(monkeypatch, r, DEMO, run_result())
    assert "(b)" in save_err(r, a["dry_run_id"], "(b)")                         # with params the demo run alone is not enough
    same = dry(monkeypatch, r, {**DEMO, "unused": "changed"}, run_result())         # still the demo's actions: it is another demo run
    assert "(b)" in save_err(r, same["dry_run_id"], "(b)")                      # an unused parameter changed no action
    noparam = form_recipe(params={}, fields=[{"label": "城市", "kind": "select", "value": "Taichung"}, {"label": "姓名", "kind": "text", "value": "王小明"},
                                             {"label": "日期", "kind": "text", "value": "2026-10-05"}])
    a2 = dry(monkeypatch, noparam, {}, run_result())
    assert recipes.save(noparam, a2["dry_run_id"]).endswith(".json")            # (b) is not asked when the recipe has no params
    real = dry(monkeypatch, r, OTHER, run_result(match=None))
    assert recipes.save(r, a["dry_run_id"]).endswith(".json")                   # now the changed-actions run exists
    assert real["passed"]


def test_save_refuses_without_columns_and_when_the_second_run_is_not_isolated(env, monkeypatch):
    put_recording(env)
    r = form_recipe()
    r["result"]["rows"].pop("columns")
    a = dry(monkeypatch, r, DEMO, run_result())
    b = dry(monkeypatch, r, OTHER, run_result(match=None))
    assert "(c)" in save_err(r, a["dry_run_id"], "(c)")
    r = form_recipe()
    a = dry(monkeypatch, r, DEMO, run_result())
    b = dry(monkeypatch, r, OTHER, run_result(match=None, isolated=False))       # passed is False without isolation; the record shows it
    assert b["passed"] is False
    assert "(b)" in save_err(r, a["dry_run_id"], "(b)")


def test_save_refuses_forged_or_edited_dry_run_records(env, monkeypatch):
    put_recording(env)
    r, a, b = passing_pair(env, monkeypatch)
    p = env / "dry" / f"{a['dry_run_id']}.json"
    rec = json.loads(p.read_text())
    # someone edits a record after the fact (a run that was not isolated claiming to be)
    forged = dict(rec, isolated=False)
    p.write_text(json.dumps(forged))
    assert "(e)" in save_err(r, a["dry_run_id"], "(e)")
    # a hand-written record with no server signature at all
    p.write_text(json.dumps({k: v for k, v in rec.items() if k != "sig"}))
    assert "(e)" in save_err(r, a["dry_run_id"], "(e)")
    # a record whose signature was made for other content (a claimed match on a record that never matched)
    p.write_text(json.dumps(dict(rec, match=False, sig=rec["sig"])))
    assert "(e)" in save_err(r, a["dry_run_id"], "(e)")
    # a demo run honestly recorded as not isolated (signed by the server) is refused with the isolation reason
    p.write_text(json.dumps(rec))
    for f in (env / "dry").glob("*.json"):
        if f.stem != a["dry_run_id"]:
            f.unlink()
    honest = recipes._write_dry_run(r, DEMO, run_result(), True, {**{k: rec[k] for k in ("recorded_from", "recording_digest", "rendered_actions_hash", "demo_run", "comparator", "match", "diff")}, "isolated": False})
    p.unlink()
    assert "(e)" in save_err(r, honest["dry_run_id"], "(e)")


def test_save_refuses_a_missing_incomplete_edited_or_expired_recording(env, monkeypatch):
    put_recording(env)
    r, a, b = passing_pair(env, monkeypatch)
    d = env / "recordings" / RID
    # digest: the log is edited after the fact
    log = (d / "log.jsonl").read_text()
    (d / "log.jsonl").write_text(log.replace("車次", "別的"))
    assert "(d)" in save_err(r, a["dry_run_id"], "digest")
    (d / "log.jsonl").write_text(log)
    assert recipes.save(r, a["dry_run_id"])
    (env / "user" / "recorded-x-test.json").unlink()
    # not completed
    meta = json.loads((d / "meta.json").read_text())
    (d / "meta.json").write_text(json.dumps({**meta, "state": "incomplete"}))
    assert "(d)" in save_err(r, a["dry_run_id"], "completed")
    # expired
    (d / "meta.json").write_text(json.dumps({**meta, "finished": time.time() - 31 * 86400}))
    assert "(d)" in save_err(r, a["dry_run_id"], "保存期限")
    # gone
    shutil.rmtree(d)
    assert "(d)" in save_err(r, a["dry_run_id"], "找不到錄製")


def test_two_recipes_cannot_borrow_one_demonstration(env, monkeypatch):
    put_recording(env)
    r, a, b = passing_pair(env, monkeypatch)
    recipes.save(r, a["dry_run_id"])
    second = form_recipe(name="recorded-second-test")
    a2 = dry(monkeypatch, second, DEMO, run_result())
    b2 = dry(monkeypatch, second, OTHER, run_result(match=None))
    msg = save_err(second, a2["dry_run_id"], "一份示範只能對應一份流程")
    assert "recorded-x-test" in msg
    # the same recipe name re-saved (a repair with the same recording) is fine
    assert recipes.save(r, b["dry_run_id"])


def test_run_recipe_never_reads_the_recordings_directory(env, monkeypatch):
    put_recording(env)
    r, a, b = passing_pair(env, monkeypatch)
    recipes.save(r, a["dry_run_id"])
    shutil.rmtree(env / "recordings")                                       # the demonstration is gone (expired / cleaned)
    monkeypatch.setattr(record, "read_recording", lambda *a_, **k: pytest.fail("run_recipe must not read a recording"))
    calls = []
    monkeypatch.setattr(recipes, "Judge", lambda url: type("J", (), {"usage": lambda self: {}})())
    monkeypatch.setattr(recipes, "ensure_chrome", lambda: None)
    monkeypatch.setattr(recipes, "Browser", lambda url: type("B", (), {"close": lambda self: None, "send": lambda self, *a_, **k: {}})())
    monkeypatch.setattr(recipes, "run_form_submit", lambda *a_, **k: calls.append(k) or {"status": "done", "rows": [["a"]]})
    out = REAL_EXECUTE(recipes.get("recorded-x-test"), DEMO)
    assert out["status"] == "done" and out["isolated"] is False and calls and calls[0].get("browser_context_id") is None and calls[0].get("demo") is None


def test_read_recording_only_serves_completed_intact_unexpired_recordings(env):
    put_recording(env)
    got = record.read_recording(RID)
    assert got["ok"] and got["draft"]["draft"]["type"] == "form_submit" and got["mark"]["group"]["total"] == 3
    assert record.read_recording("nothex")["ok"] is False and record.read_recording("../../etc/passwd")["ok"] is False
    assert record.read_recording("ffffffffffff")["ok"] is False


# ---------- stop: compare_to and draft in the result ----------

def test_manager_stop_diffs_a_stored_result_against_a_recipe(env, monkeypatch):
    put_recording(env)
    d = env / "recordings" / RID
    res = {"recording_id": RID, "state": "completed", "warnings": []}
    record.apply_draft(res, draft.to_draft(record.read_log(d), record.read_snapshots(d), None, recording_id=RID))
    (d / "result.json").write_text(json.dumps(res, ensure_ascii=False))
    (env / "user").mkdir()
    old = {k: v for k, v in form_recipe().items() if k != "recorded_from"}
    old["fields"] = [{"label": "城市", "kind": "select", "value": "Taipei"}, *old["fields"][1:]]
    (env / "user" / "recorded-x-test.json").write_text(json.dumps(old))
    m = record.Manager(home=env)
    out = m.stop(RID, compare_to="recorded-x-test")
    assert out["draft"]["type"] == "form_submit" and out["diff"]["recipe"] == "recorded-x-test"
    assert any(c["kind"] == "field_value" and c["label"] == "城市" for c in out["diff"]["changes"])
    missing = m.stop(RID, compare_to="no-such-recipe")
    assert missing["diff"]["error"] and any("compare_to" in w for w in missing["warnings"])
    assert "diff" not in m.stop(RID)                                           # the stored result itself never carries a diff
    assert len(json.dumps(m.stop(RID), ensure_ascii=False)) < 9000
