---
version: 1
slug: "website-src-pages-index-astro"
primary_target: "website/src/pages/index.astro"
related_targets: ["website/src/styles/global.css","website/src/layouts/Layout.astro"]
---

# 首頁與展示網站

Mode: Persuade；技術、開始使用與證據頁為 Read。首頁目標是讓一般人理解重複查詢如何成為可重用流程；互動示意与真實記錄分開。

## Direction contract

THESIS: 把日常查詢翻成可以再用的一頁。用行程摺頁的輸入、步驟與結果連續展開，拒絕功能卡片堆疊。

OWN-WORLD: 深綠 #184f43 大色面、黃綠 #ddf391 操作與摺頁邊、灰白 #f5f7f2 紙面、墨綠 #192d28 文字。自託管 Noto Sans TC 與 Manrope；直角分區、明確的表單與結果表。

STORY: 訪客先知道常做的網頁查詢可變成流程，改條件演示重用，再看真實截圖、小樣本量測與開始使用。

FIRST VIEWPORT: 左侧大字「查過的事，下次一句話。」與用途、實際用途入口；右侧占约一半畫面的展开摺頁，站名／日期條件、可播放步驟、三列結果。深綠包住整個第一屏、黃綠承接需求。主要操作「播放流程示意」。下緣直接露出實測證據入口。Signature: 改條件後摺頁結果以 clip-path 展開，reduced-motion 下即時切換。

FORM: 台灣行程摺頁，候選第 3；seed 43c1260e。候選依序：公共資訊查詢站、日常使用指南、行程摺頁、購物明細、科學展解說、家庭行事曆、文具索引。使用者授權開始實作，代理暫採主提案；使用者尚未在方向頁選定。借鑑印樣的差異可見、訊號的狀態清晰、織造的結果可追溯、深潛的資訊分層、剪輯的證據順序。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## 使用者追加要求（2026-10-02）

首頁明確介紹示範錄製，提供標記結果的鍵盤可用互動示意，區分錄製、重播核對與確認儲存；高鐵第 1 階段已真人驗收，多步驟和示範修復仍待驗收。首頁直接解釋加速原理：重用流程減少逐步模型與工具往返，Kav 當次操作網頁並回傳具名資料；高鐵不靠 Kev 或答案快取。技術頁提供工具呼叫、配方節錄、DOM 取值與原始碼入口對照。
