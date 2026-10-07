"""WP0b Chrome integration: old-vs-new observation equivalence, groups/fingerprints, sensitive fields,
and the engine's ambiguity handling against fixture pages. Run with KFW_CHROME_TESTS=1 (isolated :9444 Chrome)."""

import json

import pytest

from kfw import form, recipes
from legacy_observe import OLD_CONTROLS_JS, OLD_ROWS_JS

pytestmark = pytest.mark.chrome

NEW_KEYS = {"name", "autocomplete", "form_id", "form_has_sensitive", "sensitive", "has_value", "native"}
PAGES = ["table_empty_cells.html", "nested_list.html", "duplicate_labels.html", "sensitive_form.html",
         "optional_buttons.html", "replace_dom.html", "two_tables.html", "one_table.html", "result_form.html"]
NO_CONTROLS = {"table_empty_cells.html", "nested_list.html", "two_tables.html", "one_table.html"}
ROW_QUERIES = [(r"\d{2}:\d{2}", 1), (r"\d{2}:\d{2}", 2), (r"\d{4}", 1), (r".", 1), (r"zzz-no-match", 1),
               (r"\d", 3), (r"Apple|Kale|Rice", 1)]


def project_old(c):
    """A new-shape control reduced to what the old observer returned."""
    return {k: v for k, v in c.items() if k not in NEW_KEYS}


@pytest.mark.parametrize("page", PAGES)
def test_controls_equivalent_to_pre_wp0b(load, page):
    tab = load(page)
    old = tab.evaluate(OLD_CONTROLS_JS)
    new = form.controls(tab)
    assert len(old) == len(new)
    assert bool(old) == (page not in NO_CONTROLS)
    for o, n in zip(old, new):
        assert NEW_KEYS <= set(n)
        if n["sensitive"]:  # the one deliberate difference: a sensitive value is never read
            assert n["value"] == "" and {**o, "value": ""} == project_old(n)
        else:
            assert o == project_old(n)


@pytest.mark.parametrize("page", PAGES)
def test_rows_equivalent_to_pre_wp0b(load, page):
    tab = load(page)
    for pattern, min_rows in ROW_QUERIES:
        old = tab.evaluate(f"{OLD_ROWS_JS}({json.dumps(pattern)}, {min_rows})")
        assert form.rows(tab, pattern, min_rows) == old, (page, pattern, min_rows)
        assert form.rows_detail(tab, pattern, min_rows)["rows"] == old, (page, pattern, min_rows)


def test_replaced_dom_invalidates_old_control_and_stays_equivalent(load):
    tab = load("replace_dom.html")
    old_ctrl = next(c for c in form.controls(tab) if c["label"] == "名稱")
    assert tab.evaluate(f"document.querySelector('[data-kfw-id=\"{old_ctrl['id']}\"]').value") == "old"
    swap = next(c for c in form.controls(tab) if c["label"] == "重繪")
    assert form.click(tab, swap["id"])["ok"]
    assert form.fill(tab, old_ctrl["id"], "zzz") == {"ok": False, "why": "gone"}
    old = tab.evaluate(OLD_CONTROLS_JS)
    new = form.controls(tab)
    assert [project_old(c) for c in new] == old
    fresh = next(c for c in new if c["label"] == "名稱")
    assert fresh["id"] != old_ctrl["id"] and fresh["value"] == "new"


