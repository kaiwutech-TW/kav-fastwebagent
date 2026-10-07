---
record_id: 260929-kav-fastweb-v0
session: claude-code 2026-09-29(第一個 session)
date: 2026-09-29
repos: [Kav-test]
tests: 97 passed / pyright 0 errors
prod_changes: none(全部本機;沒有部署。本機資料寫在 ~/.kav-fastweb/)
---
<!-- flightwake record — 飛行紀錄。 -->

# 從「Kev 在中文好不好」到可用的 Kav-FastwebAgent:本機 MCP + skill + 配方

**TL;DR**:起點是想用開源的 Kev(jaredpalmer/kev,以 Qwen3.5 為底、仿 TypeSafe Jev 的決策模型)做一個適合台灣市場的工具。
第一步先量 Kev 的繁中能力,接著依序試了網頁自動化(jev-ultrafast、Laya)和電商比價。
最後收斂成 **Kav-FastwebAgent**:Claude 透過 `kav-fastweb` skill 為「網站 × 動作」寫 JSON 配方,試跑通過並附證據才能存檔;
之後由本機的 Chrome、Kev 和程式驗證快速執行。目前有兩份內建配方:台灣四站比價、高鐵時刻表。

## 關鍵發現(依重要性排序)

1. **把問題拆成 Kev 擅長的小題,比寫一個大 prompt 有效得多;精確比對交給程式。**
   - 高鐵模擬頁:一題大選擇題 1/6,拆成每個欄位問一題 12/12。
   - 比價同商品判斷:單題 0.797,「型號由程式比對 + Kev 只回答配件、組合、福利品」0.949。
   - 已記入 TRAPS `kev-weak-at-literal-model-matching`、DECISIONS 2026-09-29(配方路線)。
2. **「完成」和「結果對不對」都必須由程式證明,不能相信模型說的。**
   - 高鐵:結果還沒非同步載入完,模型就判定完成(TRAPS `web-agent-false-done-before-async-results`)。
   - 比價:沒看過的 PS5 Pro,最低價一度是 $399 的支架。後來靠「價格合理性防線 + 商品頁結構化資料驗證」修正
     (TRAPS `price-compare-false-matches-need-price-guard`)。
   - 設計上現在是這樣實作的:配方沒有程式能檢查的完成條件就存不進去;`best` 一定經過商品頁驗證。
3. **Kev 的繁中能力可以用。** 簡中的路由題和 Jev 同級(語音 0.954 vs 0.960);換成台灣原生語句,判斷只翻轉 1.5%(Laya 是 12.8%)。
   弱點是評分題和是非題的校準。數字和重現方式在 `evals/README.md`;訓練資料幾乎沒有中文,見 TRAPS `kev-chinese-advantage-unverified`。
4. **jev-ultrafast 的瀏覽器層在真實網站上不可靠**(填字全選被攔截、每步只等 50ms、只看畫面內的文字、完成誤判),
   所以自己寫了 `kfw/`。Laya 在 MLX 上每步只要 20–42ms,但在網頁操作決策上 0/6(TRAPS `laya-cannot-drive-web-agent-policy`)。
5. **能不能連上網站**:開著 Cloudflare WARP 時酷澎拒絕存取;蝦皮和淘寶要登入(TRAPS `shopee-taobao-block-anonymous-automation`)。
   Chrome 136 以後不能用 CDP 連預設 profile,所以 Kav 用自己專屬的 profile。
6. **這台 Mac(M5 Max 36GB)可以在本機訓練短資料**;長資料(約 3.8k tokens)會吃光記憶體(TRAPS `kev-mps-training-oom-long-states`)。訓練目前暫停。

## 交付 / Commits

12d4f19..2849ad9(三段:繁中評測與探針 → MCP 比價 v0 → skill 與配方系統)

## 驗證證據

- 單元測試 97 個通過(售價規則用 83 張真實卡片、配方的存檔門檻、參數格式檢查);pyright 0 errors。
- 走 MCP stdio 協定、跑真實網站:
  - `tw-shop-compare`:AirPods Pro 3 最低價酷澎 $6,475,商品頁驗證通過,6.3 s;
    PS5 Pro 最低價 momo $44,580(Yahoo 同型號同價),驗證通過,$27,478 那筆因缺貨被移出,5.4 s。
  - `thsr-timetable`:照 skill 流程寫出(inspect_page → dry_run → 看截圖 → save_recipe);
    用新參數(新竹到台南、2026/10/12、14:00)跑,5.4 s 回傳 5 班車;`2026/10/5` 被參數格式檢查擋下。
- 評測:`evals/README.md`(繁中)、`evals/price/README.md`(比價同商品判斷)。截圖留在本機 `~/.kav-fastweb/runs/`,依使用者決定不進 git。

## 未完 / 交接

- **還沒在真正的 Claude Code session 裡用過 skill**(目前都是用腳本模擬 MCP client)→ 使用者重開 Claude Code 後驗收。STATE 下一步 1。
- 組合包判斷偏弱;Kev 呼叫改批次(四站並行時單次從 136ms 拖到約 450ms);`detail_extract` 沒有實跑過真實網站。
- 13 筆 `uncertain` 標註(`evals/price/labels-260929.jsonl`)待使用者複核。
