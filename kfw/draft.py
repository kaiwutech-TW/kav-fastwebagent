"""Recording -> draft recipe (design docs/design/demo-recording.md 7.2 - 7.4). Pure functions: no browser, no disk.

Inputs are exactly what WP1 wrote (see kfw/record.py): log.jsonl records
  hello{doc_id,href,restored}  baseline{snap}  snapshot{id}  group_open{gid,kind,target,prev_snap}
  group_close{gid,kind,snap,keys,synthetic?,doc_navigated_after?}  group_nav{gid}  mark{tag,text,text_truncated,href,group}
  incomplete{reason}  done
each carrying `epoch` (one document generation), and snapshots/<id>.json control lists (form.OBSERVE_JS `snapshot`).

Scope: version A shapes (one page, fill fields + one click) become `form_submit` / `detail_extract`; every other supported shape
(several pages, clicks between edits, edits after a click) becomes `steps` (design 6.3). What neither can express says why it
is not supported (`unsupported`), it is never silently reduced to what does fit (I2).
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from . import safety
from .judge import normalize

# strings shared with kfw/record.py so a result never carries the same warning twice
W_NO_MARK = "沒有標記結果:錄製裡沒有『標記結果』的動作,之後無法據此產生流程。"


def w_multi_mark(n):
    return f"標記了 {n} 次,只會採用最後一次。"


COMPARATORS = ("rows-exact-v1", "text-contains-v1")
_BUTTON_INPUT_TYPES = ("button", "submit", "reset", "image", "hidden")
_UNFILLABLE_INPUT_TYPES = ("file", "range", "color")


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


# =====================================================================================================
# row_pattern (7.2 point 7): a candidate pattern generalised from the marked rows. Only a candidate: whether it
# singles out one table is for the live check (7.3) or the dry run (5.2) to say.
# =====================================================================================================

_GENERIC = r"\S(?:.*?\S)?"
_SHAPES = (  # (name, regex source; both Python and JS read it)
    ("time", r"\d{1,2}:\d{2}(?::\d{2})?"),
    ("date", r"\d{4}[/-]\d{1,2}[/-]\d{1,2}"),
    ("number", r"[-+]?\d[\d,]*(?:\.\d+)?"),
)


def _js_escape(s):
    return re.sub(r"[.*+?^${}()|\[\]\\/]", lambda m: "\\" + m.group(0), s)


def _cell_shape(cell):
    for name, src in _SHAPES:
        if re.fullmatch(src, cell):
            return name, src
    return None


def row_pattern(rows, texts=None, joiner=" "):
    """rows: the marked group's canonical raw cells (list of lists of str). -> a regex source string (valid in both Python
    and JS, anchored, cells joined by one space like the normalised row text) or None when it cannot be made.
    Fewer than 2 rows -> None (one row says nothing about what varies); ragged rows -> None. Each cell position is
    generalised on its own: all equal -> copied literally; all the same time/date/number shape -> that shape; else \\S(.*?\\S)?.
    texts: the rows' normalised innerText when known (a list-row's inline cells may have no space between them); the pattern
    must match each of them. joiner: what sits between two cells (a regex source)."""
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    n = len(rows[0])
    if n == 0 or any(len(r) != n for r in rows):
        return None
    parts = []
    for i in range(n):
        col = [r[i] for r in rows]
        if len(set(col)) == 1:
            parts.append(_js_escape(col[0]))
            continue
        shapes = {sh[1] if sh else None for sh in map(_cell_shape, col)}
        only = next(iter(shapes))
        parts.append(only if len(shapes) == 1 and only is not None else _GENERIC)
    pattern = "^" + joiner.join(parts) + "$"
    subjects = texts if texts is not None else [" ".join(r) for r in rows]
    try:
        if not all(re.fullmatch(pattern[1:-1], t) for t in subjects):
            return None
    except re.error:
        return None
    return pattern


def candidate_pattern(group):
    """(pattern | None, warnings) for the mark's `group` payload. None group -> (None, [])."""
    if not group:
        return None, []
    rows = group.get("rows") or []
    if len(rows) < 2:
        return None, ["single_row:標記的表只有 1 列,程式無法從一列看出哪些格會變,沒有產生 rows.pattern,請自己寫一個能只選中這張表的 pattern。"]
    p = row_pattern(rows)
    if p is None:
        return None, ["pattern_unavailable:標記的各列格數不一致,程式沒有產生 rows.pattern,請自己寫。"]
    return p, []


def headers_for(group):
    """rows.columns filled only when it is certain: a th header row recorded, one header per cell, no repeats."""
    if not group or not group.get("has_th"):
        return None
    hs = group.get("headers")
    rows = group.get("rows") or []
    if not isinstance(hs, list) or not rows or not all(isinstance(h, str) and h for h in hs):
        return None
    if any(len(r) != len(hs) for r in rows) or len(set(hs)) != len(hs):
        return None
    return list(hs)


# =====================================================================================================
# log parsing
# =====================================================================================================

def _parse(log):
    docs, groups, marks, incompletes, by_key = {}, [], [], [], {}
    for rec in log:
        t, ep = rec.get("type"), rec.get("epoch", 0)
        if t == "hello":
            docs[ep] = {"href": rec.get("href", ""), "restored": bool(rec.get("restored")), "baseline": None, "res": None}
        elif t == "baseline":
            d = docs.setdefault(ep, {"href": "", "restored": False, "baseline": None, "res": None})
            d["baseline"], d["res"] = rec.get("snap"), rec.get("res")
        elif t == "group_open":
            g = {"epoch": ep, "gid": rec.get("gid"), "kind": rec.get("kind"), "target": rec.get("target") or {},
                 "prev": rec.get("prev_snap"), "snap": None, "keys": [], "synthetic": False, "nav_after": False, "index": len(groups),
                 "res": rec.get("res"), "row": (rec.get("target") or {}).get("row")}
            groups.append(g)
            by_key[(ep, g["gid"])] = g
        elif t == "group_close":
            g = by_key.get((ep, rec.get("gid")))
            if g is not None:
                g.update(snap=rec.get("snap"), synthetic=bool(rec.get("synthetic")), nav_after=bool(rec.get("doc_navigated_after")))
                if rec.get("kind"):
                    g["kind"] = rec["kind"]
                g["keys"] = list(rec.get("keys") or [])
        elif t == "group_nav":
            g = by_key.get((ep, rec.get("gid")))
            if g is not None:
                g["nav_after"] = True
        elif t == "mark":
            marks.append({**rec, "epoch": ep, "after": len(groups)})
        elif t == "incomplete":
            incompletes.append(rec)
    # The last action group of a document, followed by a newer document, is what navigated away (the recorder's own
    # flag is missing when the unload beat the flag: TRAPS pagehide-binding-call-not-delivered).
    later = sorted(docs)
    for g in groups:
        same = [x for x in groups if x["epoch"] == g["epoch"]]
        if same and same[-1] is g and any(ep > g["epoch"] for ep in later):
            g["nav_after"] = True
    return docs, groups, marks, incompletes


def mark_reference(log):
    """The last mark of a recording: {epoch, href, text, text_truncated, group} (group = canonical raw cells payload) or None."""
    marks = _parse(log)[2]
    if not marks:
        return None
    m = marks[-1]
    return {"epoch": m["epoch"], "href": m.get("href", ""), "text": m.get("text", ""), "text_truncated": bool(m.get("text_truncated")),
            "group": m.get("group")}


def _by_id(controls):
    return {c.get("id"): c for c in controls or [] if isinstance(c, dict)}


def _kind_of(c):
    return "select" if c.get("kind") == "select" else "text"


def _changes(prev, cur):
    """Native field differences between two committed snapshots: [(id, label, kind, before, after, control_after)]."""
    old = _by_id(prev)
    out = []
    for c in cur or []:
        if not isinstance(c, dict) or c.get("sensitive"):
            continue
        p = old.get(c.get("id"))
        if p is None:
            continue
        kind = c.get("kind")
        key = "checked" if kind in ("checkbox", "radio") else "value" if kind in ("select", "text") else None
        if key and p.get(key) != c.get(key):
            out.append({"id": c["id"], "label": c.get("label", ""), "kind": kind, "before": p.get(key), "after": c.get(key), "ctl": c})
    return out


