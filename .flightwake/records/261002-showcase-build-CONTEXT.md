# 展示網站接續

## Scope

Astro 展示網站首版已實作於 `website/`。Codex 負責前端；引擎與真人驗證由另一 Claude Code session 處理。下一輪以使用者看成品後的回饋為準；部署與公開 repo 尚未進行。

驗收：首頁可換條件播放流程示意、標記錄製結果；一般讀者看得懂加速機制；技術頁能對回工具和程式入口；桌面與手機無溢出，型別檢查、瀏覽器測試與 build 通過。證據見同名 record。

## 已定案決策

技術、code-first 與首頁需包含錄製／原理的原因見 DECISIONS 2026-10-02。深綠、黃綠行程摺頁是已做成可預覽成品的主提案，尚未得到使用者對視覺的最終確認；不重問已確認的 Astro 與 code-first。

## 現況與資料底座

- 根目錄 PRODUCT.md、DESIGN.md 與 .impeccable/design.json 為產品／設計入口，首頁策略在 .impeccable/surfaces/website-src-pages-index-astro.md。
- 啟動與驗證指令見 website/README.md。本機開發預覽使用 4321 埠；若停了，在 website/ 執行 npm run dev。
- 頁面：首頁、how-it-works、evidence、get-started、technical、404，以及 llms.txt、evidence-notes.txt。
- 錄製元件 RecordingDemo.astro 是標記教學；Mechanism.astro 解釋減少逐步模型往返；technical 的 fast-path 以實際配方與程式入口說明。
- 互動全部是明示的前端示意，沒有呼叫真實高鐵或錄製引擎；真實證據只有兩張歷史網頁截圖與記錄摘要。
- 使用者強調：不能只說快，要說明 Claude 為何能快拿到資料。高鐵重用流程包住多步操作、DOM 擷取與具名回傳；實測不使用 Kev，也不是答案快取。
- Impeccable 自動 hook 狀態與本輪人工檢查結果見 record；既有安裝產物尚未納入此工作線。

## 下一步

1. 先開本機首頁，依使用者回饋調整視覺、錄製段落與原理說明；修改後只跑相應前端檢查。
2. 引擎驗收結果若更新，先核對最新 STATE／record，再更新 evidence 和公開說明。不要替 Claude session 宣稱已驗證。
3. 真正準備發布時，再驗證公開 GitHub 入口與正式網域，處理 STATE 的歷史 GIF 隱私事項，然後部署；不直接把整個 repo 或 .flightwake 當作靜態網站發布。

## 開放問題

- 需與使用者確認：對目前成品視覺／內容的回饋。
- 發布時需確認：正式網域、Cloudflare 專案、公開 GitHub 入口；目前只有本機成品。
