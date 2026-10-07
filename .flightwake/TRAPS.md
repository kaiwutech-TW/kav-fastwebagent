<!-- flightwake TRAPS — 坑 registry。非顯而易見、會再咬人的事實。 -->
<!-- 條目採 OKF 式慣例:frontmatter 區塊 + 內文;可用 [[名稱]] 互連。新的加最上面。 -->
<!-- 時效:條目過時(功能合併/重構後不再成立)不刪 — status 改 superseded 並指向取代者;讀的人只信 active。 -->
<!-- 證據強度:confidence 標的是「根因」的把握度,不是症狀。**不對稱門檻**——拿這條論證
     「這樣會壞」probable 就夠(錯了只是多做防護);論證「這樣是安全的」必須 confirmed
     (錯了直接打到 prod 和使用者)。 -->

# 坑 Registry

---
name: playwright-text-matcher-skips-noscript
type: gotcha
status: active
confidence: confirmed
tags: [frontend, playwright, no-javascript, testing]
discovered: 2026-10-02
---

**症狀**:關閉 JavaScript 的 Chrome 中，`getByText` 找不到 noscript 說明；`expect(locator('noscript')).toContainText(...)` 回報 `Received string: ""`，但 `locator('noscript').textContent()` 讀得到完整文字。
**根因**:Playwright 1.63.0 的文字比對 helper 明確略過 SCRIPT、NOSCRIPT、STYLE 與 head 後代；不是 Astro 漏掉 noscript 內容。
**解法**:無 JavaScript 驗證改讀 DOM `textContent()`，另驗證真正的靜態表格可見；不要只用 getByText 或 toContainText 判定 noscript 是否輸出。
**佐證**:`website/node_modules/playwright-core/lib/coreBundle.js`（1.63.0，line 19837 內嵌的文字比對 helper）；`website/tests/site.spec.ts` 的無 JavaScript 測試桌面／手機兩次都從失敗轉為通過。安裝版本由 website/package-lock.json 固定。

---
name: unlabeled-row-columns-misread-by-answering-model
type: trap
status: active
confidence: confirmed
tags: [kfw, rows, thsr, answer-quality]
discovered: 2026-09-29
---

**症狀**:對照組實驗 A 組(kav-fastweb)回答「10/12 15:00 後台中→台北」時,把 0648 的台北抵達說成 16:02(官網抵達欄 15:59),5 班全部晚 3 分鐘左右,還自己編出「車程欄是到終點南港的時間」來解釋差異。run_recipe 是 `done`,引擎抓到的資料沒有錯。
**根因**:(confirmed,官網截圖對過)高鐵結果列展開後的第 6 欄是停靠站列表,列的是各站**發車**時間(台北站停 3 分鐘)。rows 只回傳沒有欄名的字串陣列,回答的模型看到「台北 16:02」就當成抵達時間。程式驗證只能證明「頁面上有這些字」,證明不了模型怎麼解讀它們。
**解法**:配方可寫 `rows.columns`(一格一個欄名,null 丟掉),引擎回傳 `{欄名: 值}`;某列格數對不上就 `result_not_proven`,不亂貼欄名。高鐵、台銀已加上(dry_run `f2f3f30322ce`、`dc67e743feb2`;少一個欄名的反向測試回 needs_help)。**配方沒寫 columns 的仍有這個風險。**
**佐證**:A 組 session `f76904a6-5ab5-49bd-aa3f-8f6d5bc803a2`,`~/.kav-fastweb/runs/260929-123647-0951/result.jpg`;B 組(Chrome)session `e76129cd-…` 答 15:59,正確。

---
name: thsr-result-row-text-format-drift
type: trap
status: superseded  # 2026-09-29:不是網站行為,是修復測試刻意弄壞配方造成的,見下方說明
confidence: suspected
tags: [kfw, form_submit, thsr, recipe, rows-pattern]
discovered: 2026-09-29
---

**[superseded — 假警報]** 12:06–12:11 之間是另一個 session 在做「修復流程」盲測:刻意把使用者配方的 rows.pattern 改成不存在的格式 `車次… →…`,網站本身沒變。這條的觀察(列文字格式)正確,但「網站格式會漂移」這個推論不成立;配方已還原成原本的 pattern。教訓見 record。
**症狀**:`thsr-timetable`(status verified,12:06 用台中→台北 2026/10/12 驗證過)在 12:11 跑新竹→台南 2026/10/20 09:00,回傳 `needs_help / result_not_proven`,`hint: 結果沒有被程式證明:rows=0 缺少文字=[]`,等了 12s。四個欄位都 `ok`,送出也有 `effect: request`,**截圖裡車次表卻完整顯示**(09:22 0615 …)。這跟 [[form-submit-fills-half-initialized-page]] 不一樣:那次截圖停在首頁,這次結果已經在頁面上。
用寬鬆 pattern 試跑,抓到的列文字是 `09:22 01:10 10:32 0615 9-12 南港 08:35 台北 08:46 …`(依序是出發、行車時間、抵達、車次、自由座、停靠站),**沒有「車次」字樣也沒有「→」**,舊 pattern `車次\s?\d{3,4} \d{2}:\d{2}→\d{2}:\d{2}` 一列都對不到。
**根因**:(suspected)高鐵結果列的 innerText 格式跟配方驗證時不一樣。還沒排除:(a) 網站 A/B 或改版,送出不同的標記;(b) 同一份標記在不同狀態(視窗寬度、RWD 版型)下 innerText 不同;(c) 12:06 那次其實是別的節點群組命中了舊 pattern。目前沒有 12:06 那次的 rows 原文可以比對。
**繞法**:rows.pattern 改成 `^\d{2}:\d{2} \d{2}:\d{2} \d{2}:\d{2} \d{3,4} |車次\s?\d{3,4} \d{2}:\d{2}→\d{2}:\d{2}`(新格式在前,舊格式保留當備選)。dry_run `b579d88ddd02`(台中→台北 10/12 15:00)通過,5 列,和截圖逐列對過,已經 save_recipe。之後用 run_recipe 跑新竹→台南也 `done`,5 列。
**佐證**:失敗 `~/.kav-fastweb/runs/260929-121104-ddb9/result.jpg`;診斷 dry_run `907cf5eaa71d`(`runs/260929-121217-0ac4`);修正後 `runs/260929-121241-b191`、`runs/260929-121300-2b96`。

