"""The `steps` engine: a multi-step flow (click / fill / select / check / wait) run once, in order, never re-run.

Design docs/design/demo-recording.md 6.1. Every click carries a `then`: a transition that must go from false to
true (principle 2), so "the click did something" is never mistaken for "the click did the right thing". A step
that fails ends the run with needs_help; there is no whole-run retry, because a re-run could repeat a
state-changing step (design 4, V02). Every real action goes through safety.gate after its node is resolved and
before any input is dispatched (principle 3).
"""

import re
import time

from . import form, recipes, safety
from .judge import NONE_ID, normalize
from .sites import classify

THEN_CAP_S = 10.0   # a then / wait condition must come true within this many seconds
POLL_S = 0.25
OPS = ("click", "fill", "select", "check", "wait", "next_page", "pick")
_CLICKABLE = ("button", "link")
_FIELD_KINDS = ("text", "select", "checkbox", "radio")
_KINDS = {"click": _CLICKABLE, "fill": ("text",), "select": ("select",), "check": ("checkbox", "radio")}


def op_of(step):
    return next(k for k in OPS if k in step)


def _body(tab):
    try:
        return tab.evaluate("document.body?.innerText || ''") or ""
    except Exception:
        return ""


def _href(tab):
    try:
        return tab.evaluate("location.href") or ""
    except Exception:
        return ""


class _Stop(Exception):
    """A step ended the run; carries the needs_help result."""
    def __init__(self, result):
        self.result = result


# ---------- then / wait conditions ----------

def _then_kind(then):
    return next(iter(then))


def _observe_then(tab, kind, val, rows_spec):
    """The current truth of one `then` condition: (holds, token). token: for `rows` the group fingerprint (None while
    there is no non-empty matching group); for `gone` whether the target is currently uniquely found."""
    if kind == "text":
        return val in _body(tab), None
    if kind == "url_contains":
        return val in _href(tab), None
    if kind == "field":
        c, problem = recipes._find_control(form.controls(tab), val, _FIELD_KINDS)
        return bool(c) or recipes._why(problem) == "ambiguous", None
    if kind == "gone":
        c, problem = recipes._find_control(form.controls(tab), val, _CLICKABLE)
        return c is None and recipes._why(problem) == "not_found", c is not None
    if kind == "rows":
        d = form.rows_detail(tab, rows_spec["pattern"], rows_spec.get("min_rows", 1))
        return bool(d["rows"]), (d["group_fingerprint"] if d["rows"] else None)
    raise AssertionError(kind)


def _safe_observe(tab, kind, val, rows_spec):
    try:
        return _observe_then(tab, kind, val, rows_spec)
    except Exception:  # the document is navigating
        return False, None


def _await_then(tab, kind, val, base, rows_spec):
    """Poll until the transition happened or the cap. rows: fingerprint differs from before the click, non-empty,
    and the same on two observations in a row (stable). Returns (met, ms)."""
    t0, prev = time.perf_counter(), None
    while True:
        holds, token = _safe_observe(tab, kind, val, rows_spec)
        if kind == "rows":
            if holds and token != base and token == prev:
                return True, round((time.perf_counter() - t0) * 1000)
            prev = token
        elif holds:
            return True, round((time.perf_counter() - t0) * 1000)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= THEN_CAP_S * 1000:
            return False, ms
        time.sleep(POLL_S)


# ---------- helpers ----------

def _fail(tab, shots, log, i, step, reason, hint, **extra):
    shot = shots / f"step{i}-fail.jpg"
    try:
        tab.screenshot(shot)
        evidence = {"screenshot": str(shot)}
    except Exception:
        evidence = {}
    return {"status": "needs_help", "reason": reason, "hint": hint, "step_index": i, "step": step, "steps": log,
            "page_url": _href(tab), "evidence": evidence, **extra}


def _gate(tab, action, c, step, allow_stateful):
    """None = allowed. The node is re-read now (form.describe); a stateful step needs the mark AND allow_stateful."""
    try:
        target = form.describe(tab, c["id"])
        url = tab.evaluate("location.href")
    except Exception:
        target, url = None, ""
    return safety.gate(action, target, url, stateful_step=bool(step.get("stateful", False)), allow_stateful=allow_stateful)


def _refused(tab, shots, log, i, step, denied, c):
    return _fail(tab, shots, log, i, step, denied["reason"], denied["hint"], action=op_of(step), target=c.get("label"))


