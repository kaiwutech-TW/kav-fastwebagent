---
record_id: 260929-bot-fx-rates
session: claude-code session 2026-09-29(台銀匯率流程)
date: 2026-09-29
repos: [Kav-test]
tests: 101 passed / pyright clean
prod_changes: none(新增使用者配方 ~/.kav-fastweb/recipes/bot-fx-rates.json,不在 git)
---

# 從零寫出「台銀今天的美金/日圓匯率」流程,並讓「是不是今天的」由程式證明

**TL;DR**:使用者說「幫我做一個流程:查台灣銀行今天的美金跟日圓匯率」。沒有現成配方 → Claude 照 kav-fastweb skill 寫 `detail_extract` 配方,第一次試跑就過;使用者確認結果後要求「加上檢查是不是今天的」,於是 kfw 新增內建 `{today}`(台灣時間)並讓 `detail_extract` 支援 `expect_text`,配方以「牌價最新掛牌時間：{today}」證明新鮮度後存檔。這是核心主張 (2)「Claude 能從零為新網站寫出配方」的第 3 種網站/第 1 份 detail_extract 實例。

## 關鍵發現(重要性排序)

1. **新網站從零到可用配方:1 次試跑就過,0 次修正。** 找配方 → inspect_page → 寫配方 → dry_run 通過,wall time 約 36 秒(12:21:12 → 12:21:48,不含冷啟動與讀 skill);MCP 工具呼叫 3 次(find、inspect、dry_run),單次讀頁 8.4–8.5 秒。人介入 1 次(skill 規定的「存檔前確認結果」),使用者追加 1 個需求。
2. **「今天的資料」原本無法由程式證明**:`detail_extract` 只檢查有沒有列,不看日期;第一版回報時是 Claude 看截圖判斷日期。依專案原則(完成判斷留在本地程式)補上 `{today}` + `expect_text` → DECISIONS 2026-09-29 `{today}` 那條。
3. `inspect_page` 的 `repeated_rows` 對台銀匯率表回 null(它只試內建的時間/價格/日期樣式),但自己寫 `\([A-Z]{3}\) .*\d+\.\d+` 一次就抓到 19 列。rows 取「符合 ≥60% 兄弟節點」的群組,所以 pattern 必須對整張表的列成立,**不能**寫成只對 USD|JPY 成立(只有 2/19 會被丟掉)→ 配方回傳全部幣別,由 Claude 挑使用者要的。

## 交付 / Commits

程式改動(`kfw/recipes.py` 的 `today()`/`render_recipe`/`run_detail_extract`、`tests/test_recipes.py`、`references/detail-extract.md`)**尚未 commit**:同檔案裡還有另一個 session 未 commit 的改動(list/delete_recipe、save 保留歷史),分開 commit 前需要使用者決定。本 commit 只含 record + STATE。

## 驗證證據

- 正向:本機以新程式 dry_run `df452bed32f2` → passed,`expect_text_missing=[]`,USD 31.4/32.07/31.75/31.85、JPY 0.1927/0.2055/0.2/0.204(現金買/賣、即期買/賣),截圖 `~/.kav-fastweb/runs/260929-122405-0ed4/detail.jpg` 顯示掛牌時間 2026/09/29 12:18,數字逐一對過。
- 反向:同配方把日期換成 2026/09/28 → `needs_help / result_not_proven`,hint 指出缺少的日期文字。
- `find_recipe("查台銀今天的美金跟日圓匯率")` → 命中 `bot-fx-rates`。
- 101 tests passed、pyright 0 errors。

## 未完 / 交接

- MCP server 要重開才會載入 `{today}`/`expect_text`;**重開前用 run_recipe 跑這個流程,日期檢查會被靜默略過**(舊程式不看 expect_text)。
- 非營業時間(晚上/假日)頁面標題會變「非營業時間匯率」,掛牌日期可能是前一個營業日 → 屆時流程會回 needs_help,是正確行為,但回報要跟使用者說明是「今天還沒掛牌」,不是壞掉。尚未實測。