---
name: mcp-empty-list-result-has-no-content
type: gotcha
status: active
confidence: confirmed
tags: [mcp, python-sdk]
discovered: 2026-09-29
---

**症狀**:MCP 工具(mcp 2.2.0 `MCPServer`)回傳 `[]` 時,client 收到的 `CallToolResult.content` 是空的,`res.content[0].text` 會丟出 `IndexError: list index out of range`。
**根因**:空清單被序列化成零個 content block,不是一個 `"[]"` 文字 block。
**解法**:工具一律回傳 dict,例如 `find_recipe` 回 `{"recipes": [...]}`,不要直接回傳 list。
**佐證**:`tests/mcp_recipe_flow.py` 第一次執行時重現,改成 dict 後正常(`kfw/mcp_server.py find_recipe`)。

---
name: price-compare-false-matches-need-price-guard
type: trap
status: active
confidence: probable
tags: [price-compare, kev, keyword-stuffing, held-out]
discovered: 2026-09-29
---

**症狀**:在沒看過的商品 PS5 Pro 上測試(規格事先寫好:must `ps5pro|playstation5pro` + `主機`),最低價是錯的:
- $399「PS5 Pro主機 橫放支架」:配件,Kev 判斷信心 0.55 就放行了。
- $17,989「PS5 Slim主機 … PS5 PRO 主機」:賣家在標題裡灌關鍵字,字串比對擋不下來。
- $59,990「PS5 Pro + PlayStation Portal 組合」:組合包,Kev 沒認出來。
**根因**:標題可以灌關鍵字,字串比對只能保證「標題裡有這些字」;Kev 在信心邊緣的配件和組合判斷不穩。只測過一個商品,所以標 probable。
**繞法**:用程式做價格合理性檢查(`kfw/compare.py split_suspicious`):離中位數 < 0.5× 或 > 2× 就移出排序,改列在 suspicious 交給 Claude 複核。這能擋掉 $399 和 $17,989,但**擋不住 $59,990**(只有中位數的 1.35×)。**2026-09-29 更新**:商品頁驗證已經做好(`kfw/verify.py`,讀四站都有的 JSON-LD / product meta,由程式檢查價格、庫存、全新與否、名稱)。PS5 Pro 重跑:$27,478 那筆在商品頁顯示缺貨,被移出;best 變成 $44,580(momo 和 Yahoo 同價,驗證通過)。**組合包仍然擋不住**:「PS5 Pro + Slim 光碟機」通過了驗證,只是剛好不是 best。
**佐證**:`tests/mcp_e2e.py` PS5 Pro 那次執行;`tests/test_core.py::test_price_guard_flags_accessory_and_stuffed_titles`。

---
name: kev-weak-at-literal-model-matching
type: constraint
status: active
confidence: probable
tags: [kev, price-compare, product-matching]
discovered: 2026-09-29
---

**症狀**:判斷電商商品是不是目標型號時,Kev-4B 會把 Switch Lite/OLED 當成 Switch 2、把 AirPods 4/5 當成 AirPods Pro 3、把 iPhone 17e 當成 iPhone 17、把 WF-1000XM6 當成 WH-1000XM6,就算題目明確列出「17e、Lite、OLED 不同」也一樣。把型號比對改用程式比對字串(planner 給 must / must_not)之後,這類錯誤歸零,整體準確率 0.797 → 0.949。
**根因(推測)**:型號比對是逐字元的精確比較,不是 Kev 擅長的語意分類;它從預訓練帶來的 Switch 世代知識也不夠。只在一份 217 筆的資料上觀察到,沒有對照組,所以標 probable。
**繞法**:型號和容量這類精確條件交給程式(規格由 planner 提供),Kev 只負責語意判斷(配件、組合、福利品)。遊戲片和主機組合還是會混淆(Switch 2 有 11 筆錯誤)。
**佐證**:`evals/price/README.md`、`results/price/judge-kev4b-*-260929.jsonl`。

---
name: shopee-taobao-block-anonymous-automation
type: constraint
status: active
confidence: confirmed  # 2026-09-29 升級:僅限「蝦皮擋程式控制的 Chrome,登入也沒用」這一句;淘寶部分仍 probable
tags: [ecommerce, shopee, taobao, anti-bot, login]
discovered: 2026-09-29
---

