# search_compare:多站搜尋 → 挑出符合的 → 比價

適用:在一或多個網站搜尋,從結果列表挑出「就是這個東西」的項目並比價。
內建配方 `tw-shop-compare` 已經涵蓋 PChome / momo / Yahoo 購物 / 酷澎;**台灣電商比價直接用它,不要重寫**。

## 欄位

```json
{
  "type": "search_compare",
  "search": {"pchome": "https://24h.pchome.com.tw/search/?q={query}", "momo": "..."},
  "per_site": 10,
  "verify_top": 3,
  "params": {
    "query": {"description": "每個網站搜尋框要打的關鍵字", "example": "AirPods Pro 3"},
    "spec": {"description": "一行中文描述商品", "example": "Apple AirPods Pro 3 耳機本體(全新)"},
    "must": {"description": "list of groups;每一組至少命中一個詞"},
    "must_not": {"description": "出現就排除的詞(相近型號)", "required": false}
  }
}
```

- `search` 的網址裡 `{query}` 會自動做 URL encode。
- 結果列表由程式擷取(找頁面上重複出現、有圖片、連結和價格的卡片),不需要寫 selector。

## 呼叫時要給的參數(最重要)

| 參數 | 怎麼寫 |
|---|---|
| `must` | 型號的必要字串,比對時轉小寫、去掉空白。例:`[["airpodspro3"]]`、`[["switch2","ns2"],["主機"]]`、`[["iphone17"],["256"]]` |
| `must_not` | 相近型號,例:`["airpods4","airpods5"]`、`["lite","oled"]`、`["17e","17pro","promax"]` |
| `spec` | Kev 用它判斷配件、組合包、福利品 |

**用你對產品線的知識,在看到結果之前寫好。** 相近型號想得越完整越好。

## 讀結果

- `best` 一定是在商品頁驗證過的(價格、庫存、全新與否、名稱)。如果沒有任何一筆驗證通過,會出現 `nothing_verified`。
- `price` 是任何人都買得到的一次付清價;首購價、回饋在 `conditional_offers` / `notes`。**回報時兩者都要講清楚**。
- `suspicious`:價格離中位數太遠的商品(可能是配件、灌關鍵字的標題、組合包),不參與排序。要讀一下,必要時告訴使用者。
- 已知弱點:組合包(例如「主機 + Portal」)有時會被當成單品。回報前看一下標題。
