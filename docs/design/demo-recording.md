# 設計:使用者示範一次 → 流程(錄製,三階段)

狀態:**v3.2**(2026-09-29):v3.1 經 Codex 核准(`demo-recording.review-v3.1.md`),v3.2 只依 WP-S spike 實測(`demo-recording.spike.md`)修 §2.2、§3.2。v1 → Codex 複查 R01–R24(`demo-recording.review.md`);v2 → 複查 V01–V12、M01–M06(`demo-recording.review-v2.md`)。
本版逐條處理,對照表在第 10 節。分工:設計與驗收 Claude(Opus);實作 Sonnet 子 agent,依第 8 節工作包。

## 0. 目標與原則

目標:Claude 寫不出流程(或寫錯兩次)時,讓不懂程式的使用者在 Kav 的 Chrome 裡**親手做一次**,Kav 錄成**可審查的草稿**,
Claude 參數化後走現有的「試跑 → 程式核對 → 確認 → 存檔」;另外新增能表達多頁、多步驟的確定性流程類型 `steps`。

原則(違反任何一條都算設計錯誤):

1. **流程是資料,不是程式。**
2. **完成由程式證明。** 每一步都要有「由假變真」的可檢查轉移;「有反應」不等於「做對了」。
3. **安全規則在程式裡,在所有實際動作的共用入口(`gate`)。** gate 拒絕**已知禁止**與**無法判定**的動作;它是有限防線,**不證明流程沒有副作用**,文件與回報都不得宣稱「已證明只讀」。
4. **一個步驟一個目標,不留備選。** `not_found` / `ambiguous` 都停;`optional` 只跳過 `not_found`。唯一例外:`pick`(第 6.4 節,使用者 2026-09-29 同意)。
5. **錄製與執行用同一套觀察程式**(欄位快照、label、列/群組抽取、正規化)。
6. **完整性偵測是盡力而為;正確性由重播把關。** 錄製能偵測到的缺口(沒 ACK、新分頁、序號不連續、iframe/shadow 互動跡象)→ `incomplete`。
   偵測不到的漏錄,由**必做的示範一致檢查**攔下:用示範值、在**乾淨的起始狀態**(7.4 的隔離瀏覽器環境,不帶示範留下的 cookie/storage)重播,結果必須和使用者標記的一模一樣,否則不能存。
   示範一致只證明「在乾淨起始狀態下,重播草稿得到同樣結果」;需要示範當下 profile 狀態(登入、網站記住的選項)才能重現的任務,錄製 v1 不支援。
7. **錄製不阻止使用者的真人操作,但絕不自動重播被禁止的動作。**
8. **動作三級**(DECISIONS 2026-09-29):永遠禁止(付款、結帳、下單、登入、註冊、填密碼/卡號等);**使用者明確要求才做**(加入購物車、收藏等改狀態但不涉付款,配方該步必須標 `stateful: true`,**而且**每次執行的呼叫必須帶 `allow_stateful: true`——第 4 節);其他照常。

## 1. 範圍

| 版本 | 內容 | 明確不支援(回報原因,不靜默) |
|---|---|---|
| **A. 示範輔助寫流程** | 單一主分頁;原生 `select`、原生 text 類 `input`/`textarea`;button/link 點擊送出;結果標記;產出 `form_submit` / `detail_extract` 草稿 | 新分頁;iframe 內操作;網站自訂元件(自動完成需選建議、隱藏值);readonly 欄位被元件改值;在欄位按 Enter 送出;無 label/重名欄位;checkbox/radio;示範中出現改狀態點擊;需要示範 profile 狀態才能重現的任務 |
| **B. 確定性 `steps`** | click / fill / select / check / wait,每個 click 有轉移證明;select 只做 exact/contains(**不用 Kev**) | 語意選列、翻頁 |
| **C. `next_page`** | 明確頁數上限、明確尾頁證據、指紋去重 | — |
| **D. `pick`** | 第 6.4 節受限例外 | — |
| **E. skill** | 建立/修復用錄製;`compare_to` | — |

## 2. CDP 層

### 2.1 `kfw/cdp.py`(R01、M01)

- **命令回覆仍由 reader 直接喚醒 slot**(不排隊);只有**事件**放進 `queue.Queue`,由一條 dispatcher 執行緒呼叫 listener。
- listener 可以呼叫 `send()`(回覆由 reader 處理,不會死鎖),但**不可等待**只能由 dispatcher 處理的下一個事件;長工作(stop、落盤)交給錄製自己的 worker 執行緒。
- listener 例外被捕捉並記錄。
- 斷線:reader 結束時標 `disconnected`,喚醒所有 pending(`CDPError("disconnected")`);之後的 `send()` 立即失敗;通知 `on_disconnect` 訂閱者。
  websocket 單次 `recv` 逾時**不等於**斷線(錄製期間可能長時間安靜):reader 對 timeout 繼續等待,只有連線關閉/錯誤才算斷線。
- 新增 `off(session_id, method, callback)`。現有行為與測試不變。

### 2.2 錄製分頁生命週期(R02、R03、R10、V10、M02)

啟動(順序固定,任何一步失敗 → `incomplete: start_failed`):
1. 記下自身 target ID;`Target.setDiscoverTargets(true)`,**忽略啟用當下已存在的 targets**,只處理之後 `type == "page"` 的 `targetCreated`。
2. `Target.createTarget(url="about:blank", background=False)` → attach(flatten)→ **先註冊所有 listener** → `Page.enable`、`Runtime.enable`。
3. `Runtime.addBinding(name="__kfwRec", executionContextName="kfw_rec")`;`Page.addScriptToEvaluateOnNewDocument(source=RECORDER_JS, worldName="kfw_rec")`(保存 identifier)。
4. `Page.navigate(url)`;等到 `kfw_rec` context 送 `hello` 且 Python 回送 `arm(epoch_token)`、JS 回 `armed` → 狀態 `recording`,工具才回傳。

