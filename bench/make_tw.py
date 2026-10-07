# -*- coding: utf-8 -*-
"""
Build Traditional Chinese (Taiwan) variants of zh-decision-bench v0.2.

  evals/massive_tw_statecn.jsonl  native MASSIVE zh-TW utterance, Simplified criteria
                                  (zh-decision-bench E4 protocol, comparable to its flip rates)
  evals/massive_tw_full.jsonl     native zh-TW utterance + criteria converted with OpenCC s2twp
                                  (what a Taiwan deployment actually sends)
  evals/synthetic_tw_s2twp.jsonl  synthetic CS / moderation items, fully converted with s2twp.
                                  Machine-converted, NOT native Taiwanese phrasing.

Gold labels are converted with the same converter so they stay equal to a criteria key.

Usage: uv run bench/make_tw.py
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["opencc-python-reimplemented"]
# ///
import json
import re
from pathlib import Path

from opencc import OpenCC

ROOT = Path(__file__).resolve().parent.parent
ZDB = ROOT / "vendor" / "zh-decision-bench" / "data"
MASSIVE_TW = ROOT / "vendor" / "massive" / "1.1" / "data" / "zh-TW.jsonl"
OUT = ROOT / "evals"

cc = OpenCC("s2twp")


def conv(x):
    if isinstance(x, str):
        return cc.convert(x)
    if isinstance(x, list):
        return [conv(v) for v in x]
    if isinstance(x, dict):
        return {conv(k) if k not in ("true", "false") else k: conv(v) for k, v in x.items()}
    return x


def convert_questions(item):
    qs = {}
    for name, q in item["questions"].items():
        qs[name] = {**q, "instructions": conv(q["instructions"]), "criteria": conv(q["criteria"])}
    gold = {k: conv(v) for k, v in item["gold"].items()}
    return qs, gold


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def dump(items, name):
    OUT.mkdir(exist_ok=True)
    with open(OUT / name, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{name}: {len(items)} items")


def main():
    tw_utt = {d["id"]: d["utt"].strip() for d in load(MASSIVE_TW)}
    statecn, full, missed = [], [], 0
    for it in load(ZDB / "massive_items.jsonl"):
        m = re.search(r"massive_id=(\d+)", it.get("notes", ""))
        if not m or m.group(1) not in tw_utt:
            missed += 1
            continue
        src = "MASSIVE zh-TW (Amazon, CC BY 4.0) via zh-decision-bench v0.2"
        statecn.append({**it, "state": tw_utt[m.group(1)], "source": src})
        qs, gold = convert_questions(it)
        full.append({**it, "state": tw_utt[m.group(1)], "questions": qs, "gold": gold,
                     "source": src + "; criteria OpenCC s2twp"})
    print(f"missed {missed} items without a zh-TW parallel")
    dump(statecn, "massive_tw_statecn.jsonl")
    dump(full, "massive_tw_full.jsonl")

    syn = []
    for it in load(ZDB / "synthetic_items.jsonl"):
        qs, gold = convert_questions(it)
        syn.append({**it, "state": conv(it["state"]), "questions": qs, "gold": gold,
                    "source": "zh-decision-bench v0.2 synthetic, OpenCC s2twp (machine-converted)"})
    dump(syn, "synthetic_tw_s2twp.jsonl")


if __name__ == "__main__":
    main()
