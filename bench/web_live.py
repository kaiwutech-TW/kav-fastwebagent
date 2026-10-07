# -*- coding: utf-8 -*-
"""
Live browser run: Kev (decomposed questions) decides, a local small LLM writes field text,
jev-ultrafast's Browser observes and executes (with its freshness / occlusion checks).

Everything runs on this Mac: Kev on :8009, text helper (mlx_lm server) on :8011,
an isolated Chrome with --remote-debugging-port (BU_CDP_URL).

Usage (from vendor/jev-ultrafast):
  BU_CDP_URL=http://127.0.0.1:9333 BH_TELEMETRY=0 BU_NAME=kevtw \
    uv run python ../../bench/web_live.py --out thsr-run1
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "jev-ultrafast"))
from jev_ultrafast.browser import Browser, StalePage  # noqa: E402

KEV_URL = os.environ.get("KEV_URL", "http://127.0.0.1:8009") + "/v1/systemone"
TEXT_URL = os.environ.get("TEXT_URL", "http://127.0.0.1:8011") + "/v1/chat/completions"
TEXT_MODEL = os.environ.get("TEXT_MODEL", "mlx-community/Qwen3.5-2B-4bit")
CLIENT = httpx.Client(timeout=60)

URL = "https://www.thsrc.com.tw/"
GOAL = "查詢 10 月 5 日從台北到左營、單程、早上 8 點左右出發的高鐵時刻,看到車次列表就停。"


def field_name(a):
    return a["label"].split(" → ")[0]


def decide(page, goal):
    """One Kev request of small independent questions; a fixed policy composes the action."""
    fields, order = {}, []
    for a in page["actions"]:
        if a.get("kind") in ("select", "fill") and a["node"] not in fields:
            fields[a["node"]] = a
            order.append(a["node"])
    buttons = {a["id"]: a for a in page["actions"] if a.get("kind") == "click" and a.get("role") == "button"}
    state = {"目標": goal, "頁面": page["title"] + "\n" + page["text"][:1500]}
    qs = {"done": {"type": "noul", "instructions": "畫面上是否已經顯示目標要的查詢結果(車次列表)?"}}
    for node in order:
        a = fields[node]
        cur = a.get("current_value") if a["kind"] == "select" else a.get("value")
        qs[f"ok_{node}"] = {"type": "noul",
                            "instructions": f"欄位「{field_name(a)}」目前的值是「{cur or '空'}」。這個值是否已經符合目標?"}
        if a["kind"] == "select":
            opts = {x["id"]: x["label"].split(" → ")[1] for x in page["actions"]
                    if x.get("kind") == "select" and x["node"] == node}
            qs[f"val_{node}"] = {"type": "choice", "instructions": f"依照目標,欄位「{field_name(a)}」應該選哪個值?",
                                 "criteria": opts}
    if buttons:
        qs["submit"] = {"type": "choice", "instructions": "所有欄位都填好之後,要按哪個按鈕送出查詢?",
                        "criteria": {i: b["label"] for i, b in buttons.items()}}
    t0 = time.perf_counter()
    r = CLIENT.post(KEV_URL, json={"model": "kev-latest", "state": state, "questions": qs})
    r.raise_for_status()
    ans = r.json()["answers"]
    kev_ms = (time.perf_counter() - t0) * 1000
    probs = {k: (v.get("noul") if v["type"] == "noul" else v.get("choice")) for k, v in ans.items()}
    if ans["done"]["noul"] >= 0.5:
        return "DONE", None, kev_ms, probs
    for node in order:
        if ans[f"ok_{node}"]["noul"] < 0.5:
            a = fields[node]
            if a["kind"] == "select":
                return "SELECT", next(x for x in page["actions"] if x["id"] == ans[f"val_{node}"]["choice"]), kev_ms, probs
            return "TYPE_TEXT", a, kev_ms, probs
    if buttons:
        return "CLICK", buttons[ans["submit"]["choice"]], kev_ms, probs
    return "BLOCKED", None, kev_ms, probs


def value_format(v):
    """Describe the field's format from its current value, e.g. 2026/09/29 -> YYYY/MM/DD."""
    return re.sub(r"\d", "9", v or "") or "自由文字"