**文件身分與完整性(V10)**:
- **文件世代(epoch)由 Python 配發**(spike 結論 2):裸 `executionContextId` 會跨程序重用,`uniqueContextId` 在 BFCache 恢復時又與舊文件相同,兩者都不能單獨當文件 ID。Python 每收到一次 `hello` 就配一個新 epoch 與 token;context 只用來驗證來源(`uniqueContextId` + `auxData.frameId` 是主框架 + `name == "kfw_rec"`)。**非主框架的 `kfw_rec` context 一律忽略**(同 site iframe 也會建立該世界)。
- 每個文件:Python 在 `hello` 後以 `Runtime.evaluate(contextId=…)` 呼叫 `__kfwArm(token)`;JS 只有持有有效 token 才送資料,每筆 payload 帶 `token` 與**從 1 起連續**的 `seq`。
- Python 對每筆 `Runtime.bindingCalled` 驗證:`executionContextId` 是已知且未失效的文件、`token` 相符、`seq` 連續、payload 為 `JSON.stringify` 的字串且 ≤ 64KB、schema 正確。任一不符 → 丟棄並標 `incomplete: bad_payload` 或 `seq_gap`。
- 缺口計時:以「主框架開始載入新文件」(`Page.frameStartedLoading` / `frameNavigated`,取先到者)或 `hello{restored}` 為起點,3 秒內沒完成 arm → `incomplete: gap`。`Page.navigatedWithinDocument` = 同文件(SPA),不換 epoch、不重送 hello(spike 已驗證)。
- arm 前的輸入:JS 計數(`pre_arm_inputs`)隨 `armed` 回報,>0 → `incomplete: pre_arm_input`(spike 已驗證可偵測;hello 之前的極短視窗偵測不到,由示範一致檢查把關)。
- **BFCache**(spike 結論 3):恢復時 `hello{restored}` **早於** `Page.frameNavigated(BackForwardCacheRestore)`,且會重發 `executionContextCreated`;舊 token 的遲到訊息真的會出現。規則:`pageshow(persisted)` 時 JS 先作廢舊 token、送 `hello{restored}`;Python 配新 epoch 重新 arm;舊 token 的資料一律丟棄。已結束的錄製(teardown 後)在 BFCache 返回時不得恢復:teardown 會設永久停用旗標,`pageshow` 檢查旗標(spike 未驗證,WP1 必測)。
- 文件失效訊號只有 `Runtime.executionContextsCleared`(沒有 `executionContextDestroyed`);跨 site 導覽不會 detach,session 沿用。
- **收束屏障**:stop / 使用者按「完成」/ 逾時,都先對目前文件 evaluate `__kfwFlush()`:JS 結束待定動作組、送出最後快照,回傳 `{last_seq}`;
  Python 確認已收到到 `last_seq` 的所有資料、所有快照引用可解析、日誌已 fsync 落盤,才寫 `completed`。任一不成立 → `incomplete: unflushed`。
  目前文件已消失(使用者關分頁)→ `incomplete: page_closed`。
- 重新 attach(只在 `Target.detachedFromTarget` 且 sessionId 相符時):由錄製 worker 序列化執行;重新 attach **不會**對已存在的文件重跑 new-document script, 主框架**不需要** `Target.setAutoAttach`(spike 結論 4)。
  所以重新 attach 後目前文件視為缺口 → `incomplete: reattached`(保守)。錄製分頁內的 CDP 呼叫一律經錄製 worker,不走 `Tab.call` 的自動重新 attach。
- 狀態:`starting → recording → stopping → completed | incomplete | discarded`。`blocked` 是 `incomplete` 的 `reason`,不是獨立狀態。
  server 重啟後,磁碟上沒有 `completed`/`incomplete` 終態紀錄的錄製目錄一律視為 `incomplete: server_restarted`。
- 時限:無事件 15 分鐘 → 走收束屏障後 `completed`;總時長 30 分鐘 → 收束後 `incomplete: too_long`。
- 清理:`removeScriptToEvaluateOnNewDocument`、`removeBinding`、對目前文件 `__kfwTeardown()`(移除 listener/observer/timer/UI host、token 作廢)、`off()`、關閉連線;分頁留給使用者。

### 2.3 新分頁、iframe、Shadow DOM(R06、R07、V03)

偵測是**盡力而為**(原則 6),偵測到就 `incomplete`,偵測不到的由示範一致檢查攔下:
- 新分頁:discovery 看到之後建立的 `page` target 且 `openerId` = 錄製分頁,或錄製期間出現任何無法歸屬的新 page target → `incomplete: new_tab`(寧可誤殺)。
  JS 偵測到帶 Cmd/Ctrl/Shift/中鍵的 anchor 點擊 → 同樣回報。
- iframe:主框架監聽 `window` 的 `blur`,若 `document.activeElement` 是 `IFRAME`/`FRAME` → `incomplete: iframe_interaction`;
  另外 `pointerdown` 的 `composedPath()[0]` 是 `IFRAME` 也算。已知盲點:iframe 內不可聚焦區域的點擊可能偵測不到。
- 網站的 Shadow DOM:`composedPath()[0]` 是**自訂元素**(tag 含 `-`)或擁有 `shadowRoot` 的元素,且事件後快照沒有對應的原生欄位變化 → `incomplete: custom_element_interaction`。
  已知盲點:closed shadow root 內的控制項從外面看只是 host,可能與一般元素無法區分。
- 這些盲點在「示範一致檢查」下的後果是:重播缺了那一步 → 結果不一致 → 不能存,回報「這個網站有 Kav 錄不到的操作」。