def _issue(reason, hint, **detail):
    return {"reason": reason, "hint": hint, **detail}


# =====================================================================================================
# to_draft
# =====================================================================================================

def _slug(label, taken, i):
    s = re.sub(r"[^0-9a-z]+", "_", unicodedata.normalize("NFKC", label or "").lower()).strip("_")
    s = s if s and not s[0].isdigit() else f"p{i}"
    base, k = s, 2
    while s in taken:
        s, k = f"{base}_{k}", k + 1
    taken.add(s)
    return s


def to_draft(log, snapshots, live_checks=None, recording_id=None, terminal_state=None):
    """-> {state, draft | None, unsupported?, param_candidates, warnings, demo, live_checks}.

    log / snapshots: read_log() / read_snapshots() of a recording directory. live_checks: what stop measured on the page
    (record.Recording._live_checks) or None. terminal_state: the recording's own terminal state when the caller knows it."""
    docs, groups, marks, incompletes = _parse(log)
    state = terminal_state or ("incomplete" if incompletes else "completed")
    out = {"state": state, "draft": None, "param_candidates": [], "warnings": [], "demo": None, "live_checks": {"status": "not_applicable"}}
    if state != "completed":
        out["warnings"].append("錄製不是 completed,不產生草稿。")
        return out
    if not marks:
        out["warnings"].append(W_NO_MARK)
        out["unsupported"] = _issue("no_mark", "沒有標記結果,無法知道要驗證什麼;請重錄並在最後按「標記結果」。")
        return out
    if len(marks) > 1:
        out["warnings"].append(w_multi_mark(len(marks)))
    mark = marks[-1]
    issues, warnings = [], out["warnings"]

    # ---- 1. events, in order ----
    events: list[dict[str, Any]] = []
    for g in groups:
        events.extend(_events(g, snapshots, issues))
    events = _collapse_retries(events, out["warnings"])
    post = [e for e in events if e["gi"] >= mark["after"]]
    events = [e for e in events if e["gi"] < mark["after"]]
    if post:
        issues.append(_issue("actions_after_mark", "標記結果之後又做了操作(" + "、".join(_describe(e) for e in post[:4]) +
                             ");請把「標記結果」放在所有操作的最後再重錄。"))
    clicks = [e for e in events if e["type"] == "click"]
    sets = [e for e in events if e["type"] == "set"]
    enters = [e for e in events if e["type"] == "enter"]
    for e in clicks:
        f = safety.text_flags(e["text"])
        if f["forbidden"]:
            issues.append(_issue("forbidden_in_demo", f"示範裡點了「{e['text']}」,這類動作(付款、結帳、登入、註冊等)Kav 永遠不重播。"))
        elif f["stateful"]:
            issues.append(_issue("stateful_in_demo", f"示範裡點了「{e['text']}」,這會改變網站狀態;示範做過不等於要 Kav 自動做,"
                                 "而且試跑會真的執行它。改狀態的流程要使用者明確要求後由 Claude 手寫 steps。"))

    # ---- 2. shape ----
    kind, action_epoch, submit, pre = None, None, None, []
    epochs = sorted({e["epoch"] for e in clicks + sets})
    needs_steps = False          # a shape only `steps` can express (design 6.3); becomes a steps draft when nothing else is wrong
    if not clicks and not sets:
        for e in enters:
            if e["nav_after"]:
                issues.append(_issue("enter_submit", "示範是在欄位裡按 Enter 送出的,錄製 v1 不支援;請改按畫面上的按鈕後重錄。"))
                break
        kind = "detail_extract"
    else:
        kind = "form_submit"
        if not clicks:
            if any(True for _ in enters):
                issues.append(_issue("enter_submit", "示範是在欄位裡按 Enter 送出的,錄製 v1 不支援;請改按畫面上的按鈕後重錄。"))
            else:
                issues.append(_issue("no_submit_click", "示範裡有填欄位但沒有點任何按鈕/連結送出,無法知道怎麼送出。"))
        else:
            action_epoch = epochs[0]
            submit = clicks[-1]
            if len(epochs) > 1:
                needs_steps = True                      # the operations span several pages
            if any(normalize(a["text"]) == normalize(b["text"]) for a, b in zip(clicks, clicks[1:])):
                needs_steps = True                      # the same button twice in a row (a pager), never "pre + submit"
            if mark["epoch"] < epochs[-1]:
                issues.append(_issue("mark_before_actions", "標記結果的頁面比操作的頁面還早,順序不合理;請重錄。"))
            if sets and max(e["gi"] for e in sets) > submit["gi"]:
                needs_steps = True                      # input after the last click: the trailing edit is reported by the steps builder
            first_set = min((e["gi"] for e in sets), default=None)
            for c in clicks[:-1]:
                if first_set is None or c["gi"] < first_set:
                    pre.append(c)
                else:
                    needs_steps = True                  # a click between edits
            for e in enters:
                if e["nav_after"] or e["gi"] > submit["gi"]:
                    issues.append(_issue("enter_submit", "示範裡有在欄位按 Enter 送出,錄製 v1 不支援;請改按畫面上的按鈕後重錄。"))
                    break
        if needs_steps:
            kind, pre = "steps", []
    if action_epoch is not None and action_epoch > min(docs, default=action_epoch):
        warnings.append("操作發生的頁面不是錄製一開始開啟的那一個文件(中間有轉址或重新載入);url 取操作當時的頁面。")

    # ---- 3. fields at the submit boundary ----
    fields, cands = [], []
    if kind == "form_submit" and submit is not None and not issues:
        fields = _boundary_fields(submit, sets, snapshots, docs.get(action_epoch, {}), issues, warnings)
    # ---- 4. result ----
    grp = mark.get("group")
    rows_spec: dict[str, Any] | None = None
    comparator, rpat = None, None
    text = mark.get("text", "")
    if grp:
        comparator = "rows-exact-v1"
        if grp.get("truncated") or grp.get("rows_sent", len(grp.get("rows") or [])) < grp.get("total", 0) or not grp.get("rows"):
            issues.append(_issue("result_kind", "標記的表太大(超過 200 列或資料量上限)或是空的,錄製 v1 的示範一致檢查需要完整、非空的表。"))
        else:
            rpat, pw = candidate_pattern(grp)
            warnings.extend(pw)
            rows_spec = {"min_rows": 1}
            if rpat:
                rows_spec["pattern"] = rpat
            cols = headers_for(grp)
            if cols:
                rows_spec["columns"] = cols
            else:
                warnings.append("columns 沒有自動填:" + ("沒有 th 表頭" if not grp.get("has_th") else "表頭沒有記錄、欄數對不上或有重複名稱")
                                + ";存檔前 Claude 必須依畫面填好每一格的欄名。")
    elif mark.get("text_truncated") or not norm_ws(text):
        issues.append(_issue("result_kind", "標記的文字超過 2000 字或是空的,錄製 v1 只支援 2000 字內的非空文字塊或非空表格。"))
    else:
        comparator = "text-contains-v1"

    # ---- 4b. steps (design 6.3) ----
    step_info = None
    if kind == "steps" and not issues:
        step_events = [e for e in events if e["type"] in ("click", "set")]
        step_info = _build_steps(step_events, groups, docs, snapshots, mark, rows_spec, issues, warnings)

    # ---- unsupported? ----
    if issues:
        first = dict(issues[0])
        if len(issues) > 1:
            first["all"] = [dict(i) for i in issues]
        out["unsupported"] = first
        out["demo"] = None
        return out

    # ---- 5. compose ----
    marked_norm = norm_ws(text)
    taken = set()
    if step_info is not None:
        fields = step_info["fields"]
    for i, f in enumerate(fields, 1):
        cands.append({"label": f["label"], "value": f["value"], "suggested_name": _slug(f["label"], taken, i), "from_default": f["from_default"],
                      "via_widget": f["via_widget"], "in_result_text": norm_ws(f["value"]) != "" and norm_ws(f["value"]) in marked_norm,
                      **({"kind": "field", "step_index": f["step_index"]} if step_info is not None else {})})
    if step_info is not None:
        for p in step_info["picks"]:
            v = p["want"]
            cands.append({"label": f"第 {p['step_index'] + 1} 步 pick 要找的列(點「{p['click']}」)", "value": v,
                          "suggested_name": _slug("want", taken, 0),
                          "from_default": False, "via_widget": False, "in_result_text": len(norm_ws(v)) >= 2 and norm_ws(v) in marked_norm,
                          "kind": "pick_want", "step_index": p["step_index"]})
    if pre:
        warnings.append("第一個欄位之前點了:" + "、".join(f"「{p['text']}」" for p in pre) + ";已建議成 pre(optional: true),需試跑確認可省略。")
    for f in fields:
        if f["via_widget"]:
            warnings.append(f"欄位「{f['label']}」的值是透過頁面元件(如日期選擇器格子)設定的,草稿改成直接填值:這是假設,"
                            "由示範值試跑驗證;不一致會回報 widget_value_not_replayable。")
        if f["from_default"]:
            warnings.append(f"欄位「{f['label']}」是網站預設值(示範者沒改);已寫進 fields,請決定要不要參數化。")
    suggested = [c["value"] for c in cands if c["in_result_text"] and len(norm_ws(c["value"])) >= 2]
    if rpat:
        for c in cands:
            v = norm_ws(c["value"])
            if len(v) >= 2 and _js_escape(v) in rpat:
                warnings.append(f"rows.pattern 有一格照抄了示範值「{v}」(欄位「{c['label']}」);把這個欄位參數化後,pattern 也要跟著改成 {{參數}} 或更通用的寫法,"
                                "否則換一組參數就選不到表。")
    if kind == "detail_extract":
        url = docs.get(mark["epoch"], {}).get("href") or ""
        if len(docs) > 1:
            warnings.append("示範沒有任何欄位/按鈕操作但換過文件;url 取標記結果的那一頁。")
    else:
        url = docs.get(action_epoch, {}).get("href") or ""
        if kind == "steps" and action_epoch is not None and len(docs) > 1:
            warnings.append(f"多頁流程:url 取第一個操作所在頁面({url})。")
    if not url:
        out["unsupported"] = _issue("no_url", "找不到操作頁面的網址(記錄裡沒有 hello)。")
        return out
    result: dict[str, Any] = {}
    if rows_spec is not None:
        result["rows"] = rows_spec
        if suggested:
            out["suggested_expect_text"] = suggested
    else:
        # one whitespace-free token: the engine looks for expect_text in the raw page text, where the marked text's spaces may be newlines
        toks = marked_norm.split(" ")[:6]
        anchor = suggested or [next((t for t in toks if len(t) >= 4), max(toks, key=len))[:30]]
        result["expect_text"] = anchor
        if not suggested:
            warnings.append("expect_text 只是取標記文字開頭的一個詞,不一定是固定內容:請改成這個結果一定會出現、不隨參數或時間變動的文字。")
    name = f"recorded-{recording_id}" if recording_id else "recorded-draft"
    draft: dict[str, Any] = {"name": name, "type": kind, "description": "(由示範錄製,請改寫成一句使用者看得懂的說明)"}
    if recording_id:
        draft["recorded_from"] = recording_id
    draft["url"] = url
    if kind == "form_submit":
        if pre:
            draft["pre"] = [{"click": p["text"], "optional": True} for p in pre]
        draft["fields"] = [{"label": f["label"], "kind": f["kind"], "value": f["value"]} for f in fields]
        assert submit is not None
        draft["submit"] = {"click": submit["text"]}
        draft["result"] = result
    elif kind == "steps":
        assert step_info is not None
        draft["steps"] = step_info["steps"]
        draft["result"] = result
    else:
        draft.update(result)
    todo = list(step_info["todo"]) if step_info is not None else []
    if rows_spec is not None and "pattern" not in rows_spec:
        todo.append("rows.pattern")
    if rows_spec is not None and "columns" not in rows_spec:
        todo.append("rows.columns")
    lc = _live(live_checks, rpat)
    if rpat:
        if lc.get("status") == "checked" and lc.get("pattern_specific") is False:
            warnings.append(f"候選 rows.pattern 在標記當下的頁面上不專一(命中 {lc.get('groups_matched')} 個群組"
                            + ("" if lc.get("fingerprint_equal") else ",且指紋和標記的表不同") + "):請自己寫一個只選中這張表的 pattern。")
            todo.append("rows.pattern(not specific)")
        elif lc.get("status") == "pending":
            warnings.append("候選 rows.pattern 的專一性沒有在頁面上檢查(stop 時頁面已離開標記的文件);"
                            "由 dry_run 的群組歧義檢查與示範一致檢查把關。")
    out.update(draft=draft, param_candidates=cands, live_checks=lc,
               demo={"comparator": comparator, "kind": kind, "marked_chars": len(marked_norm),
                     "marked_rows": len(grp["rows"]) if grp else None,
                     "actions": demo_actions(draft, {f["step_index"]: f["via_widget"] for f in fields} if step_info is not None
                                             else {f["label"]: f["via_widget"] for f in fields})})
    if step_info is not None:
        out["then_candidates"] = step_info["then_candidates"]
        if step_info["suggestions"]:
            out["step_suggestions"] = step_info["suggestions"]
        out["needs_review"] = step_info["needs_review"]
    if todo:
        out["draft_todo"] = todo
    return out


