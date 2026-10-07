# demo-recording 設計複查

審查對象：`docs/design/demo-recording.md` 草案 v1，2026-09-29。已讀 README、STATE、最新 record、DECISIONS、相關 TRAPS，以及 `kfw/form.py`、`recipes.py`、`cdp.py`、`page.py`、`mcp_server.py` 與現有配方測試。

結論：方向可行，但尚不適合照 WP0–WP4 直接實作。主要阻擋在事件保存與重播語意、安全檢查覆蓋、示範驗證的證據綁定，以及 `pick` 的定位能力。以下是靜態審查與官方協定核對；沒有把尚未實作的功能宣稱為已經過 Chrome 驗證。本次只新增此審查檔，未更動程式、原設計或 flightwake 文件，也未執行產品測試。

嚴重度：**阻擋**＝會破壞核心承諾或需先定義契約才能實作；**應修**＝實作前應補齊的可靠性／驗收缺口；**建議**＝可降低成本或複雜度。

## 1. CDP、事件與錄製生命週期

### R01【阻擋】重新 attach 不能直接在目前的 CDP callback 裡執行

引用：設計 §2.1（83–84 行）、WP1；`kfw/cdp.py:40–69`、`:90–107`；`kfw/page.py:41–51`。

`Browser._read()` 在唯一讀取執行緒同步呼叫 listener；`attach()`／`call()` 又會等同一執行緒接收命令回覆。在 `detachedFromTarget` callback 裡直接 attach、重新註冊 binding，甚至截圖或 stop 清理，都會等到 timeout；callback 丟出的例外也沒有隔離，會讓 reader 結束。這是現有程式可直接推導的問題。

修正：callback 只入佇列，由另一個 worker 序列化 session 修復、停止與存檔；加上 listener 解除註冊、callback 例外隔離與連線中斷時喚醒 pending calls。WP1 必須明列 `kfw/cdp.py`／`page.py` 的工作與測試，而非只新增 `record.py`。

### R02【應修】分清 document、execution context、session、target，不要以 URL 變化決定重連

引用：設計 §1.2、§2.1；`kfw/cdp.py:97–104`。

跨站／跨程序導覽不應被定義成「必然換 session」；`targetInfoChanged` 也不是 session 已失效的證據。無差別重 attach 會重複監聽或重複注入。相反地，僅 discovery 並不保證新 renderer 開始執行前已裝好 recorder。官方協定將 discovery 與 auto-attach 分為不同功能；detach 事件須核對實際 `sessionId`。[CDP Target 定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)

修正：定義狀態機、session 世代、注入成功 ACK、資料缺口旗標；區分正常 context 重建、真正 detach、target 關閉／crash、整條 websocket 斷線。發生無法證明完整性的空窗就標為 incomplete，不能繼續產生可存草稿。先用兩個不同 site 的本機來源驗證目前支援的 Chrome 行為，再決定是否需要受限的 auto-attach；不要為所有分頁啟用暫停。

### R03【阻擋】binding 的 world、啟動順序與資料可信邊界未定義

引用：設計 §1.2（35–37 行）、§2.1、§6 iframe 限制。

未限定 context 的 `addBinding` 會暴露到 target 的各 execution context，且一般 reload 會保留；binding 只接受一個字串，所以應明寫 `JSON.stringify(payload)`。在頁面 main world 暴露 `__kfwRec`，網站可直接呼叫它提交假的 set／mark／完成資料，根本不需經過 `isTrusted` listener。`isTrusted` 不能替 binding payload 背書。[CDP Runtime 定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/js_protocol.json)

修正：使用固定名稱的 isolated world 搭配 `executionContextName`，Python 驗證 context 所屬 frame／session 世代、payload schema、大小與順序。先裝 listener／binding，再裝新文件 script，最後導覽；當前文件 evaluate 也要進同一 world。啟動採 about:blank → 安裝 → 導覽 → ACK 才告訴使用者開始。這能隔離 JS 全域，不能讓網站 DOM 變成可信輸入，仍須本地安全與結果核對。

### R04【阻擋】「欄位變了就吸收 click」會丟失必要動作

引用：設計 §1.1、§2.3（109 行）、§2.5；`kfw/form.py:85–95`。

