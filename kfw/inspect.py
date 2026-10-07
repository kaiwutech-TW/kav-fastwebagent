"""inspect_page: a compact, token-cheap description of a page for the recipe author (Claude).
Not raw HTML: controls with their labels and options, clickable labels, repeated lists,
structured product data, and why the page might be unusable (login, verification, ...)."""

import time

from . import form
from .extract import extract_cards
from .page import ObservedTab
from .sites import classify
from .verify import PRODUCT_JS

ROW_PATTERNS = {"time": r"\d{1,2}:\d{2}", "price": r"(?:NT)?\$\s?[\d,]{2,}", "date": r"\d{4}[/-]\d{1,2}[/-]\d{1,2}"}


def inspect_page(browser, url, settle_ms=8000):
    t0 = time.perf_counter()
    tab = ObservedTab.open(browser)
    try:
        tab.navigate(url)
        time.sleep(0.3)
        ready = tab.wait_ready(cap_ms=settle_ms, net_quiet_ms=400, dom_quiet_ms=300)
        ctrls = form.controls(tab)
        body = tab.evaluate("document.body?.innerText || ''") or ""
        cards = extract_cards(tab)
        status, reason, hint = classify(tab.evaluate("location.href"), body, len(cards["cards"]))
        fields, clickables = [], []
        for c in ctrls:
            if c["kind"] == "select":
                fields.append({"label": c["label"], "kind": "select", "value": c["value"],
                               "options": c["options"][:12], "n_options": len(c["options"])})
            elif c["kind"] == "text":
                fields.append({"label": c["label"], "kind": "text", "value": c["value"], "readonly": c.get("readonly"),
                               "input_type": c.get("input_type")})
            elif c["kind"] in ("checkbox", "radio"):
                fields.append({"label": c["label"], "kind": c["kind"], "checked": c.get("checked")})
            elif c["label"] not in clickables:
                clickables.append(c["label"])
        row_hits = {}
        for name, pat in ROW_PATTERNS.items():
            got = form.rows(tab, pat, 3)
            if got:
                row_hits[name] = {"pattern": pat, "n_rows": len(got), "sample": got[:2]}
        return {
            "url": tab.evaluate("location.href"), "title": tab.evaluate("document.title"),
            "usable": status in ("ok", "extraction_failed", "no_results"), "blocked_reason": reason if status == "blocked" else None,
            "hint": hint if status == "blocked" else None,
            "fields": fields[:30], "clickables": clickables[:40],
            "product_list": ({"n_cards": len(cards["cards"]), "sample_titles": [c["title"][:60] for c in cards["cards"][:3]]}
                             if cards["cards"] else None),
            "repeated_rows": row_hits or None,
            "product_data": tab.evaluate(PRODUCT_JS),
            "ready": {"ok": ready.ok, "ms": ready.ms}, "ms": round((time.perf_counter() - t0) * 1000),
        }
    finally:
        try:
            tab.close()
        except Exception:
            pass
