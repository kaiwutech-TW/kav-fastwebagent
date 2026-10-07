# -*- coding: utf-8 -*-
"""
Score a System One endpoint (local Kev by default) on the same-product judgement for the
price-comparison eval: is this listing the specified product itself, a bundle, refurbished,
an accessory, another model, or not a comparable price?

Usage: uv run python bench/price/judge_eval.py [--labels evals/price/labels-260929.jsonl]
"""
import argparse
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ.get("KEV_URL", "http://127.0.0.1:8009") + "/v1/systemone"
KINDS = {
    "E": "就是規格中的商品本體(全新、單品;附小贈品也算)",
    "B": "組合包:商品另外搭配其他要付錢的商品(遊戲、保護殼組、充電器、買一送一)",
    "R": "福利品、整新品或二手",
    "A": "這個商品的配件、耗材、周邊或遊戲軟體",
    "O": "其他型號或其他商品",
    "X": "價格不是一次付清的售價(分期、訂閱)",
}


def ask(client, row):
    state = {"規格": row["spec"], "商品標題": row["title"], "商品卡片文字": row["text"]}
    qs = {
        "kind": {"type": "choice", "instructions": "這筆商品和規格的關係是哪一種?", "criteria": KINDS},
        "is_it": {"type": "noul", "instructions": "這筆商品就是規格中的商品本體嗎(全新、單品,不是配件、組合、福利品或其他型號)?"},
    }
    t0 = time.perf_counter()
    r = client.post(URL, json={"model": "kev-latest", "state": state, "questions": qs})
    r.raise_for_status()
    a = r.json()["answers"]
    return a["kind"]["choice"], a["kind"]["probabilities"], a["is_it"]["noul"], (time.perf_counter() - t0) * 1000


CHECKS = {
    "model": "標題裡的商品型號是否和規格完全一致?型號多了或少了字(例如 17e、Pro、Max、Lite、OLED、AirPods 4、WF 與 WH 不同)就不一致。",
    "accessory": "這筆商品是不是配件、耗材、周邊或遊戲軟體,而不是規格中的主商品本身?",
    "bundle": "除了主商品之外,是否還另外包含其他商品(例如遊戲片、充電器、保護殼組、收納包、第二件商品)?小贈品、贈券不算。",
    "refurb": "這是福利品、整新品或二手商品嗎?",
    "installment": "標示的價格是分期或訂閱的每期金額,而不是一次付清的售價嗎?",
}


def ask_decomposed(client, row):
    """One request, five independent yes/no checks; a fixed rule composes the verdict."""
    state = {"規格": row["spec"], "商品標題": row["title"], "商品卡片文字": row["text"]}
    qs = {k: {"type": "noul", "instructions": v} for k, v in CHECKS.items()}
    t0 = time.perf_counter()
    r = client.post(URL, json={"model": "kev-latest", "state": state, "questions": qs})
    r.raise_for_status()
    a = {k: v["noul"] for k, v in r.json()["answers"].items()}
    if a["installment"] >= 0.5:
        kind = "X"
    elif a["accessory"] >= 0.5:
        kind = "A"
    elif a["model"] < 0.5:
        kind = "O"
    elif a["refurb"] >= 0.5:
        kind = "R"
    elif a["bundle"] >= 0.5:
        kind = "B"
    else:
        kind = "E"
    p_is = min(a["model"], 1 - a["accessory"], 1 - a["bundle"], 1 - a["refurb"], 1 - a["installment"])
    return kind, a, p_is, (time.perf_counter() - t0) * 1000


# What the calling planner (Claude, via MCP) would hand over once per query: literal constraints
# code can check exactly. Matching is on lowercase text with spaces removed.
MATCH = {
    "AirPods Pro 3": {"must": [["airpodspro3"]], "must_not": ["airpods4", "airpods5"]},
    "Nintendo Switch 2": {"must": [["switch2", "ns2"]], "must_not": ["lite", "oled"]},
    "Dyson V15 Detect": {"must": [["v15"]], "must_not": []},
    "Sony WH-1000XM6": {"must": [["wh-1000xm6", "wh1000xm6"]], "must_not": []},
    "iPhone 17 256GB": {"must": [["iphone17"], ["256"]], "must_not": ["17e", "17pro", "promax", "iphoneair", "16e"]},
    "象印 保溫杯 480ml": {"must": [["象印", "zojirushi"], ["480"]], "must_not": ["日象"]},
}
SEMANTIC = {
    "accessory": "這筆商品是不是配件、耗材、周邊或遊戲軟體,而不是規格中的主商品本身?",
    "bundle": "除了主商品之外,是否另外搭售其他要一起付錢的商品(例如遊戲片、充電器、保護殼組、第二件相同商品)?"
              "贈品、商品卡、P幣、點數、贈送的收納架或耳機架、帆布袋都不算。",
    "refurb": "這是福利品、整新品或二手商品嗎?",
    "installment": "標示的價格是分期或訂閱的每期金額,而不是一次付清的售價嗎?",
}