**症狀**:在沒有登入的獨立 Chrome(CDP 控制)裡搜尋「AirPods Pro」:
- **蝦皮**:先跳語言選擇,接著被導到 `shopee.tw/verify/traffic/error`,整頁只有 160 字。
- **淘寶**:強制跳出手機號碼登入框,結果區只有灰色骨架,整頁只有 115 字。
- **酷澎 Coupang(tw.coupang.com)**:回「您沒有權限存取此頁面 / Access Denied」,頁面顯示 Client IP 104.28.198.10(屬於 Cloudflare 網段,可能是 WARP 或 Private Relay)。**2026-09-29 已驗證**:關掉 WARP、改走中華電信 IP 之後,同樣的搜尋就正常了(有結果,抓到 212 個價格)→ 是 WARP 的 IP 被擋,不是偵測到自動化。**開著 Cloudflare WARP 時不要跑電商評測。**
- **PChome、momo、Yahoo 購物**:不登入就能搜尋並看到價格。momo 的「$」和數字是分開的元素,innerText 會被拆成兩行,單一 regex 抓不到價格。
**根因**:淘寶的搜尋必須登入。蝦皮在關掉 WARP 後仍然被導到 verify/traffic/error,但頁面文字已經改成「看起來您尚未登入。請登入以繼續」。我們的 Chrome 顯示 navigator.webdriver=false,首頁可以正常開,所以比較像是新的、未登入的 session 不能搜尋,而不是被認出是自動化(只測一次,仍是推測)。每站只測了一次,所以標 probable。
**更正(2026-09-29 11:5x)**:使用者在 Kav 專屬 Chrome 手動登入蝦皮後,`inspect_page` 開 `shopee.tw/search?keyword=AirPods%20Pro%203` 仍被導到 `verify/traffic/error?...&is_logged_in=true`(blocked_reason=verification);當時 WARP off、台灣 IP(111.248.x)。→「沒登入所以不能搜尋」**不成立**,登入不足以解鎖;較可能是偵測到 CDP 自動化或帳號/session 被風控,尚未分辨(只測 1 次,刻意不重試以免加重帳號風控)。蝦皮的淘寶那半部未重測。
對照組(同一個 Kav Chrome、同設定檔、同帳號、同 IP):使用者**手動**在首頁搜尋框輸入 `airpods pro 3` → 正常顯示商品列表,網址與我們程式開的同形(`/search?keyword=...`)。→ 網址格式本身沒被擋,差別在「怎麼到這頁」(程式直接導航/CDP 附著分頁)或使用者手動操作時順便解除了驗證狀態,尚待一次程式重試區分。
程式重試(使用者已完成登入的簡訊二段驗證、手動搜尋成功之後,經同意):`inspect_page` 同網址**仍被擋**(verify/traffic/error, is_logged_in=true)。→ 不是 session 被標記後可手動解除;是程式這條路被認出。剩下待分:是 CDP 附著/新分頁被偵測,還是「直接整頁載入搜尋網址」本身(使用者手動是在首頁搜尋框走站內導航)。已停止程式重試。
最後對照:使用者在同一個 Kav Chrome 開新分頁、**手動把同一串搜尋網址貼進網址列** → 正常看得到商品。→ 整頁直接載入不是原因;同設定檔/帳號/IP 下,手動 2 次都過、程式(CDP)2 次都被擋 → **蝦皮偵測的是 CDP 控制本身,登入解不開**。細部機制(新分頁由 CDP 建立、Runtime 附著等)未分辨,也不打算分辨——再往下就是在繞過偵測。**結論:蝦皮不做自動化,不加進 SITES**(DECISIONS 2026-09-29)。
**繞法**:v1 評測只用 PChome、momo、Yahoo。蝦皮和淘寶只能在使用者自己登入的專用 profile 下低頻使用,碰到驗證一律回傳 needs_help 交給使用者處理,不破解。另外兩站的條款都禁止自動化存取,帳號有被停權的風險,要由使用者自己決定。
**佐證**:`results/web/probe-{pchome,momo,yahoo,shopee,taobao,coupang}.jpg`。

---
name: web-agent-false-done-before-async-results
type: trap
status: active
confidence: confirmed
tags: [web-agent, thsrc, async, done-check, jev-ultrafast]
discovered: 2026-09-29
---

**症狀**:thsrc.com.tw 時刻表查詢按下「查詢」後,Kev 的 done 題(noul)在約 3.3 s 回傳 DONE,但當下截圖(`results/web/thsr-run11-at-done.jpg`)只看得到公告和時刻表下載,沒有任何車次。約 5 s 後車次表和票價才出現(`-after-5s.jpg`,2026/10/05 08:00,第一班 1305 次)。前面回報的「3/3 成功、3.3 秒」是誤判。
**根因**:結果是在頁面載入後才非同步渲染的;頁面文字停止變動 300 ms 並不代表資料已經回來。再加上 jev-ultrafast 的 snapshot 只送畫面內的文字,模型看不到尚未出現的內容,只能靠「時刻表」這類字眼去猜。兩次觀察一致(run2 用 5 s 重新載入看到結果、run11 當下截圖看不到),而且症狀可以重現。
**解法**:完成與否不能交給模型單獨判斷。必須用程式條件確認(網路請求靜止、目標區塊出現,例如結果表至少有一列、日期字串吻合),模型只負責「內容對不對」。在程式確認資料存在之前,不准回報完成。
**佐證**:`results/web/thsr-run11*.{json,jpg}`、`bench/web_live.py`。

---
name: laya-cannot-drive-web-agent-policy
type: constraint
status: active
confidence: probable
tags: [laya, web-agent, jev-ultrafast, latency, mlx]
discovered: 2026-09-29
---

**症狀**:在 `bench/web_probe.py` 的高鐵模擬頁上(6 步),Laya 不管用 jev-ultrafast 原版 prompt 或精簡版都是 **0/6**,幾乎每步都回 DONE,信心值 0.03–0.14。速度:laya-apple(MLX)原版每步 42 ms、精簡版每步 20 ms;upstream laya-serve(PyTorch MPS)每步 160 ms / 70–250 ms。兩個 runtime 的答案完全一致。
**根因(推測)**:原版 prompt 超過 Laya 的 token 上限(usage 顯示 4096,輸入被截斷),每題的選項預算也只有 192–256 tokens;但換成約 1.3k tokens 的精簡版還是 0/6,所以主因是 322M/421M 的 encoder 做不來「目標 + 頁面狀態 → 下一步操作」這種多步推理。只測過一個合成頁面。
**繞法**:Laya 只適合拿來做短文字、選項少的單步判斷(分類、守門員),不要拿來當 web agent 的決策層。要當決策層必須先 fine-tune,而且要先驗證。
**佐證**:`bench/web_probe.py`(加 `--compact` 是精簡版);laya 0.3.21、laya-apple(PyPI)、M5 Max。

---
name: kev-mps-training-oom-long-states
type: constraint
status: active
confidence: probable
tags: [kev, training, mps, mac, memory]
discovered: 2026-09-29
---