def field_text(goal, action):
    prompt = (f"目標:{goal}\n今天是 {date.today():%Y/%m/%d}。\n"
              f"只填這一個欄位:「{field_name(action)}」。目前值是「{action.get('value', '')}」,"
              f"輸入的格式必須和目前值一樣({value_format(action.get('value'))},9 代表數字)。\n"
              f"這個欄位要輸入什麼?")
    t0 = time.perf_counter()
    r = CLIENT.post(TEXT_URL, json={
        "model": TEXT_MODEL, "max_tokens": 40, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": '只回傳 JSON {"text": "要輸入的值"},不要其他文字。'},
                     {"role": "user", "content": prompt}]})
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"]
    text = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))["text"]
    return text, (time.perf_counter() - t0) * 1000


def fill(b, action, page, text):
    """Replace a field's value. Date/time widgets can swallow the Cmd+A that Browser.act sends,
    which inserted text mid-value on thsrc.com.tw; select() via the observed node is reliable.
    The JS is fixed code over a code-owned node id, never model output."""
    if not b.fresh(page, action):
        raise StalePage("Page changed since this decision. Observe again.")
    ok = b.evaluate("""(node => { const e=window.__jevFast?.nodes.get(node);
      if (!e?.isConnected || e.readOnly) return false; e.focus(); e.select(); return true; })(""" + json.dumps(action["node"]) + ")")
    if not ok:
        raise StalePage("Field is gone or read-only.")
    b.call("Input.insertText", text=text)
    b.evaluate("""(node => { const e=window.__jevFast.nodes.get(node);
      e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); e.blur(); })("""
               + json.dumps(action["node"]) + ")")
    for t in ("keyDown", "keyUp"):  # close a picker the focus opened
        b.call("Input.dispatchKeyEvent", type=t, key="Escape", code="Escape")