def _live(lc, pattern):
    if not pattern:
        return {"status": "not_applicable"}
    if isinstance(lc, dict) and lc.get("status") == "checked" and lc.get("pattern") == pattern:
        return lc
    return {"status": "pending", "reason": (lc or {}).get("reason", "not_checked"), "pattern": pattern, "pattern_specific": None}


def _describe(e):
    return {"click": f"點「{e.get('text', '')}」", "set": f"改「{e.get('label', '')}」"}.get(str(e["type"]), str(e["type"]))


def _events(g, snapshots, issues):
    """One action group -> zero or more events {type: click|set|enter, gi, epoch, ...}. Problems go to `issues`."""
    tgt, gi, keys = g["target"], g["index"], g["keys"]
    base = {"gi": gi, "epoch": g["epoch"], "gid": g["gid"], "prev": g["prev"], "snap": g["snap"]}
    if tgt.get("iframe"):
        issues.append(_issue("iframe_interaction", "示範裡操作了內嵌框(iframe),錄製看不到裡面。"))
        return []
    if tgt.get("is_button_like"):
        if g["kind"] != "pointer" and keys and set(keys) <= {"Tab", "Escape"}:
            return []
        if not g["nav_after"]:
            ws = _widget_sets(g, snapshots, issues, base)
            if ws is not None:
                return ws
        text = norm_ws(tgt.get("label") or tgt.get("text") or "")
        if not text:
            issues.append(_issue("unlabeled_click", "示範裡點了沒有文字的按鈕/連結,無法在流程裡指名它。"))
            return []
        return [{**base, "type": "click", "text": text, "nav_after": g["nav_after"]}]
    out = []
    prev, cur = snapshots.get(g["prev"] or ""), snapshots.get(g["snap"] or "")
    if g["kind"] != "pointer" and tgt.get("native") and cur is None:
        issues.append(_issue("unclosed_input_group", f"「{tgt.get('label') or tgt.get('tag')}」的最後一次輸入沒有記到結果(離開頁面太快),請重錄。"))
        return []
    for c in _changes(prev, cur) if prev is not None and cur is not None else []:
        label, kind = c["label"], c["kind"]
        if kind in ("checkbox", "radio"):
            issues.append(_issue("checkbox_radio", f"示範改了勾選/單選「{label}」,錄製 v1 不支援 checkbox/radio。", field=label))
            continue
        if c["ctl"].get("readonly"):
            issues.append(_issue("readonly_widget", f"「{label}」是唯讀欄位,值是被網站元件(如日期選擇器)改的,無法直接填寫。", field=label))
            continue
        if tgt.get("native") and c["id"] == tgt.get("id"):
            out.append({**base, "type": "set", "id": c["id"], "label": label, "kind": _kind_of(c["ctl"]), "value": c["after"], "via_widget": False})
        elif tgt.get("custom_element"):
            issues.append(_issue("custom_widget", f"「{label}」的值是被網站自訂元件改的,錄製無法確定它怎麼改,A 版不支援。", field=label))
        elif tgt.get("native"):
            continue       # a site side effect of typing in another field; the boundary check (dependent_reset) judges it
        else:
            out.append({**base, "type": "set", "id": c["id"], "label": label, "kind": _kind_of(c["ctl"]), "value": c["after"], "via_widget": True})
    if "Enter" in keys and tgt.get("tag") == "INPUT":
        out.append({**base, "type": "enter", "nav_after": g["nav_after"]})
    return out


