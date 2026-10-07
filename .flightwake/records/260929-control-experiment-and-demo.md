---
record_id: 260929-control-experiment-and-demo
session: claude-code session 2026-09-29(第四個 session:驗證新引擎、對照組實驗、示範 GIF)
date: 2026-09-29
repos: [Kav-test]
tests: 103 passed / pyright 0 errors
prod_changes: none(使用者配方、示範影片都在 ~/.kav-fastweb/,不在 git)
---
<!-- flightwake record — 飛行紀錄。 -->

# 對照組實驗:Kav 在多步驟填表快約 5 倍,但抓對資料不等於答對;補上欄名,錄了並排示範

**TL;DR**:先驗證 189e193 在重開後真的生效(黃燈第 1 項解除)。接著做 STATE 列了很久的對照組:同一句話分別交給「Kav 配方」和「Claude in Chrome 一步步操作」,各開全新 Claude Code session 量測。高鐵(填表+多步)Kav 快約 5 倍、輸入 token 少約 4 倍;台銀(單頁讀表)兩邊一樣快。實驗中 Kav 組**答錯**了抵達時間——引擎資料正確、回答的模型讀錯沒有欄名的欄——因此加了 `rows.columns`,重跑答對。最後錄了兩邊並排的 4 倍速 GIF。

## 關鍵發現(重要性排序)

1. **速度優勢只在多步驟任務上成立。** 全新 session、同一句使用者的話、答案都用官網截圖核對:

   | 任務 | 方式 | 牆鐘 | 工具呼叫 | 輸出 token | 輸入 token(含快取) | 人介入 | 答對 |
   |---|---|---|---|---|---|---|---|
   | 台銀今天美金/日圓現金賣出 | A Kav | 19 秒 | 3 | 775 | 16.5 萬 | 0 | ✅ |
   | 〃 | B Chrome | 20 秒 | 5 | 1,065 | 25.7 萬 | 0 | ✅ |
   | 高鐵 10/12 15:00 後台中→台北 | A Kav(修前) | 22 秒 | 4 | 1,183 | 21.8 萬 | 0 | ❌ 抵達時間 |
   | 〃 | A Kav(修後,兩次) | 20 / 23 秒 | 4 / 5 | 1,175 / 1,345 | 17.6 / 26.6 萬 | 0 | ✅ |
   | 〃 | B Chrome(四次) | 118 / 151 / 98 / 98 秒 | 29 / 33 / 31 / 18 | 5,569 / 10,170 / 5,503 / 5,383 | 88.5 / 128.1 / 93.2 / 77.0 萬 | 0 | ✅ |

   高鐵:A 約 22 秒 vs B 約 116 秒(約 5 倍;151 秒那次中途誤點「較晚班次」把表單清空、重填);輸入 token 約 4 倍差。台銀只要開一頁讀表,Chrome 也 20 秒,**Kav 沒有優勢**——故事要講「多步驟、重複的網頁動作」,不能說所有網頁任務都快。
   附帶成本沒算進上表:建立配方是一次性成本(台銀從零到可用約 36 秒、3 次工具呼叫,見 [[260929-bot-fx-rates]];修一次壞掉的配方約 1.2–2.6 萬輸出 token,見 [[260929-repair-and-user-flow]])。這兩題 Kav 端**沒有呼叫 Kev**(高鐵四個欄位都完全比對成功、台銀只讀頁),Kav 端的成本只有本機 Chrome + 程式約 6–9 秒。
   比較範圍不完全相等:B 常自己翻頁列出更多班次(最多列到末班車),A 列出 15:00 起的 5 班。
2. **程式驗證證明「頁面上有這些字」,證明不了模型怎麼讀。** A 組修前把停靠站列表裡的台北**發車**時間 16:02 當成抵達(官網抵達 15:59),還自己編「車程欄是到南港」來圓。登 TRAPS `unlabeled-row-columns-misread-by-answering-model`(confirmed)。解法見 DECISIONS:配方宣告 `rows.columns`,引擎回傳 `{欄名: 值}`,格數對不上就 `result_not_proven`。高鐵、台銀配方已加;新開 session 重跑答對。**沒寫 columns 的配方仍有這個風險。**
3. **Claude Code 帳號同時連著兩個 Chrome 擴充功能實例時,新 session 可能操作到看不見的那個。** 前兩次錄 B 組,答案都對,但螢幕上的 Chrome 從頭到尾沒動。使用者用 `/chrome` 看到 Browser 1 / Browser 2 兩個(都標在這台 Mac),本 session 用 Browser 1 開 google.com 才確認出現在眼前的視窗。之後 B 組開場先 `select_browser` 指定 Browser 1(不計時),畫面才錄得到。影響量測嗎:B 組答案與耗時在三次之間一致,看不見只影響錄影。
4. **盲測受釘選記憶污染。** B 組 session 多次主動說「可以拿來跟 kfw 配方比速度」、甚至自己用 `date` 計時——釘選記憶裡寫著實驗要量化,新 session 讀得到。對數字影響不大(B 組多了 1 次 shell 呼叫),但它不是乾淨的盲測。
5. Kav 引擎在背景分頁操作(`background=True`),直接錄只拍到空白分頁;示範時用外部小程式把新分頁切到前景(不改引擎)。

## 交付 / Commits

8607c5a(rows.columns)+ 本 record。實驗與錄影腳本在 session 暫存區,未進 repo(一次性)。

## 驗證證據

- 189e193 重開後:`list_recipes` 可用;台銀 `done` 8.6 秒(`~/.kav-fastweb/runs/260929-123427-f748`);日期設 1999/01/01 → `needs_help / result_not_proven`(`-123446-f617`);拼錯 `expect_txt` → 直接拒絕。
- rows.columns:高鐵 dry_run `f2f3f30322ce`、台銀 `dc67e743feb2` 通過並存檔;少一個欄名 → `needs_help`,hint 指出 5 列格數對不上。103 passed、pyright 0。
- 修後新 session 答 0648 抵達 15:59,與官網截圖 `runs/260929-123647-0951/result.jpg` 一致。
- 各 session 的對話紀錄在 `~/.claude/projects/-Users-kaiwu-orca-projects-Kav-test/`:A 台銀 `88359064…`、B 台銀 `91ba597c…`、A 高鐵修前 `f76904a6…`、B 高鐵 `e76129cd…`、A 修後 `d6a750aa…`(A2)/`62040e80…`(錄影)、B 錄影 `3ae93f27…`/`acedfdc3…`/`b29a1fad…`(另有一次錄影中斷、沒有答案,不計)。數字由 jsonl 的時間戳與 usage 算出(從使用者那句話到最後一則回覆;B 錄影那次從正式題目起算,不含指定瀏覽器)。
- 示範影片:`~/.kav-fastweb/demos/kav-vs-chrome-thsr.gif`(1.8MB,4 倍速,A 25 秒 vs B 100 秒)與 `.mp4`。錄影從外部 `screencapture` 錄兩個螢幕,不用 gif_creator(會讓 B 多出工具呼叫)。已逐格檢查沒有私人畫面;B 組終端機開頭可見指定瀏覽器的準備指令。

## 未完 / 交接

- 本 session 的 MCP server 是舊程式,會拒絕加了 columns 的兩份配方 → **重開 Claude Code**。
- Kev 呼叫沒有記 token 與耗時(`kfw/judge.py`),用到 Kev 的流程(比價)量不到本機模型成本。
- 其他配方(比價)還沒加 columns。其餘見 STATE。
