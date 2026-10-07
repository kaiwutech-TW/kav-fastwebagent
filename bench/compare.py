# -*- coding: utf-8 -*-
"""
Compare two runs over the same items: decision flip rate, mean total-variation distance,
and each run's accuracy. Options are matched by position, which holds because
make_tw.py converts criteria in place without reordering.

Usage: uv run bench/compare.py results/raw/A.jsonl results/raw/B.jsonl
"""
import json
import sys


def load(p):
    return {(d["item_id"], d["question"]): d
            for d in map(json.loads, open(p, encoding="utf-8")) if "_meta" not in d}


def argmax(v):
    return max(range(len(v)), key=v.__getitem__)


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    keys = sorted(a.keys() & b.keys())
    flips = [argmax(a[k]["probs"]) != argmax(b[k]["probs"]) for k in keys]
    tvs = [0.5 * sum(abs(x - y) for x, y in zip(a[k]["probs"], b[k]["probs"])) for k in keys]
    acc = lambda r: sum(argmax(r[k]["probs"]) == r[k]["gold_idx"] for k in keys) / len(keys)
    print(f"n={len(keys)}  flip={sum(flips) / len(keys):.1%}  meanTV={sum(tvs) / len(keys):.3f}  "
          f"accA={acc(a):.3f}  accB={acc(b):.3f}")


if __name__ == "__main__":
    main()