def _pick_option(options, wanted):
    """exact, then contains; never Kev. Returns (option, how) or (None, "ambiguous" | "not_found")."""
    n = normalize(wanted)
    opts = [o for o in options if normalize(o)]
    exact = [o for o in opts if normalize(o) == n]
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        return None, "ambiguous"
    part = [o for o in opts if n in normalize(o) or normalize(o) in n]
    if len(part) == 1:
        return part[0], "contains"
    return None, "ambiguous" if part else "not_found"


def _preflight(tab, shots, log, steps, allow_stateful):
    """Gate every action that can already be resolved on the first loaded page before anything is dispatched, so a
    refused recipe touches the page with zero input events. Actions on later pages are gated when reached."""
    ctrls = form.controls(tab)
    for i, step in enumerate(steps):
        op = op_of(step)
        if op not in _KINDS:
            continue
        c, _ = recipes._find_control(ctrls, step[op], _KINDS[op])
        if c:
            denied = _gate(tab, op, c, step, allow_stateful)
            if denied:
                return _refused(tab, shots, log, i, step, denied, c)
    return None


def _doc_changed(tab, href_before):
    try:
        return tab.evaluate("window.__kfwClickAt ?? null") is None or _href(tab) != href_before
    except Exception:
        return True


# ---------- one step ----------

def _do_click(tab, shots, log, i, step, r, allow_stateful):
    label, then = step["click"], step["then"]
    c, problem = recipes._find_control(form.controls(tab), label, _CLICKABLE)
    if not c:
        if step.get("optional") and recipes._why(problem) == "not_found":  # optional skips absence only
            log.append({"i": i, "click": label, "skipped": recipes._problem_text(label, problem)})
            return
        raise _Stop(_fail(tab, shots, log, i, step, "step_failed", recipes._problem_text(label, problem),
                          why=recipes._why(problem)))
    denied = _gate(tab, "click", c, step, allow_stateful)
    if denied:
        raise _Stop(_refused(tab, shots, log, i, step, denied, c))
    kind = _then_kind(then)
    val = then[kind]
    rows_spec = (r.get("result") or {}).get("rows")
    holds, token = _safe_observe(tab, kind, val, rows_spec)
    if kind == "gone":
        if not token:  # the target must be uniquely found before the click, or its disappearance proves nothing
            raise _Stop(_fail(tab, shots, log, i, step, "step_failed", f"then.gone:點擊前找不到唯一的按鈕/連結「{val}」,"
                              "無法證明它之後消失(找不到或不唯一)", why="then_target_not_unique"))
        holds = False
    if holds and kind != "rows":  # rows is a change relative to the fingerprint, an existing table is not "already true"
        raise _Stop(_fail(tab, shots, log, i, step, "then_already_true",
                          f"then 條件 {then} 在點擊前就已成立,點擊之後成立不能證明點擊有效:換一個點擊後才會變真的條件"))
    href_before = _href(tab)
    clicked = form.click(tab, c["id"])
    if not clicked.get("ok"):
        raise _Stop(_fail(tab, shots, log, i, step, "step_failed", f"點擊「{label}」沒有送出:{clicked}",
                          why=clicked.get("why", "click_failed")))
    met, ms = _await_then(tab, kind, val, token if kind == "rows" else None, rows_spec)
    if not met:
        raise _Stop(_fail(tab, shots, log, i, step, "step_failed",
                          f"點擊「{label}」後 {THEN_CAP_S:g} 秒內 then 條件 {then} 沒有成立(頁面沒有進到預期的下一個狀態)",
                          why="then_not_met"))
    entry = {"i": i, "click": label, "then": then, "then_ms": ms}
    if _doc_changed(tab, href_before):
        entry["ready"] = tab.wait_ready(cap_ms=8000, net_quiet_ms=300, dom_quiet_ms=300).reason
    log.append(entry)


