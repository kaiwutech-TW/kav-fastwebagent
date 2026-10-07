"""Site-agnostic extraction of product cards from a search-results page.

A results list is a parent whose children repeat the same structure (tag + classes) and mostly
carry both a link and a price. Code finds the list; the model only judges the cards
(same product? accessory? refurbished?). Prices come from two sources: "$1,234" / "1,234元" in whitespace-normalised card text,
and digits inside elements whose class mentions "price" (momo prints "6,999" with no currency
sign at all). A card may itself be the link (Yahoo: <a> cards).
"""

import re

CARDS_JS = r"""
(() => {
  const PRICE = /(?:NT\$|\$)\s?([\d,]{2,9})|([\d,]{2,9})\s?元/g;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const sig = e => e.tagName + '.' + [...e.classList].filter(c => !/\d{3,}/.test(c)).slice(0, 3).sort().join('.');
  const num = s => parseInt(s.replace(/,/g, ''), 10);
  const classPrices = k => [...k.querySelectorAll('[class*=price i]')]
    .map(e => (norm(e.innerText).match(/^[^\d]{0,4}([\d,]{2,9})/) || [])[1]).filter(Boolean).map(num);
  const prices = k => {
    const fromText = [...norm(k.innerText).matchAll(PRICE)].map(m => num(m[1] || m[2]));
    return [...new Set(fromText.concat(classPrices(k)))].filter(n => n > 0);
  };
  const links = k => (k.matches('a[href]') ? [k] : []).concat([...k.querySelectorAll('a[href]')]);
  let best = null;
  for (const parent of document.querySelectorAll('body *')) {
    const kids = [...parent.children];
    if (kids.length < 2) continue;
    const groups = {};
    for (const k of kids) (groups[sig(k)] ||= []).push(k);
    for (const [s, items] of Object.entries(groups)) {
      if (items.length < 2) continue;
      // A card points at one product; an item linking to >3 distinct pages is a wrapper around a list (PChome SECTION).
      const atomic = k => new Set(links(k).map(a => a.href.split('#')[0])).size <= 3;
      const good = items.filter(k => links(k).length && prices(k).length && k.querySelector('img') && atomic(k));
      if (good.length < 2) continue;  // small result sets are real (momo 'Dyson V15 Detect' had 3); no ratio: lazy lists hold empty placeholders
      const area = good.reduce((a, k) => { const r = k.getBoundingClientRect(); return a + r.width * r.height; }, 0);
      // Rank by on-screen area, not count: main results are big cards, side widgets (Yahoo 挑戰低價) are small.
      if (!best || area > best.area)
        best = {good, sig: s, area, parent: sig(parent)};
    }
  }
  if (!best) return {list: null, cards: []};
  const cards = best.good.slice(0, 60).map((k, i) => {
    const text = norm(k.innerText);
    const cands = links(k).map(a => norm(a.innerText))
      .concat([...k.querySelectorAll('img[alt]')].map(i => norm(i.alt)))
      .concat([...k.querySelectorAll('[title]')].map(e => norm(e.getAttribute('title'))))
      .filter(t => t.length >= 6 && !/^[\s$\d,.元NT]+$/.test(t));
    const title = cands.sort((a, b) => b.length - a.length)[0] || text.slice(0, 80);
    const link = links(k).find(a => norm(a.innerText) === title || a.querySelector('img')) || links(k)[0];
    return {rank: i + 1, title: title.slice(0, 200), prices: prices(k), class_prices: [...new Set(classPrices(k))],
            url: link ? link.href : null, text: text.slice(0, 400)};
  });
  return {list: {parent: best.parent, item: best.sig, n: best.good.length}, cards};
})()
"""


UI_PREFIXES = ("比較 找相似 ", "找相似 ", "補貨中 ", "到貨通知我 ")


def clean_title(title):
    """Card titles often carry UI words and the price text (Yahoo "比較 找相似 …", Coupang whole card).
    Keep the product name: drop known UI prefixes, cut at the first price."""
    t = re.sub(r"^(?:NT)?\$\s?[\d,]+\s*酷澎幣回饋\s*", "", title)
    for p in UI_PREFIXES:
        while t.startswith(p):
            t = t[len(p):]
    t = re.split(r"\s(?:NT)?\$\s?[\d,]{2,}", t, maxsplit=1)[0]
    return t.strip() or title


def extract_cards(tab):
    res = tab.evaluate(CARDS_JS)
    for c in res["cards"]:
        c["raw_title"], c["title"] = c["title"], clean_title(c["title"])
    return res
