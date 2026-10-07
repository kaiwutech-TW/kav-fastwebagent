---
record_id: 261007-pick-judgment-experiment
session: claude-code session 2026-10-07(存 thsr-by-demo、修 via_widget 誤報、591 錄製驗收中途轉向、執行時判斷三組對照實驗)
date: 2026-10-07
repos: [Kav-test]
tests: 433 passed + 191 Chrome 整合 = 624 passed / pyright 0 errors(8fd2764;之後只動文件與 evals/)
prod_changes: none(thsr-by-demo 存在 ~/.kav-fastweb/recipes/,不在 git;Kev 以 jaredpalmer/kev-4b 本機啟動)
---
<!-- flightwake record — 飛行紀錄。 -->

# 執行時的判斷由誰做:Kev 在真實 591 列表上「不錯選但很保守」,Claude 全對但慢且貴;Claude 寫的 pattern 悄悄漏掉 4/30 列才是更大的洞

**TL;DR**:開場先收掉上次的尾巴(存 `thsr-by-demo`、修示範一致失敗時誤咎 via_widget 的 bug)。接著請使用者在 591 租屋示範第 2 階段錄製,轉出的草稿漏掉「雅房」篩選、標記的表格只抓到卡片裡的三行小字——兩個都是轉換器的通用缺口。
使用者在此指出核心問題:錄製後由 Claude 驗證修成固定抓取規則,執行時沒有任何判斷是模型做的,Kav 就只是「Claude 寫的爬蟲加執行器」,拿掉 Kev 也沒差;專案要測的是本地模型 Jev/Kev 在執行當下有沒有實際貢獻。
於是暫停錄製驗收(DECISIONS 2026-10-07),改做三組對照:同一份 591 北投區雅房列表、18 題口語需求(唯一解/多解該停/無解該停/兩條件/比較/字面),
A = Kav 正式 pick 路徑 + Kev、B = 同路徑無模型、C = 全新 Claude session(C1 讀同一份文字、C2 用 Claude in Chrome 到真實頁面)。
結果:Kev 零錯選、該停的全停,但唯一解只放行 4/11;Claude 18/18 對。pattern 漏列、pick 在卡片列表點不下去,是比 Kev 判斷力更先碰到的牆。

## 關鍵發現(重要性排序)

1. **Kev(4B,本機)在真實列表上「不會錯、但答得少」。** 30 列、18 題,正式 `steps._select_row` 路徑(文字比對 → 每列一題是非題 → 最高 ≥ 0.8 且贏第二名 ≥ 0.3):

   | 組別 | 唯一解 13 題 | 該停 5 題 | 錯選 | 每題耗時 | 每題成本 |
   |---|---|---|---|---|---|
   | A Kav+Kev | 選對 6(Kev 4 + 字面比對 2)、停下 7 | 5/5 正確停下 | **0** | Kev 約 1.1 秒(26 列熱跑 0.78 秒) | 約 5.1k 本機 token,免費 |
   | B Kav 無模型 | 選對 2(只有字面比對那兩題)、其餘停下等人 | 5/5 | 0 | 0 | 0 |
   | C1 Claude 讀同一份文字(26 列版 16 題) | 11/11 | 5/5 | 0 | 整批 24.6 秒(約 1.5 秒/題) | 整批輸入約 35.5 萬 token(14.1 萬寫快取 + 21.4 萬讀快取)、輸出 4.1k |
   | C2 Claude in Chrome 到真實頁面(3 題) | 3/3 | — | 0 | 43 / 162 / 21 秒 | 每題輸入(含快取累計)91 萬 / 61 萬 / 45 萬 token |

   Kev 停下的 7 題裡,最高分那列有 4 題其實是對的(Q03 電梯+廚房、Q06 短租+陽台、Q04 最便宜、Q11 知行路),被差距門檻擋下;3 題最高分是錯的(Q08 限男生、Q09 押一付一+陽台、Q13 文林北路+可開伙+最便宜)但機率不高也停了。
   模式很清楚:**單一屬性**(頂樓加蓋、地下室、一樓、2,900)Kev 選得準;**兩條件並列**或**比較級**(最便宜)時,只符合一半的列也拿到 0.85–0.97,差距就不夠——每列獨立問是非題本來就表達不了「同時」與「比別列」。兩次重跑結果完全一致(確定性)。
   26 列版(16 題)同樣 0 錯選:選對 8、該停 4 全停、保守停下 4。
