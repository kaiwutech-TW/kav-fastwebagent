# form_submit:填表單、送出、讀結果

適用:時刻表、包裹追蹤、查詢系統這類「填幾個欄位 → 按查詢 → 看結果列表」的頁面。

## 欄位

```json
{
  "type": "form_submit",
  "url": "https://www.thsrc.com.tw/",
  "pre": [{"click": "不同意", "optional": true}],
  "fields": [
    {"label": "出發站", "kind": "select", "value": "{from}"},
    {"label": "出發日期", "kind": "text", "value": "{date}"}
  ],
  "submit": {"click": "查詢"},
  "result": {
    "rows": {"pattern": "\\d{2}:\\d{2} \\d{2}:\\d{2} \\d{2}:\\d{2} \\d{3,4}", "min_rows": 1, "max_rows": 30},
    "expect_text": ["{date}"]
  }
}
```

| 欄位 | 說明 |
|---|---|
| `pre` | 開頁後要先點的東西,例如 Cookie 橫幅。**選最少同意的選項**(例如「不同意」)。`optional: true` 表示找不到也沒關係 |
| `fields[].label` | 照抄 `inspect_page` 的 `fields[].label` |
| `fields[].kind` | `select`(下拉選單)或 `text`(輸入框)。Kav 會自動判斷已經是目標值的欄位並跳過 |
| `fields[].value` | 下拉選單:優先找完全相同的選項,其次找包含關係,最後才讓 Kev 選。輸入框:原樣輸入,並讀回確認 |
| `submit.click` | 送出按鈕的文字,照抄 `inspect_page` 的 `clickables` |
| `result.rows.pattern` | 一列結果的 regex,比對每列正規化後的文字(空白會壓成一個)。要**具體到只會命中結果列**:只寫 `\d{2}:\d{2}` 會連公告的時間一起命中 |
| `result.rows.min_rows` | 至少要有幾列才算完成 |
| `result.rows.columns` | **每格的欄名**,一格一個,`null` 表示丟掉那格。有寫就回傳 `{欄名: 值}`,沒寫只回傳沒有欄名的字串陣列,回答時很容易讀錯欄(例:把停靠站的發車時間當成抵達時間)。欄名照網站表頭寫,意思不明顯的要寫清楚(`停靠站與各站發車時間`)。某列格數對不上就回傳 `result_not_proven`,不會亂貼欄名 |
| `result.expect_text` | 結果頁一定會出現的文字,通常是查詢條件本身(日期、站名),用來證明查的是對的條件 |

## 寫法提示

- `inspect_page` 的 `repeated_rows` 只能當參考,那是**送出前**的頁面。要看結果列長什麼樣,先用一份初版配方試跑,再看回傳的 `rows` 和截圖,調整 pattern。
- 日期、時間輸入框:照 `inspect_page` 顯示的 `value` 格式寫 pattern(例如 `2026/09/29` → `\d{4}/\d{2}/\d{2}`)。
- 沒有 label 的欄位(`"label": ""`)不要寫進 fields;如果一定要設定,告訴使用者這個網站目前做不到。