## 3. 錄製 JS(`kfw/record.py` 的 `RECORDER_JS`)

### 3.1 共用觀察(原則 5、V07、V12)

`kfw/form.py` 抽出共用 JS 模組 `OBSERVE_JS`,提供:
- `snapshot()`:和現在 `CONTROLS_JS` 相同的欄位清單,另加 `name`、`autocomplete`、`form_id`(所屬 form 的穩定標記)、`form_has_sensitive`、`sensitive`(布林,由規則在頁內判定)、`native`(原生 select/input/textarea 為 true)。
  **敏感欄位的 `value` 在 JS 端就不讀取**,快照中只有 `sensitive: true` 與 `has_value: bool`(V11)。
- `groups(root, pattern|null)`:回傳**所有**符合條件的重複列群組 `[{group_id, rows:[{row_id, cells[], text, controls[]}], total}]`(`data-kfw-row`/`data-kfw-group` 寫在 DOM,同一次觀察內有效)。
- `rows(pattern, minRows)`(legacy):內部改用 `groups()` 選最佳群組,**回傳形狀與現在完全相同**;另提供 `rows_detail()` 回傳所選群組、其他同樣合格的群組數(歧義資訊)。
- `CONTROLS_JS`、`ROWS_JS` 改由它組成,現有 Python 介面不變。

### 3.2 動作組(V04)

錄製 JS 把使用者輸入分成**動作組**,每組一筆紀錄;值的變化由**相鄰兩個已提交快照**的差異得出,不在 capture 當下拍 before:

- 動作組的開始:`pointerdown`、`keydown`(非修飾鍵)、`beforeinput`、`paste`、`compositionstart`(isTrusted、capture 階段)。
  結束:沒有新輸入且欄位穩定(快照連續兩次相同,間隔 150ms,上限 1500ms),或下一個動作組開始。
- 同一組內的 pointerdown→click、keydown→input→change、compositionstart…compositionend、paste→input 都屬於同一組,不重複計數。
- 組結束時拍一次**已提交快照**。紀錄內容:
  `{seq, token, gid, kind: pointer|keyboard|text_input|paste|ime, target:{tag, native, in_controls, label, text(≤80), is_button_like, custom_element, iframe}, keys: ["Enter"...](只記 Enter/Escape/Tab), prev_snap, snap, doc_navigated_after: bool}`
- **離頁不能靠 `pagehide` 送資料**(TRAPS `pagehide-binding-call-not-delivered`,spike 0/13):動作組**開始當下**先送一筆 `group_open{gid, kind, target, prev_snap}`,結束時再送 `group_close{gid, snap}`;`beforeunload` 時盡力送 `group_close`(spike 13/13 送達,但只當提示)。
  Python 端:一個 `group_open` 之後文件就換了、沒收到 `group_close` → 這組的事件後快照為空;若它是 button/link 點擊,視為「送出/導覽」完成(沒有值變化可遺漏);若是欄位輸入,標 `incomplete: unclosed_input_group`。
- `baseline`:arm 後第一個穩定快照。
- 快照以內容 hash 去重,日誌引用 id。

### 3.3 提示列與標記(R08、R09、V09、M04)

- 以 `document.createElement` + `textContent` + CSSOM(`element.style`)建立,放在 closed shadow root;不用 innerHTML、`<style>`、inline handler。
- 事件監聽在注入當下安裝;UI 在 `document.body` 存在後掛上(注入時若 `DOMContentLoaded` 已發生就立即掛);`MutationObserver` 在 host 被移除時重掛;teardown 旗標優先於重掛。
- 我方 UI 的事件以 `composedPath()` 含 host 排除,不形成動作組。
- **標記只從提示列按鈕進入(取消 Alt 捷徑)**:進入時先 `blur()` 目前焦點元素,蓋上全頁透明攔截層並讓它取得焦點;攔截層在 capture 階段吞掉 pointer/mouse/click/key/wheel 事件;
  移動時 `elementsFromPoint` 取下方元素畫外框;點擊 → `mark`;Esc → 取消並恢復原焦點。契約只保證「進入標記模式之後」網站收不到事件。
- `mark`:標記元素正規化文字(≤2000 字,非空)、`groups(元素, null)` 在元素內的最佳群組(canonical raw cells、`total`、是否 `truncated`(>200 列))、是否有 `th` 表頭、該群組的指紋。
  另外**在標記當下**用 `groups(document, null)` 找出全頁與它同簽名的其他群組數,供 live 驗證用(6.2)。
- 「完成」按鈕 → `done` → Python 走收束屏障。

## 4. 安全(`kfw/safety.py` + `kfw/safety_rules.json`,R11、R12、V02、V11、M03)

- 規則只有一份 JSON(禁止詞、改狀態詞、敏感欄位詞、`autocomplete` 清單、結帳類網址片段)。Python 讀檔;JS 以注入常數取得。**同一批測試輸入在 Python 與 JS 兩邊都要得到相同判定**(M03)。
- 比對:中文用正規化後的包含;英文**保留詞界**再比(`\bpay\b`、`\bcheckout\b`),不能先把空白去掉(`Pay now` 不可變成 `paynow`)。

**`gate(action, target, page_ctx) -> Allow | Deny(reason)`**,所有引擎的每個實際動作(fill、select、check、click、next_page、pick)在**解析出實際節點之後、派發輸入之前**呼叫;
`target` 是當下重新讀取的節點資訊(文字、`type`、`autocomplete`、`name`、`form_has_sensitive`、`sensitive`),不是舊快照。