def test_snapshot_new_fields(load):
    tab = load("sensitive_form.html")
    ctrls = {c["label"]: c for c in form.controls(tab)}
    for label in ("密碼", "卡號", "驗證碼", "新密碼"):
        assert ctrls[label]["sensitive"] is True and ctrls[label]["value"] == ""
    assert ctrls["密碼"]["has_value"] is True and ctrls["驗證碼"]["has_value"] is False
    assert ctrls["卡號"]["autocomplete"] == "cc-number" and ctrls["密碼"]["name"] == "pw"
    assert ctrls["帳號"]["sensitive"] is False and ctrls["帳號"]["value"] == "kai"
    assert ctrls["暱稱"]["sensitive"] is False and ctrls["暱稱"]["value"] == "K"
    assert "s3cret-pw" not in json.dumps(form.controls(tab)) and "4111" not in json.dumps(form.controls(tab))
    login = ctrls["繼續"]["form_id"]
    assert login and ctrls["繼續"]["form_has_sensitive"] is True
    # form= attribute association: buttons/inputs outside the <form> element still belong to it
    assert ctrls["外置送出"]["form_id"] == login and ctrls["外置送出"]["form_has_sensitive"] is True
    assert ctrls["外部欄位"]["form_id"] == login
    assert ctrls["搜尋"]["form_id"] not in (None, login) and ctrls["搜尋"]["form_has_sensitive"] is False
    assert ctrls["無 form 按鈕"]["form_id"] is None and ctrls["無 form 按鈕"]["form_has_sensitive"] is False
    assert all(c["native"] for c in ctrls.values() if c["kind"] in ("text", "select", "checkbox"))
    assert ctrls["繼續"]["native"] is False  # native = select/input/textarea only
    tab2 = load("duplicate_labels.html")
    div = next(c for c in form.controls(tab2) if c["label"] == "x")  # a button's label is its text, as before
    assert div["native"] is False and div["kind"] == "button"


def test_groups_all_qualifying_marked_in_dom(load):
    tab = load("two_tables.html")
    gs = form.groups(tab, r"\d{2}:\d{2}", min_rows=2)
    tr_groups = [g for g in gs if g["total"] == 3]
    assert len(tr_groups) == 2
    assert tr_groups[0]["fingerprint"] != tr_groups[1]["fingerprint"]
    g = tr_groups[0]
    assert g["rows"][0]["cells"] == ["0101", "08:00"] and g["rows"][0]["text"] == "0101 08:00" and g["rows"][0]["controls"] == []
    marked = tab.evaluate(f"document.querySelectorAll('[data-kfw-group=\"{g['group_id']}\"][data-kfw-row]').length")
    assert marked == 3
    assert tab.evaluate(f"document.querySelector('[data-kfw-row=\"{g['rows'][1]['row_id']}\"]').innerText").strip().startswith("0103")
    # groups() with no pattern: every repeating group (needs >= 2 rows by default)
    assert len(form.groups(tab)) >= len(gs)


def test_group_fingerprint_is_content_not_dom_ids(load):
    tab = load("two_tables.html")
    a = form.groups(tab, r"\d{2}:\d{2}", min_rows=2)
    b = form.groups(tab, r"\d{2}:\d{2}", min_rows=2)  # new group/row ids, same content
    assert [g["group_id"] for g in a] != [g["group_id"] for g in b]
    assert [g["fingerprint"] for g in a] == [g["fingerprint"] for g in b]
    tab.evaluate("document.querySelectorAll('tbody')[0].rows[0].cells[0].textContent = '9999'")
    c = form.groups(tab, r"\d{2}:\d{2}", min_rows=2)
    assert [g["fingerprint"] for g in c] != [g["fingerprint"] for g in a]


def test_groups_row_controls_use_snapshot_rule(load, chrome):
    tab = load("sensitive_form.html")
    gs = form.groups(tab, None, min_rows=2, root="body")
    assert isinstance(gs, list)
    tab.evaluate("""document.body.insertAdjacentHTML('beforeend',
      '<ul id=L><li><input value=a> x1</li><li><input type=password value=p> x2</li></ul>')""")
    g = next(g for g in form.groups(tab, "x", min_rows=2) if g["total"] == 2)
    inputs = [r["controls"][0] for r in g["rows"]]
    assert inputs[0]["value"] == "a" and inputs[1]["sensitive"] is True and inputs[1]["value"] == ""


def test_rows_detail_reports_other_qualifying_groups(load):
    tab = load("two_tables.html")
    d = form.rows_detail(tab, r"\d{2}:\d{2}", 1)
    assert d["other_qualifying_groups"] == 1 and len(d["rows"]) == 3 and d["group_fingerprint"]
    tab = load("one_table.html")
    d = form.rows_detail(tab, r"\d{2}:\d{2}", 1)
    assert d["other_qualifying_groups"] == 0 and len(d["rows"]) == 3
    tab = load("nested_list.html")  # groups at other nesting levels are the same list, not a rival
    d = form.rows_detail(tab, r"\d{2}:\d{2}", 1)
    assert d["other_qualifying_groups"] == 0 and len(d["rows"]) == 3
    assert form.rows_detail(tab, "zzz-none", 1) == {"rows": [], "group_fingerprint": None, "other_qualifying_groups": 0, "rows_skipped": 0}