def literal_match(query, title):
    t = title.lower().replace(" ", "")
    spec = MATCH[query]
    return all(any(w in t for w in group) for group in spec["must"]) and not any(w in t for w in spec["must_not"])


def ask_hybrid(client, row):
    """Code checks the model literally (planner-supplied constraints); Kev answers only semantic checks."""
    if not literal_match(row["query"], row["title"]):
        return "O", {"literal": False}, 0.0, 0.0
    state = {"規格": row["spec"], "商品標題": row["title"], "商品卡片文字": row["text"]}
    qs = {k: {"type": "noul", "instructions": v} for k, v in SEMANTIC.items()}
    t0 = time.perf_counter()
    r = client.post(URL, json={"model": "kev-latest", "state": state, "questions": qs})
    r.raise_for_status()
    a = {k: v["noul"] for k, v in r.json()["answers"].items()}
    kind = ("X" if a["installment"] >= 0.5 else "A" if a["accessory"] >= 0.5 else
            "R" if a["refurb"] >= 0.5 else "B" if a["bundle"] >= 0.5 else "E")
    p_is = min(1 - a["accessory"], 1 - a["bundle"], 1 - a["refurb"], 1 - a["installment"])
    return kind, a, p_is, (time.perf_counter() - t0) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(ROOT / "evals" / "price" / "labels-260929.jsonl"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--mode", choices=["single", "decomposed", "hybrid"], default="decomposed")
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(args.labels, encoding="utf-8")]
    client = httpx.Client(timeout=60)
    preds, ms = [], []
    for row in rows:
        kind, probs, p_is, t = {"single": ask, "decomposed": ask_decomposed, "hybrid": ask_hybrid}[args.mode](client, row)
        preds.append({"i": row["i"], "gold": row["label"], "kind": kind, "p_is": p_is, "probs": probs})
        ms.append(t)

    n = len(rows)
    acc6 = sum(p["kind"] == p["gold"] for p in preds) / n
    tp = sum(p["p_is"] >= 0.5 and p["gold"] == "E" for p in preds)
    fp = sum(p["p_is"] >= 0.5 and p["gold"] != "E" for p in preds)
    fn = sum(p["p_is"] < 0.5 and p["gold"] == "E" for p in preds)
    tn = n - tp - fp - fn
    print(f"n={n}  6-way acc={acc6:.3f}")
    print(f"is_it (E vs rest): acc={(tp + tn) / n:.3f}  precision={tp / max(1, tp + fp):.3f}  recall={tp / max(1, tp + fn):.3f}  "
          f"(tp={tp} fp={fp} fn={fn} tn={tn})")
    by_gold = defaultdict(Counter)
    for p in preds:
        by_gold[p["gold"]][p["kind"]] += 1
    for g in "EBRAOX":
        if by_gold[g]:
            print(f"  gold {g}: {dict(by_gold[g])}")
    ms = sorted(m for m in ms if m > 0)  # literal rejects never reach the model
    print(f"latency per model call: median {ms[len(ms) // 2]:.0f} ms, p90 {ms[int(len(ms) * 0.9)]:.0f} ms ({len(ms)} calls)")
    wrong = [(p, rows[p["i"]]) for p in preds if (p["p_is"] >= 0.5) != (p["gold"] == "E")]
    print(f"\n{len(wrong)} is_it errors:")
    for p, r in wrong:
        print(f"  [{r['i']}] gold={p['gold']} p_is={p['p_is']:.2f} kind={p['kind']}  {r['query']} | {r['title'][:70]}")
    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in preds))


if __name__ == "__main__":
    main()
