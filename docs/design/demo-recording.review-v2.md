# demo-recording v2 複查

對象：`f4f08a9` 的 `docs/design/demo-recording.md`。下文設計行號均指此版本；程式引用以目前工作樹為準。本次為靜態設計審查，並核對相關官方規範；沒有執行 WP-S、產品測試或實作，也沒有修改程式、設計及 flightwake 文件。

結論：**CHANGES_REQUIRED**。v2 已解決多項 v1 問題，但仍有會影響錄製正確性、存檔條件與重試安全的契約缺口，並非只剩實作細節。**R13 的待決與 WP5 暫停不構成本次否決原因**。

WP-S 可以開始探索，但不能照「跨 port＝跨 site」的原描述驗收；WP0 的 CDP 分派、觀察抽取、optional 修正可以先做，整包按目前安全保證與測試描述直接驗收則不行。具體開工條件見末節。

## R01–R24 處理核對

「已解決」指設計方向與契約足夠，不代表已有實作驗證。「部分」後附本次問題編號，避免把第 9 節的「採納」當作全部關閉。

| 原編號 | 判定 | v2 核對結果 |
|---|---|---|
| R01 | 已解決主要問題 | §2.1 將事件 callback 移出 reader、加入 off／例外隔離／斷線喚醒；WP0 仍須遵守回覆不排進同一 dispatcher 等實作約束，見 M01。 |
| R02 | 部分 | §2.2 不再以 targetInfoChanged 判失效，方向正確；WP-S 沒真正測跨 site，世代／ACK／結束完整性還不明確，見 V01、V10。 |
| R03 | 已解決主要問題 | §2.2 的 isolated world、context/frame 驗證及注入順序正確；只需補 listener 安裝、當前 context 與 payload 細節，見 M02。 |
| R04 | 部分 | §3.2 保留日誌、§6.2 不吸收 button/link，解決原先的直接漏 submit；before 的時點、重複事件與「原生 text 即可重播」仍不成立，見 V04。 |
| R05 | 部分 | baseline／文件切段與無 label 拒絕有補；§6.2 卻明確丟棄多數未改預設值，且排序不足以處理相依動作，見 V05。 |
| R06 | 已解決方向 | §2.3 不改寫網站、無法歸屬也拒絕，保守範圍可接受；discovery 過濾等屬實作細節，見 M02。 |
| R07 | 未完全解決 | SPA／BFCache 有補，但 iframe 及 closed Shadow DOM 的偵測敘述不能保證「全部明確拒絕」，見 V03。 |
| R08 | 部分 | UI host 排除與專用標記層正確；Alt 啟動當次事件、已在網站欄位上的鍵盤焦點仍未隔離，見 V09。 |
| R09 | 已解決方向 | DOM API＋CSSOM 與三種 CSP fixture 是合理做法；WP-S 要實測 UI 而不只是 hello，見 V01。不再主張 CSP 必然擋 binding。 |
| R10 | 部分 | 狀態、時限、冪等 stop、磁碟限制及清理已有；blocked 終態、最後事件提交、崩潰復原與來源到期仍未閉合，見 V10、V11。 |
| R11 | 部分 | gate 覆蓋所有動作與真實元素是改善；「禁止購物車所以全部只讀」是錯誤推論，見 V02。 |
| R12 | 部分 | 同一規則來源、baseline 檢查、blocked 不截圖已補；URL/mark 等出口及已落盤內容清理仍不完整，見 V11。 |
| R13 | 合理延期 | §5.4 已刪第一個連結 fallback；依使用者本次指示，原則例外未決前 WP5 不做。延後項的 API 細節見 M05，不阻擋前面工作。 |
| R14 | 已解決 | §5.1 明定 not_found／ambiguous，optional 只跳前者；§6.2 把 pre optional 改成待核對的建議。 |
| R15 | 已解決主要問題 | §6.3 明確 opt-in，且證據綁 recipe_hash＋recording_digest，不再聲稱 server 能強制辨識所有錄製來源；新增的第二組參數條件另有 V06 問題。 |
| R16 | 部分 | canonical raw cells 與截斷拒比已補；無 rows、無參數及非穩定資料的適用範圍仍未定，見 V06。 |
| R17 | 部分 | 單列不自動產生、禁止自動放寬正確；全頁同筆數不是同一群列，columns 非空也非已確認，見 V07。 |
| R18 | 已解決主要結構問題 | §3.4 加 row ID／列內 controls，§5.4 點前重驗，WP5 獨立；即時 row ID 有效期與純 converter 邊界需補，見 V07、M05。 |
| R19 | 部分 | 有 then 與中途失敗 gate 是改善；並非每種 then 都證明變化，重試的只讀前提也未建立，見 V02、V08。 |
| R20 | 部分 | check boolean／radio、遞迴 schema、steps 不接受 partial 已解決；分頁結束／循環及 wait 契約仍有缺口，見 V08。 |
| R21 | 部分 | WP-S 與 B/C/D 拆開、隔離測試環境很好；跨 site fixture 錯誤，WP0 改 DOM 觀察卻未列 Chrome 等價驗收，見 V01、V12。 |
| R22 | 已解決方向 | §5.4 明列對照數字及負例；WP5 延後合理。信心門檻仍須實測，不是已校準的安全保證，見 M05。 |
| R23 | 已解決 | A/B/C/D/E 分拆符合建議；不要求先完成語意 pick 才交付錄製。 |
| R24 | 已解決主要問題 | §6.1 compare_to 已入介面，§6.4 修復不再確認結果；明確要求錄製卻再問一次的冗餘可在 skill 實作時修正，見 M06。 |

