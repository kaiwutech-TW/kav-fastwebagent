"""Arm A (Kev) / arm B (no model): the production pick decision (steps._select_row) over the captured rows.
usage: run_pick.py A|B [repeat]"""
import json, sys, time
from pathlib import Path

from kfw import steps
from kfw.judge import Judge

HERE = Path(__file__).parent
arm = sys.argv[1]
repeat = int(sys.argv[2]) if len(sys.argv) > 2 else 1
suffix = sys.argv[3] if len(sys.argv) > 3 else ""          # "" = the 26-row set, "30" = the full 30-row set
rows = json.loads((HERE / f"rows{suffix}.json").read_text())["rows"]
queries = json.loads((HERE / f"queries{suffix}.json").read_text())
cands = {f"c{n}": {"row_id": f"r{n}", "cells": r["cells"], "text": r["text"], "controls": []} for n, r in enumerate(rows, 1)}


class NoKev:
    def row_match(self, *a, **k):
        raise RuntimeError("no local model in this arm")

    def usage(self):
        return {}


judge = Judge() if arm == "A" else NoKev()
if arm == "A" and not judge.healthy():
    sys.exit("Kev is not up")

results = []
for q in queries:
    for rep in range(repeat):
        ev: dict = {}
        t0 = time.perf_counter()
        row, problem = steps._select_row(judge, cands, q["want"], ev, "")
        ms = round((time.perf_counter() - t0) * 1000)
        chosen = next((k for k, v in cands.items() if v is row), None) if row else None
        exp = q["expect"]
        if len(exp) == 1:
            verdict = "correct" if chosen == exp[0] else ("stopped" if chosen is None else "WRONG")
        else:  # none or several fit: stopping is the designed, correct behaviour; picking any is wrong
            verdict = "correct-stop" if chosen is None else "WRONG"
        top = sorted(ev.get("probabilities", {}).items(), key=lambda kv: -kv[1])[:3]
        rec = {"id": q["id"], "rep": rep + 1, "want": q["want"], "kind": q["kind"], "expect": exp, "chosen": chosen, "verdict": verdict,
               "how": ev.get("how"), "ms": ms, "kev_ms": ev.get("kev_ms"), "why": (problem[2].get("why") if problem else None),
               "top3": top, "kev_error": ev.get("kev_error")}
        results.append(rec)
        print(f"{q['id']} {verdict:12} chosen={chosen} how={ev.get('how')} {ms}ms why={rec['why']} top3={top}")

out = HERE / f"results_{arm}{suffix}.json"
out.write_text(json.dumps({"arm": arm, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "usage": judge.usage(), "results": results},
                          ensure_ascii=False, indent=1))
print("usage:", judge.usage())
