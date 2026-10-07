# WP-S 技術驗證(spike)結果:錄製的 CDP 行為

日期 2026-09-29。對應設計 `demo-recording.md` v3.1 的 §2.2、§2.3、§3.3、§8 WP-S、§11 I1;驗證動機見 `demo-recording.review-v2.md` V01、V09、V10。
**不進產品程式**:spike 在 `spike/recording/`(`spike.py` 驅動與 Python 端驗證、`recorder.js` 最小 recorder),之後會刪。

## 環境

- Chrome **154.0.8037.58**(macOS,arm64),headless 用 `--headless=new`,headed 為有視窗;兩者各完整跑一輪(同一支腳本)。
- 隔離實例:`--remote-debugging-port=9445`、暫存 `--user-data-dir`、`--host-resolver-rules="MAP a.test 127.0.0.1, MAP b.test 127.0.0.1"`。沒碰 :9333、`~/.kav-fastweb`、`vendor/`。跑完程序已關閉、暫存 profile 已刪。
- fixture:Python `http.server` 兩個 port(P1=18461、P2=18462)。`a.test:P1`、`a.test:P2`(跨 origin 同 site)、`b.test:P1`(跨 site)。伺服器端 Host 記錄:三種都有請求進來,確認解析正確。
- recorder 注入順序照設計 §2.2:createTarget(about:blank) → attach(flatten) → 註冊 listener → Page.enable/Runtime.enable → `Runtime.addBinding(__kfwRec, executionContextName=kfw_rec)` → `addScriptToEvaluateOnNewDocument(worldName=kfw_rec)` → navigate → hello → Python `Runtime.evaluate(contextId)` 呼叫 `__kfwArm(token)` → JS 送 armed。JS 在頁內模擬使用者以 CDP `Input.*`(2 次 mouse click、1 次 keyDown/keyUp、1 次 `insertText`),每個文件預期收到 5 筆(pointerdown、pointerdown、keydown、input、input)。
- 原始資料:`spike/recording/out/results-headless.json`、`results-headed.json`(每步結構化結果)、`out/timelines/<mode>/*.txt`(每步的原始事件序列,含到達順序 `n` 與毫秒)、`out/shots/*.png`(提示列截圖)。以下「事件序列」是這些檔案的摘要。
- 統計基準:hello 相對於導覽動作的延遲,新文件(非 BFCache)各 20 次,兩種模式中位數皆 **7 ms**(範圍 5–28 ms);hello 到 armed 的間隔中位數 8–9 ms(0–16 ms)。

## 各情境

### 1. 初次導覽 a.test:P1(headless/headed 相同)
做法:Page.navigate。事件序列:`Page.frameStartedLoading` → `executionContextsCleared` ×2 → `Page.frameNavigated(type=Navigation)` → `Target.targetInfoChanged` → `executionContextCreated`(主世界 default)→ `executionContextCreated(name=kfw_rec, isolated)` → `Runtime.bindingCalled(hello)` → `domContentEventFired`/`loadEventFired` → `bindingCalled(armed)`。
- hello 時 `readyState=loading`、`document.documentElement` 尚不存在(`earlyAttr="no-documentElement"`)、`hasBody=false`:new-document script 在頁面任何內容之前執行。提示列在 body 出現後由 MutationObserver 掛上。
- 用 `uniqueContextId` 做 `Runtime.evaluate` 也可行(`typeof __kfwArm` = function)。
- 5 筆事件全到、token 相符、seq 1–5 連續。
結論:**可行**。

### 2. reload
`Page.reload`:同樣的序列;新的 kfw_rec context(新 executionContextId 與 uniqueId)、新 hello(`navType=reload`)、需重新 arm;舊文件沒有 `executionContextDestroyed`,只有 `executionContextsCleared`。5/5 事件、seq 連續。**可行**。

