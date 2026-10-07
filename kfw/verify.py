"""Verify an offer on its product page, from the page's own structured data (site-agnostic).

All four shops publish it: JSON-LD Product / ProductGroup (PChome, Yahoo, Coupang) or
product:* meta tags (momo). From it code reads name, price, list price, condition and stock,
so price changes, out-of-stock and used/refurbished items are caught without the model.
"""

import time

from .judge import literal_match
from .page import ObservedTab

PRODUCT_JS = r"""(() => {
  const num = v => { const n = parseFloat(String(v ?? '').replace(/[^\d.]/g, '')); return isFinite(n) && n > 0 ? Math.round(n) : null; };
  const flat = [];
  const walk = o => { if (Array.isArray(o)) o.forEach(walk); else if (o && typeof o === 'object') { flat.push(o);
    ['@graph', 'hasVariant', 'offers'].forEach(k => o[k] && walk(o[k])); } };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) { try { walk(JSON.parse(s.textContent)); } catch (e) {} }
  const type = o => String(o['@type'] || '');
  const prod = flat.find(o => /Product/.test(type(o)));
  const offer = flat.find(o => /Offer/.test(type(o)) && o.price != null) || (prod && prod.offers && !Array.isArray(prod.offers) ? prod.offers : null);
  const meta = k => document.querySelector(`meta[property="${k}"], meta[name="${k}"]`)?.content;
  const strike = flat.find(o => /StrikethroughPrice/.test(String(o.priceType || '')));
  const price = num(offer?.price ?? offer?.lowPrice ?? meta('product:price:amount') ?? meta('og:price:amount'));
  if (!prod && price == null) return null;
  const tail = s => String(s || '').split('/').pop().toLowerCase();
  return {
    name: prod?.name || meta('og:title') || document.title,
    price, list_price: num(strike?.price),
    currency: offer?.priceCurrency || meta('product:price:currency') || null,
    condition: tail(offer?.itemCondition || prod?.itemCondition || meta('product:condition')) || null,
    availability: tail(offer?.availability || meta('product:availability')) || null,
    source: offer ? 'json-ld' : 'meta',
  };
})()"""

NOT_NEW = ("used", "refurbished", "damaged", "usedcondition", "refurbishedcondition", "damagedcondition")
OUT = ("outofstock", "soldout", "discontinued", "out of stock")


def read_product(tab, cap_s=8.0, poll_s=0.25):
    """Content-based readiness: return as soon as the page's product data is present."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < cap_s:
        try:
            data = tab.evaluate(PRODUCT_JS)
        except Exception:
            data = None
        if data and data.get("price"):
            return data, round((time.perf_counter() - t0) * 1000)
        time.sleep(poll_s)
    return None, round((time.perf_counter() - t0) * 1000)


def verify_offer(browser, offer, must, must_not):
    """-> the offer with `verify` filled in; verify.status is ok | price_changed | out_of_stock | not_new |
    name_mismatch | no_structured_data | error. price is replaced by the page price when they differ."""
    t0 = time.perf_counter()
    tab = ObservedTab.open(browser)
    try:
        tab.navigate(offer["url"])
        data, ms = read_product(tab)
        if not data:
            status = "no_structured_data"
        else:
            cond = (data.get("condition") or "").replace("condition", "")
            avail = (data.get("availability") or "").replace(" ", "")
            if any(w in avail for w in OUT):
                status = "out_of_stock"
            elif cond and any(cond.startswith(w.replace("condition", "")) for w in NOT_NEW):
                status = "not_new"
            elif not literal_match(data["name"], must, must_not):
                status = "name_mismatch"
            elif data["price"] != offer["price"]:
                status = "price_changed"
            else:
                status = "ok"
        v = {"status": status, "page": data, "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as e:
        v = {"status": "error", "error": f"{type(e).__name__}: {str(e)[:120]}", "ms": round((time.perf_counter() - t0) * 1000)}
    finally:
        try:
            tab.close()
        except Exception:
            pass
    out = {**offer, "verify": v}
    if v["status"] == "price_changed":
        out["card_price"], out["price"] = offer["price"], v["page"]["price"]
    if v.get("page") and v["page"].get("list_price") and not offer.get("original_price"):
        out["original_price"] = v["page"]["list_price"]
    out["verified"] = v["status"] in ("ok", "price_changed")
    return out