**症狀**:在 M5 Max 36GB 上用 MPS 訓練 Kev-4B(`--batch 1 --accum 8 --checkpointing 1 --max_state 4096`),資料是約 3.8k tokens 的 web-agent 紀錄。程序 footprint 衝到 33GB,swap 用滿,`top` 顯示 stuck,10 分鐘內一步都沒跑完。使用者看到的是「記憶體忽然降下來」,那其實是系統在壓縮和換頁。
**根因(推測)**:Mac 上沒有 flash-linear-attention / causal_conv1d,DeltaNet 走純 PyTorch 的 reference 實作,長序列的中間張量很大;MPS 上也不能用 bf16 autocast(train.py 寫 CUDA only),權重是 fp32。只測過一次。
**繞法**:在 Mac 上只拿短資料(≤幾百 tokens)訓練 4B:約 7 s/step(8 筆),峰值約 19GB。長資料(web agent)要到 Modal / CUDA 上訓練。本機跑長資料之前,先用 `top -pid` 盯住記憶體,超過 28GB 就停。
**佐證**:`runs/mps-4b-probe*.log`(短資料 3 步 76 s、13 步 146 s)、`runs/mps-4b-web.log`(長資料,中途停掉)。

---
name: kev-stock-fails-jev-ultrafast-policy
type: constraint
status: active
confidence: probable
tags: [kev, web-agent, jev-ultrafast, latency]
discovered: 2026-09-29
---

**症狀**:jev-ultrafast 原封不動的 `choose()`,只把 endpoint 換成本機 Kev-4B,在模擬的高鐵訂票頁上只答對 1/6。它幾乎每步都回「CLICK Open 去程日期」或 BLOCKED,operation 信心值只有 0.11–0.17。中文目標和英文目標的結果相同。每步約 1.4 s、約 3.8k input tokens(M5 Max,MLX bf16);Jev 官方中位數是 178 ms。
**根因(推測)**:Kev 訓練時的 state 最長 384 tokens,而且沒有 web-agent 動作選擇的訓練資料;這個 prompt 長約 3.8k tokens,每題都重複一份英文規則,已經超出分佈。語言不是主因,因為換成英文也一樣錯。目前只測過這一個合成頁面,沒有對照組,所以標 probable。
**2026-09-29 更新**:改用精簡 prompt(`--compact`,約 900 tokens、規則只說一次)後,Kev-4B 升到 3/6、每步約 420 ms;錯在三個 SELECT 步驟(都誤選 TYPE_TEXT 或提早按查詢)。
**2026-09-29 再更新**:改成「拆題」(`--decomposed`):每個欄位問一題 noul(目前值是否符合目標)、每個下拉選單問一題 choice(該選哪個值),再加「是否已完成」和「送出按鈕」兩題,一次請求送出,由固定的 policy 組出動作。原生 Kev-4B 在兩組目標 × 6 步上全對(12/12,包含把選錯的站改回來),每步約 220 ms、約 550 tokens。同一個拆法 Laya MLX 只對 1/6。限制:這個 policy 只涵蓋「填表 → 送出」型頁面;導覽、autocomplete、日期選擇器、結果頁挑選都還沒測。
**繞法**:原生 Kev 不能直接拿來當 web agent 的決策層。要先用老師模型(Jev / Claude)收集瀏覽軌跡來 fine-tune,並縮短 prompt。在這台 Mac 上 Kev-4B 單步比 Jev API 慢,「本地一定比較快」這個說法不成立。
**佐證**:`bench/web_probe.py`(跑在 vendor/jev-ultrafast@1231850 上)。

---
name: opencc-s2twp-keeps-mainland-vocab
type: gotcha
status: active
confidence: confirmed
tags: [chinese, zh-tw, opencc, eval-data]
discovered: 2026-09-29
---

**症狀**:`opencc-python-reimplemented` 的 s2twp 轉出「賬戶」「到賬」「發貨」「快遞」「攬收」等,字形是繁體但用語是陸用(台灣會說 帳戶/入帳/出貨/宅配)。
**根因**:s2twp 只換字形和一部分詞彙,陸用語境的詞(物流、金流用語)不在它的詞庫裡;純 Python 版的詞庫又比 C++ OpenCC 小。
**解法/繞法**:機器轉繁的資料只能拿來測「字形」的穩健度,不能當成台灣用語評測。台灣題組必須用原生語料(例如 MASSIVE zh-TW)或人工撰寫。
**佐證**:`evals/synthetic_tw_s2twp.jsonl` 第 1 行(`賬戶安全`、`退款到賬`);`bench/make_tw.py`。

---
name: kev-chinese-advantage-unverified
type: constraint
status: active
confidence: probable
tags: [kev, chinese, premise, eval]
discovered: 2026-09-29
---

**症狀**:「Kev 基於 Qwen 所以中文更好」是推論;Kev README 的所有準確率/校準數字都只來自英文資料,沒有任何中文評測。
**根因**:Kev 的 LoRA + pointer head 以 decision-v7 訓練(trec/mnli/dbpedia14/banking77/agnews/yelp/sst5/imdb/boolq/amazon + 生成政策題),3348 筆中僅 2 筆含 CJK,且都是英文文件引用中文片名;中文能力只能「繼承自 Qwen base」,未被量測,溫度校準也是英文資料擬合的。未查 v8/v9 與後續 follow-up fine-tune 資料,故標 probable。
**繞法**:任何中文產品決策前,先建繁中評測集(含台灣用語)量 Kev 的準確率與 calibration;門檻值一律在中文資料上重擬合,不沿用英文的 temperature。README 本身也建議「another language」要 fine-tune。
**2026-09-29 更新**:簡中已實測(zh-decision-bench v0.2),路由 0.954–0.960 與 Jev 同級,簡轉繁翻轉率 1.5%;score/noul 題較弱、ECE 約是 Jev 的 2 倍。台灣原生商業題仍未量測。詳見 `evals/README.md`。
**佐證**:jaredpalmer/kev@main `evals/v7/decision-v7/*.jsonl` 以 `grep -cP '[\x{4e00}-\x{9fff}]{4,}'` 計數(calibration 0/968、development 1/1204、test 1/1176)。

---
name: form-submit-fills-half-initialized-page
type: trap
status: active
confidence: suspected
tags: [kfw, form_submit, thsr, timing]
discovered: 2026-09-29
---

