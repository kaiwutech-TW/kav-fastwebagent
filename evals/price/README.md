# 電商比價評測 — v0(2026-09-29)

四個不用登入的平台:PChome 24h、momo、Yahoo 購物、酷澎(要關掉 Cloudflare WARP)。6 個商品。

| 檔案 | 內容 |
|---|---|
| `listings-260929.jsonl` | 710 筆搜尋結果卡片(`bench/price/capture.py`,擷取器在 `kfw/extract.py`)。`url` 是商品頁網址;這版的搜尋頁網址被覆蓋掉了,可由 query+site 重建 |
| `labels-260929.jsonl` | 每頁前 10 名,共 217 筆的「同商品」標註:E 本體 / B 組合 / R 福利品 / A 配件 / O 其他型號 / X 分期。**Claude 草擬**(`label_source`),其中 13 筆標 `uncertain`,待人工複核 |

## 同商品判斷(Kev-4B,本機 MLX)

| 模式 | 做法 | 準確率(E vs 其他) | precision | recall | 每次呼叫 |
|---|---|---|---|---|---|
| single | 一題 6 選 1 + 一題 noul | 0.797 | 0.654 | 1.000 | 117 ms |
| decomposed | 5 題 noul(含型號比對)+ 規則 | 0.825 | 0.765 | 0.783 | 138 ms |
| **hybrid** | **型號用程式比對字串(planner 給 must / must_not),Kev 只答配件/組合/福利品/分期** | **0.949** | **0.883** | **1.000** | 136 ms(139/217 筆需要呼叫) |

`uv run python bench/price/judge_eval.py --mode hybrid`

- hybrid 剩下的 11 個錯誤**全部在 Switch 2**:遊戲片(「Switch 2 NS2 咚奇剛」)和主機組合被判成主機本體。可能的修法是讓 planner 規格要求「主機」字樣,**但這是看過錯誤之後才想到的,必須在新的商品上驗證**,不能拿這份資料來宣稱改進。
- `MATCH` 表是我扮演 planner 手寫的;正式版要由呼叫 MCP 的 Claude 在不看結果的情況下產生。
- 尚未處理:**售價解析**。卡片裡常同時出現原價、折扣價、首購價、「再省 $200」、酷澎幣回饋等金額,目前 `prices` 只是全部列出。
