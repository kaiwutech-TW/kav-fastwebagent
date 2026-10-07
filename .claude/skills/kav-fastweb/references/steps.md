# steps:多頁、多步驟的流程

適用:要點好幾頁才看得到結果、中間要選一筆、或要翻頁收集的網站。
只有一頁表單「填完按查詢」的,用 `form_submit` 就好(比較簡單,也有「送出沒反應就重跑一次」)。

## 格式

```json
{
  "type": "steps",
  "url": "https://example.com/",
  "steps": [
    {"click": "不同意", "optional": true, "then": {"gone": "不同意"}},
    {"select": "縣市", "value": "{city}"},
    {"fill": "關鍵字", "value": "{keyword}"},
    {"check": "只看有空位", "value": true},
    {"click": "查詢", "then": {"rows": true}},
    {"pick": {"rows": {"pattern": "..."}, "want": "{title}", "click": "查看"}},
    {"wait": {"text": "詳細資料"}}
  ],
  "result": {"rows": {"pattern": "...", "min_rows": 1, "columns": ["..."]}, "expect_text": ["{keyword}"]}
}
```

每一步**只能有一種動作**:`click` | `fill` | `select` | `check` | `wait` | `pick` | `next_page`。

| 動作 | 寫法與規則 |
|---|---|
| `click` | 按鈕或連結的文字(照抄 `inspect_page`)。**一定要寫 `then`**(見下)。`optional: true` 只在「找不到」時跳過;找到兩個以上同名的仍然會停 |
| `fill` | 輸入框的 label + `value`。填完會讀回確認 |
| `select` | 下拉選單的 label + `value`。只做完全相同或包含的比對,**不會讓 Kev 猜**;對不到唯一選項就停 |
| `check` | checkbox / radio 的 label + `value`(只能寫 `true` / `false`,不能用參數;radio 只能 `true`) |
| `wait` | `{"wait": {"text": "..."}}`:等頁面出現某段文字(最多 10 秒) |
| `pick` | 從列表挑一筆再點進去(見下) |
| `next_page` | 翻頁收集(見下),只能是最後一步 |

## then:點了之後「什麼會變」

`then` 必須是**點擊前不成立、點擊後才成立**的條件。點擊前就已經成立,程式會停下來回報 `then_already_true`——換一個真的會改變的條件。

| 條件 | 意思 |
|---|---|
| `{"text": "..."}` | 頁面出現這段文字 |
| `{"gone": "..."}` | 這個按鈕消失(例:同意 cookie 後橫幅不見) |
| `{"url_contains": "..."}` | 網址變成包含這段 |
| `{"field": "label"}` | 出現某個欄位(例:點「進階搜尋」後出現「出版年」) |
| `{"rows": true}` | 出現符合 `result.rows.pattern` 的結果,而且內容和點擊前不同(原本已有舊表格也可以用) |

選條件的原則:挑**這一步做對了才會出現**的東西。「頁面有變化」不夠——網站一直在動。

## pick:從列表挑一筆

```json
{"pick": {"rows": {"pattern": "...", "min_rows": 1}, "want": "{title}", "click": "查看"}}
```

- 先用文字比對 `want`(整格相同 → 包含),唯一就選。
- 文字比對不唯一時才問本機的 Kev,每一列問一次「是不是使用者要的」;**非常有把握才選**(最高 ≥ 0.8 且贏第二名 ≥ 0.3),否則回 `pick_uncertain` 並附上候選與機率——這時把 `want` 寫得更明確,或把 `rows.pattern` 收窄,不要調門檻。
- 選定那一列後,在**那一列裡**找文字為 `click` 的按鈕,必須唯一;沒有就停,不會點別的連結代替。
- 點下去之後要換頁或列表改變,否則 `pick_no_effect`。
- `want` 寫使用者的原話或關鍵名詞(例:「退費申請」),不要寫成一整段說明。

## next_page:翻頁收集

```json
{"next_page": {"click": "下一頁", "max_pages": 3, "end": "disabled"}}
```

- `max_pages`:總共收幾頁(含第一頁),1–10。
- `end`:最後一頁長什麼樣——`"disabled"`(下一頁按鈕還在但按不了)或 `"absent"`(按鈕消失)。**試跑時翻到最後一頁看截圖再決定**,不要猜。
- 到 `max_pages` 還沒到最後一頁,結果會帶 `more_pages: true`。回報時要說「已收集前 N 頁,還有更多」,不能說全部。
- `result.rows.min_rows` 每一頁都要滿足,**最後一頁常常只剩幾筆,設 1**。
- 內容和之前某一頁一樣(兜圈子)會停下,回 `partial`。

## 改變網站狀態的步驟(加入購物車、收藏、預約…)

- 只有使用者**明確要求**這個動作時才寫,該步加 `"stateful": true`。
- 執行(`run_recipe` / `dry_run`)時要帶 `allow_stateful: true`,而且**只在使用者要求過這個動作時才帶**:本次對話中要求過,或這個流程是應使用者要求建立、使用者現在點名要跑它。`dry_run` 也是真的執行,同樣適用。
- 付款、結帳、下單、登入、註冊、填密碼或卡號:永遠不做,程式也會拒絕。
- `form_submit` 不支援改狀態的動作。
- steps 流程**不會自動重跑**:中途失敗就回報第幾步、為什麼,附截圖。

## 常見 needs_help

| reason | 意思與做法 |
|---|---|
| `then_already_true` | then 條件點擊前就成立,換一個會改變的條件 |
| `step_failed` | 看 `step_index`、`why`、截圖;是 label 對不上就修那一步 |
| `pick_uncertain` / `pick_no_candidate` / `pick_no_control` | 見上面 pick |
| `end_mismatch` | 最後一頁的樣子跟 `end` 寫的不一樣,看截圖改 `end` |
| `result_ambiguous` | 頁面上有兩個以上同樣符合的列表,把 pattern 寫得更專一 |
| `rows_skipped` > 0(done 也會附 `note`) | 同一個列表裡有列不符 pattern,被漏掉:pattern 寫得太窄,改成只鎖每列一定有的錨再跑;pick 的候選同樣會少這幾列 |
| `unsafe_action` / `stateful_not_authorized` | 見上面「改變網站狀態的步驟」;不要為了通過而加 stateful 或 allow_stateful |