**症狀**:`thsr-timetable` 在新 session 第一次跑回 `needs_help / result_not_proven`(rows=0,等了 12s)。四個欄位 `ok: true`、查詢鈕有按到,但截圖停在首頁:banner 空白、行程顯示「去回程」、適用優惠是空的、查詢鈕是淡色;`steps` 裡沒有 `pre: 不同意`。緊接著熱跑和關掉 Kav Chrome 後的冷跑都 `done`(5 班,約 6s),沒有重現。
**根因**:(當下最像的解釋)頁面 JS 還沒初始化完就開始填表。依據是截圖裡「適用優惠」下拉選單沒有被套上樣式,查詢鈕也是淡色。原本的 `wait_ready` 就算等到上限也不算失敗,結果也沒被檢查,所以程式看不出頁面還沒準備好。觸發條件不明:關掉 Chrome 冷啟動也沒有重現。
更正:少了 `pre: 不同意` **不是**證據。之後頁面正常的幾次也都是 `skipped`,對話框有沒有出現,取決於 profile 裡有沒有存過同意設定。
**繞法(已實作)**:`form_submit` 現在會把 `ready`、`pre skipped`、`controls_settled` 寫進 steps。按下送出後 2 秒內要看到換頁、送出請求或 DOM 變化其中之一,否則重新載入整頁、再跑一次(只重跑一次)。本機假頁面實測:第一次載入時按鈕沒反應的情況,重跑後通過;按鈕永遠沒反應的情況,回報 `result_not_proven`,hint 會寫明兩次送出都沒反應。原本的失敗還沒在真實網站上重現過,所以不能確定這個修法真的解決了它。
**佐證**:`~/.kav-fastweb/runs/260929-111204-1012/result.jpg`(失敗)vs `260929-111239-1955`、`260929-111300-d5cf`(成功)
2026-09-29 11:34 新程式(6eea579)走 MCP 跑 3 趟(熱跑、關 Kav Chrome 後冷跑、換起訖站)都 `done`,`controls_settled` 約 270ms,送出後 1–2ms 就看到請求,沒有觸發 `retry` → 仍未重現,confidence 維持 suspected。

---
name: biggo-card-ancestor-spans-offers
type: gotcha
status: active
confidence: probable
tags: [biggo, extraction, price-compare, shopee]
discovered: 2026-09-29
---

**症狀**:BigGo 搜尋結果(`biggo.com.tw/s/<q>?m=cp&c[]=tw_bid_shopee&c[]=tw_mall_shopeemall`)裡,從 `a[href*="purl="]` 往上找「最近一個含價格的祖先」當卡片 → 10 筆都拿到同一個標題「蘋果 AirPods Pro 3 真無線…」和 $4,990;使用者點開其中一筆 purl(`shopee.tw/product/19247371/47368306698`),實際是 1 元的客製化耳機套。
**根因**:BigGo 會把同款商品合成一張「$X 起」的彙整卡,旁邊的單一商品卡沒有自己的價格節點時,往上找會越過卡片邊界,拿到彙整卡或鄰居的標題/價格。只觀察這一頁一次,標 probable。
**繞法**:往上找卡片時,一旦祖先包含**兩個以上不同的 purl** 就停,只用停下前、有價格的最小區塊(改完後 26 筆都自洽,例 `1220524697/40727200293` → Apple AirPods Pro 3 $4,790)。另外卡片文字裡的第一個 `$` 可能是「折扣 $100」這類促銷字樣,不是售價,要用 `kfw/price.py` 的解析而非第一個 regex 命中。
**佐證**:scratchpad 探測腳本(未進 repo);使用者 2026-09-29 抽查截圖回報。

---
name: old-engine-silently-ignores-new-recipe-checks
type: trap
status: active
confidence: confirmed  # 讀 a4de5f6 的程式碼可確定,非推測
tags: [kfw, recipes, mcp, validation, safety]
discovered: 2026-09-29
---

**症狀**:`bot-fx-rates` 用了新加的 `expect_text: ["牌價最新掛牌時間：{today}"]` 來確保匯率是今天的。還沒重開 Claude Code 的 session 跑的是舊的 MCP server,舊引擎的 detail_extract 根本不讀 `expect_text`,結果照樣回 `done`、照樣給數字,**日期檢查被默默跳過,沒有任何提示**。
**根因**:`validate()` 只檢查必要欄位,不拒絕不認得的欄位;MCP server 啟動後程式碼就固定了。所以「配方用了引擎還沒有的檢查」時,舊引擎會把它當成不存在——安全檢查失效卻顯示成功。流程和引擎是分開更新的(流程在 `~/.kav-fastweb/`,引擎在 repo),這個落差會一再出現。
**繞法(已實作,2026-09-29)**:`kfw/recipes.py` 的 `_SCHEMA` 列出每種類型引擎會讀的欄位(含巢狀),`validate()` 遇到不認得的欄位就拒絕執行,提示「打錯字,或是新功能:請重開 Claude Code」(測試 `test_unknown_fields_are_refused_not_skipped`)。**只保護往後**:這之前啟動的 server 沒有這段檢查。新增引擎欄位時要同步更新 `_SCHEMA`,否則新欄位會被自己擋下(這是刻意的:寧可擋也不默默跳過)。
**佐證**:`git show a4de5f6:kfw/recipes.py` 的 detail_extract 沒有 expect_text;另一個 session 的 record `records/260929-bot-fx-rates.md`。

---
name: bot-fx-headless-chrome-cloudflare-challenge
type: gotcha
status: active
confidence: suspected  # 單次觀察(WP0b 子 agent 回報),未做對照
tags: [chrome, headless, cloudflare, testing, bot-fx-rates]
discovered: 2026-09-29
---

**症狀**:WP0b 在隔離的 `--headless=new` Chrome 跑 `bot-fx-rates`(台灣銀行牌告匯率),頁面標題是 "Challenge Validation",引擎回 `needs_help: no_structured_data`;同一台機器、同一份程式改用有視窗的 Chrome(`KFW_CHROME_HEADED=1`)就 `done`、19 列。同一次 headless 跑高鐵則正常。
**根因**:推測台銀前面的 Cloudflare 會挑戰 headless Chrome(尚未對照驗證)。
**繞法**:要對真實網站做驗收時用有視窗的隔離 Chrome(`tests/chrome_harness.py` 的 `KFW_CHROME_HEADED=1`);Chrome 整合測試只用本機 fixture 網站,不依賴真實網站。看到 "Challenge Validation" 不要當成配方壞掉,也不要嘗試繞過挑戰。
**佐證**:WP0b 回報(merge ab35e9f);2026-09-29 合併後以 headed 隔離 Chrome 重跑 `bot-fx-rates` → done、19 列。

