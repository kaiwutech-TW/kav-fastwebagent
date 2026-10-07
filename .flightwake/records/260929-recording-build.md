---
record_id: 260929-recording-build
session: claude-code session 2026-09-29(第六個 session 後半:錄製功能三階段實作)
date: 2026-09-29
repos: [Kav-test]
tests: 433 passed / Chrome 整合 190 passed(6 個需真站/真 Kev 另跑 9 passed)/ pyright 0 errors(HEAD 合併後)
prod_changes: none(新增 MCP 工具 start_recording / stop_recording;要重開 Claude Code 才載入)
---
<!-- flightwake record — 飛行紀錄。 -->

# 錄製功能三階段程式完成:示範 → 草稿 → 隔離重播證明 → 存檔;steps(多步驟、翻頁、從列表挑一筆)

**TL;DR**:照 Codex 核准的設計 v3.2,由 Sonnet 子 agent 在各自 worktree 平行實作 9 個工作包,Opus 逐包審查、修正、合併,
每包都有 Chrome 整合測試(隔離 Chrome、fixture 網站),關鍵包另在真實網站驗證。尚未做的是**真人示範驗收**(需重開 Claude Code)。

## 關鍵發現(重要性排序)

1. **「從列表挑一筆」的本機模型價值,取決於問法。** Kev-4B 在 4 列語意 fixture、5 個口語需求(門檻不變:最高 ≥ 0.8 且贏第二名 ≥ 0.3):

   | 問法 | 有解 4 題 | 無解 1 題 |
   |---|---|---|
   | 一題選擇題(含「都不是」) | 0/4 選中(全停) | 正確停下 |
   | 每列一題是非題、原始列文字 | 1/4 | 正確停下 |
   | 每列是非題 + 去掉價格/按鈕字 + 候選清單放 state | **4/4 選對(p 0.89–0.96)** | 正確停下 |

   每題約 0.15–0.2 秒、全在本機;所有版本都沒有錯選,差別只在停下來問人的次數。這是第一個「本機模型在多步驟任務有用」的數據(樣本小,DECISIONS 已列重評條件)。
2. **錄製的正確性靠「乾淨環境重播」,不靠偵測完整。** B3 驗收:示範把狀態寫進 localStorage、草稿漏掉那一步 → 隔離環境重播 2 列 ≠ 示範 4 列 → 不能存;同一草稿在日常 profile 會誤判通過(4 列)。
3. **CDP 實測推翻兩個假設**(spike):離頁事件裡呼叫 binding 0/13 送達(TRAPS `pagehide-binding-call-not-delivered`,confirmed);BFCache 恢復時 hello 早於 frameNavigated、uniqueContextId 與舊文件相同 → 文件世代改由 Python 配發。
4. **既有漏洞**:`<input type=submit>` 被當成輸入框,這類網站的 form_submit 找不到送出鈕(TRAPS `input-type-submit-seen-as-text-field`,6481a9c 已修)。
5. **安全詞表的誤擋**:改狀態詞「追蹤」會擋掉「包裹追蹤」(README 主打用途)→ 改用片語(e581c00)。

## 交付 / Commits

dd4467c..HEAD(36 commits;`kfw/` 10 檔 +4,520 行)。工作包合併點:5eebda6(WP-S spike)、c5b98e0(WP0a CDP 分派)、ab35e9f(WP0b 觀察層)、6988e77(WP0c 安全入口)、
da7097a(WP1 錄製器)、99dde35(WP2 轉草稿與證據)、a2a3613(WP3 steps)、892eee6(WP4 翻頁)、3eb6e08 + b3f2ad2(WP5 pick 與問法)、94dd95c(錄製轉 steps)。
設計:`docs/design/demo-recording.md` v3.2 與 `demo-recording.spike.md`。skill:`references/steps.md`、`references/recording.md`;README 三語「示範一次給它看」(e07c895)。

## 驗證證據

- 測試數:433 單元;190 Chrome 整合(Chrome 154.0.8037.58,隔離 profile、`KFW_TEST_CDP_PORT` 自選埠、暫存 KFW_HOME);另 9 個真站/真 Kev 測試全過(`KFW_REAL_SITE=1 KFW_KEV_TESTS=1`,headed)。
- 真站(headed 隔離 Chrome,每次重大合併後):`thsr-timetable` done 6.1–7.1 秒、5 列;`bot-fx-rates` done 8.4–8.6 秒、19 列;高鐵改寫成 steps 版 done 7.7 秒,rows 與 form_submit 版相同。
- 流程:設計 Codex 複查 4 輪(24 → 12 → 3 → 核准);9 個工作包由 Sonnet 實作,平均每包 8–40 分鐘;一次因 API 用量上限中斷,以 SendMessage 續做未重來。

## 未完 / 交接

- **真人示範驗收**(下一步):重開 Claude Code → 使用者說「我示範給你看」→ 在真實網站(建議先高鐵,再一個 steps 任務)示範 → 量牆鐘、工具呼叫、使用者介入次數、是否一次通過示範一致檢查,對照 Claude 直接寫流程的數字(260929-bot-fx-rates:36 秒、3 次工具呼叫)。
- 錄製器在 pointerdown 時做群組觀察,大型真實頁面的延遲未量(DECISIONS 有重評條件)。
- 換頁會重新載入的分頁型網站、跨 site iframe、Target 崩潰,都沒有專測。
- 子 agent 的 worktree 仍在 `.claude/worktrees/`(已 gitignore),驗收後可清。