| 判定 | 規則 |
|---|---|
| 永遠拒絕 | fill/select/check 到敏感欄位;click 文字命中禁止詞;click 的按鈕所屬 form 含敏感欄位;無文字按鈕位於結帳類網址 |
| 需 `stateful: true` 且本次呼叫 `allow_stateful: true` | click 文字命中改狀態詞(加入購物車、收藏、訂閱、預約、刪除、送出申請…);配方該步沒標,或本次執行沒有 `allow_stateful` → 拒絕(輸入派發 0 次) |
| 無法判定 → 拒絕 | 無文字、無 aria-label 的按鈕;目標節點資訊讀不到 |
| 其他 | 允許(**不代表已證明無副作用**) |

- **授權(B1)**:`run_recipe` / `dry_run` 新增參數 `allow_stateful`(預設 false)。Claude 只在使用者**明確要求過這個改狀態動作**時才傳 true:
  使用者在本次對話中要求,或這個流程是應使用者要求建立、而使用者現在點名要跑它。配方上的 `stateful` 只是標示,**不構成授權**;轉換器產生的 `stateful` 只是候選。
  `dry_run` 也是真實執行,同樣受此限制。
- **`form_submit` 不支援 stateful(B2)**:`validate()` 拒絕 `form_submit` 的 pre/submit 帶 `stateful`,執行時 gate 對改狀態詞一律拒絕;改狀態流程只能用 `steps`(不重跑)。
  因此 `form_submit` 維持現有「送出沒反應重跑一次」(只讀,DECISIONS 既有決策,不擴張)。**`steps` 一律不整段重跑**;失敗直接 `needs_help`(V02)。
- **錄製端**:每個快照(含 baseline)若出現 `sensitive && has_value`,或使用者聚焦敏感欄位 → 錄製立即結束收集,`incomplete: blocked`;
  **原子收尾**:刪除該錄製的日誌、快照、暫存檔,只留 tombstone `{state:"incomplete", reason:"blocked", origin}`;不截圖。
- **其他出口(誠實界定)**:網址 query、頁面回顯文字、mark 文字不做敏感偵測。錄製檔只存在本機 `~/.kav-fastweb/recordings/`,回傳給 Claude 的只有摘要;文件與 skill 明寫這個限制,並請使用者在錄製前先登入、錄製中不要輸入個資。

## 5. 流程格式與引擎共通

### 5.1 `_find_control` 結構化(R14)

回傳 `(control, None)` 或 `(None, {"why": "not_found"|"ambiguous", "candidates": n})`;`optional` 只跳 `not_found`。這改變現有 `pre` 行為,記入 DECISIONS。

### 5.2 結果列群組歧義(V07)

引擎用 `rows_detail()`:若除了選中的群組外,還有其他**同樣滿足 pattern 與 min_rows** 的群組 → `needs_help: result_ambiguous`(不猜哪一張表)。
這對所有類型生效;現有 `thsr-timetable`、`bot-fx-rates` 需在 WP0 以 Chrome fixture 與真站各驗一次不受影響。

### 5.3 `columns` 驗證

`validate()` 拒絕重複的非空欄名(否則 `label_rows` 的 dict 會覆蓋)。

## 6. `steps`、`next_page`、`pick`

### 6.1 `steps` 格式(B 版)

```json
{
  "type": "steps",
  "url": "https://example.com/",
  "steps": [
    {"click": "不同意", "optional": true, "then": {"gone": "不同意"}},
    {"select": "出發站", "value": "{from}"},
    {"fill": "出發日期", "value": "{date}"},
    {"check": "只看直達車", "value": true},
    {"click": "查詢", "then": {"text": "{date}"}},
    {"click": "加入追蹤", "stateful": true, "then": {"text": "已加入"}}
  ],
  "result": {"rows": {"pattern": "...", "min_rows": 1, "columns": ["..."]}, "expect_text": ["{date}"]}
}
```

- 每步**恰一種**操作鍵:`click` | `fill` | `select` | `check` | `wait` | `next_page` | `pick`。允許的附加鍵:`optional`(僅 click)、`then`(click 必填)、`stateful`(僅 click)。schema 遞迴檢查,未知鍵拒絕。
- `fill`/`select`:讀回核對;`select` 只做 exact → contains,**不叫 Kev**(不唯一 → ambiguous)。
- `check`:`value` 必須是 JSON boolean 字面值;radio 只能 `true`;讀回 `checked`。
- `click.then`(V08)——每種都是**轉移**:點擊前先評估一次,若已為真 → `needs_help: then_already_true`(配方要換一個會改變的條件);點擊後在 cap(10 秒)內變真才算完成:
  - `{"text": "..."}` 頁面文字出現(非空字串)
  - `{"gone": "..."}` 點擊前以該文字**唯一**找到的 button/link,點擊後 `not_found`(變成 ambiguous 不算)
  - `{"url_contains": "..."}`、`{"field": "label"}` 同樣要求點擊前為假
  - `{"rows": true}` 出現符合 `result.rows.pattern` 的群組,且其指紋與點擊前不同、連續兩次觀察相同(穩定,不接受空列)
  - 文件換了(新的主框架導覽)**不**自動算成立,仍要條件變真
- `wait`:`{"wait": {"text": "..."}}` 純狀態等待(不要求之前為假),cap 10 秒。
- 任一步失敗 → `needs_help: step_failed`,附 `step_index`、該步內容、原因、截圖;**不整段重跑**;最後頁面上碰巧有結果也不算 done。
- `dry_run`:`steps` 只有 `status == "done"` 才通過。

### 6.2 `next_page`(C 版,V08)

