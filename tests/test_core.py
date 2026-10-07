from kfw.extract import clean_title
from kfw.judge import literal_match
from kfw.sites import classify


def test_literal_match_near_miss_models():
    must, must_not = [["switch2", "ns2"]], ["lite", "oled"]
    assert literal_match("【Nintendo 任天堂】Switch 2 主機(台灣公司貨)", must, must_not)
    assert not literal_match("Nintendo SWITCH Lite 遊戲主機 灰色", must, must_not)
    assert not literal_match("Nintendo SWITCH OLED款式 遊戲主機", must, must_not)


def test_literal_match_all_groups_needed_and_fullwidth():
    must = [["iphone17"], ["256"]]
    assert literal_match("Apple iPhone 17(256G/6.3吋)", must, ["17e", "17pro"])
    assert not literal_match("Apple iPhone 17 Pro(256G/6.3吋)", must, ["17e", "17pro"])
    assert not literal_match("Apple iPhone 17(512G)", must, [])
    assert literal_match("ＩＰＨＯＮＥ １７ ２５６ＧＢ", must, [])  # NFKC folds full-width


def test_clean_title():
    assert clean_title("比較 找相似 Apple AirPods Pro 3 降噪無線藍牙耳機 $6,699 4.8 (23)") == "Apple AirPods Pro 3 降噪無線藍牙耳機"
    assert clean_title("$226 酷澎幣回饋 Nintendo Switch 2 主機 $14,780") == "Nintendo Switch 2 主機"


def test_classify_page_outcomes():
    assert classify("https://shopee.tw/verify/traffic/error", "請登入", 0)[1] == "verification"
    assert classify("https://s.taobao.com/search", "请输入手机号 登录", 0)[1] == "login_required"
    assert classify("https://www.tw.coupang.com/search", "您沒有權限存取此頁面", 0)[1] == "access_denied"
    assert classify("https://x/search", "很抱歉,查無相關商品" + "x" * 800, 0)[0] == "no_results"
    assert classify("https://x/search", "x" * 800, 0)[0] == "extraction_failed"
    assert classify("https://x/search", "x" * 800, 12)[0] == "ok"


def test_price_guard_flags_accessory_and_stuffed_titles():
    from kfw.compare import split_suspicious
    prices = [399, 17989, 27478, 44580, 44980, 44980, 44580]
    ok, flagged = split_suspicious([{"price": p} for p in prices])
    assert sorted(o["price"] for o in flagged) == [399, 17989]
    assert all(o["price"] >= 27478 for o in ok)


def test_submit_effect_needs_evidence_after_the_click():
    from kfw.form import submit_effect
    href = "https://www.thsrc.com.tw/"
    assert submit_effect(href, 10.0, 0.0, [href, 500.0, 400.0]) is None  # dead button: nothing after the click
    assert submit_effect(href, 10.0, 9.0, [href, 500.0, 400.0]) is None  # request started before the click
    assert submit_effect(href, 10.0, 10.5, [href, 500.0, 400.0]) == "request"
    assert submit_effect(href, 10.0, 0.0, [href, 500.0, 520.0]) == "dom"
    assert submit_effect(href, 10.0, 0.0, [href + "ArticleContent/x", 500.0, 0.0]) == "navigated"
    assert submit_effect(href, 10.0, 0.0, [href, None, 0.0]) == "navigated"  # new document lost the mark
    assert submit_effect(href, 10.0, 0.0, None) == "navigating"


def test_judge_tallies_kev_tokens_and_time():
    import httpx
    from kfw.judge import Judge

    def kev(req):
        qs = __import__("json").loads(req.content)["questions"]
        answers = {k: ({"choice": "台北", "probabilities": {"台北": 0.9}} if v["type"] == "choice" else {"noul": 0.1})
                   for k, v in qs.items()}
        return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 120, "output_tokens": 4}, "latency_ms": 30})

    j = Judge()
    j.client = httpx.Client(transport=httpx.MockTransport(kev))
    assert j.usage()["calls"] == 0
    card = {"title": "Apple AirPods Pro 3", "text": ""}
    assert j.judge("AirPods Pro 3", card, [["airpodspro3"]], [])[0] == "E"
    assert j.judge("AirPods Pro 3", {"title": "AirPods 4"}, [["airpodspro3"]], [])[2] == 0  # code decided: no Kev call
    assert j.choice("哪個是台北?", ["台北", "南港"])["choice"] == "台北"
    u = j.usage()
    assert (u["calls"], u["input_tokens"], u["output_tokens"], u["model_ms_sum"]) == (2, 240, 8, 60)
    assert u["call_ms_sum"] >= 0
