# Kav 展示網站

獨立 Astro 靜態網站。繁中首頁、流程互動示意、如何運作、實測紀錄、開始使用、技術說明與 AI 純文字入口。

```sh
cd website
npm ci
npm run dev
```

本機預設網址為 http://127.0.0.1:4321/。

```sh
npm run check
npm test
npm run build
```

瀏覽器測試使用本機 Google Chrome；涵蓋桌面與手機、站名錯誤、示意結果更新、導覽及圖片、axe 無障礙、剪貼簿成功與拒絕、減少動態和關閉 JavaScript。

`dist/` 是可部署產物。Cloudflare Pages 可設定 root directory 為 `website`、build command 為 `npm run build`、output directory 為 `dist`；本次未部署，正式網域尚未設定。依 package lock 使用 Node 22.12 以上的相容版本。

產品依據在根目錄 PRODUCT.md；視覺規則在 DESIGN.md。首頁互動不連線查高鐵，所有變體均標示為示意；真實截圖與量測來源在實測頁，不能把示意速度當成 benchmark。

公開 GitHub 入口準備好且驗證後，再更新開始使用頁的下載入口。不要直接發布含私人資訊的歷史 GIF。本站只採用兩張已檢視的公開網頁歷史截圖，原始來源以 JPEG comment 記錄。