def _do_field(tab, shots, log, i, step, allow_stateful):
    op = op_of(step)
    label, want = step[op], step["value"]
    c, problem = recipes._find_control(form.controls(tab), label, _KINDS[op])
    if not c:
        raise _Stop(_fail(tab, shots, log, i, step, "step_failed", recipes._problem_text(label, problem),
                          why=recipes._why(problem)))
    if op == "check":
        if c["kind"] == "radio" and want is False:
            raise _Stop(_fail(tab, shots, log, i, step, "step_failed", f"「{label}」是 radio,只能設為 true(radio 不能取消勾選)",
                              why="radio_false"))
        if bool(c["checked"]) == want:
            log.append({"i": i, "check": label, "value": want, "already": True})
            return
        denied = _gate(tab, "check", c, step, allow_stateful)
        if denied:
            raise _Stop(_refused(tab, shots, log, i, step, denied, c))
        clicked = form.click(tab, c["id"])
        now = form.checked(tab, c["id"]) if clicked.get("ok") else None
        if now is not want:
            raise _Stop(_fail(tab, shots, log, i, step, "step_failed",
                              f"「{label}」讀回的勾選狀態不符:要 {want},讀到 {now}", why="not_set"))
        log.append({"i": i, "check": label, "value": want, "read_back": now})
        return
    denied = _gate(tab, op, c, step, allow_stateful)
    if denied:
        raise _Stop(_refused(tab, shots, log, i, step, denied, c))
    if op == "select":
        if normalize(c["value"]) == normalize(want):
            log.append({"i": i, "select": label, "value": want, "already": c["value"]})
            return
        opt, how = _pick_option(c["options"], want)
        if not opt:
            raise _Stop(_fail(tab, shots, log, i, step, "step_failed",
                              f"「{label}」的選項中" + ("有多個符合" if how == "ambiguous" else "沒有符合")
                              + f"「{want}」(只做完全相符/包含,不猜)", why=how, options=c["options"][:30]))
        res = form.select_option(tab, c["id"], opt)
        entry = {"i": i, "select": label, "want": want, "chose": opt, "how": how, **recipes._public(res)}
    else:
        res = form.fill(tab, c["id"], want)
        entry = {"i": i, "fill": label, "want": want, **recipes._public(res)}
    log.append(entry)
    if not res.get("ok"):
        raise _Stop(_fail(tab, shots, log, i, step, "step_failed", f"讀回的值不符:{entry}", why="not_set"))


def _do_wait(tab, shots, log, i, step):
    text = step["wait"]["text"]
    t0 = time.perf_counter()
    while True:
        if text in _body(tab):
            log.append({"i": i, "wait": text, "ms": round((time.perf_counter() - t0) * 1000)})
            return
        if time.perf_counter() - t0 >= THEN_CAP_S:
            raise _Stop(_fail(tab, shots, log, i, step, "step_failed",
                              f"等了 {THEN_CAP_S:g} 秒,頁面上仍沒有出現文字「{text}」", why="wait_timeout"))
        time.sleep(POLL_S)


# ---------- next_page (design 6.2) ----------

def _stable_rows(tab, rows_spec):
    """Wait for the result group to be non-empty and unchanged over two polls (a loading skeleton or an empty table
    is not a page). Returns the rows_detail dict, or None at the cap."""
    t0, prev = time.perf_counter(), None
    while True:
        try:
            d = form.rows_detail(tab, rows_spec["pattern"], rows_spec.get("min_rows", 1))
        except Exception:  # the document is navigating
            d = {"rows": []}
        fp = d["group_fingerprint"] if d["rows"] else None
        if fp is not None and fp == prev:
            return d
        prev = fp
        if time.perf_counter() - t0 >= THEN_CAP_S:
            return None
        time.sleep(POLL_S)