### 3. 同 origin 換頁(用真實點擊連結)
新 context、新 hello、isolate 不變(同一 renderer)。**可行**。

### 4. 跨 origin 同 site(a.test:P1 → a.test:P2,連結點擊)
新 context/hello;`Runtime.getIsolateId` 不變(同一 renderer 程序)、target/session/frameId 不變。**可行**。

### 5. 跨 site(a.test → b.test)
連結點擊(5)與 browser 發起的 `Page.navigate`(5b)都測:
- **同一個 target、同一個 session 仍有效**:沒有 `Target.detachedFromTarget`、沒有 `targetDestroyed`;只有 `Target.targetInfoChanged`(url 變、attached=True)。主框架 `frameId` 也不變。
- **換了 renderer 程序**:`Runtime.getIsolateId` 變了(5 與 5b 各變一次);`ps` 看到新增 `--type=renderer` 程序(5 與 5b 各多一個)。
- **executionContextId 會重用**:整個 tab 生命期內 kfw_rec 出現 6 個 context,`id=2` 對應兩個不同的 `uniqueId`(a.test 與 b.test 各一)。兩種模式都重現。裸 `executionContextId` 不可當文件身分(§11 I1 屬實)。
- 新文件 hello/armed 正常,5/5 事件、seq 連續。
結論:**可行**;必須用 `uniqueContextId`(或本地 epoch)識別文件。

### 6. SPA(pushState、hash、history.back)
做法:點頁面按鈕呼叫 `history.pushState`、`location.hash`,再 `history.back()`(回到 fragment)。事件:每次 `Page.frameStartedLoading` → `Target.targetInfoChanged` → `Page.navigatedWithinDocument`(`type=historyApi` 或 `fragment`)→ `frameStoppedLoading`。
- **沒有**新 `executionContextCreated`、**沒有**新 hello;epoch token 不變、seq 接續(1–7 再 8–12),沒有間斷。
結論:**可行**;`navigatedWithinDocument` 即「同文件」訊號。

### 7. BFCache
A(a.test)→ B(b.test 跨 site;另跑同 site a.test:P2)→ `Page.navigateToHistoryEntry` 回 A → 再前進 B。**兩種模式、跨 site 與同 site 都真的從 BFCache 恢復**:
- 證據:`Page.frameNavigated` `type=BackForwardCacheRestore`;主世界 `window.__pageshows == [false, true]`(persisted=true);主世界 `window.__loadId` 恢復前後相同(頁面腳本沒重跑);本 spike 沒收到 `Page.backForwardCacheNotUsed`。
- 恢復時序:`executionContextsCleared` → **重新發出** `executionContextCreated`(kfw_rec 是**同一個 id 與同一個 uniqueId**;主世界則是新 id/新 uniqueId,且新 id 恰好等於別的文件先前用過的 id)→ 舊 JS 的 pageshow(persisted) 送 `hello{restored:true, persisted:true}`(此時 `readyState=complete`、`hasBody=true`、提示列還在、JS 狀態保留)→ **`Page.frameNavigated(BackForwardCacheRestore)` 在 hello 之後才到**。與一般導覽(frameNavigated 先、hello 後)順序相反。
- Python 重新 arm(新 token)後 5/5 事件正確、seq 從 1 起連續。
- 沒有測到「沒進 BFCache」的分支:`backForwardCacheNotUsed` 從未出現,該路徑**未覆蓋**(例如有 `unload` handler、`Cache-Control: no-store` 的頁面沒測)。
- 「已停止的錄製在 BFCache 返回時不得恢復」:teardown 移除所有 listener,理論上成立,但**未實測**。
結論:**可行**(要處理上述順序與 context 重發)。

