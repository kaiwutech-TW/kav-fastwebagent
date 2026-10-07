# -*- coding: utf-8 -*-
"""
Run a zh-decision-bench format eval set against any TypeSafe System One compatible
endpoint (a local Kev server by default, which also works for Jev).

Output records match zh-decision-bench's run_eval.py, so its report.py / refit.py /
metrics.py can score Kev results next to the published Jev / Laya / NeoHorse raws.

Usage:
  uv run bench/run_kev.py --data vendor/zh-decision-bench/data/massive_items.jsonl --out kev4b_massive
  KEV_URL=https://...modal.run KEV_API_KEY=... uv run bench/run_kev.py ...
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def gold_index(labels, gold_val):
    if isinstance(gold_val, bool):
        return 0 if gold_val else 1  # noul labels = ["true", "false"]
    return labels.index(gold_val)


def to_probs(qspec, ans):
    """Convert one System One answer into (labels, probs); same rules as the harness's jev_adapter."""
    qtype = qspec["type"]
    p = ans.get("probabilities", {})
    if qtype == "choice":
        labels = list(qspec["criteria"].keys())
        probs = [float(p.get(l, 0.0)) for l in labels]
    elif qtype == "score":
        labels = list(qspec["criteria"])
        probs = [float(p.get(str(i), p.get(l, 0.0))) for i, l in enumerate(labels)]
    elif qtype == "noul":
        labels = ["true", "false"]
        pt = float(ans["noul"])
        probs = [pt, 1.0 - pt]
    else:
        raise ValueError(qtype)
    s = sum(probs)
    return labels, [x / s for x in probs] if s > 0 else probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--out", required=True, help="run id; writes results/raw/<out>.jsonl")
    ap.add_argument("--model-name", default="kev-4b", help="label stored in each record")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    url = os.environ.get("KEV_URL", "http://127.0.0.1:8009").rstrip("/")
    session = requests.Session()
    if os.environ.get("KEV_API_KEY"):
        session.headers["Authorization"] = f"Bearer {os.environ['KEV_API_KEY']}"
    served = session.get(f"{url}/v1/models", timeout=30).json()

    out_path = ROOT / "results" / "raw" / f"{args.out}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"_meta": {"run_id": args.out, "model": args.model_name, "url": url,
                      "served": served, "data": args.data,
                      "started": datetime.now().isoformat(), "limit": args.limit}}

    n_items = n_q = 0
    t_start = time.time()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for data_file in args.data:
            items = [json.loads(l) for l in open(data_file, encoding="utf-8") if l.strip()]
            if args.limit:
                items = items[:args.limit]
            for item in items:
                payload = {"model": "kev-latest", "state": item["state"], "questions": item["questions"]}
                r = session.post(f"{url}/v1/systemone", json=payload, timeout=120)
                r.raise_for_status()
                result = r.json()
                for qname, qspec in item["questions"].items():
                    labels, probs = to_probs(qspec, result["answers"][qname])
                    rec = {"run_id": args.out, "model": args.model_name, "item_id": item["id"],
                           "domain": item["domain"], "question": qname, "qtype": qspec["type"],
                           "labels": labels, "probs": probs,
                           "gold_idx": gold_index(labels, item["gold"][qname]),
                           "confidence": result["answers"][qname].get("confidence"),
                           "latency_ms": result.get("latency_ms")}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n_q += 1
                n_items += 1
                if n_items % 50 == 0:
                    print(f"  {n_items} items / {n_q} questions / {time.time() - t_start:.0f}s", flush=True)
    print(f"done: {n_items} items, {n_q} questions -> {out_path} ({time.time() - t_start:.0f}s)")


if __name__ == "__main__":
    main()