```json
{"next_page": {"click": "下一頁", "max_pages": 3, "end": "disabled"}}
```
- 只能是最後一步;`max_pages` = 總頁數(含第一頁),1–10。
- `end`:尾頁證據,由 Claude 在試跑時觀察後明寫:`"disabled"`(按鈕仍在但 `disabled`/`aria-disabled=true`)或 `"absent"`(按鈕消失)。
- 每頁:等結果群組穩定且非空 → 記指紋 → 若指紋已在**已訪集合**中 → 停止,`partial: loop_detected` → 否則收集(以正規化文字去重)→ 檢查尾頁證據:符合 `end` → `done`;
  `end: "disabled"` 卻 not_found,或 `end: "absent"` 卻 disabled → `needs_help: end_mismatch` → gate → 點 → then 固定為 `{"rows": true}`。
- 到 `max_pages` 仍非尾頁 → `done` 並回傳 `more_pages: true`,回報文字必須說「已收集前 N 頁,還有更多」,不可說全部。
- 每頁都要滿足 `expect_text`(若有)。

### 6.3 錄製轉 `steps`

A 版規則(第 7 節)以外的形狀在 B 版轉成 `steps`:每次 button/link 點擊成一個 click 步驟,`then` 由**點擊後的已提交快照**推得候選(新出現的欄位 label、新出現的顯著文字、群組指紋變化),
並列入 warnings 讓 Claude 挑選;轉換器不自動決定 `then`。錄到改狀態詞的點擊 → **錄製 v1 不支援**(`unsupported: stateful_in_demo`):示範中做過不等於要求 Kav 自動做,而示範一致檢查與第二組試跑都會真的執行它。改狀態流程由使用者明確要求後,Claude 手寫 `steps`。
連續點同一文字按鈕且每次結果群組指紋改變 → 建議 `next_page`,`end` 留空由 Claude 填。

### 6.4 `pick`(D 版,受限例外,M05)

- 只能由配方明寫;候選 = 一次 `groups()` 觀察中符合 pattern 的單一群組(群組歧義 → needs_help)。
- 先 exact → contains(對列文字),唯一則選;零列 → `needs_help: pick_no_candidate`。
- 多列才問 Kev:以**穩定候選 ID**(`c1…cn`)為選項,另加 `none`(都不是),需要**完整機率分佈**(`Judge.choice` 擴充回傳全部機率,不以列文字當 dict key);
  最高 p ≥ 0.8 且與第二名差 ≥ 0.3 才接受;`none` 或未達門檻 → `needs_help: pick_uncertain`,附候選與機率。
- 選定列內找文字為 `click` 的控制項,必須唯一,否則 needs_help;**不點第一個連結**。點之前核對 `data-kfw-row` 節點仍連接、文字未變、觀察世代未變,否則重新觀察一次,再不一致就停止。
- 每次選擇的證據寫進步驟紀錄。驗收:無合適候選、同名候選、低信心、列表重排的負例;並記錄與 Claude 直接操作對照的牆鐘、雲端 token、Kev 用量、人介入次數(R22)。門檻是初值,要用驗收資料檢驗,不是已校準的保證。

## 7. 錄製 → 草稿 → 可存檔

### 7.1 MCP 工具

| 工具 | 說明 |
|---|---|
| `start_recording(url)` | armed 後回傳 `{recording_id, state, tell_user}` |
| `stop_recording(recording_id, discard=false, compare_to=null)` | 冪等(見下);回傳 `{state, reason?, draft?, param_candidates, warnings, demo, live_checks, screenshot?, diff?}` |

- `stop_recording` 的順序:收束屏障 → **live 驗證**(頁面仍在時,對目前文件執行 7.3 的群組檢查,結果寫入 `live_checks`)→ 截圖 → teardown → `to_draft`。
- 冪等:`completed`/`incomplete` 的重複 stop 回同一份結果(從磁碟讀);`discard` 後回 tombstone `{state:"discarded"}`,不承諾保留內容。
- 磁碟:`~/.kav-fastweb/recordings/<id>/`(`log.jsonl`、`snapshots/`、`meta.json` 含內容 SHA-256 digest 與終態);上限 5000 筆 / 5MB,超過 → `incomplete: truncated`。
  `recording_id` 固定 12 位 hex,路徑由 server 組。保留 30 天;**已存流程的執行(`run_recipe`)永不依賴錄製目錄**;只有 `save_recipe` 對 `recorded_from` 配方需要來源存在,過期就請使用者重錄。
- `compare_to=<recipe>`:`diff` 比較錄到的動作序列(類型、目標、值、順序)與結果契約,和既有配方的差異(新增/刪除/改名/改值/順序/結果欄位)。

### 7.2 轉換器 `to_draft(log, snapshots, live_checks) -> {state, draft|None, unsupported?, param_candidates, warnings}`(純函式,不碰瀏覽器)

1. 拒絕:終態不是 `completed`;沒有 `mark`(多個 mark 取最後一個並 warning)。
2. 依文件 ID 切段;以動作組為單位,比較 `prev_snap` → `snap` 的欄位差異:
   - 目標是**原生欄位本身**的 `text_input`/`paste`/`ime`/`keyboard` 組 → 該欄位的值變化記為 `set`。
   - 目標是原生 `select` 的組 → `set`。
   - 目標是 button/link(`is_button_like`)→ `click`,**永不吸收**;同組內網站順帶改的欄位值不記(那是網站自己的正規化)。
   - 目標**不是**欄位也不是 button/link,但造成某原生欄位值改變(日期選擇器格子)→ 吸收為該欄位的 `set`,並標 `via_widget: true`。
     這是**假設**,由示範一致檢查驗證(用 fill 直接填值能否重現同樣結果);不一致 → 回報 `unsupported: widget_value_not_replayable`。
   - readonly 欄位被改值 → `unsupported: readonly_widget`。自訂元素/非原生目標改值 → `unsupported: custom_widget`。
   - 欄位內 Enter 後文件導覽或結果出現 → `unsupported: enter_submit`(請改按畫面上的按鈕重錄)。