### 離頁時的訊號(§3.2 pagehide,額外量測)
JS 在 `beforeunload`、`pagehide`、`visibilitychange` 各呼叫 binding。對「離開已 arm 文件」的 13 次導覽(reload、連結、Page.navigate、history 前進後退、跨 site/同 site):
- `beforeunload` binding:**13/13 送達**,且在 `Page.frameStartedLoading` 之前(約 導覽動作後 1–14 ms)。
- `pagehide` binding:**0/13 送達**(JS 端 `send` 沒丟例外、計數器顯示 handler 有執行,BFCache 恢復後也從未補送)。
- `visibilitychange(hidden)`:離頁時 0 送達;BFCache 恢復後,只收到「恢復後 visible」那一筆,且帶著舊 token,被 Python 以 `BAD_TOKEN` 正確丟棄(headless 4/4)。
- 導覽當下被點擊的連結的 `pointerdown` 都先於導覽送達。
結論:binding 呼叫在 `pagehide` 期間**不可靠(本環境 0/13)**;`beforeunload` 可靠但不保證導覽真的發生,也不含導覽後快照。

### 8. CSP 三組(a.test:P1 的專用 handler;headless 與 headed 一致)
| CSP | hello / armed | 5 筆事件 | 提示列可見 | 按鈕可按 | teardown 後 |
|---|---|---|---|---|---|
| `script-src 'none'` | 有 / 有(主世界頁面腳本確實沒執行:`data-early` 缺) | 5/5 | host rect [583,410,157,43]、`elementFromPoint` 命中 host、截圖取樣為預期綠 (0,170,119)(headed 為色彩描述檔偏移的 (78,167,121),肉眼可見) | 真實滑鼠點擊按鈕 → 收到 `ui_click`,且**沒有**額外的一般 pointerdown 事件 | body 子節點 5→4、`connected=false`、之後點擊/打字 0 事件 |
| `style-src 'none'`(頁面 `<style>` 確實被擋:背景變透明) | 有 / 有 | 5/5 | 同上(提示列用 CSSOM `style.setProperty`,不受影響) | 可 | 同上 |
| `require-trusted-types-for 'script'`(頁面 innerHTML 確實被擋) | 有 / 有 | 5/5 | 同上 | 可 | 同上 |

isolated world 內的探測(`__kfwProbe`):
- `script-src 'none'`:`innerHTML`、`eval`、`setAttribute('style')`、`<style>`、constructable stylesheet 全部**可用**(isolated world 不受主世界 script-src 限制)。
- `style-src 'none'`:`setAttribute('style',…)` **無效**、`<style>` 元素**無效**;`style.setProperty`、`style.cssText`、`adoptedStyleSheets` **有效**。→ 提示列必須只用 CSSOM(設計 §3.3 的做法正確,且不能用 `<style>`)。
- Trusted Types:isolated world 內 `innerHTML` **丟 TypeError**(被強制),其餘可用。→ 不用 innerHTML 的規則正確。
結論:三組都**可行**。範圍限制:只測了這三條單一 header 的 CSP 與一個空白頁;沒測 `default-src 'none'`、`frame-src`、多 header 疊加,或網站刻意遮蓋提示列。

### 9. 主世界呼叫 `window.__kfwRec`
`Runtime.evaluate`(不指定 context):`typeof __kfwRec / __kfwArm / __kfwTeardown / __kfwInfo` 全為 `undefined`,`Object.getOwnPropertyNames(window)` 沒有 kfw 相關名稱;呼叫 → `TypeError: ... is not a function`;Python 端 `bindingCalled` 0 筆。另開一個名為 `other` 的 isolated world(`Page.createIsolatedWorld`)同樣看不到 binding;kfw_rec 世界(正對照)兩者皆為 function。主世界自己定義同名假函式只影響主世界,不會通到 binding,kfw_rec 內的 binding 仍是真的。**可行**(binding 只存在於指定名稱的世界)。

