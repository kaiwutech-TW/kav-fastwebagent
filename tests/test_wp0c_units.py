"""WP0c unit tests (no Chrome): rules, matching, gate branches, validate, allow_stateful plumbing."""

import json

import pytest

from kfw import form, recipes, safety
from safety_samples import FIELD_SAMPLES, TEXT_SAMPLES


def node(text="查詢", **kw):
    return {"ok": True, "tag": "BUTTON", "type": "submit", "text": text, "aria_label": "", "label": text, "name": "",
            "autocomplete": "", "sensitive": False, "form_has_sensitive": False, **kw}


def gate(action, target, url="http://x/", *, stateful_step=False, allow_stateful=False):
    return safety.gate(action, target, url, stateful_step=stateful_step, allow_stateful=allow_stateful)


# ---------- rules ----------

def test_rules_file_is_the_single_source():
    r = json.loads((safety.Path(safety.__file__).parent / "safety_rules.json").read_text(encoding="utf-8"))
    for k in ("forbidden_click", "stateful_click", "sensitive_label"):
        assert set(r[k]) == {"zh", "en"} and r[k]["zh"] and r[k]["en"]
    assert "付款" in r["forbidden_click"]["zh"] and "checkout" in r["forbidden_click"]["en"]
    assert "加入購物車" in r["stateful_click"]["zh"] and "add to cart" in r["stateful_click"]["en"]
    assert set(r["sensitive_autocomplete"]) >= {"cc-*", "one-time-code", "current-password", "new-password"}
    assert r["sensitive_input_types"] == ["password"] and "/checkout" in r["checkout_url_parts"]
    js = safety.js_rules()  # what the JS gets: the same lists, not a second hand-written copy
    assert js["forbidden_click"]["zh"] == safety.FORBIDDEN.zh and len(js["stateful_click"]["en"]) == len(r["stateful_click"]["en"])
    assert "KFW_RULES" in form.OBSERVE_JS and "SENSITIVE_TYPES" not in form.OBSERVE_JS


@pytest.mark.parametrize("text,forbidden,stateful,label", TEXT_SAMPLES)
def test_python_matching(text, forbidden, stateful, label):
    assert safety.text_flags(text) == {"forbidden": forbidden, "stateful": stateful, "sensitive_label": label}


def test_at_least_30_consistency_samples():
    assert len(TEXT_SAMPLES) + len(FIELD_SAMPLES) >= 30


def test_named_boundaries():
    assert safety.FORBIDDEN.hit("Pay now") == "pay"
    assert safety.FORBIDDEN.hit("payment history") is None
    assert safety.FORBIDDEN.hit("PayPal") is None
    assert safety.FORBIDDEN.hit("Place  order") == "place order"
    assert safety.FORBIDDEN.hit("登入") == "登入" and safety.STATEFUL.hit("加入購物車") == "加入購物車"


@pytest.mark.parametrize("tag,typ,ac,label,expected", FIELD_SAMPLES)
def test_python_sensitive_field(tag, typ, ac, label, expected):
    assert safety.sensitive_field(tag, typ, ac, label) is expected


# ---------- gate ----------

def test_gate_allows_ordinary_click_and_field():
    assert gate("click", node("查詢")) is None
    assert gate("click", node("下一頁")) is None
    assert gate("fill", node("關鍵字", tag="INPUT", type="text")) is None
    assert gate("select", node("出發站", tag="SELECT", type="select-one")) is None
    assert gate("click", node("payment history")) is None


@pytest.mark.parametrize("action", ["fill", "select", "check"])
def test_gate_refuses_sensitive_fields(action):
    d = gate(action, node("密碼", tag="INPUT", type="password", sensitive=True))
    assert d and d["reason"] == "unsafe_action" and "敏感欄位" in d["hint"]
    # the gate also recomputes from the raw attributes, not only the JS `sensitive` flag
    d = gate(action, node("x", tag="INPUT", type="text", autocomplete="cc-number"))
    assert d and d["reason"] == "unsafe_action"
    d = gate(action, node("Card number", tag="INPUT", type="text"))
    assert d and d["reason"] == "unsafe_action"


@pytest.mark.parametrize("action", ["click", "next_page", "pick"])
def test_gate_click_branches(action):
    d = gate(action, node("立即購買"))
    assert d and d["reason"] == "unsafe_action" and "禁止詞" in d["hint"]
    d = gate(action, node("Pay now"))
    assert d and d["reason"] == "unsafe_action"
    d = gate(action, node("繼續", form_has_sensitive=True))
    assert d and d["reason"] == "unsafe_action" and "敏感欄位" in d["hint"]
    d = gate(action, node("", aria_label=""))
    assert d and d["reason"] == "unsafe_action" and "aria-label" in d["hint"]
    d = gate(action, node("", aria_label=""), "https://shop.test/checkout/step2")
    assert d and d["reason"] == "unsafe_action" and "結帳類網址" in d["hint"]
    assert gate(action, node("", aria_label="關閉")) is None  # aria-label is enough to judge
    d = gate(action, node("", aria_label="Login"))  # the forbidden word may sit in aria-label
    assert d and d["reason"] == "unsafe_action"
    d = gate(action, {"ok": False, "why": "gone"})
    assert d and d["reason"] == "unsafe_action" and "gone" in d["hint"]
    assert gate(action, None)["reason"] == "unsafe_action"
    assert gate("teleport", node())["reason"] == "unsafe_action"


