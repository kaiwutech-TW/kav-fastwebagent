"""Price rule on 83 real search-result cards (evals/price, 2026-09-29). Expected values were read
off each card by hand under the DECISIONS 2026-09-29 rule: main price = one-time price anyone pays."""
import json
from pathlib import Path

import pytest

from kfw.price import parse_price

CARDS = [json.loads(l) for l in open(Path(__file__).parent / "fixtures" / "price_cards.jsonl", encoding="utf-8")]


@pytest.mark.parametrize("card", CARDS, ids=[f"{c['site']}-{c['i']}" for c in CARDS])
def test_main_price(card):
    p = parse_price(card["text"], card["class_prices"])
    assert p.price == card["price"]
    fp = [c["price"] for c in p.conditional if c["kind"] == "first_purchase"]
    assert fp == ([card["first_purchase"]] if card["first_purchase"] else [])


def test_cashback_and_thresholds_are_not_prices():
    p = parse_price("$226 酷澎幣回饋 Switch 2 主機 $14,780 明天送達 最高再省 $200 (王道卡) 满 $1,500 再省 $75")
    assert p.price == 14780 and p.original is None


def test_shipping_is_separate():
    p = parse_price("SONY WH-1000XM6 $13,900 運費 $45 起")
    assert (p.price, p.shipping) == (13900, 45)


def test_starting_price_is_flagged():
    p = parse_price("滿1件折1,100元 WH-1000XM6 9,780起(售價已折)", class_prices=[9780])
    assert p.price == 9780 and any("起價" in n for n in p.notes)