def _do_next_page(tab, shots, log, i, step, r, allow_stateful):
    np, res_spec = step["next_page"], r["result"]
    label, max_pages, end = np["click"], np["max_pages"], np["end"]
    rows_spec = res_spec["rows"]
    seen, merged, keys, pages = set(), [], set(), []
    more, status, reason, hint, skipped = False, "done", None, None, 0

    def fail(why_reason, text, **extra):
        return _fail(tab, shots, log, i, step, why_reason, text, pages=pages, pages_collected=len(pages), **extra)

    for page in range(1, max_pages + 1):
        d = _stable_rows(tab, rows_spec)
        if d is None:
            return fail("step_failed", f"第 {page} 頁在 {THEN_CAP_S:g} 秒內沒有出現穩定且非空的結果群組(rows.pattern)", why="page_empty")
        n_skipped = d.get("rows_skipped")
        skipped += n_skipped if isinstance(n_skipped, int) else 0
        amb = recipes._ambiguity(d)
        if amb:
            return fail(amb["reason"], amb["hint"])
        fp = d["group_fingerprint"]
        if fp in seen:
            status, reason = "partial", "loop_detected"
            hint = f"第 {page} 頁的內容與先前某頁相同(翻頁繞回原處),已停止;只收集到前 {len(pages)} 頁,不是全部"
            break
        seen.add(fp)
        fresh = 0
        for row in d["rows"]:
            k = normalize(" ".join(row))
            if k not in keys:
                keys.add(k)
                merged.append(row)
                fresh += 1
        pages.append({"page": page, "rows_count": len(d["rows"]), "fingerprint": fp})
        log.append({"i": i, "page": page, "rows": len(d["rows"]), "new_rows": fresh, "fingerprint": fp})
        body = _body(tab)
        missing = [t for t in res_spec.get("expect_text", []) if t not in body]
        if missing:
            return fail("result_not_proven", f"第 {page} 頁缺少文字 {missing}(每一頁都要滿足 expect_text)", expect_text_missing=missing)
        ev = form.find_clickable(tab, label)
        state = ev["state"]
        if state == "ambiguous":
            return fail("next_button_ambiguous", f"第 {page} 頁有 {ev['candidates']} 個按鈕/連結符合「{label}」,無法確定哪個是下一頁", why="ambiguous")
        if state == end:
            break  # last page, proven by the evidence the recipe named
        if state in ("absent", "disabled"):
            saw = "沒有這個按鈕(消失)" if state == "absent" else "按鈕還在但是 disabled"
            return fail("end_mismatch", f"配方寫 end:\"{end}\",但第 {page} 頁{saw}:看截圖確認尾頁的樣子後改 end", why=state)
        if page == max_pages:
            more, hint = True, f"已收集前 {page} 頁,還有更多(下一頁按鈕仍可按);不是全部資料"
            break
        c = {"id": ev["control"]["id"], "label": ev["control"]["label"]}
        denied = _gate(tab, "next_page", c, {}, allow_stateful)  # never stateful: a stateful-worded pager is refused
        if denied:
            return _refused(tab, shots, log, i, step, denied, c)
        clicked = form.click(tab, c["id"])
        if not clicked.get("ok"):
            return fail("step_failed", f"點擊「{label}」沒有送出:{clicked}", why=clicked.get("why", "click_failed"))
        met, ms = _await_then(tab, "rows", True, fp, rows_spec)
        if not met:
            return fail("step_failed", f"點擊「{label}」後 {THEN_CAP_S:g} 秒內結果群組沒有變成新的穩定內容(翻頁沒有生效)",
                        why="then_not_met")
        log.append({"i": i, "click": label, "then": {"rows": True}, "then_ms": ms})
    got, unmatched = recipes.label_rows(merged, rows_spec.get("columns"))
    shot = shots / "result.jpg"
    tab.screenshot(shot)
    ok = len(got) >= rows_spec.get("min_rows", 1) and not unmatched
    if not ok:
        return fail("result_not_proven", f"收集到 {len(got)} 列,{unmatched} 列的格數和 columns 對不上(欄位可能變了,看截圖後修 columns)")
    out = {"status": status, "reason": reason, "hint": hint, "rows": got[: rows_spec.get("max_rows", 50)],
           "rows_total": len(got), "rows_skipped": skipped, "expect_text_missing": [], "steps": log, "pages": pages,
           "pages_collected": len(pages), "more_pages": more, "page_url": _href(tab), "evidence": {"screenshot": str(shot)}}
    if skipped:
        out["note"] = recipes.skipped_note(skipped)
    return out


# ---------- pick (design 6.4) ----------
# The one bounded exception to "one step, one target": choose one row of a list, then click one control inside it.
# Text first (exact, then contains); Kev only when that is not unique; a threshold on the full distribution; the
# control inside the chosen row must be unique; nothing is ever clicked "as a fallback".

PICK_MIN_P = 0.8        # the best candidate's probability
PICK_MIN_GAP = 0.3      # ... and its lead over the runner-up (which may be "none")
PICK_MAX_CANDIDATES = 40
PICK_ATTEMPTS = 2       # the first observation, and one re-observation if the list moved under us
_EPS = 1e-9


def decide_pick(probs, min_p=PICK_MIN_P, min_gap=PICK_MIN_GAP):
    """The acceptance rule on a full distribution {id: p} that includes "none". Returns (chosen id | None, why):
    why is None when accepted, else "none_highest" | "low_confidence" | "small_gap"."""
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])
    (top, p1), p2 = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    if top == NONE_ID:
        return None, "none_highest"
    if p1 < min_p - _EPS:
        return None, "low_confidence"
    if p1 - p2 < min_gap - _EPS:
        return None, "small_gap"
    return top, None