def _widget_sets(g, snapshots, issues, base):
    """A button / link click that did NOT navigate but changed a native field's value is a picker control (the up/down
    arrows of a time picker, a calendar's day cell drawn as a link): keep the field's new value, drop the click.
    This is a hypothesis like every via_widget set; the isolated demo replay proves or refutes it. A real submit either
    navigates (nav_after) or changes no field, so it stays a click. Returns None when no field changed."""
    prev, cur = snapshots.get(g["prev"] or ""), snapshots.get(g["snap"] or "")
    if prev is None or cur is None:
        return None
    changes = [c for c in _changes(prev, cur) if c["kind"] not in ("checkbox", "radio")]
    if not changes:
        return None
    out = []
    for c in changes:
        if c["ctl"].get("readonly"):
            issues.append(_issue("readonly_widget", f"「{c['label']}」是唯讀欄位,值是被網站元件(如日期選擇器)改的,無法直接填寫。", field=c["label"]))
            continue
        out.append({**base, "type": "set", "id": c["id"], "label": c["label"], "kind": _kind_of(c["ctl"]), "value": c["after"], "via_widget": True})
    return out


def _collapse_retries(events, warnings):
    """A button pressed, nothing navigated, only field edits, then the SAME button again: the user retried after fixing
    the form (e.g. 查詢 with the same departure and arrival station, then again after changing one). Keep the last press."""
    out = list(events)
    i = 0
    while i < len(out):
        e = out[i]
        if e["type"] == "click" and not e.get("nav_after"):
            j = next((k for k in range(i + 1, len(out)) if out[k]["type"] != "set"), None)
            if (j is not None and j > i + 1 and out[j]["type"] == "click" and out[j]["text"] == e["text"]
                    and out[j]["epoch"] == e["epoch"]):  # at least one field was changed in between (a pager has none)
                warnings.append(f"第一次按「{e['text']}」沒有換頁,之後只改了欄位又按了一次:視為重試,只保留最後一次。")
                del out[i]
                continue
        i += 1
    return out


def _fillable(P):
    """The native, visible, non-sensitive text / select fields of one committed snapshot, and how often each (kind, label) occurs."""
    fl = []
    for c in P:
        if not isinstance(c, dict) or not c.get("native") or c.get("sensitive"):
            continue
        if c.get("kind") == "text" and (c.get("input_type") or "").lower() in _BUTTON_INPUT_TYPES:
            continue
        if c.get("kind") in ("select", "text"):
            fl.append(c)
    return fl, Counter((_kind_of(c), normalize(c.get("label", ""))) for c in fl)


def _edited_fields(sets, fl, counts, base_by_id, issues, fields):
    """The user's edits, one per field at its LAST value and in the order of the last edit, checked against the effective value
    at the boundary snapshot (V05, I2): a field the site reset afterwards is `dependent_reset`, a cleared one `cleared_field`."""
    by_id = {c["id"]: c for c in fl}
    set_last = {}
    for e in sets:
        set_last[e["id"]] = e
    for e in sorted(set_last.values(), key=lambda e: e["gi"]):
        c = by_id.get(e["id"])
        if c is None:  # the site re-rendered the form: match by kind + unique label
            cand = [x for x in fl if _kind_of(x) == e["kind"] and normalize(x.get("label", "")) == normalize(e["label"])]
            c = cand[0] if len(cand) == 1 else None
        if c is None:
            issues.append(_issue("dependent_reset", f"欄位「{e['label']}」在送出時已不在畫面上(被網站重設或移除)。", field=e["label"]))
            continue
        eff = c.get("value") or ""
        if norm_ws(eff) != norm_ws(e["value"]):
            issues.append(_issue("dependent_reset", f"欄位「{e['label']}」示範時設為「{e['value']}」,但送出時實際是「{eff}」"
                                 "(網站在你設定之後重設了它,例如換城市後清空區域);錄製轉出的流程無法表達這種先後相依,請 Claude 手寫並用試跑驗證。",
                                 field=e["label"]))
            continue
        if eff == "":
            b = base_by_id.get(e["id"])
            if b is not None and (b.get("value") or "") != "":
                issues.append(_issue("cleared_field", f"欄位「{e['label']}」被清空了;流程無法表達「清空」,請 Claude 手寫並用試跑驗證。", field=e["label"]))
            continue
        _add_field(c, counts, issues, fields, from_default=False, via_widget=bool(e["via_widget"]))


def _boundary_fields(submit, sets, snapshots, doc, issues, warnings):
    """The effective value of every fillable field at the moment of the submit click (V05, I2)."""
    P = snapshots.get(submit.get("prev") or "")
    if P is None:
        issues.append(_issue("no_boundary_snapshot", "找不到送出前一刻的欄位快照,無法確定各欄位的值。"))
        return []
    base = snapshots.get(doc.get("baseline") or "") or []
    base_by_id = _by_id(base)
    fl, counts = _fillable(P)
    set_ids = {e["id"] for e in sets}
    fields = []
    # fields the user never edited: DOM order
    for c in fl:
        if c["id"] in set_ids:
            continue
        v = c.get("value") or ""
        b = base_by_id.get(c["id"])
        if v == "":
            if b is not None and (b.get("value") or "") != "":
                issues.append(_issue("cleared_field", f"欄位「{c.get('label')}」的預設值被清空了;流程無法表達「清空」,請 Claude 手寫並用試跑驗證。", field=c.get("label")))
            continue
        if c.get("readonly"):
            warnings.append(f"唯讀欄位「{c.get('label')}」有預設值,不由流程填寫(網站自己帶入)。")
            continue
        _add_field(c, counts, issues, fields, from_default=True, via_widget=False, warnings=warnings)
    # fields the user edited: order of the last edit
    _edited_fields(sets, fl, counts, base_by_id, issues, fields)
    return fields


def _add_field(c, counts, issues, fields, from_default, via_widget, warnings=None):
    label = norm_ws(c.get("label", ""))
    unnameable = not label or counts[(_kind_of(c), normalize(label))] > 1
    unfillable = (c.get("input_type") or "").lower() in _UNFILLABLE_INPUT_TYPES
    if from_default and warnings is not None and (unnameable or unfillable):
        # A value the user never touched and a flow cannot name: leave it to the site's default. If that default came
        # from the demo's browser state rather than the site, the isolated demo replay differs and the draft cannot be saved.
        warnings.append(f"欄位「{label or '(沒有名稱)'}」使用者沒動過,值「{c.get('value')}」是網站預設;流程無法指名它,不寫入,"
                        "靠隔離重播確認它不影響結果。")
        return
    if unfillable:
        issues.append(_issue("unsupported_input_type", f"欄位「{label}」是 {c.get('input_type')} 類型,A 版不支援。", field=label))
        return
    if unnameable:
        issues.append(_issue("ambiguous_field_label", f"有值的欄位「{label or '(沒有名稱)'}」沒有名稱或和別的欄位重名,流程無法唯一指名它;"
                             "不能默默略過(值會影響結果)。", field=label))
        return
    fields.append({"label": label, "kind": _kind_of(c), "value": c.get("value") or "", "from_default": from_default, "via_widget": via_widget})


