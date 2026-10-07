"""The shared safety entry: one vocabulary (safety_rules.json), one gate in front of every real action.

Design docs/design/demo-recording.md section 4. The gate refuses what is known to be forbidden and what it
cannot judge; it does NOT prove that an allowed action has no side effects (principle 3).

Matching (Python and the observation JS in form.py build the same matchers from the same JSON, and a Chrome
test feeds both the same strings):
  zh  normalized containment: NFKC, lowercase, spaces removed (judge.normalize), then `term in text`.
  en  lowercase; ASCII word boundaries kept; spaces inside a phrase match one or more whitespace.
      `Pay now` and `Place  order` hit; `payment history` and `PayPal` do not hit `pay`.
      Boundaries are explicit ASCII classes, not \\b, because \\b means different things in Python and JS.
"""

import json
import re
import unicodedata
from pathlib import Path

from .judge import normalize as _zh_norm

RULES = json.loads((Path(__file__).resolve().parent / "safety_rules.json").read_text(encoding="utf-8"))

CLICK_ACTIONS = ("click", "next_page", "pick")
FIELD_ACTIONS = ("fill", "select", "check")
_WS = r"[ \t\r\n]+"
_LEFT, _RIGHT = r"(?<![a-z0-9_])", r"(?![a-z0-9_])"
_TEXTLESS_INPUT_TYPES = ("checkbox", "radio", "button", "submit", "reset", "image", "hidden", "file", "range", "color")


def _en_pattern(term):
    words = term.lower().split()
    assert words and all(re.fullmatch(r"[a-z0-9]+", w) for w in words), f"english rule term must be [a-z0-9 ]: {term!r}"
    return _LEFT + _WS.join(words) + _RIGHT


class _Rule:
    def __init__(self, spec):
        self.zh = [_zh_norm(t) for t in spec["zh"]]
        self.en_src = [_en_pattern(t) for t in spec["en"]]
        self._en = [(t, re.compile(p)) for t, p in zip(spec["en"], self.en_src)]
        self._zh_raw = spec["zh"]

    def hit(self, text):
        """The rule term that matches `text`, or None."""
        z, e = _zh_norm(text), unicodedata.normalize("NFKC", text or "").lower()
        for raw, t in zip(self._zh_raw, self.zh):
            if t in z:
                return raw
        for raw, rx in self._en:
            if rx.search(e):
                return raw
        return None


FORBIDDEN = _Rule(RULES["forbidden_click"])
STATEFUL = _Rule(RULES["stateful_click"])
SENSITIVE_LABEL = _Rule(RULES["sensitive_label"])
_AC = RULES["sensitive_autocomplete"]
_TYPES = [t.lower() for t in RULES["sensitive_input_types"]]
_CHECKOUT = [p.lower() for p in RULES["checkout_url_parts"]]


def js_rules():
    """The rules as the JS constant KFW_RULES: normalized zh terms and ready-made en regex sources."""
    def rule(r):
        return {"zh": r.zh, "en": r.en_src}
    return {"forbidden_click": rule(FORBIDDEN), "stateful_click": rule(STATEFUL), "sensitive_label": rule(SENSITIVE_LABEL),
            "sensitive_autocomplete": _AC, "sensitive_input_types": _TYPES}


def autocomplete_sensitive(value):
    for tok in re.split(_WS, (value or "").lower()):
        if not tok:
            continue
        for p in _AC:
            if p.endswith("*"):
                if len(tok) > len(p) - 1 and tok.startswith(p[:-1]):
                    return True
            elif tok == p:
                return True
    return False


def sensitive_field(tag, input_type, autocomplete, label):
    """Is this a field whose value must never be read or written? `label` may be a string or a callable."""
    if tag.upper() not in ("INPUT", "TEXTAREA"):
        return False
    t = (input_type or "").lower()
    if t in _TYPES or autocomplete_sensitive(autocomplete):
        return True
    if t in _TEXTLESS_INPUT_TYPES:
        return False
    return SENSITIVE_LABEL.hit(label() if callable(label) else label) is not None


def text_flags(text):
    """What the vocabulary says about one string; the Python/JS consistency test compares this with O.classify."""
    return {"forbidden": FORBIDDEN.hit(text) is not None, "stateful": STATEFUL.hit(text) is not None,
            "sensitive_label": SENSITIVE_LABEL.hit(text) is not None}


def checkout_url(url):
    u = (url or "").lower()
    return any(p in u for p in _CHECKOUT)


def _deny(hint, reason="unsafe_action"):
    return {"reason": reason, "hint": hint}


def gate(action, target, page_url, *, stateful_step, allow_stateful):
    """None = allowed; otherwise {"reason", "hint"} (the engine turns it into needs_help before any input).

    target: node info read just before the action (form.describe): text, aria_label, type, autocomplete, name,
    label, sensitive, form_has_sensitive. stateful_step: the recipe marked this step stateful (form_submit
    steps never can). allow_stateful: the caller of this run said the user asked for the state change (I7)."""
    if action not in CLICK_ACTIONS + FIELD_ACTIONS:
        return _deny(f"未知的動作 {action!r},程式無法判定,拒絕")
    if not isinstance(target, dict) or not target.get("ok", True):
        why = target.get("why") if isinstance(target, dict) else None
        return _deny(f"讀不到動作目標的節點資訊({why or 'unreadable'}),無法判定是否安全,拒絕")
    if action in FIELD_ACTIONS:
        label = target.get("label") or target.get("text") or ""
        if target.get("sensitive") or sensitive_field(target.get("tag") or "INPUT", target.get("type"),
                                                      target.get("autocomplete"), label):
            return _deny(f"欄位「{label}」是敏感欄位(密碼、卡號、驗證碼等),Kav 永遠不填寫、不選取")
        return None
    text, aria = target.get("text") or "", target.get("aria_label") or ""
    if not text.strip() and not aria.strip():
        if checkout_url(page_url):
            return _deny(f"結帳類網址上的無文字按鈕({page_url}),永遠拒絕")
        return _deny("按鈕沒有文字也沒有 aria-label,無法判定它做什麼,拒絕")
    shown = text or aria
    for s in (text, aria):
        term = FORBIDDEN.hit(s)
        if term:
            return _deny(f"按鈕「{shown}」命中禁止詞「{term}」(付款、結帳、下單、登入、註冊等永遠不由 Kav 執行)")
    if target.get("form_has_sensitive"):
        return _deny(f"按鈕「{shown}」所屬的表單含有敏感欄位(密碼、卡號等),Kav 不送出這種表單")
    term = next((t for t in (STATEFUL.hit(text), STATEFUL.hit(aria)) if t), None)
    if term or stateful_step:
        if stateful_step and allow_stateful:  # both are required: the step is marked AND this call is authorized
            return None
        why = (f"按鈕「{shown}」命中改變網站狀態的詞「{term}」" if term else f"這一步標了 stateful(按鈕「{shown}」)")
        if stateful_step:
            return _deny(why + ",但這次呼叫沒有帶 allow_stateful=true(使用者沒有明確要求這個動作)", "stateful_not_authorized")
        return _deny(why + ",但這一步沒有標 stateful。改狀態的動作只能寫在 steps 流程、該步標 stateful: true,"
                     "而且使用者明確要求時才以 allow_stateful=true 執行(form_submit 一律不支援)",
                     "stateful_not_authorized")
    return None
