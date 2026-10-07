# Kav-FastwebAgent 展示網站

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

使用者於 2026-10-02 確認沿用 Astro 靜態網站提案，獨立於 `website/`；繁中首版、預留英文，未來可部署 Cloudflare Pages。正式網域與部署專案尚未決定。

## Users

首先服務不寫程式、想理解重複網頁查詢如何變簡單的一般讀者；另設技術與 AI 可直接閱讀的入口。

## Product Purpose

讓讀者理解「這件事我也用得上」，看懂需求、實際操作、結果，以及改條件後重用流程的方式。

## Positioning

Claude 將需求寫成流程並協助修復；Kav 用專屬 Chrome 執行，程式核對結果；需要語意判斷時才使用本機 Kev。

## Capabilities and Constraints

- 使用者端稱為「流程」，內部格式為 recipe JSON。
- 首版依既有高鐵、台銀與比價案例說明功能；尚未驗收的能力明確標示範圍。
- 程式在本機執行不代表所有資料都不離開電腦；Claude 與 Kev 的職責分開說明。
- 不把首頁互動示意當成真實即時查詢，不捏造結果或能力。
- 引擎開發與驗證由另一 Claude Code session 負責；本工作線負責展示前端。
- 公開 repo 與網域尚未建立或驗證，不提供冒充可用的下載與部署連結。

## Brand Commitments

品牌標誌、頁首／頁尾與頁面標題使用完整名稱 Kav-FastwebAgent，和 GitHub repo 一致（使用者 2026-10-02 指定）。繁體中文，以容易理解的用途說明為先，使用 Impeccable 協助設計一致性。

## Evidence on Hand

產品依據為 README.md 與 .flightwake/STATE.md；歷史量測來源為 .flightwake/records/260929-control-experiment-and-demo.md 及 260929-kev-usage-accounting.md。高鐵約 5 倍僅是單站小樣本，且對照的列出班次範圍不完全相同；約 6 秒流程執行與約 22 秒整趟對話不可混算。高鐵與台銀未使用 Kev。台銀單頁讀表未顯示速度優勢。舊 GIF 有隱私待處理事項，公開前不可直接沿用。

## 展示內容要求

使用者要求首頁顯著呈現動作錄製，並解釋高鐵加速的實際機制。技術頁延伸至專案工具與程式入口；不能只用快幾倍代替原理說明。

## Product Principles

- 從讀者熟悉的需求與結果介紹機制。
- 真實證據與互動示意分開標示。
- 數字保留量測範圍與限制。
- 技術細節另設入口，讓一般讀者順暢理解。