3. **提交邊界的有效值**(V05):對 A 版的送出點擊,取點擊前一刻的已提交快照,**所有**原生、可見、非敏感、有唯一 label 且值非空的欄位,都以其**有效值**寫入 `fields`
   (使用者沒改的預設值也寫,標 `from_default: true` 在 param_candidates,讓 Claude 決定是否參數化)。
   若某欄位的有效值 ≠ 使用者對它最後一次 `set` 的值(網站重設了它,例:換城市後區被清空)→ `unsupported: dependent_reset`(需要 steps 表達先後,A 版不支援)。
   `fields` 順序:沒被使用者改過的在前(DOM 順序),改過的依**最後一次編輯**的順序在後。
4. 類型:只有導覽 + mark → `detail_extract`;單一文件內 set + 一次 button/link 點擊 + mark → `form_submit`;其他 → `steps`(B 版)或 `unsupported: needs_steps_type`(A 版)。
5. `pre`:第一個 set 之前的 button/link 點擊 → 建議 `{"click": text, "optional": true}` 並 warning「需試跑確認可省略」。
6. 值一律寫示範原值;`param_candidates`:`[{label, value, suggested_name, from_default}]`。
7. 結果:
   - 支援的標記結果只有兩種:**非空表格群組**(比較器 `rows-exact-v1`)或**非空文字塊**(`text-contains-v1`,標記文字 ≤2000 字)。其他 → `unsupported: result_kind`。
   - `rows.columns`:只有 `th` 表頭、欄數吻合、無重複時自動填;否則留空,Claude 必須填。
   - `rows.pattern` 候選由 `row_pattern(rows)`:標記列 < 2 → 不產生,`warnings: single_row`;逐格泛化(全相同照抄、時間/日期/數字形狀、其他 `\S(?:.*?\S)?`);
     轉換器**只產生候選**,是否專一由 7.3 的 live 檢查或之後的 dry_run 決定。
   - `expect_text`:示範值中出現在標記文字裡的 → 建議(以參數形式)。

### 7.3 live 驗證(stop 時,頁面仍在)

對候選 pattern 用 `groups(document, pattern)`:**命中的群組必須恰好一個,且它的指紋等於標記群組的指紋**(不是只比列數)。
不成立 → `live_checks.pattern_specific: false`,warning 給 Claude 手寫。頁面已不在 → `live_checks: pending`,由 dry_run 的群組歧義檢查(5.2)與示範一致檢查把關。

### 7.4 可存檔的證據(opt-in,誠實界定;R15、R16、V06)

- 錄製產生的配方帶 `recorded_from: <recording_id>`。這是**選擇加入的檢查**:skill 規定保留;server 無法阻止手寫配方不帶它。
- **乾淨起始狀態(B3)**:對 `recorded_from` 配方,`dry_run` 一律在新的隔離瀏覽器環境執行(`Target.createBrowserContext` 建立、跑完 `disposeBrowserContext`),
  沒有示範留下的 cookie、localStorage、登入狀態。引擎的 `ObservedTab.open` 增加可選的 `browser_context_id`。
  在隔離環境失敗、但使用者 profile 下成功 → 回報 `unsupported: needs_profile_state`(錄製 v1 不支援這類任務;Claude 可改用手寫流程並照一般流程驗證)。
- `dry_run` 對 `recorded_from` 配方:把配方以 params **渲染後的動作值與網址**(url、每個 field 值、點擊目標)和錄製的示範動作逐一比對;全部相同 → 這是**示範值試跑**,做示範一致比較並寫入 dry-run 紀錄:
  `{recipe_hash, recording_digest, rendered_actions_hash, comparator, match, diff}`。
  - `rows-exact-v1`:canonical raw cells(未套 columns),群組總列數相同、逐格正規化文字相同;任一方截斷或為空 → `match: false`。
  - `text-contains-v1`:標記文字(正規化、非空)必須完整出現在重播後頁面文字中。
  - 不一致不放寬;若因資料本身在變動(價格、名額)而無法一致 → 回報「此任務的結果會變動,錄製暫不支援」,**不要求無限重錄**。
- `save_recipe` 對 `recorded_from` 配方要求:
  (a) 同 `recipe_hash`、同 `recording_digest` 的示範值試跑 `match: true`;
  (b) 若配方有 params:同 `recipe_hash`、**`rendered_actions_hash` 不同**的一次試跑通過(參數確實改變了實際動作,不是塞一個沒用的參數);沒有 params 則免;
  (c) rows 的 `columns` 已填且合法(是否經使用者確認屬建立流程的確認步驟,不由程式宣稱);
  (d) 錄製存在且 `completed`,digest 相符;
  (e) (a)(b) 兩筆試跑都在隔離瀏覽器環境執行(dry-run 紀錄帶 `isolated: true`)。
- 修復換新錄製:`recorded_from` 改為新 id,重新滿足 (a)–(d)。

### 7.5 確認規則(R24、M06)

- 使用者自己說「我示範給你看/開始錄」→ 已授權,直接開錄。Claude 主動提議 → 先問,對方同意才開錄。
- 建立新流程:存檔前給使用者確認結果(照舊)。修復:照 DECISIONS「修好再回報」,不再確認,但 7.4 證據仍必須滿足。

## 8. 工作包(依賴關係;每包:`uv run pytest -q` 綠、`uvx pyright` 0 errors;標 Chrome 的包另外跑整合套件並貼出指令與 Chrome 版本)

