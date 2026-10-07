# 展示網站交接

## Scope

製作 Kav-FastwebAgent 對外展示與說明網站，未來提供 GitHub 對外連結。一般人能理解用途與操作，另有技術及 AI 閱讀入口。Codex 負責前端與生成圖片；另一個 Claude Code session 負責引擎與驗收，不碰其檔案或代替它宣稱測試通過。

驗收：首頁能連貫呈現一句需求、實際操作與結果，以及更換條件後重用流程；案例數字附來源及量測範圍；桌面與手機能閱讀操作；技術／AI 文件可直接讀取；build、型別與重要導覽互動檢查通過，公開素材完成隱私檢視。正式網址與 GitHub 連結須實際驗證。

本次只規劃，尚未寫網站、生成圖片、啟動 subagent 或部署。使用者指定順序：先看計畫 → 交 Claude 複驗 → 再由 Codex 開 subagent 製作。尚未收到複驗結果，不視為已允許開始製作。

## 已定案決策

見 DECISIONS 2026-10-02 展示網站條目（含 why），不另複寫。Impeccable 已由使用者安裝，安裝觀察與驗證範圍見同名 record。

## 現況與資料底座

- 產品依據：README.md、.flightwake/STATE.md、records/260930-thsr-demo-acceptance.md；數字來源再讀 records/260929-control-experiment-and-demo.md 與 records/260929-kev-usage-accounting.md。執行前 spot-check 新提交及真人驗收結果。
- 尚待確認的提案：Astro 靜態網站 + Cloudflare Pages，獨立 website/；繁中首版、預留英文；首頁、案例、運作方式、開始使用、技術、AI 入口、實測證據等路由。框架、路由及暖白／青綠視覺均非使用者定案。
- 首頁構想：以高鐵重複查詢為主，台銀為輔，比價次要；展示同一流程換日期或站名再次執行。真實示範與互動示意明確分開；生成圖片負責插畫與分享封面，實測畫面使用真實素材。
- 文案限制：約 6 秒流程執行與約 22 秒整趟對話不可混算；高鐵約 5 倍為小樣本單站對照；高鐵／台銀未使用 Kev；本機執行不等於所有資料不出電腦；錄製、修復與安裝相容性依實際驗收範圍描述。
- 公開素材及 repo 歷史已有待處理事項，見 STATE「公開 repo 前」。不要直接發布舊 GIF 或推公開歷史。
- Impeccable 方法參考已讀：核心 SKILL、shape、new-work、critique 的主要規則。尚未執行 context/init，也未建立 PRODUCT.md 或 DESIGN.md。下次以本機安裝版本為準，避免把上游變動當成本機能力。

## 下一步

1. 冷啟動後讀本文件及本機 .agents/skills/impeccable/SKILL.md；依技能執行 context，檢查安裝檔案與 hook 狀態，不覆寫 flightwake hook。
2. 確认使用者與 Claude 的複驗意見；保留已知受眾與價值方向，不重問已回答的問題。
3. 依 Impeccable 規劃流程提出首頁構圖與敘事方案供選擇；選定後才落實視覺規則。圖片製作時讀 imagegen skill。
4. 計畫確認後再開 subagent，按不同檔案分工：首頁與共用版型、案例內容、技術／AI 文件與建置；主 agent 負責圖片、共用設計與整合驗收。

## 開放問題

- 需與使用者確認：Claude 複驗結果、首頁視覺方案、首版頁面範圍及技術選型。
- 部署階段再確認正式網域與 Cloudflare 專案；帳號資訊不寫入交接。
- 安裝產物尚未提交；納入版本控制的範圍及 hooks 實際執行仍待檢查。
