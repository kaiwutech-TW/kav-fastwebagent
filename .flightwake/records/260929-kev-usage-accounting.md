---
record_id: 260929-kev-usage-accounting
session: claude-code session 2026-09-29(第五個 session:重開後驗證欄名、記錄 Kev 用量)
date: 2026-09-29
repos: [Kav-test]
tests: 104 passed / pyright 0 errors
prod_changes: none
---
<!-- flightwake record — 飛行紀錄。 -->

# 欄名重開後確認生效;每次執行都回報本機模型 Kev 花了多少

**TL;DR**:上個 session 加的「結果每格附欄名」要重開 Claude Code 才生效,本 session 重開後經 MCP 實跑高鐵與台銀確認生效,答案與官網截圖一致。接著補上一直量不到的本機模型成本:每次執行流程都會回傳 Kev 呼叫次數、token 與耗時。比價一趟(4 個網站)Kev 被呼叫 18 次、共約 6 千 token;高鐵實測 0 次(台銀是讀單頁的流程類型,引擎不會呼叫 Kev)。

## 關鍵發現(重要性排序)

1. **本機模型的成本很小,而且只有比價用得到。** Switch 2 比價一趟:

   | 流程 | 整趟 | Kev 呼叫 | 輸入 / 輸出 token | Kev 模型時間加總 | kfw 等待加總 |
   |---|---|---|---|---|---|
   | 比價 Switch 2(PChome / momo / Yahoo / 酷澎) | 5.6 秒 | 18 | 4,491 / 1,630 | 3.9 秒 | 6.5 秒 |
   | 高鐵 台中→台北 10/12 15:00 | 6.4 秒 | 0 | 0 | 0 | 0 |

   對照 [[260929-control-experiment-and-demo]]:讓 Claude 一步步操作瀏覽器做高鐵,一趟要 77–128 萬輸入 token(雲端)。Kav 路徑的雲端成本是回答使用者的那個 Claude(17–27 萬,見該 record),Kev 另外只在本機花約 6 千 token。每站判斷前 10 筆、共 40 筆,其中 22 筆由程式的型號比對直接排除、沒問 Kev(每站只問 1–7 次)——**程式先篩、模型只判斷語意**的分工讓呼叫數維持很低。
   kfw 等待加總(6.5 秒)大於整趟(5.6 秒),是因為四站並行;欄位名因此寫成 `call_ms_sum` / `model_ms_sum`(DECISIONS 2026-09-29)。
2. **比價不需要 `rows.columns`。** STATE 原本列了「比價補欄名」,但比價回傳的每筆本來就是具名欄位(site、title、price…),沒有高鐵那種讀錯欄的風險;已從待辦移除。

## 交付 / Commits

1d1f9b9..本 record(42851a4 是程式;其餘是 STATE)

## 驗證證據

- 欄名重開後經 MCP 實跑:高鐵 `done` 6.4 秒(`~/.kav-fastweb/runs/260929-133050-b2cd`),0648 抵達 15:59、1234 抵達 15:54、0652 抵達 16:33,與 `result.jpg` 截圖一致;台銀 `done` 8.5 秒(`-133057-5227`),19 種幣別皆帶 5 個欄名。
- Kev 用量:單元測試用假的 Kev 驗證累計(2 次呼叫、240/8 token;程式直接排除的卡片不計)。真實比價以 Python 直接呼叫引擎(MCP server 還是舊程式):`done`、4 站皆 ok、最低價酷澎 14,780 元並在商品頁驗證(`runs/260929-133253`);高鐵 `kev.calls = 0`(`-133314-023f`)。
- 104 passed、pyright 0 errors。

## 未完 / 交接

- MCP server 是舊程式,要**重開 Claude Code** 後經 MCP 跑一次比價,確認回傳有 `kev` 欄位。
- 其餘見 STATE。