整合測試環境(M04):**在 import `kfw` 之前**設 `KFW_HOME`=暫存資料夾、`KFW_CDP=http://127.0.0.1:9444`;測試自己以 `--user-data-dir=<暫存>` 啟動 Chrome,並核對 `:9444` 的 `/json/version` 屬於這個實例(啟動時記下的 browser ID)。
絕不碰使用者的 `:9333` 與 `~/.kav-fastweb`。跨 site fixture:測試 Chrome 以 `--host-resolver-rules="MAP a.test 127.0.0.1, MAP b.test 127.0.0.1"` 啟動,fixture 伺服器分別以 `http://a.test:<port>`、`http://b.test:<port>` 存取(V01)。
以 `@pytest.mark.chrome` 標記,`KFW_CHROME_TESTS=1` 才跑。

| WP | 依賴 | 內容 | 驗收 |
|---|---|---|---|
| **WP-S** spike | — | 最小 recorder(isolated world binding、新文件注入、hello/arm、最小提示列);分列**同 origin / 跨 origin 同 site / 跨 site(a.test→b.test)**、reload、SPA、BFCache(確認真的 persisted 恢復,沒進 BFCache 記「未覆蓋」)、三種 CSP(提示列可見、可按、可 teardown);主世界呼叫 binding;`autoAttach` 是否需要 | `docs/design/demo-recording.spike.md`:每情境的 target/session/frame/context 與事件順序;不確定就寫「未驗證」。不進產品程式 |
| **WP0a** CDP | — | 2.1 | 單元:listener 內 send 不死鎖、listener 例外不殺 reader、斷線喚醒 pending 且之後 send 立即失敗、recv 逾時不算斷線、off |
| **WP0b** 觀察 | — | 3.1、5.1、5.2、5.3 | Chrome 等價 fixture:改版前後 `controls()`、`rows()` 對同一批頁面輸出相同(表格空格、巢狀列、重名、optional 重名、DOM 替換後的 stale control);群組歧義;真站 `thsr-timetable`、`bot-fx-rates` 各跑一次仍 done |
| **WP0c** 安全 | WP0b | 第 4 節 gate、規則 JSON、接到 `form_submit` 的 pre/fill/select/submit | 單元 + Chrome:Python/JS 同批輸入同判定;`form_submit` 帶 stateful 被 validate 拒絕;`steps` 未帶 `allow_stateful` 時 stateful 步驟輸入派發 0 次(steps 部分於 WP3 驗);`payment history` 不擋、`Pay now` 擋;form 含密碼的「繼續」擋;外置 `form=` 屬性關聯的按鈕;無文字按鈕;`stateful` 缺標被擋;**經真實 form_submit 路徑,被拒動作沒有派發任何輸入事件** |
| **WP1** 錄製器 | WP-S、WP0a、WP0b、WP0c | 2.2、2.3、3.2、3.3、4(錄製端)、7.1(不含 to_draft) | Chrome:單次打字、paste、IME(`Input.imeSetComposition`)、一次送出的多事件各成**一個**動作組;假 payload(主世界、錯 token、跳號)被丟;新分頁/iframe/自訂元素 → incomplete;blocked 原子收尾;收束屏障;重複 stop;teardown 無殘留;標記模式下網站 pointerdown/Enter 計數為 0 |
| **WP2** 轉換與證據 | WP1 | 7.2、7.3、7.4、5.3 | 單元:吸收/不吸收、via_widget、dependent_reset、from_default、單列、兩種比較器、空結果、截斷、未用參數不算(b);Chrome:錄 → 草稿 → dry_run 示範一致 → 第二組參數 → save;兩份配方借用示範被拒;**殘留狀態負例**:示範把狀態寫進 localStorage/cookie、草稿漏掉該操作,在隔離環境重播必須不一致而不能存;示範含改狀態點擊 → unsupported |
| **WP3** steps | WP0c | 6.1、6.3 | fixture 多頁網站;負例:then_already_true、舊頁當新頁、ambiguous、gate 拒絕、stateful 缺標 |
| **WP4** next_page | WP3 | 6.2 | fixture:disabled 尾頁、absent 尾頁、end_mismatch、A→B→A 循環、loading skeleton、到上限 more_pages |
| **WP5** pick | WP3 | 6.4(含 `Judge.choice` 回傳完整分佈) | 負例齊全;Kev 門檻數據記錄 |
| **WP6** skill 與文件 | WP2(A/B/C 部分不等 WP5) | SKILL.md 路由與提議時機、`references/recording.md`、`references/steps.md`、`compare_to` 修復用法、README 三語小節、明寫 4 節的敏感資料限制 | Opus 審閱 |

之後由 Opus:重開 Claude Code 經 MCP 端到端;真實網站驗收(用示範重建高鐵,和 Claude 直接寫的數字對照;一個 steps 真實任務;一個 pick 任務);flightwake record。

## 9. 已知不做

拖拉、滑桿、畫布;iframe 內表單;網站自訂元件(A 版);新分頁;在欄位按 Enter 送出;錄製中登入;結果會變動而無法示範一致的任務;網址/頁面文字中的敏感資料偵測。

## 10. 複查處理對照

### v2 複查(V01–V12、M01–M06)