def test_rows_detail_and_pick_groups_count_the_rows_the_pattern_skipped(load):
    """A too-narrow pattern drops sibling rows silently: 591's integer-坪 / `\\dF/\\dF` pattern missed 3.5坪 and B1 cards.
    The chosen group reports how many same-signature siblings did not match, so Claude can see its pattern is too narrow."""
    tab = load("rows_skipped.html")
    narrow = form.rows_detail(tab, r"雅房\d+坪\d+F/\d+F", 1)
    assert len(narrow["rows"]) == 3 and narrow["rows_skipped"] == 2 and narrow["other_qualifying_groups"] == 0
    wide = form.rows_detail(tab, r"元/月", 1)
    assert len(wide["rows"]) == 5 and wide["rows_skipped"] == 0
    g = form.pick_groups(tab, r"雅房\d+坪\d+F/\d+F", 1)["groups"]
    assert len(g) == 1 and g[0]["total"] == 3 and g[0]["skipped"] == 2


def test_table_with_empty_cells_rows_shape(load):
    tab = load("table_empty_cells.html")
    got = form.rows(tab, r"\d", 1)
    assert got[0] == ["0101", "08:00"]  # empty cells vanish, exactly as before
    assert form.rows(tab, r"\d", 1) == tab.evaluate(f"{OLD_ROWS_JS}({json.dumps(chr(92) + 'd')}, 1)")


# ---------- engines on fixture pages ----------

def _form_recipe(chrome, pre=None, pattern=r"\d{2}:\d{2}", min_rows=2):
    return {"name": "wp0b-fixture", "type": "form_submit", "description": "fixture", "url": chrome.url("result_form.html"),
            "pre": pre or [], "fields": [{"label": "城市", "kind": "text", "value": "台北"}],
            "submit": {"click": "查詢"}, "result": {"rows": {"pattern": pattern, "min_rows": min_rows}}}


def test_engine_form_submit_two_tables_is_result_ambiguous(chrome):
    out = recipes.execute(_form_recipe(chrome), {})
    assert out["status"] == "needs_help" and out["reason"] == "result_ambiguous", out
    assert "2 張表" in out["hint"]


def test_engine_form_submit_specific_pattern_is_done(chrome):
    out = recipes.execute(_form_recipe(chrome, pattern=r"^A\d", min_rows=3), {})
    assert out["status"] == "done" and len(out["rows"]) == 3 and out["rows"][0][0] == "A1", out


def test_engine_detail_extract_ambiguity(chrome):
    d = {"name": "wp0b-detail", "type": "detail_extract", "description": "x", "url": chrome.url("two_tables.html"),
         "rows": {"pattern": r"\d{2}:\d{2}", "min_rows": 1}}
    out = recipes.execute(d, {})
    assert out["status"] == "needs_help" and out["reason"] == "result_ambiguous", out
    d["url"] = chrome.url("one_table.html")
    out = recipes.execute(d, {})
    assert out["status"] == "done" and len(out["rows"]) == 3, out


def test_engine_optional_pre_semantics_on_real_page(chrome):
    # the page has two "同意"?  No: optional_buttons.html does; result_form has none. Use both pages.
    out = recipes.execute(_form_recipe(chrome, pre=[{"click": "不存在的按鈕", "optional": True}], pattern=r"^A\d", min_rows=3), {})
    assert out["status"] == "done" and any("skipped" in s for s in out["steps"]), out
    r = {**_form_recipe(chrome), "url": chrome.url("optional_buttons.html"), "pre": [{"click": "同意", "optional": True}]}
    out = recipes.execute(r, {})
    assert out["status"] == "needs_help" and out["reason"] == "pre_step_failed" and out["why"] == "ambiguous", out
