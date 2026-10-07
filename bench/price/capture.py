# -*- coding: utf-8 -*-
"""
Capture search-result listings (title / prices / url) from the no-login shops, for the
price-comparison eval. One page load per (query, site), a pause between loads, a screenshot each.

Usage: uv run python bench/price/capture.py [--queries "AirPods Pro 3" ...]
Writes evals/price/listings-<YYMMDD>.jsonl and results/price/<YYMMDD>/<site>-<n>.jpg
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from kfw.cdp import Browser
from kfw.extract import extract_cards
from kfw.page import ObservedTab

ROOT = Path(__file__).resolve().parents[2]
SITES = {
    "pchome": "https://24h.pchome.com.tw/search/?q={q}",
    "momo": "https://www.momoshop.com.tw/search/searchShop.jsp?keyword={q}",
    "yahoo": "https://tw.buy.yahoo.com/search/product?p={q}",
    "coupang": "https://www.tw.coupang.com/search?q={q}",
}
QUERIES = ["AirPods Pro 3", "Nintendo Switch 2", "Dyson V15 Detect", "Sony WH-1000XM6",
           "iPhone 17 256GB", "象印 保溫杯 480ml"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", nargs="*", default=QUERIES)
    ap.add_argument("--pause", type=float, default=3.0)
    args = ap.parse_args()

    day = datetime.now().strftime("%y%m%d")
    out = ROOT / "evals" / "price" / f"listings-{day}.jsonl"
    shots = ROOT / "results" / "price" / day
    out.parent.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)

    b = Browser()
    n_rows = 0
    with open(out, "w", encoding="utf-8") as f:
        for qi, query in enumerate(args.queries):
            for site, tpl in SITES.items():
                tab = ObservedTab.open(b)
                t0 = time.perf_counter()
                ready = tab.goto(tpl.format(q=quote(query)))
                scroll_ms = tab.scroll_to_load(max_screens=4)
                res = extract_cards(tab)
                ms = round((time.perf_counter() - t0) * 1000)
                shot = shots / f"{site}-{qi}.jpg"
                tab.screenshot(shot)
                meta = {"query": query, "site": site, "page_url": tab.evaluate("location.href"),
                        "captured_at": datetime.now().isoformat(timespec="seconds"),
                        "ready_ms": ready.ms, "ready_ok": ready.ok, "scroll_ms": scroll_ms, "total_ms": ms,
                        "list": res["list"], "screenshot": str(shot.relative_to(ROOT))}
                for c in res["cards"]:
                    f.write(json.dumps({**meta, **c}, ensure_ascii=False) + "\n")
                    n_rows += 1
                print(f"{query:<20} {site:<8} cards={len(res['cards']):>2} ready={ready.ms}ms total={ms}ms")
                tab.close()
                time.sleep(args.pause)
    print(f"{n_rows} listings -> {out}")


if __name__ == "__main__":
    main()
