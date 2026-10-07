"""Shops Kav-FastwebAgent can search without logging in, and how to tell why a page gave nothing.

Page outcomes are classified by code so the caller gets a reason it can act on
(TRAPS shopee-taobao-block-anonymous-automation).
"""

from urllib.parse import quote

SITES = {
    "pchome": {"name": "PChome 24h", "search": "https://24h.pchome.com.tw/search/?q={q}"},
    "momo": {"name": "momo 購物網", "search": "https://www.momoshop.com.tw/search/searchShop.jsp?keyword={q}"},
    "yahoo": {"name": "Yahoo 購物中心", "search": "https://tw.buy.yahoo.com/search/product?p={q}"},
    "coupang": {"name": "酷澎 Coupang", "search": "https://www.tw.coupang.com/search?q={q}"},
}

NO_RESULTS = ("查無", "找不到", "沒有找到", "0 筆結果", "0筆結果", "沒有符合")


def search_url(site, query):
    return SITES[site]["search"].format(q=quote(query))


def classify(url, text, n_cards):
    """-> (status, reason, hint). status: ok | no_results | blocked | extraction_failed."""
    u, t = (url or "").lower(), text or ""
    if "verify" in u or "captcha" in u or "滑块" in t or "驗證碼" in t:
        return "blocked", "verification", "網站要求人機驗證;請使用者在 Kav 專用 Chrome 手動完成後重試,不要嘗試繞過"
    if "沒有權限存取" in t or "access denied" in t.lower() or "you don’t have permission" in t.lower():
        return "blocked", "access_denied", "網站拒絕存取;若開著 Cloudflare WARP / VPN / 私密轉送請先關閉"
    if len(t) < 600 and any(w in t for w in ("請登入", "尚未登入", "登录", "Log in", "Sign in")):
        return "blocked", "login_required", "此站搜尋需要登入;請使用者在 Kav 專用 Chrome profile 登入"
    if n_cards:
        return "ok", None, None
    if any(w in t for w in NO_RESULTS):
        return "no_results", "no_results", "搜尋沒有結果;可請 planner 放寬關鍵字"
    return "extraction_failed", "no_cards_found", "頁面有內容但找不到商品列表;需要 Claude 用 Claude in Chrome 檢查"