### 10. arm 之前的輸入
hello 之後、arm 之前模擬 5 筆輸入:**Python 收到 0 筆**(本 JS 在未 arm 時丟棄並計數);arm 訊息回報 `preArm=5`、`preKinds=[pointerdown,pointerdown,keydown,input,input]`,所以「缺口偵測」可行(不會默默丟)。JS 直到 hello 為止的視窗:導覽到 hello 中位數 7 ms,hello 到 armed 中位數 8–9 ms;**hello 之前**(文件開始到 script 執行)的輸入無法量測(script 尚未存在),視為缺口/未驗證。**現象記錄,結論:丟失但可偵測(限 hello 之後)**。

### 11. 是否需要 `Target.setAutoAttach(waitForDebuggerOnStart)`
- 主框架跨程序導覽(情境 5):沒有新 target,session 沿用;new-document script 在頁面第一段 inline script **之前**執行(所有文件 hello 的 `documentElement` 尚不存在;JS 時戳 < 頁面 inline script 時戳,凡頁面腳本有執行、可比較的新文件皆然(兩種模式各約 17 個),含跨 site、有無 autoAttach)。→ **主框架不需要 autoAttach**。
- 帶 iframe 的頁面:同 site iframe(a.test:P2)在同一 session 也建立 kfw_rec context(`frame_is_main=false`),JS 主框架 guard 使其**不送 hello**(hello 只 1 筆),可行。
- 跨 site iframe(b.test)只有在 autoAttach 開啟時才會出現為獨立 target(`attachedToTarget`,`waitingForDebugger=true`,不呼叫 `runIfWaitingForDebugger` 會卡住;本 spike 有呼叫);沒開 autoAttach 時完全看不到,也無 kfw_rec context。iframe 內操作偵測仍依 §2.3 的盲點與示範一致檢查。
結論:錄製主框架**不需要**;若要偵測 OOPIF 需要 autoAttach 並處理 `waitingForDebugger`,**該用途未驗證**。

## 總表

| # | 情境 | 結論 | 備註 |
|---|---|---|---|
| 1 | 初次導覽 | 可行 | hello 中位 7 ms;script 在頁面內容前 |
| 2 | reload | 可行 | 新 context、新 hello |
| 3 | 同 origin 換頁 | 可行 | 同程序 |
| 4 | 跨 origin 同 site | 可行 | 同程序(isolate 不變) |
| 5 | 跨 site | 可行 | 同 target/session/frameId;換程序;**contextId 重用**(id=2 兩個 uniqueId) |
| 6 | SPA | 可行 | `navigatedWithinDocument`;無新 hello、seq 續號 |
| 7 | BFCache(恢復) | 可行 | `BackForwardCacheRestore`;hello 先於 frameNavigated;同 uniqueId 重發 context |
| 7' | BFCache(未進入的分支) | 未驗證 | 從未觸發 `backForwardCacheNotUsed` |
| 7'' | teardown 後 BFCache 返回不復活 | 未驗證 | 僅理論(listener 已移除) |
| 8a | CSP `script-src 'none'` | 可行 | UI 可見/可按/可 teardown |
| 8b | CSP `style-src 'none'` | 可行 | 只能用 CSSOM;`<style>`、setAttribute 無效 |
| 8c | CSP `require-trusted-types-for 'script'` | 可行 | innerHTML 被擋 |
| 9 | 主世界呼叫 binding | 可行(擋得住) | 主世界與其他 isolated world 都沒有 |
| 10 | arm 前輸入 | 丟失但可偵測 | hello 前的視窗未驗證 |
| 11 | 需要 autoAttach | 主框架不需要 | OOPIF 偵測用途未驗證 |
| 額外 | `pagehide` binding 送達 | **不可行(0/13)** | 見上 |
| 額外 | `beforeunload` binding 送達 | 可行(13/13) | |
| 未覆蓋 | 崩潰/`detachedFromTarget` 重新 attach、IME(`Input.imeSetComposition`)、新分頁、標記模式攔截層(V09)、`unload`/no-store 頁面、Chrome 以外版本 | 未驗證 | 不在本 spike 範圍或未跑 |

