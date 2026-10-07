# demo-recording v3.1 複查

審查對象：`c727fab` 的 `docs/design/demo-recording.md`。本輪只核對 B1、B2、B3 及修法新增的阻擋風險，未重審其他設計，也未審查正在進行的 WP-S／WP0a／WP0b 實作。

**結論：B1–B3 可關閉，未發現本次修法引入新的阻擋問題，APPROVE。** 這是設計核准，實作仍須通過文件所列驗收；本次未執行產品測試。

| 項目 | 判定 | 依據 |
|---|---|---|
| B1：stateful 執行前授權 | 關閉 | 原則 8、§4（130–132 行）要求每次 `run_recipe`／`dry_run` 明確帶 `allow_stateful`，預設 false，且只有既有使用者明確要求才可傳 true。配方旗標不再等同授權。§6.3（202 行）將錄製中的改狀態點擊直接列為 unsupported，避免自動生成後為取得兩組試跑證據而重複執行。 |
| B2：form_submit 重複副作用 | 關閉 | §4（133–134 行）明定 form_submit 不支援 stateful：validate 拒絕旗標，執行時 gate 仍拒絕改狀態目標。這類操作只能走不整段重跑的 steps，已消除上一版 stateful pre 被再次執行的路徑。 |
| B3：示範殘留狀態造成假通過 | 關閉，限新宣告的錄製範圍 | 原則 6、§7.4（262–275 行）要求每次錄製配方 dry_run 使用新的 BrowserContext，不攜帶示範 cookie／storage／登入狀態；save 同時要求隔離試跑證據。依賴示範 profile 的任務明確不支援，WP2 加入殘留狀態負例。這足以處理前輪指出的 profile 污染反例，不再拿同一份示範後狀態直接證明重播成功。 |

`Target.createBrowserContext` 建立空的、類似無痕 profile 的環境，適合這次限定的隔離目的；`disposeBrowserContext` 會關閉其所屬頁面。[CDP Target 官方定義](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)

以下可在實作與測試中處理，不需再等一輪設計核准：

1. **授權只屬本次呼叫。** `allow_stateful` 不得存成 recipe 的永久許可，也不得從前次呼叫繼承。已標 `stateful: true` 的步驟，即使當下文字未命中詞表，仍受原則 8 的呼叫授權限制。已有明確要求可沿用其授權範圍，不必重問；但一次執行的要求不能被默認擴張為任意次試跑。驗收至少測 default false、旗標不能代替授權，以及一次獲准後下一次省略參數仍拒絕。
2. **隔離必須落在真實執行路徑。** 每次 dry_run 各建新 context，所有相關分頁建立都傳入其 ID；失敗時不得退回預設 profile 繼續取得通過證據。`isolated: true` 由 server 根據實際執行環境記錄，不能信呼叫端自報。完成截圖與結果取證後，在 finally 清理 context。測試兩趟互不繼承 storage，並拒絕缺少隔離證據的紀錄。
3. **§7.4 的兩個小文字不一致依總規則實作。** 無 params 時，(b) 已明定免除，因此 (e) 只檢查必要的 (a)，不要硬要求第二筆。修復段落仍寫「(a)–(d)」，但 save 的 (e) 與 §7.5 的全部證據要求仍適用；修復不得略過隔離檢查。
4. **保持隔離證據的範圍。** 新 context 隔離的是瀏覽器狀態，不是網站伺服器的交易回滾機制；不要把它宣稱為 stateful 試跑沙箱。`needs_profile_state` 也不應觸發自動切回使用者 profile 重跑以求成功。錄製草稿不能只刪 `recorded_from` 來避開失敗；改用手寫流程時仍須重新建立有效動作與完成證據。

WP-S、WP0a、WP0b 可繼續；本次核准不要求回退或暫停這些工作。本輪只新增此審查檔，未修改程式或設計。

VERDICT: APPROVE