def _cand_view(cands):
    return [{"id": cid, "text": row["text"][:80]} for cid, row in cands.items()]


_NOISE_CELL = re.compile(r"^[\s$¥￥€£NTDUSRMBnt元圓円.,:%/+\-\d]*$")


def _kev_text(row, click_text):
    """What Kev reads for one row: its meaningful cells. Drop the button words the step will click and cells that
    are only prices / numbers; they are the same on every row and drown the difference (2026-09-29: with them Kev
    stopped on 3 of 4 answerable wants, without them and with the list as context it chose right on 5/5)."""
    ct = normalize(click_text)
    keep = [c for c in row["cells"] if c and normalize(c) != ct and not _NOISE_CELL.match(c)]
    return (" ".join(keep) or row["text"])[:200]


def _select_row(judge, cands, want, ev, click_text=""):
    """(row | None, problem | None). Fills `ev` (how, kev_ms, probabilities). problem = (reason, hint, extra)."""
    n = normalize(want)
    norm = {cid: normalize(row["text"]) for cid, row in cands.items()}
    # a row's text also carries its price / button words, so "exact" is the whole row text OR one whole cell
    exact = [cid for cid, row in cands.items() if norm[cid] == n or n in {normalize(c) for c in row["cells"]}]
    if len(exact) == 1:
        ev["how"] = "exact"
        return cands[exact[0]], None
    part = [cid for cid in cands if n in norm[cid]]
    if not exact and len(part) == 1:
        ev["how"] = "contains"
        return cands[part[0]], None
    if len(cands) > PICK_MAX_CANDIDATES:
        return None, ("pick_uncertain", f"文字比對不唯一,而候選有 {len(cands)} 列,超過 {PICK_MAX_CANDIDATES} 列不交給 Kev 猜:"
                      "把 rows.pattern 寫得更專一,或把 want 寫得更完整", {"why": "too_many_candidates"})
    ev["how"] = "kev"
    t0 = time.perf_counter()
    try:
        texts = {cid: _kev_text(row, click_text) for cid, row in cands.items()}
        ev["kev_texts"] = texts
        probs = judge.row_match(want, texts, state={"要找的": want, "候選清單": "、".join(texts.values())[:2000]})
    except Exception as e:  # Kev down, malformed answer: stop, never fall back to a guess
        ev["kev_ms"] = round((time.perf_counter() - t0) * 1000)
        ev["kev_error"] = f"{type(e).__name__}: {e}"[:300]
        return None, ("pick_uncertain", f"文字比對不唯一,而 Kev 沒有給出可用的答案({ev['kev_error']});不猜",
                      {"why": "kev_error", "candidates": _cand_view(cands)})
    ev["kev_ms"] = round((time.perf_counter() - t0) * 1000)
    ev["probabilities"] = {k: round(v, 4) for k, v in probs.items()}
    chosen, why = decide_pick(probs)
    if not chosen:
        text = {"none_highest": "Kev 認為都不是", "low_confidence": f"最高機率不到 {PICK_MIN_P}",
                "small_gap": f"最高與第二名的差距不到 {PICK_MIN_GAP}"}.get(why or "", "")
        return None, ("pick_uncertain", f"要找「{want}」:{text},程式不猜。看候選與機率後,把 want 寫得更明確(或把 rows.pattern 收窄)",
                      {"why": why, "candidates": _cand_view(cands), "probabilities": ev["probabilities"]})
    return cands[chosen], None


def _await_pick_effect(tab, base_fp, href_before, rows_spec):
    """The click must change the document or the list's fingerprint (a vanished list counts). Returns (how|None, ms)."""
    t0 = time.perf_counter()
    while True:
        if _doc_changed(tab, href_before):
            return "document", round((time.perf_counter() - t0) * 1000)
        try:
            d = form.rows_detail(tab, rows_spec["pattern"], rows_spec.get("min_rows", 1))
            fp = d["group_fingerprint"] if d["rows"] else None
        except Exception:  # the document is navigating
            return "document", round((time.perf_counter() - t0) * 1000)
        if fp != base_fp:
            return "fingerprint", round((time.perf_counter() - t0) * 1000)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= THEN_CAP_S * 1000:
            return None, ms
        time.sleep(0.1)