def settle(b, quiet_ms=300, cap_ms=4000):
    """After a click: wait for load, then until body text stops changing for quiet_ms.
    thsrc.com.tw renders the train list after the navigation completes, so jev-ultrafast's
    50 ms post-action wait observed the page before results existed."""
    t_end = time.perf_counter() + cap_ms / 1000
    last, since = None, time.perf_counter()
    while time.perf_counter() < t_end:
        try:
            cur = b.evaluate("document.readyState + '|' + (document.body?.innerText.length ?? 0)")
        except StalePage:
            cur = None
        if cur != last:
            last, since = cur, time.perf_counter()
        elif cur and cur.startswith("complete") and (time.perf_counter() - since) * 1000 >= quiet_ms:
            return
        time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--keep-open", action="store_true", help="leave the tab open and capture it again after 5 s")
    args = ap.parse_args()

    trace = {"goal": GOAL, "url": URL, "kev": KEV_URL, "text_model": TEXT_MODEL, "steps": []}
    b = Browser(URL)
    page = b.observe(screenshot=False)
    # Not a model decision: decline the cookie banner once, before timing starts.
    decline = next((a for a in page["actions"] if a.get("label") == "不同意"), None)
    if decline:
        b.act(decline, page)
        time.sleep(1.0)
        page = b.observe(screenshot=False)

    t_start = time.perf_counter()
    last, repeats, status = None, 0, "max_steps"
    for step in range(args.max_steps):
        op, action, kev_ms, probs = decide(page, GOAL)
        rec = {"step": step, "op": op, "label": action["label"] if action else None,
               "seen": {"url": page["url"][:80], "len": len(page["text"]), "has_trains": "車次" in page["text"] and "抵達時間" in page["text"],
                        "head": page["text"][:1500][-200:]},
               "kev_ms": round(kev_ms), "answers": probs}
        if op in ("DONE", "BLOCKED"):
            status = op.lower()
            rec["elapsed_ms"] = round((time.perf_counter() - t_start) * 1000)
            trace["steps"].append(rec)
            print(f"[{step}] {op}  kev={rec['kev_ms']}ms  t={rec['elapsed_ms']}ms")
            break
        key = (op, action["id"])
        scroll = next((a for a in page["actions"] if a.get("id") == "scroll_down"), None)
        if key == last and op == "CLICK" and scroll:
            # Never re-submit the same thing blindly: results are often below the fold, and
            # snapshot.js only sends visible text. Look first.
            op, action = "SCROLL", scroll
            rec.update(op=op, label=action["label"], note="repeat submit -> scroll")
            key = (op, action["id"])
        repeats = repeats + 1 if key == last else 0
        last = key
        if repeats >= 2:
            status = "stuck"
            trace["steps"].append({**rec, "note": "same action 3x"})
            print(f"[{step}] stuck on {op} {action['label']}")
            break
        text = None
        if op == "TYPE_TEXT":
            text, rec["text_ms"] = field_text(GOAL, action)
            rec["text"] = text
        t0 = time.perf_counter()
        try:
            if op == "TYPE_TEXT":
                fill(b, action, page, text)
            else:
                b.act(action, page, text=text)
        except StalePage as e:
            rec["stale"] = str(e)
        if op in ("CLICK", "SCROLL"):
            settle(b)
        page = b.observe(screenshot=False)
        rec["browser_ms"] = round((time.perf_counter() - t0) * 1000)
        rec["elapsed_ms"] = round((time.perf_counter() - t_start) * 1000)
        trace["steps"].append(rec)
        extra = f" text={text!r} ({rec['text_ms']:.0f}ms)" if text else ""
        print(f"[{step}] {op} {action['label']}{extra}  kev={rec['kev_ms']}ms "
              f"browser={rec['browser_ms']}ms  t={rec['elapsed_ms']}ms")

    # Independent check, not the model's word for it.
    settle(b)
    final = b.evaluate("document.body.innerText")
    trace.update(status=status, final_url=page["url"],
                 total_ms=round((time.perf_counter() - t_start) * 1000),
                 verify={"dates_shown": re.findall(r"20\d\d/\d{1,2}/\d{1,2}\S{0,4} \d\d:\d\d", final)[:3],
                         "has_train_table": "抵達時間" in final and "車次" in final,
                         "first_rows": final[final.find("備註"):final.find("備註") + 60].split()[1:9]})
    out = ROOT / "results" / "web"
    out.mkdir(parents=True, exist_ok=True)
    shot = b.call("Page.captureScreenshot", format="jpeg", quality=70)["data"]
    (out / f"{args.out}-at-done.jpg").write_bytes(__import__("base64").b64decode(shot))
    if args.keep_open:
        time.sleep(5)
        later = b.evaluate("document.body.innerText")
        trace["after_5s"] = {"dates_shown": re.findall(r"20\d\d/\d{1,2}/\d{1,2}\S{0,4} \d\d:\d\d", later)[:3],
                             "first_rows": later[later.find("備註"):later.find("備註") + 60].split()[1:9]}
        shot = b.call("Page.captureScreenshot", format="jpeg", quality=70, captureBeyondViewport=False)["data"]
        (out / f"{args.out}-after-5s.jpg").write_bytes(__import__("base64").b64decode(shot))
        print("after 5s:", trace["after_5s"])
    else:
        b.close() / f"{args.out}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out = out / f"{args.out}.json"
    out.write_text(json.dumps(trace, ensure_ascii=False, indent=1))
    print(f"status={status} total={trace['total_ms']}ms verify={trace['verify']} url={page['url']}")
    print(f"trace -> {out}")


if __name__ == "__main__":
    main()