2. **Claude 寫的 `rows.pattern` 悄悄漏掉 4/30 列,而且把 Q01 的正確答案從「c25」變成「兩筆、該停」。** 第一次抓快照用 `雅房\d+坪\d+F/\d+F`,3.5 坪、4.5 坪、2.7 坪(小數)和「頂樓加蓋/5F」「B1/5F」都不中;漏掉的恰好有一筆可養寵物。C2 看的是全部 30 列,才發現對不上。
   這是比 Kev 判斷力更上游的洞:確定性前置過濾一旦寫錯,**Kev 根本看不到那幾列,也不會報錯**。登 TRAPS `rows-pattern-silently-narrows-pick-candidates`。
3. **591 這種卡片列表,正式的 `pick` 點不下去。** 每張卡片唯一可點的是標題連結,文字每列不同、而且 `target=_blank` 開新分頁;`pick.click` 要求列內有固定文字的按鈕、點了要在同一分頁換頁。所以本實驗只量到「選哪一列」,沒有端到端 run_recipe。登 TRAPS `pick-needs-fixed-button-text-card-lists-have-none`。
4. **框架真正可用的點,比原本敘事窄也比原本敘事具體**:
   - 確定性的抓取(載入 → 找列表 → 取列文字)快而穩:`pick_groups` 31 ms;Claude in Chrome 做同一件事 21–162 秒、45–91 萬 token,而且擴充功能三次逾時、一次斷線。
   - 判斷這一段,**最划算的組合是「引擎抓文字 + Claude 判斷」**(C1:每題 1.5 秒、2 萬多 token),不是 Kev。Kev 的位置只剩:離線/隱私/零雲端成本,而且需求是單一屬性時。
   - 用戶指出的前提成立:流程固定後執行時沒有模型參與的任務(高鐵、台銀),Kav 等於 Claude 寫的爬蟲加執行器;本實驗證實有模型參與的那一段,本地模型的貢獻是「免費但只能答簡單題」。方向由使用者決定(見 STATE)。
5. 收尾上次的黃燈:`thsr-by-demo` 從上個 session 的對話紀錄還原配方(hash `ad9ebdba58c7e613` 與試跑證據一致)後存檔;`_unsupported_after_failed_demo` 改為只在 `match: false` 時歸咎 via_widget(8fd2764,補回歸測試)。
6. 591 錄製示範找到兩個轉換器缺口(未修,已登 TRAPS `recording-drops-non-button-filter-clicks-silently`、`mark-table-skips-single-child-card-wrappers`)。另:C2 的全新 session 開場會問「5 個 Chrome 要用哪個」,和 260929 發現 3 相同,選瀏覽器那回合不計時。

## 交付 / Commits

8fd2764..(本 record):修誤報 + 文件(STATE/TRAPS/DECISIONS)+ `evals/pick-591/`(列表快照已把屋主/仲介姓名改成○○、18 題與標準答案、A/B 兩組原始結果含每列機率、跑法腳本)。C 組證據在各 session 的對話紀錄(見下)。

## 驗證證據

- A/B:`evals/pick-591/results_A30.json`、`results_B30.json`(26 列版 `results_A.json`、`results_B.json`);Kev 用量由 `Judge.usage()` 累計(30 列版 32 次呼叫、輸入 163,908、輸出 22,670 token、模型自報 34.5 秒)。
- C1:對話紀錄 `abba1876…`(1 次工具呼叫、24.6 秒、16 題表格全對)。C2:對話紀錄見 `~/.claude/projects/` 中含「可以養寵物的」的最新一份(第 1 回合是選瀏覽器,不計;第 2–4 回合為三題);數字由 `evals/pick-591/session_stats.py` 從時間戳與 usage 算出。
- 快照時間與即時頁面:三次抓取 26 列文字只有「N 分鐘內更新」變動;30 列版多出的 4 列見 `rows30.json` c11、c12、c13、c17。
- 存檔:`thsr-by-demo` 通過 save 的五項證據條款(示範一致 `b25bb21ed2bb`、換參數 `f9f25f3b702c`)。測試 624 passed、pyright 0(8fd2764)。

## 未完 / 交接

- **方向由使用者決定**:本地模型只在「單一屬性、離線/免費」有位置;若要留 Kev,下一步是改 pick 的問法讓它處理兩條件(例:先拆條件各問一次再取交集,或把候選清單整份給它比較)並重跑這 18 題;若不留,敘事改為「確定性引擎抓資料 + Claude 判斷」。
- 錄製第 2/3 階段驗收暫停;兩個轉換缺口與 pattern 漏列、pick 點不下去的設計缺口都在 TRAPS,等方向定了再決定修不修。
- 高鐵 `retry` 仍未被真實失敗驗證(不變)。
