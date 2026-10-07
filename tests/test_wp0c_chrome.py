"""WP0c Chrome integration: Python/JS rule consistency and the gate on the real form_submit path.
Run with KFW_CHROME_TESTS=1 (isolated :9444 Chrome). Fixture pages count every pointerdown/mousedown/click/keydown/
input/beforeinput they receive (capture phase, into localStorage) so a refused run can be shown to touch nothing."""

import json

import pytest

from kfw import form, recipes, safety
from safety_samples import FIELD_SAMPLES, TEXT_SAMPLES

pytestmark = pytest.mark.chrome


# ---------- Python == JS ----------

def test_text_rules_python_and_js_agree(load):
    tab = load("one_table.html")
    assert len(TEXT_SAMPLES) + len(FIELD_SAMPLES) >= 30
    for text, forbidden, stateful, label in TEXT_SAMPLES:
        js = tab.evaluate(f"{form.CLASSIFY_JS}({json.dumps(text)})")
        assert js == safety.text_flags(text), (text, js)
        assert js == {"forbidden": forbidden, "stateful": stateful, "sensitive_label": label}, (text, js)


def test_field_rules_python_and_js_agree(load):
    tab = load("one_table.html")
    for tag, typ, ac, label, expected in FIELD_SAMPLES:
        js = tab.evaluate(f"{form.SENSITIVE_FOR_JS}({json.dumps(tag)}, {json.dumps(typ)}, {json.dumps(ac)}, {json.dumps(label)})")
        assert js is safety.sensitive_field(tag, typ, ac, label) is expected, (tag, typ, ac, label, js)


def test_rules_injected_into_js_are_the_json_file(load):
    tab = load("one_table.html")
    got = tab.evaluate(f"(() => {{ {form.OBSERVE_JS}\n return KFW_RULES; }})()")
    assert got == json.loads(json.dumps(safety.js_rules()))


# ---------- helpers ----------

def counts(load):
    tab = load("gate_query.html")
    return json.loads(tab.evaluate("localStorage.getItem('kfw_ev') || '{}'"))


def clear_counts(load):
    load("gate_query.html").evaluate("localStorage.removeItem('kfw_ev')")


def recipe(chrome, page, *, fields=None, pre=None, submit="查詢", rows=True):
    return {"name": "wp0c-fixture", "type": "form_submit", "description": "fixture", "url": chrome.url(page),
            "pre": pre or [], "fields": fields if fields is not None else [], "submit": {"click": submit},
            "result": {"rows": {"pattern": r"\d{2}:\d{2}", "min_rows": 2}} if rows else {"expect_text": ["zzz"]}}


KW = [{"label": "關鍵字", "kind": "text", "value": "abc"}]


# ---------- the engine path ----------

def test_ordinary_query_form_is_done_and_counters_see_events(chrome, load):
    clear_counts(load)
    out = recipes.execute(recipe(chrome, "gate_query.html", fields=KW), {})
    assert out["status"] == "done" and len(out["rows"]) == 3, out
    c = counts(load)
    assert c.get("click", 0) >= 1 and c.get("pointerdown", 0) >= 1 and c.get("input", 0) >= 1, c  # counters do work


REFUSED = [
    # (page, recipe kwargs, expected reason, hint fragment)
    ("gate_continue_pwd.html", dict(fields=KW, submit="繼續"), "unsafe_action", "敏感欄位"),  # innocent text, password in its form
    ("gate_external_button.html", dict(fields=KW, submit="繼續"), "unsafe_action", "敏感欄位"),  # form="acct" association
    ("gate_password_field.html", dict(fields=[{"label": "密碼", "kind": "text", "value": "x"}]), "unsafe_action", "敏感欄位"),
    ("gate_add_cart.html", dict(fields=KW, submit="加入購物車"), "stateful_not_authorized", "加入購物車"),
    ("gate_pre_login.html", dict(fields=KW, pre=[{"click": "登入"}]), "unsafe_action", "登入"),
    ("gate_pre_login.html", dict(fields=KW, pre=[{"click": "登入", "optional": True}]), "unsafe_action", "登入"),  # optional never skips a refusal
]