反例：查詢按鈕的 handler 同時正規化日期並送出請求，依規則 click 被吸收，整個 submit 就不見了。日期 widget 在 `setTimeout`／網路回覆後才設值，capture 當下的快照尚未變，反而留下日曆格子的 click。直接 `.value = ...` 不一定觸發 input/change；只收 trusted input 會漏掉真實操作引起的程式更新。trusted 只描述事件來源，CDP 輸入也可以符合，並非「真人且已完成操作」證明。[DOM 事件定義](https://dom.spec.whatwg.org/#dom-event-istrusted)

此外，readonly 日期欄位即使錄得到最後值，現有 `fill()` 會立即拒絕；自動完成欄位也可能必須選 suggestion 才設定隱藏 ID，讀回顯示文字相同不代表重播等價。

修正：先保留原始操作順序與操作前後快照，轉換時才折疊；吸收只適用於已證明可由現有 setter 重播的 widget，不適用於送出／導覽。定義 settle 上限、離頁前同步 flush、Enter submit、blur、IME／貼上與延遲更新。無法證明可重播時回 unsupported，不要產生看似完整的 fields。

### R05【應修】欄位 diff 缺少初始值、作用範圍與相依順序

引用：設計 §1.1、§2.3（109–110 行）、§3.2；`kfw/form.py:26–39`；`kfw/recipes.py:271–290`。

只存「值變過」的欄位，會漏掉使用者接受的預設／autofill 值；隔天預設日期變了，重播就查錯。以 label 全域取最後值會合併不同頁的同名欄位，也會改變相依下拉選單的語意：例如先選城市 A、選區、改城市 B、再改区，不可只按第一次出現順序填最後值。DOM 替換後 `data-kfw-id` 也不是跨文件身分。

修正：紀錄 document／動作序號與控制項身分，保存提交邊界的有效欄位值；只在同一段、無相依動作的編輯中合併。空 label 或重名欄位應立即標明無法定位。§4 用「沒有 label」主動建議錄製，與 §0.5 共用同一 label 算法不能解決此限制，需改成明確的不支援原因或另立定位能力工作包。

### R06【應修】新分頁改同頁既不完整，也改變示範的語意

引用：設計 §1.2（39–40 行）、§6（201 行）。

capture listener 可以處理部分 anchor 預設導覽，不能普遍改寫 handler 中或非同步呼叫的 `window.open()`；要攔它通常需 patch main-world API，且會改變 window handle、opener、命名視窗與 postMessage 行為。Ctrl/Cmd-click、中鍵、`form target`、`<base target>`、noopener 與 COOP 也不在現有契約內，不能只假設每次都能取得可歸屬的 openerId。

更簡單做法：既然兩階段均不支援新分頁，就不要改寫網站；偵測確定的新視窗需求或錄製分頁離開操作範圍時停止並回 unsupported。不得靜默漏錄後把剩餘 events 轉成成功草稿；無法可靠歸屬的情況需明列限制。

### R07【應修】只聽 frameNavigated 不足，iframe 的「不支援」也尚未可觀測

引用：設計 §1.2、§2.3 類型判斷、§6。

SPA history／hash 導覽須另處理 `Page.navigatedWithinDocument`；新文件 script 本身是在各 frame 建立時執行，不會自動只限主框架。[CDP Page 定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)

修正：JS 加主框架 guard，Python 再以 context/frame 驗證；記錄 reload、返回／前進與 BFCache 恢復後的基線／監聽狀態，避免重複裝 listener。主文件 listener 看不到子 frame 內的操作，單純「不錄 iframe」不等於能回報不支援；必須定義可偵測方式與漏錄時的拒絕條件。同樣要明列網站自身的 open/closed Shadow DOM 控制項不在現有 `document.querySelectorAll` 掃描範圍（`kfw/form.py:27`），不要只討論提示列的 Shadow DOM。

### R08【應修】提示列仍會污染事件；標記模式不能只攔 click

引用：設計 §1.3；`kfw/form.py:27`、`:48–61`；`kfw/page.py:15–18`。

Shadow DOM 可讓目前的 selectors 不深入內部，但 composed click 仍可冒到外層，target 會 retarget 到 host；按「標記結果／完成」可能被記成 click_other。標記如果只在 click 時攔截，網站早已在 pointerdown/mousedown 觸發動作；`stopPropagation` 也不會阻止同一節點剩餘 listener。[DOM 事件傳遞規則](https://dom.spec.whatwg.org/#interface-event)

修正：以 host／composedPath 明確排除自己的 UI；標記模式使用獨立透明攔截層，處理整組 pointer、鍵盤與取消事件，避免把標記變成真操作。新文件早期 `body` 尚不存在，UI 掛載須延後但操作監聽應先裝；處理 body 替換、host 被移除、樣式繼承、全螢幕／top-layer 遮蔽。提示列引起的 DOM mutation 也不應被算作網站操作效果。

### R09【應修】CSP 測試應拆成 binding、UI 建構與樣式三件事

引用：設計 §6（205 行）、WP1。

不應把 CDP evaluate 能執行推成「整個 recorder 不受 CSP 影響」。協定提供 evaluate 的 unsafe-eval bypass 參數；這並非對所有 DOM sink 與 UI 樣式的保證。[CDP Runtime.evaluate 定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/js_protocol.json)

修正：fixture 至少涵蓋 `script-src 'none'`、嚴格 `style-src`、`require-trusted-types-for 'script'`，分别驗證 binding 到達、提示列可見／可按、重載後仍有效。避免用 innerHTML／inline handler 建構 UI；選定實際建構方式後才判定 Trusted Types／style 的影響。不需以全頁 `Page.setBypassCSP` 當預設解法。這是待實測風險，不是判定 addBinding 在 CSP 下不可用。

### R10【應修】stop、逾時、完成按鈕、超量與重啟缺少一致契約

引用：設計 §1.3（50 行）、§2.1–2.2；`kfw/cdp.py:72–80`；`kfw/mcp_server.py:26–27`。

「完成」究竟立即 finalize，還是等下一次 MCP stop？若已移除 `_active`，後續 stop 如何取回資料？idle 自動結束與使用者 stop 競爭時是否存兩次？MCP 工具在 worker thread 執行，只用 dict 的先查後放不能保證同時僅一份錄製。MCP server 重啟也會丟掉記憶體狀態。

修正：定義 active/stopping/completed/discarded/incomplete 狀態、鎖與冪等 stop；完成結果保留供取回。清理須包含所有 listener／timer／observer、new-document script identifier、binding 訂閱與 Browser 連線，而非只移除提示列；`removeBinding` 本身不會刪除頁面上的全域函式。[CDP removeBinding 定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/js_protocol.json)

200 events／50 rows 必須分清儲存限制和回傳摘要限制；若截斷原始證據，需明確 incomplete，不能把前 200 筆當完整流程。另訂總時限、payload 字節上限、落盤方式、recording_id 驗證與保留／刪除策略。持續有事件的錄製目前可以無限存活。

## 2. 安全與既有原則

### R11【阻擋】只擋 click 文字，沒有實現「安全規則在程式裡」

引用：設計 §0.3、§1.5、§3.1；`kfw/form.py:33–35`、`:85–95`；`kfw/recipes.py:271–294`；DECISIONS 2026-09-29「安全與完成判斷放在本地程式」。

錄製轉換器拒絕 sensitive，不代表手寫流程不能填密碼；現有 form.fill 沒有敏感欄位 gate，input[type=password] 仍被當作 text 控制項。steps 的 select/check 也可能觸發動作；pick 與 next_page 實際同樣會點擊，但 §1.5 只明列「每個 click」，沒有保證走共用安全入口。登入按鈕可叫「繼續」，購買可叫「確認」或只有圖示，單靠禁止詞無法證明安全。反之包含比對 `Pay` 也會誤擋 `payment history` 這類只讀查詢。

修正：把安全檢查設在所有實際動作的共用邊界，填值前核對真實 input type／autocomplete／label／表單脈絡；pick/next_page 也必經此入口，不能直接繞到 Input。定義對未知／含糊的交易與登入情境如何停止，並明言文字 denylist 只是有限防線。對錄製中的真人操作另分清「不阻止使用者操作」與「絕不自動重播」；目前『程式拒絕』容易被誤讀為能防止示範當下已發生的付款。

### R12【阻擋】敏感值在 JS 遮罩不足以涵蓋所有離頁管道

引用：設計 §1.4、§1.5、§2.2、§6；`kfw/form.py:35`；DECISIONS 已登入 profile 限制；skill §5 不存帳密個資。

同一敏感值可能出現在 URL query、mark 文字／列、click_other.row_text、頁面回顯、截圖與錯誤訊息；遮住 input.value 不能保證「值不離開頁面」。若使用者已有預填密碼但未修改，只有 diff 的事件也未必會產生 sensitive 事件，與「出現登入表單就 blocked」不一致。

修正：在初始及後續快照做敏感狀態偵測，不只檢查有改過的欄位；明列所有序列化／截圖出口的處置。偵測登入或敏感操作後停止內容收集、只回最小 blocked metadata；若保留截圖就不能承諾原值絕不離頁。JS 判定與 Python safety 要由同一規則資料生成，避免兩份詞表漂移。單純已登入且只讀的頁面仍應可用，不要把「網站有登入連結」誤判成登入流程。

### R13【阻擋】pick 的備選點擊與歧義處理直接違反 §0.4

引用：設計 §0.4、§3.1（159 行）；DECISIONS 2026-09-29「修法取代舊條件、不留備選」。

指定 `click: 查看` 找不到就點第一個連結，是明確的備選找法，可能改點廣告、收藏或交易連結。多列同名時交 Kev 選一個，也與「不唯一 → needs_help」矛盾。語意任務可以交 Kev，但須區分「把語意條件解析成候選」與「對已歧義的實際目標猜一個」；`p >= 0.6` 不能消除定位歧義，更不是安全證明。

修正：刪除第一個連結 fallback；確定列後仍要求列內指定控制項唯一，否則停止。若要允許語意選列，明列為 §0.4 的受限例外、其判斷證據與拒答條件，再由使用者決定是否改原則。不得靠實作悄悄放寬。

### R14【應修】optional 應只跳過缺席，不能跳過歧義

引用：設計 §0.4、§2.3 的 pre、§3.1；`kfw/recipes.py:223–233`、`:260–268`。

現有 `_find_control` 用同一 `None` 表達找不到與不唯一，而 pre 的 optional 兩種都跳過。照用到 steps 會違反原則。把第一個 set 前的「關閉／接受」一律變 optional 也沒有證據：它可能是必要導覽或選擇，不是 cookie 橫幅。

修正：用結構化 not_found／ambiguous 原因，optional 僅允許前者；pre 的 optional 是候選建議，應由實際頁面與試跑驗證。WP0 的「行為不變」與新原則需明確劃界，不能假設共用原函式便已符合。

## 3. 轉換、結果與可存檔證據

### R15【阻擋】示範一致檢查缺少配方版本與示範來源的完整綁定

引用：設計 §1.4、WP2；`kfw/recipes.py:50–52`、`:194–203`、`:409–420`。

§1.4 只要求「已有一筆示範通過」，未說該筆必須屬於現在這份 recipe hash。先讓 A 版以示範值通過，再改 B 版用另一組參數通過，不能據此證明 B 可重播示範。現有 dry-run record 只存 status/reason/evidence/rows_total，不存比較證據。`recorded_from` 是呼叫端可刪的可選欄位，刪掉後仍可沿一般 save 路徑，故目前只是一個自選檢查，不是所宣稱的強制保證。

修正：把示範通過紀錄綁定 recipe_hash、recording 的不可變內容摘要、示範參數／動作值映射、比較器版本與結果；本次 save 核對相同 hash。定義刪除來源、來源不存在、blocked/incomplete、修復換錄製與參數化後重驗的規則。若保留「程式強制來源」承諾，來源關係須由 server 管理的草稿身分帶入，不能只信 recipe 自報；否則應把承諾改成明確有限的 opted-in 檢查。

### R16【應修】示範列與執行列不是同一種資料，動態結果也不一定能逐格相等

引用：設計 §1.3、§1.4、§2.3；`kfw/recipes.py:302–313`、`:334–348`、`:364–376`。

mark.rows 是格子陣列，但引擎經 columns 轉成 dict，且 `null` 欄位會被刪除，不能直接逐格比。錄製上限 50 列、ROWS_JS 上限 200 列、回傳再截 50 列，也會讓「列數相同」失去明確定義。價格、剩餘名額、職缺排序在兩次執行間會變；之後修復若一直要求重現舊錄製，更可能永遠不能存。

修正：保留同一套 canonical raw rows 用於比較，顯示欄名另做投影；保存是否截斷及真實總數。先限制精確示範驗證只支援可重現的任務，動態資料需重新示範或明確、事前宣告的比較規則，不能失敗後自動忽略差異。另定義無 mark、空結果、多次 mark、僅文字／商品詳情等無 rows 情境。現有 detail_extract 單有 expect_text、沒有 product/rows 仍不會 done，不能假設兩種類型涵蓋所有「點那一塊」的結果。

### R17【應修】row_pattern 一次命中示範，不等於可泛化的結果證明

引用：設計 §1.3（49 行）、§2.3–2.4；`kfw/form.py:43–62`；DECISIONS 的 rows.columns 決策。

只有一列時，所有格子都「所有列相同」，會把日期、車次與價格寫死。沒有明確 anchors／欄位邊界的寬 regex，又可能匹配其他列表；現有 ROWS_JS 在全頁挑最大群組，不限使用者標記區域，還要求群組至少 60% 命中。錄製時在局部匹配成功，不保證重播選到同一結果群。第一列全為非數字也可能是資料列，不是表頭；缺表頭就留空、重複表頭被 dict 覆蓋，都不能聲稱欄名已驗證。

修正：錄製與執行共用列抽取／正規化規則；單列、空格子、多行格子、巢狀列表、同形群組及重複表頭需有拒絕或人工補齊契約。欄名未確認的草稿不得標 verified。泛化優先依欄位型態／參數關係，不要自我驗證失敗就無上限放寬；產出的 regex 必須在瀏覽器 JS RegExp 驗證。至少用另一組參數驗證一次，且保留示範值檢查，避免把記住範例當成功。

### R18【阻擋】現有 rows API 不保留 DOM 身分，無法實作列內 pick

引用：設計 §3.1（159 行）、§3.2、WP3；`kfw/form.py:59–62`、`:161–162`。

`form.rows()` 只回格子文字陣列，沒有列 ID 或列內 controls；選出第 N 筆文字後，現有 API 不能安全地定位那一列及其中的「查看」。模型判斷期间列表也可能重新排序。§3.2 又要求 click_other 在「有 mark 的列表頁」轉 pick，但使用者流程只要求最後在詳情頁標記一次，前面的列表可能根本沒有 mark 或候選快照。

修正：先設計一次觀察中產生 row ID、文字、列內 control ID 的共用 API；點前核對同一節點仍連接、內容仍一致且控制項唯一，失效就重新觀察或停止，不能用舊索引。點列表時就捕捉所需候選證據，不要倒推不存在的 mark。較簡單的第一版先只做確定性 steps，延後 pick。

### R19【阻擋】「任何效果」不證明步驟完成，整段重試不能直接套用

引用：設計 §3.1（155、160–162 行）；`kfw/form.py:131–156`；`kfw/recipes.py:321–345`；DECISIONS 的 form_submit 重試及 STATE yellow。

現有 wait_submit_effect 只證明可能有反應：任意請求／DOM mutation 都可命中，甚至 evaluate 例外被轉成 None 後直接視為 navigating。這不能證明點對目標。等待下一頁時可因 analytics 請求過關，隨即把舊頁結果當新頁再收一次。同樣列數的異步替換還會通過只看筆數的 wait_rows（`kfw/form.py:165–177`）。

遇到後段 click 無效果就從頭重跑，會重複前面已成功的加入購物車／其他有狀態動作。現有 DECISIONS 只決定單表單送出重試，而且真實失敗尚未驗證，不能擴張成任意多步驟的通用恢復保證。

修正：每步區分 effect 與可檢查的 postcondition；導航／翻頁要證明預期頁或內容版本已改變。完整重試先限定為明確只讀、可重播的流程並設總預算；不能確認副作用時回 needs_help。最後結果存在也不能掩蓋中途步驟失敗。

### R20【應修】next_page、check 與 steps schema 的語意仍不夠實作

引用：設計 §3.1–3.2；`kfw/recipes.py:138–160`、`:173–180`、`:409–418`。

`max_pages: 3` 是共三頁還是多走三次？到上限但仍有下一頁算 done 還是 partial？尾頁按鈕可能 disabled 而非消失；「下一頁」改名也會被當正常結束。沒有結果去重、循環偵測與每頁 expect_text 規則。錄到點兩次也不足以推論使用者想收集所有頁面。radio 不一定能直接設 false；`value: "{flag}"` 經現有 render 會變字串而不是 boolean。

修正：定義總頁數／總列數／總時間上限、終止證據、部分結果的回傳與存檔資格，並由明確意圖決定是否折成 next_page。schema 必須每步恰有一種操作、值型別正確、拒絕深層未知欄位；目前 `_check_keys` 不是任意深度遞迴，不能直接套用到 pick.rows。也要更新 dry_run 契約：目前 expect_text-only 的 steps 即使 done，因沒 rows/offers/product 仍 passed=false；partial 有資料卻可 passed=true，需明確選擇而非沿用。

## 4. 工作包、測試與較簡單的方案

### R21【應修】目前拆包把最高風險混在 WP1／WP3，驗收太晚

引用：設計 §2.5、§3.3、§5；現有 `tests/test_recipes.py`。

建議順序：先定事件／狀態／安全／比較契約 → 做最小 CDP 注入與換頁 spike → 共用觀察與安全入口 → recorder → converter＋存檔證據 → 確定性 steps → 獨立 pick 與 pagination → skill。WP1 當時尚無 WP2 converter，不能把 start→to_draft→dry_run 當成 WP1 已完成的驗收；WP3 同時包含引擎、語意選列、翻頁、checkbox 與轉換器，失敗時很難定位。

每包測試綠＋pyright 乾淨保留；但 Chrome 全預設 skip 時，綠燈不代表錄製能力經驗證。WP1/WP2/WP3 交付需明確執行 Chrome 整合套件，記錄 Chrome 版本與指令；使用隔離測試 profile／埠，避免污染使用者 Kav 登入狀態。純手寫 events 只能測 converter，測不到最危險的 recorder 因果與掉事件問題。

必要驗收矩陣如下；可分配到上列各包，不必全部塞進最後真站驗收：

| 範圍 | 應觀察到的結果 |
|---|---|
| 初始注入、reload、不同 site 導覽、SPA、返回／前進 | 一次操作恰一組事件；main frame 正確；無 ACK／有缺口不能存 |
| detach callback、callback exception、Chrome 關閉、重複 start/stop | 無 reader 阻塞、資源可清理、重複 stop 可取相同結果 |
| 延遲 widget、readonly、Enter、IME、預設值、相依 select | 必要 submit 不被吸收；不能重播就明確拒絕 |
| CSP/Trusted Types、iframe、Shadow DOM、提示列按鈕 | UI 與網站事件分離；不支援操作不靜默漏錄 |
| 新分頁、Ctrl/Cmd-click、中鍵、window.open | 不改寫網站語意；不完整錄製不可轉可存草稿 |
| 假 binding payload、敏感輸入、URL/mark/截圖出口 | 不信頁面自報；原值不出現在禁止的輸出中 |
| pick/next_page 安全、找不到、重名、DOM 重排 | 不點備選；不重複副作用；不讀取舊頁當新頁 |
| 雙配方 hash、缺來源、改參數、截斷、動態列 | 不借用舊示範通過證據；比較失敗原因可解釋 |
| 第二組參數與錯誤結果的負例 | 能泛化；不把錯表、旧結果或未知欄位當 done |

### R22【應修】真站驗收只量 Kev 呼叫，不能證明「本機模型加速」

引用：設計 §3.3、§5（197 行）；DECISIONS 2026-09-29 核心主張與 Kev 用量決策。

一個語意 pick 任務成功加上 Kev 耗時，只能證明可用與成本，不能證明加速或 `p=0.6` 足夠。應在選定任務前訂成功／拒答標準，再記錄建流程、每次重播的牆鐘時間、雲端 token、本機用量與使用者介入時間，與既有 Claude 建流程／操作方式比較。pick 至少要有多候選、無合適候選、同名候選、低信心與錯選負例；不應為了讓 Kev 出場而把原本可精確匹配的任務變成語意判斷。

### R23【建議】先做「示範輔助寫流程」，把通用工作流能力拆開

引用：設計 §0 目標、§2、§3、§4。

最小可交付版本可以只記單主分頁的初始／提交快照、按鈕文字、結果標記與完整性狀態；輸出可審查草稿，由 Claude 參數化後沿現有 dry_run→確認→save。先明列只支援可直接填寫的原生欄位，遇新分頁、readonly widget、無 label、iframe 就拒絕。這仍然解決「Claude 猜錯頁面」的一部分，不必同時承諾自動推導任意 steps、row regex 與語意 pick。

第二階段先交付手寫、確定性的 click/fill/select/wait/result steps；錄製到 steps、pick、next_page 各自後加。若精確示範比對暫只支援穩定表格，要把適用範圍寫清楚，保留程式核對與使用者確認，不以模糊比對取代完成證據。

### R24【應修】修復流程的確認與 compare_to 介面要和既有約定對齊

引用：設計 §0.2、§2.2、§4（184 行）；DECISIONS 2026-09-29「只有建立時確認、修復直接修好再回報」。

§0 把所有錄製都寫成「試跑→使用者確認→存檔」，但 §4 又包含修復錄製；若修復也強制再問結果，會違反既有決策。請區分「邀請使用者花時間示範需先問」與「修復後是否再確認」，後者依目前決策不用再問。`compare_to` 也未出現在 §2.2 工具簽名／WP1，需列入正式介面與工作包；差異不能只比 label／按鈕，還要包含步驟增減、值、順序與結果契約，否則無法修復網站新增一步的情況。

VERDICT: CHANGES_REQUIRED
