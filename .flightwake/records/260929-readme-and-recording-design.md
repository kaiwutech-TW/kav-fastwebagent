---
record_id: 260929-readme-and-recording-design
session: claude-code session 2026-09-29(第六個 session:README 三語、錄製功能設計與第一批工作包)
date: 2026-09-29
repos: [Kav-test]
tests: 123 passed / 29 Chrome 整合 passed / pyright 0 errors(merge ab35e9f + 2fbed2d)
prod_changes: none
---
<!-- flightwake record — 飛行紀錄。 -->

# README 三語版;「使用者示範一次 → 流程」錄製功能設計經 Codex 三輪複查核准,第一批工作包合併

**TL;DR**:確認 Kev 用量欄位經 MCP 生效後,把 README 改寫成產品故事(圖文、硬體建議、貼給 Claude Code 的安裝段、三語)。調查同類專案後,使用者決定做錄製功能三階段。
設計由 Opus 寫、Codex(gpt-6-astra,orca terminal)複查三輪(v1 24 點 → v2 12 點 → v3 3 點 → v3.1 核准),實作交給 Sonnet 子 agent 分工作包在 worktree 平行做。
WP0a(CDP 分派)、WP0b(共用觀察層)已合併並在真實網站驗證;WP0c(安全入口)、WP-S(CDP spike)進行中。

## 關鍵發現(重要性排序)

1. **高鐵快 5 倍跟 Kev 無關。** 高鐵、台銀流程 Kev 呼叫 0 次,速度來自「流程 + 本機程式」,跟 workflow-use / Stagehand / Skyvern 的「探索一次、之後照著跑」同一類。
   Kav 能講的差別是「答案由程式證明」(讀回、欄名、日期、商品頁核對),不是快。「本機模型加速」目前只有比價一例撐。已寫進 README 的「還不夠的地方」。
2. **workflow-use 的自我修復在程式碼裡是關掉的。** 讀了它的原始碼(2026-08-27):步驟失敗時丟 `Agent fallback is disabled`,讀結果靠 LLM。
3. **設計複查抓到的真問題**(若照 v1 實作會出事):錄製 binding 暴露在網站主世界可被偽造;「點擊後欄位值變了就吸收」會吞掉送出按鈕;示範留下的 cookie/storage 會讓漏錄的流程在重播時照樣通過一致檢查(改成隔離瀏覽器環境重播);改狀態動作的授權必須在第一次試跑之前。
4. **使用者指正:改狀態動作(加入購物車等)是使用者的決定。** 我原本為了讓整段重跑安全而全面禁止,被指正後改為「動作三級」(DECISIONS),並存成記憶。
5. **台銀擋 headless Chrome**(TRAPS `bot-fx-headless-chrome-cloudflare-challenge`,suspected):真站驗收要用有視窗的隔離 Chrome。

## 交付 / Commits

3bef6e0..f5d1935(18 commits)。重點:53b2f78 / bbef056(README 三語、GIF 遮蔽)、b82052f → 504cd2d(設計 v1→v3.1 與四份複查紀錄 `docs/design/demo-recording.review*.md`)、
c5b98e0(合併 WP0a)、ab35e9f(合併 WP0b)、2fbed2d(關閉時空訊息框)、f5d1935(trap)。

## 驗證證據

- Kev 欄位:MCP 比價 Switch 2 `done` 7.8 秒、Kev 31 次 / 7,987+2,811 token(`~/.kav-fastweb/runs/260929-133729`)。
- WP0a:`tests/test_cdp.py` 8 個(假 websocket),合併後全套 112 passed。
- WP0b:29 個 Chrome 整合測試(Chrome 154.0.8037.58,隔離 :9444、暫存 KFW_HOME),含改版前後 `controls()`/`rows()` 在 9 個 fixture 頁的等價比對。
- 合併 WP0a+WP0b 後,有視窗的隔離 Chrome 真站:`thsr-timetable` done 7.1 秒、5 列、送出效果 `request`、Kev 0;`bot-fx-rates` done 8.5 秒、19 列。
- 設計複查的數字:v1 24 點(9 阻擋)→ v2 12 點 → v3 3 阻擋 → v3.1 APPROVE;每輪 Codex 約 5–10 分鐘。

## 未完 / 交接

- WP0c、WP-S 子 agent 進行中;回來後審查合併,依 spike 結果修設計 §2.2/§3.3,再開 WP1。
- 公開 repo 前的待辦(GitHub repo 未建、git 歷史裡有未遮蔽 GIF)見 STATE。
- 其餘見 STATE。