def _describe(tab, cid):
    try:
        return form.describe(tab, cid)
    except Exception:
        return None


def _do_pick(tab, shots, log, i, step, r, judge, allow_stateful):
    pk = step["pick"]
    rows_spec, want, label = pk["rows"], pk["want"], pk["click"]
    ev: dict = {"i": i, "pick": want, "click": label, "attempts": []}
    log.append(ev)

    def fail(reason, hint, **extra):
        return _Stop(_fail(tab, shots, log, i, step, reason, hint, **extra))

    for attempt in range(1, PICK_ATTEMPTS + 1):
        att: dict = {"attempt": attempt}
        ev["attempts"].append(att)
        stable = _stable_rows(tab, rows_spec)
        if stable is None:
            raise fail("pick_no_candidate", f"{THEN_CAP_S:g} 秒內頁面上沒有穩定且非空、符合 pick.rows.pattern 的列表", why="no_rows")
        obs = form.pick_groups(tab, rows_spec["pattern"], rows_spec.get("min_rows", 1))
        groups = obs["groups"]
        if len(groups) > 1:
            raise fail("result_ambiguous", f"頁面上有 {len(groups)} 個獨立的列表同時符合 pick.rows.pattern,程式不猜是哪一個:"
                       "看截圖後把 pattern 改得更精確,讓只有想要的列表符合")
        if not groups or not groups[0]["rows"]:
            raise fail("pick_no_candidate", "沒有任何列符合 pick.rows.pattern", why="no_rows")
        rows = groups[0]["rows"]
        cands = {f"c{n}": row for n, row in enumerate(rows, 1)}
        skipped = groups[0].get("skipped", 0)
        att.update(candidates=_cand_view(cands), group_fingerprint=groups[0]["fingerprint"], rows_skipped=skipped)
        row, problem = _select_row(judge, cands, want, att, label)
        if problem:
            reason, hint, extra = problem
            if skipped:  # the row Kev could not find may be one the pattern never showed it
                hint += f"({(recipes.skipped_note(skipped) or '').replace('rows.pattern', 'pick.rows.pattern')})"
            raise fail(reason, hint, **extra, rows_skipped=skipped)
        assert row is not None
        cid = next(k for k, v in cands.items() if v is row)
        att["chosen"] = {"id": cid, "row_id": row["row_id"], "text": row["text"][:200]}
        ctrl, prob = recipes._find_control(row["controls"], label, _CLICKABLE)
        if not ctrl:  # zero or several: stop, never the first link as a fallback
            raise fail("pick_no_control" if recipes._why(prob) == "not_found" else "pick_control_ambiguous",
                       f"選中的列 {cid}「{row['text'][:40]}」之內:" + recipes._problem_text(label, prob),
                       why=recipes._why(prob), chosen=att["chosen"])
        target = _describe(tab, ctrl["id"])
        if not (target or {}).get("ok"):  # the node vanished since the observation: the list moved, not a safety verdict
            att["stale"] = "control_gone"
            continue
        denied = safety.gate("pick", target, _href(tab), stateful_step=False, allow_stateful=allow_stateful)
        if denied:
            raise _Stop(_refused(tab, shots, log, i, step, denied, ctrl))
        ok = form.verify_pick(tab, row["row_id"], groups[0]["group_id"], row["text"], obs["generation"], ctrl["id"])
        if not ok.get("ok"):
            att["stale"] = ok.get("why")
            continue
        href_before = _href(tab)
        clicked = form.click(tab, ctrl["id"])
        if not clicked.get("ok"):
            raise fail("step_failed", f"點擊「{label}」沒有送出:{clicked}", why=clicked.get("why", "click_failed"))
        how, ms = _await_pick_effect(tab, stable["group_fingerprint"], href_before, rows_spec)
        if not how:
            raise fail("pick_no_effect", f"點擊選中列 {cid} 的「{label}」後 {THEN_CAP_S:g} 秒內文件沒有換頁、列表指紋也沒有變(點擊沒有效果)",
                       chosen=att["chosen"])
        ev.update(how=att.get("how"), chosen=att["chosen"], effect=how, effect_ms=ms)
        for k in ("probabilities", "kev_ms", "rows_skipped"):
            if k in att:
                ev[k] = att[k]
        if _doc_changed(tab, href_before):
            ev["ready"] = tab.wait_ready(cap_ms=8000, net_quiet_ms=300, dom_quiet_ms=300).reason
        return
    raise fail("pick_stale", f"列表在選擇與點擊之間連續 {PICK_ATTEMPTS} 次被頁面改動({[a.get('stale') for a in ev['attempts']]}),"
               "程式不點可能已經不是原本那一列的節點", why="stale")