@pytest.mark.parametrize("page,kw,reason,frag", REFUSED)
@pytest.mark.parametrize("allow", [False, True])
def test_refused_runs_dispatch_no_input_events(chrome, load, page, kw, reason, frag, allow):
    clear_counts(load)
    out = recipes.execute(recipe(chrome, page, **kw), {}, allow_stateful=allow)
    assert out["status"] == "needs_help" and out["reason"] == reason, out
    assert frag in out["hint"], out["hint"]
    assert counts(load) == {}, counts(load)  # not a single pointerdown/mousedown/click/keydown/input/beforeinput


def test_refusal_reports_which_action_and_target(chrome, load):
    clear_counts(load)
    out = recipes.execute(recipe(chrome, "gate_add_cart.html", fields=KW, submit="加入購物車"), {})
    assert out["action"] == "click" and out["target"] == "加入購物車"


def test_node_changed_after_snapshot_is_judged_on_the_fresh_read(chrome, load, monkeypatch):
    """The gate must not trust the earlier snapshot: the label says 查詢, the node now says 付款 when the gate reads it."""
    clear_counts(load)
    real, n = form.describe, {"i": 0}

    def flip(tab, cid):
        n["i"] += 1
        if n["i"] >= 2:  # call 1 is the preflight; call 2 is the dispatch-time read
            tab.evaluate("document.getElementById('go').textContent = '付款'")
        return real(tab, cid)
    monkeypatch.setattr(form, "describe", flip)
    out = recipes.execute(recipe(chrome, "gate_no_text.html", submit="查詢"), {})
    assert out["status"] == "needs_help" and out["reason"] == "unsafe_action" and "付款" in out["hint"], out
    assert n["i"] == 2 and counts(load) == {}


def test_button_that_lost_its_text_after_snapshot_is_refused(chrome, load, monkeypatch):
    clear_counts(load)
    real, n = form.describe, {"i": 0}

    def blank(tab, cid):
        n["i"] += 1
        if n["i"] >= 2:
            tab.evaluate("document.getElementById('go').textContent = ''")
        return real(tab, cid)
    monkeypatch.setattr(form, "describe", blank)
    out = recipes.execute(recipe(chrome, "gate_no_text.html", submit="查詢"), {})
    assert out["status"] == "needs_help" and out["reason"] == "unsafe_action" and "aria-label" in out["hint"], out
    assert counts(load) == {}


def test_describe_and_gate_on_real_nodes(load):
    tab = load("gate_no_text.html")
    tab.evaluate("document.querySelectorAll('button').forEach((b, i) => b.dataset.kfwId = 'b' + i)")
    ok = form.describe(tab, "b0")
    assert ok["text"] == "查詢" and ok["ok"] and safety.gate("click", ok, tab.evaluate("location.href"), stateful_step=False, allow_stateful=False) is None
    blank = form.describe(tab, "b1")
    assert blank["text"] == "" and blank["aria_label"] == ""
    d = safety.gate("click", blank, tab.evaluate("location.href"), stateful_step=False, allow_stateful=False)
    assert d and d["reason"] == "unsafe_action" and "aria-label" in d["hint"]
    aria = form.describe(tab, "b2")
    assert aria["aria_label"] == "關閉"
    assert safety.gate("click", aria, "http://x/", stateful_step=False, allow_stateful=False) is None
    gone = form.describe(tab, "nope")
    assert gone == {"ok": False, "why": "gone"}
    assert safety.gate("click", gone, "http://x/", stateful_step=False, allow_stateful=False)["reason"] == "unsafe_action"


def test_describe_never_returns_a_field_value(load):
    tab = load("sensitive_form.html")
    ctrls = {c["label"]: c for c in form.controls(tab)}
    d = form.describe(tab, ctrls["密碼"]["id"])
    assert d["sensitive"] is True and "s3cret-pw" not in json.dumps(d) and d["text"] == ""
    btn = form.describe(tab, ctrls["外置送出"]["id"])
    assert btn["form_has_sensitive"] is True and btn["text"] == "外置送出"
    assert form.describe(tab, ctrls["搜尋"]["id"])["form_has_sensitive"] is False


def test_label_based_sensitivity_in_snapshot(load):
    tab = load("gate_password_field.html")
    tab.evaluate("document.body.insertAdjacentHTML('beforeend', '<label>Card number <input name=n></label><label>暱稱 <input name=k></label>')")
    got = {c["label"]: c for c in form.controls(tab) if c["kind"] == "text"}
    assert got["Card number"]["sensitive"] is True and got["暱稱"]["sensitive"] is False and got["密碼"]["sensitive"] is True