# =====================================================================================================
# steps drafts (design 6.3): every click a `click` step, the edits between two clicks `fill` / `select` steps before the
# next click, `then` only as candidates, a list-row click suggested as `pick`, a repeated pager click as `next_page`.
# =====================================================================================================

_FIELD_LIKE = ("text", "select", "checkbox", "radio")
_CLICKABLE_KINDS = ("button", "link")
# same rule steps._kev_text uses (kept here: steps imports recipes, which imports this module): cells that are only prices / numbers
_NOISE_CELL = re.compile(r"^[\s$¥￥€£NTDUSRMBnt元圓円.,:%/+\-\d]*$")
THEN_PLACEHOLDER = "<待填>"


def _labels(controls, kinds):
    return [norm_ws(c.get("label") or "") for c in controls or [] if isinstance(c, dict) and c.get("kind") in kinds and not c.get("sensitive")]


def _dedupe(xs):
    seen, out = set(), []
    for x in xs:
        k = normalize(x)
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _url_token(h0, h1):
    """What changed in the URL, as a piece of the new one worth waiting for (url_contains), or None."""
    if not h0 or not h1 or h0 == h1:
        return None
    a, b = urlsplit(h0), urlsplit(h1)
    if a.path != b.path:
        seg = b.path.rstrip("/").rsplit("/", 1)[-1]
        if seg and seg not in h0:
            return seg
        return b.path if b.path not in ("", "/") else None
    if a.query != b.query:
        old = set(a.query.split("&"))
        for kv in b.query.split("&"):
            if kv and kv not in old:
                return kv
    if a.fragment != b.fragment and b.fragment:
        return "#" + b.fragment
    return None


def _group_change(r0, r1, mg):
    """Did the marked result table (by fingerprint, else by row signature) appear or change between two observations?"""
    if not r1 or not mg or r0 is None:
        return False
    gs1 = r1.get("groups") or []
    g1 = next((x for x in gs1 if x.get("fp") == mg.get("fingerprint")), None) or next(
        (x for x in gs1 if mg.get("sig") and x.get("sig") == mg["sig"]), None)
    if g1 is None:
        return False
    g0 = next((x for x in r0.get("groups") or [] if x.get("sig") and x.get("sig") == g1.get("sig")), None)
    return g0 is None or g0.get("fp") != g1.get("fp")


def _res_after(g, groups, mark):
    """The result groups after a click that stayed in its document: what the next click saw just before it, else the marked table."""
    for g2 in groups[g["index"] + 1:]:
        if g2["epoch"] != g["epoch"]:
            break
        if g2.get("res"):
            return g2["res"]
    m = mark.get("group")
    if mark["epoch"] == g["epoch"] and m and m.get("rows"):
        return {"groups": [{"fp": m.get("fingerprint"), "n": m.get("total", 0), "cols": len(m["rows"][0]), "sig": m.get("sig") or ""}], "heads": []}
    return None


def _click_context(g, groups, docs, snapshots, mark):
    """The page before a click and the page after it: committed control snapshots, result-group observations, URLs."""
    ctx: dict[str, Any] = {"P": snapshots.get(g["prev"] or ""), "A": None, "R0": g.get("res"), "R1": None,
                           "H0": docs.get(g["epoch"], {}).get("href") or None, "H1": None, "nav": False}
    if g["snap"] is None or g["nav_after"]:                  # the document went away: the next document's baseline is the "after"
        later = sorted(e for e in docs if e > g["epoch"])
        if later:
            nd = docs[later[0]]
            ctx.update(A=snapshots.get(nd.get("baseline") or ""), R1=nd.get("res"), H1=nd.get("href") or None, nav=True)
            return ctx
    if g["snap"]:
        ctx["A"] = snapshots.get(g["snap"])
        ctx["R1"] = _res_after(g, groups, mark)
    return ctx


def _then_candidates(text, ctx, mg, rows_ok):
    """Candidate `then` conditions, best first: a new field label, new prominent text (a heading or a new button/link),
    the URL change, the result table changing, the clicked control gone. Only candidates: the converter never decides."""
    P, A, r0, r1 = ctx["P"], ctx["A"], ctx["R0"], ctx["R1"]
    out: list[dict[str, Any]] = []
    if P is not None and A is not None:
        before = {normalize(x) for x in _labels(P, _FIELD_LIKE)}
        after = _labels(A, _FIELD_LIKE)
        fresh = [x for x in _dedupe(after) if normalize(x) not in before and sum(1 for y in after if normalize(y) == normalize(x)) == 1]
        out += [{"field": x} for x in fresh[:3]]
        heads0 = {normalize(x) for x in (r0 or {}).get("heads") or []} if r0 is not None else None
        heads = [h for h in (r1 or {}).get("heads") or [] if heads0 is not None and normalize(h) not in heads0 and len(norm_ws(h)) >= 2]
        btn0 = {normalize(x) for x in _labels(P, _CLICKABLE_KINDS)}
        btns = [x for x in _labels(A, _CLICKABLE_KINDS) if normalize(x) not in btn0 and len(x) >= 2 and normalize(x) != normalize(text)]
        out += [{"text": t} for t in _dedupe(heads + btns)[:3]]
    tok = _url_token(ctx["H0"], ctx["H1"])
    if tok:
        out.append({"url_contains": tok})
    if rows_ok and _group_change(r0, r1, mg):
        out.append({"rows": True})
    if P is not None and A is not None and ctx["A"] is not None:
        n = normalize(text)
        was = [c for c in P if isinstance(c, dict) and c.get("kind") in _CLICKABLE_KINDS and normalize(c.get("label") or "") == n]
        now = [c for c in A if isinstance(c, dict) and c.get("kind") in _CLICKABLE_KINDS and n in normalize(c.get("label") or "")]
        if len(was) == 1 and not now:
            out.append({"gone": text})
    return out


def _pick_for(e, g, ctx, mark, warnings):
    """A click on a control inside a repeating list row, after which the URL changed and a mark follows: the demonstrator chose
    one row of a list. -> {step, want, pattern, click, rows} or None (a plain click stays a click)."""
    row = g.get("row")
    if not row or not ctx["nav"] or not ctx["H1"] or ctx["H1"] == ctx["H0"] or mark["epoch"] <= g["epoch"]:
        return None
    rows, texts = row.get("rows") or [], row.get("texts") or []
    if len(rows) < 2:
        return None
    ct = normalize(e["text"])
    meaningful = [c for c in row.get("cells") or [] if c and normalize(c) != ct and not _NOISE_CELL.match(c)]
    if not meaningful:
        return None
    unique = [c for c in meaningful if sum(1 for r in rows if c in r) == 1]
    want = unique[0] if unique else meaningful[0]
    pattern = row_pattern(rows, texts) or row_pattern(rows, texts, joiner=r"\s*")
    if pattern is None:
        warnings.append(f"點「{e['text']}」看起來是在列表(共 {row.get('total')} 列)裡選了一列,但程式無法從各列推出 rows.pattern(格數不一致或列文字被截斷),"
                        "沒有建議 pick;草稿保留為 click(同名按鈕會不唯一)。請看畫面自己寫 pick。")
        return None
    if not unique:
        warnings.append(f"pick 要找的列「{want}」在列表裡不是唯一的(多列有相同文字):請把 want 改成能分辨這一列的內容。")
    return {"step": {"pick": {"rows": {"pattern": pattern}, "want": want, "click": e["text"]}}, "want": want, "pattern": pattern,
            "click": e["text"], "rows": row.get("total")}