---
name: pagehide-binding-call-not-delivered
type: trap
status: active
confidence: confirmed  # 同一 spike 內對照:pagehide 0/13、beforeunload 13/13 送達,headless 與 headed 一致
tags: [cdp, recording, binding, navigation, bfcache]
discovered: 2026-09-29
---

**症狀**:錄製 JS 在 `pagehide`(以及 `visibilitychange: hidden`)裡同步呼叫 CDP binding `__kfwRec(...)`,13 次離頁 Python 端**一次都沒收到** `Runtime.bindingCalled`;同樣的呼叫放在 `beforeunload` 則 13/13 送達(在 `Page.frameStartedLoading` 之前)。
**根因**:離頁時 binding 呼叫雖然在 JS 端是同步的,但訊息沒在文件卸載前送出到 DevTools 端(確切機制未深究;現象可重現)。
**解法**:不要依賴離頁事件送出最後資料。動作組在事件當下先送一筆「未完成」紀錄;`beforeunload` 只當提示;離頁前最後一組沒有事件後快照就視為缺口,由 Python 以 `frameNavigated` 補或標 incomplete;收束屏障一律由 Python 主動呼叫 `__kfwFlush()`。
**佐證**:`docs/design/demo-recording.spike.md`、`spike/recording/out/`(merge WP-S);Chrome 154.0.8037.58。

---
name: closed-shadow-root-composedpath-hides-inner-nodes
type: trap
status: active
confidence: confirmed  # 受控:同一段 markHandler,改用位置判斷前 7 個標記模式測試失敗(網站事件沒被吞),改後全過
tags: [recording, shadow-dom, events, chrome]
discovered: 2026-09-29
---

**症狀**:錄製提示列(closed shadow root)的全頁攔截層在標記模式下沒吞掉事件,網站的 pointerdown/click 照常收到;`event.composedPath().includes(overlay)` 永遠是 false。
**根因**:closed shadow root 外的監聽器,`composedPath()` 只含 host,**不含** root 內的節點(規格行為)。所以「事件是打在攔截層還是打在提示列按鈕」不能靠 path 分辨。
**解法**:滑鼠事件用座標判斷是否落在提示列矩形內;鍵盤事件用自己持有的 `shadowRoot.activeElement`(closed root 對持有引用的人仍可讀)。判斷「是我們自己的 UI」用 `path.includes(host)` 沒問題,host 在 path 裡。
**佐證**:`kfw/record.py` 的 `markHandler`/`inBar`;`tests/test_wp1_chrome.py` 的 mark 系列測試。

---
name: chrome-test-port-9444-shared-across-worktrees
type: gotcha
status: active
confidence: confirmed  # 直接觀察:並行 worktree 同時跑 -m chrome,第二個被 harness 拒絕(RuntimeError)
tags: [testing, chrome, harness, worktree]
discovered: 2026-09-29
---

**症狀**:`KFW_CHROME_TESTS=1 pytest -m chrome` 報 `RuntimeError: something already listens on :9444; refusing to reuse a Chrome the harness did not start`。
**根因**:harness 固定用 :9444;多個 agent/worktree 並行跑整合測試時只有一個能持有它(拒絕沿用別人的 Chrome 是刻意的,M04)。
**繞法**:等對方跑完再跑(`curl :9444/json/version` 失敗才啟動);不要殺對方的 Chrome。要真的並行需要 harness 支援 `KFW_TEST_PORT`(尚未做)。
**佐證**:WP1 開發過程多次遇到;`tests/chrome_harness.py`。

---
name: macos-closed-select-arrowdown-opens-popup
type: gotcha
status: active
confidence: probable  # 一次觀察(macOS Chrome 154 headless),換成 type-ahead 就改值;未對其他平台驗證
tags: [testing, chrome, input, select]
discovered: 2026-09-29
---

**症狀**:用 `Input.dispatchKeyEvent` 對聚焦的 `<select>` 送 ArrowDown,值沒變(沒有 input/change)。
**根因**:推測 macOS 上收起的 select 收到方向鍵是開啟選單而不是改值(Windows/Linux 才直接改值)。
**繞法**:測試改送可見字元(type-ahead,選項用拉丁字母開頭)才會改值並觸發 change。
**佐證**:`tests/test_wp1_chrome.py::test_select_change_is_one_group`。

---
name: input-type-submit-seen-as-text-field
type: trap
status: active
confidence: confirmed  # 修正前後 fixture 對照:修前 submit_not_found、修後 done;讀 CONTROLS_JS 可確定
tags: [kfw, form, controls, submit]
discovered: 2026-09-29
---

**症狀**:網站用 `<input type="submit" value="查詢">` 當送出鈕時,`form_submit` 回 `submit_not_found`;`controls()` 把它列成 kind `text`(label 取 placeholder/name,不是按鈕上的字)。
**根因**:`CONTROLS_JS`(後來的 `OBSERVE_JS`)把所有 `INPUT` 都當輸入框,只特例 checkbox/radio;`_find_control` 找送出鈕只看 button/link。
**解法(2026-09-29 已修)**:`input` 的 type 是 submit/button/reset/image 時列為 kind `button`,label 取 `value`/aria-label/alt(`tests/test_input_submit_chrome.py`)。改版前後等價測試沒涵蓋這種頁面,所以它是「刻意改變」而非回歸。
**佐證**:WP2 回報;commit 見 git log「input type=submit」。

---
name: {{kebab-case-slug}}
type: trap          # trap | gotcha | constraint
status: active      # active | superseded(過時不刪,改此欄並在內文指向 [[取代條目]] 或 record)
confidence: suspected  # confirmed(受控實驗坐實:改變因 → 症狀跟著出現/消失,至少兩次;
                       #           非因果事實則為「窮盡查證 + 指得出一手來源」)
                       # probable(多次觀察一致,但沒做對照組)
                       # suspected(單次觀察,或「當下最像的解釋」)
                       # 未標此欄 = unknown(舊條目),讀的人比照 suspected 對待
