---
record_id: 261007-showcase-narrative
session: codex session 2026-10-07
date: 2026-10-07
repos: [Kav-test]
tests: website Playwright 10 passed; Astro check 17 files, 0 errors/warnings/hints; static build 6 pages
prod_changes: none
---

# 展示網站改為本機確定性執行，Kev 降為選配

**TL;DR**：網站仍沿用舊的本地模型敘事，這次以 README 與 DECISIONS 2026-10-07 為準更新。首頁與技術頁現在說明 agent 用對話建立、修理流程，本機程式抓取與驗證，判斷題再交給 Claude；591 數字附上各組量測範圍，既有版面與互動保留。

## 關鍵發現

1. 591 的抓取時間、判斷題與瀏覽器操作各有不同範圍，不能直接換算端到端加速倍率。展示以共用元件保持各頁一致，明列 Claude 文字組的列表版本與題數、Kev 唯一解排除字面比對的分母，以及尚未完成端到端點擊的限制。實驗權威仍是 [原始紀錄](261007-pick-judgment-experiment.md)，不在這裡重抄結果。
2. 原理圖以可讀 HTML 重畫成抓資料、程式驗證、需要判斷時交給 Claude；Kev 在補充文字中說明為選配。技術頁同時說清楚交回 Claude 並非引擎自動呼叫雲端模型，流程條件通過也不保證擷取規則完整。

## 交付 / Commits

06a0941..62c2ec2（僅 website/；收尾紀錄與 STATE 在後續 docs commit）。

## 驗證證據

- `cd website` 後分別執行 `npm run test`：10 passed（5.2 秒），涵蓋桌機／手機互動、導覽與圖片、無障礙、複製失敗、減少動態及無 JavaScript。首次啟動 Astro 背景伺服器時 Playwright webServer 提早退出；確認本機伺服器已啟動後重跑，全數通過。
- `npm run check`：17 個 Astro 檔案，0 errors、0 warnings、0 hints。
- `npm run build`：6 個靜態頁面成功；加入技術頁的實驗導覽後再次檢查與建置通過。
- Chrome 批次檢視首頁、技術頁與實驗頁，1440、800、390 像素寬皆無水平溢出，三頁均含新實驗說明，首頁原理圖順序正確。桌機／手機截圖檢視保留既有設計；Impeccable detect 與 website diff whitespace 檢查通過。
- 沒有執行或修改 kfw/ 與根目錄 tests/；引擎驗證沿用前一 Claude session 的證據。沒有部署。既有 skills/hooks、其他未提交修改均未納入。

## 未完 / 交接

- 網站待使用者成品回饋、公開入口與部署；既有建設上下文見 [CONTEXT](261002-showcase-build-CONTEXT.md)。引擎錄製第 2/3 階段、pick 點擊與修復廣度等未驗證項目留在 STATE，專案健康仍為 yellow。
