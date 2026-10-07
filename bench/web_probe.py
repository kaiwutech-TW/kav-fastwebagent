# -*- coding: utf-8 -*-
"""
Offline probe: does Kev make jev-ultrafast's per-step decision correctly on a Traditional Chinese
page, and how fast is it locally? No browser. Feeds hand-written snapshots of a THSR-style
booking form (same action shape snapshot.js produces) through jev-ultrafast's unmodified
choose(), with only the endpoint redirected to the local Kev server.

Usage (from vendor/jev-ultrafast, after `uv sync`):
  uv run python ../../bench/web_probe.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "jev-ultrafast"))
import jev_ultrafast.model as m  # noqa: E402

KEV_URL = os.environ.get("KEV_URL", "http://127.0.0.1:8009") + "/v1/systemone"
_post = m.post_json
m.post_json = lambda url, key, body: _post(KEV_URL, key, {**body, "model": "kev-latest"})
os.environ.setdefault("TYPESAFE_API_KEY", "local")

STATIONS = ["南港", "台北", "板橋", "桃園", "新竹", "苗栗", "台中", "彰化", "雲林", "嘉義", "台南", "左營"]
TIMES = ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]
GOAL = "查詢 10 月 5 日從台北到左營、早上 8 點左右出發的高鐵標準車廂成人票 1 張,看到車次列表就停。"


def select(node, label, options, current):
    return [{"node": node, "role": "combobox", "label": f"{label} → {o}", "kind": "select",
             "value": o, "current_value": current} for o in options if o != current]


def page(origin="南港", dest="南港", date="", time_="06:00", results=False):
    acts = [
        {"node": "n1", "role": "link", "label": "首頁", "kind": "click", "value": ""},
        {"node": "n2", "role": "link", "label": "時刻表與票價", "kind": "click", "value": ""},
        {"node": "n3", "role": "link", "label": "會員登入", "kind": "click", "value": ""},
        {"node": "n4", "role": "link", "label": "English", "kind": "click", "value": ""},
    ]
    acts += select("s1", "起程站", STATIONS, origin)
    acts += select("s2", "到達站", STATIONS, dest)
    acts += [{"node": "d1", "role": "textbox", "label": "去程日期", "kind": "fill", "value": date},
             {"node": "d1", "role": "textbox", "label": "Open 去程日期", "kind": "click", "value": date}]
    acts += select("t1", "出發時間", TIMES, time_)
    acts += [{"node": "b1", "role": "button", "label": "開始查詢", "kind": "click", "value": ""},
             {"node": "b2", "role": "button", "label": "清除重填", "kind": "click", "value": ""}]
    text = "台灣高鐵 網路訂票 請選擇起訖站與日期"
    if results:
        text += " 查詢結果 台北→左營 10/05 車次 0603 08:01 發車 09:35 抵達 車次 0115 08:21 發車 10:00 抵達"
    acts += [{"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
             {"id": "wait", "kind": "wait", "label": "Wait for the page to update"}]
    for i, a in enumerate(acts):
        a.setdefault("id", f"a{i}")
    return {"url": "https://irs.thsrc.com.tw/IMINT/", "title": "台灣高鐵網路訂票", "text": text, "actions": acts}


CASES = [
    ("起程站設台北", page(), ("SELECT", "s1", "台北")),
    ("到達站設左營", page(origin="台北"), ("SELECT", "s2", "左營")),
    ("填日期", page(origin="台北", dest="左營"), ("TYPE_TEXT", "d1", None)),
    ("出發時間 08:00", page(origin="台北", dest="左營", date="2026/10/05"), ("SELECT", "t1", "08:00")),
    ("按查詢", page(origin="台北", dest="左營", date="2026/10/05", time_="08:00"), ("CLICK", "b1", None)),
    ("看到結果 → DONE", page(origin="台北", dest="左營", date="2026/10/05", time_="08:00", results=True),
     ("DONE", None, None)),
]


OP_LABELS = {"CLICK": "點擊按鈕或連結", "TYPE_TEXT": "在空白輸入框輸入文字", "SELECT": "在下拉選單選一個值",
             "DONE": "目標已完成(畫面上已看到結果)", "WAIT": "等待頁面更新"}


def compact_choose(state, goal, history):
    """Same decision as choose(), but short string criteria and the rules said once, in the state."""
    elements, targets, _ = m.action_space(state["actions"])
    lines = [f"[{e['index']}] {e['role']} {e['label']} 目前值={e.get('value', '') or '空'}" for e in elements]
    ops = {k: v for k, v in OP_LABELS.items() if k in targets or k in ("DONE", "WAIT")}
    questions = {"operation": {"type": "choice", "instructions": "要完成目標,下一步該做哪種操作?已經是目標值的欄位不要再改。",
                               "criteria": ops}}
    for op, cands in targets.items():
        questions[op.lower() + "_target"] = {
            "type": "choice", "instructions": f"如果下一步是「{OP_LABELS[op]}」,該操作哪一個?",
            "criteria": {i: a["label"] + (f"(目前值 {a.get('current_value') or a.get('value') or '空'})" if op != "SELECT" else "")
                         for i, a in cands.items()}}
    body = {"model": "kev-latest", "state": {"目標": goal, "頁面": state["title"] + " " + state["text"], "元素": lines},
            "questions": questions}
    t0 = m.time.perf_counter()
    r = m.post_json(KEV_URL, "local", body)
    ms = round((m.time.perf_counter() - t0) * 1000)
    op = r["answers"]["operation"]["choice"]
    tgt = r["answers"].get(op.lower() + "_target", {}).get("choice") if op in targets else None
    return {"operation": op, "target": tgt, "confidence": r["answers"]["operation"]["confidence"],
            "usage": r.get("usage", {}), "latency_ms": ms}


def decomposed_choose(state, goal, history):
    """Ask Kev only small questions it is good at, in one request; a fixed policy composes the action.
    One noul per form field ("already matches the goal?"), one noul for "goal visibly done",
    one choice per dropdown for the wanted value, one choice for which button submits."""
    _, targets, _ = m.action_space(state["actions"])
    fields, order = {}, []
    for a in state["actions"]:
        if a.get("kind") in ("select", "fill") and a["node"] not in fields:
            fields[a["node"]] = a
            order.append(a["node"])
    page = {"目標": goal, "頁面": state["title"] + " " + state["text"]}
    qs = {"done": {"type": "noul", "instructions": "畫面上是否已經顯示目標要的結果(例如查詢結果列表)?"}}
    for node in order:
        a = fields[node]
        name = a["label"].split(" → ")[0]
        cur = a.get("current_value") if a["kind"] == "select" else a.get("value")
        qs[f"ok_{node}"] = {"type": "noul", "instructions": f"欄位「{name}」目前的值是「{cur or '空'}」。這個值是否已經符合目標?"}
        if a["kind"] == "select":
            opts = {i: t["label"].split(" → ")[1] for i, t in targets["SELECT"].items() if t["node"] == node}
            qs[f"val_{node}"] = {"type": "choice", "instructions": f"依照目標,欄位「{name}」應該選哪個值?", "criteria": opts}
    buttons = {i: t["label"] for i, t in targets["CLICK"].items() if t.get("role") == "button"}
    qs["submit"] = {"type": "choice", "instructions": "所有欄位填好之後,要按哪個按鈕送出?", "criteria": buttons}
    t0 = m.time.perf_counter()
    r = m.post_json(KEV_URL, "local", {"model": "kev-latest", "state": page, "questions": qs})
    ms = round((m.time.perf_counter() - t0) * 1000)
    ans = r["answers"]
    out = {"usage": r.get("usage", {}), "latency_ms": ms, "confidence": ans["done"]["noul"]}
    if ans["done"]["noul"] >= 0.5:
        return {**out, "operation": "DONE", "target": None}
    for node in order:
        if ans[f"ok_{node}"]["noul"] < 0.5:
            if fields[node]["kind"] == "select":
                return {**out, "operation": "SELECT", "target": ans[f"val_{node}"]["choice"]}
            idx = next(i for i, t in targets["TYPE_TEXT"].items() if t["node"] == node)
            return {**out, "operation": "TYPE_TEXT", "target": idx}
    return {**out, "operation": "CLICK", "target": ans["submit"]["choice"]}


def main():
    ok = 0
    decide = m.choose
    if "--compact" in sys.argv:
        decide = compact_choose
    if "--decomposed" in sys.argv:
        decide = decomposed_choose
    for name, state, (want_op, want_node, want_value) in CASES:
        d = decide(state, GOAL, history=[])
        op, tgt = d["operation"], d["target"]
        action = None
        if tgt:
            _, targets, _ = m.action_space(state["actions"])
            action = targets[op][tgt]
        hit = op == want_op and (want_node is None or (action and action["node"] == want_node)) and \
            (want_value is None or (action and action.get("value") == want_value))
        ok += hit
        got = f"{op} {action['label'] if action else ''}".strip()
        print(f"{'✅' if hit else '❌'} {name:<14} → {got:<28} op_conf={d['confidence']:.2f} "
              f"tokens={d['usage'].get('input_tokens')} {d['latency_ms']} ms")
    print(f"{ok}/{len(CASES)} correct")


if __name__ == "__main__":
    main()
