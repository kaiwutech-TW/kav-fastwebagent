---
record_id: 260929-repair-and-user-flow
session: claude-code session 2026-09-29(第三個 session:修復盲測與使用者流程)
date: 2026-09-29
repos: [Kav-test]
tests: 102 passed / pyright 0 errors
prod_changes: none(使用者配方與 Kav Chrome profile 都在 ~/.kav-fastweb/,不在 git)
---
<!-- flightwake record — 飛行紀錄。 -->

# 驗證「配方壞了 Claude 自己修得好」,把使用者端做成「用說的建立流程」;蝦皮確認不可自動化

**TL;DR**:起點是 health yellow(高鐵重跑修法未被真實失敗驗證)和一個問題:能不能用已登入的 Chrome。途中蝦皮被證實會擋 CDP 控制(登入也沒用),使用者因此把專案重心從「打磨比價」拉回核心主張——**網站改版時,不懂程式的使用者靠 Claude 就能修好流程,而且流程跑得快、安全檢查留在本地程式**。兩輪盲測(另開全新 session,不告知哪裡壞)Claude 都修對;接著把使用者端改成「流程」的說法、建立前確認一次、可列出/刪除,並用第三個盲測(台銀匯率,見 [[260929-bot-fx-rates]])證明一般人一句話就能建立新流程。

## 關鍵發現(重要性排序)

1. **修復流程在兩種常見改版下成立**(盲測:我弄壞使用者配方,另開全新 Claude Code session 用一般人的話提需求,不提示壞了):

   | | 第 1 輪:欄位改名(`出發站`→`起程站`) | 第 2 輪:結果列格式對不上 |
   |---|---|---|
   | 失敗回報有沒有洩題 | 有(`controls_seen` 直接列出正確欄位名) | 沒有(只有 rows=0) |
   | 結果 | 自動修好、存檔、答題 | 先從截圖給部分答案並問要不要修;使用者說「好」後修好 |
   | 時間 / 輸出 token / 工具呼叫 | 2 分 12 秒 / 約 1.2 萬 / 11 | 約 2 分 16 秒(29 秒 + 1 分 47 秒)/ 約 2.6 萬 / 20 |
   | 使用者介入 | 0 | 1 句 |

   兩輪都只改了壞掉的那一處,修好後我用別的參數重跑皆 `done`。第 2 輪它明確排除了 TRAPS `form-submit-fills-half-initialized-page`(症狀相同但截圖不同),沒被舊坑帶偏。
   觀察到的缺點(已修進 skill,commit 189e193):找配方檔多花 2 次 shell、斷言「網站改版了」(它分辨不出)、用英文回中文使用者、把舊條件留成「備選」、重存會覆蓋驗證歷史。使用者決定:以後**直接修好再回報**(DECISIONS)。
2. **盲測會污染飛行紀錄。** 第 2 輪的修復者發現「12:06 才驗證過、12:11 就壞」不合理,把它登成 trap「高鐵結果格式會漂移」——觀察正確、推論錯(網站沒變,是我弄壞的)。沒發現的話所有未來 session 都會信它。已標 superseded(`thsr-result-row-text-format-drift`)並還原配方。**往後做破壞測試:結束立刻還原,並在 record 寫明破壞的時間窗與內容。**
3. **舊引擎會默默跳過新檢查,還回報成功**(TRAPS `old-engine-silently-ignores-new-recipe-checks`,confirmed)。台銀流程用了新的 `expect_text` 日期檢查,但還沒重開的 MCP server 不認得,照樣 `done`。已修:`validate()` 依類型白名單拒絕不認得的欄位(只保護往後)。
4. **使用者建立流程 = 說一句話 + 確認一次。** 台銀匯率從零到試跑通過約 36 秒、3 次工具呼叫;存檔前問「這是你要的嗎?」並給出以後的說法(數字見 [[260929-bot-fx-rates]])。使用者要求「檢查是不是今天」時,流程格式表達不了,修復者**改了引擎**(通用的 `{today}` + detail_extract `expect_text`,附測試)。在 repo 裡可接受;但若發佈給他人,使用者端的 Claude 不該改引擎 → 需要「回報缺少的能力」的管道。
5. **蝦皮擋的是 CDP 控制本身,登入解不開**(TRAPS `shopee-taobao-block-anonymous-automation` 升 confirmed)。同一個 Kav Chrome、同帳號、同台灣 IP(WARP off):使用者手動 2 次(首頁搜尋框、直接貼網址)都看得到商品;程式 2 次(`inspect_page`,含使用者剛完成簡訊驗證之後)都被導到 `verify/traffic/error?...is_logged_in=true`。不再往下分辨機制(那就是在繞偵測),蝦皮排除(DECISIONS)。
6. **BigGo 能不碰蝦皮拿到蝦皮商品**,但只能當行情參考:`/s/<q>?m=cp&c[]=tw_bid_shopee&c[]=tw_mall_shopeemall` 只列蝦皮;轉址連結的 `purl` 參數就是真的蝦皮商品網址。抽查 1 筆:價格對,但它是**福利品**而標題寫「原廠公司貨」——BigGo 分不出新舊,我們也進不了蝦皮商品頁核對。抽取時的卡片邊界坑見 TRAPS `biggo-card-ancestor-spans-offers`。尚未寫成配方。
7. 高鐵「送出沒反應就重跑」仍未被真實失敗觸發:新程式走 MCP 3 趟(熱跑、關 Kav Chrome 冷跑、換起訖站)都 `done`,送出後 1–2ms 見到請求,沒有 `retry`。trap 維持 suspected。
8. 登入與瀏覽器的取捨(DECISIONS):用 Kav 專屬 profile 由使用者手動登入(隔離、建議副帳號;:9333 任何本機程式都能連),不用平常的 Chrome profile(Chrome 136 起拒絕遠端除錯),暫不做 Chrome 擴充功能。

## 交付 / Commits

a4de5f6..189e193(e79ce49 是另一個 session 的台銀 record;189e193 合併兩個 session 交錯在同檔案的程式改動,訊息裡分列)

## 驗證證據

- 102 passed、pyright 0 errors(189e193 當下)。現有三份配方(內建 2、使用者 1)都通過新的欄位白名單。
- 修復盲測對話紀錄:`~/.claude/projects/-Users-kaiwu-orca-projects-Kav-test/9002126d-….jsonl`(第 1 輪)、`57062d32-….jsonl`(第 2 輪);修好後重跑截圖 `~/.kav-fastweb/runs/260929-120735-d9ac/`、`260929-121407-6131/`。
- 破壞時間窗:12:05 前後(第 1 輪)、12:10–12:14(第 2 輪),都已還原成 repo 內建版的條件。
- 高鐵 3 趟:`runs/260929-113413-0f30`、`-113428-f120`、`-113437-b3f7`。

## 未完 / 交接

- 目前這個 Claude Code 的 MCP server 是舊程式:**重開後**才有 `list_recipes`/`delete_recipe`、欄位白名單、`{today}`。
- 缺對照組:同樣的任務一般 agent(Claude in Chrome 一步步操作)要多久、多少 token——「快多少」要靠這個數字。其餘見 STATE。