| # | 處理 | 位置 |
|---|---|---|
| V01 | 真跨 site(host-resolver-rules a.test/b.test)、三層分列、SPA/BFCache 分開、CSP 測實際 UI、未覆蓋照實寫 | 8 WP-S |
| V02 | 刪除「全部只讀」保證;gate 只拒絕已知禁止與無法判定;steps 不整段重跑;form_submit 維持既有重試不擴張 | 0.3、4、6.1 |
| V03 | 偵測改為盡力而為並列出盲點;正確性由示範一致檢查把關;加 closed root、自訂 host、iframe 不可聚焦區負例(進 WP1 測試) | 0.6、2.3 |
| V04 | 動作組 + 已提交快照差異(不在 capture 拍 before);beforeinput/paste/IME;吸收只是假設、由重播驗證;A 版拒絕自訂元件 | 3.2、7.2 |
| V05 | 提交邊界有效值全寫(含預設);dependent_reset 拒絕 | 7.2 第 3 點 |
| V06 | (b) 只對有 params 的配方、以渲染後動作 hash 判斷不同;兩種比較器、空結果不算;動態資料明確不支援 | 7.2、7.4 |
| V07 | `groups()` 回傳全部群組;live 驗證比群組指紋;純轉換器不碰瀏覽器;引擎群組歧義 → needs_help;columns 拒重複 | 3.1、5.2、5.3、7.3 |
| V08 | then 一律是轉移(點擊前為假);gone 定義;wait 純狀態;next_page 已訪指紋、明寫 end、稳定非空;steps 的 select 不用 Kev | 6.1、6.2 |
| V09 | 取消 Alt 捷徑;焦點管理;契約限定進入模式之後 | 3.3 |
| V10 | Python 配文件 ID(executionContextId)、token + 連續 seq、收束屏障、BFCache 新 epoch、重啟視為 incomplete、blocked 為 reason | 2.2 |
| V11 | 敏感值不讀、presence boolean;blocked 原子刪除只留 tombstone;其他出口誠實界定;run 不依賴錄製;discard tombstone | 4、7.1 |
| V12 | WP0 拆 a/b/c,b、c 含 Chrome 等價與「被拒動作未派發」整合測試 | 8 |
| M01 | 回覆由 reader 直接喚醒;listener 不等待 dispatcher 事件;recv 逾時不算斷線 | 2.1 |
| M02 | 先註冊 listener;JSON.stringify;忽略既有 targets、只看 page;錄製分頁 CDP 經 worker;重新 attach 視為缺口 | 2.2 |
| M03 | 英文保留詞界;Python/JS 同批輸入同判定 | 4 |
| M04 | UI 延後掛載的各種時機;測試 Chrome 身分核對 | 3.3、8 |
| M05 | pick 用候選 ID 與完整分佈 | 6.4 |
| M06 | 使用者明說即授權;WP 以依賴表示 | 7.5、8 |
| B1 | `allow_stateful` 呼叫參數為執行前授權,旗標不構成授權;錄製不產生 stateful(unsupported) | 0.8、4、6.3 |
| B2 | `form_submit` 不支援 stateful,只讀才保留既有重試 | 4 |
| B3 | 示範一致與第二組試跑在隔離瀏覽器環境(乾淨起始狀態);需要 profile 狀態 → unsupported;殘留狀態負例 | 0.6、7.4、WP2 |

### v1 複查(R01–R24)

R01–R12、R14–R24 的處理已併入上述各節(v2 對照表見 git 歷史 `f4f08a9`);R13 由使用者決定採受限例外(DECISIONS 2026-09-29),見 6.4。

## 11. 實作注意事項(v3 複查 I1–I6,實作時必須照做並寫測試)

- **I1**:文件身分用本地 epoch 對照 `uniqueContextId`(不用裸 `executionContextId`,它可能跨程序重用);舊 context 遲到的資料不得掛到新文件;屏障要涵蓋離頁前舊文件的最後一組;arm 前的輸入記為缺口(`incomplete`),不可默默丟掉;已停止的錄製在 BFCache 返回時不得恢復收集。
- **I2**:送出前先提交待定欄位組(最後一個字、blur 正規化);刻意清空的欄位不能因 fields 只收非空而消失,表達不了就 unsupported;無 label/重名/checkbox 的拒絕要回報 unsupported,不能只是從 fields 過濾掉;相依欄位至少測自動清空與延遲重設。
- **I3**:stop 實作為「純候選產生 → live 檢查 → 組合草稿」;stop 時頁面已離開 mark 所在文件 → `pending`;群組指紋由 canonical 內容計算,不用 DOM ID。
- **I4**:`rows` 的 then 是「相對點擊前指紋的轉移」,原本已有表格不算 then_already_true;disabled 尾頁檢查要能看見 disabled 控制項(現有 controls 會過濾);pick/next_page 也經 gate,且不能標 stateful → 目標需要 stateful 時拒絕。
- **I5**:`text-contains-v1` 要接通 `detail_extract` 的執行與 dry_run 成功條件(現在要求 product 或 rows);示範動作 hash 比較轉換後可執行的正規化動作;未被引用的參數不影響 hash。
- **I6**:文件如實說明 mark/demo/URL 摘要仍會交給 Claude(摘要不是脫敏);blocked 之後 stop 的截圖與 to_draft 路徑不得重新產出內容;WP3 的錄製轉換部分依賴 WP2 輸入契約,WP6 的 B/C 文件等對應能力完成。
- **I7**(v3.1 複查 1):`allow_stateful` 只屬本次呼叫,不存進配方、不從前次繼承;已標 `stateful` 的步驟即使文字沒命中詞表也受限。測:預設 false、旗標不代替授權、一次獲准後下一次省略參數仍拒絕。
- **I8**(v3.1 複查 2):每次 dry_run 各建新 BrowserContext,相關分頁都用它;失敗不得退回預設 profile 取得通過證據;`isolated: true` 由 server 依實際環境記錄;finally 清理 context。測兩趟互不繼承 storage,並拒絕缺隔離證據的紀錄。
- **I9**(v3.1 複查 3):無 params 時 (e) 只檢查 (a);修復換新錄製時 (a)–(e) 全部適用。
- **I10**(v3.1 複查 4):隔離的是瀏覽器狀態,不是伺服器交易回滾,不可宣稱為 stateful 沙箱;`needs_profile_state` 不自動改用使用者 profile 重跑;不能靠刪 `recorded_from` 避開失敗。