# ---------- the run ----------

def run_steps(recipe, params, browser, judge, shots, *, allow_stateful=False, browser_context_id=None, demo=None):
    """Run a steps recipe once. `judge` is only used by `pick` (design 6.4), and only when text matching is not unique.
    browser_context_id: every tab of the run lives in that isolated browser context (design 7.4, I8; the run opens exactly one tab).
    demo: the demonstration comparison to make on the result page (dry_run of a recorded recipe), before the tab closes."""
    r = recipes.render_recipe(recipe, params)
    steps, log = r["steps"], []
    tab = recipes._open_tab(browser, browser_context_id)
    try:
        out = _run(tab, r, steps, log, judge, shots, allow_stateful)
        if demo and out.get("status") == "done":
            out["demo_compare"] = recipes._demo_compare(tab, (r.get("result") or {}).get("rows"), demo)
        return out
    finally:
        try:
            tab.close()
        except Exception:
            pass


def _run(tab, r, steps, log, judge, shots, allow_stateful):
    tab.navigate(r["url"])
    time.sleep(0.3)
    ready = tab.wait_ready(cap_ms=8000, net_quiet_ms=300, dom_quiet_ms=300)
    log.append({"ready": ready.reason, "ms": ready.ms, "inflight": ready.inflight})
    _, settled = form.settle_controls(tab)
    log.append({"controls_settled": settled["ok"], "ms": settled["ms"]})
    denied = _preflight(tab, shots, log, steps, allow_stateful)
    if denied:
        return denied
    for i, step in enumerate(steps):
        op = op_of(step)
        try:
            if op == "click":
                _do_click(tab, shots, log, i, step, r, allow_stateful)
            elif op == "wait":
                _do_wait(tab, shots, log, i, step)
            elif op == "pick":
                _do_pick(tab, shots, log, i, step, r, judge, allow_stateful)
            elif op == "next_page":
                return _do_next_page(tab, shots, log, i, step, r, allow_stateful)
            else:
                _do_field(tab, shots, log, i, step, allow_stateful)
        except _Stop as stop:
            return stop.result
        form.settle_controls(tab)
    return _result(tab, r, shots, log)


def _result(tab, r, shots, log):
    """Same completion proof as form_submit: rows (with group ambiguity), columns labelling, expect_text."""
    res_spec, got, wait_ms, ambiguous, skipped = r["result"], [], 0, None, 0
    rows_spec = res_spec.get("rows")
    if rows_spec:
        got, ambiguous, wait_ms, skipped = recipes._result_rows(tab, rows_spec)
    else:
        tab.wait_ready(cap_ms=10000)
    got, unmatched = recipes.label_rows(got, (rows_spec or {}).get("columns"))
    body = _body(tab)
    missing = [t for t in res_spec.get("expect_text", []) if t not in body]
    shot = shots / "result.jpg"
    tab.screenshot(shot)
    ok = (not rows_spec or len(got) >= rows_spec.get("min_rows", 1)) and not missing and not unmatched and not ambiguous
    status, reason, hint = ("done", None, None) if ok else classify(_href(tab), body, 0)
    if ambiguous:
        reason, hint = ambiguous["reason"], ambiguous["hint"]
    elif not ok and status == "extraction_failed":
        reason, hint = "result_not_proven", f"所有步驟都完成了,但結果沒有被程式證明:rows={len(got)} 缺少文字={missing}"
        if unmatched:
            hint += f"({unmatched} 列的格數和 columns 對不上:欄位可能變了,看截圖後修 columns)"
        if skipped:
            hint += f"({recipes.skipped_note(skipped)})"
    out = {"status": "done" if ok else "needs_help", "reason": reason, "hint": hint,
           "rows": got[: (rows_spec or {}).get("max_rows", 50)], "rows_total": len(got), "rows_skipped": skipped,
           "expect_text_missing": missing, "steps": log, "result_wait_ms": wait_ms, "page_url": _href(tab),
           "evidence": {"screenshot": str(shot)}}
    if skipped and ok:
        out["note"] = recipes.skipped_note(skipped)
    return out
