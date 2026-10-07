"""Capture the 591 北投區雅房 list page once: the rows exactly as the pick step would see them (form.pick_groups)."""
import json, sys, time
from pathlib import Path

from kfw import form
from kfw.cdp import Browser
from kfw.page import ObservedTab

URL = "https://rent.591.com.tw/list?region=1&section=9&kind=4"
PATTERN = r"雅房\d+坪\d+F/\d+F.*\d[\d,]*元/月"
OUT = Path(__file__).parent / (sys.argv[1] if len(sys.argv) > 1 else "rows.json")

b = Browser()
try:
    tab = ObservedTab.open(b)
    tab.goto(URL)
    r = tab.wait_ready(cap_ms=10000)
    t0 = time.perf_counter()
    obs = form.pick_groups(tab, PATTERN, 1)
    ms = round((time.perf_counter() - t0) * 1000)
    groups = obs["groups"]
    print("ready:", r.reason, r.ms, "ms; pick_groups:", ms, "ms; groups:", len(groups), [g["total"] for g in groups])
    if len(groups) != 1:
        sys.exit("ambiguous or empty")
    rows = [{"cells": row["cells"], "text": row["text"]} for row in groups[0]["rows"]]
    OUT.write_text(json.dumps({"url": URL, "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "pattern": PATTERN,
                               "fingerprint": groups[0]["fingerprint"], "rows": rows}, ensure_ascii=False, indent=1))
    for i, row in enumerate(rows, 1):
        print(f"c{i}: {row['text'][:150]}")
    tab.screenshot(str(OUT.with_name("list.jpg")), full_page=False)
    tab.close()
finally:
    b.close()
