---
updated: 2026-10-07
updated_by: codex session 2026-10-07(展示網站敘事更新;引擎狀態沿用 Claude session)
latest_record: records/261007-showcase-narrative.md
health: yellow   # 引擎:434 單元 + Chrome 整合測試綠、pyright 乾淨(rows_skipped 之後,見最新 commit)。展示網站:新敘事已完成,前端 build、型別、10 項瀏覽器測試通過(見 261007-showcase-narrative)。黃在:(1) 錄製第 2/3 階段驗收暫停,591 找到的兩個轉換缺口與 pick「點不下去」的設計缺口未修(TRAPS);(2) 高鐵 retry 未被真實失敗驗證;(3) 修復廣度待驗證
---
<!-- flightwake STATE — 永遠短、永遠新。新 session 的第一站。 -->
<!-- 規則:只寫「現在」與「下一步」;歷史去 records/,決策去 DECISIONS.md。 -->

# 現在在哪

Kav-FastwebAgent:使用者用說的建立「流程」(內部叫配方,JSON),Claude 寫/修,本機 Chrome + 程式驗證執行(Kev 選配),約 5–9 秒一次。
使用者端說明在 README「怎麼用」;Claude 端規則在 kav-fastweb skill 第 0 節。流程:內建 `thsr-timetable`、`tw-shop-compare`;使用者 `bot-fx-rates`(台銀今天匯率)。
專案敘事(DECISIONS 2026-10-07,取代 09-29 的「本地模型加速」):**Claude/Codex 用對話替不懂程式的人建立、修理固定的網頁流程;之後每次執行由本機確定性程式快速、可驗證地完成,省的是重複執行時的時間與 token**。Kev 是選配(只在 pick 文字比對不唯一且需求是單一屬性時用)。安全與完成判斷留在本地程式不變。
對照組已做:多步驟填表(高鐵)Kav 約 5 倍快;單頁讀表(台銀)沒有優勢。數字與並排示範 GIF(`~/.kav-fastweb/demos/`)見 [[260929-control-experiment-and-demo]]。
**2026-10-07 執行時判斷實驗**([[261007-pick-judgment-experiment]]):流程固定後執行時沒有模型參與的任務,Kav 等於「Claude 寫的爬蟲 + 執行器」;唯一有模型參與的 `pick` 在真實 591 列表上,Kev 零錯選但只放行 4/11 唯一解(兩條件、比較級全停),Claude 全對;Claude 寫的 `rows.pattern` 漏掉 4/30 列是更上游的洞。最划算的組合是「引擎確定性抓文字 + Claude 判斷」。每次執行回傳 `kev`(Kev 呼叫次數、token、耗時加總);重開後經 MCP 確認生效(比價 Switch 2 `done` 7.8 秒、Kev 31 次 / 7,987+2,811 token,`~/.kav-fastweb/runs/260929-133729`)。

# 進行中(未完成勿刪)

- [ ] **展示網站(Codex)**：Astro 首版與 10/07 新敘事已完成本機前端驗證，含錄製示意、抓取／驗證／Claude 判斷原理圖與 591 實驗；待使用者成品回饋、公開入口與部署。接續見 [CONTEXT](records/261002-showcase-build-CONTEXT.md)。Impeccable 安裝產物仍未提交。

