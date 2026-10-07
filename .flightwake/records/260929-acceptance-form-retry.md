---
record_id: 260929-acceptance-form-retry
session: claude-code 2026-09-29(第二個 session:驗收)
date: 2026-09-29
repos: [Kav-test]
tests: 98 passed / pyright 0 errors
prod_changes: none(全部在本機)
---
<!-- flightwake record — 飛行紀錄。 -->

# 在真的 Claude Code session 驗收 Kav-FastwebAgent;修 form_submit「送出沒反應」的漏洞

**TL;DR**:上一個 session 只用腳本模擬過 MCP client。這次在重開後的 Claude Code 裡用自然語言下兩題,
skill 觸發 → `find_recipe` → `run_recipe` 都走得通。但高鐵配方第一趟失敗一次:表單填好了,按下查詢卻沒反應,
而且程式看不出原因。這次補上兩件事:把頁面的就緒狀態記進 steps,以及「送出沒反應就重新載入、重跑一次」。
原本那次失敗之後沒再重現,所以這個修法還沒被真實的失敗驗證過。

## 關鍵發現(依重要性排序)

1. **網路靜止不代表頁面可以操作了。** 高鐵那次失敗的截圖裡,下拉選單還沒被 JS 套上樣式,查詢鈕是淡色;
   四個欄位讀回的值卻都正確,程式只能等 12 秒後回報 `result_not_proven`。
   原本的 `wait_ready` 就算等到上限也照樣往下跑,結果也沒被檢查。
   → TRAPS `form-submit-fills-half-initialized-page`(suspected)。DECISIONS 2026-09-29:
   選擇「檢查送出後有沒有反應」,不讓配方宣告 ready 條件,也不只靠網路靜止。
2. **少了 `pre: 不同意` 不是頁面沒載完的證據。** 一開始我這樣推論,後來發現頁面正常時也會略過這一步。
   cookie 對話框有沒有出現,取決於 profile 裡有沒有存過同意設定。已在上面那條 trap 裡更正。
3. **高鐵配方不需要 Kev。** 四個欄位都是精確比對,Kev 沒開也能跑;只有比價要用到 Kev。
4. **直接跑 `pytest` 會收集到 `vendor/`**(Kev 的原始碼,不進 git):裡面的測試在收集階段就結束程式,整個測試中斷。
   已設定 `testpaths = ["tests"]`。

## 交付 / Commits

6eea579

## 驗證證據

- 驗收(走 MCP,真的 Claude Code session):
  - 「查 10/5 台北到左營早上 8 點的高鐵」:第 1 趟 `result_not_proven`;接下來熱跑和關掉 Kav Chrome 後的冷跑都 `done`,5 班,約 6.2 秒。
  - 「比 AirPods Pro 3 哪裡最便宜」:`done`,最低價酷澎 $6,475,商品頁 JSON-LD 驗證通過,四站並行 6.8 秒。
  - 截圖:`~/.kav-fastweb/runs/260929-111204-1012`(失敗)、`260929-111239-1955`、`260929-111300-d5cf`、`260929-111350/`(比價)。
- 新的 form_submit(直接呼叫引擎,真的 Chrome):
  - 本機假頁面「第一次載入時按鈕沒反應」:第 1 次 `effect: null`(等 2.0 秒)→ 重新載入 → 第 2 次 `effect: dom` → `done`,共 3.9 秒。
  - 本機假頁面「按鈕正常」:沒有重試,`done`,1.3 秒。
  - 本機假頁面「按鈕永遠沒反應」:重試後回報 `result_not_proven`,17.7 秒。
  - 高鐵官網連跑 2 次:都是 `done`,`effect: request`,5.7–6.5 秒。
- 單元測試:`submit_effect` 的 7 種情況;總計 98 passed、pyright 0 errors。

## 未完 / 交接

- 正在跑的 kav-fastweb MCP server 是舊程式碼,要重開 Claude Code 才會載入 6eea579。
- 下次 steps 裡出現 `retry` 時,看它有沒有把失敗接住,再依結果升級或修正那條 trap。其他未完項目見 STATE。