## 尚需修正的實質問題

### V01【應修；WP-S 開工前校正】不同 port 不是跨 site，spike 會得到錯誤信心

引用：§7，243–248 行；關聯 R02、R09、R21。

`http://localhost:8000` → `http://localhost:8001` 是不同 origin，但仍是同一 site。Chromium 的 site 定義忽略 port；這組測試不能作為 renderer 程序切換、session 行為或是否需要 auto-attach 的證據。[Chromium Site Isolation 設計](https://www.chromium.org/developers/design-documents/site-isolation/)

修正：以兩個真正不同 site 的 hostname（例如測試 Chrome 的 host resolver 將 `a.test`、`b.test` 都映到 loopback）提供 fixture；分列同 origin、跨 origin 同 site、跨 site。結果表保存 target/session/frame/context 與導覽事件順序；若未取得程序切換證據，就如實寫「未驗證」，不能判定不需要相關處理。

WP-S 的 CSP 驗收目前只寫 hello／事件，還不夠關閉 R09。應用 §3.3 的最小實際 UI，在三組 CSP 下測「可見、可標記、可完成、可 teardown」。SPA 原本不應重送新文件 hello；BFCache 須真的觀察到 persisted 恢復，沒進 BFCache 要記未覆蓋，不能當成功。這些都是 spike 本身的驗收校正，不必先做完整 recorder。

### V02【阻擋；影響 WP0 安全契約及 WP3】denylist 不能推出只讀，結果確認也不能保證沒有副作用

引用：§4，111–122 行；§5.2，156 行；DECISIONS 2026-09-29「安全與完成判斷放在本地程式」；關聯 R11、R19。

把「加入購物車」也禁止，仍擋不住名稱為「確認／送出／繼續」的狀態修改，例如訂閱、刪除、預約或已登入的一鍵交易；沒有密碼欄、沒有敏感輸入、URL 不是三個指定路徑，也能改資料。checkbox/select 的 change handler 亦可能直接送出。故 §4.116 的「讓所有流程都是只讀的」及 §4.122 的「真正保證」沒有被 gate 規則建立。

這不是要求做出能理解任何網站的完美安全判定，而是不能以有限檢查推出不存在的保證，再以此授權自動重跑。使用者確認結果發生於 dry_run **之後**，當時副作用可能已發生，也不能充當執行前安全邊界。

最小修正：將 gate 定位為拒絕已知禁用及無法判定的操作；明確限制支援任務範圍，列出具體可接受／拒絕例子。**新 steps 預設不整段自動重跑**；若要保留，另訂能被執行器核對的重播資格，不接受單靠配方自報 `readonly`。不必在 WP0 順便改既有 form_submit 的重試決策，但不能把那項決策擴張到任意 steps。

WP0 可以實作列出的拒絕規則；驗收應稱「已知禁用操作被 gate 拒絕」，不能稱「已證明全部流程只讀」。另需將 gate 放在動作之前的實際節點解析處，不能只檢查過期快照。

### V03【阻擋；WP1 前解決】closed Shadow DOM 與 iframe 的漏錄偵測仍有確定盲點

引用：§0.6、§2.3，62–63 行；§8，261–262 行；關聯 R07。

外部 listener 的 `composedPath()` 不會包含 closed shadow root 裡的節點；`composedPath()[0]` 會是外部可見的 host，因此「檢查它是否位於 shadow root」不能偵測這種控制項。[DOM composedPath 規範](https://dom.spec.whatwg.org/#dom-event-composedpath)

iframe 子文件內的 pointerdown 不會冒到父文件，把主框架 listener 的 target 寫成 IFRAME 並不能覆蓋內部操作。activeElement 可以表示焦點在子框架，但不能當作每次操作必然產生的通知；需指定監測時機，且不可假設所有非聚焦操作都會轉移焦點。[HTML 焦點 API](https://html.spec.whatwg.org/multipage/interaction.html#dom-document-activeelement)

修正：先選擇可驗證的保守政策，例如所有無法解析成支援操作的網站互動一律 incomplete，對可互動 iframe 採更早拒絕；若要更細緻，需增加能觀察到該情境的機制並經 fixture 證明。不要寫「全部明確拒絕」，實際卻只辨識 open shadow 與剛好得到焦點的 iframe。至少加入 closed root、自訂 host、iframe 內不可聚焦區域及跨來源 frame 負例。

### V04【阻擋；WP1/WP2 契約】原始日誌的 before/after 尚不能可靠還原使用者動作

引用：§3.2，75–89 行；§6.2，203–207 行；`kfw/form.py:27–35`、`:76–95`；關聯 R04。

input/change 是值已更新後的通知，即使在 capture 階段拍照，before 也可能已是新值。paste、自動填入、IME 提交等不能靠僅記 Enter/Escape/Tab 的 key 欄位補回。一次滑鼠輸入還可能依序產生 pointerdown、click、input、change、submit；每筆各等 150ms 穩定，會得到互相重疊的 before/after，不能當作多次獨立操作依序轉換。快速離頁時的 after 更不一定能形成。

§6.2.204 也把「非 readonly 的原生 text」當成 setter 可重播證明；自動完成依賴隱藏 ID 的反例仍成立。原生標籤不代表網站只看 `.value`。另外 `in_controls == false` 的註解寫「不是 button/link」，但 controls 本來也包含 input/select，這兩個條件不是同義。

修正：明訂穩定基線／最後已提交快照、動作分組 ID、事件去重與離頁收束規則；使用 beforeinput 或上一已知值處理值變化，定時快照僅是觀察資料。保留必要網站操作，無法證明等價時不要吸收。A 版可先拒絕自動完成／非原生選項選擇，避免假裝現有 fill 足夠。測試至少包含單次文字輸入、paste/IME、一次 submit 的多事件，以及送出同時正規化欄位；日誌應轉成一次正確動作，而非零次或多次。

### V05【應修；WP2 前】baseline 有存，卻把影響結果的預設值丟掉

引用：§6.2，203、208 行；關聯 R05。

「其他未改動的預設值不寫，執行時同樣是預設」沒有依據。起訖站、地區、排序、幣別也可能取自 profile、localStorage 或上次查詢；下一次執行的預設不一定等於示範。日期只列 param_candidates 和 warning，也沒有要求最後必須進草稿。

「依最後一次編輯排序」同樣不能取代相依步驟：例如城市 A→區 X→城市 B→送出，網站會重設區，最後一次使用者編輯的區 X 已不是提交值；多次快照中的自動更新亦不能一概當使用者獨立設定。

修正：保存並核對提交邊界的有效欄位值，對可重播且影響查詢的預設建立明確 set 或 precondition；只合併連續、沒有相依動作介入的編輯。不能表達就 needs_steps／unsupported，不能憑日期形狀決定哪些預設值得保留。

### V06【阻擋；WP2 前】第二組參數與 exact-v1 排除了合法流程，又留下空比對漏洞

引用：§6.2，210、213–219 行；§6.3，224–232 行；`kfw/recipes.py:163–179`、`:358–376`；關聯 R15、R16，新引入條件。

所有 recorded_from 都要「不同參數」會讓無參數 detail_extract（例如固定網址的台銀今天匯率）永遠不能存，這恰是 A 版要支援的類型。反之現有 check_params 不拒絕額外參數，render 會忽略未引用的 key；把 `{}` 改成 `{"unused": 1}` 就是不同 dict，實际行為完全相同，不能證明泛化。

示範值相等的判斷只談「欄位值」，對 URL 參數、click 目標、同 label 的多步驟及零 fields 沒有定義。僅比較 raw rows 又使無 rows 的 mark 可能變成 `[] == []`：現有 detail_extract 即使只抓到另一份 product 也可能 done，不能據此說重現了使用者標記的段落。若實作改成一律拒絕空 rows，也必須在設計明說，不然兩種實作都看似符合文件。

修正：A 版先明列 exact-v1 支援穩定、非空表格；其他結果另定比較器或明確 unsupported。第二組測試只對具有可變輸入的流程要求，且至少一個**實際使用的有效輸入／渲染後動作值**不同；無參數流程以同條件重跑與原有完成條件驗證。定義 demo_params_map 如何映射到有順序的動作和 URL，不採用空集合的相等當證據。

動態資料不放寬是正確的，但「請再示範」不保證幾分鐘後資料不變；應明寫不能達到 exact-v1 時此任務暫不支援，避免無限重錄。

### V07【應修；WP0/WP2 前劃清介面】列數一致不是選對群組，純 converter 也不能驗現場 DOM

引用：§3.4，103–105 行；§6.2，199、214–218 行；`kfw/form.py:43–62`；`kfw/recipes.py:302–313`；關聯 R17、R18。

全頁有另一個同樣 N 列的群組時，「全頁命中數等於標記列數」仍可能選錯。現有 ROWS_JS 只回最佳群組，而非所有匹配群組；沿用它的回傳筆數尤其不能聲稱沒有誤中。相同文字的兩張表也可能通過 exact-v1，仍未證明所標的是哪張表。

`to_draft(log, snapshots)` 被定義成純函式，但步驟內要求在錄製頁面執行 JS RegExp 全頁驗證；該頁可能已導覽、關閉、或 stop 已 teardown／斷線。這是工作包間的介面矛盾，不能由純函式自行補瀏覽器呼叫。

修正：共用觀察器提供群組／列身分與歧義資訊；現場驗證比較標記群組與全頁實際選中群組，不能只比筆數。純 converter 僅產生候選 pattern；live validation 由獨立 orchestration 執行並將證據傳入，頁面已不存在則標待 dry_run 驗證。明確保留 canonical raw rows 與是否截斷的 metadata，別從已截斷的 public rows 重建。

columns 還需拒絕重複非空名稱，否則 `label_rows` 的 dict 會覆蓋同名欄。`save` 能檢查「已填合法欄名」，無法僅憑非空推論「使用者確認過」；後者留在建立流程的確認步驟即可，不必虛構程式保證。對空格子、表頭排除、root 本身是否參與分組應先訂等價測試，見 V12。

### V08【應修；WP3/WP4 前】then 與分頁仍可把舊狀態當新結果

引用：§5.2，151–157 行；§5.3，164–169 行；`kfw/form.py:165–177`；關聯 R19、R20。

`text`／`rows` 有前後差異要求，但 `field`／`url_contains` 沒有：若點擊前已存在欄位或 URL 已含 `/timetable`，壞掉的 click 仍可立即通過。`gone` 也須釐清是指定的唯一控制項確實消失，還是查找結果由唯一變成 ambiguous。wait「同 then 判定」又沒有 click 前的基準時點，已存在的文字到底應立即成功還是必須先消失再出現不明。

next_page 只比前一頁，不能偵測 A→B→A 循環；也可能在短暫空表／loading skeleton 時視為內容已變。not_found 當正常結束依然會把按鈕改名／未載完誤當尾頁。`more_pages: true` 的上限語意已明確，可以保留，但這是「完成要求的頁數」，不能顯示為已收集全部。

修正：click 的 then 明確要求相關轉移或新的文件／結果版本，wait 則定義為純狀態等待；空字串／無效 rows 條件拒絕。分頁保存已訪結果指紋，等待符合結果規格且穩定的非暫態資料；採明確尾頁證據，或把無法區分的按鈕缺席列為未證明完整。B 版「確定性」也應說清 select 是否仍借用 `_resolve_option` 的 Kev fallback（`kfw/recipes.py:236–246`）；若只允許確定性選項，不能無說明地沿用它。

### V09【應修；WP1 前】標記 overlay 不會追溯攔下觸發它的事件，也不會自動接管鍵盤焦點

引用：§3.3，96–97 行；關聯 R08。

Alt+pointerdown 在網站元素上觸發後才插入 overlay，當次事件的 target/path 不會變成 overlay；只靠新 overlay 的 listener 無法阻止原事件繼續到網站。overlay 也不會自然奪走原欄位的鍵盤焦點，因此「網站收不到任何事件」過度承諾；keydown 可能還在原 input 上發生。

修正：最簡單先取消 Alt 捷徑，只由提示列按鈕進入標記模式；或明確在既有 capture listener 取消啟動事件及後續相容 mouse/click。進入模式時管理鍵盤焦點並攔截鍵盤事件，退出時恢復。不能倒轉更早執行的網站 listener，因此契約應限定模式已啟動之後。加入測試：網站在 pointerdown 計數／導覽、輸入框已聚焦時按 Enter、按 Esc 取消均不得觸發網站操作。

### V10【應修；WP1 前】完整性不能只靠 hello 和同步 binding 呼叫

引用：§2.2，49–55 行；§3.2，84–89 行；§6.1，195–196 行；關聯 R02、R10。

`doc_seq` 由每份新文件的 JS 送出，但沒定義誰跨 reload 配號；新 isolated world 的計數會重設，BFCache 又會回到舊物件。必須定義 document ID 與恢復世代，不能靠每份文件都從 1 開始。seq「遞增」也不等於連續，遺失尾端更不會由下一筆發現。

binding 的 JS 呼叫是同步，不代表 Python 已收妥、快照已完整落盤；協定提供的是 bindingCalled 通知，並沒有磁碟提交確認。[CDP Runtime binding 定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/js_protocol.json)

修正：定義明確文件 ID／session epoch、最後序號與快照引用提交屏障；done／stop 須先收束 pending after、完成所需快照，才能寫 completed。缺最終資料或壞引用一律 incomplete。server 重啟後未 finalize 的目錄不得被當作 completed；保留分頁且回到 BFCache 時，舊 recorder 的 listener／timer 不得復活繼續收集，需停止 token／租期等可驗證方案。§2.2 的終態也要納入 §4 的 blocked，或規定 blocked 是 incomplete 的 reason，不能各自實作不同狀態。

### V11【應修；WP0 介面、WP1 行為】敏感資料出口與保存期限還未閉合

引用：§4，118–120 行；§6.1，195–196 行；§6.3，228–233 行；關聯 R12、R16。

JS 不輸出敏感欄位 value 是正確的，但 URL query／fragment、頁面回顯與 mark 仍可能含敏感值，而不一定存在非空敏感 input 或 focus 事件。現在已改成日誌增量落盤，「blocked 後只保留摘要」還需要明列既有 log、snapshot、暫存檔與之後 MCP 回傳如何清理；摘要裡的 target/label/text 也不能直接假設不敏感。敏感 input 的「非空檢查」與「從不讀取值」應改成清楚的契約，例如僅在頁內判定 presence boolean、不複製原值。

另一个新增生命週期問題是錄製保留 30 天，但日後 save 仍要求來源存在；不改配方而重存也可能因到期失敗。更嚴重的是未明列來源是否也為 run_recipe 的依賴：若誤放進共用 validate，已驗證流程可能第 31 天突然不能執行。

修正：定義各輸出欄位的最小保存／遮罩政策與 blocked 原子收尾測試；不要把不見敏感 input 當作所有文字可保存的證據。明訂已存流程的執行不依賴錄製目錄；對再次驗證／修復，選擇保留被引用的必要證據，或明確要求新錄製。重複 stop 與 discard 也需定義：discard 後回最小 tombstone 狀態，不能一邊刪檔、一邊承諾永遠回同一份完整結果。

### V12【應修；WP0 驗收前】WP0 不是只有 Python 抽常數，缺少 DOM 等價與安全整合測試

引用：§3.1、§3.4、§7 WP0；`kfw/form.py:11–62`；`tests/test_core.py`、`tests/test_recipes.py`；關聯 R21。

把 ROWS_JS 改為支援任意 root、無 pattern、row ID、列內 controls，已超過抽常數。現有主要單元測試沒有在真 DOM 上證明這些 JS 保持結果一致；全套 Python 測試綠不代表 rows／label 行為沒變。gate 所需 autocomplete、name、form 脈絡也不是目前 controls 的完整回傳內容，單測合成 control dict 會漏掉觀察層沒有提供資訊的整合錯誤。

修正：WP0 明列 Chrome 包，使用隔離 profile 執行 controls／rows 的前後等價 fixtures，及「經真實 form_submit 路徑，危險動作未被派發」的測試。涵蓋重名 optional、表格空格／巢狀列、readonly／password／autocomplete、外置 form 關聯按鈕、DOM 替換後 stale control。先訂共用觀察器介面，再實作 §3.4 擴充；不要求 WP0 提前做 pick。

## 可在實作中處理、不單獨阻擋的事項

以下都標為【建議】；不必另等一次設計核准，但要寫入對應測試或實作說明。

| 編號 | 引用 | 實作注意 |
|---|---|---|
| M01 | §2.1；`kfw/cdp.py:40–69` | 命令回覆仍由 reader 直接喚醒 slot，只把事件交 dispatcher。listener 可 send，但不能等待只能由同一 dispatcher 處理的下一個事件；長時間 stop／磁碟工作移到 recording worker。同步管理 pending/disconnected，避免斷線後新 send 永等；目前 socket timeout=30 秒，安靜錄製不應因單次 recv timeout 被判斷真斷線。 |
| M02 | §2.2–2.3 | 在任何可能產生事件的命令前註冊 listener；payload 明寫 JSON.stringify。記錄 self target ID、忽略 discovery 初始既有 targets、限定 page 類型，否則 worker／OOPIF／自身 targetCreated 也可能造成 new_tab 誤殺。錄製實際 reattach 與 Tab.call 的 fallback 需序列化；重新 attach 不能替已存在 document 自動重跑 new-document script。 |
| M03 | §4；`kfw/judge.py:26–27` | 英文 safety 比對保留詞界再做 `\bpay\b`，不要沿用會去空白的 normalize，否則 `Pay now` 變 `paynow`。Python／JS 從同一 JSON 取規則後，還需同一批輸入證明正規化／regex 語意一致。 |
| M04 | §3.3；§7 | 延後掛 UI 要兼容 DOMContentLoaded 已發生／BFCache 恢復；安全處理 observer 重掛與 teardown 競爭。KFW_HOME／CDP 在 import 前設定，且確認 :9444 確為本測試 profile；`ensure_chrome()`（`kfw/compare.py:34–42`）目前只看埠可連，不核對 profile。 |
| M05 | §5.4；`kfw/judge.py:83–89` | 現有 choice 只回選中項機率，無第二名；options 作 dict key 又會合併同名列。WP5 若獲准，使用穩定候選 ID、完整機率、row ID 的觀察世代，再驗證門檻。此項隨 WP5 延後，不要求現在改 Judge。 |
| M06 | §6.4，237 行；§7 | 使用者已明確說「請開始錄製」就已有授權，不必再問一次；只有 Claude 主動建議時先邀請。WP5 待決不應卡住 WP6 的 A/B/C 文件與整合；工作包用依賴關係表達，比無條件「依序」清楚。 |

## WP-S 與 WP0 開工判斷

| 工作 | 能否按現描述直接開工／驗收 | 最小前置修正 |
|---|---|---|
| WP-S | **可以做探索；不可照原測試條件宣告完成** | 修正 V01：真正跨 site、SPA/BFCache 不混為新文件 hello、CSP 測實際 UI。保存原始事件表與版本；spike 不確定的結果照實標未驗證。 |
| WP0：CDP 分派、off、optional | **可以先開工** | 採 M01 的 reader／dispatcher 約束；既有回覆路徑不搬到會被 listener 阻塞的佇列。 |
| WP0：共用觀察 | **介面校正後可開工** | V07／V12：分清 legacy rows 回傳與新觀察資料、群組歧義及 canonical rows；加入 Chrome 等價測試。 |
| WP0：safety gate | **已知規則可做，但不能以目前保證驗收整包** | V02／V11：取消「denylist 推出只讀」保證，定義 gate 的輸入／拒絕結果及觀察 metadata；敏感值不可在收集後才由 Python 遮罩。WP3 的整段重試先不依此放行。 |

不必等待 R13 決策才能進行上述工作，也不必先把 WP3–WP5 全部實作才能修正這些契約。此次否決是因 V02–V07 等仍可能產生錯誤動作、漏錄或錯誤示範證據；單純補 M01–M06 的實作細節不足以關閉它們。

VERDICT: CHANGES_REQUIRED