tags: [{{標籤}}]
discovered: {{YYYY-MM-DD}}
---

**症狀**:{{看到什麼(錯誤訊息/怪行為)——這欄永遠是事實,錯誤訊息照貼}}
**根因**:{{一句話。confidence 標的就是這一欄的把握度}}
**解法/繞法**:{{怎麼處理。非 confirmed 時只寫「繞法」,不寫「解法」,也不得當行為準則}}
**佐證**:{{commit/record 連結;標 confirmed 必須指得出受控實驗}}

---
name: expect-text-vs-innertext-newlines
type: trap
status: active
confidence: confirmed  # 直接觀察:WP2 Chrome 測試,text-contains 比對 match:true 但引擎 expect_text 判 result_not_proven
tags: [recording, recipes, expect_text, text-contains]
discovered: 2026-09-29
---

**症狀**:標記一個多段落的文字塊,草稿的 `expect_text` 取標記文字開頭 30 字(含空格),dry_run 的 text-contains-v1 比對通過,引擎卻回 `result_not_proven`(缺少文字)。
**根因**:標記文字是空白正規化過的(換行變單一空格),引擎 `expect_text` 卻用 `t in body`(原始 innerText,段落間是換行)。兩邊的空白處理不同。
**解法**:草稿的 expect_text 錨點取單一不含空白的詞(`draft.py`);text-contains-v1 比較器本身才負責完整文字。之後若要放寬引擎的 expect_text 比對要連同既有配方一起評估。
**佐證**:`tests/test_wp2_chrome.py::test_text_block_demo_becomes_detail_extract...`。

---
name: recorded-consent-click-missing-in-everyday-profile
type: trap
status: active
confidence: confirmed  # 直接觀察:WP2b Chrome 測試,同一份草稿在乾淨環境 done、在已同意過的日常 profile step_failed;標 optional 後兩邊都 done
tags: [recording, steps, cookie-banner, optional, profile-state]
discovered: 2026-09-29
---

**症狀**:示範時點了「同意 cookie」,轉出的 steps 第一步是 `{click: 同意, then: {gone: 同意}}`。隔離環境的 dry_run 通過、存檔後用 `run_recipe`(日常 profile)卻 `step_failed`:找不到「同意」。
**根因**:橫幅只在沒有同意記錄的瀏覽器狀態出現;示範完 profile 已記住同意,之後每次執行(日常 profile)橫幅都不在,非 optional 的點擊 `not_found` 就停。
**解法/繞法**:Claude 把這種點擊標 `optional: true`(只跳過 not_found、不跳過 ambiguous);轉換器在 then 候選是「自己消失」時會發警告。示範值判定不計 optional 點擊(見 DECISIONS 同日),所以標了仍能滿足 (a)。反過來,示範前 profile 就已同意過、沒錄到這個點擊 → 乾淨環境重播的頁面不同 → `needs_profile_state`(測試 `test_state_the_demonstrator_already_had_is_not_replayable_needs_profile_state`)。
**佐證**:`tests/test_wp2b_chrome.py::test_multi_page_demo_becomes_steps_with_pick_then_dry_run_in_a_clean_context_second_params_and_save`。

---
name: demo-profile-hides-consent-banner-from-clean-replay
type: trap
status: active
confidence: confirmed  # 2026-09-30 高鐵真人示範:同一份草稿,沒有 pre 時隔離試跑 submit covered;加 {click: 不同意, optional} 後隔離試跑 done 且示範一致
tags: [recording, cookie-banner, isolated-replay, profile-state, diagnostics]
discovered: 2026-09-30
---

**症狀**:使用者在日常的 Kav Chrome 示範高鐵查詢,草稿沒有任何 pre;隔離環境的示範值試跑卡在 `{"submit": "查詢", "ok": false, "why": "covered"}`,截圖上是「個人資料使用說明」同意視窗蓋住表單。回傳的 `unsupported` 卻寫 `widget_value_not_replayable`(把錯推給「出發時間」是元件設定的)。
**根因**:使用者的 profile 早就關過 cookie 同意視窗,示範時它根本沒出現,所以錄不到;乾淨環境是全新狀態,視窗一定跳出來。這是 `recorded-consent-click-missing-in-everyday-profile` 的反方向。誤報是因為 dry_run 只要「草稿有 via_widget 欄位 + 示範不一致」就歸咎元件,沒先看是不是中途步驟就失敗。
**解法**:Claude 看到 covered / 截圖有同意視窗 → 在 pre 加 `{"click": "<最少同意的選項>", "optional": true}`(pre 不計入示範值判定),重跑即可。誤報已修(8fd2764):`_unsupported_after_failed_demo` 只在比對真的判定不一致(match: false)時才歸咎 via_widget,引擎中途失敗回 None。
**佐證**:`~/.kav-fastweb/runs/260930-123021-b890/result.jpg`(被擋)、`-123057-c74b`(加 pre 後一致);record 260930-thsr-demo-acceptance。

---
name: recording-page-closed-while-tab-still-open
type: trap
status: active
confidence: suspected  # 單次觀察;推測的原因(網址列預先載入換掉 target)未驗證
tags: [recording, cdp, target, prerender]
discovered: 2026-09-30
---

**症狀**:錄製開始 155 秒後自己結束,`incomplete: page_closed`,但 Kav Chrome 裡錄製的高鐵分頁還開著(`/json/list` 看得到)。當時使用者正在問「要怎麼開始錄製」,可能在那個分頁的網址列重打了網址。
**根因(推測)**:從網址列開啟時 Chrome 啟用預先載入(prerender)的頁面,用另一個 target 換掉原分頁;錄製器只認原本的 targetId,`detachedFromTarget` + `getTargets` 找不到它 → 判定關閉。
**繞法**:8de32d7 對錄製分頁送 `Page.setPrerenderingAllowed(false)`,並在 page_closed 時記下 `target_id` 與當下所有分頁(`meta.json`、flag detail)——再發生時可直接比對是否被換掉。之後兩次示範沒有再發生(不代表已證實)。告訴使用者:錄製時不要在網址列重打網址。
**佐證**:`~/.kav-fastweb/recordings/0da72da54868/`(當時還沒存 target_id)。