def test_gate_stateful_needs_step_mark_and_authorization():
    cart = node("加入購物車")
    # a form_submit-style call: never a stateful step, so refused even when the caller authorized
    for allow in (False, True):
        d = gate("click", cart, stateful_step=False, allow_stateful=allow)
        assert d and d["reason"] == "stateful_not_authorized" and "加入購物車" in d["hint"]
    d = gate("click", cart, stateful_step=True, allow_stateful=False)
    assert d and d["reason"] == "stateful_not_authorized" and "allow_stateful" in d["hint"]
    assert gate("click", cart, stateful_step=True, allow_stateful=True) is None
    # I7: a step marked stateful is restricted even when its text is not in the vocabulary
    assert gate("click", node("送出"), stateful_step=True, allow_stateful=False)["reason"] == "stateful_not_authorized"
    assert gate("click", node("送出"), stateful_step=True, allow_stateful=True) is None
    # authorization never lifts the forbidden list or the sensitive form rule
    assert gate("click", node("付款"), stateful_step=True, allow_stateful=True)["reason"] == "unsafe_action"
    assert gate("click", node("加入購物車", form_has_sensitive=True), stateful_step=True, allow_stateful=True)["reason"] == "unsafe_action"
    assert gate("fill", node("密碼", tag="INPUT", type="password", sensitive=True), stateful_step=True, allow_stateful=True)


# ---------- validate / allow_stateful plumbing ----------

def _fs(**over):
    r = {"name": "gate-test", "type": "form_submit", "description": "x", "url": "http://x/", "pre": [],
         "fields": [], "submit": {"click": "查詢"}, "result": {"expect_text": ["a"]}}
    r.update(over)
    return r


def test_validate_refuses_stateful_on_form_submit():
    recipes.validate(_fs())
    with pytest.raises(recipes.RecipeError, match="stateful"):
        recipes.validate(_fs(submit={"click": "加入購物車", "stateful": True}))
    with pytest.raises(recipes.RecipeError, match="stateful"):
        recipes.validate(_fs(pre=[{"click": "加入購物車", "stateful": True}]))
    with pytest.raises(recipes.RecipeError, match="stateful"):
        recipes.validate(_fs(pre=[{"click": "x", "stateful": False}]))  # even a false mark: the field does not exist here


def test_allow_stateful_defaults_false_and_is_forwarded(monkeypatch):
    import inspect
    for fn in (recipes.execute, recipes.dry_run):
        assert inspect.signature(fn).parameters["allow_stateful"].default is False
    seen = []
    monkeypatch.setattr(recipes, "execute", lambda recipe, params, allow_stateful=False: seen.append(allow_stateful) or {"status": "needs_help"})
    monkeypatch.setattr(recipes, "DRYRUNS", recipes.Path("/nonexistent-kfw-dryruns"))
    monkeypatch.setattr(recipes.Path, "mkdir", lambda *a, **k: None)
    monkeypatch.setattr(recipes.Path, "write_text", lambda *a, **k: None)
    recipes.dry_run(_fs(), {})
    recipes.dry_run(_fs(), {}, allow_stateful=True)
    assert seen == [False, True]


def test_mcp_tools_take_allow_stateful():
    import inspect
    from kfw import mcp_server
    for fn in (mcp_server.run_recipe, mcp_server.dry_run):
        p = inspect.signature(fn).parameters["allow_stateful"]
        assert p.default is False and p.annotation is bool
        assert "this call only" in fn.__doc__ or "本次" in fn.__doc__ or "call only" in fn.__doc__


class _Tab:
    def __init__(self):
        self.calls = []

    def evaluate(self, js):
        return "http://x/"


def test_form_submit_never_passes_stateful_even_with_allow_stateful(monkeypatch):
    """The engine path: a 加入購物車 submit is refused with allow_stateful False and with True (I7)."""
    ctrls = [{"id": "k1", "label": "加入購物車", "kind": "button"}]
    monkeypatch.setattr(form, "controls", lambda tab: ctrls)
    monkeypatch.setattr(form, "settle_controls", lambda tab: (ctrls, {"ok": True, "ms": 0}))
    monkeypatch.setattr(form, "describe", lambda tab, cid: node("加入購物車"))
    dispatched = []
    monkeypatch.setattr(form, "click", lambda tab, cid: dispatched.append(cid) or {"ok": True, "_href": "h", "_at": 0.0})
    monkeypatch.setattr(form, "fill", lambda *a: dispatched.append("fill") or {"ok": True})
    monkeypatch.setattr(recipes.time, "sleep", lambda s: None)

    class T(_Tab):
        def navigate(self, url):
            pass

        def wait_ready(self, **kw):
            return type("R", (), {"reason": "settled", "ms": 1, "inflight": 0})()

    r = {"url": "http://x/", "pre": [], "fields": [], "submit": {"click": "加入購物車"}}
    for allow in (False, True):
        out = recipes._fill_and_submit(T(), r, None, [], allow)
        assert out["status"] == "needs_help" and out["reason"] == "stateful_not_authorized", out
    assert dispatched == []