headed 與 headless 的差異:**未觀察到**(BFCache 皆真的恢復、isolated world/binding/CSP 行為、事件序列與 seq 皆一致,只有 headed 為 Retina 2x 截圖)。

## 對設計的影響

1. **§2.2 / §3.2 / §11 I1:不可依賴 `pagehide` 同步送出**(0/13)。`pagehide` 一節「同步結束目前的組並送出」不成立。建議改為:(a) 動作組在事件當下就先送一筆「未完成」記錄(pointerdown 先送達的事實已驗證),之後再用更新記錄補齊;(b) 導覽偵測用 `beforeunload`(13/13)當「可能離頁」的提示,而非唯一保證;(c) 離頁前最後一組的「事件後快照」拿不到,規格應改為 `doc_navigated_after: true` 且 `snap` 為空,由 Python 依 `Page.frameNavigated` 補接續,或視為缺口。收束屏障(§2.2)仍以 Python 主動 `__kfwFlush()` 為準,不依賴離頁事件。
2. **§2.2 文件身分**:確認 I1。必須以 `uniqueContextId`(或本地 epoch + `uniqueId`)識別文件;裸 `executionContextId` 已在單一 tab 內重用(跨程序時)。並且 BFCache 恢復時 **kfw_rec 的 uniqueId 與舊文件相同**,所以「uniqueId 不同 = 新文件」不完整:文件世代必須另加 JS 端 `docId` + 每次 hello 由 Python 配新 epoch(spike 的做法:hello 帶 `docId`,Python 每次 hello 換 token)。
3. **§2.2 BFCache 一節**:順序改寫為「`hello{restored}` 可能**早於** `Page.frameNavigated(type=BackForwardCacheRestore)`」;不可用「frameNavigated 後 3 秒內未 arm → gap」的計時起點來假設 hello 在其後。恢復時會重發 `executionContextCreated`(kfw_rec 同 uniqueId)與 `executionContextsCleared`。舊 token 的遲到訊息實測會出現(4 筆 `vis`,皆被 token 檢查丟棄),故「舊 token 的任何資料一律丟棄」保留。
4. **§2.2 失效判斷**:context 消失只有 `executionContextsCleared`,沒有 `executionContextDestroyed`;導覽後 session/target/frameId 不變。「重新 attach 只在 `detachedFromTarget`」的規則與觀察一致(跨 site 沒有 detach);設計不必因跨程序另做 attach。**不需要 autoAttach**(主框架)。
5. **§3.3 提示列**:規則正確且必須嚴守——只用 createElement + textContent + CSSOM `style.setProperty`(在 `style-src 'none'` 下 `<style>`、`setAttribute('style')` 無效;Trusted Types 下 innerHTML 丟錯)。closed shadow root + `composedPath().includes(host)` 排除自家事件有效(按鈕點擊只產生 `ui_click`,沒有一般 pointerdown)。可在 §3.3 加註「isolated world 不受頁面 `script-src` 限制,`eval` 也可用,但不要依賴」。
6. **§2.2 arm/preArm**:JS 在 arm 前計數輸入並在 `armed` 回報(`preArm`、`preKinds`),Python 據此標 `incomplete`,已驗證可行。hello 前的視窗無法偵測,§0 原則 6 的「示範一致檢查」仍要保留。
7. **§2.3 iframe**:同 site iframe 也會建立 kfw_rec context,主框架 guard 使其不送 hello,可行;Python 端應忽略 `frameId != 主框架` 的 kfw_rec context。跨 site iframe 在沒有 autoAttach 時完全不可見,偵測只能靠 §2.3 的 blur/composedPath 啟發式。
8. **§8 WP-S 驗收/整合測試**:`a.test`/`b.test` + host-resolver-rules 有效;之後 WP1 的整合測試可直接沿用該環境與 `uniqueContextId` 檢查。
