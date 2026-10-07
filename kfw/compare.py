"""compare_price: search several shops at once, keep listings that are the requested product,
read the comparable price, and say plainly what could not be done (needs_help).

Everything here is local: a Kav-owned Chrome over CDP, Kev over HTTP, code for the rest.
"""

import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from urllib.parse import quote

import httpx

from .cdp import Browser
from .extract import extract_cards
from .judge import KIND_NAMES, Judge
from .page import ObservedTab
from .price import parse_price
from .sites import SITES, classify, search_url
from .verify import verify_offer

HOME = Path(os.environ.get("KFW_HOME", Path.home() / ".kav-fastweb"))
CDP = os.environ.get("KFW_CDP", "http://127.0.0.1:9333")
KEV = os.environ.get("KFW_KEV", "http://127.0.0.1:8009")
CHROME = os.environ.get("KFW_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def ensure_chrome(timeout=20):
    """Connect to the Kav Chrome, launching it with its own persistent profile if nothing listens.
    The profile is separate from the user's everyday Chrome (Chrome refuses CDP on the default one)."""
    try:
        httpx.get(f"{CDP}/json/version", timeout=2)
        return "running"
    except httpx.HTTPError:
        pass
    port = CDP.rsplit(":", 1)[1]
    profile = HOME / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
                      "--no-default-browser-check", "--window-size=1280,900", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    end = time.time() + timeout
    while time.time() < end:
        try:
            httpx.get(f"{CDP}/json/version", timeout=1)
            return "launched"
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError(f"Chrome did not open a debugging port at {CDP}")


def wait_for_cards(tab, stable_polls=2, poll_s=0.3, cap_s=12.0):
    """Content-based readiness for result pages: done when the product list exists and its size
    stops changing — ads and trackers that keep the network busy do not matter here.
    Falls back to the full settle when no list shows up (no results, blocked, slow site)."""
    t0 = time.perf_counter()
    last, same = None, 0
    while time.perf_counter() - t0 < cap_s:
        try:
            res = extract_cards(tab)
        except Exception:
            res = {"cards": []}
        n = len(res["cards"])
        if n >= 2 and n == last:
            same += 1
            if same >= stable_polls:
                return res, round((time.perf_counter() - t0) * 1000), "cards_stable"
        else:
            same = 0
        last = n
        time.sleep(poll_s)
    tab.wait_ready(cap_ms=3000)
    return extract_cards(tab), round((time.perf_counter() - t0) * 1000), "cap"


def search_site(browser, judge, site, query, spec, must, must_not, per_site, shots, url_template=None):
    out = {"site": site, "name": SITES.get(site, {}).get("name", site)}
    t0 = time.perf_counter()
    tab = ObservedTab.open(browser)
    try:
        tab.navigate(url_template.replace("{query}", quote(query)) if url_template else search_url(site, query))
        time.sleep(0.3)
        res, ready_ms, ready_how = wait_for_cards(tab)
        if len(res["cards"]) < per_site:  # lazy lists: look further down once, then re-read
            tab.scroll_to_load(max_screens=2)
            res = extract_cards(tab)
        url, text = tab.evaluate("location.href"), tab.evaluate("document.body?.innerText || ''")
        shot = shots / f"{site}.jpg"
        tab.screenshot(shot)
        status, reason, hint = classify(url, text, len(res["cards"]))
        out.update(status=status, reason=reason, hint=hint, page_url=url, screenshot=str(shot),
                   ready_ms=ready_ms, ready=ready_how, cards_seen=len(res["cards"]))
        offers, rejected, model_ms = [], {}, []
        for card in res["cards"][:per_site]:
            kind, p_match, ms = judge.judge(spec, card, must, must_not)
            if ms:
                model_ms.append(ms)
            if kind != "E":
                rejected[KIND_NAMES[kind]] = rejected.get(KIND_NAMES[kind], 0) + 1
                continue
            p = parse_price(card.get("text", ""), card.get("class_prices", []))
            if p.price is None:
                rejected["no_price"] = rejected.get("no_price", 0) + 1
                continue
            offers.append({"site": site, "title": card["title"], "price": p.price, "original_price": p.original,
                           "conditional_offers": p.conditional, "notes": p.notes, "shipping": p.shipping,
                           "url": card["url"], "rank_on_site": card["rank"], "match_confidence": round(p_match, 2)})
        out.update(offers=sorted(offers, key=lambda o: o["price"]), rejected=rejected,
                   model_calls=len(model_ms), model_ms=round(sum(model_ms)))
        if status == "ok" and not offers:
            out.update(status="no_match", reason="no_listing_matched",
                       hint="有搜尋結果,但沒有一筆符合規格(看 rejected);可請 planner 檢查 must / must_not")
    except Exception as e:  # a broken site must not take the others down
        out.update(status="error", reason=type(e).__name__, hint=str(e)[:200], offers=[])
    finally:
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        try:
            tab.close()
        except Exception:
            pass
    return out


def split_suspicious(offers, low=0.5, high=2.0):
    """Price sanity guard (code, not model). Listings far below the median are usually accessories or
    keyword-stuffed titles ("PS5 Slim主機 … PS5 PRO 主機" at 40% of the median, a $399 stand);
    far above are usually bundles. They are kept for review but never ranked."""
    if len(offers) < 3:
        return offers, []
    prices = sorted(o["price"] for o in offers)
    median = prices[len(prices) // 2]
    ok, flagged = [], []
    for o in offers:
        ratio = o["price"] / median
        if ratio < low or ratio > high:
            flagged.append({**o, "flag": "suspicious_low_price" if ratio < low else "suspicious_high_price",
                            "price_vs_median": round(ratio, 2)})
        else:
            ok.append(o)
    return ok, flagged


def verify_cheapest(browser, offers, must, must_not, want=3, max_rounds=3):
    """Open product pages cheapest-first until `want` offers verify (or candidates run out).
    Returns (verified_sorted, dropped, unverified_rest)."""
    queue, verified, dropped = list(offers), [], []
    for _ in range(max_rounds):
        if len(verified) >= want or not queue:
            break
        batch, queue = queue[:want - len(verified)], queue[want - len(verified):]
        results = [None] * len(batch)

        def work(i, o):
            results[i] = verify_offer(browser, o, list(must), list(must_not))

        threads = [threading.Thread(target=work, args=(i, o)) for i, o in enumerate(batch)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for r in results:
            (verified if r and r["verified"] else dropped).append(r)
    return sorted(verified, key=lambda o: o["price"]), dropped, [{**o, "verified": False} for o in queue]


def compare_price(query, spec, must, must_not=(), sites=None, per_site=10, verify_top=3, search_urls=None):
    """search_urls: optional {site: URL template with {query}} from a recipe; defaults to kfw.sites."""
    t0 = time.perf_counter()
    search_urls = search_urls or {}
    sites = [s for s in (sites or list(SITES)) if s in SITES or s in search_urls]
    judge = Judge(KEV)
    if not judge.healthy():
        return {"status": "needs_help", "query": query, "needs_help": [{
            "reason": "kev_not_running",
            "hint": "Kev 沒有在 " + KEV + " 回應;請使用者啟動:cd vendor/kev && uv run --extra serve python -m kev.serve "
                    "--run jaredpalmer/kev-4b --port 8009"}]}
    chrome = ensure_chrome()
    shots = HOME / "runs" / datetime.now().strftime("%y%m%d-%H%M%S")
    shots.mkdir(parents=True, exist_ok=True)
    browser = Browser(CDP)
    results = {}

    def work(site):
        results[site] = search_site(browser, judge, site, query, spec, list(must), list(must_not), per_site, shots,
                                    search_urls.get(site))

    threads = [threading.Thread(target=work, args=(s,)) for s in sites]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    per_site = [results[s] for s in sites]
    offers = sorted((o for r in per_site for o in r.get("offers", [])), key=lambda o: o["price"])
    offers, suspicious = split_suspicious(offers)
    t_verify = time.perf_counter()
    verified, dropped, rest = verify_cheapest(browser, offers, must, must_not, want=verify_top) if verify_top else ([], [], offers)
    verify_ms = round((time.perf_counter() - t_verify) * 1000)
    browser.close()
    offers = verified + rest
    helps = [{"site": r["site"], "reason": r["reason"], "hint": r["hint"], "screenshot": r.get("screenshot")}
             for r in per_site if r["status"] not in ("ok",)]
    if offers and not verified:
        helps.append({"site": None, "reason": "nothing_verified",
                      "hint": "沒有任何一筆在商品頁驗證通過(看 dropped_after_verify);best 是未驗證的"})
    if suspicious:
        helps.append({"site": None, "reason": "suspicious_prices",
                      "hint": f"{len(suspicious)} 筆價格離中位數太遠,已排除在排序外(見 suspicious);請確認是不是配件、組合或灌關鍵字的標題"})
    status = "done" if offers and not helps else "partial" if offers else "needs_help"
    return {
        "status": status,
        "query": query,
        "best": verified[0] if verified else (offers[0] if offers else None),
        "offers": offers,
        "suspicious": suspicious,
        "dropped_after_verify": dropped,
        "verify_ms": verify_ms,
        "per_site": [{k: v for k, v in r.items() if k != "offers"} for r in per_site],
        "needs_help": helps,
        "price_rule": "price = 任何人都買得到的一次付清售價;首購價、回饋、點數只列在 conditional_offers / notes,不參與排序",
        "chrome": chrome,
        "evidence_dir": str(shots),
        "kev": judge.usage(),
        "total_ms": round((time.perf_counter() - t0) * 1000),
    }