---
name: recording-drops-non-button-filter-clicks-silently
type: trap
status: active
confidence: confirmed  # 讀 draft._events 程式碼 + 591 錄製 e154d6f4c2e9 的日誌:g2 目標 DIV「雅房」is_button_like false、無原生欄位變化 → _events 回 [],無任何警告
tags: [recording, converter, spa, filter-pill]
discovered: 2026-10-07
---

**症狀**:591 租屋示範 3 步(北投區、雅房、下一頁),草稿只剩 `pre: 北投區` + `submit: 下一頁`,「雅房」篩選不見,也沒有警告;重播會拿到未篩選的列表。
**根因**:`draft._events` 只把 `is_button_like` 的目標當 click;非按鈕目標只看原生欄位有沒有變,沒變就回空。591 的篩選膠囊是 DIV(`in_controls: false`),改的是網址 query(`kind=4`)而非表單欄位。日誌其實有線索:每次點擊後都有 `nav same_document` 記下新網址,但 `_parse` 忽略 `nav` 紀錄。
**解法(未做,2026-10-07 決定暫停錄製驗收)**:`_parse` 把 same_document nav 掛到當下的 group 當 `url_changed`;非按鈕點擊若 `url_changed` 且有文字就留成 click(pre 不標 optional);引擎端 `_find_control` 找不到按鈕/連結時,退回「可見、文字精確相等、最內層」的元素(需唯一),否則 DIV 點不到。
**佐證**:`~/.kav-fastweb/recordings/e154d6f4c2e9/log.jsonl`(g2 與其後的 nav)。

---
name: mark-table-skips-single-child-card-wrappers
type: trap
status: active
confidence: confirmed  # 591 列表頁即時 DOM:每張卡片 = `DIV.`(無 class)→ 單一子元素 `DIV.item`(2 子);collect() 無 pattern 路徑要求列有 ≥2 子元素,整組卡片被排除
tags: [recording, mark, table-finding, card-list]
discovered: 2026-10-07
---

**症狀**:使用者標記 591 整個列表(MAIN,4 張卡片),`marked_summary.table` 只有 3 列、而且是第一張卡片裡的三行小字(`DIV.item-info-txt|3`);`pattern_unavailable`,無法產生 rows.pattern。引擎在點擊前觀察到的 `res.groups` 也從未出現卡片群組。
**根因**:fc5b595 為高鐵加的「列至少要有兩個部分」規則(`k.children.length >= 2`)在卡片列表上誤殺:卡片外層是只有一個子元素的包裝 DIV,真正的多部分在裡面一層。
**解法(未做)**:判斷「多部分」時先沿單一子元素鏈往內剝(`while children.length === 1`),再數部分;`cellsOf` 兩側一致即可不動。有 pattern 的引擎路徑不受影響(regex 比對 innerText 不看子元素數)。
**佐證**:本 session 以 `kfw.cdp` 對 `rent.591.com.tw/list?region=1&section=9&kind=4&page=2` 取得的祖先鏈;record 261007-pick-judgment-experiment。

---
name: rows-pattern-silently-narrows-pick-candidates
type: trap
status: active
confidence: confirmed  # 同一頁同時用嚴格與寬鬆 pattern 各抓一次:26 vs 30 列,漏掉的 4 列逐一看過(小數坪數、頂樓加蓋、B1)
tags: [pick, rows-pattern, kev, silent-failure]
discovered: 2026-10-07
---

**症狀**:591 北投區雅房列表 30 張卡片,`rows.pattern` 寫 `雅房\d+坪\d+F/\d+F.*元/月` 只中 26 列;漏掉的 4 列裡有一筆「可養寵物」,讓「可養寵物的」這題的正確答案從唯一一筆變成兩筆(該停)。Kev 只看得到 pattern 選中的列,選對了 26 列版的答案,其實是錯的。
**根因**:pattern 是 Claude 看幾張卡片後寫死的格式假設(整數坪、`數字F/數字F`);真實資料有 3.5 坪、4.5 坪、2.7 坪、「頂樓加蓋/5F」「B1/5F」。pick 路徑對「列表裡有些列不符 pattern」沒有任何訊號(同群組 ≥ 60% 符合就算合格)。
**解法/繞法**:列表類 pattern 只鎖「每列一定有、別處沒有」的錨(這頁是 `元/月`),不要描述格式細節;寫完用寬鬆 pattern 對照一次列數。待做(方向定了再決定):群組內不符 pattern 的列數回傳到結果,讓 Claude 看得到「漏了幾列」。
**佐證**:`evals/pick-591/rows.json`(26)vs `rows30.json`(30);record 261007-pick-judgment-experiment 發現 2。

---
name: pick-needs-fixed-button-text-card-lists-have-none
type: trap
status: active
confidence: confirmed  # 591 列表即時 DOM:每張卡片內唯一可點的是標題 `<a target="_blank">`,文字逐列不同
tags: [pick, steps, card-list, new-tab]
discovered: 2026-10-07
---

**症狀**:想在 591 用 `steps` 的 `pick` 挑一筆再點進詳情,但 `pick.click` 要填「列內固定文字的按鈕/連結」,卡片裡只有標題連結(文字每列不同),而且 `target=_blank` 會開新分頁——引擎只盯原分頁,會回 `pick_no_effect`。
**根因**:pick 的設計(DECISIONS 2026-09-29)假設列表像後台表格,每列有同名的「查看」鈕;電商/租屋/新聞這類卡片列表普遍是整張卡片或標題可點、常開新分頁。
**解法/繞法**:本實驗改量「選哪一列」(直接呼叫 `steps._select_row`),不做端到端。待做(方向定了再決定):pick 支援 `click` 省略 = 點選中列裡唯一的連結,並接住新分頁(`Target.targetCreated` 後接管)。
**佐證**:record 261007-pick-judgment-experiment 發現 3。
