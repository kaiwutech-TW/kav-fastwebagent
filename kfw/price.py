"""Read the comparable price out of a product card's text.

Rule (DECISIONS 2026-09-29): the main price is the one-time price anyone can pay. Conditional
offers (first-purchase price, card cashback, points / 酷澎幣) are returned as notes and never
used for ranking. Amounts that are not prices of the item (再省 $200, 運費 $45, $600 商品卡,
滿 $1,500 thresholds, unit prices) are dropped by their surrounding words.
"""

import re
from dataclasses import dataclass, field

AMOUNT = re.compile(r"(?:NT\$|\$)\s?([\d,]{2,9})(?:\.\d+)?|([\d,]{2,9})\s?元")
# Words right before an amount that make it not the item's price.
NOT_PRICE_BEFORE = ("再省", "運費", "商品卡", "满", "滿", "送", "贈", "折價券", "回饋", "折", "最高")
# Words right after an amount that make it not the item's price.
NOT_PRICE_AFTER = ("酷澎幣", "回饋", "商品卡", "/1", "/期", "期付", "元商品卡", "購物金")
DISCOUNT_THEN_PRICE = re.compile(r"^\s*\d{1,2}%\s*(?:NT\$|\$)\s?([\d,]{2,9})")


@dataclass
class Price:
    price: int | None
    original: int | None = None
    conditional: list = field(default_factory=list)  # [{"kind": "first_purchase", "price": 4290}]
    notes: list = field(default_factory=list)
    shipping: int | None = None


def _num(s):
    return int(s.replace(",", ""))


def _excluded(before, after):
    """Only words touching the amount count: "再省 $200" is out, "送好禮 $12,400" is in."""
    b, a = before.rstrip(" $NT"), after.lstrip()
    return any(b.endswith(w) for w in NOT_PRICE_BEFORE) or any(a.startswith(w) for w in NOT_PRICE_AFTER)


def _class_price_ok(text, value):
    """A class="price" number is kept only if some occurrence of it in the text passes the same filter
    (momo puts "滿1件折1,100元" in a price-classed element too)."""
    found = False
    for m in re.finditer(rf"(?<![\d,]){value:,}(?![\d,])|(?<![\d,]){value}(?![\d,])", text):
        found = True
        if not _excluded(text[max(0, m.start() - 4):m.start()], text[m.end():m.end() + 5]):
            return True
    return not found


def parse_price(text, class_prices=()):
    text = re.sub(r"\s+", " ", text or "")
    cands, conditional, notes, shipping, skip, listed = [], [], [], None, set(), []
    for m in AMOUNT.finditer(text):
        if m.start() in skip:
            continue
        value = _num(m.group(1) or m.group(2))
        before, after = text[max(0, m.start() - 4):m.start()], text[m.end():m.end() + 5]
        if "運費" in before:
            shipping = value
            continue
        if _excluded(before, after):
            continue
        if text[max(0, m.start() - 1):m.start()] == "(":
            continue  # "($479.00/1個)" unit price
        follow = DISCOUNT_THEN_PRICE.match(text[m.end():])
        if follow:
            second = _num(follow.group(1))
            nxt = AMOUNT.search(text, m.end())  # the "$B" of "$A n% $B": consumed here
            if nxt:
                skip.add(nxt.start())
            if "首購" in text[max(0, m.start() - 30):m.start()]:
                cands.append(value)  # regular price; the discounted one is first-purchase only
                conditional.append({"kind": "first_purchase", "price": second})
            else:
                cands.append(second)
                listed.append(value)  # struck-through list price
            continue
        cands.append(value)
    if not cands and class_prices:
        cands = [p for p in class_prices if p > 0 and _class_price_ok(text, p)]
    if not cands:
        return Price(None, conditional=conditional, notes=notes, shipping=shipping)
    main = min(cands)
    original = max(cands + listed) if max(cands + listed) > main else None
    if re.search(rf"{main:,}起|{main}起", text):
        notes.append("起價(多種規格,最低規格的價格)")
    return Price(main, original, conditional, notes, shipping)