- [x] **專案方向**:2026-10-07 使用者決定——敘事改為「引擎抓資料 + Claude 判斷」,Kev 降為選配(DECISIONS 同日;README 三語已改)。漏列可見已做:結果帶 `rows_skipped`(同一列表不符 pattern 的列數),done 附 `note`、失敗併入 hint、pick 的候選也帶;skill 的 recipe-rules 加「pattern 只鎖錨」原則
- [x] 展示網站(`website/`,codex 線)已依 DECISIONS 2026-10-07 更新新敘事與實驗範圍;驗證見 [record](records/261007-showcase-narrative.md)
- [ ] 可選:改 pick 問法處理兩條件/比較級後用 `evals/pick-591/` 18 題重跑(留 Kev 的前提下才值得)
- [ ] **錄製功能(使用者示範一次 → 流程)**:程式三階段完成([[260929-recording-build]]);第 1 階段真人驗收通過(高鐵,[[260930-thsr-demo-acceptance]]),`thsr-by-demo` 已存、via_widget 誤報已修(8fd2764)。**第 2/3 階段驗收暫停**(DECISIONS 2026-10-07);591 示範找到的兩個轉換缺口在 TRAPS(`recording-drops-non-button-filter-clicks-silently`、`mark-table-skips-single-child-card-wrappers`),方向定了再決定修不修
- [ ] **公開 repo 前**:2026-10-07 已做——MIT LICENSE、示範 GIF 從檔案樹拿掉(使用者決定先拿掉;53b2f78 的歷史裡仍有,所以要從**乾淨的 orphan 分支**推,不帶歷史)、內建流程驗證紀錄的本機路徑改成 `~/`、`evals/pick-591` 的電話遮蔽。還沒:GitHub 上建 `kaiwutech-TW/Kav-FastwebAgent` 與設 remote;決定其他 session 的未 commit 修改(skills/hooks)要不要進去;「任何資料夾都能用」安裝、Windows、Codex 都未實測
- [ ] **高鐵第一趟失敗一次**→ TRAPS `form-submit-fills-half-initialized-page`(suspected)。3 趟新程式都沒觸發 `retry`;下次真的出現 `retry` 時回頭更新
- [ ] 組合包判斷偏弱 — TRAPS `price-compare-false-matches-need-price-guard`(比價已降為次要,DECISIONS)
- [ ] 13 筆 `uncertain` 標註待使用者複核(`evals/price/labels-260929.jsonl`)
- [ ] 台灣原生繁中評測題組,使用者說先暫停

# 下一步入口

- 展示網站工作線：先讀 [CONTEXT](records/261002-showcase-build-CONTEXT.md)，看本機成品後依使用者回饋接續；下列引擎工作由另一 Claude session 處理。

0. 展示網站新敘事已完成;引擎線決定 pick「點不下去」(TRAPS `pick-needs-fixed-button-text-card-lists-have-none`:click 可省略 + 接新分頁)要不要修——這是卡片列表網站能不能端到端跑完的關鍵。錄製第 2/3 階段驗收暫停中
1. 對照組補更多多步驟任務(翻頁、多欄位表單),避免只靠高鐵一例;盲測前留意釘選記憶會洩題
2. 更多修復盲測:換網站、換壞法(送出鈕改名+多一步、需要翻頁);破壞測試結束立刻還原並記時間窗(見 260929-control-experiment-and-demo 發現 2)
3. BigGo 行情參考配方(蝦皮價格只當參考、標未驗證;卡片邊界見 TRAPS `biggo-card-ancestor-spans-offers`)
4. 「回報缺少的能力」:使用者需求碰到流程格式表達不了的東西時,如何記錄與回饋給引擎(台銀 `{today}` 是第一例)

# 常備事實(這個 repo 的保命知識)

- 啟動 Kev:`cd vendor/kev && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009`(`vendor/` 不進 git,來源見 README;高鐵、台銀流程不需要 Kev,比價需要)
- Kav 的 Chrome 用 `:9333` 和專屬 profile `~/.kav-fastweb/chrome-profile`(沒開會自動啟動);截圖、試跑紀錄、使用者流程、回收區都在 `~/.kav-fastweb/`,不進 git
- 使用者流程(`~/.kav-fastweb/recipes/`)會蓋過同名內建流程(`recipes/`)
- 改了 kfw 就要重開 Claude Code;新增引擎欄位要同步更新 `kfw/recipes.py` 的 `_SCHEMA`,否則會被白名單擋下
- 開著 Cloudflare WARP / VPN 時酷澎會拒絕存取;蝦皮擋 CDP 控制(登入也沒用,不做);淘寶未測
- 測試:`uv run pytest -q`(testpaths=tests,避開 vendor/);型別:`uvx pyright`;真實網站端到端:`tests/mcp_e2e.py`、`tests/mcp_recipe_flow.py`
- 盲測另一個 session:`orca terminal create --worktree active --command claude`,再 `terminal send` / `wait --for tui-idle` / `read`
- Claude in Chrome 帳號可能連著多個瀏覽器;新 session 要錄影或讓使用者看得到,開場先 `select_browser` 指定(見 260929-control-experiment-and-demo 發現 3)
- MCP 工具不要回傳 list(空清單會變成沒有 content)— TRAPS `mcp-empty-list-result-has-no-content`
