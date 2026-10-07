# detail_extract:讀一個已知網址

適用:商品頁的價格、庫存、全新與否;有固定網址的公告或列表頁。

```json
{
  "type": "detail_extract",
  "url": "{url}",
  "rows": {"pattern": "\\d{4}/\\d{2}/\\d{2}", "min_rows": 1},
  "params": {"url": {"description": "商品頁網址", "example": "https://24h.pchome.com.tw/prod/DMAX00-A900HC7B6", "pattern": "https://.+"}}
}
```

- 商品頁:Kav 會讀頁面自己的結構化資料(JSON-LD 或 product meta),回傳 `product`,欄位有 name、price、list_price、condition、availability。
  PChome、momo、Yahoo 購物、酷澎都有這些資料。不用寫任何欄位設定。
- 其他頁面:寫 `rows.pattern`,回傳符合的重複列;再寫 `rows.columns` 給每格一個欄名(`null` 丟掉那格,例如重複的「查詢」按鈕),規則同 form_submit。
- `product` 和 `rows` 都拿不到,就回傳 `needs_help`(`no_structured_data`)。
- 要證明頁面是**今天的**資料(匯率、公告):加 `expect_text`,**把日期連同它前面的標籤一起寫**,例:`["牌價最新掛牌時間：{today}"]`——只寫 `{today}` 會被頁面上其他地方的今天日期(日期選單、新聞)誤中。`{today}` 由程式代入台灣時間的今天(`2026/09/29` 格式),
  不是參數、不用使用者給;頁面上找不到就回傳 `needs_help`(`result_not_proven`)。網站的日期格式不是 `YYYY/MM/DD` 時不要用它。