def _flush_fields(pending, snap_id, epoch, docs, snapshots, steps, meta, issues):
    """Turn the edits since the previous click into fill/select steps (same effective-value rules as version A)."""
    P = snapshots.get(snap_id or "")
    if P is None:
        issues.append(_issue("no_boundary_snapshot", "找不到點擊前一刻的欄位快照,無法確定各欄位的值。"))
        return
    base_by_id = _by_id(snapshots.get(docs.get(epoch, {}).get("baseline") or "") or [])
    fl, counts = _fillable(P)
    fields: list[dict[str, Any]] = []
    _edited_fields(pending, fl, counts, base_by_id, issues, fields)
    for f in fields:
        steps.append({"select" if f["kind"] == "select" else "fill": f["label"], "value": f["value"]})
        meta.append({**f, "step_index": len(steps) - 1})


def _build_steps(events, groups, docs, snapshots, mark, rows_spec, issues, warnings):
    """events: the demonstration's click / set events in order. -> {steps, fields, picks, then_candidates, suggestions, needs_review,
    todo}; problems go to `issues` (unsupported), never silently dropped."""
    rows_ok = bool(rows_spec and rows_spec.get("pattern"))
    mg = mark.get("group") if rows_ok else None
    steps: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    picks: list[dict[str, Any]] = []
    clicks: dict[int, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for e in events:
        if e["type"] == "set":
            pending.append(e)
            continue
        g = groups[e["gi"]]
        if pending:
            _flush_fields(pending, e.get("prev"), e["epoch"], docs, snapshots, steps, fields, issues)
            pending = []
        ctx = _click_context(g, groups, docs, snapshots, mark)
        pk = _pick_for(e, g, ctx, mark, warnings)
        if pk:
            picks.append({"step_index": len(steps), "want": pk["want"], "click": pk["click"], "pattern": pk["pattern"], "rows": pk["rows"]})
            steps.append(pk["step"])
            continue
        cands = _then_candidates(e["text"], ctx, mg, rows_ok)
        clicks[len(steps)] = {"text": e["text"], "cands": cands, "rows_change": rows_ok and _group_change(ctx["R0"], ctx["R1"], mg)}
        steps.append({"click": e["text"], "then": None})
    if pending:
        last = pending[-1]
        warnings.append("最後一次點擊之後又填了欄位,沒有點擊可以證明它生效;結果由 result 的檢查與示範值試跑把關。")
        _flush_fields(pending, last.get("snap"), last["epoch"], docs, snapshots, steps, fields, issues)

    # repeated same-text clicks that each change the result table: a pager
    suggestions: list[dict[str, Any]] = []
    in_run: set[int] = set()
    i = 0
    while i < len(steps):
        if i in clicks:
            j = i
            while j + 1 < len(steps) and j + 1 in clicks and normalize(clicks[j + 1]["text"]) == normalize(clicks[i]["text"]):
                j += 1
            if j > i and all(clicks[k]["rows_change"] for k in range(i, j + 1)):
                in_run.update(range(i, j + 1))
                np = {"click": clicks[i]["text"], "max_pages": j - i + 2, "end": ""}
                last = j == len(steps) - 1
                suggestions.append({"kind": "next_page", "step_indices": list(range(i, j + 1)), "next_page": np,
                                    "can_replace_now": last, "note": "end 要 Claude 試跑後看尾頁的樣子填 disabled 或 absent;next_page 只能是最後一步"})
                warnings.append(f"連續點了 {j - i + 1} 次「{clicks[i]['text']}」且每次結果表都變了:建議改成最後一步 "
                                f"{{\"next_page\": {{\"click\": \"{clicks[i]['text']}\", \"max_pages\": {j - i + 2}, \"end\": \"\"}}}}。"
                                "end 留空,要試跑後看尾頁是按鈕變 disabled 還是消失才能填;"
                                + ("" if last else "但它們不是最後一步,next_page 只能放在最後,所以草稿保留為一般 click。"))
            i = j + 1
        else:
            i += 1
    for p in picks:
        suggestions.append({"kind": "pick", "step_index": p["step_index"], "want": p["want"], "click": p["click"],
                            "rows_pattern": p["pattern"], "list_rows": p["rows"]})
        warnings.append(f"steps[{p['step_index']}]:示範在列表(共 {p['rows']} 列)點了某一列的「{p['click']}」,草稿寫成 pick:want=「{p['want']}」"
                        f"(該列有意義的文字,請參數化)、click=「{p['click']}」、rows.pattern 是從列表各列推出的候選(dry_run 會檢查它只選中這張列表)。")

    then_cands, review, todo = [], [], []
    for idx, m in clicks.items():
        cands = m["cands"]
        if idx in in_run and {"rows": True} in cands:
            cands = [{"rows": True}] + [c for c in cands if c != {"rows": True}]
        if cands:
            chosen = cands[0]
            rest = "、".join(json.dumps(c, ensure_ascii=False) for c in cands[1:])
            warnings.append(f"steps[{idx}] 點「{m['text']}」的 then 是程式從點擊後的畫面推出的候選,不是最終決定:預設 "
                            f"{json.dumps(chosen, ensure_ascii=False)}" + (f";其他候選 {rest}" if rest else "")
                            + "。then 必須「點擊前為假、點擊後為真」,請試跑後確認或換一個。")
        else:
            chosen = {"text": THEN_PLACEHOLDER}
            todo.append(f"steps[{idx}].then")
            warnings.append(f"steps[{idx}] 點「{m['text']}」沒有推得任何 then 候選(畫面前後沒有可辨認的差異或記錄不足):"
                            f"草稿先填 {{\"text\": \"{THEN_PLACEHOLDER}\"}} 佔位,必須由 Claude 看畫面改成點擊後才會出現的條件。")
        steps[idx]["then"] = chosen
        if "gone" in chosen and normalize(chosen["gone"]) == normalize(m["text"]):
            warnings.append(f"steps[{idx}] 點「{m['text']}」之後這個按鈕就消失了,像是可關閉的橫幅(同意 cookie、關閉公告):在使用者自己的 profile 裡"
                            "它可能已經被關過、之後找不到。是否加 optional: true 由 Claude 試跑後決定(optional 只跳過找不到,不跳過不唯一)。")
        then_cands.append({"step_index": idx, "click": m["text"], "chosen": chosen, "candidates": cands})
        review.append({"step_index": idx, "what": "then", "reason": "候選由程式推得,需 Claude 試跑確認" if cands else "沒有候選,是佔位"})
    for sg in suggestions:
        if sg["kind"] == "next_page":
            review.append({"step_indices": sg["step_indices"], "what": "next_page.end", "reason": "end 留空,要試跑後填"})
    return {"steps": steps, "fields": fields, "picks": picks, "then_candidates": then_cands, "suggestions": suggestions,
            "needs_review": review, "todo": todo}


# =====================================================================================================
# demonstration actions, rendered actions, comparators
# =====================================================================================================

def demo_actions(draft, via_widget=None):
    """The demonstration as normalised executable actions (same shape as rendered_actions)."""
    a = _actions_of(draft)
    if via_widget is not None and a.get("fields"):
        for f in a["fields"]:
            f["via_widget"] = bool(via_widget.get(f["label"]))
    if via_widget is not None and a.get("steps"):           # steps drafts: keyed by step index
        for i, st in enumerate(a["steps"]):
            if st["op"] in ("fill", "select"):
                st["via_widget"] = bool(via_widget.get(i))
    return a


def via_widget_labels(actions):
    """Labels of the demonstrated fields whose value came from a page widget (form_submit fields or steps fill/select)."""
    fs = (actions or {}).get("fields") or [st for st in (actions or {}).get("steps") or [] if st.get("op") in ("fill", "select")]
    return [f.get("label") or f.get("target") for f in fs if f.get("via_widget")]


def _step_action(st):
    """One step as a normalised action: what is done to which target with which value (never its `then`)."""
    if "click" in st:
        return {"op": "click", "target": norm_ws(st["click"]), "optional": bool(st.get("optional")), "stateful": bool(st.get("stateful"))}
    for op in ("fill", "select", "check"):
        if op in st:
            return {"op": op, "target": norm_ws(st[op]), "value": st.get("value")}
    if "wait" in st:
        return {"op": "wait", "target": norm_ws((st["wait"] or {}).get("text", ""))}
    if "pick" in st:
        pk = st["pick"] or {}
        return {"op": "pick", "target": norm_ws(pk.get("click", "")), "want": pk.get("want"), "pattern": (pk.get("rows") or {}).get("pattern")}
    np = st.get("next_page") or {}
    return {"op": "next_page", "target": norm_ws(np.get("click", "")), "max_pages": np.get("max_pages"), "end": np.get("end")}


def _core_steps(actions, skippable=()):
    """The actions that make a run "the demonstration": waits and optional clicks are Claude's additions and do not count, a
    next_page stands for the (max_pages - 1) page clicks the demonstrator made, a pick for (click, want). `skippable`: click
    targets the compared recipe marked optional; the demonstration's own click on such a target does not count either (an
    optional click may find its banner already gone, exactly like a suggested `pre` in version A)."""
    out = []
    for st in actions.get("steps") or []:
        op = st["op"]
        if op == "wait" or (op == "click" and (st.get("optional") or st["target"] in skippable)):
            continue
        if op == "next_page":
            out += [("click", st["target"], None)] * max(int(st.get("max_pages") or 1) - 1, 0)
        elif op == "pick":
            out.append(("pick", st["target"], st.get("want")))
        elif op == "click":
            out.append(("click", st["target"], None))
        else:
            out.append((op, st["target"], st.get("value")))
    return out


def _actions_of(r):
    if r.get("type") == "steps":
        return {"type": "steps", "url": r.get("url"), "steps": [_step_action(st) for st in r.get("steps") or [] if isinstance(st, dict)]}
    if r.get("type") == "form_submit":
        return {"type": "form_submit", "url": r.get("url"),
                "pre": [{"click": norm_ws(p.get("click", "")), "optional": bool(p.get("optional"))} for p in r.get("pre") or []],
                "fields": [{"label": norm_ws(f.get("label", "")), "kind": "select" if f.get("kind") == "select" else "text",
                            "value": f.get("value")} for f in r.get("fields") or []],
                "submit": norm_ws((r.get("submit") or {}).get("click", ""))}
    return {"type": r.get("type"), "url": r.get("url")}


def rendered_actions(rendered_recipe):
    """The executable, normalised actions of a rendered form_submit / detail_extract recipe. Only what runs: a parameter no
    action refers to changes nothing here, so it cannot change the hash (I5)."""
    return _actions_of(rendered_recipe)


def actions_hash(actions):
    """Hash of the executable actions only (the via_widget annotation of a demonstration is not an action)."""
    a = dict(actions)
    if "fields" in a:
        a["fields"] = [{k: v for k, v in f.items() if k != "via_widget"} for f in a["fields"]]
    if "steps" in a:
        a["steps"] = [{k: v for k, v in st.items() if k != "via_widget"} for st in a["steps"]]
    return hashlib.sha256(json.dumps(a, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def is_demo_run(actions, demo):
    """Do the rendered actions carry the demonstration's own values? url, every field (label, kind, value, order) and the
    submit click. `pre` clicks are optional suggestions Claude may drop after a trial, so they do not decide it."""
    if not demo or actions.get("type") != demo.get("type") or actions.get("url") != demo.get("url"):
        return False
    if actions.get("type") == "steps":
        skippable = {st["target"] for st in actions.get("steps") or [] if st["op"] == "click" and st.get("optional")}
        return _core_steps(actions) == _core_steps(demo, skippable)
    if actions.get("type") == "form_submit":
        strip = lambda fs: [(f["label"], f["kind"], f["value"]) for f in fs]  # noqa: E731
        return strip(actions.get("fields") or []) == strip(demo.get("fields") or []) and actions.get("submit") == demo.get("submit")
    return True


def compare_rows_exact(demo_group, replay):
    """rows-exact-v1. demo_group: the mark's group payload. replay: {rows, total, truncated} of the replayed group
    (canonical raw cells, columns NOT applied). Equal group total, every cell equal after normalisation; truncation or an
    empty side is a mismatch. -> (match, diff)."""
    d_rows = (demo_group or {}).get("rows") or []
    d_total = (demo_group or {}).get("total", 0)
    d_trunc = bool((demo_group or {}).get("truncated")) or (demo_group or {}).get("rows_sent", len(d_rows)) < d_total
    r_rows = (replay or {}).get("rows") or []
    r_total = (replay or {}).get("total", 0)
    diff = {"comparator": "rows-exact-v1", "demo_total": d_total, "replay_total": r_total}
    if not d_rows or not d_total:
        return False, {**diff, "why": "示範的表是空的,不能拿來比對"}
    if not r_rows or not r_total:
        return False, {**diff, "why": "重播後沒有取到結果表(空的)"}
    if d_trunc or (replay or {}).get("truncated"):
        return False, {**diff, "why": "示範或重播的表被截斷(超過 200 列或資料量上限),無法逐格比對"}
    if d_total != r_total or len(d_rows) != len(r_rows):
        return False, {**diff, "why": f"列數不同:示範 {d_total} 列,重播 {r_total} 列"}
    for i, (a, b) in enumerate(zip(d_rows, r_rows)):
        if len(a) != len(b) or any(normalize(x) != normalize(y) for x, y in zip(a, b)):
            return False, {**diff, "why": f"第 {i + 1} 列的內容不同", "row": i + 1, "demo": [c[:60] for c in a[:12]], "replay": [c[:60] for c in b[:12]]}
    return True, diff


def compare_text_contains(demo_text, page_text):
    """text-contains-v1: the marked text (normalised, non-empty) appears whole in the replayed page's text."""
    t, p = norm_ws(demo_text), norm_ws(page_text)
    diff = {"comparator": "text-contains-v1", "demo_chars": len(t), "page_chars": len(p)}
    if not t:
        return False, {**diff, "why": "示範標記的文字是空的"}
    if t in p:
        return True, diff
    # where the match stops, so Claude sees what changed
    k = 0
    for k in range(len(t), 0, -1):
        if t[:k] in p:
            break
    else:
        k = 0
    return False, {**diff, "why": "標記的文字沒有完整出現在重播後的頁面", "matched_prefix_chars": k,
                   "demo_next": t[k:k + 60]}


# =====================================================================================================
# compare_to: how the demonstration differs from an existing recipe (7.1)
# =====================================================================================================

def _render(v, params):
    return re.sub(r"\{(\w+)\}", lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), v) if isinstance(v, str) else v


def _step_view(st):
    a = _step_action(st)
    v = {"op": a["op"], "target": a["target"], "value": a.get("value"), "extra": {}}
    if a["op"] == "pick":
        v["value"], v["extra"] = a.get("want"), {"pattern": a.get("pattern")}
    elif a["op"] == "next_page":
        v["extra"] = {"max_pages": a.get("max_pages"), "end": a.get("end")}
    return v                     # optional / stateful are Claude's decisions, never something a demonstration shows: not diffed


def _brief(v):
    return {"op": v["op"], "target": v["target"], **({"value": v["value"]} if v["value"] is not None else {})}


def _diff_steps(d_steps, r_steps, ex):
    """The demonstrated step sequence against a recipe's: same operation on the same target is the same step; an unmatched step of the
    same operation is a rename (a control's label changed) when it is the only candidate (fill/select/check also need the same value);
    the rest were added / removed. Then values, per-operation details (pick pattern, next_page limits, optional/stateful) and order."""
    ch = []
    pairs = []                                   # (recipe index, demo index)
    used_r, used_d = set(), set()
    for di, d in enumerate(d_steps):
        for ri, r in enumerate(r_steps):
            if ri not in used_r and (r["op"], r["target"]) == (d["op"], d["target"]):
                pairs.append((ri, di))
                used_r.add(ri)
                used_d.add(di)
                break
    renamed = []
    for op in dict.fromkeys(v["op"] for v in d_steps + r_steps):
        ru = [i for i in range(len(r_steps)) if i not in used_r and r_steps[i]["op"] == op]
        du = [i for i in range(len(d_steps)) if i not in used_d and d_steps[i]["op"] == op]
        if op in ("fill", "select", "check"):
            for di in list(du):
                m = next((ri for ri in ru if _render(r_steps[ri]["value"], ex) == d_steps[di]["value"]), None)
                if m is not None:
                    renamed.append((m, di))
                    ru.remove(m)
                    du.remove(di)
        elif len(ru) == len(du):
            renamed += list(zip(ru, du))
            ru, du = [], []
        for ri, di in renamed:
            used_r.add(ri)
            used_d.add(di)
    for ri, di in renamed:
        r, d = r_steps[ri], d_steps[di]
        ch.append({"kind": "step_renamed", "op": d["op"], "recipe": r["target"], "demo": d["target"], "recipe_index": ri, "demo_index": di})
    pairs += renamed
    ch += [{"kind": "step_added", "index": di, "step": _brief(d_steps[di])} for di in range(len(d_steps)) if di not in used_d]
    ch += [{"kind": "step_removed", "index": ri, "step": _brief(r_steps[ri])} for ri in range(len(r_steps)) if ri not in used_r]
    for ri, di in sorted(pairs, key=lambda x: x[1]):
        r, d = r_steps[ri], d_steps[di]
        if r["op"] in ("fill", "select", "check", "pick"):
            shown = _render(r["value"], ex)
            if isinstance(shown, str) and re.search(r"\{\w+\}", shown):
                ch.append({"kind": "step_value_param_unresolved", "op": r["op"], "target": d["target"], "recipe": r["value"], "demo": d["value"]})
            elif shown != d["value"]:
                ch.append({"kind": "step_value", "op": r["op"], "target": d["target"], "recipe": shown, "demo": d["value"],
                           **({"recipe_template": r["value"]} if shown != r["value"] else {})})
        for k in sorted(set(r["extra"]) | set(d["extra"])):
            rv, dv = _render(r["extra"].get(k), ex), d["extra"].get(k)
            if k == "pattern":
                if rv != dv:
                    ch.append({"kind": "step_pick_pattern", "target": d["target"], "recipe": rv, "demo": dv})
            elif rv != dv:
                ch.append({"kind": "step_next_page", "field": k, "target": d["target"], "recipe": rv, "demo": dv})
    ordered = [di for _, di in sorted(pairs, key=lambda x: x[0])]
    if ordered != sorted(ordered):
        ch.append({"kind": "order", "recipe": [r_steps[ri]["target"] for ri, _ in sorted(pairs, key=lambda x: x[0])],
                   "demo": [d_steps[di]["target"] for _, di in sorted(pairs, key=lambda x: x[1])]})
    return ch


def _view(r):
    if not isinstance(r, dict):
        return None
    t = r.get("type")
    if t == "steps":
        res = r.get("result") or {}
        return {"type": t, "url": r.get("url"), "steps": [_step_view(st) for st in r.get("steps") or [] if isinstance(st, dict)],
                "rows": res.get("rows"), "expect_text": res.get("expect_text") or []}
    if t == "form_submit":
        res = r.get("result") or {}
        return {"type": t, "url": r.get("url"), "pre": [(norm_ws(p.get("click", "")), bool(p.get("optional"))) for p in r.get("pre") or []],
                "fields": [(norm_ws(f.get("label", "")), f.get("kind"), f.get("value")) for f in r.get("fields") or []],
                "submit": norm_ws((r.get("submit") or {}).get("click", "")), "rows": res.get("rows"), "expect_text": res.get("expect_text") or []}
    if t == "detail_extract":
        return {"type": t, "url": r.get("url"), "pre": [], "fields": [], "submit": None, "rows": r.get("rows"), "expect_text": r.get("expect_text") or []}
    return None


def diff_against_recipe(draft, recipe):
    """{same, changes[]}: the demonstrated action sequence (type, target, value, order) and result contract against an
    existing recipe. Recipe values that are {params} are compared through the params' examples; without one they are reported
    as not comparable, never as equal."""
    d, r = _view(draft), _view(recipe)
    if d is None:
        return {"same": False, "error": "沒有草稿可以比對"}
    if r is None:
        return {"same": False, "error": f"compare_to 只支援 form_submit / detail_extract / steps 流程(這份是 {recipe.get('type')})"}
    ex = {k: v.get("example") for k, v in (recipe.get("params") or {}).items() if v.get("example") is not None}
    ch = []
    if d["type"] != r["type"]:
        ch.append({"kind": "type", "recipe": r["type"], "demo": d["type"]})
    if d["url"] != r["url"]:
        ch.append({"kind": "url", "recipe": r["url"], "demo": d["url"]})
    if d["type"] == "steps" and r["type"] == "steps":
        ch += _diff_steps(d["steps"], r["steps"], ex)
        return _diff_result(d, r, ch, ex)
    if "steps" in (d["type"], r["type"]):
        ch.append({"kind": "steps_vs_other", "note": "一邊是 steps、另一邊不是:動作序列的形狀不同,不逐步比對"})
        return _diff_result(d, r, ch, ex)
    rp, dp = {c for c, _ in r["pre"]}, {c for c, _ in d["pre"]}
    ch += [{"kind": "pre_added", "click": c} for c in sorted(dp - rp)] + [{"kind": "pre_removed", "click": c} for c in sorted(rp - dp)]
    rl, dl = {f[0]: f for f in r["fields"]}, {f[0]: f for f in d["fields"]}
    added, removed = [f for f in d["fields"] if f[0] not in rl], [f for f in r["fields"] if f[0] not in dl]
    for f in list(removed):
        m = next((a for a in added if a[1] == f[1] and _render(f[2], ex) == a[2]), None)
        if m:
            ch.append({"kind": "field_renamed", "from": f[0], "to": m[0], "value": m[2]})
            added.remove(m)
            removed.remove(f)
    ch += [{"kind": "field_added", "label": f[0], "value": f[2], "field_kind": f[1]} for f in added]
    ch += [{"kind": "field_removed", "label": f[0], "value": f[2], "field_kind": f[1]} for f in removed]
    for lab in [f[0] for f in d["fields"] if f[0] in rl]:
        (_, dk, dv), (_, rk, rv) = dl[lab], rl[lab]
        if (dk == "select") != (rk == "select"):
            ch.append({"kind": "field_kind", "label": lab, "recipe": rk, "demo": dk})
        shown = _render(rv, ex)
        if isinstance(shown, str) and re.search(r"\{\w+\}", shown):
            ch.append({"kind": "field_value_param_unresolved", "label": lab, "recipe": rv, "demo": dv})
        elif shown != dv:
            ch.append({"kind": "field_value", "label": lab, "recipe": shown, "demo": dv, **({"recipe_template": rv} if shown != rv else {})})
    common_r = [f[0] for f in r["fields"] if f[0] in dl]
    common_d = [f[0] for f in d["fields"] if f[0] in rl]
    if common_r != common_d:
        ch.append({"kind": "order", "recipe": common_r, "demo": common_d})
    if d["submit"] != r["submit"]:
        ch.append({"kind": "submit", "recipe": r["submit"], "demo": d["submit"]})
    return _diff_result(d, r, ch, ex)


def _diff_result(d, r, ch, ex):
    dr, rr = d["rows"], r["rows"]
    if bool(dr) != bool(rr):
        ch.append({"kind": "result_kind", "recipe": "rows" if rr else "text", "demo": "rows" if dr else "text"})
    elif dr and rr:
        for k in ("pattern", "columns", "min_rows"):
            if dr.get(k) != rr.get(k):
                ch.append({"kind": f"result_{k}", "recipe": rr.get(k), "demo": dr.get(k)})
    de, re_ = [_render(x, ex) for x in d["expect_text"]], [_render(x, ex) for x in r["expect_text"]]
    if sorted(de) != sorted(re_):
        ch.append({"kind": "result_expect_text", "recipe": re_, "demo": de})
    return {"same": not ch, "changes": ch}
